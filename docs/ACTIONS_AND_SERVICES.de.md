# Aktionen und Dienste

Sprache: [Deutsch](ACTIONS_AND_SERVICES.de.md) | [English](ACTIONS_AND_SERVICES.md)

Diese Seite erklaert die Schalter und Dienste der Integration sowie ihre Voraussetzungen.

## Aktionen im Ueberblick

### Smart-Control-Schalter

- Entitaetsmuster: `switch.octopus_<account_number>_<device_id>_smart_control`
- Zweck: SmartFlex Smart Control fuer ein Geraet aktivieren oder pausieren

Verhalten:

- `ON`:
  - Entsperrt Smart Control (unsuspend)
  - Geplantes Smart Charging ist wieder moeglich
- `OFF`:
  - Pausiert Smart Control (suspend)

Voraussetzungen:

- Geraet ist in Octopus SmartFlex registriert
- Provider-Integration kann das Geraet erreichen

### Boost-Ladeschalter

- Entitaetsmuster: `switch.octopus_germany_<account_number>_<device_id>_boost_charge`
- Zweck: Sofortiges Laden manuell starten

Verhalten:

- `ON`: Boost-Laden starten
- `OFF`: Boost-Laden beenden

Voraussetzungen:

- Smart Control sollte `ON` sein
- Geraet muss Boost unterstuetzen und LIVE sein

### Steckstatus-Binaersensor

- Entitaetsmuster: `binary_sensor.octopus_<account_number>_<device_id>_plugged`
- Zweck: abgeleiteter Steckstatus aus SmartFlex-API-Zustaenden

Entscheidungslogik:

- `is_suspended = true` -> `unknown`
- `is_suspended = false` und `current_state = SMART_CONTROL_NOT_AVAILABLE` -> `off`
- `is_suspended = false` und sonstiger `current_state` -> `on`

Wichtige Einschraenkung:

- Die SmartFlex API liefert fuer Fahrzeuge keinen eigenen booleschen Wert `isPlugged`.
- Bei pausiertem Smart Control ist der API-Status mehrdeutig, daher absichtlich `unknown`.

## Dienste

### `octopus_germany.refresh_intelligent_data`

Fordert fuer alle eingerichteten Konten mit Intelligent-Tarif sofort eine Aktualisierung von Geraete- und Dispatch-Daten an. Konten ohne diese Faehigkeit werden ignoriert.

Beispiel:

```yaml
service: octopus_germany.refresh_intelligent_data
```

### `octopus_germany.set_device_preferences`

Setzt Ziel-SoC und Zielzeit fuer ein EV/Charge Point.

Waehle das Fahrzeug oder den Ladepunkt anhand seines Namens aus der
Home-Assistant-Liste aus. Das Account-Servicegeraet wird nicht angeboten;
Home Assistant ordnet die Auswahl automatisch der Octopus-Geraete-ID zu.
In YAML sind sowohl die Home-Assistant-Geraeteregister-ID als auch die
Octopus-Geraete-UUID gueltig; HA-IDs werden automatisch aufgeloest.
Entity-IDs sind kein gueltiger Ersatz.

Eingaben:

- `device_id` (erforderlich): im UI per Name ausgewaehlt; in YAML HA-Geraeteregister-ID oder Octopus-Geraete-UUID
- `target_percentage` (erforderlich): 20-100 in 5%-Schritten
- `target_time` (erforderlich): `HH:MM` zwischen 04:00 und 17:00

Beispiel:

```yaml
service: octopus_germany.set_device_preferences
data:
  device_id: "00000000-0002-4000-803c-0000000021c7"
  target_percentage: 80
  target_time: "07:00"
```

### `octopus_germany.get_smart_meter_readings`

Liest iMSys-Daten fuer ein bestimmtes Datum.
Die Service-Antwort wird auch als Event `octopus_germany_smart_meter_readings_result` gesendet.

Eingaben:

- `account_number` (erforderlich): `A-xxxxxxxx`
- `date` (erforderlich): `YYYY-MM-DD`
- `property_id` (optional)


Beispiel:

