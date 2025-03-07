Light Group Dimmer
Light Group Dimmer ist eine benutzerdefinierte Integration für Home Assistant, mit der du mehrere Lampen zu Gruppen zusammenfassen und gemeinsam dimmen kannst. Die Integration ermöglicht es, globale Verzögerungswerte (Delay) sowie eine gewichtete, iterative Dimm-Logik zu nutzen – ideal, um gruppenweise Lichtsteuerung präzise zu regeln.

Inhalt:
Features
Installation
Konfiguration
YAML-Konfiguration
UI-Konfiguration (Config Flow)
Verwendung
Bekannte Probleme und Verbesserungen
Beitrag leisten
Lizenz
Features:
  - Gruppensteuerung: Fasse mehrere Lichtentitäten zu einer Gruppe zusammen und steuere sie gemeinsam.
  - Globaler Delay: Lege einen globalen Verzögerungswert (Delay) fest, der für alle gruppenweiten Dimm-Operationen gilt.
  - Weighted Dimming: Nutzt eine iterative, gewichtete Berechnungslogik, um Helligkeitsänderungen möglichst gleichmäßig zu verteilen.
  - Unterstützung für YAML und UI: Du kannst Gruppen und Delay entweder über die configuration.yaml oder über den integrierten Config Flow in Home Assistant konfigurieren.
  - Automatischer Master-Eintrag: Global Delay Settings (Master) werden automatisch erstellt, falls noch keiner existiert – dieser Eintrag ist dann schreibgeschützt, um Dopplungen zu vermeiden.


Installation
Voraussetzungen:
Stelle sicher, dass du Home Assistant in einer Version ≥ 2025.2 (oder kompatibel mit Custom Components) installiert hast.

Download:
Lade den Quellcode von GitHub herunter oder klone das Repository:

bash
Kopieren
git clone https://github.com/xHecktor/light-group-dimmer
Installation:
Kopiere den Inhalt des Repositorys in das Verzeichnis custom_components/light_group_dimmer in deinem Home Assistant-Konfigurationsverzeichnis.

Neustart:
Starte Home Assistant neu, damit die Integration erkannt und initialisiert wird.

Konfiguration
YAML-Konfiguration
Du kannst den Delay-Wert und Gruppen auch über YAML konfigurieren. Füge dazu beispielsweise folgenden Abschnitt in deine configuration.yaml ein:

yaml
Kopieren
light_group_dimmer:
  delay: 5
  groups:
    - name: "Wohnzimmer Gruppe"
      entities:
        - light.wohnzimmer_decke_1
        - light.wohnzimmer_decke_2
    - name: "Schlafzimmer Gruppe"
      entities:
        - light.schlafzimmer_decke_1
        - light.schlafzimmer_decke_2
Wird YAML konfiguriert, übernimmt die Integration den Delay-Wert aus der YAML-Konfiguration und aktualisiert automatisch den Master-Eintrag. YAML-basierte Gruppen sind dann nicht über den UI-OptionsFlow änderbar.

UI-Konfiguration (Config Flow)
Falls du lieber die Benutzeroberfläche nutzt, kannst du Gruppen über den Config Flow anlegen und bearbeiten. Beachte dabei:

Beim ersten Start wird automatisch ein Master-Eintrag "Global Delay Settings" erstellt, falls noch keiner vorhanden ist. Dieser Eintrag wird als Master (globaler Delay) geführt und ist schreibgeschützt, wenn YAML aktiv ist.
Neue Gruppen (Typ "group") können über den Config Flow erstellt und über die Options im UI geändert werden. Änderungen werden in entry.options gespeichert und beim nächsten Reload übernommen.
Die Auswahl zwischen „group“ und „master“ im Config Flow ist optional – du kannst den Master-Eintrag auch vollständig automatisch erzeugen, sodass Nutzer nur noch Gruppen erstellen und anpassen können.

Verwendung
Steuerung über Home Assistant:
Sobald die Integration eingerichtet ist, erscheinen deine Gruppen als Lichtentitäten in Home Assistant. Du kannst sie über die Standard-Lichtsteuerung (Dashboard, Automatisierungen, Sprachassistenten) steuern.

Dimmen:
Die integrierte gewichtete Dimmlogik sorgt dafür, dass sich alle Lampen in der Gruppe gleichmäßig dimmen – unter Berücksichtigung des globalen Delay-Werts. Bei schnellen Änderungen (z. B. über einen Schieberegler) wird ein Debounce-Effekt erzielt, der die Änderungen stabilisiert.

Automatische Updates:
Die Integration nutzt asynchrone Updates und Cache-Logik, um den Status der einzelnen Lampen zu aggregieren. Dadurch werden Änderungen an einzelnen Lampen (z. B. über eine separate Lichtsteuerung) automatisch in der Gruppenentität aktualisiert.

Bekannte Probleme und Verbesserungen
Delay-Anpassung:
Es kann vorkommen, dass der Delay-Wert um 2–5 Sekunden zu hoch eingestellt werden muss, damit die Cache-Logik stabil arbeitet. Dies liegt an den asynchronen Updates, dem iterativen Dimm-Verfahren und Netzwerk-/Systemlatenzen.
Verbesserungsvorschlag:
Ein Debounce-Mechanismus oder dynamische Verzögerungsberechnung könnte hier helfen, die Logik weiter zu optimieren.

Race Conditions und Cache-Management:
Durch die iterative Berechnung und das asynchrone Event-Handling können in manchen Fällen Race Conditions auftreten. Eine Überarbeitung der Cache-Logik (z. B. durch asynchrone Queues) ist denkbar.

Farbmodi und Effekte:
Bei bestimmten Kombinationen von Farbmodi und Effekten kann es zu Warnungen kommen. Bitte melde solche Fälle, damit die Integration weiter verbessert werden kann.

Beitrag leisten
Beiträge zur Weiterentwicklung der Integration sind willkommen!
Bitte reiche Pull Requests ein oder eröffne ein Issue, wenn du Fehler findest oder neue Features implementieren möchtest.

Lizenz
Dieses Projekt steht unter der MIT-Lizenz.
