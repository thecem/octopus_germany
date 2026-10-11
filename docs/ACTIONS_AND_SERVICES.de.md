# Actions und Services

Sprache / Language: [Deutsch](ACTIONS_AND_SERVICES.de.md) | [English](ACTIONS_AND_SERVICES.md)

Diese Seite erklaert die wichtigsten EV-Aktionen und wie die Services der Integration sauber verwendet werden.

## Aktionen im Ueberblick

### Smart Charging Control Switch

- Entitaetsmuster: `switch.octopus_<account_number>_<device_id>_smart_control`
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

- Entitaetsmuster: `switch.octopus_germany_<account_number>_<device_id>_boost_charge`
- Zweck: Sofortiges Laden manuell starten

Verhalten:

- ON: Boost-Laden starten
- OFF: Boost-Laden beenden

Voraussetzungen:

- Smart Control sollte ON sein
- Geraet muss Boost unterstuetzen und LIVE sein

### Plugged Binary Sensor

- Entitaetsmuster: `binary_sensor.octopus_<account_number>_<device_id>_plugged`
- Zweck: Best-effort Steckstatus aus SmartFlex API-Zustaenden

Entscheidungslogik:

- `is_suspended = true` -> `unknown`
- `is_suspended = false` und `current_state = SMART_CONTROL_NOT_AVAILABLE` -> `off`
- `is_suspended = false` und sonstiger `current_state` -> `on`

Wichtige Einschraenkung:

- Die SmartFlex API liefert fuer Fahrzeuge kein dediziertes `isPlugged` Boolean.
- Bei pausiertem Smart Control ist der API-Status mehrdeutig, daher absichtlich `unknown`.

## Services

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

Parameter:

- `device_id` (required): Im UI per Name ausgewaehlt; in YAML HA-Geraeteregister-ID oder Octopus-Geraete-UUID
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

Die Datei wird unter `/config/octopus_germany/exports` gespeichert. Eine persistente Home-Assistant-Benachrichtigung enthaelt einen gleich-originigen Download-Link, der in einem neuen Tab oeffnet; Service-Antwort und Ergebnis-Event enthalten die URL ebenfalls. Der aktuelle HA-Host wird verwendet, sodass keine internen Container-Adressen im Link landen. Das dateigebundene Token liegt in HAs privatem Speicher und ist 30 Tage gueltig.

Der Export verwendet paginierte Monatsabfragen und lokale Kalendergrenzen aus der konfigurierten Home-Assistant-Zeitzone. Ein Jahresexport wird in Monatsabfragen aufgeteilt. Quellen- und Qualitaetsmetadaten bleiben beim Laden erhalten, die CSV enthaelt jedoch nur Verbrauchswerte; vor einer Bewertung als echte Zaehlerwerte muessen die Metadaten separat geprueft werden.

Die Service-Antwort enthaelt `measurement_metadata` mit `sources`, `reading_qualities`, `reading_frequencies`, `device_ids`, `register_ids`, `missing_device_id_count` und `missing_register_id_count`. Fehlende IDs sind bei manchen aggregierten Property-Messungen normal und kennzeichnen allein keine Schaetzung; fuer die Einordnung sind `sources` und `reading_qualities` massgeblich.

Parameter:

- `account_number` (required)
- `property_id` (optional): verwendet ohne Angabe die erste Strom-Property
- `period` (required): `month` oder `year`
- `year` (required)
- `month` (optional bei `period: month`)
- `filename` (optional)
- `layout` (optional): `wide` oder `tall`
- `resolution` (optional): `15min` oder `hour`; Standard ist `15min`
- `summary` (optional): `true/false`
- `go_window_start` und `go_window_end` (optional): lokale `HH:MM`-Grenzen fuer die Aufteilung in der Zusammenfassung

### `octopus_germany.export_cost_report`

