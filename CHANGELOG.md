# Changelog

Alle nennenswerten Änderungen an dieser Integration.

## 1.1.2
- Fix: Auch die Farb- und Farbtemperatur-Regler springen beim Setzen über die
  Gruppe nicht mehr durch Zwischenwerte. Die Anzeige hält kurz den kommandierten
  Wert, bis die Lampen ihn erreicht haben (analog zum Helligkeitsregler).

## 1.1.1
- Fix: Eine Gruppe, die eine umbenannte oder gelöschte Lampe enthielt, ließ sich
  im Optionen-Dialog nicht mehr bearbeiten oder speichern ("not a valid option").
  Solche Entitäten werden jetzt als abwählbare Option "(nicht verfügbar)"
  angezeigt.

## 1.1.0
### Verhalten
- Helligkeitsregler springt beim Dimmen nicht mehr durch Zwischenwerte.
- Delay misst jetzt exakt die Ruhezeit nach dem letzten Slider-Befehl.
- Vollständig event-getrieben: schnelle Reaktion beim Ein-/Ausschalten.
- Mehrfach in einer Gruppe gelistete Lampen werden entdupliziert.
- Gewichtete Dimm-Berechnung geschlossen (nicht mehr iterativ); Verhalten
  gegen 37 reale Hue-Referenzmessungen getestet.

### Neu
- Farbtemperatur durchgängig in Kelvin; Kelvin-Grenzen der Gruppe ergeben sich
  aus den Mitgliedern.
- `transition:` aus Szenen/Automationen/Service-Aufrufen wird durchgereicht.
- Diagnose-Download unter Geräte & Dienste.
- Stabile unique_id für UI-Gruppen (überlebt Umbenennen, mit Migration).

### Projekt
- CI (hassfest, HACS-Validierung, Regressionstests) und Testpaket im Repository.
