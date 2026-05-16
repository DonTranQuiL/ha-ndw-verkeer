"""Test the KNMI Seismisch integration."""

from custom_components.entsoe_prijzen.const import DOMAIN


async def test_domain_name():
    """A simple test to ensure pytest is running correctly."""
    assert DOMAIN == "ndw_verkeer"