Erstellt eine taegliche Kostenberechnung als CSV-Datei unter `/config/octopus_germany/exports` fuer einen Kalendermonat oder ein Jahr. Eine persistente Home-Assistant-Benachrichtigung enthaelt einen gleich-originigen Download-Link, der in einem neuen Tab oeffnet; Service-Antwort und Ergebnis-Event enthalten die URL ebenfalls. Der aktuelle HA-Host wird verwendet, sodass keine internen Container-Adressen im Link landen. Das dateigebundene Token liegt in HAs privatem Speicher und ist 30 Tage gueltig. Tarifbloecke und Bezeichnungen kommen aus den Agreement-Preisnamen und Aktivierungsregeln; GO/Standard werden nicht vorausgesetzt, Waermestromtarife werden ebenfalls unter ihrer API-Preisbezeichnung ausgewiesen. Der Netzbetreiber kommt aus den Daten des Stromzaehlpunkts. Modul, Rate-Typen, Zeitfenster und `validFrom`/`validTo` werden fuer diesen Netzbetreiber aus der API gelesen; an API-Gueltigkeitsgrenzen fragt der Service erneut ab, auch bei kuerzeren, z. B. quartalsweisen Zeitraeumen. Am Ende steht eine Summenzeile.

Die CSV enthaelt pro Kalendermonat eine Zeile `MONTH_TOTAL YYYY-MM`. Sie summiert die Tarif-/Netzzeitbloecke einzeln und zeigt die Monatsformel: Energie nach Netzentgeltkorrektur + Grundpreis - Modul-1-Gutschrift brutto = Monatsgesamtpreis brutto. Ist mindestens ein Tag unvollstaendig, bleibt der Monatsgesamtpreis leer; der Status nennt die Zahl der zu pruefenden Tage.

Monatliche API-Grundpreise werden mit dem Jahresfaktor `12 / 365` in den vertraglichen Tagessatz umgerechnet und anschliessend fuer jeden tatsaechlichen Kalendertag angesetzt. Damit bleibt der Grundpreis nicht kuenstlich in jedem Monat gleich, wenn der Tarif pro Tag abgerechnet wird.

Parameter:

- `account_number` (erforderlich)
- `property_id` (optional): ohne Angabe wird die erste Strom-Property verwendet
- `period` (erforderlich): `month` oder `year`
- `year` (erforderlich); `month` ist fuer Monatsberichte erforderlich
- `contract_start_network_charge_ct_kwh` (erforderlich, Vorgabe `7.65`): der **Netto-Netzentgeltanteil** in ct/kWh, der laut urspruenglichem Vertrag/Preisblatt bereits im Brutto-Arbeitspreis enthalten ist. Der Bericht ersetzt diese Baseline durch den zeitlich gueltigen Satz des zustaendigen VNB; er schlaegt nicht das gesamte Netzentgelt nochmals auf. `7.65` ist ein Referenzwert aus dem Preisblatt eines VNB von 2024, kein allgemeiner oder gesetzlicher Standard. Nur verwenden, wenn der urspruengliche Vertrag diese Baseline bestaetigt.
- `module3_start_date` (optional): Datum, ab dem du Modul 3 fuer diesen Zaehlerpunkt erklaert/gewaehlt hast; ab diesem Datum werden zeitvariable API-Saetze auch dann genutzt, wenn das API-Feld `module` noch `MODULE_1` meldet
- `module3_rates_json` (optional): JSON-Array manueller Saetze fuer historische Zeitraeume ohne API-Zeitfenster; Rate netto in ct/kWh, Zeiten lokal
- `module1_start_date` (optional): Startdatum fuer die zeitanteilige, manuell angegebene Modul-1-Gutschrift
- `module1_annual_credit_net_eur` (erforderlich, Standard `0`): jaehrliche Netto-Gutschrift des zustaendigen Netzbetreibers; der Betrag muss dem ausgewaehlten Abfragejahr entsprechen
- `vat_percent` (erforderlich, Standard `19`): Ersatzwert, wenn das Agreement keinen MwSt.-Satz liefert
- `filename` (optional): CSV-Dateiname unter `/config`

Beispiel fuer manuelle historische Saetze:

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

Die Beispielwerte stammen aus dem Preisblatt eines VNB fuer 2025, gueltig fuer Modul 3 ab 1. April 2025: OFFPEAK 1,99 ct/kWh, STANDARD 6,64 ct/kWh und PEAK 12,75 ct/kWh. Setze `module3_start_date` auf das fuer deinen Zaehlerpunkt erklaerte/gewaehlte Wirksamkeitsdatum. Die Vorbelegung wird nur beim passenden Netzbetreiber-Code angewendet; bei einem anderen VNB dessen eigene Werte eintragen. API-Zeitplaene werden ab diesem Datum auch verwendet, wenn die API als Modul `MODULE_1` meldet.