```yaml
service: octopus_germany.get_smart_meter_readings
data:
  account_number: "A-12345678"
  date: "2026-06-01"
```

### `octopus_germany.export_smart_meter_csv`

Exportiert Zaehlerdaten als CSV.

Die Datei wird unter `/config/octopus_germany/exports` gespeichert. Eine persistente Home-Assistant-Benachrichtigung enthaelt einen Download-Link zur aktuellen HA-Adresse, der in einem neuen Tab oeffnet. Service-Antwort und Ergebnis-Event enthalten die URL ebenfalls. Das dateigebundene Bearer-Token liegt in HAs privatem Speicher und ist gemaess Integration-Option gueltig (Standard 24 Stunden, einstellbar von 1 bis 168 Stunden). Eine Aenderung gilt nur fuer neue Exporte; bereits erzeugte Links behalten ihre bisherige Ablaufzeit.

Der Export verwendet paginierte Monatsabfragen und lokale Kalendergrenzen aus der konfigurierten Home-Assistant-Zeitzone. Ein Jahresexport wird in Monatsabfragen aufgeteilt. Quellen- und Qualitaetsmetadaten bleiben beim Laden erhalten, die CSV enthaelt jedoch nur Verbrauchswerte; vor einer Bewertung als echte Zaehlerwerte muessen die Metadaten separat geprueft werden.

Die Service-Antwort und das Event `octopus_germany_csv_export_result` enthalten `measurement_metadata` mit `sources`, `reading_qualities`, `reading_frequencies`, `device_ids`, `register_ids`, `missing_device_id_count` und `missing_register_id_count`. Fehlende IDs sind bei manchen aggregierten Property-Messungen normal und kennzeichnen allein keine Schaetzung; fuer die Einordnung sind `sources` und `reading_qualities` massgeblich.

Eingaben:

- `account_number` (erforderlich)
- `property_id` (optional): ohne Angabe wird die erste Strom-Property verwendet
- `period` (erforderlich): `month` oder `year`
- `year` (erforderlich)
- `month` (bei `period: month` erforderlich)
- `filename` (optional)
- `layout` (optional): `wide` oder `tall`
- `resolution` (optional): `15min` oder `hour`; Standard ist `15min`
- `summary` (optional): `true/false`
- `go_window_start` und `go_window_end` (optional): lokale `HH:MM`-Grenzen fuer die Aufteilung in der Zusammenfassung

### `octopus_germany.export_cost_report`

Erstellt eine taegliche und monatliche Kostenschaetzung als CSV. Der Bericht nutzt Agreement-Preise und die API-Netzentgelte des Netzbetreibers am Zaehlerpunkt. Formeln, Parametergruende, CSV-Aufbau, Umgang mit fehlenden Daten und Rechtsrahmen stehen im [Leitfaden zum Stromkostenbericht](COST_REPORT.de.md).

- `account_number` (erforderlich); `property_id` (optional)
- `period` und `year` (erforderlich); `month` bei Monatsberichten erforderlich
- `contract_start_network_charge_ct_kwh` (erforderlich; Vorgabe `7.65` ist ein unbestaetigter Referenzwert)
- `module3_start_date`, `module3_rates_json` (optional)
- `module1_start_date` (optional); `module1_annual_credit_net_eur` (optional; leer nutzt den Jahreswert aus der passenden Datei, sonst null)
- `vat_percent` (MwSt.-Ersatzwert, Vorgabe 19); `filename` (optional)

Beispiel fuer `module3_rates_json` mit historischen Zeitfenstern:

```json
[
  {"rate_type":"OFFPEAK","start_time":"23:00:00","end_time":"06:00:00","rate_cents_per_kwh":1.99,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"STANDARD","start_time":"06:00:00","end_time":"11:00:00","rate_cents_per_kwh":6.64,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"OFFPEAK","start_time":"11:00:00","end_time":"15:00:00","rate_cents_per_kwh":1.99,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"STANDARD","start_time":"15:00:00","end_time":"17:00:00","rate_cents_per_kwh":6.64,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"PEAK","start_time":"17:00:00","end_time":"22:00:00","rate_cents_per_kwh":12.75,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"STANDARD","start_time":"22:00:00","end_time":"23:00:00","rate_cents_per_kwh":6.64,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"}
]
```

