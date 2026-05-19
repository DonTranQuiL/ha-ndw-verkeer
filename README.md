<div align="center">

# 🌌 DW Verkeer Integration for Home Assistant
**A roadworks, and planned events integration for the dutch muncipality for Home Assistant.**
</div>

<p align="center">
  <!-- Release / License -->
  <a href="https://github.com/DonTranQuiL/ha-ndw-verkeer/releases">
    <img src="https://img.shields.io/github/v/release/DonTranQuiL/ha-ndw-verkeer?style=for-the-badge&color=007ec6" alt="Latest Release">
  </a>
  <a href="https://github.com/DonTranQuiL/ha-ndw-verkeer/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/DonTranQuiL/ha-ndw-verkeer?style=for-the-badge&color=007ec6" alt="License">
  </a>

  <!-- CI / Quality -->
  <a href="https://github.com/DonTranQuiL/ha-ndw-verkeer/actions">
    <img src="https://img.shields.io/github/actions/workflow/status/DonTranQuiL/ha-ndw-verkeer/codechecker.yml?style=for-the-badge&label=CODE%20CHECKS&color=5dbb0f" alt="Code Checks">
  </a>
  <a href="https://github.com/DonTranQuiL/ha-ndw-verkeer/actions">
    <img src="https://img.shields.io/github/actions/workflow/status/DonTranQuiL/ha-ndw-verkeer/pytest.yml?style=for-the-badge&label=TESTS&color=5dbb0f" alt="Tests">
  </a>
  <a href="https://github.com/DonTranQuiL/ha-ndw-verkeer/actions">
    <img src="https://img.shields.io/github/actions/workflow/status/DonTranQuiL/ha-ndw-verkeer/hacs.yaml?style=for-the-badge&label=HACS%20VALIDATION&color=5dbb0f" alt="HACS Validation">
  </a>

  <!-- Code Quality -->
  <a href="https://github.com/pre-commit/pre-commit">
    <img src="https://img.shields.io/badge/pre--commit-enabled-5dbb0f?style=for-the-badge" alt="pre-commit">
  </a>
  <a href="https://github.com/astral-sh/ruff">
    <img src="https://img.shields.io/badge/code%20style-ruff-000000?style=for-the-badge" alt="Ruff">
  </a>
  <a href="https://codecov.io/gh/DonTranQuiL/ha-ndw-verkeer">
  <img 
    src="https://codecov.io/gh/DonTranQuiL/ha-ndw-verkeer/branch/main/graph/badge.svg"
    alt="Coverage"
    style="height:28px;"
  >
</a>

  <!-- Ecosystem -->
  <a href="https://hacs.xyz/">
    <img src="https://img.shields.io/badge/HACS-CUSTOM-ff6e27?style=for-the-badge" alt="HACS">
  </a>
  <a href="https://www.home-assistant.io/">
    <img src="https://img.shields.io/badge/Home%20Assistant-2024.5%2B-007ec6?style=for-the-badge" alt="Home Assistant">
  </a>

  <!-- Social / Support -->
  <a href="https://github.com/DonTranQuiL">
    <img src="https://img.shields.io/badge/maintainer-%40DonTranQuiL-007ec6?style=for-the-badge" alt="Maintainer">
  </a>
  <a href="https://ko-fi.com/DonTranQuiL">
    <img src="https://img.shields.io/badge/buy%20me%20a%20coffee-donate-ffdd00?style=for-the-badge" alt="Donate">
  </a>
  <a href="https://community.home-assistant.io/">
    <img src="https://img.shields.io/badge/community-forum-007ec6?style=for-the-badge" alt="Community">
  </a>
</p>

</div>

