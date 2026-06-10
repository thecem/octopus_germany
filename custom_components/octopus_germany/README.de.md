# Octopus Germany Integration fuer Home Assistant

Sprache / Language: [Deutsch](README.de.md) | [English](README.md)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.octopus_germany.total)

Diese Dokumentation beschreibt die Entitaeten und die Bedienung innerhalb der Integration.

## Installation und Konfiguration

Die Einrichtung erfolgt in Home Assistant ueber:

1. Einstellungen > Geraete und Dienste
2. Integration hinzufuegen
3. Octopus Germany auswaehlen
4. Login-Daten eingeben

## Dokumentationsstruktur

- Actions und Services mit Praxisbeispielen:
  - [docs/ACTIONS_AND_SERVICES.de.md](../../docs/ACTIONS_AND_SERVICES.de.md)
- Kompakte Projekt-Startseite:
  - [README.de.md](../../README.de.md)

## Entitaeten (Ueberblick)

### Binary Sensors

- binary_sensor.octopus_<account_number>_<device_name>_intelligent_dispatching
  - on waehrend aktivem Dispatch
- binary_sensor.octopus_<account_number>_<device_name>_plugged
  - abgeleiteter Steckstatus

Plugged-Logik:

- is_suspended = true -> unknown
- is_suspended = false und current_state = SMART_CONTROL_NOT_AVAILABLE -> off
- is_suspended = false und sonstiger current_state -> on

Wichtig:

- Die API liefert fuer Fahrzeuge kein dediziertes isPlugged Feld.
- Bei deaktiviertem Smart Control ist der Steckstatus daher nicht immer eindeutig.

### Sensors

- Strompreis, Stromsaldo, letzter Stromzaehlerstand
- Gasprodukte, Gassaldo, Gaszaehler, Gasvertrag
- Fahrzeugdaten (SoC, Battery Size)
- Smart Charging Sessions
- Historische Smart-Meter-Verbrauchswerte

Hinweis:

- SoC Change und SoC Limit wurden entfernt.

### Switches

- switch.octopus_<account_number>_<device_name>_smart_control
- switch.octopus_germany_<account_number>_<device_name>_boost_charge

## Services

- octopus_germany.set_device_preferences
- octopus_germany.get_smart_meter_readings
- octopus_germany.export_smart_meter_csv

Fuer Parameter, Beispiele und Event-Outputs siehe:

- [docs/ACTIONS_AND_SERVICES.de.md](../../docs/ACTIONS_AND_SERVICES.de.md)

## iMSys / SMGW-HAN

Fuer direkte HAN-Auslesung am Smart Meter Gateway (SMGW) kann parallel genutzt werden:

- [TRON4R/ha-ppc-smgw-han](https://github.com/TRON4R/ha-ppc-smgw-han)

Empfohlene Rollenverteilung:

- octopus_germany: Tarif, Konto, SmartFlex, Steuerung
- ha-ppc-smgw-han: lokale HAN-Telemetrie

## API Support

- REST: https://developer.oeg-kraken.energy/
- GraphQL: https://developer.oeg-kraken.energy/graphql/

## Support

- Diskussionen: https://github.com/thecem/octopus_germany/discussions
- Issues: https://github.com/thecem/octopus_germany/issues
