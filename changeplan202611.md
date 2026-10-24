# Home Assistant 2026.11 – Changeplan

Stand: 24.10.2026

Ziel: Integration und Entwicklungsumgebung auf Home Assistant 2026.11
ausrichten; Anwenderdokumentation auf den Marketplace fokussieren.

## Ergebnis der Bestandsaufnahme

| Thema | Stand im Repository | Maßnahme |
|---|---|---|
| HACS → Marketplace | Die Installationsanleitungen und Badges nannten noch die eigenständige HACS-Oberfläche. | Auf „Einstellungen > Marketplace“ umgestellt. Keine veraltete HACS-Installationsanleitung fortführen. |
| Markenbilder | Bilder sind bereits unter `custom_components/octopus_germany/brand/` enthalten. | Keine Bildmigration nötig. `brand/` ist der Integrationsordner; Home Assistant stellt die Bilder über seine Brands-API bereit. Für Marketplace-Vorschauen werden die Assets aus dem Repository verwendet. |
| Marketplace-Kategorien | Im Manifest fehlten Kategorien. | `energy.energy_prices` und `energy.ev_charging` hinzugefügt; HACS-Action prüft, ob die Kategorien bekannt sind. |
| Mindestversion | `hacs.json` erlaubte bisher HA 2026.6.1. | Auf Wunsch auf HA 2026.11.0 angehoben. Damit werden ältere Versionen nicht mehr als unterstützt ausgewiesen. |
| Entwicklungsziel | `requirements.txt` und Dokumentation zielten auf HA 2026.10.1. | Auf HA 2026.11.0 ausgerichtet. Die lokal installierte Laufzeit muss nach Veröffentlichung aktualisiert werden. |
| HACS-Katalogprüfung | `.github/workflows/hacs.yaml` verwendet `hacs/action@main`. | Beibehalten: Marketplace verwendet weiterhin denselben Katalog und `hacs.json`; die Action bleibt eine verfügbare Repository-Prüfung. |
| Weitere HA-2026.11-Änderungen | Kein `RestoreStateData.last_states`, keine selbst implementierte MFA-Authentifizierung und keine Update-/Climate-/Water-heater-Entity gefunden. `DeviceInfo` wird bereits über typisierte Felder erstellt. | Keine Migration für diese APIs nötig. Die Rückgabewerte der Config-Entry-Funktionen sind für Custom Integrations weiterhin kompatibel. |
| Entity-ID-Wechsel | Mehrere Entities überschreiben `async_added_to_hass` bzw. `async_will_remove_from_hass`; `async_entity_id_changed` wird nicht implementiert. | HA 2026.11 behält für diese Entities vorerst das Entfernen/Wiederanlegen bei. Kein 2026.11-Blocker; vor dem Wegfall der Kompatibilität in 2027.11 erneut prüfen. |
| Recorder-Limit bei Preisattributen | `price_combinations` konnte die 16-KiB-Grenze überschreiten; Recorder verwarf dann alle Attribute einschließlich Einheit, was Langzeitstatistiken stoppte. | Nur `price_combinations` aus Recorder ausschließen. Der Live-Sensor und seine Tarifprognose bleiben unverändert verfügbar. Regressionstest prüft HA-Recorder-Serialisierung. |
| Dynamische Tarife im Kostenbericht | Historische Ist-Intervallpreise sind nicht als Historie in den Kontodaten verfügbar; aktuelle Prognosewerte sind kein Beleg für vergangene Abrechnungspreise. | Kostenbericht und Servicebeschreibung klar als nicht verlässliche Abrechnungsbasis für dynamische Tarife kennzeichnen. Keine Rechnungssummen als tatsächlich abgerechnet darstellen. |

## Umgesetzte Änderungen

- Mindestversion und Entwicklungsziel auf HA 2026.11.0 gestellt.
- Marketplace-Kategorien im Integrationsmanifest eingetragen.
- Englische und deutsche Start- und Integrationsdokumentation auf den
  eingebauten Marketplace aktualisiert; alte HACS-Bedienpfade entfernt.
- Vorhandene Markenbilder beibehalten und als mitgelieferte `brand/`-Assets
  beschrieben.
