"""DataUpdateCoordinator: stream-parse NDW gzip XML feeds with conditional HTTP."""

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

# Short generic labels / noise prefixes. Softened: only drop when the *whole*
# value is a short label (or contact/pdf/verkeersbesluit). Longer free-text
# that happens to start with these words is kept for location/description.
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
    r"boulevard|baan|route|toerit|afrit|a[\s-]?\d{1,3}|n[\s-]?\d{1,3})\b",
    re.IGNORECASE,
)
_MGMT_TYPE_LABELS = {
    "carriagewayClosures": "Rijbaanafsluiting",
    "laneClosures": "Rijstrookafsluiting",
    "roadClosures": "Wegafsluiting",
    "intermittentCarriagewayClosures": "Periodieke rijbaanafsluiting",
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


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


# Work-category / equipment labels that DATEX sometimes puts in location-ish fields.
_JUNK_LOCATION_RE = re.compile(
    r"^(bouw|takel|bouw\s*/\s*takel|inspectie|markering|asfalt|"
    r"riolering|kabels?\s*(en|&)\s*leidingen|groenvoorziening|"
    r"verharding|bestrating|civiel|masten?|borden?|"
    r"werkzaamheden|onderhoud|evenement)\b",
    re.IGNORECASE,
)


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


def _normalize_location_candidate(text: str) -> str:
    """Drop empty comma parts from values like 'Bouw/Takel, ,'."""
    parts = [part.strip() for part in (text or "").split(",")]
    parts = [part for part in parts if part]
    return ", ".join(parts).strip(" ,")


def _part_is_category_junk(part: str) -> bool:
    """True for work-category labels that are not a street by themselves."""
    cleaned = (part or "").strip()
    if not cleaned:
        return True
    if _JUNK_LOCATION_RE.match(cleaned):
        return True
    if "/" in cleaned and not _ROADISH_RE.search(cleaned) and len(cleaned) <= 40:
        return True
    return False


def _polish_location(text: str) -> str:
    """Keep street/road fragments; drop category junk and empty commas.

    Examples:
    - 'Bouw/Takel, ,' -> ''
    - 'Bouw/Takel, , Coriovallumstraat BRM' -> 'Coriovallumstraat BRM'
    - 'Coriovallumstraat' -> 'Coriovallumstraat'
    """
    parts = [part.strip() for part in (text or "").split(",") if part.strip()]
    kept: list[str] = []
    for part in parts:
        if _part_is_category_junk(part) and not _ROADISH_RE.search(part):
            continue
        if _part_is_category_junk(part) and _ROADISH_RE.search(part):
            # Strip a leading category token before the first roadish word.
            match = _ROADISH_RE.search(part)
            if match:
                trimmed = part[match.start() :].strip(" -/")
                if trimmed:
                    kept.append(trimmed)
            continue
        if _MUNICIPALITY_RE.match(part) or _is_noise_value(part):
            continue
        kept.append(part)
    return ", ".join(kept).strip(" ,")


def _is_junk_location(text: str) -> bool:
    """Reject work-category labels and empty leftovers as streets."""
    cleaned = _polish_location(text)
    if not cleaned:
        return True
    if _is_noise_value(cleaned):
        return True
    if _MUNICIPALITY_RE.match(cleaned):
        return True
    if _part_is_category_junk(cleaned) and not _ROADISH_RE.search(cleaned):
        return True
    if len(cleaned) < 3:
        return True
    return False


def _looks_like_location(text: str) -> bool:
    """Heuristic: street-like place; not municipality, noise, or work category."""
    cleaned = _polish_location(text) or _normalize_location_candidate(text)
    if _is_junk_location(cleaned):
        return False
    if _ROADISH_RE.search(cleaned):
        return True
    # Allow junction-style names without street suffix only from dedicated tags.
    return False


def _minute_key(iso_or_display: str) -> str:
    """Normalize start/end to minute precision for dedupe."""
    if not iso_or_display or iso_or_display == "Onbekend":
        return iso_or_display or ""
    try:
        dt = datetime.fromisoformat(iso_or_display.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT%H:%M")
    except Exception:
        # Already formatted DD-MM-YYYY HH:MM or similar
        return iso_or_display[:16]


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
        # Start met een lege lijst; cache wordt via __init__.py op de achtergrond geladen
        self.last_data: list[dict[str, Any]] = []
        self._feed_state: dict[str, Any] = {}
        self.error_count = 0
        self.last_update_success_timestamp = None
        # Bij opstarten download overslaan als we bruikbare cache hebben
        self._is_first_run = True

        scan_interval = config_entry.options.get("scan_interval", 18000)
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=scan_interval)
        )

    def _write_debug_file_sync(self, debug_path, content):
        """Helper functie om debug file synchroon op de achtergrond weg te schrijven."""
        try:
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            _LOGGER.error("Kon NDW debug file niet wegschrijven: %s", e)

    def _clear_debug_file_sync(self, debug_path):
        """Helper functie om debug file synchroon op de achtergrond te verwijderen."""
        if os.path.exists(debug_path):
            try:
                os.remove(debug_path)
            except Exception:
                pass

    def _extract_situation(self, elem, now: datetime) -> dict[str, Any] | None:
        """Parse one situationRecord element into a filtered dict, or None."""
        record_id = elem.attrib.get("id", "onbekend")
        parts = record_id.split("_")
        base_id = "_".join(parts[:2]) if len(parts) >= 2 else record_id

        start_time = "Onbekend"
        end_time = "Onbekend"
        value_texts: list[str] = []
        location_from_tags: list[str] = []
        municipality = ""
        latitude: str | None = None
        longitude: str | None = None
        management_type = ""

        for child in elem.iter():
            tag_name = _local_tag(child.tag)
            text_val = (child.text or "").strip()
            if not text_val:
                continue

            if tag_name == "overallStartTime":
                start_time = text_val
            elif tag_name == "overallEndTime":
                end_time = text_val
            elif tag_name == "latitude" and latitude is None:
                latitude = text_val
            elif tag_name == "longitude" and longitude is None:
                longitude = text_val
            elif tag_name == "roadOrCarriagewayOrLaneManagementType":
                management_type = text_val
            elif tag_name in _LOCATION_TAGS:
                cleaned = _polish_location(text_val)
                if (
                    cleaned
                    and cleaned not in location_from_tags
                    and not _is_junk_location(cleaned)
                ):
                    # Skip pure enums stuffed into descriptor-like tags
                    if cleaned.lower() not in {
                        "maincarriageway",
                        "inboundcarriageway",
                        "outboundcarriageway",
                    }:
                        location_from_tags.append(cleaned)
            elif tag_name == "value":
                if text_val not in value_texts:
                    value_texts.append(text_val)

        if end_time != "Onbekend":
            try:
                if datetime.fromisoformat(end_time.replace("Z", "+00:00")) < now:
                    return None
            except Exception:
                pass

        type_hinder = elem.attrib.get(
            "{http://www.w3.org/2001/XMLSchema-instance}type",
            "Verkeershinder",
        )
        type_hinder = type_hinder.split(":")[-1]

        # Split value texts into municipality / location candidates / narrative
        description_parts: list[str] = []
        location_candidates: list[str] = list(location_from_tags)

        for text_val in value_texts:
            if _MUNICIPALITY_RE.match(text_val):
                if not municipality:
                    municipality = text_val
                continue
            if _is_noise_value(text_val):
                continue
            cleaned = _polish_location(text_val)
            if (
                cleaned
                and _looks_like_location(cleaned)
                and cleaned not in location_candidates
                and _ROADISH_RE.search(cleaned)
            ):
                location_candidates.append(cleaned)
            if text_val not in description_parts and not _is_noise_value(text_val):
                description_parts.append(text_val)

        # Prefer explicit roadOrJunctionNumber-style tags over free-text
        location = ""
        tag_pool = [c for c in location_from_tags if not _is_junk_location(c)]
        free_pool = [
            c
            for c in location_candidates
            if not _is_junk_location(c) and _ROADISH_RE.search(c)
        ]
        if tag_pool:
            # Prefer roadish tag values when present
            roadish_tags = [c for c in tag_pool if _ROADISH_RE.search(c)]
            location = (roadish_tags or tag_pool)[0]
        elif free_pool:
            location = min(free_pool, key=len)

        # If location equals a description part, keep narrative without duplicating
        narrative = [
            p
            for p in description_parts
            if p != location and not _MUNICIPALITY_RE.match(p)
        ]
        if not narrative and management_type:
            narrative.append(_MGMT_TYPE_LABELS.get(management_type, management_type))

        final_desc = (
            " - ".join(narrative)
            if narrative
            else (municipality or "Geen details beschikbaar")
        )

        # Match search terms against all human fields (not only description)
        haystack = " ".join(
            filter(None, [final_desc, location, municipality, type_hinder])
        ).lower()
        if self.search_terms and not any(
            term in haystack for term in self.search_terms
        ):
            return None

        item: dict[str, Any] = {
            "id": base_id,
            "type": type_hinder,
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

    async def _parse_feed_response(self, response) -> dict[str, dict[str, Any]]:
        """Stream-decompress and pull-parse a gzip XML response into situations."""
        parser = XMLPullParser(["end"])
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        now = dt_util.utcnow()
        situations: dict[str, dict[str, Any]] = {}

        async for chunk in response.content.iter_chunked(64 * 1024):
            uncompressed_chunk = decompressor.decompress(chunk)
            if uncompressed_chunk:
                parser.feed(uncompressed_chunk)

            for _event, elem in parser.read_events():
                if not elem.tag.endswith("situationRecord"):
                    continue
                parsed = self._extract_situation(elem, now)
                elem.clear()
                if parsed is None:
                    continue
                base_id = parsed["id"]
                # Prefer richer records (longer location + description)
                if base_id not in situations:
                    situations[base_id] = parsed
                else:
                    prev = situations[base_id]
                    prev_score = len(prev.get("location") or "") + len(
                        prev.get("description") or ""
                    )
                    new_score = len(parsed.get("location") or "") + len(
                        parsed.get("description") or ""
                    )
                    if new_score > prev_score:
                        situations[base_id] = parsed

        return situations

    def _merge_and_format(
        self, all_situations: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Deduplicate by location+description+time and format timestamps."""
        unique_desc_situations: dict[str, dict[str, Any]] = {}
        for sit in all_situations.values():
            loc = (sit.get("location") or "").strip().lower()
            desc = (sit.get("description") or "").strip().lower()
            muni = (sit.get("municipality") or "").strip().lower()
            start_m = _minute_key(sit.get("start", ""))
            end_m = _minute_key(sit.get("end", ""))
            # Distinct streets with same municipality/dates stay separate via loc.
            # Gemeente-only clones with same minute window collapse together.
            unique_key = f"{loc}|{desc}|{muni}|{start_m}|{end_m}|{sit.get('type', '')}"
            existing = unique_desc_situations.get(unique_key)
            if existing is None:
                unique_desc_situations[unique_key] = sit
            else:
                # Keep the richer of two true duplicates
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
            try:
                item["start"] = datetime.fromisoformat(
                    item["start"].replace("Z", "+00:00")
                ).strftime("%d-%m-%Y %H:%M")
            except Exception:
                pass
            try:
                item["end"] = datetime.fromisoformat(
                    item["end"].replace("Z", "+00:00")
                ).strftime("%d-%m-%Y %H:%M")
            except Exception:
                pass

        return final_list

    async def _async_update_data(self):
        # Sla de zware download over na een herstart als we al cache hebben
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
                            # deepcopy so later date formatting does not mutate cache
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
                        # Keep prior slice if we have one so mixed updates stay coherent
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

            # If every feed was 304/error-with-cache and nothing new, reuse last_data
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
