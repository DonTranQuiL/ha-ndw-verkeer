import pytest
from unittest.mock import MagicMock
from homeassistant.const import EntityCategory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ndw_verkeer.const import DOMAIN, MANUFACTURER
from custom_components.ndw_verkeer.sensor import NDWSensor, NDWDiagnosticSensor

@pytest.fixture
def mock_coordinator():
    coordinator = MagicMock()
    coordinator.data = [
        {
            "id": "12345", 
            "start": "2026-05-19T10:00:00Z", 
            "end": "Onbekend", 
            "description": "File door ongeval", 
            "type": "Ongeval"
        }
    ]
    coordinator.last_update_success_timestamp = "2026-05-19T11:49:00Z"
    coordinator.error_count = 0
    return coordinator

@pytest.fixture
def mock_entry():
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="test_entry_id",
        data={"instance_name": "Test Regio", "search_terms": "Test"},
        options={"scan_interval": 300},
    )

def test_ndw_sensor_with_data(mock_coordinator, mock_entry):
    """Test the main NDW sensor populates correctly when incidents exist."""
    sensor = NDWSensor(mock_coordinator, mock_entry)
    
    assert sensor.unique_id == "test_entry_id_latest_hinder"
    assert sensor.icon == "mdi:traffic-cone"
    assert sensor.device_info["name"] == "NDW Verkeer (Test Regio)"
    assert sensor.device_info["manufacturer"] == MANUFACTURER
    
    # State mapping tests
    assert sensor.native_value == "Ongeval"
    
    # Attribute mapping tests
    attrs = sensor.extra_state_attributes
    assert attrs["id"] == "12345"
    assert attrs["description"] == "File door ongeval"
    assert attrs["start"] == "2026-05-19T10:00:00Z"
    assert attrs["history"] == []

def test_ndw_sensor_no_data(mock_coordinator, mock_entry):
    """Test the main NDW sensor fallback when no incidents are active."""
    mock_coordinator.data = []
    sensor = NDWSensor(mock_coordinator, mock_entry)
    
    assert sensor.native_value == "Geen meldingen"
    assert sensor.extra_state_attributes == {}

def test_ndw_diagnostic_sensor_status(mock_coordinator, mock_entry):
    """Test diagnostic sensor handles connection status logic."""
    sensor = NDWDiagnosticSensor(mock_coordinator, mock_entry, "last_update_status", "Last Update Status")
    
    assert sensor.unique_id == "test_entry_id_diag_last_update_status"
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC
    assert sensor.native_value == "OK"
    
    # Simulate a network drop
    mock_coordinator.last_update_success_timestamp = None
    assert sensor.native_value == "Error"

def test_ndw_diagnostic_sensor_time_and_errors(mock_coordinator, mock_entry):
    """Test diagnostic sensors output exact update times and error counts."""
    time_sensor = NDWDiagnosticSensor(mock_coordinator, mock_entry, "last_update_time", "Last Update Time")
    assert time_sensor.native_value == "2026-05-19T11:49:00Z"

    mock_coordinator.error_count = 5
    error_sensor = NDWDiagnosticSensor(mock_coordinator, mock_entry, "error_count", "Consecutive Errors")
    assert error_sensor.native_value == 5
