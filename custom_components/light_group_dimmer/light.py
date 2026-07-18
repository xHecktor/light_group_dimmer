import logging
import asyncio
import time
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_XY_COLOR,
    LightEntity,
    ColorMode,
    LightEntityFeature
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.start import async_at_start
from homeassistant.helpers import entity_registry as er
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN, CONF_TYPE, CONF_NAME, CONF_ENTITIES, CONF_DELAY, DEFAULT_DELAY
from .brightness import compute_target_brightnesses

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Kompatibilität, falls alte discovery genutzt wird (wird oft leer gelassen)."""
    _LOGGER.debug("Starte async_setup_platform für Light Group Dimmer (legacy).")
    return


async def _async_migrate_unique_id(hass: HomeAssistant, name: str, new_uid: str):
    """
    Migriert die frühere namensbasierte unique_id einer UI-Gruppe auf die
    stabile entry_id, ohne die Entity (samt Historie/Automationen) zu verlieren.
    """
    old_uid = f"light_group_{name.replace(' ', '_').lower()}"
    if old_uid == new_uid:
        return
    registry = er.async_get(hass)
    ent_id = registry.async_get_entity_id("light", DOMAIN, old_uid)
    if ent_id and not registry.async_get_entity_id("light", DOMAIN, new_uid):
        _LOGGER.info("Migriere unique_id '%s' -> '%s' für Entity %s", old_uid, new_uid, ent_id)
        registry.async_update_entity(ent_id, new_unique_id=new_uid)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    _LOGGER.debug("Starte async_setup_entry für Light Group Dimmer (entry_id=%s).", entry.entry_id)

    # 1) Hole den 'type' dieses Eintrags (z. B. 'yaml', 'group', 'master' ...)
    entry_type = entry.data.get(CONF_TYPE)

    # 2) Bestimme, welche Gruppen zu diesem Entry gehören
    if entry_type == "yaml":
        groups_data = entry.data.get("groups", [])
    elif entry_type == "group":
        group_name = entry.options.get(CONF_NAME, entry.data.get(CONF_NAME))
        group_entities = entry.options.get(CONF_ENTITIES, entry.data.get(CONF_ENTITIES, []))
        groups_data = [{
            "name": group_name,
            "entities": group_entities
        }]
    elif entry_type == "master":
        if "groups" in entry.data and entry.data.get("groups"):
            groups_data = entry.data.get("groups", [])
            _LOGGER.debug("Master-Eintrag enthält YAML-Gruppen: %s", groups_data)
        else:
            groups_data = []
            _LOGGER.debug("Master-Eintrag erzeugt keine Light-Gruppen.")
    else:
        groups_data = []
        _LOGGER.warning("Unbekannter entry_type: %s", entry_type)

    _LOGGER.debug("Gefundene Gruppen für dieses Entry: %s", groups_data)

    # 3) Delay-Wert auslesen
    delay_value = hass.data[DOMAIN].get(CONF_DELAY, DEFAULT_DELAY)
    _LOGGER.debug("Verwende Delay=%s für dieses Entry.", delay_value)

    # 4) Aus den Gruppen CustomLightGroup-Entities bauen
    entities = []
    for group in groups_data:
        name = group["name"]
        lights = group["entities"]
        if not lights:
            _LOGGER.warning("Gruppe %s hat keine Lichter definiert, wird übersprungen.", name)
            continue

        # UI-Gruppen: stabile unique_id über die entry_id (überlebt Umbenennen).
        # YAML-Gruppen: weiterhin namensbasiert (kein stabilerer Schlüssel vorhanden).
        if entry_type == "group":
            unique_id = entry.entry_id
            await _async_migrate_unique_id(hass, name, unique_id)
        else:
            unique_id = f"light_group_{name.replace(' ', '_').lower()}"

        _LOGGER.debug("Erstelle LightGroupEntity: %s (Entitäten: %s, unique_id=%s)", name, lights, unique_id)
        entities.append(CustomLightGroup(name, lights, hass, unique_id, delay_value))

    if entities:
        async_add_entities(entities)
        _LOGGER.info("%d Lichtgruppen für Entry '%s' hinzugefügt.", len(entities), entry.title)
    else:
        _LOGGER.info("Keine (neuen) gültigen Gruppen in Entry '%s' gefunden.", entry.title)


class CustomLightGroup(LightEntity):
    # Die Gruppe ist vollständig event-getrieben (Listener auf alle Mitglieder),
    # daher kein Polling durch Home Assistant.
    _attr_should_poll = False

    def __init__(self, name, entities, hass, unique_id, delay):
        """Initialisiere die benutzerdefinierte Lichtgruppe."""
        self._color_temp_kelvin = None
        self._attr_min_color_temp_kelvin = 2000
        self._attr_max_color_temp_kelvin = 6500

        self._name = name
        self._unique_id = unique_id
        # Doppelte Einträge entfernen (reihenfolgetreu): sonst zählt eine mehrfach
        # gelistete Lampe doppelt in den Mittelwert und bekommt doppelte Service-Calls.
        self._entities = list(dict.fromkeys(entities))
        if len(self._entities) != len(entities):
            _LOGGER.debug(
                "Doppelte Entitäten in Gruppe '%s' entfernt: %s -> %s",
                name, entities, self._entities,
            )
        self._special_case = True  # Flag für den Spezialfall (Farb-Transformation)
        self._brightness = 0
        self._hs_color = (0, 0)
        self._effect = None
        self._effect_list = []
        self._is_on = False
        self._color_mode = None
        self._rgb_color = None
        self._xy_color = None
        self.hass = hass
        self._icon = "mdi:lightbulb-group"
        self._supported_color_modes = set()
        self._supported_features = LightEntityFeature.EFFECT
        self._update_scheduled = False
        self._update_pending = False
        # Optimistische Gruppenhelligkeit: hält den angezeigten Wert während eines
        # selbst ausgelösten Kommandos auf dem Zielwert, damit der Regler nicht durch
        # die Zwischenmittelwerte der nacheinander meldenden Lampen springt.
        self._optimistic_brightness = None
        self._optimistic_until = 0.0
        self._optimistic_task = None
        self._brightness_cache = {}  # {group_id: {"group_brightness", "lamp_brightnesses", "timer"}}
        _LOGGER.debug(f"Initialisiere Lichtgruppe: {self._name} mit Entitäten: {self._entities}")

    async def async_added_to_hass(self):
        """Wird aufgerufen, wenn die Entity zum System hinzugefügt wird."""
        _LOGGER.debug("Registriere Listener für Lichtgruppe: %s", self._name)
        for entity_id in self._entities:
            # async_on_remove sorgt dafür, dass die Listener beim Entfernen/Reload
            # der Gruppe sauber wieder abgemeldet werden (kein Memory-Leak).
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, entity_id, self._handle_light_change
                )
            )

        await self._initialize_supported_color_modes()
        await self.async_update()

        # Kein Warten auf die Mitglieds-Integrationen: Sobald deren Lampen (z. B. über
        # die Hue-Bridge) States bekommen, feuern die Listener und die Gruppe füllt sich.
        # Zusätzlich einmal nachziehen, wenn HA vollständig gestartet ist.
        self.async_on_remove(async_at_start(self.hass, self._async_on_ha_start))

        # Beim Entfernen/Reload einen evtl. laufenden Reconcile-Task abbrechen.
        self.async_on_remove(self._clear_optimistic_brightness)

    async def _async_on_ha_start(self, _hass):
        """Nach vollständigem HA-Start erneut aktualisieren (spät registrierte Lampen)."""
        await self.async_update()

    async def _initialize_supported_color_modes(self):
        """Initialisiere die unterstützten Farbmodi basierend auf den Entitäten."""
        supported_modes = set()
        for entity_id in self._entities:
            state = self.hass.states.get(entity_id)
            if state and "supported_color_modes" in state.attributes:
                supported_modes.update(state.attributes["supported_color_modes"])

        # Filtere ungültige Modi
        valid_modes = {"color_temp", "xy", "hs", "brightness", "onoff", "rgb", "rgbw", "rgbww"}
        supported_modes = {mode for mode in supported_modes if mode in valid_modes}

        # Entferne 'onoff', wenn es andere Modi gibt
        if "onoff" in supported_modes and len(supported_modes) > 1:
            supported_modes.discard("onoff")

        if "xy" in supported_modes and "color_temp" in supported_modes:
            _LOGGER.debug("Kombination (xy, color_temp) gefunden. Wandle xy -> hs.")
            supported_modes.discard("xy")
            supported_modes.add("hs")

        has_color = any(m in supported_modes for m in ("hs", "rgb", "rgbw", "rgbww", "xy"))
        if has_color or "color_temp" in supported_modes:
            if "brightness" in supported_modes:
                _LOGGER.debug("Entferne brightness, weil wir (Farbe oder color_temp) haben.")
                supported_modes.discard("brightness")

        self._supported_color_modes = supported_modes

    async def _update_color_mode(self):
        """Aktualisiere den aktiven Farbmodus basierend auf den eingeschalteten Lampen."""
        active_modes = set()
        for entity_id in self._entities:
            state = self.hass.states.get(entity_id)
            if state and state.state == "on" and "color_mode" in state.attributes:
                active_modes.add(state.attributes["color_mode"])

        if active_modes:
            if "hs" in active_modes:
                self._color_mode = ColorMode.HS
            elif "xy" in active_modes:
                self._color_mode = ColorMode.XY
            elif "color_temp" in active_modes:
                self._color_mode = ColorMode.COLOR_TEMP
            elif "brightness" in active_modes:
                self._color_mode = ColorMode.BRIGHTNESS
            else:
                self._color_mode = ColorMode.HS
        else:
            self._color_mode = None

    @property
    def delay(self):
        """Liefert den aktuellen Delay-Wert dynamisch ab, auch aus YAML, falls gesetzt."""
        return self.hass.data[DOMAIN].get(CONF_DELAY, DEFAULT_DELAY)

    @property
    def supported_color_modes(self):
        """Gibt die unterstützten Farbmodi der Lichtgruppe an."""
        if not self._supported_color_modes:
            return {ColorMode.ONOFF}
        return self._supported_color_modes

    @property
    def name(self):
        """Name der Lichtgruppe."""
        return self._name

    @property
    def unique_id(self):
        """Eindeutige ID der Lichtgruppe."""
        return self._unique_id

    @property
    def is_on(self):
        """Status der Lichtgruppe."""
        return self._is_on

    @property
    def brightness(self):
        """Helligkeit der Lichtgruppe."""
        return self._brightness

    @property
    def hs_color(self):
        """Farbe der Lichtgruppe im HS-Farbraum."""
        return self._hs_color

    @property
    def color_temp_kelvin(self):
        return self._color_temp_kelvin

    @color_temp_kelvin.setter
    def color_temp_kelvin(self, value):
        self._color_temp_kelvin = value

    @property
    def min_color_temp_kelvin(self):
        return self._attr_min_color_temp_kelvin

    @property
    def max_color_temp_kelvin(self):
        return self._attr_max_color_temp_kelvin

    @property
    def effect(self):
        """Aktueller Effekt der Lichtgruppe."""
        return self._effect

    @property
    def effect_list(self):
        """Liste der verfügbaren Effekte."""
        return self._effect_list

    @property
    def color_mode(self):
        """Aktiver Farbmodus der Lichtgruppe."""
        return self._color_mode

    @property
    def supported_features(self):
        """Gibt die unterstützten Features der Lichtgruppe an."""
        return self._supported_features

    @property
    def icon(self):
        """Icon der Lichtgruppe."""
        return self._icon

    @property
    def extra_state_attributes(self):
        """
        Zusätzliche Attribute für die Lichtgruppe.
        Nur die Mitgliederliste – alle übrigen Werte (brightness, hs_color,
        color_mode, ...) liefert LightEntity bereits über die Properties und
        filtert sie passend zum aktiven color_mode.
        """
        return {
            "entity_id": self._entities,
        }

    async def async_update(self):
        """Aktualisiere den Status und die Attribute der Lichtgruppe."""
        states = [self.hass.states.get(entity_id) for entity_id in self._entities if self.hass.states.get(entity_id)]

        # Aktualisiere den EIN/AUS-Status
        self._is_on = any(state.state == "on" for state in states if state)

        # Sammle Helligkeitswerte (nur dimmbare, eingeschaltete Lampen)
        brightness_values = [
            state.attributes.get(ATTR_BRIGHTNESS, 0)
            for state in states if state and state.state == "on" and ATTR_BRIGHTNESS in state.attributes and state.attributes.get(ATTR_BRIGHTNESS) is not None
        ]
        computed_brightness = round(sum(brightness_values) / len(brightness_values)) if brightness_values else 0
        # Während des Settle-Fensters den kommandierten Zielwert halten, sonst den
        # echten Ist-Mittelwert übernehmen (verhindert das Springen des Reglers).
        if self._optimistic_brightness is not None and time.monotonic() < self._optimistic_until:
            # Früh-Löser: Sobald der echte Mittelwert nahe genug am Zielwert ist,
            # das Pinning sofort beenden (kleine/schnelle Gruppen lösen dann nach
            # ~0,5 s statt fix 2 s). Der Timeout in _reconcile_brightness bleibt als
            # Obergrenze, falls eine Lampe gar nicht (mehr) meldet -> kein Einfrieren.
            if abs(computed_brightness - self._optimistic_brightness) <= self._OPTIMISTIC_TOLERANCE:
                self._optimistic_brightness = None
                self._brightness = computed_brightness
            else:
                self._brightness = self._optimistic_brightness
        else:
            self._optimistic_brightness = None
            self._brightness = computed_brightness

        # Farbtemperatur direkt in Kelvin (HA-Standard seit 2024.12; Hue liefert nur noch Kelvin)
        kelvin_values = [
            state.attributes.get(ATTR_COLOR_TEMP_KELVIN)
            for state in states if state and state.state == "on" and state.attributes.get(ATTR_COLOR_TEMP_KELVIN)
        ]
        if kelvin_values:
            self._color_temp_kelvin = int(round(sum(kelvin_values) / len(kelvin_values)))
        else:
            self._color_temp_kelvin = None

        # Sammle HS-Farben
        hs_colors = [
            state.attributes.get(ATTR_HS_COLOR)
            for state in states if state and state.state == "on" and ATTR_HS_COLOR in state.attributes and state.attributes.get(ATTR_HS_COLOR) is not None
        ]
        self._hs_color = hs_colors[0] if hs_colors else None

        # Sammle RGB-Farben (falls verfügbar)
        rgb_colors = [
            state.attributes.get("rgb_color")
            for state in states if state and state.state == "on" and "rgb_color" in state.attributes and state.attributes.get("rgb_color") is not None
        ]
        self._rgb_color = rgb_colors[0] if rgb_colors else None

        # Sammle XY-Farben
        xy_colors = [
            state.attributes.get(ATTR_XY_COLOR)
            for state in states if state and state.state == "on" and ATTR_XY_COLOR in state.attributes and state.attributes.get(ATTR_XY_COLOR) is not None
        ]
        self._xy_color = xy_colors[0] if xy_colors else None

        # --- Spezialfall: Transformiere Farbwerte nur zur Anzeige ---
        if self._special_case:
            self._hs_color, self._rgb_color, self._xy_color = self._transform_special(
                self._hs_color, self._rgb_color, self._xy_color
            )

        # Sammle unterstützte Farbmodi
        self._supported_color_modes = set()
        for state in states:
            if ATTR_SUPPORTED_COLOR_MODES in state.attributes:
                self._supported_color_modes.update(state.attributes[ATTR_SUPPORTED_COLOR_MODES])

        # Entferne 'onoff', wenn andere Farbmodi verfügbar sind
        if ColorMode.ONOFF in self._supported_color_modes and len(self._supported_color_modes) > 1:
            self._supported_color_modes.discard(ColorMode.ONOFF)

        if "xy" in self._supported_color_modes and "color_temp" in self._supported_color_modes:
            _LOGGER.debug("Kombination (xy, color_temp) im Laufzeit-Update gefunden. Ersetze xy -> hs.")
            self._supported_color_modes.discard("xy")
            self._supported_color_modes.add("hs")

        has_color = any(m in self._supported_color_modes for m in ("hs", "rgb", "rgbw", "rgbww", "xy"))
        if has_color or "color_temp" in self._supported_color_modes:
            if "brightness" in self._supported_color_modes:
                _LOGGER.debug("Entferne brightness, weil wir (Farbe oder color_temp) haben.")
                self._supported_color_modes.discard("brightness")

        # Bestimme den Farbmodus basierend auf verfügbaren Attributen
        if self._color_temp_kelvin and ColorMode.COLOR_TEMP in self._supported_color_modes:
            self._color_mode = ColorMode.COLOR_TEMP
        elif self._hs_color and ColorMode.HS in self._supported_color_modes:
            self._color_mode = ColorMode.HS
        elif self._xy_color and ColorMode.XY in self._supported_color_modes:
            self._color_mode = ColorMode.XY
        elif self._brightness and ColorMode.BRIGHTNESS in self._supported_color_modes:
            self._color_mode = ColorMode.BRIGHTNESS
        else:
            if ColorMode.ONOFF in self._supported_color_modes:
                self._color_mode = ColorMode.ONOFF
            elif ColorMode.BRIGHTNESS in self._supported_color_modes:
                self._color_mode = ColorMode.BRIGHTNESS
            else:
                self._color_mode = next(iter(self._supported_color_modes), ColorMode.ONOFF)

        # Sammle Effekte
        effects = [
            state.attributes.get(ATTR_EFFECT)
            for state in states if state and state.state == "on" and ATTR_EFFECT in state.attributes and state.attributes.get(ATTR_EFFECT) is not None
        ]
        self._effect = effects[0] if effects else None

        # Sammle Effektlisten
        effect_lists = [
            state.attributes.get("effect_list", [])
            for state in states if state
        ]
        self._effect_list = sorted({effect for effect_list in effect_lists for effect in effect_list}) if effect_lists else []

        # Erzwinge Statusaktualisierung in Home Assistant
        self.async_write_ha_state()

    def _transform_special(self, hs_color, rgb_color, xy_color):
        """
        Transformiert die Farbwerte nur für die Anzeige in HA.
        Beispiel:
          Ursprüngliche Werte:
            hs_color: [54.768, 1.6]
            rgb_color: [255, 255, 251]
            xy_color: [0.325, 0.333]
          Angezeigte Werte:
            hs_color: [27.028, 18.905]
            rgb_color: [255, 229, 207]
            xy_color: [0.37, 0.35]
        """
        _LOGGER.debug("Transformiere Spezialfall: hs_color=%s, rgb_color=%s, xy_color=%s", hs_color, rgb_color, xy_color)
        if isinstance(rgb_color, tuple):
            rgb_color = list(rgb_color)
        if rgb_color == [255, 255, 251]:
            return [27.028, 18.905], [255, 229, 207], [0.37, 0.35]
        return hs_color, rgb_color, xy_color

    def is_group_on(self):
        """Berechnet dynamisch, ob die Gruppe eingeschaltet ist."""
        for entity_id in self._entities:
            state = self.hass.states.get(entity_id)
            if state and state.state == "on":
                return True
        return False

    def _is_dimmable(self, state):
        """True, wenn die Lampe dimmbar ist (Steckdosen o. Ä. sind es nicht)."""
        if not state:
            return False
        return (
            ATTR_BRIGHTNESS in state.attributes
            or "brightness" in state.attributes.get(ATTR_SUPPORTED_COLOR_MODES, [])
        )

    async def async_turn_on(self, **kwargs):
        """
        Schalte die Gruppe ein und verarbeite optional Helligkeit/Farben/Effekte.
        Enthält die gewichtete Helligkeitsberechnung mit Cache.
        """
        self._is_on = True

        new_brightness = kwargs.get(ATTR_BRIGHTNESS, None)
        new_xy_color = kwargs.get(ATTR_XY_COLOR, None)
        new_hs_color = kwargs.get(ATTR_HS_COLOR, None)
        new_kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        if new_kelvin:
            self._color_temp_kelvin = new_kelvin
        new_effect = kwargs.get(ATTR_EFFECT, None)

        # Optimistisch: die eigene Gruppen-Entity sofort aktualisieren, damit die UI
        # reagiert. Bei einer Helligkeitsänderung den Zielwert pinnen (kein Springen
        # des Reglers). Echte Lampen-States kommen anschließend per Event zurück.
        if new_brightness is not None:
            self._pin_optimistic_brightness(new_brightness)
        self.async_write_ha_state()

        group_is_on = self.is_group_on()

        only_brightness_requested = (
            new_brightness is not None
            and new_xy_color is None
            and new_hs_color is None
            and new_kelvin is None
            and new_effect is None
        )

        # Ist irgendeine dimmbare Lampe tatsächlich an?
        dimmable_on = any(
            self._is_dimmable(self.hass.states.get(entity_id))
            and (self.hass.states.get(entity_id) and self.hass.states.get(entity_id).state == "on")
            for entity_id in self._entities
        )

        # Spezialfall: Gruppe (dimmbar) aus + ausschließlich Helligkeit -> alle Lampen
        # einschalten und Helligkeit setzen. Steckdosen bekommen nur ein reines turn_on.
        treat_as_off = (not group_is_on) or (not dimmable_on)
        if treat_as_off and only_brightness_requested:
            _LOGGER.debug(
                f"[Spezialfall] Gruppe '{self._name}' hat keine dimmbare Lampe an. "
                f"Schalte alle Lampen ein und setze Helligkeit auf {new_brightness}."
            )
            service_data_list = []
            for entity_id in self._entities:
                state = self.hass.states.get(entity_id)
                if not state or state.state in ("unavailable", "unknown"):
                    _LOGGER.debug(f"Lampe {entity_id} ist unavailable/unknown. Überspringe sie.")
                    continue
                if self._is_dimmable(state):
                    service_data_list.append({"entity_id": entity_id, ATTR_BRIGHTNESS: new_brightness})
                else:
                    # Steckdose / On-Off-Gerät: keine Helligkeit mitschicken
                    service_data_list.append({"entity_id": entity_id})

            await self._async_call_turn_on(service_data_list)
            await self.async_update()
            return

        # Sonderfall: sehr niedrige Helligkeit (<=3) => alle aktiven dimmbaren Lampen
        # exakt auf diesen Wert setzen (ohne Gewichtung).
        if new_brightness is not None and new_brightness <= 3:
            _LOGGER.debug(f"[1%%-Override] Setze alle aktiven Lampen exakt auf {new_brightness}.")
            service_data_list = []
            for entity_id in self._entities:
                state = self.hass.states.get(entity_id)
                if not state or state.state in ("off", "unavailable", "unknown"):
                    continue
                if self._is_dimmable(state):
                    service_data_list.append({"entity_id": entity_id, ATTR_BRIGHTNESS: new_brightness})
            service_data_list.extend(
                self._build_color_service_data(new_xy_color, new_hs_color, new_kelvin, new_effect)
            )
            await self._async_call_turn_on(service_data_list)
            await self.async_update()
            return

        # ================= Gewichtete Helligkeits-Logik (Cache) =================
        if new_brightness is not None:
            _LOGGER.debug(f"[Cache] Manuelle Helligkeitsänderung erkannt: Ziel={new_brightness}")

            cached_data = self.get_brightness_cache(self._name)
            if not cached_data:
                _LOGGER.debug(f"[Cache] Kein Cache vorhanden. Erstelle neuen Cache für '{self._name}'")
                self.store_brightness_cache(self._name)
                cached_data = self.get_brightness_cache(self._name)
            else:
                _LOGGER.debug("[Cache] Cache existiert bereits, Timer wird zurückgesetzt.")
                self.reset_brightness_cache_timer(self._name)

            old_lamp_brightnesses = cached_data["lamp_brightnesses"]  # {entity_id: brightness}
            _LOGGER.debug(f"[Cache] Verwende aus Cache für '{self._name}': {old_lamp_brightnesses}")

            # Geschlossene (nicht-iterative) Berechnung der Ziel-Helligkeiten
            adjusted = self._compute_target_brightnesses(dict(old_lamp_brightnesses), new_brightness)

            service_data_list = []
            for entity_id, adj_brightness in adjusted.items():
                state = self.hass.states.get(entity_id)
                if not state or state.state in ("off", "unavailable", "unknown"):
                    _LOGGER.debug(f"Lampe {entity_id} ist aus/nicht verfügbar. Überspringe.")
                    continue
                service_data_list.append({"entity_id": entity_id, ATTR_BRIGHTNESS: adj_brightness})

            # Farben/Effekte + neue Kelvin-Farbtemperatur verarbeiten
            service_data_list.extend(
                self._build_color_service_data(new_xy_color, new_hs_color, new_kelvin, new_effect)
            )
            await self._async_call_turn_on(service_data_list)

        else:
            # Kein new_brightness => Farben/Effekt oder nur Einschalten
            _LOGGER.debug("Kein new_brightness => normales Einschalten oder nur Farbe/Effekt setzen.")

            service_data_list = self._build_color_service_data(
                new_xy_color, new_hs_color, self._color_temp_kelvin, new_effect
            )

            is_simple_turn_on = all(
                x is None for x in [new_brightness, new_xy_color, new_hs_color, new_kelvin, new_effect]
            )
            if is_simple_turn_on and not service_data_list:
                service_data_list = [{"entity_id": e} for e in self._entities]

            await self._async_call_turn_on(service_data_list)

        await self.async_update()

    async def _async_call_turn_on(self, service_data_list):
        """Ruft light.turn_on parallel für alle vorbereiteten Service-Daten auf."""
        tasks = [
            self.hass.services.async_call("light", "turn_on", data)
            for data in service_data_list
        ]
        if tasks:
            await asyncio.gather(*tasks)

    # Settle-Fenster: etwas mehr als eine typische Hue-Transition plus Event-Latenz.
    # Dient als harte Obergrenze; die Anzeige wird i. d. R. früher gelöst (siehe unten).
    _OPTIMISTIC_SETTLE_SECONDS = 2.0
    # Toleranz für das Früh-Lösen: liegt der echte Mittelwert so nah (0..255) am
    # Zielwert, gilt die Gruppe als "angekommen" (~2 % von 255).
    _OPTIMISTIC_TOLERANCE = 5

    def _pin_optimistic_brightness(self, value):
        """
        Zeigt die kommandierte Gruppenhelligkeit sofort an und hält sie für ein kurzes
        Settle-Fenster, damit der Regler nicht durch die Zwischenmittelwerte der
        nacheinander meldenden Lampen springt. Betrifft nur die eigene Anzeige der
        Gruppe – es werden keine fremden Lampen-States geschrieben.
        """
        self._optimistic_brightness = value
        self._brightness = value
        self._optimistic_until = time.monotonic() + self._OPTIMISTIC_SETTLE_SECONDS
        if self._optimistic_task:
            self._optimistic_task.cancel()
        self._optimistic_task = self.hass.async_create_task(self._reconcile_brightness())

    def _clear_optimistic_brightness(self):
        """Beendet das Pinnen (z. B. beim Ausschalten)."""
        self._optimistic_brightness = None
        self._optimistic_until = 0.0
        if self._optimistic_task:
            self._optimistic_task.cancel()
            self._optimistic_task = None

    async def _reconcile_brightness(self):
        """Übernimmt nach Ablauf des Settle-Fensters wieder den echten Ist-Mittelwert."""
        try:
            await asyncio.sleep(self._OPTIMISTIC_SETTLE_SECONDS + 0.1)
            self._optimistic_brightness = None
            self._optimistic_task = None
            await self.async_update()
        except asyncio.CancelledError:
            pass

    async def async_turn_off(self, **kwargs):
        """Schalte die ganze Gruppe aus."""
        self._is_on = False
        # Optimistisch: Gruppe sofort als "aus" melden, damit der Helligkeitsbalken
        # nicht auf die Bestätigung der Lampen warten muss.
        self._clear_optimistic_brightness()
        self.async_write_ha_state()

        tasks = []
        for entity_id in self._entities:
            state = self.hass.states.get(entity_id)
            if not state or state.state in ("off", "unavailable", "unknown"):
                _LOGGER.debug(f"{entity_id} ist bereits aus oder nicht verfügbar.")
                continue
            tasks.append(self.hass.services.async_call("light", "turn_off", {"entity_id": entity_id}))

        if tasks:
            await asyncio.gather(*tasks)
        await self.async_update()

    async def _handle_light_change(self, event):
        """Wird getriggert, wenn sich eine einzelne Lampe ändert."""
        _LOGGER.debug(f"Lichtänderung erkannt: {event}")

        # Bewusst KEIN Zurücksetzen des Cache-Timers hier: Der Baseline im Cache ist
        # eingefroren (store_brightness_cache), die Lampen-Rückmeldungen nach einem
        # Slider-Zug ändern ihn nicht. Ein Reset würde das Fenster nur um die Settle-
        # Zeit der Lampen verlängern (und mit der Gruppengröße skalieren). Der Delay
        # soll die Ruhezeit NACH dem letzten Slider-Befehl messen – die Resets dafür
        # sitzen in store_brightness_cache und im async_turn_on-Befehlspfad.

        # Läuft bereits ein Update, Event nicht verwerfen, sondern nachholen.
        if self._update_scheduled:
            self._update_pending = True
            return

        self._update_scheduled = True
        try:
            await self.async_update()
            while self._update_pending:
                self._update_pending = False
                await self.async_update()
        finally:
            self._update_scheduled = False
        _LOGGER.debug(f"Lichtänderung für '{self._name}' verarbeitet.")

    # ----------------------------------------------------------
    #               CACHING-FUNKTIONEN
    # ----------------------------------------------------------
    def store_brightness_cache(self, group_id):
        """Erzeugt einen neuen Cache-Eintrag auf Basis der aktuellen IST-Werte."""
        lamp_brightnesses = {}
        active_vals = []

        for entity_id in self._entities:
            state = self.hass.states.get(entity_id)
            if state and state.state == "on":
                val = state.attributes.get(ATTR_BRIGHTNESS, 0)
                lamp_brightnesses[entity_id] = val
                if val > 0:
                    active_vals.append(val)

        old_group_brightness = sum(active_vals) / len(active_vals) if active_vals else 0

        self.clear_brightness_cache(group_id)
        self._brightness_cache[group_id] = {
            "group_brightness": old_group_brightness,
            "lamp_brightnesses": lamp_brightnesses,
            "timer": None
        }
        _LOGGER.debug(
            f"[Cache] Neuer Cache angelegt für '{group_id}': group_brightness={old_group_brightness}, "
            f"lamp_brightnesses={lamp_brightnesses}"
        )
        self.reset_brightness_cache_timer(group_id, log_reason="Neuanlage")

    def reset_brightness_cache_timer(self, group_id, log_reason="Reset"):
        """Setzt den Delay-Timer zurück, damit der Cache nicht gelöscht wird."""
        entry = self._brightness_cache.get(group_id)
        if not entry:
            return
        if entry["timer"]:
            entry["timer"].cancel()
        entry["timer"] = asyncio.create_task(self._clear_cache_after_delay(group_id, self.delay))
        _LOGGER.debug(f"[Cache] Timer zurückgesetzt (Grund: {log_reason}) für Gruppe '{group_id}'")

    async def _clear_cache_after_delay(self, group_id, delay):
        """Wartet 'delay' Sekunden und löscht dann den Cache, wenn nichts Neues passiert."""
        try:
            _LOGGER.debug(f"[Cache] Starte {delay}s-Timer, um Cache für '{group_id}' zu löschen.")
            await asyncio.sleep(delay)
            self.clear_brightness_cache(group_id)
            _LOGGER.debug(f"[Cache] Cache für '{group_id}' ist abgelaufen und wurde gelöscht.")
        except asyncio.CancelledError:
            _LOGGER.debug(f"[Cache] Timer für '{group_id}' wurde abgebrochen.")
            raise

    def clear_brightness_cache(self, group_id):
        """Cache-Eintrag für group_id entfernen, wenn vorhanden."""
        if group_id in self._brightness_cache:
            timer_task = self._brightness_cache[group_id].get("timer")
            if timer_task:
                timer_task.cancel()
            del self._brightness_cache[group_id]
            _LOGGER.debug(f"[Cache] remove: Cache für '{group_id}' entfernt.")

    def get_brightness_cache(self, group_id):
        """Liefert den Cache-Eintrag für group_id oder None."""
        return self._brightness_cache.get(group_id)

    # ----------------------------------------------------------
    #   Geschlossene Berechnung der Ziel-Helligkeiten
    # ----------------------------------------------------------
    def _compute_target_brightnesses(self, lamp_brightnesses, target_group_brightness):
        """
        Dünner Wrapper um die reine Rechenfunktion (siehe brightness.py) mit Logging.
        Steckdosen / On-Off-Geräte (Helligkeit 0) werden dort ignoriert.
        """
        result = compute_target_brightnesses(lamp_brightnesses, target_group_brightness)
        _LOGGER.debug(f"[Cache] Ziel-Helligkeiten (target={target_group_brightness}): {result}")
        return result

    # ----------------------------------------------------------
    #   Sonstige Helferfunktionen (Farben/Effekte etc.)
    # ----------------------------------------------------------
    def _build_color_service_data(self, xy_color, hs_color, kelvin_temp, effect):
        service_data_list = []
        group_is_on = self.is_group_on()

        # Entscheide einmal, welcher Farbmodus benutzt werden soll
        chosen_color_mode = None
        if hs_color is not None:
            chosen_color_mode = "hs"
        elif xy_color is not None:
            chosen_color_mode = "xy"
        elif kelvin_temp is not None:
            chosen_color_mode = "temp"

        for entity_id in self._entities:
            state = self.hass.states.get(entity_id)
            if group_is_on and (not state or state.state == "off"):
                continue
            if not state or state.state in ("unavailable", "unknown"):
                _LOGGER.debug(f"Lampe {entity_id} ist unavailable/unknown, überspringe Service-Call.")
                continue

            attrs = state.attributes
            modes = attrs.get(ATTR_SUPPORTED_COLOR_MODES, [])
            service_data = {"entity_id": entity_id}

            # Schreibe nur den ausgewählten Farbmodus, sofern die Lampe ihn kann
            if chosen_color_mode == "hs" and ("hs" in modes or ATTR_HS_COLOR in attrs):
                service_data[ATTR_HS_COLOR] = hs_color
            elif chosen_color_mode == "xy" and ("xy" in modes or ATTR_XY_COLOR in attrs):
                service_data[ATTR_XY_COLOR] = xy_color
            elif chosen_color_mode == "temp" and ("color_temp" in modes or ATTR_COLOR_TEMP_KELVIN in attrs):
                service_data[ATTR_COLOR_TEMP_KELVIN] = kelvin_temp

            # Effekt darf mit hinzu
            if effect is not None and (ATTR_EFFECT in attrs or "effect_list" in attrs):
                service_data[ATTR_EFFECT] = effect

            if not group_is_on:
                service_data_list.append(service_data)
            else:
                if len(service_data) > 1:
                    service_data_list.append(service_data)

        return service_data_list
