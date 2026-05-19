import pytest
from unittest.mock import patch
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ndw_verkeer.const import (
    DOMAIN,
    CONF_INSTANCE_NAME,
    CONF_SEARCH_TERMS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
)

@pytest.mark.asyncio
async def test_form_user_success(hass):
    """Test we can create an entry through the user step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch("custom_components.ndw_verkeer.async_setup_entry", return_value=True):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_INSTANCE_NAME: "A12 Hinder",
                CONF_SEARCH_TERMS: "A12",
                CONF_SCAN_INTERVAL: 600,
            },
        )

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "NDW Verkeer (A12 Hinder)"
    assert result2["data"][CONF_INSTANCE_NAME] == "A12 Hinder"
    assert result2["data"][CONF_SEARCH_TERMS] == "A12"
    assert result2["options"][CONF_SCAN_INTERVAL] == 600
    assert result2["options"][CONF_SEARCH_TERMS] == "A12"


@pytest.mark.asyncio
async def test_form_user_invalid_scan_interval(hass):
    """Test we handle invalid scan interval."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_INSTANCE_NAME: "A12 Hinder",
            CONF_SEARCH_TERMS: "A12",
            CONF_SCAN_INTERVAL: 60,  # Below the 300 minimum limit
        },
    )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {CONF_SCAN_INTERVAL: "invalid_scan_interval"}


@pytest.mark.asyncio
async def test_form_user_invalid_terms(hass):
    """Test we handle empty search terms properly."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_INSTANCE_NAME: "A12 Hinder",
            CONF_SEARCH_TERMS: "   ",
            CONF_SCAN_INTERVAL: 300,
        },
    )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_terms"}


@pytest.mark.asyncio
async def test_options_flow(hass):
    """Test the options flow for changing settings."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_INSTANCE_NAME: "A12", CONF_SEARCH_TERMS: "A12"},
        options={CONF_SCAN_INTERVAL: 300, CONF_SEARCH_TERMS: "A12"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SEARCH_TERMS: "A15",
            CONF_SCAN_INTERVAL: 600,
        },
    )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_SEARCH_TERMS] == "A15"
    assert result2["data"][CONF_SCAN_INTERVAL] == 600


@pytest.mark.asyncio
async def test_options_flow_invalid_scan_interval(hass):
    """Test options flow rejects invalid scan intervals."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_INSTANCE_NAME: "A12", CONF_SEARCH_TERMS: "A12"},
        options={CONF_SCAN_INTERVAL: 300, CONF_SEARCH_TERMS: "A12"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SEARCH_TERMS: "A15",
            CONF_SCAN_INTERVAL: 100,  # Below minimum
        },
    )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {CONF_SCAN_INTERVAL: "invalid_scan_interval"}
