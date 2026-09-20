# Implementierungsplan: Tarifabhaengige Abfragen und Polling

Ziel ist eine ressourcenschonende, tarifabhaengige Home-Assistant-Integration fuer `octopus_germany`. Die bestehende Funktionalitaet und alte Entity-Namen sollen erhalten bleiben, sofern keine bewusste Migration vereinbart wird.

## GitHub-Issue-Status

- [x] #92: `accountNumber` beim Einreichen von Zaehlerstaenden an Mutation und Service durchreichen.
- [x] #94: Kein kuenstliches `TEST_PRODUCT` mehr erzeugen.
- [x] #95: Polling-Defaults, konfigurierbare Intervalle und reduzierte Smart-Meter-Abfragen umsetzen.
- [x] #96: Terminale Account-Status filtern und aktiven Strom-Account bevorzugen.
- [x] #97: Smart-Meter-Serverfehler von leeren Ergebnissen unterscheiden und drei Stunden Backoff verwenden.
- [x] #104: Time-of-Use-Zeitfenster in der konfigurierten Home-Assistant-Zeitzone auswerten; Forecast-Zeitstempel bleiben absolute Instants.
- [x] #105: JWT-Epochenzeit korrekt vergleichen und automatischen Token-Refresh nach transienten Fehlern weiterlaufen lassen.
- [x] #106: Smart-Charging-Sessions aus aktuellen Coordinator-Daten lesen, nicht aus einem Ladezeit-Snapshot oder Attribut-Cache.
- [x] #107: Produktgueltigkeit als geparste, timezone-aware Zeitpunkte vergleichen, nicht als ISO-Strings.
- [ ] PR #90: Upstream-Pull-Request bleibt offen, bis der lokale Stand als Commit/PR veroeffentlicht und dort geprueft wurde.

## Leitlinien

- Bestehende Entity- und Sensor-Namen kompatibel halten.
- Nur API-Endpunkte abfragen, die fuer den Account bzw. Tarif verfuegbar sind.
- Keine Intelligent-Octopus-Abfragen fuer Standard-Tarife.
- Polling ueber den Config Flow konfigurierbar machen.
- Sensoren nur anlegen, wenn die zugehoerigen Daten verfuegbar sind.
- Fuer Architektur und Refresh-Verhalten die Integration von BottlecapDave als Referenz pruefen.
- Mutationen oder manuelle Aktionen nach Moeglichkeit mit einem gezielten Refresh bestaetigen.
- Keine echten Account-Daten, Tokens oder persoenliche Logs in Tests und Dokumentation verwenden.
- Zeitpunkte nie als Strings vergleichen. API-Zeitstempel werden zentral geparst, auf UTC normalisiert und erst danach verglichen.
- API-Wandzeit und lokale Tarifzeit strikt unterscheiden: Forecast-/Dispatch-Zeitstempel sind absolute Instants; `activeFromTime`/`activeToTime` von Time-of-Use-Regeln sind lokale Wandzeit.
- Epoch-Werte nur mit timezone-sicherer UTC-Zeit erzeugen, z. B. `datetime.now(UTC).timestamp()`; kein `datetime.utcnow().timestamp()`.
- Hintergrundaufgaben muessen transiente Netzwerkfehler innerhalb der Schleife behandeln. Ein einzelner 502/Timeout darf keinen dauerhaften Task-Tod verursachen.
- Entities duerfen keine unveraenderlichen API-Snapshots oder dauerhaft gecachten Attribute als Datenquelle verwenden. Dynamische Werte kommen aus dem Coordinator.
- Jede Aenderung an API-, Zeit-, Cache- oder Coordinator-Logik braucht einen Unit-Test und einen echten Home-Assistant-Startup-Test.

## Zielarchitektur bei einem Neustart

Die Integration soll schrittweise neu geordnet werden, ohne die bestehende Funktionalitaet sofort zu verwerfen. Die Architektur orientiert sich bei Coordinator-, Refresh- und Testmustern an BottlecapDaves Integration, uebernimmt aber weder deren britische API-Queries noch deren Entity-Namen ungeprueft.

```text
custom_components/octopus_germany/
├── api.py              # HTTP- und GraphQL-Kommunikation
├── queries.py          # getrennte GraphQL-Queries
├── models.py           # typisierte API-Daten
├── tariff.py           # Tarif- und Feature-Erkennung
├── coordinator.py      # Datenabruf und Polling
├── sensor.py           # ausschliesslich Sensor-Entities
├── config_flow.py      # Zugangsdaten und Polling-Konfiguration
└── __init__.py         # Setup und optionale Services
```

