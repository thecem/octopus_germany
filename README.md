# Integration Octopus Energy Germany für Home Assistant

## Was ist Octopus Energy?

[Octopus Energy](https://octopusenergy.de/)

Unter anderem bietet es die **Solar Wallet**, einen Service, der es ermöglicht, durch Solarüberschüsse erhaltenes Guthaben zu sammeln, um die Rechnung auf 0 € zu reduzieren und für zukünftige Rechnungen zu sparen.

## Was macht die Octopus Germany Komponente?

Diese Komponente verbindet sich mit deinem _Octopus Energy_ Konto, um den aktuellen Stand deiner **Solar Wallet** sowie die Basisdaten der letzten Rechnung abzurufen.

Diese Komponente wurde von den Ingenieuren von _Octopus Energy_ überprüft und genehmigt.

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
Nach der Konfiguration der Komponente hast du zwei Entitäten für jedes Konto, das mit deiner E-Mail verknüpft ist (normalerweise eines).

### Solar Wallet
Die Solar Wallet Entität gibt den aktuellen Wert deiner Solar Wallet zurück. Dieser Wert (in Euro) wird auf den Stand deiner letzten Rechnung aktualisiert. Derzeit kann er nicht in Echtzeit abgefragt werden.

## Octopus Credit
Die Octopus Credit Entität gibt den aktuellen Wert deines Guthabens bei Octopus zurück, das durch geworbene Konten oder andere mögliche Boni erhalten wurde.

### Letzte Rechnung
Diese Entität gibt die Kosten deiner letzten Rechnung zurück.

Zusätzlich sind in den Attributen die Ausstellungsdaten dieser Rechnung sowie der Zeitraum (Anfang und Ende) verfügbar.

## Nutzung

Du kannst diese Entitäten verwenden, um den Status anzuzeigen und Automatisierungen zu erstellen, um dich beispielsweise zu informieren, wenn sich das Attribut "Ausgestellt" der letzten Rechnung ändert.

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

![card.png](img/card.png)

## Videotutorial

[![Octopus Germany](http://img.youtube.com/vi/fJ1W_wACbfw/0.jpg)](http://www.youtube.com/watch?v=fJ1W_wACbfw)

