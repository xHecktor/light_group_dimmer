import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_NAME
from .const import (
    DOMAIN,
    CONF_TYPE,
    CONF_DELAY,
    DEFAULT_DELAY,
    CONF_GROUPS,
    CONF_NAME,
    CONF_ENTITIES
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["light"]


async def async_setup(hass: HomeAssistant, config: dict):
    """
    Wird einmal beim Starten geladen. Liest YAML-Konfiguration ein (falls vorhanden)
    und erzeugt bei Bedarf einen Master-Eintrag. 
    """
    hass.data.setdefault(DOMAIN, {})
    # Globale Defaults in hass.data
    hass.data[DOMAIN].setdefault(CONF_GROUPS, [])
    hass.data[DOMAIN].setdefault(CONF_DELAY, DEFAULT_DELAY)
    hass.data[DOMAIN]["yaml_config"] = False

    # Schauen, ob in configuration.yaml (oder packages) ein Abschnitt 'light_group_dimmer:' vorhanden ist
    if DOMAIN in config:
        yaml_conf = config[DOMAIN]

        # Delay aus YAML (falls gesetzt)
        if CONF_DELAY in yaml_conf:
            yaml_delay = yaml_conf.get(CONF_DELAY)
            _LOGGER.info("YAML-Delay erkannt: %s (hat Vorrang)", yaml_delay)
            hass.data[DOMAIN][CONF_DELAY] = yaml_delay
            hass.data[DOMAIN]["yaml_config"] = True

        # Gruppen aus YAML
        yaml_groups = yaml_conf.get(CONF_GROUPS, [])
        _LOGGER.debug("Geladene Gruppen aus YAML: %s", yaml_groups)
        hass.data[DOMAIN][CONF_GROUPS] = yaml_groups

        # Diese YAML-Gruppen per Import-Flow in den Master-Eintrag integrieren
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data={"groups": yaml_groups}
            )
        )

    # Prüfen, ob bereits ein Master-Eintrag existiert
    already_master = any(
        entry.data.get(CONF_TYPE) == "master"
        for entry in hass.config_entries.async_entries(DOMAIN)
    )
    if not already_master:
        _LOGGER.info("Kein Master-Eintrag vorhanden. Lege automatisch einen an.")
        master_delay = DEFAULT_DELAY
        data = {CONF_TYPE: "master", CONF_DELAY: master_delay}


        # Starte den System-Flow zum Anlegen des Master-Eintrags
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "system"},
                data=data
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """
    Wird aufgerufen, wenn (nach einem Reload oder HA-Start) ein Config-Eintrag dieses 
    Domains (DOMAIN="light_group_dimmer") eingerichtet wird.
    """
    entry.async_on_unload(entry.add_update_listener(update_listener))
    entry_type = entry.data.get(CONF_TYPE)
    
    if entry_type == "master":
        
        if entry.data.get("groups"):
            clean_data = {k: v for k, v in entry.data.items() if k != "groups"}
            hass.config_entries.async_update_entry(entry, data=clean_data)
            _LOGGER.info("Alte Gruppen aus dem Master‑Eintrag gelöscht")        
        
        # Master-Eintrag: Delay aus YAML oder OptionsFlow übernehmen
        if hass.data[DOMAIN].get("yaml_config"):
            yaml_delay = hass.data[DOMAIN][CONF_DELAY]
            _LOGGER.info("YAML ist aktiv. Verwende YAML-Delay: %s", yaml_delay)
            # Falls YAML-Gruppen vorhanden sind, übernimm sie in hass.data
            if "groups" in entry.data:
                hass.data[DOMAIN][CONF_GROUPS] = entry.data["groups"]
                _LOGGER.info("Master-Eintrag verwendet YAML-Gruppen: %s", entry.data["groups"])
        else:
            # Kein YAML aktiv -> Delay aus entry.options oder entry.data
            new_delay = entry.options.get(CONF_DELAY, entry.data.get(CONF_DELAY, DEFAULT_DELAY))
            hass.data[DOMAIN][CONF_DELAY] = new_delay
            _LOGGER.info("Aktueller Delay in hass.data: %s (über config entry)", new_delay)

    elif entry_type == "group":
        # Gruppen-Eintrag, der im UI erstellt wurde
        # Der Nutzer kann den Namen und die Entities im OptionsFlow ändern
        # => Wir lesen sie aus entry.options (Fallback: entry.data)
        group_name = entry.options.get(CONF_NAME, entry.data.get(CONF_NAME))
        group_entities = entry.options.get(CONF_ENTITIES, entry.data.get(CONF_ENTITIES, []))

        # Falls du globale Speicherung möchtest, z.B. in hass.data,
        # kannst du es hier ablegen; oder direkt in light.py aus entry.options lesen
        _LOGGER.debug("Setup Gruppe '%s' mit Entities=%s", group_name, group_entities)

    # Starte das Setup der Light-Plattform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """
    Wird getriggert, wenn sich an einem vorhandenen Config-Eintrag 
    die Options oder Data geändert haben (z.B. durch den OptionsFlow).
    """
    new_delay = entry.options.get(
        CONF_DELAY,
        entry.data.get(CONF_DELAY, DEFAULT_DELAY)
    )
    _LOGGER.debug("Update Listener: Neuer Delay=%s", new_delay)

    # Aktualisiere den globalen Delay in hass.data
    hass.data[DOMAIN][CONF_DELAY] = new_delay

    # YAML-Eintrag => Gruppen updaten
    if entry.data.get("type") == "yaml":
        new_groups = entry.data.get("groups", [])
        hass.data[DOMAIN][CONF_GROUPS] = new_groups
        _LOGGER.debug("Update Listener: Neue YAML-Gruppen=%s", new_groups)

    # Reload des Config-Entry
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """
    Entladen eines Eintrags (z.B. wenn man ihn entfernt oder deaktiviert).
    """
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unloaded:
        return False

    entry_type = entry.data.get(CONF_TYPE)
    if entry_type == "master":
        # Wenn der Master entfernt wird, auf Default zurücksetzen
        hass.data[DOMAIN][CONF_DELAY] = DEFAULT_DELAY
    # Bei group-Einträgen ggf. Daten entfernen
    return True
