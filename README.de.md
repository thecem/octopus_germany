# Octopus Germany Integration für Home Assistant

Sprache / Language: [Deutsch](README.de.md) | [English](README.md)

[![Repository im Marketplace auf My Home Assistant oeffnen](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=thecem&repository=octopus_germany&category=integration)

[![Neueste Version](https://img.shields.io/github/v/release/thecem/octopus_germany?label=Version&color=41BDF5&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/releases/latest)
[![Home-Assistant-Mindestversion](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fthecem%2Foctopus_germany%2Fmain%2Fhacs.json&query=%24.homeassistant&label=Home%20Assistant%20%E2%89%A5&color=41BDF5&logo=homeassistant&logoColor=white)](hacs.json)
[![Lizenz](https://img.shields.io/github/license/thecem/octopus_germany?label=Lizenz&color=41BDF5)](LICENSE)

[![GitHub-Sterne](https://img.shields.io/github/stars/thecem/octopus_germany?label=Sterne&color=41BDF5&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/stargazers)
[![GitHub-Release-Downloads](https://img.shields.io/github/downloads/thecem/octopus_germany/total?label=Downloads%20seit%2011%2F2026&color=41BDF5&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/releases)
[![Aktive Home-Assistant-Installationen](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fanalytics.home-assistant.io%2Fcustom_integrations.json&query=%24.octopus_germany.total&label=aktive%20Installationen&color=41BDF5&logo=homeassistant&logoColor=white&cacheSeconds=21600)](https://analytics.home-assistant.io/custom_integrations)

Diese Custom Integration bindet Octopus Energy Germany in Home Assistant ein. Sie liefert Kontodaten, Tarifpreise, SmartFlex-Status sowie Steuerungsmöglichkeiten fuer EV/Wallbox.

*Diese Integration ist nicht offiziell mit Octopus Energy verbunden.*

Voraussetzung ist Home Assistant **2026.11.0 oder neuer**. Entwicklung,
Regressionstests und das Setup des Entwicklungscontainers verwenden
Home Assistant **2026.11.0**. Die Mindestversion steht in `hacs.json`;
die vorhandenen Markenbilder werden im Integrationsordner `brand/` mitgeliefert.

**Zu den Zaehlern:** Downloads zaehlen GitHub-Release-Asset-Downloads aller
Versionen, einschliesslich erneuter Downloads und Updates. Die Zaehlung begann
mit den ZIP-Release-Assets im November 2026; fruehere Installationen fehlen.
Aktive Installationen stammen aus freiwilligen Home-Assistant-Analytics-Meldungen
und erfassen nicht alle Nutzer. Beide Zaehler messen unterschiedliche Dinge.

---

**Support das Projekt**
[![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-Sponsor-ea4aaa?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/thecem)
[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/K3K71LPRM2)

GitHub Sponsors ist jetzt freigeschaltet. Du kannst das Projekt ueber
GitHub Sponsors oder Ko-fi unterstuetzen.

## Freund*innen werben

Wenn du über [meinen Empfehlungslink](https://octopusenergy.de/empfehlungen?referralCode=free-cat-744) zu Octopus Energy wechselst, erhältst du **150 €** als Rechnungsgutschrift. Es gelten die Teilnahmebedingungen von Octopus Energy.

## Funktionsumfang

- Konto- und Saldo-Daten fuer Strom, Gas und Waerme sowie Gaszaehler, Gasvertragslaufzeit und Multi-Account/Multi-Device-Unterstuetzung
- Aktuelle Strom- und Gaspreise (Festpreis, TOU und dynamische Tarife) sowie historische Agreement-Preise
- Paragraph-14a-Netzentgelte mit von OE gemeldetem Modul, standardisierten NT/ST/HT-Attributen und vollstaendigem Tagesplan
- Kombinierter Bruttopreis aus Octopus-Tarif und zeitvariablem Netzentgelt mit Tagesplan der Tarif-/Modul-3-Preiskombinationen und Zeitintervalle; numerische Werte bleiben fuer Templates und Automationen verfuegbar
- Alle von OE gelieferten vergangenen, aktiven und zukuenftigen Stromvertraege mit Brutto-/Netto-Arbeitspreisen, MwSt. sowie Netto-Monatsgrundpreis und brutto ausgewiesenen Grundpreisstufen mit Gueltigkeitsdaten in den Attributen des Strompreis-Sensors
- Service `octopus_germany.export_cost_report`: taegliche Kostenschaetzung nach Agreement-Preisbezeichnung als Monats-/Jahres-CSV aus Messwerten und API-Netzentgelten des tatsaechlichen Netzbetreibers, einschliesslich Waermestromtarifen. Keine verlaessliche Abrechnung dynamischer Tarife ohne historische Ist-Intervallpreise; Prognosen sind keine historischen Preise.
- Smart-Meter- und Kosten-CSV-Dateien liegen unter `/config/octopus_germany/exports`; HA zeigt pro Export eine persistente Benachrichtigung mit dateigebundenem Bearer-Token-Downloadlink. Gueltigkeit: standardmaessig 24 Stunden, in den Integration-Optionen auf 1 bis 168 Stunden einstellbar. Bestehende Links behalten ihre Ablaufzeit.
- SmartFlex-Geraetestatus, Dispatching, Session-Daten
- Schalter fuer Smart Control und Boost Charge
- Fahrzeug- und Ladepunktdaten wie SoC und Batteriegroesse, sofern vom Anbieter geliefert
- **Smart-Meter-Readings**: Vortagsverbrauch akkumuliert mit stundenweiser Aufschluesselung (aus bei Octopus gespeicherten Zaehlerdaten)
- Zaehlerregistersensoren fuer verwertbare OBIS-Register mit Messwerthistorie; Nullwerte bleiben gueltige Messwerte
- **Historische Octopus-Daten auslesen**: Historische Verbrauchs- und Zaehlerdaten aus dem Octopus-System abrufen
- Strom- und Gaszaehlerstaende an die OE-API uebermitteln; Einreichungen unterstuetzen Tageswerte, keine 15-Minuten-Intervalle
- Multi-Account und Multi-Device Support

## Installation

### Home Assistant Marketplace

1. **Einstellungen** > **Marketplace** oeffnen
2. Nach **Octopus Germany** suchen. Falls nicht gelistet, **Vom Link hinzufuegen** auswaehlen und `https://github.com/thecem/octopus_germany` eingeben; bei Aufforderung GitHub verbinden
3. Integration installieren
4. Home Assistant neu starten
5. Integration unter **Einstellungen** > **Geraete und Dienste** > **Integration hinzufuegen** hinzufuegen

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

### Manuell

1. Ordner octopus_germany nach custom_components kopieren
2. Home Assistant neu starten
3. Integration in Einstellungen > Geraete und Dienste hinzufuegen

## Konfiguration

Die Konfiguration erfolgt komplett ueber die Home-Assistant-UI:

1. Einstellungen > Geraete und Dienste
2. Integration hinzufuegen
3. Octopus Germany auswaehlen
4. Login-Daten eingeben

## Dokumentation

Fuer eine kompakte Startseite sind die Details aufgeteilt:

- Vollstaendige Entitaets- und Attributreferenz:
  - [custom_components/octopus_germany/README.de.md](custom_components/octopus_germany/README.de.md)
- Aktionen und Dienste mit Beispielen:
  - [docs/ACTIONS_AND_SERVICES.de.md](docs/ACTIONS_AND_SERVICES.de.md)
- Kostenbericht mit Berechnungen, Eingaben, CSV-Aufbau und Rechtsrahmen:
  - [docs/COST_REPORT.de.md](docs/COST_REPORT.de.md)
- Vorlage fuer netzbetreiber- und jahresspezifische Stundenwerte:
  - [docs/examples/grid_fee_schedules.example.json](docs/examples/grid_fee_schedules.example.json)

## Aktionen und Dienste auf einen Blick

- switch.octopus_<account_number>_<device_id>_smart_control
  - on: Smart Control aktivieren
  - off: Smart Control pausieren
- switch.octopus_germany_<account_number>_<device_id>_boost_charge
  - Sofortiges Boost-Laden starten/stoppen
- octopus_germany.set_device_preferences
  - Ziel-SoC und Zielzeit fuer ein Geraet setzen
- octopus_germany.get_smart_meter_readings
  - Tageswerte aus iMSys Historie laden
- octopus_germany.export_smart_meter_csv
  - iMSys-Daten ueber paginierte Monatsabfragen als CSV exportieren
  - Verwendet die Home-Assistant-Zeitzone und behaelt OE-Messqualitaetsdaten beim Laden bei
- octopus_germany.export_cost_report
  - Kostenbericht als Monats- oder Jahres-CSV exportieren
- octopus_germany.submit_meter_readings
  - Strom- oder Gaszaehlerstand an die OE-API uebermitteln
- octopus_germany.refresh_intelligent_data
  - Intelligent-Geraete- und Dispatch-Daten sofort aktualisieren

## Hinweis zu iMSys / SMGW-HAN

Fuer direkte HAN-Auslesung am Smart Meter Gateway (SMGW) kann diese Integration parallel genutzt werden:

- [TRON4R/ha-ppc-smgw-han](https://github.com/TRON4R/ha-ppc-smgw-han)

Empfohlene Kombination:

- octopus_germany fuer Tarif, Konto, SmartFlex, Steuerung sowie das Auslesen der bei Octopus gespeicherten historischen Verbrauchs-/Zaehlerdaten
- ha-ppc-smgw-han fuer lokale HAN-Rohdaten

## Automationen

- [Octopus Intelligent Go mit EVCC](https://github.com/ha-puzzles/homeassistant-puzzlepieces/blob/main/use-cases/stromtarife/octopus-intelligent-go/README.md)

## Entwicklung und Validierung

[![Hassfest](https://img.shields.io/github/actions/workflow/status/thecem/octopus_germany/hassfest.yaml?branch=main&label=Hassfest&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/actions/workflows/hassfest.yaml)
[![Katalogvalidierung](https://img.shields.io/github/actions/workflow/status/thecem/octopus_germany/hacs.yaml?branch=main&label=Katalogvalidierung&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/actions/workflows/hacs.yaml)
[![Offene Issues](https://img.shields.io/github/issues/thecem/octopus_germany?label=offene%20Issues&color=41BDF5&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/issues)
[![Letzter Commit](https://img.shields.io/github/last-commit/thecem/octopus_germany/main?label=letzter%20Commit&color=41BDF5&logo=github&logoColor=white)](https://github.com/thecem/octopus_germany/commits/main)

Validierungsbadges zeigen den Workflow-Status, keine Zertifizierung oder
Empfehlung durch Home Assistant.

## Debugging

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

Beispiel fuer Debug-Logs in configuration.yaml:

```yaml
logger:
  logs:
    custom_components.octopus_germany: debug
    custom_components.octopus_germany.octopus_germany: debug
    custom_components.octopus_germany.switch: debug
```

## API-Unterstuetzung

Die Integration verwendet zwei GraphQL-Endpunkte:

| API | Endpunkt | Verwendung |
|---|---|---|
| OEG Kraken GraphQL | `https://api.oeg-kraken.energy/v1/graphql/` | Anmeldung, Konten, Vertraege, Preise, Smart-Meter-/Zaehlerdaten und Intelligent-/SmartFlex-Geraetesteuerung |
| OE Backend GraphQL | `https://api.backend.octopusenergy.de/v1/graphql/` | Variable Netzentgelte (`variableGridFees`), authentifiziert mit demselben Kraken-Token |

- [Kraken-GraphQL-Dokumentation](https://developer.oeg-kraken.energy/graphql/)
- [Octopus-Entwicklerdokumentation mit REST-Referenz](https://developer.oeg-kraken.energy/): Hintergrundinformation; die Integration ruft derzeit keine Octopus-REST-Endpunkte auf.
- Schema-Snapshots: [OEG Kraken](custom_components/octopus_germany/oeg_graphql_schema.yaml) und [OE Backend](custom_components/octopus_germany/oe_backend_graphql_schema.json).

`https://my.octopusenergy.de/` ist der Link zum Kundenportal in der
Geraeteoberflaeche, kein zusaetzlicher API-Endpunkt.

## Support

- Diskussionen: https://github.com/thecem/octopus_germany/discussions
- Issues: https://github.com/thecem/octopus_germany/issues

## Sponsoring

Wenn dir die Integration hilft, kannst du ihre Weiterentwicklung ueber
GitHub Sponsors oder Ko-fi unterstuetzen:

[![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-Sponsor-ea4aaa?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/thecem)
[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/K3K71LPRM2)

GitHub Sponsors ist jetzt freigeschaltet. Du kannst das Projekt ueber
GitHub Sponsors oder Ko-fi unterstuetzen.

## Lizenz

MIT Lizenz

## Haftungsausschluss

Diese Integration ist nicht offiziell von Octopus Energy Germany.