- Release Notes für Version `0.0.195-beta.1` ergänzt.
- Recorder-Regression für Issue [#129](https://github.com/thecem/octopus_germany/issues/129)
  ergänzt; die Liste `price_combinations` bleibt live erhalten, wird aber nicht
  in Recorder-Attribute geschrieben.
- Englische/deutsche Kostenbericht-Doku und Service-Beschreibungen warnen nun
  vor der Nutzung für eine dynamische Tarifabrechnung ohne historische
  Ist-Intervallpreise.
- Download-Link-Token sind nun in den Integration-Optionen auf 1 bis 168
  Stunden einstellbar (Standard 24 Stunden); die Einstellung gilt für neue
  Exporte. Authentifizierung, dateibezogene Gültigkeit und Pfadprüfung am
  Download-Endpunkt bleiben erhalten.

## Noch offen: lokale Home-Assistant-Laufzeit

Am 24.10.2026 enthält die lokale Python-Umgebung Home Assistant **2026.6.1**.
PyPI führt als neueste verfügbare Version **2026.10.3**; die Abfrage nach
`homeassistant==2026.11.0` liefert noch 404. Daher lässt sich die
2026.11-Laufzeit momentan nicht installieren oder hier starten. Sobald
2026.11.0 auf PyPI veröffentlicht ist:

1. `scripts/setup` ausführen, um die geänderte `requirements.txt` zu
   installieren.
2. Version mit `python3 -m pip show homeassistant` bestätigen.
3. `scripts/lint` und die Tests erneut ausführen.
4. Die lokale Instanz starten und Setup, Reload/Unload, Marketplace-Installation
   sowie Markenbilder in der UI prüfen.

Die installierte Abhängigkeit auf 2026.10.3 zu setzen wäre nur ein Zwischenstand
und würde das gewünschte 2026.11-Ziel nicht erfüllen. Deshalb wurde die
Laufzeit nicht fälschlich als aktualisiert ausgewiesen.

## Validierung vor Veröffentlichung

- [ ] HA 2026.11.0 tatsächlich installieren und vollständige Tests ausführen.
- [ ] Hassfest und HACS-Action bestehen lassen; insbesondere die Kategorien
  gegen die dann aktuelle Marketplace-Kategorieliste prüfen.
- [ ] Marketplace-Installation und Aktualisierung einer bestehenden
  Integration verifizieren.
- [ ] Konfigurationsfluss, Plattform-Setup, Entladen/Neuladen, Sensoren,
  Services und Markenbilder in einer frischen HA-Instanz smoke-testen.
- [ ] README, Manifest-Mindestversion und Release Notes konsistent prüfen.

## Release-Vorschlag

Der übliche Home-Assistant-Release-Rhythmus lässt für 2026.11 den
**4. November 2026** erwarten; zum Stand dieses Plans sind die endgültigen
Release Notes noch nicht veröffentlicht. Die aktuelle Integrationsfassung ist
als `0.0.195-beta.2` mit Mindestversion HA 2026.11.0 geplant und darf daher
vor 2026.11.0 nicht als nutzbares Release veröffentlicht werden. In den
Release-Text muss ausdrücklich: **„Pre-Release – nur mit Home Assistant
2026.11.0 oder neuer“**.

**Issue #129 kann unabhängig davon vorher als regulärer Patch erscheinen.**
Der Fix besteht nur aus der unterstützten Recorder-Attributausnahme und ist
laut Issue-Ersteller bereits unter HA 2026.10.2 einschließlich Recorder- und
Langzeitstatistik-Lifecycle getestet. Vorschlag: diesen eng begrenzten Fix
zuerst separat als stabile Version `0.0.194` veröffentlichen, ohne die
Mindestversion auf 2026.11 anzuheben. Danach den 2026.11-Stand als
`0.0.195-beta.2` testen; bei Veröffentlichung von HA 2026.11.0 und bestandenen
Checks am **6. November 2026** als `0.0.195` finalisieren. Das setzt einen
separaten Backport/Release-Stand für 0.0.194 voraus; die 2026.11-Prerelease
selbst kann nicht vor dem Core-Release von Nutzern mit älterem HA verwendet
werden. Bei verzögertem Core-Release oder Marketplace-/Brands-Regression
verschieben.

## Quellen

- [HACS und Marketplace – Übergang ab Home Assistant 2026.11](https://hacs.xyz/docs/marketplace/)
- [Home Assistant: eigene Markenbilder für Custom Integrations (ab 2026.3)](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/)
- [Home Assistant: Integrationskategorien und Marketplace-Katalog](https://contributors.home-assistant.io/blog/2026/10/20/integration-categories/)
- [Home Assistant: Änderungen an RestoreStateData](https://contributors.home-assistant.io/blog/2026/10/06/restore-state-last-states-removal/)
- [Home Assistant: Entity-Lifecycle-Hooks](https://contributors.home-assistant.io/blog/2026/10/12/new-entity-lifecycle-hooks/)
- [Home Assistant: DeviceInfo als Dataclass](https://contributors.home-assistant.io/blog/2026/10/13/device-info-class/)
- [Home Assistant: Config-Entry-Funktionen und Rückgabewerte](https://contributors.home-assistant.io/blog/2026/10/23/config-entry-methods-return-none/)
- [Home Assistant auf PyPI](https://pypi.org/project/homeassistant/)
