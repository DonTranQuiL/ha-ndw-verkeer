import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ndw_verkeer.const import DOMAIN, PLATFORMS
from custom_components.ndw_verkeer import (
    async_setup_entry,
    async_unload_entry,
    update_listener,
)


@pytest.fixture
def mock_coordinator():
    """Fixture to mock the NDWVerkeerCoordinator so we don't make real API or file system calls."""
    with patch(
        "custom_components.ndw_verkeer.NDWVerkeerCoordinator"
    ) as mock_coord_class:
        mock_coord = MagicMock()
        mock_coord.cache.load_cache = MagicMock(return_value=[])
        mock_coord.cache.clear_cache = MagicMock()
        mock_coord.clear_debug_file = MagicMock()
        mock_coord.async_config_entry_first_refresh = AsyncMock()
        mock_coord.async_request_refresh = AsyncMock()

        mock_coord_class.return_value = mock_coord
        yield mock_coord_class


@pytest.mark.asyncio
async def test_async_setup_and_unload_entry(hass: HomeAssistant, mock_coordinator):
    """Test successful setup and unload of the integration."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={"instance_name": "Test"}, options={"scan_interval": 300}
    )
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ) as mock_forward:
        # Setup the entry
        assert await async_setup_entry(hass, entry) is True

        # Verify coordinator is stored in hass.data
        assert DOMAIN in hass.data
        assert entry.entry_id in hass.data[DOMAIN]

        # Verify platforms were forwarded
        mock_forward.assert_called_once_with(entry, PLATFORMS)

        # Verify services were registered
        assert hass.services.has_service(DOMAIN, "refresh")
        assert hass.services.has_service(DOMAIN, "clear_files")

    # Test Unload
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=True,
    ) as mock_unload:
        assert await async_unload_entry(hass, entry) is True

        # Verify data is cleaned up
        assert entry.entry_id not in hass.data[DOMAIN]
        mock_unload.assert_called_once_with(entry, PLATFORMS)


@pytest.mark.asyncio
async def test_update_listener(hass: HomeAssistant):
    """Test the update listener successfully requests an entry reload."""
    entry = MockConfigEntry(domain=DOMAIN, data={"instance_name": "Test"})

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload", return_value=True
    ) as mock_reload:
        await update_listener(hass, entry)
        mock_reload.assert_called_once_with(entry.entry_id)


@pytest.mark.asyncio
async def test_services(hass: HomeAssistant, mock_coordinator):
    """Test the custom registered services execute their coordinator methods."""
    entry = MockConfigEntry(domain=DOMAIN, data={"instance_name": "Test"})
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await async_setup_entry(hass, entry)

    coord = hass.data[DOMAIN][entry.entry_id]

    # Test refresh service manually triggers _is_first_run to False
    await hass.services.async_call(DOMAIN, "refresh", blocking=True)
    assert getattr(coord, "_is_first_run", None) is False
    coord.async_request_refresh.assert_called_once()

    # Test clear_files service triggers cache and debug clears
    await hass.services.async_call(DOMAIN, "clear_files", blocking=True)
    coord.cache.clear_cache.assert_called_once()
    coord.clear_debug_file.assert_called_once()
