"""DataUpdateCoordinator: stream-parse NDW gzip DATEX II feeds with conditional HTTP."""

from __future__ import annotations

import copy
import logging
import os
import re
import zlib
from datetime import datetime, timedelta
from typing import Any
from xml.etree.ElementTree import XMLPullParser

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .cache import NDWCache
from .const import (
    CONF_SEARCH_TERMS,
    DOMAIN,
    FEED_CLOSURES,
    FEED_PLANNED,
)

_LOGGER = logging.getLogger(__name__)

# Whole-value noise only. Longer free-text that starts with these words is kept.
_GENERIC_LABEL_RE = re.compile(
    r"^(beperking|omleiding|afsluiting|volg route|geen gevolgen|doorgang|"
    r"verkeersbelemmering|werkzaamheden|tijdens|let op|ja,? alleen)\b"
    r"(\s*\d+)?\s*$",
    re.IGNORECASE,
)
_MUNICIPALITY_RE = re.compile(
    r"^(gemeente|provincie)\s+.+$",
    re.IGNORECASE,
)
_CONTACT_RE = re.compile(r"^contact(informatie|persoon)\b", re.IGNORECASE)
_ROADISH_RE = re.compile(
    r"\b(straat|laan|weg|plein|singel|dijk|kade|steeg|gracht|allee|"
    r"boulevard|baan|route|toerit|afrit|a[\s-]?\d{1,3}|n[\s-]?\d{1,3}|"
    r"s[\s-]?\d{1,3})\b",
    re.IGNORECASE,
)
_MGMT_TYPE_LABELS = {
    "carriagewayClosures": "Rijbaanafsluiting",
    "laneClosures": "Rijstrookafsluiting",
    "roadClosures": "Wegafsluiting",
    "intermittentCarriagewayClosures": "Periodieke rijbaanafsluiting",
    "useOfSpecifiedLanesOrCarriagewaysAllowed": "Gedeeltelijk open",
}
# Prefer these record types when choosing the situation "type" shown in HA.
_TYPE_PRIORITY = {
    "RoadOrCarriagewayOrLaneManagement": 50,
    "ReroutingManagement": 40,
    "SpeedManagement": 30,
    "MaintenanceWorks": 20,
    "PublicEvent": 20,
    "ConstructionWorks": 20,
}
# DATEX tags that often hold a human street / junction / area name.
_LOCATION_TAGS = frozenset(
    {
        "roadOrJunctionNumber",
        "roadName",
        "roadNumber",
        "locationDescriptor",
        "locationName",
        "junctionName",
        "namedArea",
        "areaName",
        "alertCLocationName",
        "tpegDescriptor",
        "descriptor",
    }
)
_PARENT_ID_RE = re.compile(
    r"^(NDW03_\d+|RWS01_[A-Z0-9]+(?:_[A-Z0-9]+)?)",
    re.IGNORECASE,
)
_XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _is_noise_value(text: str) -> bool:
    tl = text.lower().strip()
    if not tl:
        return True
    if ".pdf" in tl or "verkeersbesluit" in tl:
        return True
    if _CONTACT_RE.match(tl):
        return True
    if _GENERIC_LABEL_RE.match(tl):
        return True
    return False


def _looks_like_location(text: str) -> bool:
    if _MUNICIPALITY_RE.match(text.strip()):
        return False
    if _is_noise_value(text):
        return False
    if _ROADISH_RE.search(text):
        return True
    return len(text.strip()) >= 8 and " " in text.strip()


def _parse_dt(iso_or_display: str) -> datetime | None:
    if not iso_or_display or iso_or_display == "Onbekend":
        return None
    try:
        return datetime.fromisoformat(iso_or_display.replace("Z", "+00:00"))
    except Exception:
        return None


def _minute_key(iso_or_display: str) -> str:
    dt = _parse_dt(iso_or_display)
    if dt is not None:
        return dt.strftime("%Y-%m-%dT%H:%M")
    return (iso_or_display or "")[:16]


