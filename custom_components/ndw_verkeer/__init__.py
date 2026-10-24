"""The NDW Verkeer integration."""

import logging
import os

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .coordinator import NDWVerkeerCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
CARD_URL_BASE = f"/{DOMAIN}"
CARD_FILE = "ndw_verkeer-card.js"
CARD_VERSION = "1.0.6"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the bundled card and the services once."""
    hass.data.setdefault(DOMAIN, {})
    www = os.path.join(os.path.dirname(__file__), "www")
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_BASE, www, True)]
        )
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, f"{CARD_URL_BASE}/{CARD_FILE}?v={CARD_VERSION}")
    except Exception as err:
        _LOGGER.warning("Could not register the NDW Verkeer card: %s", err)

    async def handle_refresh(call: ServiceCall) -> None:
        for coord in list(hass.data.get(DOMAIN, {}).values()):
            coord._is_first_run = False  # Forceer download bij handmatige refresh
            await coord.async_request_refresh()

    async def handle_clear_files(call: ServiceCall) -> None:
        for coord in list(hass.data.get(DOMAIN, {}).values()):
            coord._feed_state = {}
            await hass.async_add_executor_job(coord.cache.clear_cache)
            await hass.async_add_executor_job(coord.clear_debug_file)

    hass.services.async_register(DOMAIN, "refresh", handle_refresh)
    hass.services.async_register(DOMAIN, "clear_files", handle_clear_files)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("Start setup NDW Verkeer voor: %s", entry.entry_id)

    coordinator = NDWVerkeerCoordinator(hass, entry)
    situations, feed_state, cached_terms = await hass.async_add_executor_job(
        coordinator.cache.load_cache_bundle
    )
    coordinator.last_data = situations
    coordinator._feed_state = feed_state
    # Force a fresh download when search terms changed since cache was written
    if cached_terms and list(cached_terms) != list(coordinator.search_terms):
        coordinator._is_first_run = False
        _LOGGER.debug(
            "Zoektermen gewijzigd t.o.v. cache; eerste run downloadt opnieuw."
        )

    # Start de timer. _is_first_run voorkomt directe download als cache bruikbaar is
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
