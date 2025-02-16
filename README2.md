# Octopus Germany Integration

> [!NOTE]
> Diese Integration ermöglicht es Ihnen, Daten von Ihrem Octopus Energy Germany Konto in Home Assistant zu integrieren.

## Funktionen

- **Kontoinformationen**: Zeigt Ihre Vertragskontonummer und den aktuellen Kontostand an.
- **Geplante Dispatches**: Verfolgt geplante Dispatches und deren Zeiträume.
- **Gerätesteuerung**: Integriert und steuert Ihre Octopus-kompatiblen Geräte.

## Installation

1. **Herunterladen**: Laden Sie die Integration von [GitHub](https://github.com/thecem/octopus_germany) herunter.
2. **Kopieren**: Kopieren Sie den Ordner `octopus_germany` in das Verzeichnis `custom_components` Ihres Home Assistant.
3. **Konfiguration**: Fügen Sie die Integration über die Home Assistant Benutzeroberfläche hinzu und geben Sie Ihre Octopus Energy Germany Anmeldedaten ein.

## Konfigurationsoptionen

| Option          | Beschreibung                              |
|-----------------|-------------------------------------------|
| `email`         | Ihre Octopus Energy Germany E-Mail-Adresse|
| `password`      | Ihr Octopus Energy Germany Passwort       |
| `update_interval` | Intervall für die Aktualisierung der Daten (in Stunden) |

## Sensoren

Die Integration erstellt die folgenden Sensoren:

- **Vertragskontonummer**: Zeigt Ihre Octopus Energy Germany Vertragskontonummer an.
- **Elektrizitätskonto**: Zeigt den aktuellen Kontostand in Euro an.
- **Geplante Dispatches**: Zeigt Informationen zu geplanten Dispatches an, einschließlich Delta und kWh.
- **Gerätesteuerung**: Integriert und steuert Ihre Octopus-kompatiblen Geräte.

## Beispielkonfiguration

```yaml
octopus_germany:
  email: "your-email@example.com"
  password: "your-password"
  update_interval: 2