Dies ist der 2025-Zeitplan eines Netzbetreibers und gilt nur vom 1. April bis 31. Dezember 2025. Die vorausgefuellten Werte werden nur fuer den passenden Netzbetreiber-Code verwendet. Fuer den eigenen Zaehlerpunkt die Saetze und Gueltigkeitsdaten aus dem passenden Preisblatt einsetzen. `module3_start_date` auf das erklaerte/gewaehlte Wirksamkeitsdatum setzen; `valid_to` ist exklusiv.

Der Service prueft auch `/config/octopus_germany/grid_fee_schedules.json`. Fehlt die Datei oder ein Eintrag fuer Netzbetreiber-Code und Abfragejahr, weist die Service-Antwort auf das [Dateibeispiel](examples/grid_fee_schedules.example.json) hin. Jeder Gueltigkeitszeitraum enthaelt alle 24 Stunden einzeln; benachbarte Stunden werden nicht zusammengefasst. API-Saetze haben Vorrang, danach fuellen explizite JSON-Eintraege API-Luecken und zuletzt Dateisaetze. Der Modul-1-Jahresbetrag aus der Datei wird nur verwendet, wenn `module1_annual_credit_net_eur` leer bleibt. Pfad und Trefferstatus stehen in der Antwort.

Service-Antwort und Event `octopus_germany_cost_report_result` enthalten Download-Link, Tageszahlen und Warnungen. Die Gueltigkeit folgt der oben genannten Integration-Option. Bei mindestens einem unvollstaendigen Tag bleibt der Monatsgesamtpreis leer.

Fuer einen einmaligen, monatlichen Ruecklauf von Dezember 2024 bis August 2026 mit 10 Sekunden Pause siehe das [Script-Beispiel](examples/export_monthly_cost_reports.yaml). Vor dem Start Konto, Vertragsbaseline und Wirksamkeitsdaten anpassen und pruefen.

### `octopus_germany.submit_meter_readings`

Schreibt Strom- oder Gas-Zaehlerstaende in die OE-API.

Eingaben:

- `account_number` (erforderlich): Konto, dem der Zaehler gehoert
- `meter_type` (erforderlich): `electricity` oder `gas`
- `meter_id` (erforderlich): OE-Meter-ID aus den Attributen der Zaehler-Entitaet
- `reading_date` (erforderlich): `YYYY-MM-DD`
- `readings_json` (optional): JSON-Array mit `value` und `register_obis_code` je Eintrag
- `reading_value` und `register_obis_code` (optional): Hilfsfelder fuer einen einzelnen Registerwert

Beispiel:

```yaml
service: octopus_germany.submit_meter_readings
data:
  account_number: "A-12345678"
  meter_type: electricity
  meter_id: "1234567890"
  reading_date: "2026-06-01"
  readings_json: >-
    [{"value": 1234.56, "register_obis_code": "1-0:1.8.0"}]
```

Wichtige Einschraenkung:

- Die OE-Mutation akzeptiert ein Datum und Registerwerte, keine Zeitstempel pro Listeintrag.
- Hier werden nur **Tageswerte** eingespielt, keine 15-Minuten-Intervalle.

Praktisches Beispiel:

- [Tägliche Zaehlerstand-Automation](UPLOAD_DAILY_METER_READING_AUTOMATION.md)

## iMSys / SMGW-HAN Empfehlung

Fuer direkte lokale HAN-Telemetrie kann diese Integration parallel genutzt werden:

- https://github.com/TRON4R/ha-ppc-smgw-han

Empfohlene Aufteilung:

- `octopus_germany`: Konto-, Tarif-, Dispatch- und SmartFlex-Steuerdaten sowie Auslesen der bei Octopus gespeicherten historischen Verbrauchs-/Zaehlerdaten
- `ha-ppc-smgw-han`: direkte HAN-Werte vom Smart Meter Gateway
