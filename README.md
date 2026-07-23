# Light Group Dimmer


<p align="center">
  <a href="https://github.com/xHecktor/light_group_dimmer">
    <img src="images/logo.png" alt="Logo" height="200">
  </a>
</p>

<p align="center">
  <a href="https://github.com/xHecktor/light_group_dimmer/releases"><img src="https://img.shields.io/github/v/release/xHecktor/light_group_dimmer?include_prereleases" alt="Release"></a>
  <a href="https://github.com/xHecktor/light_group_dimmer/actions/workflows/validate.yml"><img src="https://github.com/xHecktor/light_group_dimmer/actions/workflows/validate.yml/badge.svg" alt="Validate"></a>
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS Custom"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/xHecktor/light_group_dimmer" alt="License"></a>
</p>

<p align="center">
  <b>English</b> | <a href="README.de.md">Deutsch</a>
</p>

**Light Group Dimmer** is a custom integration for [Home Assistant](https://www.home-assistant.io/) that lets you combine several lights into groups and dim them together.

It mimics the dimming behaviour of Philips Hue and accounts for the fact that individual lamps within a group can start at different brightness levels. When dimming, the change is **not** distributed evenly: lamps that are already bright receive proportionally less of the increase, while darker lamps are raised more. This keeps the light balance of the whole group intact. The calculation is tested against real Hue reference measurements (see `tests/`).

In the Hue app you can press and hold the slider to experiment with the desired brightness. Home Assistant has no "press and hold", so the integration uses a **delay** instead: on the first slider command, the original brightness distribution of the lamps is cached. Every further brightness change within the delay is computed from that original distribution — so you can dim up and back down and land exactly on the starting picture. The delay measures the **idle time after the last slider command**; only then does the current distribution become the new baseline.

Please note that I'm not a professional developer and built this in my spare time. It's tested primarily with a Hue Bridge, but the integration only uses the standard Home Assistant light services and is **not** limited to Hue.

## Why weighted dimming?

Move the group slider and the member lamps keep their relative brightness (here: 31 % / 93 % / 100 %) instead of collapsing to one value:

<p align="center">
  <img src="images/light_dimmer_2.gif" alt="Dragging the group slider while the member lamps keep their relative brightness." width="480">
</p>

A standard light group pushes every lamp to the same value when you move the slider, so any balance you set up is lost. Light Group Dimmer scales the lamps proportionally instead — both hit the same group average, but only the weighted version keeps the character of the scene:

<p align="center">
  <img src="images/comparison.svg" alt="Standard light group forces every lamp to the same brightness, while Light Group Dimmer keeps their relative levels." width="760">
</p>

## Contents

- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
  - [YAML configuration](#yaml-configuration)
  - [UI configuration (config flow)](#ui-configuration-config-flow)
- [Usage](#usage)
- [Tests](#tests)
- [Notes](#notes)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Group control:** Combine several light entities into a group and control them together. Devices without brightness (e.g. smart plugs) can be members — they switch along but are ignored while dimming.
- **Weighted dimming:** Hue-style weighted calculation — the brightness ratios between lamps are preserved while dimming. Only lamps that are switched on are taken into account.
- **Global delay:** Idle time after the last slider command during which the original distribution stays the calculation baseline (default: 5 s).
- **Instant response:** The group is fully event-driven. The sliders react immediately and don't jump through intermediate values while dimming.
- **Color temperature in Kelvin:** Uses `color_temp_kelvin` throughout (the HA standard); the group's Kelvin range is derived automatically from its members.
- **Transitions:** `transition:` from scenes, automations and service calls is passed through to the lamps.
- **YAML and UI:** Configure groups and delay via `configuration.yaml` or the config flow; UI groups can be renamed later without creating a new entity.
- **Diagnostics:** Under *Settings → Devices & Services → Light Group Dimmer → Download diagnostics* you get a JSON dump for bug reports.
- **Turn-on behaviour:** On a plain turn-on the bridge (e.g. Hue) restores the lamps' last states. To switch all lamps on at the same brightness, set the brightness via the slider while the group is off.

## Installation

Requirement: Home Assistant ≥ 2024.12.

### Via HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=xHecktor&repository=light_group_dimmer&category=integration)

or manually in HACS:

1. Make sure [HACS](https://hacs.xyz) is installed.
2. Add the custom repository **xHecktor/light_group_dimmer** (type: **Integration**) in HACS.
3. Install **Light Group Dimmer** and restart Home Assistant.
4. Add the integration under **Settings → Devices & Services**.

*Beta versions:* In HACS choose "Redownload" on the repository and enable "Show beta versions".

### Manual

1. Download the source from [GitHub](https://github.com/xHecktor/light_group_dimmer).
2. Copy `custom_components/light_group_dimmer` into the `custom_components` directory of your Home Assistant configuration.
3. Restart Home Assistant.

## Configuration

### YAML configuration

```yaml
light_group_dimmer:
  delay: 5
  groups:
    - name: "Living Room Group"
      entities:
        - light.living_room_ceiling_1
        - light.living_room_ceiling_2
    - name: "Bedroom Group"
      entities:
        - light.bedroom_ceiling_1
        - light.bedroom_ceiling_2
```

When configured via YAML, the YAML delay takes precedence and the master entry becomes read-only. YAML groups cannot be edited through the UI options flow; changes to the YAML take effect after a Home Assistant restart.

### UI configuration (config flow)

- On first start a master entry **"Global Delay Settings"** is created automatically (global delay). It must exist only once; the manual "master" option in the dialog is only a backup in case it was deleted.
- New groups (type "group") are created via the config flow and edited through the UI options (name and entities). Renaming keeps the entity along with its history and automations.
- YAML groups appear collected under the **"Imported from YAML"** entry.

## Usage

**Control:** Groups appear as normal light entities and can be controlled from the dashboard, automations and voice assistants — including `transition:` in service calls.

**Dimming:** The weighted dimming logic distributes changes proportionally. The delay timer restarts with every brightness command; while it runs, the group keeps computing from the original distribution (Hue "press and hold" behaviour).

## Tests

The repository ships a complete test package:

- `tests/test_brightness.py` – regression test of the dimming math against 37 real Hue reference measurements (runs in CI on every push).
- `docs/TESTPLAN.md` + `docs/test_scripts.yaml` – scripts that run all test cases directly in Home Assistant and write the results to a file.
- `tests/evaluate_results.py` – turns that result file into a pass/fail table.

## Notes

- **±1–2 % deviation** between commanded and displayed values is normal (percent ↔ 0–255 conversion plus rounding in the lamp firmware).
- **Effects:** The group offers the union of all member effects; lamps that don't know a chosen effect simply ignore it.
- **Dynamic Hue scenes** are a bridge feature and are started through the Hue integration (`hue.activate_scene` with `dynamic: true`); the group follows the lamp states automatically.

## Contributing

Contributions are welcome! Please open a pull request or an issue if you find bugs or want to suggest features. For bug reports, the diagnostics download (see above) helps a lot.

## License

This project is licensed under the MIT License.
