"""Unit tests for DATEX situation extraction and merge (1.0.5-beta.3)."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from xml.etree.ElementTree import fromstring

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "situation_heerlen_location.xml"


def _load_coordinator_module():
    """Load coordinator.py with HA stubs, skipping package __init__ side effects."""
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    sys.modules["homeassistant"] = ha
    for name in (
        "homeassistant.helpers",
        "homeassistant.helpers.aiohttp_client",
        "homeassistant.helpers.update_coordinator",
        "homeassistant.util",
        "homeassistant.util.dt",
    ):
        mod = types.ModuleType(name)
        mod.__path__ = []
        sys.modules[name] = mod

    sys.modules[
        "homeassistant.helpers.aiohttp_client"
    ].async_get_clientsession = lambda hass: None

    class _DataUpdateCoordinator:
        def __init__(self, *args, **kwargs):
            pass

    sys.modules[
        "homeassistant.helpers.update_coordinator"
    ].DataUpdateCoordinator = _DataUpdateCoordinator
    sys.modules["homeassistant.util.dt"].utcnow = lambda: datetime.now(timezone.utc)

    # Package placeholders
    sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
    pkg = types.ModuleType("custom_components.ndw_verkeer")
    pkg.__path__ = [str(ROOT / "custom_components" / "ndw_verkeer")]
    sys.modules["custom_components.ndw_verkeer"] = pkg

    # const
    const_path = ROOT / "custom_components" / "ndw_verkeer" / "const.py"
    spec_c = importlib.util.spec_from_file_location(
        "custom_components.ndw_verkeer.const", const_path
    )
    const = importlib.util.module_from_spec(spec_c)
    sys.modules["custom_components.ndw_verkeer.const"] = const
    assert spec_c.loader is not None
    spec_c.loader.exec_module(const)

    # cache stub (coordinator imports NDWCache)
    cache_mod = types.ModuleType("custom_components.ndw_verkeer.cache")

    class NDWCache:
        def __init__(self, *args, **kwargs):
            pass

    cache_mod.NDWCache = NDWCache
    sys.modules["custom_components.ndw_verkeer.cache"] = cache_mod

    coord_path = ROOT / "custom_components" / "ndw_verkeer" / "coordinator.py"
    spec = importlib.util.spec_from_file_location(
        "custom_components.ndw_verkeer.coordinator", coord_path
    )
    coord_mod = importlib.util.module_from_spec(spec)
    sys.modules["custom_components.ndw_verkeer.coordinator"] = coord_mod
    assert spec.loader is not None
    spec.loader.exec_module(coord_mod)
    return coord_mod.NDWVerkeerCoordinator


NDWVerkeerCoordinator = _load_coordinator_module()


def _coord(search_terms: str = "Heerlen") -> NDWVerkeerCoordinator:
    coord = object.__new__(NDWVerkeerCoordinator)
    coord.hass = MagicMock()
    coord.instance_name = "test"
    coord.search_terms = [
        term.strip().lower() for term in search_terms.split(",") if term.strip()
    ]
    coord.feeds = []
    coord.cache = MagicMock()
    coord.last_data = []
    coord._feed_state = {}
    coord.error_count = 0
    coord.last_update_success_timestamp = None
    coord._is_first_run = True
    return coord


def _records():
    root = fromstring(FIXTURE.read_text(encoding="utf-8"))
    return [el for el in root.iter() if el.tag.endswith("situationRecord")]


@pytest.fixture
def now_fixed():
    return datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)


def test_extract_prefers_road_or_junction_for_location(now_fixed):
    coord = _coord("Heerlen")
    rich = _records()[0]
    parsed = coord._extract_situation(rich, now_fixed)
    assert parsed is not None
    assert parsed["location"] == "Coriovallumstraat"
    assert parsed["municipality"] == "Gemeente Heerlen"
    assert "Weg dicht" in parsed["description"]
    assert ".pdf" not in parsed["description"].lower()
    assert "Contactinformatie" not in parsed["description"]
    assert parsed["type"] == "MaintenanceWorks"
    assert parsed.get("latitude") == "50.8871"
    assert parsed.get("longitude") == "5.9790"


def test_extract_gemeente_only_does_not_invent_street(now_fixed):
    coord = _coord("Heerlen")
    lane = _records()[1]
    parsed = coord._extract_situation(lane, now_fixed)
    assert parsed is not None
    assert parsed["location"] == ""
    assert parsed["municipality"] == "Gemeente Heerlen"
    assert "Beperking" not in parsed["description"]
    assert parsed["description"] == "Rijbaanafsluiting"
    assert parsed["type"] == "RoadOrCarriagewayOrLaneManagement"


def test_extract_distinct_street_via_junction_tag(now_fixed):
    coord = _coord("Heerlen")
    reroute = _records()[3]
    parsed = coord._extract_situation(reroute, now_fixed)
    assert parsed is not None
    assert parsed["location"] == "Stationsplein"
    assert parsed["municipality"] == "Gemeente Heerlen"


def test_merge_collapses_gemeente_only_clones_keeps_distinct_locations(now_fixed):
    coord = _coord("Heerlen")
    situations = {}
    for elem in _records():
        parsed = coord._extract_situation(elem, now_fixed)
        if parsed:
            situations[parsed["id"]] = parsed

    assert len(situations) == 4
    merged = coord._merge_and_format(situations)
    locations = {(m.get("location") or "") for m in merged}
    assert "Coriovallumstraat" in locations
    assert "Stationsplein" in locations
    gemeente_only = [
        m
        for m in merged
        if not m.get("location") and m.get("municipality") == "Gemeente Heerlen"
    ]
    assert len(gemeente_only) == 1
    assert "-" in merged[0]["start"]


def test_search_matches_location_field(now_fixed):
    coord = _coord("Stationsplein")
    reroute = _records()[3]
    parsed = coord._extract_situation(reroute, now_fixed)
    assert parsed is not None
    assert parsed["location"] == "Stationsplein"


def test_junk_bouw_takel_rejected_as_location(now_fixed):
    coord = _coord("Maastricht")
    junk = None
    for elem in _records():
        if elem.attrib.get("id", "").startswith("NDW03_486073"):
            junk = elem
            break
    assert junk is not None
    parsed = coord._extract_situation(junk, now_fixed)
    assert parsed is not None
    assert parsed["location"] == ""
    assert parsed["municipality"] == "Gemeente Maastricht"
    assert "Snelheidsbeperking" in parsed["description"]
