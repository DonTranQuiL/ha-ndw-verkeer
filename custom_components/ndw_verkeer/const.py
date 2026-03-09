DOMAIN = "ndw_verkeer"
MANUFACTURER = "NDW Opendata"
DEFAULT_SCAN_INTERVAL = 18000 # voor nu, je kunt de service oproepen voor de update. database gaat via live parsing!

# Configuratie sleutels
CONF_INSTANCE_NAME = "instance_name"
CONF_SEARCH_TERMS = "search_terms"
CONF_SCAN_INTERVAL = "scan_interval"

# De 3 Gouden NDW Datasets
FEED_PLANNED = "https://opendata.ndw.nu/planningsfeed_wegwerkzaamheden_en_evenementen.xml.gz"
FEED_CLOSURES = "https://opendata.ndw.nu/tijdelijke_verkeersmaatregelen_afsluitingen.xml.gz"
FEED_ROADWORKS = "https://opendata.ndw.nu/wegwerkzaamheden.xml.gz"

PLATFORMS = ["sensor"]