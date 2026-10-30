# Implementierungsplan: gemeinsames Stromkosten-Exportpaket

Stand: 13.10.2026. Die abgestimmte Variante ist in Version 0.0.190 umgesetzt.
Ein Exportauftrag erzeugt aus einem gemeinsamen Messwertabruf die
Messwerte-CSV und eine offline berechenbare XLSX, ohne zusaetzliche Kosten-CSV.
Der bisherige Kosten-CSV-Export bleibt das Standardverhalten.

## 1. Abgestimmtes Zielbild

```text
export_cost_report: format: package
                 |
                 v
Viertelstundenwerte einmal pro angefragtem Monat abrufen
+ gueltige Vertraege, Preise und Netzentgelte
                 |
                 v
Gemeinsame Intervall-/Berechnungsbasis
                 |
      +----------------------+
      |                      |
      v                      v
Messwerte-CSV          Kostenbericht.xlsx
```

Ein vorheriger Aufruf von `export_smart_meter_csv` oder ein Wiedereinlesen
der erzeugten CSV ist nicht erforderlich. So bleiben Mengen, Gueltigkeiten
und Preiszuordnungen identisch, ohne doppelte API-Abfragen und ohne
Rundungsverluste durch eine CSV-Zwischenstufe.

Empfehlung und Umsetzung: Rohmesswerte **sowohl in der XLSX als auch
zusaetzlich als CSV**. Die XLSX ist damit allein nutzbar; die CSV bleibt ein
unabhaengiges Archiv-/Austauschformat.

## 2. Vertragsmodell: GO oder Heat, nicht GO plus Heat

Die jeweils gueltige Vertragszuordnung entscheidet ueber die Preiszonen:

| Vertragsmodell | Rechnungspositionen |
| --- | --- |
| GO | Verbrauch GO und Verbrauch STANDARD |
| Heat | Verbrauch Niedrig, Standard und Hoch |

Die beschriebenen Heat-Zeitfenster sind:

- Niedrig: 02:00-06:00 und 12:00-16:00.
- Standard: 06:00-12:00, 16:00-18:00 und 21:00-02:00.
- Hoch: 18:00-21:00.

**Entscheidend bleiben die tatsaechlichen Aktivierungsregeln, Preise und
Gueltigkeiten des individuellen Vertrags.** Die Integration uebernimmt
keine allgemeinen Website-Preise und setzt auch keine universellen
Heat-Zeitfenster anstelle der Vertragsdaten.

Heat-Messentgelte, die bereits im Vertragsgrundpreis enthalten sind,
werden nicht nochmals als beispielsweise 35 EUR/Jahr aufgeschlagen.

Die Netzzeitzonen **NT/ST/HT** sind eine unabhaengige Dimension.
Beispielsweise kann Heat Standard gleichzeitig Netz-HT sein.
Auch ein Vertragswechsel innerhalb eines Monats wird intervallgenau
beruecksichtigt; beide gueltigen Vertraege erscheinen dann nachvollziehbar.

## 3. Bedienung und Ausgabevertrag

```yaml
action: octopus_germany.export_cost_report
data:
  account_number: A-REPLACE-ME
  period: month
  year: 2026
  month: 5
  format: package
  # Optional: weglassen, um den belegten Basiswert je Vertragsbeginn aus der Datei zu verwenden.
  network_comparison: contract_start
response_variable: monthly_cost_export
```

- `format: csv` bzw. keine Angabe: bisherige Kosten-CSV.
- `format: package`: `.xlsx` und `_measurements_15min.csv`, keine Kosten-CSV.
- Der separate Service `export_smart_meter_csv` bleibt verfuegbar.
- Bestehende Modul-1-/Modul-3-Parameter bleiben verwendbar.
- `network_comparison`: `contract_start` oder `current_year`.
- `standard_network_charge_ct_kwh`: bei Paketvergleich `current_year`
  erforderlicher dokumentierter normaler Jahressatz, netto ct/kWh.
  Er wird nicht aus dem Modul-3-ST-Band abgeleitet.
- Eine Abschlussmeldung zeigt zwei separat geschuetzte Downloadlinks.
- `output_file` und `download_url` verweisen im Paketmodus auf die XLSX,
  im CSV-Modus weiterhin auf die Kosten-CSV.
  Die Antwortliste `files` enthaelt beide Paketergebnisse mit
  `type`, `output_file` und `download_url`.
- Die vorhandene Monatsautomation nutzt nun einen Paketaufruf pro Monat.
- Ein zusaetzliches ZIP ist nicht Bestandteil dieser Umsetzung.

## 4. XLSX-Aufbau und Offline-Berechnung

