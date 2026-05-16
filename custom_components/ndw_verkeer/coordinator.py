import os
import zlib
from datetime import timedelta, datetime
import logging
from xml.etree.ElementTree import XMLPullParser

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_SEARCH_TERMS,
    FEED_PLANNED,
    FEED_CLOSURES,
    FEED_ROADWORKS,
)
from .cache import NDWCache

_LOGGER = logging.getLogger(__name__)


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

        self.feeds = [FEED_CLOSURES, FEED_ROADWORKS, FEED_PLANNED]

        self.cache = NDWCache(hass, self.instance_name)
        # Start met een lege lijst, de cache wordt via __init__.py op de achtergrond ingeladen
        self.last_data = []
        self.error_count = 0
        self.last_update_success_timestamp = None
        self._is_first_run = True  # Zorgt ervoor dat we bij opstarten de zware download overslaan als we cache hebben

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

    async def _async_update_data(self):
        # Sla de zware download over na een herstart als we al cache hebben!
        if self._is_first_run and self.last_data:
            self._is_first_run = False
            _LOGGER.debug(
                "Eerste run na opstarten: Download overgeslagen, cache gebruikt."
            )
            return self.last_data
        self._is_first_run = False

        _LOGGER.debug("NDW data streamen voor termen: %s", self.search_terms)
        session = async_get_clientsession(self.hass)

        all_situations = {}
        debug_log_content = (
            f"NDW VERKEER DEBUG LOG\nZoektermen: {self.search_terms}\n\n"
        )
        now = dt_util.utcnow()

        try:
            for feed_url in self.feeds:
                async with session.get(feed_url) as response:
                    if response.status != 200:
                        continue

                    parser = XMLPullParser(["end"])
                    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)

                    async for chunk in response.content.iter_chunked(64 * 1024):
                        uncompressed_chunk = decompressor.decompress(chunk)

                        if uncompressed_chunk:
                            parser.feed(uncompressed_chunk)

                        for event, elem in parser.read_events():
                            if elem.tag.endswith("situationRecord"):
                                record_id = elem.attrib.get("id", "onbekend")
                                parts = record_id.split("_")
                                base_id = (
                                    "_".join(parts[:2])
                                    if len(parts) >= 2
                                    else record_id
                                )

                                start_time = "Onbekend"
                                end_time = "Onbekend"
                                description_parts = []

                                for child in elem.iter():
                                    tag_name = (
                                        child.tag.split("}")[-1]
                                        if "}" in child.tag
                                        else child.tag
                                    )
                                    if tag_name == "overallStartTime" and child.text:
                                        start_time = child.text
                                    elif tag_name == "overallEndTime" and child.text:
                                        end_time = child.text
                                    elif tag_name == "value" and child.text:
                                        text_val = child.text.strip()
                                        tl = text_val.lower()
                                        invalid_starts = (
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
                                        if (
                                            len(text_val) > 4
                                            and not tl.startswith(invalid_starts)
                                            and ".pdf" not in tl
                                            and "verkeersbesluit" not in tl
                                        ):
                                            if text_val not in description_parts:
                                                description_parts.append(text_val)

                                is_expired = False
                                if end_time != "Onbekend":
                                    try:
                                        if (
                                            datetime.fromisoformat(
                                                end_time.replace("Z", "+00:00")
                                            )
                                            < now
                                        ):
                                            is_expired = True
                                    except Exception:
                                        pass

                                if is_expired:
                                    elem.clear()
                                    continue

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

                                if any(
                                    term in final_desc.lower()
                                    for term in self.search_terms
                                ):
                                    if base_id not in all_situations or len(
                                        final_desc
                                    ) > len(all_situations[base_id]["description"]):
                                        all_situations[base_id] = {
                                            "id": base_id,
                                            "type": type_hinder,
                                            "start": start_time,
                                            "end": end_time,
                                            "description": final_desc,
                                        }
                                elem.clear()

            unique_desc_situations = {}
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

            if final_list:
                self.last_data = final_list
                await self.hass.async_add_executor_job(
                    self.cache.save_cache, final_list
                )
            else:
                self.last_data = []
                await self.hass.async_add_executor_job(self.cache.save_cache, [])

            self.error_count = 0
            self.last_update_success_timestamp = dt_util.utcnow()

            debug_log_content += f"SUCCES: {len(final_list)} records.\n"

            current_dir = os.path.dirname(__file__)
            debug_path = os.path.join(
                current_dir, f"ndw_debug_{self.instance_name}.txt"
            )
            await self.hass.async_add_executor_job(
                self._write_debug_file_sync, debug_path, debug_log_content
            )

            return self.last_data

        except Exception as err:
            self.error_count += 1
            _LOGGER.error("Update mislukt voor NDW: %s", err)
            return self.last_data

    def clear_debug_file(self):
        current_dir = os.path.dirname(__file__)
        debug_path = os.path.join(current_dir, f"ndw_debug_{self.instance_name}.txt")
        # Dit moet in principe ook via async_add_executor_job worden aangeroepen vanuit __init__.py
        self._clear_debug_file_sync(debug_path)
