"""Disk persistence for filtered NDW situations and per-feed HTTP validators."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

_LOGGER = logging.getLogger(__name__)

CACHE_VERSION = 2


class NDWCache:
    def __init__(self, hass, instance_name: str) -> None:
        self.cache_path = hass.config.path(f".ndw_verkeer_{instance_name}.json")

    def save_cache(
        self,
        data: list[dict[str, Any]],
        *,
        feed_state: dict[str, Any] | None = None,
        search_terms: list[str] | None = None,
    ) -> None:
        """Persist situations; optionally store per-feed ETag state (cache v2)."""
        try:
            if feed_state is not None:
                payload: list | dict[str, Any] = {
                    "version": CACHE_VERSION,
                    "situations": data,
                    "search_terms": list(search_terms or []),
                    "feeds": feed_state,
                }
            else:
                payload = data
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)
        except Exception as e:
            _LOGGER.error("Fout bij opslaan NDW cache: %s", e)

    def load_cache_bundle(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
        """Return (situations, feed_state, search_terms). Supports legacy list cache."""
        if not os.path.exists(self.cache_path):
            return [], {}, []
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                return raw, {}, []
            if isinstance(raw, dict):
                situations = raw.get("situations", [])
                feeds = raw.get("feeds", {})
                terms = raw.get("search_terms", [])
                if not isinstance(situations, list):
                    situations = []
                if not isinstance(feeds, dict):
                    feeds = {}
                if not isinstance(terms, list):
                    terms = []
                return situations, feeds, terms
            return [], {}, []
        except Exception as e:
            _LOGGER.error("Fout bij laden NDW cache: %s", e)
            return [], {}, []

    def load_cache(self) -> list[dict[str, Any]]:
        situations, _, _ = self.load_cache_bundle()
        return situations

    def clear_cache(self) -> None:
        """Verwijdert het JSON cache bestand."""
        if os.path.exists(self.cache_path):
            try:
                os.remove(self.cache_path)
                _LOGGER.debug("Cache bestand verwijderd: %s", self.cache_path)
            except Exception as e:
                _LOGGER.error("Fout bij verwijderen cache: %s", e)
