DOMAIN = "ndw_verkeer"
MANUFACTURER = "NDW Opendata"
DEFAULT_SCAN_INTERVAL = 18000  # 5h default; prefer service refresh for planning use

# Configuratie sleutels
CONF_INSTANCE_NAME = "instance_name"
CONF_SEARCH_TERMS = "search_terms"
CONF_SCAN_INTERVAL = "scan_interval"

# Active NDW DATEX II gzip feeds (national dumps; streamed + filtered client-side).
# Note: former FEED_ROADWORKS (wegwerkzaamheden.xml.gz) returns 404 on opendata.ndw.nu.
FEED_PLANNED = (
    "https://opendata.ndw.nu/planningsfeed_wegwerkzaamheden_en_evenementen.xml.gz"
)
FEED_CLOSURES = (
    "https://opendata.ndw.nu/tijdelijke_verkeersmaatregelen_afsluitingen.xml.gz"
)

PLATFORMS = ["sensor"]
