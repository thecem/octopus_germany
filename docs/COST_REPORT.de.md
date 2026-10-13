# Stromkostenbericht

`octopus_germany.export_cost_report` erstellt eine taegliche und monatliche Kostenschaetzung aus Octopus-Agreement-Preisen, Smart-Meter-Messwerten, Grundpreisen und den fuer den Zaehlerpunkt gelieferten Netzentgelten des zustaendigen Netzbetreibers.

Der Bericht ist eine nachvollziehbare Berechnungshilfe, keine Lieferantenrechnung und keine rechtliche Entscheidung ueber Anspruch oder Teilnahme nach §14a EnWG. Fehlende Preise und Saetze werden nicht stillschweigend als null behandelt.

## Exportpaket: ein Abruf, zwei Dateien

Im UI unter **Entwicklerwerkzeuge > Aktionen** die Aktion
`octopus_germany.export_cost_report` auswaehlen und zum UI-Modus wechseln.
Kontonummer, Jahr und bei Monatsberichten den Monat eingeben; fuer das
Exportpaket `format: package` auswaehlen. Nach einem Integrationsupdate
Home Assistant neu starten und die Browserseite neu laden, damit die
Aktionsbeschreibung aktualisiert wird.

Mit `format: package` erzeugt derselbe Messwertabruf:

1. eine `.xlsx` mit Rohwerten, editierbaren Preisen und Excel-Formeln,
2. eine `_measurements_15min.csv` mit ungerundeten Viertelstunden-kWh,
   96 regulaeren Uhrzeitspalten je Tag und Datenstatus.

Die Downloadmeldung enthaelt zwei separat geschuetzte Links. Im Paketmodus
verweisen `output_file` und `download_url` auf die XLSX;
zusaetzlich enthaelt `files` die zwei Eintraege mit `type`, `output_file`
und `download_url`. Ohne `format` bleibt der bisherige CSV-Export erhalten.
Es ist kein vorheriger Aufruf von `export_smart_meter_csv` erforderlich.
Dieser separate Messwerte-CSV-Service bleibt verfuegbar. Der Paketmodus
erzeugt keine Kosten-CSV mehr; bereits exportierte Dateien werden nicht geloescht.

```yaml
action: octopus_germany.export_cost_report
data:
  account_number: A-REPLACE-ME
  period: month
  year: 2026
  month: 5
  format: package
  contract_start_network_charge_ct_kwh: 7.65  # eigenen Vertragswert pruefen
  network_comparison: contract_start
response_variable: cost_export
```

Die XLSX hat die Blaetter **Rechnung**, **Eingaben**, **Messwerte**,
**Tarifpreise**, **Grundpreise**, **Netzpreise**, **Intervalle**,
**Tageswerte** und **Basis**. Blau markierte Messwerte, Tarif-/Netzpreise
und Intervall-Preis-IDs sind editierbar. Monatsrechnungen, Tarif- und
Netzband-Tagesmengen sowie Kosten aktualisieren sich offline, ohne Makros,
API-Verbindungen oder externe Arbeitsmappenlinks. Der Export speichert
initiale Formelergebnisse fuer Vorschauprogramme.

Die im Abruf gueltige **Vertragszuordnung** entscheidet, ob beispielsweise
GO/STANDARD oder Heat Niedrig/Standard/Hoch verwendet wird. Es gibt kein
festes Modell GO + STANDARD + HEAT. Heat-Zeitfenster und Preise kommen
aus dem gueltigen Agreement, nicht pauschal von einer Website. Heat-
Messentgelte, die schon im Vertragsgrundpreis enthalten sind, werden nicht
nochmals berechnet. Netz-NT/ST/HT wird unabhaengig von den Vertragspreiszonen
zugeordnet. Historische Intelligent-GO-Zusatzslots werden nicht erfunden:
eine manuelle Tarif-ID-Zuordnung in Excel ist moeglich, soweit die
historischen Agreement-Preise diese Slots nicht bereits abbilden.

`network_comparison: current_year` benoetigt
`standard_network_charge_ct_kwh`, den dokumentierten **normalen**
Netzentgeltsatz des Berichtjahrs in netto ct/kWh. Das Modul-3-ST-Band
ist nicht automatisch dieser Satz. Der Vergleich veraendert den
ausgewiesenen Modul-3-Effekt, nicht die effektiven Endkosten:

```text
Tarifkosten + Grundgebuehr
+ Anpassung Vertragsnetz an Vergleichsnetz
- Modul 1 Gutschrift
- (Vergleichs-Netzkosten - tatsaechliche NT/ST/HT-Netzkosten)
= Gesamtkosten
```

