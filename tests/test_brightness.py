"""
Regressionstest für die gewichtete Gruppendimmung.

Die Referenzwerte (REFERENCE) stammen aus realen Messungen mit einer Hue-Bridge:
Für einen Ausgangszustand aus drei Lampen wurde die Gruppe auf eine Ziel-Helligkeit
gestellt und die resultierenden Einzel-Helligkeiten notiert. Der Test stellt sicher,
dass compute_target_brightnesses dieses Hue-Verhalten weiterhin reproduziert.

Die Tabelle ist in ganzen Prozent notiert; Home Assistant rechnet in 0..255. Ein
einzelner Helligkeitsschritt entspricht ~0,4 %, daher wird eine Toleranz von
TOLERANCE Prozentpunkten (reines Umrechnungs-/Rundungsrauschen) zugelassen.

Der Test läuft ohne installiertes Home Assistant – brightness.py wird direkt per
Dateipfad geladen, ohne das Paket __init__ (das HA importiert) zu berühren.
"""
import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components" / "light_group_dimmer" / "brightness.py"
)
_spec = importlib.util.spec_from_file_location("lgd_brightness", _MODULE_PATH)
_brightness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_brightness)
compute_target_brightnesses = _brightness.compute_target_brightnesses

TOLERANCE = 2  # erlaubte Abweichung in Prozentpunkten (Umrechnung Prozent <-> 0..255)


def _pct_to_255(pct):
    """Prozent -> Home-Assistant-Helligkeit (0..255). None = Lampe aus."""
    return None if pct is None else round(pct / 100 * 255)


def _b255_to_pct(val):
    """Home-Assistant-Helligkeit (0..255) -> Prozent."""
    return round(val / 255 * 100)


# (V_Nr, (L1_old, L2_old, L3_old), target_%, (L1_new, L2_new, L3_new)); None = aus
REFERENCE = [
    (1, (80, 70, 100), 95, (95, 92, 100)),
    (2, (50, 50, 100), 80, (70, 70, 100)),
    (3, (None, 100, 100), 90, (None, 90, 90)),
    (4, (90, 90, 90), 100, (100, 100, 100)),
    (5, (100, 100, 100), 80, (80, 80, 80)),
    (6, (30, 50, 100), 85, (74, 82, 100)),
    (7, (None, 50, 98), 95, (None, 90, 100)),
    (8, (100, 50, None), 60, (80, 40, None)),
    (9, (100, 100, None), 70, (70, 70, None)),
    (10, (20, 100, 40), 90, (83, 100, 87)),
    (11, (80, 90, 95), 97, (95, 97, 98)),
    (12, (60, 70, 85), 95, (93, 95, 97)),
    (13, (50, 90, 100), 90, (73, 95, 100)),
    (14, (80, 50, 30), 85, (94, 84, 78)),
    (15, (75, 85, 50), 92, (93, 96, 87)),
    (16, (50, 100, 70), 95, (91, 100, 95)),
    (17, (100, 60, 40), 90, (100, 89, 83)),
    (18, (40, 70, 60), 88, (84, 92, 89)),
    (19, (70, 80, 90), 98, (97, 98, 99)),
    (20, (100, 100, 50), 80, (97, 97, 49)),
    (21, (24, 21, 39), 35, (31, 29, 45)),
    (22, (28, 54, 100), 88, (78, 86, 100)),
    (23, (93, 31, 100), 97, (99, 93, 100)),
    (24, (93, 31, 100), 30, (37, 12, 40)),
    (25, (100, 12, 100), 96, (100, 89, 100)),
    (26, (36, 100, None), 90, (80, 100, None)),
    (27, (95, 95, 80), 98, (99, 99, 97)),
    (28, (99, 85, 50), 97, (100, 98, 94)),
    (29, (98, 70, 95), 96, (99, 90, 98)),
    (30, (95, 95, 95), 99, (99, 99, 99)),
    (31, (90, 100, 99), 97, (93, 100, 99)),
    (32, (99, 98, 97), 100, (100, 100, 100)),
    (33, (90, 95, 85), 93, (93, 96, 89)),
    (34, (96, 80, 70), 95, (99, 95, 92)),
    (35, (80, 99, 99), 98, (94, 100, 100)),
    (36, (98, 97, 96), 99, (99, 99, 99)),
    (37, (90, 100, 99), 99, (97, 100, 100)),
]


def _run_row(old_pct, target_pct):
    """Führt die Berechnung für eine Tabellenzeile aus und liefert %-Ergebnisse je Lampe."""
    lamps = {f"L{i + 1}": _pct_to_255(p) for i, p in enumerate(old_pct)}
    result = compute_target_brightnesses(lamps, _pct_to_255(target_pct))
    return {lp: (_b255_to_pct(result[lp]) if lp in result else None) for lp in lamps}


def _check_row(nr, old_pct, target_pct, expected_pct):
    got = _run_row(old_pct, target_pct)
    for i, exp in enumerate(expected_pct):
        lp = f"L{i + 1}"
        if exp is None:
            assert got[lp] is None, f"Zeile {nr}: {lp} sollte aus sein, ist {got[lp]}"
        else:
            assert got[lp] is not None, f"Zeile {nr}: {lp} sollte an sein, ist aus"
            diff = abs(got[lp] - exp)
            assert diff <= TOLERANCE, (
                f"Zeile {nr} {lp}: erwartet {exp}%, berechnet {got[lp]}% "
                f"(Abweichung {diff} > {TOLERANCE} Pp)"
            )


try:
    import pytest

    @pytest.mark.parametrize("nr,old_pct,target_pct,expected_pct", REFERENCE,
                             ids=[f"row{r[0]}" for r in REFERENCE])
    def test_hue_reference(nr, old_pct, target_pct, expected_pct):
        _check_row(nr, old_pct, target_pct, expected_pct)
except ImportError:  # pragma: no cover - Fallback ohne pytest
    pass


def test_empty_and_plug_only():
    """Nur Steckdosen / keine aktiven Lampen => leeres Ergebnis."""
    assert compute_target_brightnesses({}, 128) == {}
    assert compute_target_brightnesses({"plug": 0}, 128) == {}


def _main():
    """Direkt ausführbar (ohne pytest): prüft alle Zeilen und meldet das Ergebnis."""
    for nr, old_pct, target_pct, expected_pct in REFERENCE:
        _check_row(nr, old_pct, target_pct, expected_pct)
    test_empty_and_plug_only()
    print(f"OK: {len(REFERENCE)} Referenzzeilen + Sonderfaelle bestanden "
          f"(Toleranz {TOLERANCE} Pp).")


if __name__ == "__main__":
    _main()
