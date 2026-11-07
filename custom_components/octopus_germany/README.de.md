# Octopus Germany Integration fuer Home Assistant

Sprache / Language: [Deutsch](README.de.md) | [English](README.md)

[![Marketplace](https://img.shields.io/badge/Home%20Assistant-Marketplace-41BDF5?logo=homeassistant&logoColor=white)](https://www.home-assistant.io/integrations/marketplace/)
[![Neueste Version](https://img.shields.io/github/v/release/thecem/octopus_germany?label=Version&color=41BDF5&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/releases/latest)
[![Home-Assistant-Mindestversion](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fthecem%2Foctopus_germany%2Fmain%2Fhacs.json&query=%24.homeassistant&label=Home%20Assistant%20%E2%89%A5&color=41BDF5&logo=homeassistant&logoColor=white)](../../hacs.json)
[![Lizenz](https://img.shields.io/github/license/thecem/octopus_germany?label=Lizenz&color=41BDF5)](../../LICENSE)

[![GitHub-Sterne](https://img.shields.io/github/stars/thecem/octopus_germany?label=Sterne&color=41BDF5&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/stargazers)
[![GitHub-Release-Downloads](https://img.shields.io/github/downloads/thecem/octopus_germany/total?label=Downloads%20seit%2011%2F2026&color=41BDF5&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/releases)
[![Aktive Home-Assistant-Installationen](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fanalytics.home-assistant.io%2Fcustom_integrations.json&query=%24.octopus_germany.total&label=aktive%20Installationen&color=41BDF5&logo=homeassistant&logoColor=white&cacheSeconds=21600)](https://analytics.home-assistant.io/custom_integrations)

Diese Dokumentation beschreibt die Entitaeten und die Bedienung innerhalb der Integration.

## Projekt unterstuetzen

Wenn dir die Integration hilft, kannst du ihre Weiterentwicklung ueber
GitHub Sponsors oder Ko-fi unterstuetzen:

[![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-Sponsor-ea4aaa?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/thecem)
[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/K3K71LPRM2)

GitHub Sponsors ist verfuegbar, sobald GitHub das persoenliche Sponsors-Profil
freigegeben hat. Bis dahin steht Ko-fi als Alternative bereit.

Voraussetzung ist Home Assistant **2026.11.0 oder neuer**. Entwicklung,
Regressionstests und das Setup des Entwicklungscontainers verwenden
Home Assistant **2026.11.0**. Markenbilder werden im Ordner `brand/` mitgeliefert.

**Zu den Zaehlern:** Downloads zaehlen GitHub-Release-Asset-Downloads aller
Versionen, einschliesslich erneuter Downloads und Updates. Die Zaehlung begann
mit den ZIP-Release-Assets im November 2026; fruehere Installationen fehlen.
Aktive Installationen stammen aus freiwilligen Home-Assistant-Analytics-Meldungen
und erfassen nicht alle Nutzer. Beide Zaehler messen unterschiedliche Dinge.

## Freund*innen werben

Wenn du über [meinen Empfehlungslink](https://octopusenergy.de/empfehlungen?referralCode=free-cat-744) zu Octopus Energy wechselst, erhältst du **150 €** als Rechnungsgutschrift. Es gelten die Teilnahmebedingungen von Octopus Energy.

## Installation und Konfiguration

Installation ueber **Einstellungen** > **Marketplace**: nach **Octopus Germany**
suchen und installieren. Falls nicht gelistet, **Vom Link hinzufuegen** mit
`https://github.com/thecem/octopus_germany` verwenden und GitHub bei Aufforderung
verbinden. Anschliessend Home Assistant neu starten.

Die Einrichtung erfolgt danach in Home Assistant ueber:

1. Einstellungen > Geraete und Dienste
2. Integration hinzufuegen
3. Octopus Germany auswaehlen
4. Login-Daten eingeben

### Umstieg von HACS

Home Assistant 2026.11 migriert HACS-Inhalte beim Start automatisch.
Installierte Integrationen, eigene Repositories und die Entity-IDs der
Update-Entitaeten bleiben erhalten; HACS selbst wird entfernt.
Octopus Germany nicht deinstallieren und Entitaeten nicht neu anlegen.
Bisherige HACS-Repository-Buttons oeffnen weiterhin den Marketplace.
`hacs.json` bleibt erforderlich, damit eigene Repositories Updates erhalten.

Eigene Templates mit `integration_entities('hacs')` auf
`integration_entities('marketplace')` umstellen. Hinweise zum notwendigen
Neustart stehen jetzt unter **Einstellungen** > **System** > **Reparaturen**,
nicht im Update-Attribut `release_summary`. YAML-Dashboard-Ressourcen auf
`/local/community/` statt `/hacsfiles/` umstellen; alte Pfade funktionieren weiter.
Siehe [HA-Migrationshinweise](https://www.home-assistant.io/integrations/marketplace/#coming-from-hacs).

Marketplace installiert das Release-Asset `octopus_germany.zip`. Die native
Downloadanzeige stammt von GitHub und zaehlt Downloads des ausgewaehlten
Release-Assets, nicht alle bisherigen Downloads oder die aktiven Installationen
im Badge oben.

Fehlt die Downloadanzeige trotz Downloads auf GitHub, im Drei-Punkte-Menue der
Marketplace-Repository-Seite **Informationen aktualisieren** auswaehlen.
Die ausgewaehlte Version muss ein Release mit `octopus_germany.zip` sein
(ab v0.0.202), nicht der Branch `main` oder ein aelteres Release ohne Asset.
Ein Wert von null wird ausgeblendet. GitHub-/Katalogdaten und Badges koennen
unterschiedlich lange zwischengespeichert sein; auf Hinweise zu GitHub-Limits
oder fehlgeschlagenen Aktualisierungen achten.

## Dokumentationsstruktur

- Entitaeten und Attribute: siehe [Entitaeten-Ueberblick](#entitaeten-ueberblick)
- [Aktionen und Dienste](../../docs/ACTIONS_AND_SERVICES.de.md)
- [Stromkostenbericht und Berechnungen](../../docs/COST_REPORT.de.md)
- [Beispieldatei fuer Netzbetreiber-Zeitplaene](../../docs/examples/grid_fee_schedules.example.json)

## Smart-Meter- und Kostenberichte

Smart-Meter-Jahresdateien werden ueber paginierte Monatsabfragen in der konfigurierten Home-Assistant-Zeitzone erstellt. Quelle und Messqualitaet werden als Metadaten zurueckgegeben; auch intern konsistente Intervalle koennen geschaetzt sein.

Kostenberichte verwenden Agreement-Preise und zeitgueltige API-Netzentgelte. Sie sind Schaetzungen, keine Lieferantenrechnung und keine Rechtsentscheidung. Dynamische Abrechnungen lassen sich ohne historische Ist-Intervallpreise nicht verlaesslich rekonstruieren; Prognosen sind keine historischen Preise. Formeln, Eingaben, unvollstaendige Daten und regulatorischer Kontext sind im [Leitfaden zum Stromkostenbericht](../../docs/COST_REPORT.de.md) beschrieben.

Fehlen API-Saetze, kann eine optionale Datei stunden- und gueltigkeitsbezogene Werte je Netzbetreiber enthalten. Die [Beispieldatei](../../docs/examples/grid_fee_schedules.example.json) zeigt das Format mit einzeln erhaltenen Stunden 0 bis 23.

CSV-Dateien werden unter `/config/octopus_germany/exports` gespeichert. Zu jedem Export erscheint eine persistente Home-Assistant-Benachrichtigung mit einem dateigebundenen Bearer-Token-Downloadlink. Gueltigkeit: standardmaessig 24 Stunden, in den Integration-Optionen auf 1 bis 168 Stunden einstellbar; die Einstellung gilt nur fuer neue Exporte.

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

## Entwicklung und Validierung

[![Hassfest](https://img.shields.io/github/actions/workflow/status/thecem/octopus_germany/hassfest.yaml?branch=main&label=Hassfest&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/actions/workflows/hassfest.yaml)
[![Katalogvalidierung](https://img.shields.io/github/actions/workflow/status/thecem/octopus_germany/hacs.yaml?branch=main&label=Katalogvalidierung&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/actions/workflows/hacs.yaml)
[![Offene Issues](https://img.shields.io/github/issues/thecem/octopus_germany?label=offene%20Issues&color=41BDF5&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/issues)
[![Letzter Commit](https://img.shields.io/github/last-commit/thecem/octopus_germany/main?label=letzter%20Commit&color=41BDF5&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/commits/main)

Validierungsbadges zeigen den Workflow-Status, keine Zertifizierung oder
Empfehlung durch Home Assistant.

## API-Unterstuetzung

Die Integration verwendet zwei GraphQL-Endpunkte:

| API | Endpunkt | Verwendung |
|---|---|---|
| OEG Kraken GraphQL | `https://api.oeg-kraken.energy/v1/graphql/` | Anmeldung, Konten, Vertraege, Preise, Smart-Meter-/Zaehlerdaten und Intelligent-/SmartFlex-Geraetesteuerung |
| OE Backend GraphQL | `https://api.backend.octopusenergy.de/v1/graphql/` | Variable Netzentgelte (`variableGridFees`), authentifiziert mit demselben Kraken-Token |

- [Kraken-GraphQL-Dokumentation](https://developer.oeg-kraken.energy/graphql/)
- [Octopus-Entwicklerdokumentation mit REST-Referenz](https://developer.oeg-kraken.energy/): Hintergrundinformation; die Integration ruft derzeit keine Octopus-REST-Endpunkte auf.
- Schema-Snapshots: [OEG Kraken](oeg_graphql_schema.yaml) und [OE Backend](oe_backend_graphql_schema.json).

`https://my.octopusenergy.de/` ist der Link zum Kundenportal in der
Geraeteoberflaeche, kein zusaetzlicher API-Endpunkt.

## Support

### DNS, API-Limits und Statistiken

- DNS-Timeouts bedeuten, dass der DNS-Server den API-Host nicht rechtzeitig
  aufloesen konnte, nicht dass das Passwort falsch ist. Bei Wiederholung
  DNS/Netzwerk pruefen; der Kontoabruf versucht es beim naechsten Update erneut.
- Eine zweite HA-Instanz und manuelle Exporte erhoehen die API-Last und koennen
  zu `KT-CT-1199` (zu viele Anfragen) beitragen. Der genaue Geltungsbereich des
  API-Limits ist nicht bekannt. Statistikabrufe laufen hoechstens alle 30 Minuten
  pro Integrationseintrag; SmartFlex bleibt unveraendert. Seiten-Retries und
  Wartezeiten nach API-Fehlern bleiben aktiv.
- `missing` zaehlt fehlende Viertelstunden, die spaeter eintreffen koennen.
  Das bedeutet nicht, dass Recorder Daten geloescht hat; der Cache bleibt erhalten.
- Recorder-Schreibbloecke werden vorab gespeichert und in kWh kontrolliert.
  Unbestaetigte Bloecke werden auch nach Neustarts mit ihren urspruenglichen Summen
  wiederholt. Abweichungen melden Zeitstempel, Feld sowie Soll-/Ist-Wert, ohne
  einen erfolgreichen Abgleich zu speichern. Die Integrationsdiagnose zeigt
  die Anzahl ausstehender Statistikwerte.

- Diskussionen: https://github.com/thecem/octopus_germany/discussions
- Issues: https://github.com/thecem/octopus_germany/issues

## Sponsoring

[![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-Sponsor-ea4aaa?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/thecem)
[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/K3K71LPRM2)

GitHub Sponsors ist verfuegbar, sobald GitHub das persoenliche Sponsors-Profil
freigegeben hat. Bis dahin steht Ko-fi als Alternative bereit.
