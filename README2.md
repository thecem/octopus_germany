# Octopus Germany Integration

> [!NOTE]
> Diese Integration ermöglicht es Ihnen, Daten von Ihrem Octopus Energy Germany Konto in Home Assistant zu integrieren.

## Entwicklung

Diese Integration ist gerade in Entwicklung und stellt für die [Germany API](https://api.oeg-kraken.energy/v1/graphql) die erste Integration dar. Speziell für den Tarif Intelligent Octopus Go entwickelt, um die Dispatch Zeiten sichtbar und nutzbar zu machen.

Mit dem Dispatch Time Sensor kannst du nun auch andere Geräte zum günstigen Preis außerhalb der 0-5 Uhr Go Zeit nutzen. (Wenn das Auto lädt, kannst du sicher sein, dass auch andere Verbraucher den Strom zum günstigsten Tarif nutzen können).

## Entwicklung Mithilfe

Wenn du weitere Entities benötigst, kann ich diese gerne erstellen. Hierzu bitte den Query und die Antwort aus dem API Explorer kopieren und als Issue einstellen. Nur wenn beide Informationen vorhanden sind, kann eine Integration als Entity erfolgen.

## Funktionen

- **Kontoinformationen**: Zeigt deine Vertragskontonummer und den aktuellen Kontostand an.
- **Geplante Dispatches**: Verfolgt geplante Dispatches und deren Zeiträume.
- **Gerätesteuerung**: Integriert und steuert deine Octopus-kompatiblen Geräte.

## Installation (Manuell)

1. **Herunterladen**: Lade die Integration von [GitHub](https://github.com/thecem/octopus_germany) herunter.
2. **Kopieren**: Kopiere den Ordner `octopus_germany` in das Verzeichnis `custom_components` deines Home Assistant.
3. **Konfiguration**: Füge die Integration über die Home Assistant Benutzeroberfläche hinzu und gib deine Octopus Energy Germany Anmeldedaten ein.

## Installation (HACS)

Du kannst die Integration über HACS installieren:

[![Öffne deine Home Assistant Instanz und öffne ein Repository im Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=thecem&repository=octopus_germany&category=integration)

## Konfiguration (UI)

Nach der Installation gehe zu _Geräte und Dienste -> Integration hinzufügen_ und suche nach _Octopus_.

Der Assistent wird dich nach deiner E-Mail und deinem Passwort von [Octopus Energy](https://octopusenergy.de/) fragen.

## Konfiguration (configuration.yaml)

Die integration kann auch per configuration.yaml erfolgen.

### Konfigurationsoptionen

| Option          | Beschreibung                              |
|-----------------|-------------------------------------------|
| `email`         | Deine Octopus Energy Germany E-Mail-Adresse|
| `password`      | Dein Octopus Energy Germany Passwort       |
| `update_interval` | Intervall für die Aktualisierung der Daten (in Stunden) |

### Beispielkonfiguration

```yaml
octopus_germany:
  email: "your-email@example.com"
  password: "your-password"
  update_interval: 2
```

## Sensoren

Die Integration erstellt die folgenden Sensoren:

- **Vertragskontonummer**: Zeigt deine Octopus Energy Germany Vertragskontonummer an.
- **Elektrizitätskonto**: Zeigt den aktuellen Kontostand in Euro an.
- **Geplante Dispatches**: Zeigt Informationen zu geplanten Dispatches an, einschließlich Delta und kWh.
- **Gerätesteuerung**: Integriert und steuert deine Octopus-kompatiblen Geräte.


## Intelligent Octopus Go Tarif

Der Intelligent Octopus Go Tarif ermöglicht es dir, von günstigeren Strompreisen während der Nachtstunden zu profitieren. Mit dem Dispatch Time Sensor kannst du sicherstellen, dass deine Geräte den Strom zum günstigsten Tarif nutzen, insbesondere außerhalb der 0-5 Uhr Go Zeit.
