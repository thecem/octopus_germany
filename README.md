# Integration Octopus Energy Germany für Home Assistant

## Was ist Octopus Energy?

[Octopus Energy](https://octopusenergy.de/)



## Was macht die Octopus Germany Komponente?

Diese Komponente verbindet sich mit deinem _Octopus Energy_ Konto, um die aktuellen "Devices" und die planned Dispatches in Home Assitant dar zu stellen.


Diese Komponente wurde von den Ingenieuren von _Octopus Energy_ NICHT überprüft und noch nicht genehmigt.

## Installation

Du kannst die Komponente über HACS installieren:

### Direkt über _My Home Assistant_
[![Öffne deine Home Assistant Instanz und öffne ein Repository im Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=miguelangellv&repository=octopus_spain&category=integration)

### Manuell
```
HACS -> Integrationen -> Drei Punkte -> Benutzerdefinierte Repositories
```
Kopiere die URL des Repositories (https://github.com/MiguelAngelLV/octopus_spain), wähle als Kategorie _Integration_ und klicke auf _Hinzufügen_.

## Konfiguration

Nach der Installation gehe zu _Geräte und Dienste -> Integration hinzufügen_ und suche nach _Octopus_.

Der Assistent wird dich nach deiner E-Mail und deinem Passwort von [Octopus Energy](https://octopusenergy.de/) fragen.

## Entitäten
Nach der Konfiguration der Komponente hast du Entitäten für jedes Konto, das mit deiner E-Mail verknüpft ist (normalerweise eines).

## Octopus Konto
Die Octopus Konto Entität gibt den aktuellen Wert deines Guthabens bei Octopus zurück, das durch geworbene Konten oder andere mögliche Boni erhalten wurde.

## Nutzung

Du kannst diese Entitäten verwenden, um den Status anzuzeigen und Automatisierungen zu erstellen.

Eine Möglichkeit, die Daten darzustellen, wäre diese:

```yaml
title: Octopus Germany
type: entities
entities:
  - entity: sensor.letzte_rechnung_octopus
  - entity: sensor.solar_wallet
  - entity: sensor.octopus_credit
  - type: attribute
    entity: sensor.letzte_rechnung_octopus
    name: Anfang
    icon: mdi:calendar-start
    attribute: Anfang
  - type: attribute
    entity: sensor.letzte_rechnung_octopus
    name: Ende
    icon: mdi:calendar-end
    attribute: Ende
  - type: attribute
    entity: sensor.letzte_rechnung_octopus
    name: Ausgestellt
    icon: mdi:email-fast-outline
    attribute: Ausgestellt
```

## Entwicklung

Diese Integration ist gerade in Entwicklung und stellt für die [Germany API](https://api.oeg-kraken.energy/v1/graphql) die erste Integration dar.
Speiziell für den Tarif intelligent Octopus Go entwickelt um die Dispatch Zeiten sichtbar und nutzbar zu machen.

Mit dem Dispatch Time Sensor kannst du nun auch andere Geräte zum günstigen Preis ausserhalb der 0-5 Uhr Go Zeit nutzen. (Wenn das Auto Lädt, kannst Du sicher sein das auch andere Verbraucher den Strom zum günstigsten Tarif nutzen können)

## Entwicklung Mithilfe

Wenn Du weitere Entities benötigst, kann ich diese gerne auch erstellen. Hierzu bitte den Query und die Antwort aus dem API Explorer kopieren und als Issue einstellen. Nur wenn beide inforatonen vorhanden sind, kann eine Integration als Entity erfolgen.