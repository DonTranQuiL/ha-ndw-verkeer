import json
import os
import logging

_LOGGER = logging.getLogger(__name__)

class NDWCache:
    def __init__(self, hass, instance_name):
        self.cache_path = hass.config.path(f".ndw_verkeer_{instance_name}.json")

    def save_cache(self, data):
        try:
            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            _LOGGER.error("Fout bij opslaan NDW cache: %s", e)

    def load_cache(self):
        if not os.path.exists(self.cache_path):
            return []
        try:
            with open(self.cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            _LOGGER.error("Fout bij laden NDW cache: %s", e)
            return []

    def clear_cache(self):
        """Verwijdert het JSON cache bestand."""
        if os.path.exists(self.cache_path):
            try:
                os.remove(self.cache_path)
                _LOGGER.debug("Cache bestand verwijderd: %s", self.cache_path)
            except Exception as e:
                _LOGGER.error("Fout bij verwijderen cache: %s", e)