Vor Modul-3-Wirksamkeit wird die normale Netzaenderung als
Referenzanpassung ausgewiesen, nicht als Modul-3-Einsparung.

Der Paketmodus prueft Vollstaendigkeit: normale lokale Tage haben 96,
Zeitwechseltage 92 oder 100 Intervalle. Zusaetzliche Herbstwerte erhalten
`(2)`-Spalten; in der XLSX stehen UTC und lokale Uhrzeit mit Offset.
Nicht existierende Fruehlingsintervalle bleiben leer und zaehlen nicht
als fehlend. Echte Nullmessungen bleiben null, fehlende Messwerte leer.
Fehlende Preise oder Messwerte sperren die Rechnung. Fehlende Messwerte
koennen in Excel nachgetragen werden; ungueltige/duplizierte Quelldaten
bleiben gesperrt und erfordern einen korrigierten neuen Export.

Der aktuelle Jahresvergleich verwendet einen eingegebenen normalen
Jahressatz. Im Paketmodus wird dieser auch fuer die tatsaechlichen
Netzkosten vor Modul-3-Wirksamkeit verwendet. Ohne diesen Wert wird ein
variabler ST-Satz nicht als normales Jahresentgelt akzeptiert; die
betroffene Rechnung bleibt unvollstaendig. Tatsaechliche zeitvariable Saetze und Vertragswechsel werden
weiterhin intervallgenau aus den gelieferten Gueltigkeiten ausgewaehlt;
die vollstaendigen Zeitplaene stehen im Blatt Basis. Preis-IDs erlauben
manuelle Szenarien, berechnen bei einer Aenderung von Zeitfenstern jedoch
nicht automatisch eine neue Vertragszuordnung.

## Berechnungsgrundlage

### Vertrags-Arbeitspreis und Netzentgeltkorrektur

Fuer jedes Messintervall waehlt der Bericht das zu diesem Zeitpunkt gueltige Agreement und daraus die Preisstufe, deren Gueltigkeit und Aktivierungszeitfenster passen. Die Preisbezeichnung des Agreements bleibt erhalten, auch bei Waermestromtarifen. Der ausgewaehlte Brutto-Vertrags-AP wird nur um die Differenz zwischen dem aktuellen Netto-Netzentgelt und dem Netto-Netzentgeltanteil angepasst, der bereits im urspruenglichen Vertrags-AP enthalten war:

```text
angepasster Brutto-AP [EUR/kWh]
  = Brutto-Vertrags-AP [EUR/kWh]
  + ((aktuelles VNB-Netzentgelt [ct/kWh] - Vertragsbaseline [ct/kWh]) / 100)
    * (1 + MwSt.-Anteil)
```

Die angepassten Intervallkosten ergeben sich aus kWh mal angepasstem AP. Die Netzentgeltdifferenz wird vor dem Aufschlag von ct in EUR umgerechnet. Vorrang hat der MwSt.-Satz aus der passenden Agreement-Preisstufe; andernfalls gilt `vat_percent`.

`contract_start_network_charge_ct_kwh` ist der **Netto-Netzentgeltanteil, der bereits im urspruenglichen Brutto-Vertrags-AP enthalten war**. Es ist weder das gesamte aktuelle Netzentgelt noch ein aus dem Tarifnamen abgeleiteter Wert. Die Vorgabe `7.65 ct/kWh` ist nur ein unbestaetigter Referenzwert aus dem Preisblatt eines VNB aus 2024. Vor Verwendung der Summen mit dem Vertrag/Preisblatt fuer den konkreten Zaehlerpunkt abgleichen.

### Modul-3-Netzentgelte

Netzentgeltzeitplaene werden fuer die relevanten Daten und den Netzbetreiber abgefragt. An API-Gueltigkeitsgrenzen fragt der Service erneut ab, damit auch kuerzere Gueltigkeitszeitraeume beruecksichtigt werden. Gemeldetes API-Modul, Rate-Typen, Zeitfenster und Gueltigkeitsdaten werden getrennt vom kundenseitig gewaehlten Wirksamkeitsdatum dokumentiert.

`module3_start_date` ist das Datum, ab dem der Kunde Modul 3 fuer diesen Zaehlerpunkt erklaert/gewaehlt hat. Ab diesem Datum werden zeitvariable API-Saetze verwendet, auch wenn die API weiterhin `MODULE_1` meldet. Das API-Modul allein belegt nicht die Auswahl des Kunden.