| Blatt | Zweck |
| --- | --- |
| Rechnung | Monatspositionen untereinander, Mengen, Preise, Grundgebuehr, Modul 1, Modul 3, Gesamtsumme und ausgeschriebener Netzentgeltaustausch; bei Jahresberichten zusaetzlich Gesamtsumme |
| Eingaben | Vertragsnetz, Vergleichsbasis, normales Jahresnetz, Modul-1-Betrag/Startdatum und Umsatzsteuer-Ersatzwert |
| Messwerte | Original-Viertelstundenmengen pro Tag, 96 regulaere Uhrzeitspalten und Zusatzspalten fuer wiederholte Herbstintervalle |
| Tarifpreise | Gueltig ausgewaehlte Vertragspreiszonen, editierbare Arbeitspreise und Umsatzsteuersaetze |
| Grundpreise | Editierbare Brutto-Monatsgrundpreise |
| Netzpreise | Editierbare Netto-Netzentgelte je ausgewaehlter Netzband-/Preis-/Quellenkombination |
| Intervalle | UTC, lokale Uhrzeit mit Offset, kWh, Tarif-ID, Netz-ID, Preise, Status und Kostenformeln |
| Tageswerte | Gesamtmengen/-kosten sowie Tagesmengen und Kosten je Vertragszone und Netzband |
| Basis | Eingaben, vollstaendige Vertrags-/API-Zeitplaene mit Gueltigkeiten und Herkunft |

Blaue Eingabezellen sind editierbar. Die Berechnung verwendet normale
Excel-Formeln; keine Makros, externen Arbeitsmappenlinks oder API-Verbindungen.
Initiale Formelergebnisse fuer reine Vorschauprogramme werden mitgeliefert.

Die Tarif- und Netzzuordnung je Intervall wird beim Export mit den
vorhandenen Berechnungshelfern getroffen. Preis-IDs koennen fuer
manuelle Szenarien geaendert werden, beispielsweise einen bestaetigten
Intelligent-GO-Zusatzslot. Das Aendern von Zeitfenstern in einem
Basis-JSON loest keine automatische neue Vertragsauswahl in Excel aus.

Historische Intelligent-Zusatzslots werden nicht aus Tagesmengen
rekonstruiert. Die XLSX weist auf diese Grenze hin; solche Slots sind
nur automatisch enthalten, soweit die gelieferten historischen
Agreement-Preise sie bereits abbilden.

## 5. Fachliche Rechenregeln

Bezeichnungen: `q` = kWh, `AP` = Vertrags-AP brutto EUR/kWh,
`N_vertrag` = bereits enthaltener Netzanteil netto ct/kWh,
`N_ref` = Vergleichsnetz netto ct/kWh, `N_band` = tatsaechliches
Netzentgelt netto ct/kWh, `u` = Umsatzsteuer-Anteil.

```text
Tarifkosten               = Summe(q * AP)
Referenzanpassung          = Summe(q * (N_ref - N_vertrag) * (1 + u) / 100)
Vergleichs-Netzkosten      = Summe(q * N_ref * (1 + u) / 100)
Tatsaechliche Netzkosten   = Summe(q * N_band * (1 + u) / 100)
Modul-3-Einsparung         = Vergleichs-Netzkosten - tatsaechliche Netzkosten

Monatskosten =
    Tarifkosten + Grundgebuehr + Referenzanpassung
  - Modul-1-Gutschrift - Modul-3-Einsparung
```

Damit wird das enthaltene Vergleichs-Netzentgelt abgezogen und
NT/ST/HT-Netzentgelt hinzugefuegt, **nicht doppelt aufgeschlagen**.
Die ausgeschriebenen Detailpositionen sind bereits verrechnet und
werden nicht nochmals zur Gesamtsumme addiert.

- Vertragsstartvergleich: `N_ref = N_vertrag`, Anpassung = 0.
- Aktuelles-Jahr-Vergleich: dokumentierten normalen Jahressatz verwenden.
  Der Endbetrag bleibt bei denselben effektiven Preisen unveraendert,
  nur die ausgewiesene Einsparung aendert sich.
- Vor Modul 3 wird eine normale Jahresentgeltaenderung als
  Referenzanpassung, nicht als Modul-3-Einsparung ausgewiesen.
- Modul 3 kann auch Mehrkosten ergeben.
- Modul 1: Netto-Jahresgutschrift / Kalendertage des Jahres ab Startdatum,
  danach Umsatzsteuer-Ersatzwert und Abzug von den Gesamtkosten.
- Grundgebuehr: gueltiger Vertrags-Monatsbetrag x 12 / 365 je Tag,
  unveraendert zur bisherigen Reportlogik. Kein neuer pauschaler Monatsmodus.
