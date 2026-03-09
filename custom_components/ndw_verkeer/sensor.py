from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import EntityCategory
from .const import DOMAIN, MANUFACTURER

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = [
        NDWSensor(coordinator, entry),
        NDWDiagnosticSensor(coordinator, entry, "last_update_status", "Last Update Status"),
        NDWDiagnosticSensor(coordinator, entry, "last_update_time", "Last Update Time", SensorDeviceClass.TIMESTAMP),
        NDWDiagnosticSensor(coordinator, entry, "error_count", "Consecutive Errors"),
    ]
    async_add_entities(entities)

class NDWSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry):
        self.coordinator = coordinator
        self._attr_name = None  # Hoofdsensor krijgt de naam van het apparaat
        self._attr_unique_id = f"{entry.entry_id}_latest_hinder"
        self._attr_icon = "mdi:traffic-cone"
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"NDW Verkeer ({entry.data['instance_name']})",
            "manufacturer": MANUFACTURER,
            "model": "DATEX II XML Feed",
        }

    @property
    def native_value(self):
        if self.coordinator.data and len(self.coordinator.data) > 0:
            return self.coordinator.data[0].get("type", "Hinder gevonden")
        return "Geen meldingen"

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data: 
            return {}
            
        latest = self.coordinator.data[0]
        return {
            "id": latest.get("id", ""),
            "start": latest.get("start", "Onbekend"),
            "end": latest.get("end", "Onbekend"),
            "description": latest.get("description", ""),
            "history": self.coordinator.data[1:]
        }

class NDWDiagnosticSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, key, name, device_class=None):
        self.coordinator = coordinator
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_diag_{key}"
        self._attr_device_class = device_class
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"NDW Verkeer ({entry.data['instance_name']})",
            "manufacturer": MANUFACTURER,
            "model": "DATEX II XML Feed",
        }

    @property
    def native_value(self):
        if self.key == "last_update_status":
            return "OK" if self.coordinator.last_update_success_timestamp else "Error"
        if self.key == "last_update_time":
            return self.coordinator.last_update_success_timestamp
        if self.key == "error_count":
            return self.coordinator.error_count