`module3_rates_json` ist ein optionales Array manuell eingetragener **Netto-Saetze** in ct/kWh fuer Intervalle, fuer die die API keine passenden Saetze liefert. Ein Eintrag verwendet:

- `rate_type`: `OFFPEAK`, `STANDARD` oder `PEAK`
- `start_time`, `end_time`: lokale Intervallgrenzen im Format `HH:MM:SS`
- `rate_cents_per_kwh`: Netto-Satz in ct/kWh
- `valid_from`, `valid_to`: optionale ISO-Zeitstempel; `valid_to` ist exklusiv

Ein passender API-Satz hat Vorrang; manuelle Werte fuellen fehlende Intervalle. Wenn kein Modul-3-Satz verfuegbar ist, kann ein zeitlich passender API-`STANDARD`-Netzentgeltsatz als explizit markierter Fallback dienen (`module3_rate_basis`). Das ist ein STANDARD-Netzentgeltsatz, kein separater „Modul-1-ST“-Preis. Fehlt auch dieser Satz, werden betroffene Verbrauchswerte als fehlend markiert; bei einem unvollstaendigen Tag bleibt der Monatsgesamtpreis leer.

Das Serviceformular enthaelt als Komfortfunktion den 2025-Zeitplan eines VNB als Vorbelegung. Er wird nur angewendet, wenn der erkannte Netzbetreiber-Code zu dieser Vorbelegung passt. Gueltig ist das Beispiel vom 1. April bis 31. Dezember 2025; fuer andere Netzbetreiber oder Zeitraeume die tatsaechlichen Saetze eintragen. Nicht fuer Februar 2026 wiederverwenden.

### Datei mit eigenen Zeitplaenen

Der Service kann auch `/config/octopus_germany/grid_fee_schedules.json` lesen und waehlt einen Eintrag anhand des vom Konto erkannten Netzbetreiber-Codes und des Abfragejahrs aus. Eine Startdatei mit Beispieldaten liegt unter [`grid_fee_schedules.example.json`](examples/grid_fee_schedules.example.json). Diese Datei an den Config-Pfad kopieren, den Code-Platzhalter ersetzen und alle Betraege und Gueltigkeitsdaten mit den aktuellen Unterlagen fuer den Zaehlerpunkt abgleichen.

Jahreseintraege enthalten ein `schedules`-Array fuer einen oder mehrere, nicht ueberlappende Gueltigkeitszeitraeume. Jeder Zeitraum hat `valid_from`, ein exklusives `valid_to`, Netto-`rates_net_ct_per_kwh` und genau 24 `hourly_rate_types` fuer die Stunden 0 bis 23. Benachbarte Stunden bleiben getrennt. Akzeptierte Bezeichnungen sind `NT`/`ST`/`HT` und `OFFPEAK`/`STANDARD`/`PEAK`; `null` bedeutet, dass fuer diese Stunde kein Dateisatz vorliegt. Vorrang haben API-Saetze, dann explizite Service-JSON-Werte; passende Dateisaetze fuellen verbleibende Luecken.

Der optionale Jahreswert `module1_credit_net_eur` wird nur verwendet, wenn `module1_annual_credit_net_eur` im Serviceaufruf leer ist. Ein expliziter Servicewert, auch null, hat Vorrang. `basis_rate_net_ct_per_kwh` ist ein Informationswert und **nicht** die Vertragsbaseline der Arbeitspreisanpassung. Passender Zeitplan und Stundenwerte werden in einer `BASIS`-CSV-Zeile dokumentiert. Fehlende, ungueltige oder nicht passende Dateien erzeugen eine Warnung, statt unbemerkt ignoriert zu werden.

### Grundpreis

Der Bericht verwendet, wenn vorhanden, den gueltigkeitsdatierten Brutto-Monatsgrundpreis des Agreements. Ist nur der Nettobetrag vorhanden, wird der MwSt.-Ersatzwert angewendet. Der Monatsbetrag wird mit `Monatsbetrag * 12 / 365` in einen Tagessatz umgerechnet und fuer jeden tatsaechlichen Tag des Berichtszeitraums angesetzt. So entspricht die Berechnung einer tagweisen Abrechnung, statt jeden Kalendermonat mit demselben Grundpreis anzusetzen.

### Modul-1-Gutschrift

Ist `module1_start_date` gesetzt, wird `module1_annual_credit_net_eur` durch die Anzahl der Tage des jeweiligen Kalenderjahres geteilt und ab diesem Datum angesetzt. Der Bericht rechnet die taegliche Nettogutschrift mit dem MwSt.-Ersatzwert brutto und zieht sie von der Bruttosumme ab. Der Jahresbetrag muss zum ausgewaehlten Berichtsjahr passen. Wenn Modul 1 nicht gilt oder der Betrag unbekannt ist, Startdatum leer lassen und null verwenden.