- Der aktuelle Jahresvergleich nutzt einen eingegebenen Jahressatz.
  Dieser dient im Paketmodus auch als normales Netzentgelt vor Modul 3.
  Ohne ihn wird ein variabler ST-Satz dort nicht als normales Jahresentgelt
  akzeptiert; betroffene Kosten bleiben unvollstaendig.
  Zeitvariable tatsaechliche Netzpreise behalten ihre API-/manuellen
  Gueltigkeiten; das ST-Band wird nicht als normales Jahresentgelt ausgegeben.

## 6. Datenqualitaet und Sicherheit

- Normale lokale Tage: 96 Viertelstunden; Zeitwechseltage: 92 oder 100.
- UTC-Zeitstempel bleiben eindeutig; wiederholte lokale Zeiten erhalten
  `(2)`-Spalten und behalten im Intervallblatt den UTC-Offset.
- Nicht existierende Fruehlingsintervalle sind in der Matrix grau markiert
  und zaehlen nicht als fehlend.
- Originalmengen bleiben in der Rohwerte-CSV ungerundet.
- Nullmessung ist gueltig, fehlende Messung bleibt leer.
- Fehlende Messwerte oder Preiszuordnungen sperren Tages-/Monatsrechnung.
  Fehlende Werte koennen offline nachgetragen werden, wenn Preise vorliegen.
- Ungueltige/duplizierte Quelldaten bleiben explizit markiert und gesperrt;
  ein korrigierter Export ist erforderlich.
- Die zwei Dateien werden zuerst temporaer erzeugt und erst nach
  erfolgreicher Erstellung bereitgestellt. Schreibfehler werden als
  Servicefehler gemeldet, nicht als erfolgreicher Download.
- Bestehende geschuetzte Downloadpfade und dateispezifische Tokens bleiben erhalten.
- API-Texte werden als Text geschrieben, nicht als Excel-Formeln.
- Keine neuen Messentgelt-Aufschlaege, EV-Sensoraenderungen oder
  Aenderungen am Tag-/Release-Workflow.

## 7. Implementierungsstand

Umgesetzt:

1. Gemeinsame Intervallinformationen aus `cost_report.py` fuer CSV und XLSX.
2. Paketmodus im vorhandenen Service mit einem Messwertabruf pro Monat.
3. CSV mit echten Viertelstundenmengen und XLSX mit Formeln.
4. Vertragsabhaengige GO-/Heat-Positionen und getrennte Netzzeitzonen.
5. Vergleichsbasis ohne Doppelberechnung und Modul-1-Gutschrift.
6. Vollstaendigkeitspruefung einschliesslich Zeitumstellung.
7. Paketnotification, Antwortliste, Dokumentation und Versionsbump.

Die Datei
[Kostenbericht_Beispiel_2026-05.xlsx](./Kostenbericht_Beispiel_2026-05.xlsx)
bleibt der **erste Layout-Prototyp aus den gelieferten Tagesaggregaten**.
Sie ist nicht die Vorlage des produktiven Paketgenerators: In ihr fehlen
echte Viertelstundenwerte und sie enthielt noch ein optionales HEAT-Segment
neben GO/STANDARD. Der neue Export verwendet stattdessen echte
Intervallwerte und die tatsaechlichen Zonen des jeweiligen Vertrags.

## 8. Abnahme und verbleibende Grenzen

Regressionen pruefen:

- Uebereinstimmung der Workbook-Summen mit der gemeinsamen Python-Berechnung.
- GO vs. drei Heat-Zonen; keine erfundene kombinierte Tarifstruktur.
- Unabhaengige Heat-Standard- und Netz-HT-Zuordnung.
- Vergleichswechsel aendert Einsparung, nicht Endkosten.
- Ohne Modul 3 werden normale Netzaenderungen nicht als Modul-3-Effekt gezeigt.
- Null-/Praezisionsmengen, fehlende/ungueltige/duplizierte Werte und 92/100 Tage.
- Ein gemeinsamer Monatsabruf, genau zwei persistente Dateien, zwei Links.
- Bisheriger CSV-Standard, Servicevalidierung und ausdruecklicher Schreibfehler.
- Keine aktiven Excel-Formeln aus API-Texten oder externe Arbeitsmappenlinks.

Zusaetzlich wurden die tatsaechlichen XLSX-Formeln unabhaengig neu
ausgewertet: Heat-Summe, Vergleichswechsel, fehlende Vergleichsrate,
fehlende/negative Messwerte, editierter Grundpreis und geaenderte
Tarif-/Netzpreise. Die vollstaendige Testsuite besteht mit 129 Tests;
gezielter Lint fuer Exportmodul, Downloadmodul und neue Tests sowie
Format- und Whitespace-Pruefung bestehen ebenfalls.

Native Darstellung und Neuberechnung in Microsoft Excel/LibreOffice
bleiben ein manueller Abnahmeschritt. Ein separater automatischer
Import historischer Intelligent-Dispatch-Slots und ein ZIP-Download
sind nicht Bestandteil dieser Version.
