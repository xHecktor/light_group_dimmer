import voluptuous as vol
import json
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_NAME
from homeassistant.helpers import entity_registry as er
import homeassistant.helpers.config_validation as cv
import logging

from .const import (
    DOMAIN,
    CONF_TYPE,
    CONF_DELAY,
    DEFAULT_DELAY,
    CONF_NAME,
    CONF_ENTITIES,
)

_LOGGER = logging.getLogger(__name__)

STEP_MASTER = "master"
STEP_GROUP = "group"


def groups_equal(groups1, groups2):
    sorted1 = sorted(groups1, key=lambda g: g.get("name", ""))
    sorted2 = sorted(groups2, key=lambda g: g.get("name", ""))
    return json.dumps(sorted1, sort_keys=True) == json.dumps(sorted2, sort_keys=True)


class LightGroupDimmerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config Flow für Light Group Dimmer."""
    VERSION = 1

    async def async_step_system(self, system_data=None):
        """
        Wird vom __init__.py (async_setup) aufgerufen, falls kein Master-Eintrag existiert.
        context={"source": "system"}, data={"type": "master", "delay": 5}
        """
        _LOGGER.debug("async_step_system mit data=%s", system_data)
        entry_type = system_data.get(CONF_TYPE, "master")
        delay_val = system_data.get(CONF_DELAY, DEFAULT_DELAY)

        # Master-Eintrag: unique_id="master"
        await self.async_set_unique_id("master")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title="Global Delay Settings",
            data={
                CONF_TYPE: entry_type,  # "master"
                CONF_DELAY: delay_val,
            },
        )

    async def async_step_import(self, import_config: dict | None = None):
        """
        YAML-Import-Flow: Wird getriggert, wenn YAML-Gruppen erkannt werden.
        Wir aktualisieren hier den Master-Eintrag oder legen ggf. einen YAML-Eintrag an.
        """
        _LOGGER.debug("async_step_import: import_config=%s", import_config)
        groups = import_config.get("groups", [])

        # Suche Master-Eintrag
        master_entries = [
            e for e in self.hass.config_entries.async_entries(DOMAIN)
            if e.data.get(CONF_TYPE) == "master"
        ]
        if master_entries:
            master_entry = master_entries[0]
            _LOGGER.debug("Master-Eintrag gefunden: %s", master_entry.data)
            # Vergleiche bisherige und neue Gruppen
            if not groups_equal(master_entry.data.get("groups", []), groups):
                _LOGGER.debug("YAML-Gruppen haben sich geändert – aktualisiere Master-Eintrag")
                new_data = {**master_entry.data, "groups": groups}
                self.hass.config_entries.async_update_entry(master_entry, data=new_data)
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(master_entry.entry_id)
                )
            else:
                _LOGGER.debug("Keine Änderungen an den YAML-Gruppen festgestellt.")
            return self.async_abort(reason="import_complete")
        else:
            # Fallback: Erstelle YAML-Eintrag, falls kein Master existiert
            return self.async_create_entry(
                title="Imported from YAML",
                data={"type": "yaml", "groups": groups}
            )

    async def async_step_user(self, user_input=None):
        """
        Standard-"user"-Flow: Ermöglicht manuell das Anlegen einer Gruppe 
        oder auch einen neuen "master".
        """
        if user_input is not None:
            chosen_type = user_input[CONF_TYPE]
            if chosen_type == "master":
                # Manuell einen Master erzeugen
                return await self.async_step_master()
            if chosen_type == "group":
                return await self.async_step_group()

        schema = vol.Schema({
            vol.Required(CONF_TYPE): vol.In(["group", "master"])
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_master(self, user_input=None):
        """
        Falls man manuell einen Master-Entry anlegen möchte.
        """
        if user_input is not None:
            delay_val = user_input.get(CONF_DELAY, DEFAULT_DELAY)
            await self.async_set_unique_id("master")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title="Global Delay Settings",
                data={
                    CONF_TYPE: "master",
                    CONF_DELAY: delay_val,
                }
            )

        schema = vol.Schema({
            vol.Required(CONF_DELAY, default=DEFAULT_DELAY): cv.positive_int
        })
        return self.async_show_form(step_id="master", data_schema=schema)

    async def async_step_group(self, user_input=None):
        """
        Flow-Schritt zum Anlegen einer UI-Gruppe (Name, Entities).
        """
        errors = {}
        if user_input is not None:
            name = user_input[CONF_NAME]
            entities = user_input[CONF_ENTITIES]
            return self.async_create_entry(
                title=name,
                data={
                    CONF_TYPE: "group",
                    CONF_NAME: name,
                    CONF_ENTITIES: entities,
                },
            )

        all_lights = await _async_get_all_light_entities(self.hass)
        schema = vol.Schema({
            vol.Required(CONF_NAME): cv.string,
            vol.Required(CONF_ENTITIES): cv.multi_select(all_lights),
        })
        return self.async_show_form(step_id="group", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        """
        Verknüpft den OptionsFlow für bestehende Einträge (Master oder Gruppen).
        """
        return LightGroupDimmerOptionsFlow(config_entry)


class LightGroupDimmerOptionsFlow(config_entries.OptionsFlow):
    """
    OptionsFlow zum nachträglichen Bearbeiten:
      - Master => Delay ändern (sofern nicht YAML aktiv)
      - Gruppe => Name/Entities ändern
      - YAML => nicht editierbar
    """
    def __init__(self, config_entry: config_entries.ConfigEntry):
        self._entry_id = config_entry.entry_id

    async def async_step_init(self, user_input=None):
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if not entry:
            return self.async_abort(reason="entry_not_found")

        entry_type = entry.data.get(CONF_TYPE)

        if entry_type == "master":
            return await self.async_step_master_options(user_input)
        elif entry_type == "yaml":
            return self.async_abort(reason="yaml_not_editable")
        elif entry_type == "group":
            return await self.async_step_group_options(user_input)
        else:
            return self.async_abort(reason="unknown_type")

    async def async_step_master_options(self, user_input=None):
        """
        Wenn YAML aktiv ist, darf man Delay nicht ändern (read-only).
        Ansonsten kann man Delay frei anpassen.
        """
        if self.hass.data[DOMAIN].get("yaml_config"):
            yaml_delay = self.hass.data[DOMAIN].get(CONF_DELAY, DEFAULT_DELAY)
            schema = vol.Schema({
                vol.Required(CONF_DELAY, default=str(yaml_delay)): vol.In([str(yaml_delay)])
            })
            return self.async_show_form(
                step_id="master_options",
                data_schema=schema,
                description_placeholders={"info": "Der Delay-Wert wird durch YAML gesetzt und kann nicht geändert werden."}
            )

        # Kein YAML => user_input auswerten
        if user_input is not None:
            new_delay = user_input.get(CONF_DELAY, DEFAULT_DELAY)
            return self.async_create_entry(
                title="",
                data={CONF_DELAY: new_delay},
            )

        # Aktuellen Delay auslesen
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        current_delay = entry.options.get(
            CONF_DELAY,
            entry.data.get(CONF_DELAY, DEFAULT_DELAY)
        )
        schema = vol.Schema({
            vol.Required(CONF_DELAY, default=current_delay): cv.positive_int,
        })
        return self.async_show_form(step_id="master_options", data_schema=schema)

    async def async_step_group_options(self, user_input=None):
        """
        Gruppen-OptionsFlow:
        Name + Entities lassen sich anpassen. 
        Gespeichert wird in entry.options => Reload => Auswertung im __init__.py
        """
        entry = self.hass.config_entries.async_get_entry(self._entry_id)

        if user_input is not None:
            new_name = user_input.get(CONF_NAME)
            new_entities = user_input.get(CONF_ENTITIES, [])
            return self.async_create_entry(
                title="",
                data={
                    CONF_NAME: new_name,
                    CONF_ENTITIES: new_entities
                },
            )

        # Defaults: entweder aus entry.options oder aus entry.data
        current_name = entry.options.get(CONF_NAME, entry.data.get(CONF_NAME, "???"))
        current_entities = entry.options.get(CONF_ENTITIES, entry.data.get(CONF_ENTITIES, []))

        all_lights = await _async_get_all_light_entities(self.hass)
        schema = vol.Schema({
            vol.Required(CONF_NAME, default=current_name): cv.string,
            vol.Required(CONF_ENTITIES, default=current_entities): cv.multi_select(all_lights),
        })
        return self.async_show_form(step_id="group_options", data_schema=schema)


async def _async_get_all_light_entities(hass: HomeAssistant):
    """
    Sammelt alle registrierten Light-Entities im Entity Registry,
    sortiert sie alphabetisch (Original-Name).
    """
    ent_reg = er.async_get(hass)
    light_entities = {
        entity.entity_id: entity.original_name or entity.entity_id
        for entity in ent_reg.entities.values()
        if entity.domain == "light"
    }
    # Alphabetisch (case-insensitiv) sortieren
    sorted_entities = dict(
        sorted(light_entities.items(), key=lambda item: item[1].lower())
    )
    return sorted_entities
