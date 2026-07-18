# Testplan – Light Group Dimmer (ab Beta 1.1.0b3)

Ziel: Nach jedem Beta reproduzierbar prüfen, dass (1) das gewichtete Dimmen die
Hue-Referenz trifft, (2) das Delay-/Cache-Verhalten stimmt, (3) der Regler beim
Dimmen nicht springt. Teil 1 und 2 laufen automatisch und liefern eine Datei,
die du an Claude gibst; Teil 3 ist eine kurze Sichtprüfung.

## Vorbereitung (einmalig)

1. Inhalt von `docs/test_scripts.yaml` in die `configuration.yaml` übernehmen
   (die drei Blöcke `notify:`, `template:`, `script:`).
2. HA neu starten (oder YAML neu laden + einmal neu starten wegen `notify`/`template`).
3. **Delay der Integration auf 5 s** stellen (Master-Eintrag „Global Delay Settings").
   Das ist Pflicht, sonst stimmen die Delay-Testfälle nicht.
4. Prüfen, dass die Testlampen im Skript zu deinem Setup passen:
   - Gruppe: `light.dimmer_arbeitszimmer`
   - L1/L2/L3: `light.hue_play_1`, `light.hue_play_2`, `light.arbeitszimmer`
   - (Eine Steckdose in der Gruppe stört nicht – wird automatisch ignoriert.)

## Teil 1 – Gewichtetes Dimmen (automatisch, ~6 min)

1. Ergebnisdatei leeren (optional): `/config/dimmer_test_results.txt` löschen.
2. **Entwicklerwerkzeuge → Aktionen → `script.lgd_test_gewichtet` → ausführen.**
3. Nicht am Licht/Dashboard herumspielen, während es läuft.

Der Ablauf pro Fall: 3 Lampen auf definierte Startwerte → 6 s warten (Lampen
settlen, alter Cache stirbt) → Gruppe auf Zielhelligkeit → 4 s warten →
Ergebnis in die Datei schreiben.

**Erwartung:** Abweichung 0–2 Pp gegenüber der Hue-Referenz. Die einzigen Fälle
mit 2 Pp sind TF13 und TF23. Real können durch Hue-Quantisierung beim
Zurückmelden nochmal ±1–2 Pp dazukommen – bis 3–4 Pp also unkritisch.

## Teil 2 – Delay-/Cache-Verhalten (automatisch, ~1 min)

1. **Aktionen → `script.lgd_test_delay` → ausführen.**

Zwei Blöcke mit identischer Abfolge (99 % → warten → 66 %), Startbild (37,72,89):

| Block | Wartezeit | Erwartung | Bedeutung |
|-------|-----------|-----------|-----------|
| BLOCK2 | 3 s (< 5 s Delay) | **≈ 37/72/89** | Cache lebt → Original-Verteilung kehrt zurück |
| BLOCK1 | 5,8 s (> 5 s Delay) | **≈ 65/66/67** | Cache tot → aus dem 99%-Zustand gerechnet |

**Kernaussage:** Die beiden Ergebnisse müssen sich **unterscheiden**. Sind sie
gleich, greift die neue Delay-Logik nicht (oder der Delay ist ≠ 5 s).

## Teil 3 – Regler springt nicht (manuell, ~1 min)

1. Gruppe `light.dimmer_arbeitszimmer` im Dashboard öffnen.
2. Optional Sensor `sensor.lgd_test_abweichung` mit anzeigen (Gruppenanzeige
   minus echter Mittelwert, in %).
3. Helligkeitsregler zügig verschieben.

**Erwartung:** Der Balken geht direkt auf den Zielwert, ohne durch
Zwischenwerte zu zappeln. Der Sensor darf beim Ziehen kurz ausschlagen und
muss danach schnell (kleine Gruppe ~0,5 s, groß bis 2 s) auf ~0 zurückgehen.

## Auswertung

Ergebnisdatei ansehen: `/config/dimmer_test_results.txt`.

**Variante A – du gibst mir die Datei:** Inhalt komplett kopieren und an Claude
schicken. Ich werte aus und melde Auffälligkeiten zurück.

**Variante B – selbst auswerten** (Python auf einem Rechner mit der Repo-Kopie):

```
python3 tests/evaluate_results.py dimmer_test_results.txt
```

Ausgabe: Pass/Fail-Tabelle je Fall mit Abweichung.
- `OK` ≤ 2 Pp · `WARN` ≤ 4 Pp · `FAIL` > 4 Pp.
- Ein `FAIL` heißt nicht automatisch Code-Bug – zuerst Aufbau prüfen:
  Delay wirklich 5 s? 0%-Lampe wirklich aus? Genug Wartezeit (Cache tot)?

## Bekannte, unkritische Effekte

- **±1–2 Pp** überall: Umrechnung Prozent ↔ 0–255 plus Hue-Quantisierung.
- **TF13, TF23**: bekannte 2-Pp-Fälle, kein Fehler.
- **0%-Lampen** (TF3/7/8/9/26): müssen wirklich *aus* sein; je nach HA-Version
  kann `brightness_pct: 0` sonst als Minimalhelligkeit landen – die Skripte
  schalten sie deshalb per `turn_off` aus.
