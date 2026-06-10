# Octopus Germany Integration für Home Assistant

Sprache / Language: [Deutsch](README.de.md) | [English](README.md)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.octopus_germany.total)

Diese Custom Integration bindet Octopus Energy Germany in Home Assistant ein. Sie liefert Kontodaten, Tarifpreise, SmartFlex-Status sowie Steuerungsmöglichkeiten fuer EV/Wallbox.

*Diese Integration ist nicht offiziell mit Octopus Energy verbunden.*

---

**Support das Projekt**
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/K3K71LPRM2)

## Funktionsumfang

- Kontodaten (Strom/Gas)
- Aktuelle Tarifpreise (inkl. Dynamic/TOU)
- SmartFlex-Geraetestatus, Dispatching, Session-Daten
- Schalter fuer Smart Control und Boost Charge
- **Smart-Meter-Readings**: Vortagsverbrauch akkumuliert mit stundenweiser Aufschluesselung (aus bei Octopus gespeicherten Zaehlerdaten)
- **Historische Octopus-Daten auslesen**: Historische Verbrauchs- und Zaehlerdaten aus dem Octopus-System abrufen
- Multi-Account und Multi-Device Support

## Installation

### HACS

1. Repository als Custom Repository in HACS eintragen
2. Nach Octopus Germany suchen
3. Integration installieren
4. Home Assistant neu starten
5. Integration in Einstellungen > Geraete und Dienste hinzufuegen

### Manuell

1. Ordner octopus_germany nach custom_components kopieren
2. Home Assistant neu starten
3. Integration in Einstellungen > Geraete und Dienste hinzufuegen

## Konfiguration

Die Konfiguration erfolgt komplett ueber die Home-Assistant-UI:

1. Einstellungen > Geraete und Dienste
2. Integration hinzufuegen
3. Octopus Germany auswaehlen
4. Login-Daten eingeben

## Dokumentation

Fuer eine kompakte Startseite sind die Details aufgeteilt:

- Vollstaendige Entitaets- und Attributreferenz:
  - [custom_components/octopus_germany/README.de.md](custom_components/octopus_germany/README.de.md)
- Actions/Services mit Beispielen:
  - [docs/ACTIONS_AND_SERVICES.de.md](docs/ACTIONS_AND_SERVICES.de.md)

## Actions auf einen Blick

- switch.octopus_<account_number>_<device_name>_smart_control
  - on: Smart Control aktivieren
  - off: Smart Control pausieren
- switch.octopus_germany_<account_number>_<device_name>_boost_charge
  - Sofortiges Boost-Laden starten/stoppen
- octopus_germany.set_device_preferences
  - Ziel-SoC und Zielzeit fuer ein Geraet setzen
- octopus_germany.get_smart_meter_readings
  - Tageswerte aus iMSys Historie laden
- octopus_germany.export_smart_meter_csv
  - iMSys Daten als CSV exportieren

## Hinweis zu iMSys / SMGW-HAN

Fuer direkte HAN-Auslesung am Smart Meter Gateway (SMGW) kann diese Integration parallel genutzt werden:

- [TRON4R/ha-ppc-smgw-han](https://github.com/TRON4R/ha-ppc-smgw-han)

Empfohlene Kombination:

- octopus_germany fuer Tarif, Konto, SmartFlex, Steuerung sowie das Auslesen der bei Octopus gespeicherten historischen Verbrauchs-/Zaehlerdaten
- ha-ppc-smgw-han fuer lokale HAN-Rohdaten

## Automationen

- [Octopus Intelligent Go mit EVCC](https://github.com/ha-puzzles/homeassistant-puzzlepieces/blob/main/use-cases/stromtarife/octopus-intelligent-go/README.md)

## Debugging

Beispiel fuer Debug-Logs in configuration.yaml:

```yaml
logger:
  logs:
    custom_components.octopus_germany: debug
    custom_components.octopus_germany.octopus_germany: debug
    custom_components.octopus_germany.switch: debug
```

## API Support

- REST: https://developer.oeg-kraken.energy/
- GraphQL: https://developer.oeg-kraken.energy/graphql/

## Support

- Diskussionen: https://github.com/thecem/octopus_germany/discussions
- Issues: https://github.com/thecem/octopus_germany/issues

## Lizenz

MIT Lizenz

## Haftungsausschluss

Diese Integration ist nicht offiziell von Octopus Energy Germany.