Ist Modul 3 gewaehlt, aber fuer ein Zeitfenster weder ein passender API-Satz noch ein manueller Satz vorhanden, verwendet der Bericht den verfuegbaren API-`STANDARD`-Netzentgeltsatz und kennzeichnet `module3_rate_basis` mit `API STANDARD grid fee fallback`. Die Zahl der Fallback-Tage steht in Service-Antwort, Event und Benachrichtigung. Das ist ausdruecklich ein Netzentgeltsatz, kein separater „Modul-1-ST“-Preis.

Berechnungsbasis nach §14a EnWG: Der Brutto-Vertrags-AP wird nur um die Differenz zwischen dem aktuell gueltigen Netto-Netzentgelt und dieser Netto-Baseline angepasst; auf die Differenz wird die MwSt. angewendet:

`angepasster Brutto-AP [EUR/kWh] = Brutto-Vertrags-AP [EUR/kWh] + ((aktuelles Netto-Netzentgelt - Netto-Baseline) [ct/kWh] / 100) × (1 + MwSt.)`

Die Umrechnung von ct/kWh in EUR/kWh erfolgt dabei einheitlich in der Integration. Regulatorischer Kontext sind die BNetzA-Festlegung BK6-22-300 zum Marktprozess fuer §14a sowie BK8-22/010-A zu Netzentgeltregeln und Kalkulation. Diese Festlegungen liefern weder deine Vertragsbaseline noch den Nachweis deiner Modul-3-Wahl. Baseline mit dem urspruenglichen Vertrag/Preisblatt und Wirksamkeitsdatum mit Kundenerklaerung und VNB-Unterlagen abgleichen.

Beispiel:

```yaml
action: octopus_germany.export_cost_report
data:
  account_number: "A-12345678"
  period: month
  year: 2026
  month: 9
  contract_start_network_charge_ct_kwh: 7.65
  module3_start_date: "2025-07-01"
  # module3_rates_json bei fehlenden API-Saetzen ergaenzen.
  module1_start_date: "2025-03-19"
  module1_annual_credit_net_eur: 108.33
  vat_percent: 19
```

Als regulatorischer Rahmen werden BK6-22-300 der BNetzA fuer Marktprozesse und BK8-22/010-A fuer Netzentgeltregeln und deren Kalkulationsrahmen beruecksichtigt. Der Service berechnet transparent aus API-Werten und expliziten Nutzereingaben; er trifft keine rechtliche Feststellung zu Anspruch, Teilnahme oder Rechnungsrichtigkeit. Netzbaseline und Modul-1-Eingaben muessen anhand des geltenden Vertrags und der Unterlagen des zustaendigen Netzbetreibers geprueft werden. Fehlende Tarif-, Netzentgelt- oder Grundpreisdaten werden als unvollstaendig ausgewiesen, nicht als 0 eingesetzt. Im laufenden Kalenderjahr endet der Abruf zwei Tage vor heute, damit noch nicht erwartbare Messwerte nicht als fehlend gelten.

Die CSV verwendet Semikolon als Spaltentrenner und das deutsche Dezimalkomma. Verbrauch wird mit drei Nachkommastellen, Eurobetraege werden auf Cent und Arbeitspreise in €/kWh mit sechs Nachkommastellen angezeigt. Die Berechnung und Summen behalten intern ihre volle Genauigkeit.

### `octopus_germany.submit_meter_readings`

Schreibt Strom- oder Gas-Zaehlerstaende in die OE-API.

Parameter:

- `account_number` (required): Konto, dem der Zaehler gehoert
- `meter_type` (required): `electricity` oder `gas`
- `meter_id` (required): OE-Meter-ID aus den Attributen des Meter-Entitaets
- `reading_date` (required): `YYYY-MM-DD`
- `readings_json` (optional): JSON-Array von Eintraegen mit `value` und `register_obis_code`
- `reading_value` und `register_obis_code` (optional): Hilfsfelder fuer einen einzelnen Registerwert

Beispiel:

```yaml
service: octopus_germany.submit_meter_readings
data:
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