This custom component for Home Assistant allows you to monitor live traffic incidents, roadworks, and planned events for any specific road or municipality in the Netherlands. It streams data directly from the official [NDW (Nationaal Dataportaal Wegverkeer)](https://opendata.ndw.nu/) Datex II XML feeds, keeping you informed about what is happening on your daily commute or in your neighborhood.

> **Disclaimer:** This integration relies on massive, public XML feeds from the Dutch government. To process these efficiently without crashing Home Assistant, it uses advanced *in-memory stream parsing*. To avoid spamming the NDW servers, the absolute minimum scan interval is 18000 seconds (5 hours), no scan time or a extreme high one is the best so you can trigger it from the actions tab in dev options and recommended for general planning.

This integration was created with significant collaboration, testing, and debugging from **TranQuiL (@Malosaaa)**.

***
## 🚀 Key Features

* ✅ **Zero-Memory Stream Parsing**: Downloads and decompresses the massive `.gz` XML files on-the-fly in chunks. It reads and clears data iteratively, keeping RAM usage near zero!
* ✅ **Multi-Keyword Filtering**: Enter a comma-separated list of your favorite cities or highways (e.g., `Heerlen, A76, N281`). The integration strictly filters the national feed for your areas of interest.
* ✅ **Smart Deduplication & Time Filter**: The NDW feed is notorious for duplicate entries and expired events. This integration automatically merges duplicates and throws out past events, turning your sensor into a perfect, forward-looking traffic agenda.
* ✅ **Local Persistence**: Includes a built-in JSON cache system. Your alerts are saved to disk and load **instantly** when Home Assistant reboots—no blank dashboard cards on startup.
* ✅ **Master Sensor Approach**: A single master sensor displays the most recent or upcoming incident, while the rest are neatly stored in a `history` attribute.
* ✅ **Diagnostic Tracking**: Includes dedicated diagnostic sensors for "Last Update Status", "Last Update Time", and "Consecutive Errors".
* ✅ **Built-in Debugging**: Automatically generates a local `.txt` debug file in the integration folder so you can see exactly which raw data was matched and filtered.
* ✅ **Service Calls**: Includes services to manually trigger a refresh or cleanly delete all local cache and debug files.

## 🛠 Installation

### Method 1: HACS (Recommended)
1. Open **HACS** -> **Integrations**.
2. Click the 3-dots menu (top right) -> **Custom Repositories**.
3. Paste URL: `https://github.com/Malosaaa/ha-ndw-verkeer` | Category: **Integration**.
4. Click **Add**, then find "NDW Verkeer" and click **Download**.
5. **Restart Home Assistant.**

### Method 2: Manual
1. Download the `ndw_verkeer` folder from this repo.
2. Copy it into your Home Assistant `custom_components/` directory.
3. **Restart Home Assistant.**

## ⚙️ Configuration

1. Go to **Settings** -> **Devices & Services**.
2. Click **+ Add Integration** and search for **NDW Verkeer**.
3. **Instance Name**: Choose a friendly name for your device (e.g., `Zuid-Limburg`).
4. **Search Terms**: Enter the roads and municipalities you want to track, separated by commas (e.g., `Gemeente, wegnummer`). *(You can change these later by clicking "Configure" on the integration page!)*
5. **Scan Interval**: Set how often to check for updates (18000 seconds / 5 hours is the default).

## 📊 Sensors & Attributes

### Master Sensor
`sensor.ndw_verkeer_<instance_name>`

| Attribute | Content |
| :--- | :--- |
| `start` | The exact start date and time of the incident/roadwork (DD-MM-YYYY HH:MM). |
| `end` | The exact end date and time of the incident/roadwork (DD-MM-YYYY HH:MM). |
| `description` | A clean, readable summary of the traffic situation, stripped of system codes. |
| `id` | The unique project identifier from the NDW feed. |
| `history` | A chronological list of all other upcoming events, complete with their own dates, types, and descriptions. |

## 🛠 Services

| Service | Description |
| :--- | :--- |
| `ndw_verkeer.refresh` | Forces an immediate stream and parse of the latest NDW XML feeds. |
| `ndw_verkeer.clear_files` | Deletes the local `.json` cache file and the `.txt` debug logs for all configured instances. |


## 🎨 Recommended Dashboard (Markdown)

To get a beautifully formatted, chronological agenda of all traffic events—complete with dynamic icons based on the type of hindrance—use the standard **Markdown Card** built right into Home Assistant. 

*Note: Replace `JEGEMEENTE` in the entity ID below with your actual instance name.*

```yaml
type: grid
cards:
  - type: heading
    heading: New section
  - type: markdown
    content: |2-
        {% set entity = 'sensor.ndw_verkeer_JEGEMEENTE' %}
        
        ## 🚦 Actuele Verkeershinder & Planning
        
        {% if states(entity) not in ['unknown', 'unavailable', 'Geen meldingen'] %}
        {% set type = states(entity) %}
        {% set icon = '🚧' if type in ['MaintenanceWorks', 'ConstructionWorks'] else '🔄' if type == 'ReroutingManagement' else '⛔' if type == 'RoadOrCarriagewayOrLaneManagement' else '🚴' if type == 'PublicEvent' else '⚠️' %}
        {{ icon }} **{{ state_attr(entity, 'start') }} t/m {{ state_attr(entity, 'end') }}** *{{ state_attr(entity, 'description') | truncate(200, true, '...') }}*
        
        ---
        
        {% if state_attr(entity, 'history') %}
        {% for item in state_attr(entity, 'history') %}
        {% set h_icon = '🚧' if item.type in ['MaintenanceWorks', 'ConstructionWorks'] else '🔄' if item.type == 'ReroutingManagement' else '⛔' if item.type == 'RoadOrCarriagewayOrLaneManagement' else '🚴' if item.type == 'PublicEvent' else '⚠️' %}
        {{ h_icon }} **{{ item.start }} t/m {{ item.end }}** *{{ item.description | truncate(200, true, '...') }}*
        
        ---
        {% endfor %}
        {% endif %}
        {% else %}
        🎉 Geen geplande werkzaamheden of actuele hinder gevonden in deze regio!
        {% endif %}

```
[hacs]: https://hacs.xyz
[hacs_badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge
[maintenance_badge]: https://img.shields.io/badge/Maintained%3F-yes-green.svg?style=for-the-badge
