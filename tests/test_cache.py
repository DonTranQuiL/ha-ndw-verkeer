"""Unit tests for NDWCache persistence formats."""

from pathlib import Path


class _Cfg:
    def __init__(self, root: Path):
        self._root = root

    def path(self, name: str) -> str:
        return str(self._root / name)


class _FakeHass:
    def __init__(self, root: Path):
        self.config = _Cfg(root)


def test_cache_legacy_list_roundtrip(tmp_path):
    from custom_components.ndw_verkeer.cache import NDWCache

    hass = _FakeHass(tmp_path)
    cache = NDWCache(hass, "demo")
    payload = [{"id": "a", "description": "Test"}]
    cache.save_cache(payload)
    situations, feeds, terms = cache.load_cache_bundle()
    assert situations == payload
    assert feeds == {}
    assert terms == []
    assert cache.load_cache() == payload


def test_cache_v2_bundle_roundtrip(tmp_path):
    from custom_components.ndw_verkeer.cache import NDWCache

    hass = _FakeHass(tmp_path)
    cache = NDWCache(hass, "demo")
    situations = [{"id": "a", "description": "Heerlen afsluiting"}]
    feed_state = {
        "https://example/feed.xml.gz": {
            "etag": '"abc"',
            "last_modified": "Fri, 18 Sep 2026 20:00:10 GMT",
            "situations": {"a": situations[0]},
        }
    }
    cache.save_cache(situations, feed_state=feed_state, search_terms=["heerlen"])
    loaded_s, loaded_f, loaded_t = cache.load_cache_bundle()
    assert loaded_s == situations
    assert loaded_f == feed_state
    assert loaded_t == ["heerlen"]


def test_cache_clear(tmp_path):
    from custom_components.ndw_verkeer.cache import NDWCache

    hass = _FakeHass(tmp_path)
    cache = NDWCache(hass, "demo")
    cache.save_cache([{"id": "x"}])
    assert Path(cache.cache_path).exists()
    cache.clear_cache()
    assert not Path(cache.cache_path).exists()
    assert cache.load_cache() == []
