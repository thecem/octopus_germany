# Octopus Germany Integration fuer Home Assistant

Sprache / Language: [Deutsch](README.de.md) | [English](README.md)

[![marketplace_badge](https://img.shields.io/badge/Home%20Assistant-Marketplace-41BDF5.svg)](https://www.home-assistant.io/integrations/marketplace/)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.octopus_germany.total)

Diese Dokumentation beschreibt die Entitaeten und die Bedienung innerhalb der Integration.

Voraussetzung ist Home Assistant **2026.11.0 oder neuer**. Die Markenbilder
werden mit der Integration im Ordner `brand/` ausgeliefert.

## Freund*innen werben

Wenn du über [meinen Empfehlungslink](https://octopusenergy.de/empfehlungen?referralCode=free-cat-744) zu Octopus Energy wechselst, erhältst du **150 €** als Rechnungsgutschrift. Es gelten die Teilnahmebedingungen von Octopus Energy.

## Installation und Konfiguration

Installation über **Einstellungen** > **Marketplace**: nach **Octopus Germany**
suchen und installieren. Anschließend Home Assistant neu starten.

Die Einrichtung erfolgt anschließend in Home Assistant ueber:

1. Einstellungen > Geraete und Dienste
2. Integration hinzufuegen
3. Octopus Germany auswaehlen
4. Login-Daten eingeben

## Dokumentationsstruktur

- Entitaeten und Attribute: siehe [Entitaeten-Ueberblick](#entitaeten-ueberblick)
- [Aktionen und Dienste](../../docs/ACTIONS_AND_SERVICES.de.md)
- [Stromkostenbericht und Berechnungen](../../docs/COST_REPORT.de.md)
- [Beispieldatei fuer Netzbetreiber-Zeitplaene](../../docs/examples/grid_fee_schedules.example.json)

## Smart-Meter- und Kostenberichte

Smart-Meter-Jahresdateien werden ueber paginierte Monatsabfragen in der konfigurierten Home-Assistant-Zeitzone erstellt. Quelle und Messqualitaet werden als Metadaten zurueckgegeben; auch intern konsistente Intervalle koennen geschaetzt sein.

Kostenberichte verwenden Agreement-Preise und zeitgueltige API-Netzentgelte. Sie sind Schaetzungen, keine Lieferantenrechnung und keine Rechtsentscheidung. Formeln, Eingaben, unvollstaendige Daten und regulatorischer Kontext sind im [Leitfaden zum Stromkostenbericht](../../docs/COST_REPORT.de.md) beschrieben.

Fehlen API-Saetze, kann eine optionale Datei stunden- und gueltigkeitsbezogene Werte je Netzbetreiber enthalten. Die [Beispieldatei](../../docs/examples/grid_fee_schedules.example.json) zeigt das Format mit einzeln erhaltenen Stunden 0 bis 23.

CSV-Dateien werden unter `/config/octopus_germany/exports` gespeichert. Zu jedem Export erscheint eine persistente Home-Assistant-Benachrichtigung mit einem dateigebundenen Download-Link. Das Bearer-Token ist standardmaessig 24 Stunden gueltig und kann in den Integration-Optionen auf 1 bis 168 Stunden eingestellt werden; die Einstellung gilt nur fuer neue Exporte.

## Entitaeten (Ueberblick)

### Binaersensoren

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

### Sensoren

- Strompreis, Stromsaldo, letzter Stromzaehlerstand
- Gasprodukte, Gassaldo, Gaszaehler, Gasvertrag
- Fahrzeugdaten (SoC, Battery Size)
- Smart Charging Sessions
- Historische Smart-Meter-Verbrauchswerte
- Registersensoren je Zaehler und verwertbarem OBIS-Code; Null ist ein gueltiger Wert, Messwerthistorie bleibt als Attribut erhalten
- Von OE gemeldetes Paragraph-14a-Modul
- Aktuell wirksamer variabler Netzentgeltanteil in EUR/kWh. `module_3_rates` bietet `NT`, `ST` und `HT`, jeweils mit `periods`. Preis (netto) und Gueltigkeit stehen einmal pro Periode; die zugehoerigen Start-/Endzeitintervalle sind darunter gruppiert. Das originale API-`rates`-Array bleibt erhalten.
- Kombinierter Bruttopreis-Sensor: Octopus-Bruttopreis plus die mit gemeldeter Umsatzsteuer hochgerechnete Abweichung der aktiven Netto-Grid-Fee zur STANDARD-Basisrate. `price_combinations` gruppiert gleiche Tarif-/Modul-3-Preise des aktuellen Tages und enthaelt die passenden Zeitintervalle. Numerische Preiswerte und Strings mit fest acht Nachkommastellen (`*_display`) werden bereitgestellt. Der State zeigt ebenfalls acht Nachkommastellen; bestehende numerische Preisattribute bleiben fuer Templates und Automationen erhalten. Der Sensor setzt voraus, dass die Octopus-Preisrate die STANDARD-Netzentgelt-Basis bereits enthaelt; der gemeldete Modulwert ist nur informativ. Bei fehlender VAT oder uneindeutiger STANDARD-Rate bleibt der Sensor unavailable.
- Der Strompreis-Sensor enthaelt unter `agreements` alle von OE gelieferten vergangenen, aktuellen und zukuenftigen Stromvertraege mit Status, Laufzeit, Brutto-/Netto-Arbeitspreisen und MwSt. sowie Netto-Monatsgrundpreis und brutto ausgewiesenen Grundpreisstufen mit Gueltigkeitsdaten. Grundpreise kommen aus einer separaten, schlanken Agreement-Query. `agreement_prices` enthaelt die Arbeitspreisstufen des aktuell ausgewaehlten Vertrags.

Jeder Eintrag in `agreements` enthaelt `code`, `name`, `type`, `is_active`, `is_revoked`, `is_terminated`, `valid_from`, `valid_to` und `prices`. Die Preise enthalten, soweit von OE geliefert, Cent/kWh und EUR/kWh fuer Brutto und Netto, `vat_percent`, die Preisgueltigkeit sowie Aktivierungszeitfenster.

Hinweis:

- SoC Change und SoC Limit wurden entfernt.
- `MODULE_1` wird neutral als OE-Backend-Wert angezeigt und beweist allein nicht, dass Modul 3 als Abrechnungsoption gewaehlt wurde.
- Eine erfolgreiche Netzentgelt-Antwort wird fuer den lokalen Tag gecacht; Zeitfensterwechsel werden lokal berechnet.

### Schalter

- switch.octopus_<account_number>_<device_id>_smart_control
- switch.octopus_germany_<account_number>_<device_id>_boost_charge

Geraetebezogene Entitaets-IDs verwenden die stabile Octopus-Geraete-UUID. Der Anzeigename bleibt lesbar, sodass gleiche Namen nicht zu Kollisionen fuehren.

## Dienste

- `octopus_germany.refresh_intelligent_data`
- `octopus_germany.set_device_preferences`
- `octopus_germany.get_smart_meter_readings`
- `octopus_germany.export_smart_meter_csv`
- `octopus_germany.export_cost_report`
- `octopus_germany.submit_meter_readings`

CSV-Exporte laden Smart-Meter-Werte ueber paginierte Monatsabfragen in der konfigurierten Home-Assistant-Zeitzone. Die API-Schicht behaelt Quellen-, Qualitaets-, Geraete- und Registerdaten bei, sofern OE sie liefert; auch intern konsistente Intervalle koennen geschaetzt sein.

Parameter, Beispiele und Ergebnis-Events:

- [docs/ACTIONS_AND_SERVICES.de.md](../../docs/ACTIONS_AND_SERVICES.de.md)

## iMSys / SMGW-HAN

Fuer direkte HAN-Auslesung am Smart Meter Gateway (SMGW) kann parallel genutzt werden:

- [TRON4R/ha-ppc-smgw-han](https://github.com/TRON4R/ha-ppc-smgw-han)

Empfohlene Rollenverteilung:

- octopus_germany: Tarif, Konto, SmartFlex, Steuerung sowie Auslesen der bei Octopus gespeicherten historischen Verbrauchs-/Zaehlerdaten
- ha-ppc-smgw-han: lokale HAN-Telemetrie

## API-Unterstuetzung

- REST: https://developer.oeg-kraken.energy/
- Kraken GraphQL: https://developer.oeg-kraken.energy/graphql/
- OE Backend GraphQL: wird fuer variable Netzentgelte direkt und mit demselben Token angesprochen
- Schema-Snapshots: `oeg_graphql_schema.yaml` und `oe_backend_graphql_schema.json`

## Support

- Diskussionen: https://github.com/thecem/octopus_germany/discussions
- Issues: https://github.com/thecem/octopus_germany/issues
