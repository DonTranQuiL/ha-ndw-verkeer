import logging
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, PLATFORMS
from .coordinator import NDWVerkeerCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up NDW Verkeer from a config entry."""
    _LOGGER.debug("Start setup NDW Verkeer voor: %s", entry.entry_id)
    
    coordinator = NDWVerkeerCoordinator(hass, entry)
    
    # SMART BOOT: Use the cache if it exists to prevent long loading times!
    if coordinator.last_data:
        _LOGGER.debug("Cache found! Loading instantly to speed up startup.")
        coordinator.data = coordinator.last_data
        # Start the heavy download silently in the background so HA isn't blocked
        entry.async_create_background_task(hass, coordinator.async_request_refresh(), "ndw_bg_refresh")
    else:
        _LOGGER.debug("No cache found. Starting the heavy first download...")
        await coordinator.async_config_entry_first_refresh()
    
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Registreer de handmatige refresh service
    async def handle_refresh(call: ServiceCall):
        _LOGGER.debug("Handmatige NDW refresh aangevraagd")
        for coord in hass.data[DOMAIN].values():
            await coord.async_request_refresh()

    # Registreer de cache/debug clear service
    async def handle_clear_files(call: ServiceCall):
        _LOGGER.debug("Clear NDW files service aangevraagd")
        for coord in hass.data[DOMAIN].values():
            await hass.async_add_executor_job(coord.cache.clear_cache)
            await hass.async_add_executor_job(coord.clear_debug_file)

    hass.services.async_register(DOMAIN, "refresh", handle_refresh)
    hass.services.async_register(DOMAIN, "clear_files", handle_clear_files)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Luister naar wijzigingen in de Opties (voor als je zoektermen aanpast via UI)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True

async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Herlaad de integratie als de zoektermen worden aangepast."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload de configuratie."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
