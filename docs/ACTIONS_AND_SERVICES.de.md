# Actions und Services

Sprache / Language: [Deutsch](ACTIONS_AND_SERVICES.de.md) | [English](ACTIONS_AND_SERVICES.md)

Diese Seite erklaert die wichtigsten EV-Aktionen und wie die Services der Integration sauber verwendet werden.

## Aktionen im Ueberblick

### Smart Charging Control Switch

- Entitaetsmuster: `switch.octopus_<account_number>_<device_name>_smart_control`
- Zweck: SmartFlex Smart Control fuer ein Geraet aktivieren oder pausieren

Verhalten:

- ON:
  - Entsperrt Smart Control (unsuspend)
  - Geplantes Smart Charging ist wieder moeglich
- OFF:
  - Pausiert Smart Control (suspend)

Voraussetzungen:

- Geraet ist in Octopus SmartFlex registriert
- Provider-Integration kann das Geraet erreichen

### Boost Charge Switch

- Entitaetsmuster: `switch.octopus_germany_<account_number>_<device_name>_boost_charge`
- Zweck: Sofortiges Laden manuell starten

Verhalten:

- ON: Boost-Laden starten
- OFF: Boost-Laden beenden

Voraussetzungen:

- Smart Control sollte ON sein
- Geraet muss Boost unterstuetzen und LIVE sein

### Plugged Binary Sensor

- Entitaetsmuster: `binary_sensor.octopus_<account_number>_<device_name>_plugged`
- Zweck: Best-effort Steckstatus aus SmartFlex API-Zustaenden

Entscheidungslogik:

- `is_suspended = true` -> `unknown`
- `is_suspended = false` und `current_state = SMART_CONTROL_NOT_AVAILABLE` -> `off`
- `is_suspended = false` und sonstiger `current_state` -> `on`

Wichtige Einschraenkung:

- Die SmartFlex API liefert fuer Fahrzeuge kein dediziertes `isPlugged` Boolean.
- Bei pausiertem Smart Control ist der API-Status mehrdeutig, daher absichtlich `unknown`.

## Services

### `octopus_germany.set_device_preferences`

Setzt Ziel-SoC und Zielzeit fuer ein EV/Charge Point.

Parameter:

- `device_id` (required): Geraete-UUID
- `target_percentage` (required): 20-100 in 5%-Schritten
- `target_time` (required): `HH:MM` zwischen 04:00 und 17:00

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

Parameter:

- `account_number` (required): `A-xxxxxxxx`
- `date` (required): `YYYY-MM-DD`
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

Parameter:

- `account_number` (required)
- `period` (required): `month` oder `year`
- `year` (required)
- `month` (optional bei `period: month`)
- `filename` (optional)
- `layout` (optional): `wide` oder `tall`
- `summary` (optional): `true/false`

## iMSys / SMGW-HAN Empfehlung

Fuer direkte lokale HAN-Telemetrie kann diese Integration parallel genutzt werden:

- https://github.com/TRON4R/ha-ppc-smgw-han

Empfohlene Aufteilung:

- `octopus_germany`: Konto-, Tarif-, Dispatch- und SmartFlex-Steuerdaten
- `ha-ppc-smgw-han`: direkte HAN-Werte vom Smart Meter Gateway
