import logging
import asyncio
import time
from asyncio import CancelledError
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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
#from .const import DOMAIN, CONF_GROUPS, CONF_NAME, CONF_ENTITIES
from .const import DOMAIN, CONF_TYPE, CONF_NAME, CONF_ENTITIES, CONF_DELAY, DEFAULT_DELAY

_LOGGER = logging.getLogger(__name__)
# Direkt nach den Imports oder ganz oben
ATTR_COLOR_TEMP = "color_temp"


def kelvin_to_mired(kelvin: float) -> int:
    """Konvertiert Kelvin -> Mired."""
    return max(1, int(round(1_000_000 / kelvin)))

def mired_to_kelvin(mired: float) -> int:
    """Konvertiert Mired -> Kelvin und begrenzt auf 1000..10000 K."""
    if not mired:
        return 0
    kelvin = int(round(1_000_000 / mired))
    return max(1000, min(kelvin, 10000))



async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Kompatibilität, falls alte discovery genutzt wird (wird oft leer gelassen)."""
    _LOGGER.debug("Starte async_setup_platform für Light Group Dimmer (legacy).")
    # In aktuellen Integrationen normalerweise leer oder deprecated.
    return


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    _LOGGER.debug("Starte async_setup_entry für Light Group Dimmer (entry_id=%s).", entry.entry_id)

    # 1) Hole den 'type' dieses Eintrags (z. B. 'yaml', 'group', 'master' ...)
    entry_type = entry.data.get(CONF_TYPE)

    # 2) Bestimme, welche Gruppen zu diesem Entry gehören
    if entry_type == "yaml":
        # Alle YAML-Gruppen sind in entry.data["groups"]
        groups_data = entry.data.get("groups", [])
    elif entry_type == "group":
        # NEU: Name / Entities zuerst aus entry.options lesen (wenn vorhanden),
        # sonst aus entry.data (Fallback).
        group_name = entry.options.get(CONF_NAME, entry.data.get(CONF_NAME))
        group_entities = entry.options.get(CONF_ENTITIES, entry.data.get(CONF_ENTITIES, []))
        groups_data = [{
            "name": group_name,
            "entities": group_entities
        }]
    elif entry_type == "master":
        # Wenn der Master-Eintrag YAML-Daten enthält, dann verwende sie,
        # ansonsten wie bisher: kein Gruppenimport.
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

        # Unique ID soll so heißen wie angelegt
        unique_id = f"light_group_{name.replace(' ', '_').lower()}"
        # Berechne eine stabile Unique ID (empfohlen, anstatt entry.entry_id zu verwenden)
        #unique_id = f"{DOMAIN}_{name.replace(' ', '_').lower()}"
        _LOGGER.debug("Erstelle LightGroupEntity: %s (Entitäten: %s, unique_id=%s)", name, lights, unique_id)
        entities.append(CustomLightGroup(name, lights, hass, unique_id, delay_value))

    if entities:
        async_add_entities(entities)
        _LOGGER.info("%d Lichtgruppen für Entry '%s' hinzugefügt.", len(entities), entry.title)
    else:
        _LOGGER.info("Keine (neuen) gültigen Gruppen in Entry '%s' gefunden.", entry.title)




class CustomLightGroup(LightEntity):
    def __init__(self, name, entities, hass, unique_id, delay):
        """Initialisiere die benutzerdefinierte Lichtgruppe."""
        self._color_temp_mired = None  # interner Mired-Wert
        # Falls du feste Defaults willst (z. B. 2000 K bis 6500 K):
        self._attr_min_color_temp_kelvin = 2000
        self._attr_max_color_temp_kelvin = 6500

        self._name = name
        self._unique_id = unique_id
        self._entities = entities
        self._special_case = True  # Flag für den Spezialfall
        self._brightness = 0
        self._hs_color = (0, 0)
        self._color_temp = None
        self._effect = None
        self._effect_list = []
        self._is_on = False
        self._color_mode = None
        self._rgb_color = None  # Hinzugefügt
        self._xy_color = None   # Hinzugefügt
        self.hass = hass
        self._icon = "mdi:lightbulb-group"  # Standard-Icon für die Gruppe
        self._supported_color_modes = set()
        self._supported_features = LightEntityFeature.EFFECT
        self._fallback_triggered = False
        self._update_scheduled = False
        self._brightness_cache = {}  # Cache-Format: {group_id: {"timestamp": time, "values": {entity_id: brightness}}}
        self._cache_update_lock = asyncio.Lock()
        self._cancel_task = None  # Task-Referenz zur Abbruchsteuerung
        #self.delay = delay
        _LOGGER.debug(f"Initialisiere Lichtgruppe: {self._name} mit Entitäten: {self._entities}")


    async def async_added_to_hass(self):
        """Wird aufgerufen, wenn die Entity zum System hinzugefügt wird."""
        _LOGGER.debug("Registriere Listener für Lichtgruppe: %s", self._name)
        for entity_id in self._entities:
            async_track_state_change_event(
                self.hass, entity_id, self._handle_light_change
            )
    
        # Anstatt 15s-Warteschleife => entweder ganz weglassen:
        _LOGGER.debug("Keine Wartezeit mehr. Initialisiere supported_color_modes direkt.")
        await self._initialize_supported_color_modes()
        
        # Eventuell einmal initial updaten
        await self.async_update()
        self.async_write_ha_state()


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
            #_LOGGER.debug(f"'onoff' entfernt, da andere Modi unterstützt werden: {supported_modes}")

        if "xy" in supported_modes and "color_temp" in supported_modes:
            _LOGGER.debug(
                "Kombination (xy, color_temp) gefunden. Entferne xy oder wandle xy -> hs."
            )
            supported_modes.discard("xy")
            supported_modes.add("hs")            

        has_color = any(m in self._supported_color_modes for m in ("hs", "rgb", "rgbw", "rgbww", "xy"))
        if has_color or "color_temp" in self._supported_color_modes:
            if "brightness" in self._supported_color_modes:
                _LOGGER.debug("Entferne brightness, weil wir (hs oder color_temp) haben.")
                self._supported_color_modes.discard("brightness")
    
        # Setze die bereinigte Liste
        self._supported_color_modes = supported_modes
    
        # Erzwinge, dass keine andere Methode 'onoff' wieder hinzufügt
        #_LOGGER.debug(f"Finale unterstützte Farbmodi für {self._name}: {self._supported_color_modes}")



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
                #self._color_mode = ColorMode.ONOFF
        else:
            self._color_mode = None

        #_LOGGER.debug(f"Aktiver Farbmodus für {self._name}: {self._color_mode}")

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

    #@property
    #def color_temp(self):
        #"""Farbtemperatur der Lichtgruppe."""
        #return self._color_temp

    @property
    def color_temp_kelvin(self):
        return self._color_temp_kelvin

    # falls du sie änderbar machen willst
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
        """Zusätzliche Attribute für die Lichtgruppe."""
        return {
            "entity_id": self._entities,
            "supported_color_modes": list(self._supported_color_modes),
            "brightness": self._brightness,
            "hs_color": self._hs_color,
            "rgb_color": self._rgb_color,
            "xy_color": self._xy_color,
            "color_temp": self._color_temp,
            "effect": self._effect,
            "effect_list": self._effect_list,
            "color_mode": self._color_mode,
        }



    async def async_update(self):
        """Aktualisiere den Status und die Attribute der Lichtgruppe."""
        #_LOGGER.debug(f"Aktualisiere Status und Attribute für {self._name}")
        await asyncio.sleep(1)
        states = [self.hass.states.get(entity_id) for entity_id in self._entities if self.hass.states.get(entity_id)]
    
        # Protokolliere alle Lampen-Attribute zur Fehlerdiagnose
        #for state in states:   'muss wieder aktiviert werden'
            #_LOGGER.debug(f"Lampe {state.entity_id}: Status={state.state}, Attribute={state.attributes}")
    
        # Aktualisiere den EIN/AUS-Status
        self._is_on = any(state.state == "on" for state in states if state)
        #_LOGGER.debug(f"{self._name}: is_on Status: {self._is_on}")
    
        # Sammle Helligkeitswerte
        brightness_values = [
            state.attributes.get(ATTR_BRIGHTNESS, 0)
            for state in states if state and state.state == "on" and ATTR_BRIGHTNESS in state.attributes and state.attributes.get(ATTR_BRIGHTNESS) is not None
        ]
        #_LOGGER.debug(f"{self._name}: brightness_values: {brightness_values}")
        self._brightness = round(sum(brightness_values) / len(brightness_values)) if brightness_values else 0
        #_LOGGER.debug(f"{self._name}: Berechnete Helligkeit: {self._brightness}")

        kelvin_values = []
        for s in states:
            if s.state != "on":
                continue
            # Angenommen, das Gerät liefert in "color_temp" (Mired):
            mired_val = s.attributes.get("color_temp")  # oder dein lokales ATTR_COLOR_TEMP
            if mired_val:
                kelvin_values.append(mired_to_kelvin(mired_val))
    
        if kelvin_values:
            # Beispiel: Einfacher Mittelwert aller Kelvin-Werte
            avg_kelvin = sum(kelvin_values) / len(kelvin_values)
            self._color_temp_kelvin = int(round(avg_kelvin))
        else:
            self._color_temp_kelvin = None
    
        # Sammle HS-Farben
        hs_colors = [
            state.attributes.get(ATTR_HS_COLOR)
            for state in states if state and state.state == "on" and ATTR_HS_COLOR in state.attributes and state.attributes.get(ATTR_HS_COLOR) is not None
        ]
        #_LOGGER.debug(f"{self._name}: hs_colors: {hs_colors}")
        self._hs_color = hs_colors[0] if hs_colors else None
    
        # Sammle RGB-Farben (falls verfügbar)
        rgb_colors = [
            state.attributes.get("rgb_color")
            for state in states if state and state.state == "on" and "rgb_color" in state.attributes and state.attributes.get("rgb_color") is not None
        ]
        #_LOGGER.debug(f"{self._name}: rgb_colors: {rgb_colors}")
        self._rgb_color = rgb_colors[0] if rgb_colors else None
    
        # Sammle Farbtemperaturen
        color_temps = [
            state.attributes.get(ATTR_COLOR_TEMP)
            for state in states if state and state.state == "on" and ATTR_COLOR_TEMP in state.attributes and state.attributes.get(ATTR_COLOR_TEMP) is not None
        ]
        #_LOGGER.debug(f"{self._name}: color_temps: {color_temps}")
        self._color_temp = round(sum(color_temps) / len(color_temps)) if color_temps else None
        #_LOGGER.debug(f"{self._name}: Berechnete Farbtemperatur: {self._color_temp}")
    
        # Sammle XY-Farben
        xy_colors = [
            state.attributes.get(ATTR_XY_COLOR)
            for state in states if state and state.state == "on" and ATTR_XY_COLOR in state.attributes and state.attributes.get(ATTR_XY_COLOR) is not None
        ]
        _LOGGER.debug(f"{self._name}: xy_colors: {xy_colors}")
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
            #_LOGGER.debug(f"{self._name}: 'onoff' entfernt, da andere Farbmodi unterstützt werden: {self._supported_color_modes}")

        if "xy" in self._supported_color_modes and "color_temp" in self._supported_color_modes:
            _LOGGER.debug(
                "Kombination (xy, color_temp) im Laufzeit-Update gefunden. Ersetze xy -> hs."
            )
            self._supported_color_modes.discard("xy")
            self._supported_color_modes.add("hs")

        has_color = any(m in self._supported_color_modes for m in ("hs", "rgb", "rgbw", "rgbww", "xy"))
        if has_color or "color_temp" in self._supported_color_modes:
            if "brightness" in self._supported_color_modes:
                _LOGGER.debug("Entferne brightness, weil wir (hs oder color_temp) haben.")
                self._supported_color_modes.discard("brightness")
    
        #_LOGGER.debug(f"{self._name}: Unterstützte Farbmodi: {self._supported_color_modes}")
    
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
            # Letzter Fallback: Falls Gruppe kein color_temp / hs / xy / brightness kann,
            # aber 'onoff' in supported_color_modes vorkommt:
            if ColorMode.ONOFF in self._supported_color_modes:
                self._color_mode = ColorMode.ONOFF
            elif ColorMode.BRIGHTNESS in self._supported_color_modes:
                self._color_mode = ColorMode.BRIGHTNESS
            else:
                # Oder nimm den ersten Eintrag, den es gibt
                self._color_mode = next(iter(self._supported_color_modes), ColorMode.ONOFF)


            #self._color_mode = ColorMode.onoff
            #self._color_mode = ColorMode.HS
        
        #_LOGGER.debug(f"{self._name}: Farbmodus: {self._color_mode}")

    
        # Sammle Effekte
        effects = [
            state.attributes.get(ATTR_EFFECT)
            for state in states if state and state.state == "on" and ATTR_EFFECT in state.attributes and state.attributes.get(ATTR_EFFECT) is not None
        ]
        #_LOGGER.debug(f"{self._name}: effects: {effects}")
        self._effect = effects[0] if effects else None
    
        # Sammle Effektlisten
        effect_lists = [
            state.attributes.get("effect_list", [])
            for state in states if state
        ]
        self._effect_list = sorted({effect for effect_list in effect_lists for effect in effect_list}) if effect_lists else []
        #_LOGGER.debug(f"{self._name}: effect_list: {self._effect_list}")
    
        # Erzwinge Statusaktualisierung in Home Assistant
        self.async_write_ha_state()
    
        """
        #_LOGGER.debug(
            f"{self._name}: Aktualisierte Helligkeit: {self._brightness}, HS-Farbe: {self._hs_color}, "
            f"Farbtemperatur: {self._color_temp}, XY-Farbe: {self._xy_color}, RGB-Farbe: {self._rgb_color}, "
            f"Effekt: {self._effect}, Effektliste: {self._effect_list}, Farbmodus: {self._color_mode}, "
            f"Status: {self._is_on}, Entitäten: {self._entities}"
        )
        """


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
        # Hier erfolgt die konkrete Transformation – z. B. anhand eines bekannten Musters:
        if rgb_color == [255, 255, 251]:
            return [27.028, 18.905], [255, 229, 207], [0.37, 0.35]
        # Falls die Werte nicht dem erwarteten Muster entsprechen, werden sie unverändert übernommen.
        return hs_color, rgb_color, xy_color




    def is_group_on(self):
        """Berechnet dynamisch, ob die Gruppe eingeschaltet ist."""
        for entity_id in self._entities:
            state = self.hass.states.get(entity_id)
            if state and state.state == "on":
                return True  # Mindestens eine Lampe ist eingeschaltet
        return False  # Keine Lampe ist eingeschaltet

    
    async def async_turn_on(self, **kwargs):
        """
        Schalte die Gruppe ein und verarbeite optional
        neue Helligkeit/Farben/Effekte. 
        Enthält die neue Cache-Logik für die Helligkeit.
        """
        self._is_on = True
        
        # Extrahiere evtl. neue Werte
        new_brightness = kwargs.get(ATTR_BRIGHTNESS, None)
        new_xy_color = kwargs.get(ATTR_XY_COLOR, None)
        new_hs_color = kwargs.get(ATTR_HS_COLOR, None)
        
        # Neu: HA gibt color_temp_kelvin statt color_temp (Mired)
        new_kelvin = kwargs.get("color_temp_kelvin")
        if new_kelvin:
            self._color_temp_kelvin = new_kelvin
    
        new_effect = kwargs.get(ATTR_EFFECT, None)
    
        # ======================= NEU: Gruppe aus + nur Helligkeit =======================
        group_is_on = self.is_group_on()
    
        # Prüfen, ob wirklich nur Helligkeit angefordert ist
        # (keine xy_color, keine hs_color, keine Kelvin-Farbtemperatur, kein Effekt)
        only_brightness_requested = (
            new_brightness is not None
            and new_xy_color is None
            and new_hs_color is None
            and new_kelvin is None
            and new_effect is None
        )
    
        # Wenn die Gruppe AUS ist und ausschließlich Helligkeit geändert wird,
        # sollen alle Lampen eingeschaltet und nur die Helligkeit gesetzt werden.
        # 1) Herausfinden, ob irgendeine dimmbare Lampe tatsächlich an ist.
        dimmable_on = False
        for entity_id in self._entities:
            state = self.hass.states.get(entity_id)
            if state and state.state == "on":
                # Prüfen, ob Lampe dimmbar ist (hat brightness oder color_modes mit brightness)
                if (
                    ATTR_BRIGHTNESS in state.attributes
                    or "brightness" in state.attributes.get(ATTR_SUPPORTED_COLOR_MODES, [])
                ):
                    dimmable_on = True
                    break
    
        # 2) Falls die Gruppe als "off" gilt ODER gar keine dimmbare Lampe an ist,
        #    und der Nutzer nur Helligkeit geändert hat:
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

    
                updated_attributes = dict(state.attributes)
                updated_attributes[ATTR_BRIGHTNESS] = new_brightness
                self.hass.states.async_set(entity_id, "on", updated_attributes)
    
                if (
                    ATTR_BRIGHTNESS in state.attributes
                    or ColorMode.BRIGHTNESS in state.attributes.get(ATTR_SUPPORTED_COLOR_MODES, [])
                ):
                    # Lampe ist dimmbar
                    service_data_list.append({
                        "entity_id": entity_id,
                        ATTR_BRIGHTNESS: new_brightness
                    })
                else:
                    # Lampe kennt nur On/Off => kein Brightness mitschicken
                    service_data_list.append({"entity_id": entity_id})
    
            # Parallel Services aufrufen
            tasks = [
                self.hass.services.async_call("light", "turn_on", data)
                for data in service_data_list
            ]
            await asyncio.gather(*tasks)
    
            await self.async_update()
            await self.async_update_ha_state(force_refresh=True)
            return
    
        # Sonderfall: sehr niedrige Helligkeit (<=3)
        if new_brightness is not None and new_brightness <= 3:
            _LOGGER.debug(
                f"[1% Override] new_brightness={new_brightness} => "
                f"Setze alle aktiven Lampen exakt auf {new_brightness}."
            )
            service_data_list = []
            for entity_id in self._entities:
                state = self.hass.states.get(entity_id)
                # Nur Lampen updaten, die "on" sind (oder ggf. alle einschalten?)
                if not state or state.state == "off":
                    _LOGGER.debug(f"Lamp {entity_id} ist off, überspringe oder schalte ein.")
                    # Zum Einschalten auskommentieren/ändern:
                    # continue
                if not state or state.state in ("unavailable", "unknown"):
                    _LOGGER.debug(f"Lampe {entity_id} ist unavailable/unknown. Überspringe sie.")
                    continue
                
                updated_attributes = dict(state.attributes if state else {})
                updated_attributes[ATTR_BRIGHTNESS] = new_brightness
                self.hass.states.async_set(entity_id, "on", updated_attributes)
                service_data_list.append({
                    "entity_id": entity_id,
                    ATTR_BRIGHTNESS: new_brightness
                })
    
        # Prüfe, ob es ein "einfaches" Einschalten ist (ohne Veränderungen)
        is_simple_turn_on = all(
            x is None for x in [new_brightness, new_xy_color, new_hs_color, new_kelvin, new_effect]
        )
    
        # =============== NEUE MANUELLE HELLIGKEITS-LOGIK (Cache) ===============
        if new_brightness is not None:
            # => Dies gilt als manuelle Änderung per Slider.
            _LOGGER.debug(f"[Cache] Manuelle Helligkeitsänderung erkannt: Ziel={new_brightness}")
    
            # 1) Gibt es schon einen Cache für diese Gruppe?
            cached_data = self.get_brightness_cache(self._name)
    
            if not cached_data:
                # Kein Cache vorhanden => erstelle neuen Cache auf Basis der "IST-Werte"
                _LOGGER.debug(f"[Cache] Kein Cache vorhanden. Erstelle neuen Cache für Gruppe '{self._name}'")
                self.store_brightness_cache(self._name)
                cached_data = self.get_brightness_cache(self._name)
            else:
                # Cache vorhanden => Timer zurücksetzen
                _LOGGER.debug(f"[Cache] Cache existiert bereits, Timer wird zurückgesetzt.")
                self.reset_brightness_cache_timer(self._name)
    
            # 2) Werte aus dem Cache holen (alte Gruppenhelligkeit, alte Lampenhelligkeiten)
            old_group_brightness = cached_data["group_brightness"]
            old_lamp_brightnesses = cached_data["lamp_brightnesses"]  # dict {entity_id: brightness}
    
            _LOGGER.debug(
                f"[Cache] Verwende aus Cache für '{self._name}': "
                f"old_group_brightness={old_group_brightness}, "
                f"old_lamp_brightnesses={old_lamp_brightnesses}"
            )
    
            # 3) Iterative Berechnung auf Basis der alten Werte
            brightness_calc_input = old_lamp_brightnesses.copy()
            adjusted_brightness_cache = await self.adjust_brightness_until_match(
                brightness_calc_input,
                new_brightness
            )
    
            # 4) Alle relevanten Lampen updaten
            service_data_list = []
            for entity_id, adj_brightness in adjusted_brightness_cache.items():
                # Nur updaten, wenn Lampe tatsächlich "on" ist
                state = self.hass.states.get(entity_id)
                if not state or state.state == "off":
                    _LOGGER.debug(f"Lampe {entity_id} ist aus. Überspringe.")
                    continue

                if not state or state.state in ("unavailable", "unknown"):
                    _LOGGER.debug(f"Lampe {entity_id} ist unavailable/unknown. Überspringe sie.")
                    continue

    
                # Prepare call
                updated_attributes = dict(state.attributes)
                updated_attributes[ATTR_BRIGHTNESS] = adj_brightness
                service_data = {
                    "entity_id": entity_id,
                    ATTR_BRIGHTNESS: adj_brightness
                }
                service_data_list.append(service_data)
    
                # Direkt in HA-Registry
                self.hass.states.async_set(entity_id, "on", updated_attributes)
    
                _LOGGER.debug(
                    f"[Cache] Setze Helligkeit für {entity_id} von {state.attributes.get(ATTR_BRIGHTNESS)} "
                    f"auf {adj_brightness}"
                )
    
            # Farben/Effekte + neue Kelvin-Farbtemperatur verarbeiten (unabhängig vom Cache)
            color_service_data_list = self._build_color_service_data(
                new_xy_color, new_hs_color, self._color_temp_kelvin, new_effect
            )
            service_data_list.extend(color_service_data_list)
    
            # Services aufrufen
            tasks = [
                self.hass.services.async_call("light", "turn_on", data)
                for data in service_data_list
            ]
            await asyncio.gather(*tasks)
    
        else:
            # Kein new_brightness => Farben/Effekt oder nur Einschalten
            _LOGGER.debug("Kein new_brightness => normales Einschalten oder nur Farbe/Effekt setzen.")
    
            # Farben/Effekte verarbeiten
            service_data_list = self._build_color_service_data(
                new_xy_color, new_hs_color, self._color_temp_kelvin, new_effect
            )
    
            # Falls einfaches Einschalten ohne Farbe/Effekt
            if is_simple_turn_on and not service_data_list:
                service_data_list = [{"entity_id": e} for e in self._entities]
    
            # Parallel aufrufen
            tasks = []
            for data in service_data_list:
                # Zustand in HA-Registry auf 'on' setzen
                ent_id = data.get("entity_id")
                if ent_id:
                    state = self.hass.states.get(ent_id)
                    if state:
                        updated_attributes = dict(state.attributes)
                        self.hass.states.async_set(ent_id, "on", updated_attributes)
                tasks.append(self.hass.services.async_call("light", "turn_on", data))
    
            await asyncio.gather(*tasks)
    
        # Abschließend: Status aktualisieren
        await self.async_update()
        await self.async_update_ha_state(force_refresh=True)


    async def async_turn_off(self, **kwargs):
        """Schalte die ganze Gruppe aus."""
        self._is_on = False
        tasks = []
        for entity_id in self._entities:
            state = self.hass.states.get(entity_id)
            if not state or state.state == "off":
                _LOGGER.debug(f"{entity_id} ist bereits aus oder nicht verfügbar.")
                continue
            if (
                not state
                or state.state == "unavailable"
                or state.state == "unknown"
            ):
                _LOGGER.debug(f"Lampe {entity_id} ist unavailable/unknown, überspringe Service-Call.")
                continue
            service_data = {"entity_id": entity_id}
            tasks.append(self.hass.services.async_call("light", "turn_off", service_data))
        
        await asyncio.gather(*tasks)
        await self.async_update()
        await self.async_update_ha_state(force_refresh=True)
        
    async def _handle_light_change(self, event):
        """Wird getriggert, wenn sich eine einzelne Lampe ändert."""
        _LOGGER.debug(f"Lichtänderung erkannt: {event}")
        
        if self._update_scheduled:
            _LOGGER.debug(f"Update für '{self._name}' ist bereits geplant – überspringe.")
            return
        self._update_scheduled = True
        
        try:
            await self.async_update()
            self.async_write_ha_state()
            await asyncio.sleep(0.2)
        finally:
            self._update_scheduled = False
        _LOGGER.debug(f"Lichtänderung für '{self._name}' verarbeitet.")

    # ----------------------------------------------------------
    #               NEUE CACHING-FUNKTIONEN
    # ----------------------------------------------------------
    def store_brightness_cache(self, group_id):
        """
        Erzeugt einen neuen Cache-Eintrag für group_id auf Basis
        der aktuellen IST-Werte.
        """
        # Alte Gruppenhelligkeit ermitteln (z.B. Mittelwert der aktiven Lampen)
        lamp_brightnesses = {}
        active_vals = []
        
        for entity_id in self._entities:
            state = self.hass.states.get(entity_id)
            if state and state.state == "on":
                val = state.attributes.get(ATTR_BRIGHTNESS, 0)
                lamp_brightnesses[entity_id] = val
                if val > 0:
                    active_vals.append(val)
        
        if active_vals:
            old_group_brightness = sum(active_vals) / len(active_vals)
        else:
            old_group_brightness = 0
        
        # Timer ggf. abbrechen, falls schon vorhanden
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
        
        # Timer starten
        self.reset_brightness_cache_timer(group_id, log_reason="Neuanlage")

    def reset_brightness_cache_timer(self, group_id, log_reason="Reset"):
        """Setzt den (5s) Timer zurück, damit der Cache nicht gelöscht wird."""
        entry = self._brightness_cache.get(group_id)
        if not entry:
            return
        
        # Bestehenden Timer abbrechen
        if entry["timer"]:
            entry["timer"].cancel()
        
        # Neuen Timer anlegen
        entry["timer"] = asyncio.create_task(self._clear_cache_after_delay(group_id, self.delay))
        _LOGGER.debug(f"[Cache] Timer zurückgesetzt (Grund: {log_reason}) für Gruppe '{group_id}'")

    async def _clear_cache_after_delay(self, group_id, delay):
        """Wartet 'delay' Sekunden und löscht dann den Cache, wenn nichts Neues passiert."""
        try:
            _LOGGER.debug(f"[Cache] Starte {delay}s-Timer, um Cache für '{group_id}' zu löschen.")
            await asyncio.sleep(delay)
            # Wenn wir hier ankommen und kein Cancel kam => Cache wirklich löschen
            self.clear_brightness_cache(group_id)
            _LOGGER.debug(f"[Cache] Cache für '{group_id}' ist abgelaufen und wurde gelöscht.")
        except asyncio.CancelledError:
            _LOGGER.debug(f"[Cache] Timer für '{group_id}' wurde abgebrochen.")
            raise

    def clear_brightness_cache(self, group_id):
        """Cache-Eintrag für group_id entfernen, wenn vorhanden."""
        if group_id in self._brightness_cache:
            # Evtl. laufenden Timer abbrechen
            timer_task = self._brightness_cache[group_id].get("timer")
            if timer_task:
                timer_task.cancel()
            del self._brightness_cache[group_id]
            _LOGGER.debug(f"[Cache] remove: Cache für '{group_id}' entfernt.")

    def get_brightness_cache(self, group_id):
        """Liefert den Cache-Eintrag für group_id oder None."""
        return self._brightness_cache.get(group_id)

    # ----------------------------------------------------------
    #       HELFER-FUNKTIONEN für Helligkeitsberechnung
    # ----------------------------------------------------------
# ----------------------------------------------------------
#   NEUE VERSION von calculate_new_brightness und
#   adjust_brightness_until_match mit "Late Rounding"
# ----------------------------------------------------------
    
    def calculate_new_brightness(
        self,
        old_group_brightness,
        new_group_brightness,
        old_light_brightness,
        group_brightness_cache,
        lamp_id
    ):
        """
        Wie bisher, nur dass wir NICHT mehr am Ende runden.
        """
        if old_light_brightness <= 0:
            return 0.0
        if new_group_brightness >= 255:
            return 255.0
    
        dimming_up = (new_group_brightness > old_group_brightness)
        
        # Nur aktive Lampen => Rechenbasis
        active_lamps = {lp: val for lp, val in group_brightness_cache.items() if val > 0}
    
        if not active_lamps:
            return float(old_light_brightness)
    
        def weight(val):
            return (1.0 - val/255.0) if dimming_up else (val/255.0)
    
        weights = {lp: weight(val) for lp, val in active_lamps.items()}
        total_weight = sum(weights.values()) or 1e-9
    
        delta = (new_group_brightness - old_group_brightness)
        scaling_factor = delta / total_weight
    
        w_lamp = weights.get(lamp_id, 0.0)
        new_val = old_light_brightness + w_lamp * scaling_factor
        
        # Wichtig: NICHT runden!
        # new_val = max(0, min(255, new_val))
        if new_val < 0:
            new_val = 0
        elif new_val > 255:
            new_val = 255
    
        return new_val  # => float zurückgeben
    
    
    async def adjust_brightness_until_match(self, group_brightness_cache, target_group_brightness):
        """
        Nur am Ende runden wir auf int, anstatt in jeder Iteration.
        """
        _LOGGER.debug("[Cache] => Starte adjust_brightness_until_match(...)")
        
        tolerance = 0.01
        max_iterations = 150
        best_result = None
        best_deviation = float('inf')
        
        if hasattr(self, "_adjustment_task") and self._adjustment_task:
            self._adjustment_task.cancel()
        self._adjustment_task = asyncio.current_task()
        
        # Nur Lampen, die tatsächlich > 0 Helligkeit haben
        active_lamps = {lp: float(val) for lp, val in group_brightness_cache.items() if val > 0}
        if not active_lamps:
            _LOGGER.debug("[Cache] Keine aktiven Lampen => leeres Ergebnis.")
            return {}
    
        # Initialwerte sichern, um pro Gruppe zu wissen, wer dieselbe Ausgangshelligkeit hatte
        lamp_initial_brightness = active_lamps.copy()
    
        try:
            for iteration in range(max_iterations):
                # Mittelwert als "aktueller Gruppenwert"
                current_group_brightness = sum(active_lamps.values()) / len(active_lamps)
                deviation = abs(current_group_brightness - target_group_brightness)
    
                # Bisher bester Wert?
                if deviation < best_deviation:
                    best_deviation = deviation
                    best_result = active_lamps.copy()  # float-Zwischenwerte
    
                if deviation <= tolerance:
                    _LOGGER.debug(f"Iteration={iteration}, Toleranz erreicht => Abbruch.")
                    break
    
                _LOGGER.debug(
                    f"Iteration={iteration}, current={current_group_brightness:.2f}, "
                    f"target={target_group_brightness:.2f}, dev={deviation:.2f}"
                )
    
                # Teilgruppen: Alle Lampen mit gleicher "initial brightness"
                brightness_groups = {}
                for lamp in active_lamps:
                    init_val = lamp_initial_brightness[lamp]
                    brightness_groups.setdefault(init_val, []).append(lamp)
    
                # Jede Teilgruppe anpassen
                for init_val, lamp_list in brightness_groups.items():
                    if not lamp_list:
                        continue
                    # Durschnitt nur innerhalb dieser Teilgruppe
                    old_group_val = sum(active_lamps[l] for l in lamp_list) / len(lamp_list)
    
                    # Repräsentative Lampe: Erst für eine Lampe berechnen, dann übernehmen
                    representative_lamp = lamp_list[0]
                    representative_brightness = active_lamps[representative_lamp]
    
                    new_representative = self.calculate_new_brightness(
                        old_group_brightness=current_group_brightness,
                        new_group_brightness=target_group_brightness,
                        old_light_brightness=representative_brightness,
                        group_brightness_cache=active_lamps,
                        lamp_id=representative_lamp
                    )
    
                    _LOGGER.debug(
                        f"[Cache] Teilgruppe init_val={init_val}, alter Mittelwert={old_group_val:.2f}, "
                        f"repr. Lamp {representative_lamp} => {new_representative:.2f}, lamps={lamp_list}"
                    )
    
                    # Setze alle Lampen dieser Teilgruppe auf den neuen repräsentativen Wert (float)
                    for lamp in lamp_list:
                        active_lamps[lamp] = new_representative
                        group_brightness_cache[lamp] = new_representative
            else:
                _LOGGER.warning(f"{max_iterations} Iterationen ausgereizt, Restabweichung={best_deviation:.2f}")
    
            # Am Ende: best_result hat die "beste" Annäherung als Float => jetzt rundest du EINMAL
            if not best_result:
                best_result = active_lamps
    
            final_result = {
                lamp: int(round(value)) for lamp, value in best_result.items()
            }
            return final_result
    
        except asyncio.CancelledError:
            _LOGGER.debug("[Cache] adjust_brightness_until_match abgebrochen.")
            raise
        finally:
            self._adjustment_task = None
            _LOGGER.debug("[Cache] adjust_brightness_until_match() beendet.")


    # ----------------------------------------------------------
    #   Sonstige Helferfunktionen (Farben/Effekte etc.)
    # ----------------------------------------------------------
    def _build_color_service_data(self, xy_color, hs_color, kelvin_temp, effect):
        service_data_list = []
        group_is_on = self.is_group_on()
    
        # 1) Entscheide einmal, welcher Farbmodus benutzt werden soll
        #    (Du kannst die Reihenfolge je nach Wunsch anpassen)
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
            if (
                not state
                or state.state == "unavailable"
                or state.state == "unknown"
            ):
                _LOGGER.debug(f"Lampe {entity_id} ist unavailable/unknown, überspringe Service-Call.")
                continue
    
            updated_attributes = dict(state.attributes) if state else {}
            service_data = {"entity_id": entity_id}
    
            # 2) Schreibe **nur** den ausgewählten Farbmodus ins service_data
            if chosen_color_mode == "hs" and ATTR_HS_COLOR in updated_attributes:
                service_data[ATTR_HS_COLOR] = hs_color
                updated_attributes[ATTR_HS_COLOR] = hs_color
    
            elif chosen_color_mode == "xy" and ATTR_XY_COLOR in updated_attributes:
                service_data[ATTR_XY_COLOR] = xy_color
                updated_attributes[ATTR_XY_COLOR] = xy_color
    
            elif chosen_color_mode == "temp" and ATTR_COLOR_TEMP in updated_attributes:
                mired_val = kelvin_to_mired(kelvin_temp)
                service_data[ATTR_COLOR_TEMP] = mired_val
                updated_attributes[ATTR_COLOR_TEMP] = mired_val
    
            # Effekt darf mit hinzu
            if effect is not None and ATTR_EFFECT in updated_attributes:
                service_data[ATTR_EFFECT] = effect
                updated_attributes[ATTR_EFFECT] = effect
    
            # Update Home Assistant State
            self.hass.states.async_set(entity_id, "on", updated_attributes)
    
            # So wie vorher:
            if not group_is_on:
                service_data_list.append(service_data)
            else:
                if len(service_data) > 1:
                    service_data_list.append(service_data)
    
        return service_data_list












