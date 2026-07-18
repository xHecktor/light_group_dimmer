"""
Auswerter für die Ergebnisdatei der HA-Testskripte (docs/test_scripts.yaml).

Liest /config/dimmer_test_results.txt (oder eine beliebige Datei / stdin) und
erzeugt eine Pass/Fail-Tabelle mit Abweichungen.

Aufruf:
    python3 tests/evaluate_results.py dimmer_test_results.txt
    cat dimmer_test_results.txt | python3 tests/evaluate_results.py

Schwellen (in Prozentpunkten):
    <= WARN_PP  -> OK    (Rundungs-/Hue-Quantisierungsrauschen)
    <= FAIL_PP  -> WARN  (auffällig, aber evtl. noch Quantisierung)
     > FAIL_PP  -> FAIL  (echter Verdacht)
"""
import sys
import re

WARN_PP = 2   # bis hier: erwartetes Rundungsrauschen
FAIL_PP = 4   # darüber: echter Verdacht


def _parse_triplet(text):
    """'95/92/100' -> [95, 92, 100]; '0' bzw. 'aus' -> 0."""
    out = []
    for part in text.split("/"):
        part = part.strip().lower()
        out.append(0 if part in ("aus", "off", "") else int(round(float(part))))
    return out


def _fields(line):
    """Extrahiert key=value-Paare aus einer Logzeile (führenden Zeitstempel ignorierend)."""
    return dict(re.findall(r"(\w+)=(\S+)", line))


def evaluate(lines):
    rows = []          # (label, ziel, soll[], ist[], maxdev, status)
    worst = 0
    n_ok = n_warn = n_fail = 0

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # Gewichtete Testfälle: "TF01 ... soll=.. ist=.."
        if line.lstrip().startswith(("TF", "BLOCK", "20")) and "ist=" in line and (
            "soll=" in line or "erwartet=" in line
        ):
            f = _fields(line)
            label_m = re.search(r"\b(TF\d+|BLOCK\d+)\b", line)
            label = label_m.group(1) if label_m else "?"
            soll = _parse_triplet(f.get("soll", f.get("erwartet", "")))
            ist = _parse_triplet(f["ist"])
            ziel = f.get("ziel", f.get("wartezeit", "-"))

            devs = []
            for s, i in zip(soll, ist):
                # aus-Fall: beide müssen 0 sein
                if s == 0 or i == 0:
                    devs.append(0 if s == i else 99)
                else:
                    devs.append(abs(s - i))
            md = max(devs) if devs else 0
            worst = max(worst, md)
            status = "OK" if md <= WARN_PP else ("WARN" if md <= FAIL_PP else "FAIL")
            if status == "OK":
                n_ok += 1
            elif status == "WARN":
                n_warn += 1
            else:
                n_fail += 1
            rows.append((label, ziel, soll, ist, md, status))

    return rows, worst, n_ok, n_warn, n_fail


def _fmt(triplet):
    return "/".join("aus" if x == 0 else str(x) for x in triplet)


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    else:
        lines = sys.stdin.readlines()

    rows, worst, n_ok, n_warn, n_fail = evaluate(lines)
    if not rows:
        print("Keine auswertbaren Zeilen gefunden. Format erwartet: "
              "'TF01 ... soll=a/b/c ist=x/y/z'.")
        return 1

    print(f"{'Fall':>7} {'Ziel':>6} | {'soll':>12} | {'ist':>12} | Δmax | Status")
    print("-" * 60)
    for label, ziel, soll, ist, md, status in rows:
        mark = {"OK": "", "WARN": "  <-- WARN", "FAIL": "  <== FAIL"}[status]
        print(f"{label:>7} {str(ziel):>6} | {_fmt(soll):>12} | {_fmt(ist):>12} | {md:>3}{mark}")

    print("-" * 60)
    print(f"OK={n_ok}  WARN={n_warn}  FAIL={n_fail}  | groesste Abweichung={worst} Pp")
    print(f"(Schwellen: OK<={WARN_PP}, WARN<={FAIL_PP}, sonst FAIL)")
    if n_fail:
        print("\n>>> FAIL-Faelle pruefen: echte Abweichung oder Testaufbau "
              "(Delay!=5s, 0%-Lampe nicht aus, Cache noch aktiv)?")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
