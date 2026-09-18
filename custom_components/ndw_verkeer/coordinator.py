"""DataUpdateCoordinator: stream-parse NDW gzip XML feeds with conditional HTTP."""

from __future__ import annotations

import copy
import logging
import os
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

_INVALID_DESC_STARTS = (
    "beperking",
    "omleiding",
    "volg route",
    "geen gevolgen",
    "afsluiting",
    "doorgang",
    "contactpersoon",
    "ja, alleen",
    "let op",
    "verkeersbelemmering",
    "werkzaamheden",
    "tijdens",
)


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
        description_parts: list[str] = []

        for child in elem.iter():
            tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag_name == "overallStartTime" and child.text:
                start_time = child.text
            elif tag_name == "overallEndTime" and child.text:
                end_time = child.text
            elif tag_name == "value" and child.text:
                text_val = child.text.strip()
                tl = text_val.lower()
                if (
                    len(text_val) > 4
                    and not tl.startswith(_INVALID_DESC_STARTS)
                    and ".pdf" not in tl
                    and "verkeersbesluit" not in tl
                ):
                    if text_val not in description_parts:
                        description_parts.append(text_val)

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
        final_desc = (
            " - ".join(description_parts)
            if description_parts
            else "Geen details beschikbaar"
        )

        if not any(term in final_desc.lower() for term in self.search_terms):
            return None

        return {
            "id": base_id,
            "type": type_hinder,
            "start": start_time,
            "end": end_time,
            "description": final_desc,
        }

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
                if base_id not in situations or len(parsed["description"]) > len(
                    situations[base_id]["description"]
                ):
                    situations[base_id] = parsed

        return situations

    def _merge_and_format(
        self, all_situations: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Deduplicate by description+start and format timestamps for display."""
        unique_desc_situations: dict[str, dict[str, Any]] = {}
        for sit in all_situations.values():
            unique_key = f"{sit['description']}_{sit['start']}"
            if unique_key not in unique_desc_situations:
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