def _format_dt(iso_or_display: str) -> str:
    dt = _parse_dt(iso_or_display)
    if dt is not None:
        return dt.strftime("%d-%m-%Y %H:%M")
    return iso_or_display or "Onbekend"


def _situation_group_id(situation_id: str, record_id: str, creation_ref: str) -> str:
    """Stable event id: parent NDW03/RWS situation, not every RSC/DET/NDW18 clone."""
    for raw in (creation_ref, record_id, situation_id):
        if not raw:
            continue
        cleaned = raw.replace("_SIT", "").replace("_WWA", "")
        match = _PARENT_ID_RE.match(cleaned)
        if match:
            return match.group(1)
    sid = (situation_id or record_id or "onbekend").replace("_SIT", "")
    parts = sid.split("_")
    if len(parts) >= 2 and parts[0] in {"NDW03", "NDW18", "RWS01"}:
        return "_".join(parts[:2])
    return sid


def _first_poslist_pair(text: str) -> tuple[str, str] | None:
    nums = text.split()
    if len(nums) >= 2:
        try:
            float(nums[0])
            float(nums[1])
            return nums[0], nums[1]
        except ValueError:
            return None
    return None


def _pick_location(from_tags: list[str], candidates: list[str]) -> str:
    if from_tags:
        return from_tags[0]
    if not candidates:
        return ""
    roadish = [c for c in candidates if _ROADISH_RE.search(c)]
    pool = roadish or candidates
    return min(pool, key=len)


def _pick_type(types: list[str]) -> str:
    if not types:
        return "Verkeershinder"
    return max(types, key=lambda t: _TYPE_PRIORITY.get(t, 0))


class NDWVerkeerCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, config_entry):
        self.hass = hass
        self.instance_name = config_entry.data["instance_name"]
        raw_terms = config_entry.options.get(
            CONF_SEARCH_TERMS, config_entry.data.get(CONF_SEARCH_TERMS, "")
        )
        self.search_terms = [
            term.strip().lower() for term in raw_terms.split(",") if term.strip()
        ]
        self.feeds = [FEED_CLOSURES, FEED_PLANNED]
        self.cache = NDWCache(hass, self.instance_name)
        self.last_data: list[dict[str, Any]] = []
        self._feed_state: dict[str, Any] = {}
        self.error_count = 0
        self.last_update_success_timestamp = None
        self._is_first_run = True
        scan_interval = config_entry.options.get("scan_interval", 18000)
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=scan_interval)
        )

    def _write_debug_file_sync(self, debug_path, content):
        try:
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            _LOGGER.error("Kon NDW debug file niet wegschrijven: %s", e)

    def _clear_debug_file_sync(self, debug_path):
        if os.path.exists(debug_path):
            try:
                os.remove(debug_path)
            except Exception:
                pass

    def _extract_situation_elem(self, sit_elem, now: datetime) -> dict[str, Any] | None:
        """Fold every situationRecord under one <situation> into a single dict."""
        situation_id = sit_elem.attrib.get("id", "")
        severity = ""
        record_types: list[str] = []
        management_type = ""
        start_time = "Onbekend"
        end_time = "Onbekend"
        value_texts: list[str] = []
        location_from_tags: list[str] = []
        municipality = ""
        latitude: str | None = None
        longitude: str | None = None
        creation_refs: list[str] = []
        record_ids: list[str] = []

        for child in sit_elem.iter():
            tag_name = _local_tag(child.tag)
            text_val = (child.text or "").strip()

            if tag_name == "situationRecord":
                rec_id = child.attrib.get("id", "")
                if rec_id:
                    record_ids.append(rec_id)
                xsi = child.attrib.get(_XSI_TYPE, "")
                if xsi:
                    record_types.append(xsi.split(":")[-1])
                continue

            if not text_val:
                continue

            if tag_name == "overallSeverity" and not severity:
                severity = text_val
            elif tag_name == "situationRecordCreationReference":
                creation_refs.append(text_val)
            elif tag_name == "overallStartTime":
                # Keep the earliest planned start (skip NDW18 "created just now" if we
                # already have a real window — handled after the loop).
                if start_time == "Onbekend":
                    start_time = text_val
                else:
                    cur, nxt = _parse_dt(start_time), _parse_dt(text_val)
                    if cur and nxt and nxt < cur:
                        start_time = text_val
            elif tag_name == "overallEndTime":
                if end_time == "Onbekend":
                    end_time = text_val
                else:
                    cur, nxt = _parse_dt(end_time), _parse_dt(text_val)
                    if cur and nxt and nxt > cur:
                        end_time = text_val
            elif tag_name == "latitude" and latitude is None:
                latitude = text_val
            elif tag_name == "longitude" and longitude is None:
                longitude = text_val
            elif tag_name == "posList" and latitude is None:
                pair = _first_poslist_pair(text_val)
                if pair:
                    latitude, longitude = pair
            elif tag_name == "roadOrCarriagewayOrLaneManagementType":
                if not management_type or text_val == "carriagewayClosures":
                    management_type = text_val
            elif tag_name in _LOCATION_TAGS:
                if text_val not in location_from_tags and not _is_noise_value(text_val):
                    if text_val.lower() not in {
                        "maincarriageway",
                        "inboundcarriageway",
                        "outboundcarriageway",
                    }:
                        location_from_tags.append(text_val)
            elif tag_name == "causeType":
                # A closure caused by a festival is still an event.
                if text_val == "publicEvent" and "PublicEvent" not in record_types:
                    record_types.append("PublicEvent")
            elif tag_name == "value":
                if text_val not in value_texts:
                    value_texts.append(text_val)

        if end_time != "Onbekend":
            end_dt = _parse_dt(end_time)
            if end_dt is not None and end_dt < now:
                return None

        group_id = _situation_group_id(
            situation_id,
            record_ids[0] if record_ids else "",
            creation_refs[0] if creation_refs else "",
        )

        description_parts: list[str] = []
        location_candidates: list[str] = list(location_from_tags)
        for text_val in value_texts:
            if _MUNICIPALITY_RE.match(text_val):
                if not municipality:
                    municipality = text_val
                continue
            if _is_noise_value(text_val):
                continue
            if _looks_like_location(text_val) and text_val not in location_candidates:
                if _ROADISH_RE.search(text_val) or not location_from_tags:
                    location_candidates.append(text_val)
            if text_val not in description_parts:
                description_parts.append(text_val)

        location = _pick_location(location_from_tags, location_candidates)
        narrative = [
            p
            for p in description_parts
            if p != location and not _MUNICIPALITY_RE.match(p)
        ]
        unique_types = list(dict.fromkeys(record_types))
        type_hinder = _pick_type(unique_types)
        if not narrative and management_type:
            narrative.append(_MGMT_TYPE_LABELS.get(management_type, management_type))
        if severity and narrative:
            # Keep severity visible without inventing a new attribute the sensor
            # does not read. Prefix only when it is not already in the text.
            joined = " - ".join(narrative)
            if severity.lower() not in joined.lower():
                prefix = _MGMT_TYPE_LABELS.get(management_type, "")
                if prefix and not joined.lower().startswith(prefix.lower()):
                    final_desc = f"{prefix}: {severity} - {joined}"
                else:
                    final_desc = f"{severity} - {joined}"
            else:
                final_desc = joined
        else:
            final_desc = (
                " - ".join(narrative)
                if narrative
                else (municipality or "Geen details beschikbaar")
            )

        haystack = " ".join(
            filter(
                None,
                [
                    final_desc,
                    location,
                    municipality,
                    type_hinder,
                    *unique_types,
                    group_id,
                ],
            )
        ).lower()
        if self.search_terms and not any(
            term in haystack for term in self.search_terms
        ):
            return None

        item: dict[str, Any] = {
            "id": group_id,
            "type": type_hinder,
            "types": unique_types,
            "start": start_time,
            "end": end_time,
            "description": final_desc,
            "location": location,
            "municipality": municipality,
        }
        if latitude is not None and longitude is not None:
            item["latitude"] = latitude
            item["longitude"] = longitude
        return item

    def _merge_into(
        self, bucket: dict[str, dict[str, Any]], parsed: dict[str, Any]
    ) -> None:
        base_id = parsed["id"]
        if base_id not in bucket:
            bucket[base_id] = parsed
            return
        prev = bucket[base_id]

        def _richer(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
            score_a = len(a.get("location") or "") + len(a.get("description") or "")
            score_b = len(b.get("location") or "") + len(b.get("description") or "")
            winner = b if score_b > score_a else a
            loser = a if winner is b else b
            # Fill blanks from the other record (NDW18 geometry + NDW03 text).
            for key in ("location", "municipality", "latitude", "longitude"):
                if not winner.get(key) and loser.get(key):
                    winner[key] = loser[key]
            # Widest time window.
            for key, pick in (("start", min), ("end", max)):
                da, db = _parse_dt(winner.get(key, "")), _parse_dt(loser.get(key, ""))
                if da and db:
                    chosen = pick(da, db)
                    winner[key] = chosen.isoformat()
                elif not da and db:
                    winner[key] = loser[key]
            if _TYPE_PRIORITY.get(loser.get("type", ""), 0) > _TYPE_PRIORITY.get(
                winner.get("type", ""), 0
            ):
                winner["type"] = loser["type"]
            merged_types = list(
                dict.fromkeys(
                    list(winner.get("types") or []) + list(loser.get("types") or [])
                )
            )
            if winner.get("type") and winner["type"] not in merged_types:
                merged_types.insert(0, winner["type"])
            winner["types"] = merged_types
            return winner

        bucket[base_id] = _richer(prev, parsed)

    async def _parse_feed_response(self, response) -> dict[str, dict[str, Any]]:
        """Stream-decompress and pull-parse a gzip DATEX II SituationPublication."""
        parser = XMLPullParser(["end"])
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        now = dt_util.utcnow()
        situations: dict[str, dict[str, Any]] = {}

        async for chunk in response.content.iter_chunked(64 * 1024):
            uncompressed_chunk = decompressor.decompress(chunk)
            if uncompressed_chunk:
                parser.feed(uncompressed_chunk)
            for _event, elem in parser.read_events():
                tag = _local_tag(elem.tag)
                if tag != "situation":
                    continue
                parsed = self._extract_situation_elem(elem, now)
                elem.clear()
                if parsed is None:
                    continue
                self._merge_into(situations, parsed)

        leftover = decompressor.flush()
        if leftover:
            parser.feed(leftover)
        parser.close()
        for _event, elem in parser.read_events():
            if _local_tag(elem.tag) != "situation":
                continue
            parsed = self._extract_situation_elem(elem, now)
            elem.clear()
            if parsed is None:
                continue
            self._merge_into(situations, parsed)

        return situations

    def _merge_and_format(
        self, all_situations: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        unique_desc_situations: dict[str, dict[str, Any]] = {}
        for sit in all_situations.values():
            loc = (sit.get("location") or "").strip().lower()
            desc = (sit.get("description") or "").strip().lower()
            muni = (sit.get("municipality") or "").strip().lower()
            start_m = _minute_key(sit.get("start", ""))
            end_m = _minute_key(sit.get("end", ""))
            unique_key = f"{sit.get('id', '')}|{loc}|{desc}|{muni}|{start_m}|{end_m}|{sit.get('type', '')}"
            existing = unique_desc_situations.get(unique_key)
            if existing is None:
                unique_desc_situations[unique_key] = sit
            else:
                prev_score = len(existing.get("location") or "") + len(
                    existing.get("description") or ""
                )
                new_score = len(sit.get("location") or "") + len(
                    sit.get("description") or ""
                )
                if new_score > prev_score:
                    unique_desc_situations[unique_key] = sit

        final_list = list(unique_desc_situations.values())
        final_list.sort(key=lambda x: x.get("start", ""))
        for item in final_list:
            item["start"] = _format_dt(item.get("start", "Onbekend"))
            item["end"] = _format_dt(item.get("end", "Onbekend"))
        return final_list

    async def _async_update_data(self):
        if self._is_first_run and self.last_data:
            self._is_first_run = False
            _LOGGER.debug(
                "Eerste run na opstarten: Download overgeslagen, cache gebruikt."
            )
            return self.last_data

        self._is_first_run = False
        _LOGGER.debug("NDW data streamen voor termen: %s", self.search_terms)
        session = async_get_clientsession(self.hass)
        all_situations: dict[str, dict[str, Any]] = {}
        new_feed_state: dict[str, Any] = {}
        any_fresh_body = False
        debug_log_content = (
            f"NDW VERKEER DEBUG LOG\nZoektermen: {self.search_terms}\n\n"
        )

        try:
            for feed_url in self.feeds:
                prev = self._feed_state.get(feed_url, {})
                headers: dict[str, str] = {}
                if etag := prev.get("etag"):
                    headers["If-None-Match"] = etag
                if last_mod := prev.get("last_modified"):
                    headers["If-Modified-Since"] = last_mod
                async with session.get(feed_url, headers=headers) as response:
                    if response.status == 304:
                        debug_log_content += f"{feed_url}: 304 Not Modified\n"
                        cached_sits = prev.get("situations", {})
                        if isinstance(cached_sits, dict):
                            all_situations.update(copy.deepcopy(cached_sits))
                        new_feed_state[feed_url] = prev
                        continue
                    if response.status != 200:
                        debug_log_content += (
                            f"{feed_url}: HTTP {response.status} (skip)\n"
                        )
                        _LOGGER.warning(
                            "NDW feed %s returned HTTP %s", feed_url, response.status
                        )
                        cached_sits = prev.get("situations", {})
                        if isinstance(cached_sits, dict):
                            all_situations.update(copy.deepcopy(cached_sits))
                        if prev:
                            new_feed_state[feed_url] = prev
                        continue
                    any_fresh_body = True
                    feed_situations = await self._parse_feed_response(response)
                    all_situations.update(feed_situations)
                    new_feed_state[feed_url] = {
                        "etag": response.headers.get("ETag"),
                        "last_modified": response.headers.get("Last-Modified"),
                        "situations": feed_situations,
                    }
                    debug_log_content += (
                        f"{feed_url}: 200 OK, {len(feed_situations)} matches\n"
                    )

            if not any_fresh_body and self.last_data and not all_situations:
                debug_log_content += "Geen verse bodies; last_data hergebruikt.\n"
                self.error_count = 0
                self.last_update_success_timestamp = dt_util.utcnow()
                await self._write_debug(debug_log_content)
                return self.last_data

            final_list = self._merge_and_format(all_situations)
            self.last_data = final_list
            self._feed_state = new_feed_state
            await self.hass.async_add_executor_job(
                lambda: self.cache.save_cache(
                    final_list,
                    feed_state=new_feed_state,
                    search_terms=self.search_terms,
                )
            )
            self.error_count = 0
            self.last_update_success_timestamp = dt_util.utcnow()
            debug_log_content += f"SUCCES: {len(final_list)} records.\n"
            await self._write_debug(debug_log_content)
            return self.last_data
        except Exception as err:
            self.error_count += 1
            _LOGGER.error("Update mislukt voor NDW: %s", err)
            return self.last_data

    async def _write_debug(self, content: str) -> None:
        current_dir = os.path.dirname(__file__)
        debug_path = os.path.join(current_dir, f"ndw_debug_{self.instance_name}.txt")
        await self.hass.async_add_executor_job(
            self._write_debug_file_sync, debug_path, content
        )

    def clear_debug_file(self):
        current_dir = os.path.dirname(__file__)
        debug_path = os.path.join(current_dir, f"ndw_debug_{self.instance_name}.txt")
        self._clear_debug_file_sync(debug_path)
