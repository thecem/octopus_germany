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

- binary_sensor.octopus_<account_number>_<device_id>_intelligent_dispatching
  - on waehrend aktivem Dispatch
- binary_sensor.octopus_<account_number>_<device_id>_plugged
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
- Von OE gemeldetes Paragraph-14a-Modul
- Aktuell wirksamer variabler Netzentgeltanteil in EUR/kWh mit vollstaendigem Tagesplan als Attribut
- Der Strompreis-Sensor enthaelt unter `agreements` alle von OE gelieferten vergangenen, aktuellen und zukuenftigen Stromvertraege mit Status, Laufzeit sowie den verfuegbaren Brutto-, Netto- und MwSt.-Preisstufen. `agreement_prices` enthaelt die Preisstufen des aktuell ausgewaehlten Vertrags.

Jeder Eintrag in `agreements` enthaelt `code`, `name`, `type`, `is_active`, `is_revoked`, `is_terminated`, `valid_from`, `valid_to` und `prices`. Die Preise enthalten, soweit von OE geliefert, Cent/kWh und EUR/kWh fuer Brutto und Netto, `vat_percent`, die Preisgueltigkeit sowie Aktivierungszeitfenster.

Hinweis:

- SoC Change und SoC Limit wurden entfernt.
- `MODULE_1` wird neutral als OE-Backend-Wert angezeigt und beweist allein nicht, dass Modul 3 als Abrechnungsoption gewaehlt wurde.
- Eine erfolgreiche Netzentgelt-Antwort wird fuer den lokalen Tag gecacht; Zeitfensterwechsel werden lokal berechnet.

### Switches

- switch.octopus_<account_number>_<device_id>_smart_control
- switch.octopus_germany_<account_number>_<device_id>_boost_charge

Geraetebezogene Entitaets-IDs verwenden die stabile Octopus-Geraete-UUID. Der Anzeigename bleibt lesbar, sodass gleiche Namen nicht zu Kollisionen fuehren.

## Services

- octopus_germany.set_device_preferences
- octopus_germany.get_smart_meter_readings
- octopus_germany.export_smart_meter_csv
- octopus_germany.submit_meter_readings

CSV-Exporte laden Smart-Meter-Werte ueber paginierte Monatsabfragen in der konfigurierten Home-Assistant-Zeitzone. Die API-Schicht behaelt Quellen-, Qualitaets-, Geraete- und Registerdaten bei, sofern OE sie liefert; auch intern konsistente Intervalle koennen geschaetzt sein.

Fuer Parameter, Beispiele und Event-Outputs siehe:

- [docs/ACTIONS_AND_SERVICES.de.md](../../docs/ACTIONS_AND_SERVICES.de.md)

## iMSys / SMGW-HAN

Fuer direkte HAN-Auslesung am Smart Meter Gateway (SMGW) kann parallel genutzt werden:

- [TRON4R/ha-ppc-smgw-han](https://github.com/TRON4R/ha-ppc-smgw-han)

Empfohlene Rollenverteilung:

- octopus_germany: Tarif, Konto, SmartFlex, Steuerung sowie Auslesen der bei Octopus gespeicherten historischen Verbrauchs-/Zaehlerdaten
- ha-ppc-smgw-han: lokale HAN-Telemetrie

## API Support

- REST: https://developer.oeg-kraken.energy/
- Kraken GraphQL: https://developer.oeg-kraken.energy/graphql/
- OE Backend GraphQL: wird fuer variable Netzentgelte direkt und mit demselben Token angesprochen
- Schema-Snapshots: `oeg_graphql_schema.yaml` und `oe_backend_graphql_schema.json`

## Support

- Diskussionen: https://github.com/thecem/octopus_germany/discussions
- Issues: https://github.com/thecem/octopus_germany/issues
