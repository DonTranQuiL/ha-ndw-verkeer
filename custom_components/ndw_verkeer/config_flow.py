"""Config flow for NDW Verkeershinder integration."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_INSTANCE_NAME, CONF_SEARCH_TERMS, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

MIN_SCAN_INTERVAL_SECONDS = 300  # Minimaal 5 minuten om NDW servers niet te overbelasten

def validate_scan_interval(scan_interval: int) -> bool:
    return scan_interval >= MIN_SCAN_INTERVAL_SECONDS

def validate_search_terms(terms: str) -> bool:
    return bool(terms.strip())

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            instance_name = user_input.get(CONF_INSTANCE_NAME)
            search_terms = user_input.get(CONF_SEARCH_TERMS)
            scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

            if not instance_name: 
                errors[CONF_INSTANCE_NAME] = "required"
            if not search_terms: 
                errors[CONF_SEARCH_TERMS] = "required"
            if not validate_scan_interval(scan_interval): 
                errors[CONF_SCAN_INTERVAL] = "invalid_scan_interval"

            if not errors:
                for entry in self._async_current_entries():
                    if entry.data.get(CONF_INSTANCE_NAME) == instance_name:
                        return self.async_abort(reason="already_configured")

                if validate_search_terms(search_terms):
                    return self.async_create_entry(
                        title=f"NDW Verkeer ({instance_name})",
                        data={
                            CONF_INSTANCE_NAME: instance_name,
                            CONF_SEARCH_TERMS: search_terms,
                        },
                        options={
                            CONF_SCAN_INTERVAL: scan_interval,
                            CONF_SEARCH_TERMS: search_terms, # Ook in options voor snelle wijzigingen
                        },
                    )
                else:
                    errors["base"] = "invalid_terms"

        data_schema = vol.Schema({
            vol.Required(CONF_INSTANCE_NAME): str,
            vol.Required(CONF_SEARCH_TERMS, default="Gemeente, wegnummer"): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
        })
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        # Lege return om de 500 Internal Server Error te voorkomen!
        return OptionsFlowHandler()

class OptionsFlowHandler(config_entries.OptionsFlow):
    
    async def async_step_init(self, user_input=None) -> FlowResult:
        if user_input is not None:
            scan_interval = user_input.get(CONF_SCAN_INTERVAL)
            if not validate_scan_interval(scan_interval):
                return self.async_show_form(
                    step_id="init",
                    data_schema=vol.Schema({
                        vol.Required(CONF_SEARCH_TERMS, default=self.config_entry.options.get(CONF_SEARCH_TERMS, self.config_entry.data.get(CONF_SEARCH_TERMS))): str,
                        vol.Required(CONF_SCAN_INTERVAL, default=self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): int
                    }),
                    errors={CONF_SCAN_INTERVAL: "invalid_scan_interval"},
                )
            return self.async_create_entry(title="", data=user_input)

        options_schema = vol.Schema({
            vol.Required(CONF_SEARCH_TERMS, default=self.config_entry.options.get(CONF_SEARCH_TERMS, self.config_entry.data.get(CONF_SEARCH_TERMS))): str,
            vol.Required(CONF_SCAN_INTERVAL, default=self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): int,
        })
        return self.async_show_form(step_id="init", data_schema=options_schema)