- [x] API-Kommunikation, Datenmodelle, Tariflogik, Coordinator und Entities voneinander trennen.
- [x] Architektur wie im Referenzprojekt [octopus_energy_de](https://github.com/thecem/octopus_energy_de) in fachliche Module zerlegen; Queries und API-Transport duerfen nicht in Entity-Dateien liegen.
- [x] `octopus_germany.py` schrittweise in `api/auth.py`, `api/queries.py` und fachliche API-Methoden aufteilen; das Modul soll keine Entity- oder Normalisierungslogik enthalten.
- [x] `__init__.py` auf Config-Entry-Lifecycle, Coordinator-Erzeugung und Service-Registrierung begrenzen; Datenverarbeitung in eigene Module verschieben.
- [x] `sensor.py`, `binary_sensor.py` und `switch.py` auf Entity-Lifecycle und Darstellung begrenzen; keine GraphQL-Abfragen, Produktselektion oder komplexe Normalisierung dort implementieren.
- [x] Gemeinsame Zeit-, Produkt- und Tarifregeln in `tariff.py`/`time_utils.py` zentralisieren; keine parallelen privaten Implementierungen in Entity-Klassen.
- [x] Pro Modul eine klare Eingabe-/Ausgabegrenze definieren und zyklische Abhängigkeiten vermeiden. Entity-Module duerfen nur Modelle, Coordinator-Daten und kleine Formatter importieren.
- [x] Zielgroessen festlegen: kein neues fachliches Verhalten in Dateien ueber 1.000 Zeilen; `octopus_germany.py`, `__init__.py` und `sensor.py` in jeweils testbare Teilmodule unter 500-800 Zeilen zerlegen.
- [x] Einen kleinen Initial-Query fuer Account, Agreements und Tarifmerkmale definieren.
- [x] Aus den Tarifdaten explizite Faehigkeiten ableiten, z. B. `has_dynamic_prices`, `has_intelligent_dispatches` und `has_smart_meter`.
- [x] Tarif-Faehigkeiten aus echten API-Daten bestimmen und nicht pauschal annehmen.
- [x] Basis-, Preis-, Verbrauchs- und Intelligent-Queries getrennt halten.
- [x] Intelligent-Felder nur abfragen, wenn die entsprechende Faehigkeit erkannt wurde.
- [ ] Zunaechst einen Coordinator mit getrennten Datenmethoden implementieren; mehrere Coordinators erst bei nachgewiesen unterschiedlichen Intervallen einfuehren.
- [ ] Als erste Zielversion nur schreibgeschuetzte Sensoren betreiben; Schalter und Nummern-Entities nicht voraussetzen.
- [x] Bestehende `unique_id`-Werte als Kompatibilitaetsvertrag behandeln.
- [x] Fuer neue geraetebezogene IDs die stabile OEG-`device.id` verwenden; bestehende Anzeigenamen-IDs bleiben ohne destruktive Migration erhalten.

### Architektur-Abnahmekriterien

- [ ] Ein API-Fehler kann ohne Home-Assistant-Entity-Test reproduziert werden, indem nur eine API-Methode mit einer anonymisierten Antwort getestet wird.
- [ ] Eine Tarifregel kann ohne Sensorinstanz getestet werden: Produktzeitpunkt, lokale Time-of-Use-Zeit und Forecast-Zeit werden jeweils mit festen Testzeiten geprueft.
- [ ] Ein Coordinator-Update aendert den Entity-Wert ohne Entity-Neuerzeugung oder Integration-Reload.
- [ ] Ein einmaliger Auth-/API-Fehler beendet keinen Hintergrundtask dauerhaft; der Test weist mindestens einen Folgeversuch nach.
- [ ] Ein Home-Assistant-Startup mit dem vorhandenen Task `Start Home Assistant (port 8123)` endet ohne Fehler aus `custom_components.octopus_germany` und liefert HTTP 200.
- [ ] Vor jedem Release werden Unit-Tests, Syntaxpruefung, `git diff --check` und ein echter HA-Startup ausgefuehrt; Logs werden auf `NameError`, Entity-Setup-Fehler, Listener-Fehler und unerwartete Produkt-/Tarifwarnungen geprueft.

## Phase 0: Bestand und offene Issues

- [x] Offene Issues und Pull Requests im Repository erfassen und nach Prioritaet sortieren.
- [x] Aktuelle GraphQL-Queries, API-Aufrufe und Datenmodelle dokumentieren.
- [x] Das aktuelle OEG-Schema fuer `AccountType`, `MaLo`, `Meter`, `SmartFlexDeviceInterface` und Dispatch-Typen direkt am Endpoint verifizieren.
- [x] Die aktiven Sammel-, Capability-, Smart-Meter- und Property-Schema-Queries live ohne Schemafehler validieren.
- [x] Bestehende Coordinators und Update-Intervalle identifizieren.
- [x] Alle aktuell erzeugten Entities mit Entity-ID, Name, Einheit und Datenquelle erfassen.
- [x] Verifizieren, welche bestehenden Sensor-Namen erhalten bleiben; BottlecapDave nur als Architektur-Referenz verwenden.
- [x] Bestaetigen, dass Account-/Tarif-IDs stabil sind und geraetebezogene IDs aktuell vom Anzeigenamen abhaengen.
- [x] Festlegen, dass bestehende Entity-IDs und Schalter aus Kompatibilitaetsgruenden nicht destruktiv migriert oder entfernt werden.

## Phase 1: Tarif-Erkennung

- [x] Einen kleinen Initial-Query fuer Account, Produkt und Tarifdaten bestimmen.
- [x] Erkennen, ob Intelligent Octopus bzw. die fuer Dispatches erforderlichen Produktdaten vorhanden sind.
- [x] Tarifstatus in einem zentralen Runtime-Datenobjekt des Config Entries ablegen.
- [x] Bei fehlenden oder unvollstaendigen Tarifdaten konservativ alle optionalen Intelligent-Faehigkeiten deaktivieren.
- [x] Tests fuer Standard-Tarif, Intelligent-Tarif und API-Fehler ergaenzen.

## Phase 2: API und dynamische Queries

- [x] API-Client in eine zentrale Request-Methode und fachliche Query-Methoden aufteilen.
- [x] Die bisherige grosse Sammelabfrage in fachliche Query-Bausteine zerlegen.
- [x] Query-Konstanten aus `octopus_germany.py` nach `queries.py` verschieben; jede Query bekommt einen anonymisierten Antwort-Fixture-Test.
- [x] Login/Token-Management von GraphQL-Abfragen trennen; Token-Refresh-Retry und Backoff als eigene testbare Komponente behandeln.
- [x] Produkt-/Tarif-Normalisierung vollstaendig aus `process_api_data` auslagern.
- [ ] Strom-/Gas-Produktselektion und `is_product_current()` in eine gemeinsame Tarif-/Produktlogik verschieben; vier duplizierte Sensor-/Setup-Pfade entfernen.
- [ ] Zeitkontrakte dokumentieren und testen: `validFrom`/`validTo` und Forecasts als Instant, TOU-Aktivierungsregeln als lokale Wandzeit.
- [x] Direkte Produktdaten in eine testbare Normalisierungsfunktion auslagern.
- [x] Gemeinsame Gross-Rate- und Time-of-Use-Slot-Normalisierung fuer Strom und Gas einfuehren.
- [x] Alle von OE gelieferten vergangenen, aktuellen und zukuenftigen Agreements mit Status, Laufzeit sowie verfuegbaren Brutto-, Netto- und MwSt.-Preisstufen im Strompreis-Sensor bereitstellen.
- [x] Gross-Rate-Fallbacks in Simple-Agreement-Produkten zentralisieren.
- [x] Optionale Forecast-Listen normalisieren und ungueltige Eintraege herausfiltern.
- [x] Simple-/Time-of-Use-Produkt-Typ-Erkennung fuer Strom und Gas zentralisieren.
- [x] Preisberechnung fuer Simple-, Time-of-Use- und Forecast-Raten in `tariff.py` auslagern.
- [x] UK-Rates-Card-Formatierung fuer Forecast-Raten in `tariff.py` auslagern.
- [x] Zeitfensterlogik des Preis-Sensors auf die zentrale Tariflogik umstellen.
- [x] Basis-Query ohne Intelligent-Felder implementieren.
- [x] Intelligent-Query mit Dispatch-/Fahrzeugdaten nur bei erkanntem Intelligent-Tarif implementieren.
- [x] Einen getrennten API-Pfad fuer Intelligent-Daten vorbereiten und fuer Standard-Tarife ueberspringen.
- [x] Eine Merge-Schicht fuer getrennte Basis- und Intelligent-GraphQL-Antworten implementieren.
- [x] Einen stabilen Merge-Vertrag fuer normalisierte Basis- und Intelligent-Account-Daten definieren.
- [x] Sicherstellen, dass unzulaessige GraphQL-Felder niemals fuer Standard-Tarife angefordert werden.
- [x] Alle aktiv verwendeten GraphQL-Queries gegen das aktuelle OEG-Schema live validieren.
- [ ] GraphQL-Fehler strukturiert behandeln und ohne sensible Variablen loggen.
- [x] Runtime-Start mit einem eingerichteten Home-Assistant-Konto prüfen und Fehler nach der Meter-Normalisierung beheben.
- [x] Nach dem Fix verifizieren, dass Account-Daten verarbeitet und Sensoren angelegt werden.
- [x] Live-Regression bei Time-of-Use-Produkten nach Formatierungsänderungen beheben.
- [x] Debug-Schemaexploration und Multi-Date-Abfragen aus dem normalen Startpfad entfernen bzw. standardmaessig deaktivieren.
- [x] Smart-Meter-Abfrage im normalen Polling auf eine einzelne Vortagsabfrage reduzieren.
- [x] Smart-Meter-Abfrage an `has_smart_meter`-Capability koppeln.
- [x] Smart-Meter-Abfrage im Intelligent-Coordinator nicht doppelt ausführen.
- [x] Query- und Antworttests mit anonymisierten Fixtures erstellen.

## Phase 3: Coordinators und Polling

- [x] Zuerst einen Coordinator mit getrennten Abrufmethoden fuer Tarife/Preise, Verbrauch und Intelligent-Daten umsetzen.
- [x] Multi-Account-Basisabruf aus dem Coordinator-Closure in eine testbare Funktion auslagern.
- [x] Nur bei echtem Bedarf mehrere Coordinators fuer unabhaengige Intervalle einfuehren.
- [x] Einen optionalen Intelligent-Coordinator nur fuer erkannte Intelligent-Tarife einrichten.
- [x] Sinnvolle Standardintervalle festlegen: Basisdaten 30 Minuten und Intelligent-Status 3 Minuten.
- [x] Polling-Intervalle ueber den Config Flow konfigurierbar machen.
- [x] Eingaben validieren und minimale sowie maximale Intervalle festlegen, um versehentliche API-Last zu vermeiden.
- [x] Intelligent-Polling-Intervall separat im Config Flow konfigurierbar machen.
- [x] Nach Tarif-Erkennung nur die benoetigten Coordinators starten.
- [x] Bei nicht verfuegbarem Intelligent-Tarif keine Dispatch-, Fahrzeug- oder Intelligent-Schalter-Entities erzeugen.
- [x] Verhalten bei Tarifwechsel oder erneuter Einrichtung festlegen: Capability-Cache wird bei einem erneuten Config-Entry-Setup neu aufgebaut.
- [x] Coordinator-Datenvertrag als typisierte Struktur statt losem verschachteltem Dictionary definieren oder schrittweise mit TypedDicts absichern.
- [x] Session-, Dispatch- und Geraete-Entities ausschliesslich aus dem aktuellen Coordinator-Datenvertrag lesen; keine Initial-Snapshots als dauerhafte Quelle zulassen.
- [ ] Automatische Refresh-Tasks mit kontrollierter Cancellation, Retry und sichtbarem Fehlerstatus versehen.

## Phase 4: On-Demand-Refresh und Services

- [x] Pruefen, welche Sensoren fuer einen manuellen Refresh geeignet sind, insbesondere Dispatch-Daten.
- [x] Einen gezielten Refresh-Service nur einfuehren, wenn der bestehende Home-Assistant-Serviceumfang dies nicht bereits abdeckt.
- [x] Refresh-Service in ein eigenes Service-Modul mit testbarem Coordinator-Filter auslagern.
- [x] Service-Schema, Zielbereiche und Fehlerverhalten definieren.
- [x] Nach einer erfolgreichen Mutation, z. B. Ladepraeferenz-Aktion, den betroffenen Coordinator gezielt aktualisieren.
- [x] Rate-Limit- und Parallel-Refresh-Schutz durch Coordinator-Refresh-Koaleszierung sicherstellen.
- [x] Service-Dokumentation und Uebersetzungen aktualisieren.

## Phase 5: Entities und Namenskompatibilitaet

- [x] Die bestehende Schalterfunktion aus Kompatibilitaetsgruenden beibehalten; neue Funktionen bleiben sensor-/capability-geprueft.
- [x] Bestehende Sensoren fuer SoC und Battery Size beibehalten.
- [x] Entfernte Sensoren SoC Change und SoC Limit nicht wieder einfuehren, sofern nicht explizit erforderlich.
- [x] Alte Entity-Namen mit den aktuell geplanten Namen abgleichen.
- [x] Falls eine Umbenennung notwendig ist: Migration planen und bis dahin bestehende IDs unveraendert lassen.
- [x] Nur tariflich und technisch verfuegbare Sensoren, Schalter oder Nummern-Entities erstellen.
- [x] Nur tariflich und technisch verfuegbare Sensoren erstellen.
- [x] Entity-Tests fuer Verfuegbarkeit und Disabled-by-default-Verhalten ergaenzen.
- [x] Geraete- und Charging-Session-Entity-Erzeugung in eine testbare Fabrik auslagern.
- [x] Intelligent-Binary-Sensor-Erzeugung in eine testbare, capability-gepruefte Fabrik auslagern.
- [x] Smart-Control- und Boost-Switch-Geräteauswahl zentral auf Intelligent-Capability begrenzen.

## Phase 6: Config Flow, Dokumentation und Release

- [x] Neue Polling-Optionen in `config_flow.py`, `strings.json` und allen Uebersetzungen ergaenzen.
- [x] Defaults und bestehende Config Entries rueckwaertskompatibel behandeln.
- [x] README-Dateien im Repository und in der Integration synchron aktualisieren.
- [x] README-Dateien im Repository und in der Integration synchron aktualisieren.
- [x] Release Notes und Manifest-Version nur zusammen mit einer tatsaechlichen Funktionaenderung aktualisieren.
- [x] Changelog-Eintrag fuer neue Services und Polling-Optionen verfassen.
- [x] Offene GitHub-Issues #92, #94, #95, #96 und #97 gegen den lokalen Stand pruefen und die behobenen Punkte dokumentieren.
- [x] Offene GitHub-Issues #104 bis #107 analysieren; die daraus entstandenen Zeit-, Token-, Entity- und Produktvalidierungsregeln oben dokumentieren.

## Phase 7: Messwert-Pagination und variable Netzentgelte nach Paragraph 14a EnWG

### Messwertabfrage und CSV-Export

- [x] Die direkte `property(id: $propertyId) { measurements(...) }`-Abfrage mit anonymisierten Live-Daten gegen den deutschen Endpoint validieren.
- [x] `marketSupplyPointId` aus dem vorhandenen `malo_number` beziehen und niemals Account-, Property-, MaLo- oder Zaehlerkennungen fest einbauen.
- [x] Die Aufloesung zentral auf die API-Frequenzen abbilden: `15min` auf `RAW_INTERVAL`, `hour` auf `HOUR_INTERVAL` und eine spaetere Tagesansicht auf `DAY_INTERVAL`.
- [x] Lokale Periodengrenzen aus der Home-Assistant-Zeitzone in timezone-aware `startAt`/`endAt`-Werte umrechnen; Sommerzeitwechsel explizit testen.
- [x] Pagination ueber `first`, `after`, `pageInfo.hasNextPage` und `pageInfo.endCursor` implementieren.
- [ ] Das vom Endpoint akzeptierte maximale `first`-Limit ermitteln; Seiten gedrosselt laden und `KT-CT-1199` mit Backoff statt als leeres Ergebnis behandeln.
- [x] Den beobachteten Tagesvertrag absichern: Ein normaler Tag liefert mit `RAW_INTERVAL` und `first: 100` genau 96 Intervalle zu je 900 Sekunden ohne Folgeseite.
- [ ] Messwerte als `Decimal` normalisieren, damit sowohl normale Dezimalstrings als auch wissenschaftliche Schreibweise wie `0E-18` ohne Genauigkeitsverlust verarbeitet werden.
- [ ] `durationInSeconds`, `readingDirection` und die zurueckgelieferte `marketSupplyPointId` validieren; fremde Zaehlerpunkte oder unerwartete Intervalllaengen nicht unbemerkt summieren.
- [x] Fuer jede Messung auch `source`, `__typename`, `readingQuality`, `readingFrequencyType`, `deviceId` und `registerId` abfragen, damit echte, kombinierte und geschaetzte Daten sowie die Zuordnung zum Zaehler unterscheidbar werden.
- [ ] Bei einem Zaehlerwechsel Messwerte vor und nach dem Wechseltermin getrennt pruefen: Wechsel von `deviceId`/`registerId`, fehlende Intervalle, Nullserien und Aenderungen von `source` oder `readingQuality` sichtbar machen.
- [ ] Wiederkehrende Ersatzprofile erkennen und als Diagnose kennzeichnen. Nahezu identische Tageswerte im Sieben-Tage-Rhythmus duerfen nicht ungeprueft als reale Smart-Meter-Messung gelten.
- [ ] Den Fehler `OE-DEU-0605` separat behandeln: Ein fehlender kundenseitig eingereichter Zaehlerstand ist nicht gleichbedeutend mit fehlenden Intervallmessungen, kann nach einem Zaehlerwechsel aber auf einen fehlenden Anfangsstand des neuen Zaehlers hinweisen.
- [x] Monatsexporte ueber die Bereichsabfrage laden und Ergebnisse anhand des lokalen `startAt` wieder nach Kalendertag gruppieren.
- [x] Jahresexporte monatsweise ausfuehren, damit Speicherbedarf, Fehlerwiederholung und Fortschritt kontrollierbar bleiben.
- [ ] Tests fuer leere Ergebnisse, mehrere Seiten, fehlenden Cursor, Rate-Limit, partielle Monate und DST-Tage mit 92 bzw. 100 Viertelstundenwerten ergaenzen.
- [ ] Die Summe der 15-Minuten-Intervalle gegen den entsprechenden `DAY_INTERVAL`-Wert testen; Abweichungen sichtbar melden statt still zu runden.
- [ ] Fuer den beobachteten Normalfall festhalten: 96 Viertelstundenwerte zu je 900 Sekunden summieren sich auf denselben Tageswert; diese interne Konsistenz beweist jedoch nicht, dass die Quelle ein physischer Zaehler und keine Schaetzung ist.

### Paragraph-14a-Datenvertrag

- [ ] Die Semantik von `variableGridFees.module` beim Octopus-Endpoint verifizieren: `MODULE_1` darf erst nach Bestaetigung als tatsaechlich gewaehltes Abrechnungsmodul angezeigt werden.
- [ ] Verifizieren, ob `gridFees` die fuer Modul 3 angebotenen Zeitfenster unabhaengig vom aktuell gewaehlten Modul liefert oder eine aktive Kombination aus Modul 1 und Modul 3 bestaetigt.
- [x] Die Quelle fuer `gridOperatorCode` aus Account-, MaLo- oder Vertragsdaten bestimmen; keine Konfigurations- oder Code-Konstante mit kundenspezifischem Wert verwenden.
- [x] Den lokalen GraphQL-Schema-Snapshot um `variableGridFees` und die zugehoerigen Typen aktualisieren oder die Abfrage als explizit optionalen, live validierten API-Pfad dokumentieren.
- [x] Eine getrennte API-Methode fuer `variableGridFees(accountNumber, gridOperatorCode, date)` implementieren und GraphQL-Fehler ohne sensible Variablen behandeln.
- [x] Ein typisiertes Modell fuer Modul, Tariftyp, Intervallbeginn/-ende, Gueltigkeit, Netzbetreiber und Cent-pro-kWh-Wert einfuehren.
- [ ] Ueberlappende, lueckenhafte oder ungueltige Zeitfenster ablehnen; das Intervall `23:00:00` bis `00:00:00` wird bereits korrekt ueber Mitternacht ausgewertet.
- [x] Die selten veraenderten API-Daten beim Start und danach hoechstens taeglich abrufen; aktuelle Tarifstufe und naechsten Wechsel lokal aus dem gecachten Zeitplan berechnen.
- [x] Sensoren nur anlegen, wenn der Endpoint fuer den Account Daten liefert; fehlende Unterstuetzung darf den Basis-Coordinator nicht fehlschlagen lassen.

### Vorgesehene Home-Assistant-Sensoren

- [x] Diagnose-Sensor `sensor.octopus_<account>_14a_module` mit stabilem `unique_id` `octopus_<account>_14a_module` vorsehen. Zustand ist der verifizierte API-Wert, zum Beispiel `module_1`; bei ungeklaerter Semantik neutral als von Octopus gemeldetes Modul bezeichnen.
- [x] Preis-Sensor `sensor.octopus_<account>_variable_grid_fee` mit stabilem `unique_id` `octopus_<account>_variable_grid_fee` vorsehen. Zustand ist ausschliesslich der aktuell aktive Netzentgeltanteil in `EUR/kWh`, nicht der gesamte Strompreis.
- [x] Am Preis-Sensor die Attribute `rate_type`, `interval_start`, `interval_end`, `next_change`, `valid_from`, `valid_to`, `grid_operator_code` und den normalisierten Tagesplan bereitstellen.
- [x] Cent pro kWh ohne vorzeitiges Runden in Euro pro kWh umrechnen; der Preis-Sensor verwendet `SensorDeviceClass.MONETARY` ohne die von Home Assistant dafuer abgelehnte `SensorStateClass.MEASUREMENT`.
- [x] Keine separaten Entities fuer jedes statische Zeitfenster erzeugen. `OFFPEAK`, `STANDARD` und `PEAK` bleiben Tarifstufen im Zeitplan; nur der aktuell wirksame Wert ist Sensorzustand.
- [x] Zustandswechsel an Intervallgrenzen lokal ausloesen, ohne dafuer eine neue GraphQL-Abfrage zu senden; nach Coordinator-Refresh den naechsten Wechsel neu planen.
- [ ] Tests fuer alle Tarifstufen, exakte Intervallgrenzen, Mitternacht, Gueltigkeitswechsel, nicht unterstuetzte Accounts und die Unterscheidung zwischen Netzentgelt und Gesamtstrompreis ergaenzen.
- [x] Beide README-Dateien, Entity-Kompatibilitaet und Release Notes zusammen mit der Implementierung aktualisieren; die Entity-Namen sind derzeit direkt im Python-Code definiert und benoetigen keine neuen Uebersetzungsschluessel.

## Phase 8: Saldo- und Buchungshistorie

### API und Datenmodell

- [ ] Eine getrennte `BalanceHistory`-Query in `api/queries.py` aufnehmen; die bestehende Basisabfrage behaelt nur `ledgerType` und `balance` und wird nicht bei jedem Coordinator-Lauf um Transaktionen vergroessert.
- [ ] Eine On-Demand-API-Methode mit `account_number`, optionalem Cursor und begrenzter Seitengroesse implementieren.
- [ ] Pagination fuer jedes zurueckgegebene Ledger getrennt modellieren und live pruefen, ob ein Cursor verbindungsspezifisch ist; einen Cursor nicht ungeprueft auf mehrere Ledger-Verbindungen anwenden.
- [ ] Ledger-Betraege aus der kleinsten Waehrungseinheit in Euro normalisieren: `balance`, `balanceCarriedForward`, `gross`, `net` und `tax` werden durch 100 geteilt.
- [ ] Transaktionen typisieren mit `id`, `transaction_type`, `posted_date`, `title`, `is_reversed`, `gross`, `net`, `tax` und `balance_carried_forward`.
- [ ] Vorzeichen nicht allein aus dem positiven API-Betrag ableiten. Die Wirkung von `Credit`, `Charge`, `Refund` und weiteren `__typename`-Werten mit anonymisierten Saldoverlaeufen testen.
- [ ] Stornierte Buchungen nicht still entfernen; `is_reversed` erhalten und eine optionale Filterung erst in der Service-Antwort anwenden.
- [ ] GraphQL- und Pagination-Fehler ohne Accountnummern, Transaktions-IDs oder Buchungstitel protokollieren.

### Home-Assistant-Schnittstelle

- [ ] Den vorhandenen Balance-Sensor als primaere Entity beibehalten; sein Zustand bleibt der aktuelle Ledger-Saldo in Euro.
- [ ] Einen antwortfaehigen Service `get_balance_history` mit `account_number`, optionalem `ledger_type`, `cursor` und `limit` vorsehen. Die Antwort enthaelt normalisierte Buchungen sowie `has_next_page` und `end_cursor`.
- [ ] Den Service-Response nach Herkunft gliedern: `source` enthaelt unveraenderte API-Felder, `amounts_minor_units` die gelieferten Ganzzahlbetraege, `amounts_eur` die durch 100 normalisierten Werte und `calculated` ausschliesslich fachlich abgeleitete Werte.
- [ ] Pro Ledger mindestens `ledger_type`, `balance_minor_units`, `balance_eur`, `transactions` und `page_info` ausgeben.
- [ ] Pro Transaktion die direkt verfuegbaren Felder `id`, `transaction_type`, `posted_date`, `title` und `is_reversed` sowie `gross`, `net`, `tax` und `balance_carried_forward` jeweils in Minor Units und Euro ausgeben.
- [ ] Abgeleitete Felder wie `direction` und `signed_gross_eur` nur nach verifizierter Typsemantik bereitstellen und unter `calculated` kennzeichnen; `Credit`, `Charge` und `Refund` nicht allein anhand ihres Namens interpretieren.
- [ ] Im Service-Response `currency: EUR`, `minor_unit_factor: 100` und eine kurze `field_semantics`-Zuordnung mitliefern, damit Automationen Rohwerte, normalisierte Werte und Berechnungen unterscheiden koennen.
- [ ] Bei gesetztem `ledger_type` nur dieses Ledger zurueckgeben; ohne Filter alle verfuegbaren Ledger getrennt und mit jeweils eigener Pagination ausgeben.
- [ ] Die vollstaendige Buchungshistorie nicht als Sensorattribut speichern, da Home Assistant Attribute in der Recorder-Datenbank vervielfacht und Buchungstitel sensible Informationen enthalten koennen.
- [ ] Zunaechst keinen zusaetzlichen Transaktionssensor anlegen. Einen standardmaessig deaktivierten Sensor fuer die letzte Buchung erst bei einem konkreten Automationsbedarf evaluieren; Freitexttitel nur nach ausdruecklicher Datenschutzentscheidung aufnehmen.
- [ ] Keine einzelne Entity pro Transaktion erzeugen.
- [ ] Service-Schema, eine Tabelle aller API- und berechneten Felder, anonymisierte Antwortbeispiele und einen Datenschutz-Hinweis in beiden README-Dateien sowie der Service-Dokumentation ergaenzen.

### Tests und Freigabe

- [ ] Anonymisierte Fixtures fuer `Credit`, `Charge`, `Refund`, stornierte Buchungen, mehrere Ledger und mehrere Seiten erstellen.
- [ ] Cent-/Euro-Konvertierung, Sortierreihenfolge, Cursor-Fortsetzung und unveraenderte Balance-Sensoren testen.
- [ ] Sicherstellen, dass ein Fehler der History-Abfrage weder den Basis-Coordinator noch bestehende Balance-Sensoren als nicht verfuegbar markiert.
- [ ] Die Manifest-Version und Release Notes erst mit der tatsaechlichen Implementierung aktualisieren.

## Verifikation pro Umsetzungsschritt

- [ ] Ruff/Lint vollstaendig bereinigen; verbleibend sind 106 Produktionsmeldungen, vor allem E501, Exception-/Komplexitaets- und Legacy-Service-Regeln.
- [x] Ruff fuer die neuen Daten-, Coordinator-, Modell- und Service-Module ausfuehren.
- [x] Alle verbliebenen Python-3-Exception-Klauseln syntaktisch korrigieren.
- [x] Betroffene Python-Dateien syntaktisch pruefen.
- [x] API-Tests mit Standard- und Intelligent-Fixtures ausfuehren.
- [x] Config-Flow-Tests fuer Defaults und benutzerdefinierte Intervalle ausfuehren.
- [x] Migration alter Config Entries ohne Polling-Werte explizit testen.
- [x] Intervall-Normalisierung fuer Defaults, Grenzen und String-Eingaben zentral testen.
- [x] Home Assistant mit Standard-Tarif-Fixtures auf unerlaubte Intelligent-Queries pruefen.
- [x] Home Assistant mit dem eingerichteten Intelligent-/Time-of-Use-Account starten und Dispatch-/Entity-Erzeugung pruefen.
- [x] Entity-Namen und Entity-IDs gegen [ENTITY_COMPATIBILITY.md](ENTITY_COMPATIBILITY.md) pruefen.
- [ ] Den vorhandenen Home-Assistant-Task vor Abschluss jeder API-/Coordinator-Aenderung ausfuehren und den Integration-Log gezielt auf neue Fehler pruefen.
- [ ] Fuer jeden Bugfix mindestens einen Test gegen den vorherigen Fehlermechanismus schreiben, nicht nur gegen das erwartete Endergebnis.

## Offene Entscheidungen

- [x] Tarif-Erkennung auf Agreements/Produktdaten sowie vorhandene Smart-Meter-/SmartFlex-Faehigkeiten stuetzen.
- [x] Polling-Intervalle fuer Basis- und Intelligent-Daten getrennt konfigurierbar machen.
- [x] Einen eigenen Intelligent-Refresh-Service und Coordinator-Refresh nach Mutationen verwenden.
- [x] Account-/Meter-Sensoren auch ohne Fahrzeug- oder Verbrauchsdaten verfuegbar lassen.
- [x] Die stabile OEG-`device.id` ist die Ziel-ID fuer neue geraetebezogene Entities; eine Rueckmigration bestehender IDs ist bewusst nicht aktiviert.
- [x] BottlecapDave-Muster nur fuer getrennte Coordinator-, Refresh- und Testkonzepte uebernehmen, ohne deutsche API-/Entity-Vertraege zu brechen.
