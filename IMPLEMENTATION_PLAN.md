# Implementierungsplan: Tarifabhaengige Abfragen und Polling

Ziel ist eine ressourcenschonende, tarifabhaengige Home-Assistant-Integration fuer `octopus_germany`. Die bestehende Funktionalitaet und alte Entity-Namen sollen erhalten bleiben, sofern keine bewusste Migration vereinbart wird.

## GitHub-Issue-Status

- [x] #92: `accountNumber` beim Einreichen von Zaehlerstaenden an Mutation und Service durchreichen.
- [x] #94: Kein kuenstliches `TEST_PRODUCT` mehr erzeugen.
- [x] #95: Polling-Defaults, konfigurierbare Intervalle und reduzierte Smart-Meter-Abfragen umsetzen.
- [x] #96: Terminale Account-Status filtern und aktiven Strom-Account bevorzugen.
- [x] #97: Smart-Meter-Serverfehler von leeren Ergebnissen unterscheiden und drei Stunden Backoff verwenden.
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

- [ ] API-Kommunikation, Datenmodelle, Tariflogik, Coordinator und Entities voneinander trennen.
- [x] Einen kleinen Initial-Query fuer Account, Agreements und Tarifmerkmale definieren.
- [x] Aus den Tarifdaten explizite Faehigkeiten ableiten, z. B. `has_dynamic_prices`, `has_intelligent_dispatches` und `has_smart_meter`.
- [x] Tarif-Faehigkeiten aus echten API-Daten bestimmen und nicht pauschal annehmen.
- [x] Basis-, Preis-, Verbrauchs- und Intelligent-Queries getrennt halten.
- [x] Intelligent-Felder nur abfragen, wenn die entsprechende Faehigkeit erkannt wurde.
- [ ] Zunaechst einen Coordinator mit getrennten Datenmethoden implementieren; mehrere Coordinators erst bei nachgewiesen unterschiedlichen Intervallen einfuehren.
- [ ] Als erste Zielversion nur schreibgeschuetzte Sensoren betreiben; Schalter und Nummern-Entities nicht voraussetzen.
- [x] Bestehende `unique_id`-Werte als Kompatibilitaetsvertrag behandeln.
- [x] Fuer neue geraetebezogene IDs die stabile OEG-`device.id` verwenden; bestehende Anzeigenamen-IDs bleiben ohne destruktive Migration erhalten.

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

- [ ] API-Client in eine zentrale Request-Methode und fachliche Query-Methoden aufteilen.
- [ ] Die bisherige grosse Sammelabfrage in fachliche Query-Bausteine zerlegen.
- [ ] Produkt-/Tarif-Normalisierung vollstaendig aus `process_api_data` auslagern.
- [x] Direkte Produktdaten in eine testbare Normalisierungsfunktion auslagern.
- [x] Gemeinsame Gross-Rate- und Time-of-Use-Slot-Normalisierung fuer Strom und Gas einfuehren.
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

## Verifikation pro Umsetzungsschritt

- [ ] Ruff/Lint vollstaendig bereinigen; der verbleibende Bestand betrifft historische Grossfunktionen.
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

## Offene Entscheidungen

- [x] Tarif-Erkennung auf Agreements/Produktdaten sowie vorhandene Smart-Meter-/SmartFlex-Faehigkeiten stuetzen.
- [x] Polling-Intervalle fuer Basis- und Intelligent-Daten getrennt konfigurierbar machen.
- [x] Einen eigenen Intelligent-Refresh-Service und Coordinator-Refresh nach Mutationen verwenden.
- [x] Account-/Meter-Sensoren auch ohne Fahrzeug- oder Verbrauchsdaten verfuegbar lassen.
- [x] Die stabile OEG-`device.id` ist die Ziel-ID fuer neue geraetebezogene Entities; eine Rueckmigration bestehender IDs ist bewusst nicht aktiviert.
- [x] BottlecapDave-Muster nur fuer getrennte Coordinator-, Refresh- und Testkonzepte uebernehmen, ohne deutsche API-/Entity-Vertraege zu brechen.