## Parameter

| Parameter | Zweck |
| --- | --- |
| `account_number` | Erforderliches Konto, dessen Agreements und Messwerte exportiert werden. |
| `property_id` | Optionale Strom-Property; ohne Angabe wird die erste verwendet. |
| `period`, `year`, `month` | Monats- oder Kalenderjahresbericht; `month` ist fuer einen Monatsbericht erforderlich. Im laufenden Jahr endet der Abruf zwei Tage vor heute. |
| `contract_start_network_charge_ct_kwh` | Erforderliche, dokumentierte Netto-Vertragsbaseline in ct/kWh; Vorgabe `7.65` ist nur ein unbestaetigter Referenzwert. |
| `module3_start_date` | Optionales, vom Kunden angegebenes Wirksamkeitsdatum von Modul 3; bestimmt den Einsatz zeitvariabler Saetze. |
| `module3_rates_json` | Optionale manuelle Netto-Zeitfenster fuer Zeitraeume, in denen passende API-Saetze fehlen. |
| `module1_start_date` | Optionales Wirksamkeitsdatum fuer die zeitanteilige Modul-1-Gutschrift. |
| `module1_annual_credit_net_eur` | Optionale Nettogutschrift fuer das ausgewaehlte Abfragejahr; ein expliziter Wert (auch null) hat Vorrang, sonst gilt der passende Dateiwert oder null. |
| `vat_percent` | MwSt.-Ersatzwert, wenn eine Agreement-Preisstufe keinen Satz enthaelt; Vorgabe 19 %. |
| `filename` | Optionaler Ausgabedateiname. |

## CSV-Aufbau

Die Zeilen sind ueber `record_type` gekennzeichnet:

- `DAY`: Tagesverbrauch und Kosten je Agreement-Tarifbezeichnung und Netzentgeltzeitfenster; enthaelt API-Modul, Satzbasis, angewendete Netto-/Brutto-Netzentgeltsaetze, fehlende kWh und Status.
- `MONTH_TOTAL`: Summen je Tarif-/Netzentgeltblock, Brutto-Grundpreis, Modul-1-Gutschrift und Brutto-Monatsgesamtpreis. Bei Satzwechseln sind die Saetze verbrauchsgewichtet.
- `TOTAL`: Summen fuer den Berichtszeitraum.
- `BASIS`: Pruefzeilen nach der Summe mit Eingaben, Agreement-Preisen/Grundpreisstufen und der API-Netzentgeltantwort pro Monat samt Gueltigkeiten.

Die Monatsberechnung lautet:

```text
Brutto-Energiekosten nach Netzentgeltkorrektur
+ Brutto-Grundpreis
- Modul-1-Gutschrift brutto
= Brutto-Monatsgesamtpreis
```

Ist ein Tag unvollstaendig, bleibt der `MONTH_TOTAL`-Betrag leer. `status`, `unpriced_kwh` und `network_rate_missing_kwh` zeigen den Grund; ein fehlender Gesamtbetrag darf nicht als null interpretiert werden. Die CSV nutzt Semikolon als Spaltentrenner und das deutsche Dezimalkomma. Verbrauch wird mit drei Nachkommastellen, Eurobetraege auf Cent und Arbeitspreise mit sechs Nachkommastellen angezeigt. Intern bleibt die volle Genauigkeit bis zur Formatierung erhalten.

Dateien werden unter `/config/octopus_germany/exports` gespeichert. Home Assistant erstellt eine persistente Benachrichtigung mit einem dateigebundenen Download-Link, der nach 30 Tagen ablaeuft.

## Rechts- und Regelungskontext

Der regulatorische Rahmen der Berechnung ist §14a EnWG, die Festlegung BK6-22-300 der Bundesnetzagentur zum Marktprozess und BK8-22/010-A zu Netzentgeltregeln und Kalkulation. Diese Grundlagen liefern weder die Vertragsbaseline eines Kunden noch den Nachweis, dass Modul 3 gewaehlt wurde. Die Integration stellt keine rechtliche Anspruchs- oder Wirksamkeitspruefung dar und ersetzt keine Lieferantenrechnung. Modul-3-Erklaerung/Wirksamkeitsdatum, Vertragsbaseline und manuelle historische Saetze muessen anhand der Kundenunterlagen und der Preisblaetter des zustaendigen Netzbetreibers geprueft werden.
