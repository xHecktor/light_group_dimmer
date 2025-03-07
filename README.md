# Light Group Dimmer


<p align="center">
  <a href="https://github.com/xHecktor/Light-Group-Dimmer/">
    <img src="https://github.com/xHecktor/Light-Group-Dimmer/blob/main/images/logo.png" alt="Logo" height="200">
  </a>
</p>

**Light Group Dimmer** ist eine benutzerdefinierte Integration für [Home Assistant](https://www.home-assistant.io/), mit der du mehrere Lampen zu Gruppen zusammenfassen und gemeinsam dimmen kannst. 

Diese Integration orientiert sich am Dimmverhalten von Hue und berücksichtigt, dass die Ausgangshelligkeit einzelner Lampen innerhalb einer Gruppe variieren kann. Beim Dimmen wird die Helligkeitsanpassung nicht gleichmäßig verteilt – Lampen, die bereits sehr hell sind, erhalten proportionell weniger zusätzliche Helligkeit, während dunklere Lampen stärker angehoben werden. So wird eine ausgewogene und harmonische Lichtbalance in der gesamten Gruppe erreicht.

In der Hue App kann man durch Drücken und Halten des Schiebereglers experimentell die gewünschte Helligkeit einstellen. Da Home Assistant dieses "Drücken und Halten" des Sliders nicht unterstützt, wurde ein Delay implementiert. Während dieser Verzögerungszeit wird die ursprüngliche Helligkeit in dem Cache gespeichert und als Grundlage für die anschließende gewichtete und interavtive Berechnung der Helligkeit der einzelnen Lampen herangezogen.


Bitte beachtet, dass ich kein Programmierer bin und mir den code in meiner Freizeit erarbeitet habe

## Inhalt

- [Features](#features)
- [Installation](#installation)
- [Konfiguration](#konfiguration)
  - [YAML-Konfiguration](#yaml-konfiguration)
  - [UI-Konfiguration (Config Flow)](#ui-konfiguration-config-flow)
- [Verwendung](#verwendung)
- [Bekannte Probleme und Verbesserungen](#bekannte-probleme-und-verbesserungen)
- [Beitrag leisten](#beitrag-leisten)
- [Lizenz](#lizenz)

## Features

- **Gruppensteuerung:** Fasse mehrere Lichtentitäten zu einer Gruppe zusammen und steuere sie gemeinsam.
- **Globaler Delay:** Lege einen globalen Verzögerungswert (Delay) fest, der für alle gruppenweiten Dimm-Operationen gilt.
- **Weighted Dimming:** Nutzt eine iterative, gewichtete Berechnungslogik, um Helligkeitsänderungen möglichst gleichmäßig zu verteilen.
- **Unterstützung für YAML und UI:** Du kannst Gruppen und Delay entweder über die `configuration.yaml` oder über den integrierten Config Flow in Home Assistant konfigurieren.
- **Einschaltverhalten:** Es werden nur Lampen beim Dimmen berücksichtigt, die bereits eingeschaltet sind

## Installation

1. **Voraussetzungen:**  
   Stelle sicher, dass du Home Assistant in einer Version ≥ 2025.2 (oder kompatibel mit Custom Components) installiert hast.

2. **Download:**  
   Lade den Quellcode von [GitHub](https://github.com/xHecktor/Light-Group-Dimmer) herunter
   
4. **Installation:**
Kopiere den Inhalt des Repositorys in das Verzeichnis custom_components/light_group_dimmer in deinem Home Assistant-Konfigurationsverzeichnis.

5. **Neustart:**
Starte Home Assistant neu, damit die Integration erkannt und initialisiert wird.


## Installation

1. Stell sicher das [HACS](https://hacs.xyz) installiert ist.
2. Füge in HACS die Benutzerdefinierte Repositories: **xHecktor/Light-Group-Dimmer** Typ:**Integration** hinzu
3. Füge die **light_group_dimmer** Integration in **Geräte & Dienste**  in den Einstellungen zu Home Assistant hinzu:



[![](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=xHecktor&repository=Light-Group-Dimmer)

   [![](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=light_group_dimmer)

   

Wenn du es manuell installieren möchtest:

2. Lade den Quellcode von [GitHub](https://github.com/xHecktor/Light-Group-Dimmer/tree/main/custom_components/light_group_dimmer) herunter
3. Kopiere die Dateien des Repositorys in das Verzeichnis custom_components/light_group_dimmer in deinem Home Assistant-Konfigurationsverzeichnis.







## Konfiguration
### YAML-Konfiguration
Du kannst den Delay-Wert und Gruppen auch über YAML konfigurieren. Füge dazu beispielsweise folgenden Abschnitt in deine configuration.yaml ein:


```
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
```

Wird YAML konfiguriert, übernimmt die Integration den Delay-Wert aus der YAML-Konfiguration und aktualisiert automatisch den Master-Eintrag. YAML-basierte Gruppen sind dann nicht über den UI-OptionsFlow änderbar und es ist anschließend ein Neustart von HA notwendig.

### UI-Konfiguration (Config Flow)
Falls du lieber die Benutzeroberfläche nutzt, kannst du Gruppen über den Config Flow anlegen und bearbeiten. Beachte dabei:

- Beim ersten Start wird automatisch ein Master-Eintrag "Global Delay Settings" erstellt, falls noch keiner vorhanden ist. Dieser Eintrag wird als Master (globaler Delay) geführt und ist schreibgeschützt, wenn YAML aktiv ist.
- Neue Gruppen (Typ "group") können über den Config Flow erstellt und über die Options im UI geändert werden. Änderungen werden in entry.options gespeichert und beim nächsten Reload übernommen.
- Die master-Option dient nur als Backup, falls "Global Delay Settings" Eintrag gelöscht oder nicht erstellt wurde. Der "Global Delay Settings" darf somit nur einmal vorliegen). 
- Falls Lichtgruppen über yaml erstellt wurden, werden die Entities in dem Eintrag "Imported from YAML" oder evtl. in  "Global Delay Settings" zusammengefasst. Änderungen der yaml Einträge werden nur über ein Neustart von HA wirksam


## Verwendung
**Steuerung über Home Assistant:**
Sobald die Integration eingerichtet ist, erscheinen deine Gruppen als Lichtentitäten in Home Assistant. Du kannst sie über die Standard-Lichtsteuerung (Dashboard, Automatisierungen, Sprachassistenten) steuern.

**Dimmen:**
Die integrierte gewichtete Dimmlogik sorgt dafür, dass sich alle Lampen in der Gruppe gleichmäßig dimmen – unter Berücksichtigung des globalen Delay-Werts. Der Delay-Timer wird jedesmal zurück gesetzt, wenn eine erneute Ändeurng der Helligkeit erfolgt und der alte Timer noch nicht abgelaufen ist


## Bekannte Probleme und Verbesserungen
**Delay-Anpassung:**
Es kann vorkommen, dass der Delay-Wert um 2–5 Sekunden zu hoch eingestellt werden muss, damit die Cache-Logik stabil arbeitet. Dies liegt an den asynchronen Updates, dem iterativen Dimm-Verfahren und Netzwerk-/Systemlatenzen.
Verbesserungsvorschlag:
Ein Debounce-Mechanismus oder dynamische Verzögerungsberechnung könnte hier helfen, die Logik weiter zu optimieren.

**Race Conditions und Cache-Management:**
Durch die iterative Berechnung und das asynchrone Event-Handling können in manchen Fällen Race Conditions auftreten. Eine Überarbeitung der Cache-Logik (z. B. durch asynchrone Queues) ist denkbar.

**Farbmodi und Effekte:**
Bei bestimmten Kombinationen von Farbmodi und Effekten kann es zu Warnungen kommen. Bitte melde solche Fälle, damit die Integration weiter verbessert werden kann.

## Beitrag leisten
Beiträge zur Weiterentwicklung der Integration sind willkommen!
Bitte reiche Pull Requests ein oder eröffne ein Issue, wenn du Fehler findest oder neue Features implementieren möchtest.

## Lizenz
Dieses Projekt steht unter der MIT-Lizenz.
