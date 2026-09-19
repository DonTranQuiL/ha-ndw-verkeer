"""Unit tests for DATEX situation-level extraction and merge (1.0.5)."""

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
HEERLEN_FIXTURE = Path(__file__).parent / "fixtures" / "situation_heerlen_location.xml"
BETA5_FIXTURE = Path(__file__).parent / "fixtures" / "situation_beta5_patterns.xml"


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

    sys.modules["homeassistant.helpers.aiohttp_client"].async_get_clientsession = (
        lambda hass: None
    )

    class _DataUpdateCoordinator:
        def __init__(self, *args, **kwargs):
            pass

    sys.modules[
        "homeassistant.helpers.update_coordinator"
    ].DataUpdateCoordinator = _DataUpdateCoordinator
    sys.modules["homeassistant.util.dt"].utcnow = lambda: datetime.now(timezone.utc)

    sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
    pkg = types.ModuleType("custom_components.ndw_verkeer")
    pkg.__path__ = [str(ROOT / "custom_components" / "ndw_verkeer")]
    sys.modules["custom_components.ndw_verkeer"] = pkg

    const_path = ROOT / "custom_components" / "ndw_verkeer" / "const.py"
    spec_c = importlib.util.spec_from_file_location(
        "custom_components.ndw_verkeer.const", const_path
    )
    const = importlib.util.module_from_spec(spec_c)
    sys.modules["custom_components.ndw_verkeer.const"] = const
    assert spec_c.loader is not None
    spec_c.loader.exec_module(const)

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


def _situations(path: Path):
    root = fromstring(path.read_text(encoding="utf-8"))
    return [el for el in root.iter() if el.tag.endswith("situation")]


def _situation(path: Path, situation_id: str):
    return next(el for el in _situations(path) if el.attrib.get("id") == situation_id)


@pytest.fixture
def now_fixed():
    return datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)


def test_extract_prefers_road_or_junction_for_location(now_fixed):
    parsed = _coord("Heerlen")._extract_situation_elem(
        _situation(HEERLEN_FIXTURE, "NDW03_100001_SIT"), now_fixed
    )
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
    parsed = _coord("Heerlen")._extract_situation_elem(
        _situation(HEERLEN_FIXTURE, "NDW03_100002_SIT"), now_fixed
    )
    assert parsed is not None
    assert parsed["location"] == ""
    assert parsed["municipality"] == "Gemeente Heerlen"
    assert parsed["description"] == "Rijbaanafsluiting"
    assert parsed["type"] == "RoadOrCarriagewayOrLaneManagement"


def test_extract_distinct_street_via_junction_tag(now_fixed):
    parsed = _coord("Heerlen")._extract_situation_elem(
        _situation(HEERLEN_FIXTURE, "NDW03_100003_SIT"), now_fixed
    )
    assert parsed is not None
    assert parsed["location"] == "Stationsplein"
    assert parsed["municipality"] == "Gemeente Heerlen"


def test_distinct_situations_stay_distinct(now_fixed):
    coord = _coord("")
    situations = {}
    for elem in _situations(HEERLEN_FIXTURE):
        parsed = coord._extract_situation_elem(elem, now_fixed)
        assert parsed is not None
        situations[parsed["id"]] = parsed

    assert len(situations) == 4
    assert {item["location"] for item in situations.values()} >= {
        "Coriovallumstraat",
        "Stationsplein",
    }
    merged = coord._merge_and_format(situations)
    assert len(merged) == 4
    assert all("-" in item["start"] for item in merged)


def test_search_matches_location_field(now_fixed):
    parsed = _coord("Stationsplein")._extract_situation_elem(
        _situation(HEERLEN_FIXTURE, "NDW03_100003_SIT"), now_fixed
    )
    assert parsed is not None
    assert parsed["location"] == "Stationsplein"


def test_bouw_takel_without_street_is_not_a_useful_location(now_fixed):
    parsed = _coord("Maastricht")._extract_situation_elem(
        _situation(HEERLEN_FIXTURE, "NDW03_100004_SIT"), now_fixed
    )
    assert parsed is not None
    assert parsed["location"] == ""
    assert "Bouw/Takel" in parsed["description"]
    assert "Snelheidsbeperking" in parsed["description"]


def test_diversion_narrative_is_not_the_location(now_fixed):
    parsed = _coord("A76")._extract_situation_elem(
        _situation(BETA5_FIXTURE, "RWS01_M1173321_SIT"), now_fixed
    )
    assert parsed is not None
    assert parsed["location"] == "Kunderberg"
    assert parsed["location"] != parsed["description"]
    assert "A76" in parsed["description"]
    assert "omleidingsroute" in parsed["description"].lower()


def test_url_uuid_a76_substring_does_not_match_alone(now_fixed):
    """A76 inside an attachment UUID must not match when human text lacks A76."""
    coord = _coord("A76")
    xml = """<?xml version='1.0' encoding='UTF-8'?>
    <situation id="NDW03_FALSE_A76_SIT" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <situationRecord xsi:type="MaintenanceWorks" id="NDW03_FALSE_A76_URL">
        <validity><validityTimeSpecification>
          <overallStartTime>2026-09-20T06:00:00Z</overallStartTime>
          <overallEndTime>2026-10-01T16:00:00Z</overallEndTime>
        </validityTimeSpecification></validity>
        <generalPublicComment><comment><values>
          <value>Gemeente Gouda</value>
        </values></comment></generalPublicComment>
        <urlLinkAddress>https://example.invalid/attachment/dea76638-a76f-4f3d-8aff-8b2a7632bfba</urlLinkAddress>
      </situationRecord>
    </situation>
    """
    assert coord._extract_situation_elem(fromstring(xml), now_fixed) is None


def test_soft_weg_dicht_not_used_as_location(now_fixed):
    parsed = _coord("Brunssum")._extract_situation_elem(
        _situation(BETA5_FIXTURE, "NDW03_529871_SIT"), now_fixed
    )
    assert parsed is not None
    assert parsed["location"] == "Brunssum centrum"
    assert "Weg dicht" in parsed["description"]
    assert "Kermis" in parsed["description"]


def test_sibling_man_and_det_merge_into_one_situation_item(now_fixed):
    parsed = _coord("Heerlen")._extract_situation_elem(
        _situation(BETA5_FIXTURE, "NDW03_84961_SIT"), now_fixed
    )
    assert parsed is not None
    assert parsed["id"] == "NDW03_84961"
    assert parsed["location"] == "S100 Beersdalweg"
    assert "Beersdalweg" in parsed["description"]
    assert "Omleiding" in parsed["description"]
    assert set(parsed["types"]) == {"MaintenanceWorks", "ReroutingManagement"}
    merged = _coord("Heerlen")._merge_and_format({parsed["id"]: parsed})
    assert len(merged) == 1


def test_long_beperking_sentence_kept_in_description(now_fixed):
    parsed = _coord("Landgraaf")._extract_situation_elem(
        _situation(BETA5_FIXTURE, "NDW03_545222_SIT"), now_fixed
    )
    assert parsed is not None
    assert parsed["location"] == "Europaweg"
    assert "eenrichtingsverkeer" in parsed["description"]
    assert "Europaweg" in parsed["description"]


def test_bouw_takel_with_street_keeps_real_street_location(now_fixed):
    parsed = _coord("Kerkrade")._extract_situation_elem(
        _situation(BETA5_FIXTURE, "NDW03_BUILD_STREET_SIT"), now_fixed
    )
    assert parsed is not None
    assert "Nullandstraat" in parsed["location"]
    assert "Weg dicht" in parsed["description"]
    assert "Bouw/Takel" in parsed["description"]
