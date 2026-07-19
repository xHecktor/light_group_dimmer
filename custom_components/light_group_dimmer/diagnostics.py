"""
Diagnostics-Support: Geräte & Dienste -> Light Group Dimmer -> Diagnose herunterladen.

Liefert einen JSON-Dump der Konfiguration und einen Snapshot der Mitglieds-Lampen,
damit Fehlerberichte ohne Rückfragen auswertbar sind. Enthält keine Zugangsdaten.
"""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_TYPE, CONF_DELAY, DEFAULT_DELAY, CONF_NAME, CONF_ENTITIES

# Attribute der Mitglieds-Lampen, die für die Fehlersuche relevant sind
_MEMBER_ATTRS = (
    "brightness",
    "color_mode",
    "supported_color_modes",
    "color_temp_kelvin",
    "min_color_temp_kelvin",
    "max_color_temp_kelvin",
    "hs_color",
    "effect",
)


def _member_snapshot(hass: HomeAssistant, entity_ids):
    """Zustand + relevante Attribute jeder Mitglieds-Lampe."""
    members = {}
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        if state is None:
            members[entity_id] = {"state": "missing"}
            continue
        members[entity_id] = {
            "state": state.state,
            **{attr: state.attributes.get(attr) for attr in _MEMBER_ATTRS
               if attr in state.attributes},
        }
    return members


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry):
    """Diagnose-Daten für einen Config-Eintrag zusammenstellen."""
    entry_type = entry.data.get(CONF_TYPE)

    # Gruppen dieses Eintrags bestimmen (gleiche Logik wie light.async_setup_entry)
    if entry_type == "yaml":
        groups = entry.data.get("groups", [])
    elif entry_type == "group":
        groups = [{
            "name": entry.options.get(CONF_NAME, entry.data.get(CONF_NAME)),
            "entities": entry.options.get(CONF_ENTITIES, entry.data.get(CONF_ENTITIES, [])),
        }]
    else:
        groups = entry.data.get("groups", [])

    return {
        "entry": {
            "title": entry.title,
            "type": entry_type,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "global": {
            "delay": hass.data.get(DOMAIN, {}).get(CONF_DELAY, DEFAULT_DELAY),
            "yaml_config": hass.data.get(DOMAIN, {}).get("yaml_config", False),
        },
        "groups": [
            {
                "name": group.get("name"),
                "entities": group.get("entities", []),
                "members": _member_snapshot(hass, group.get("entities", [])),
            }
            for group in groups
        ],
    }
