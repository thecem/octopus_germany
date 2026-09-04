# Entity-Kompatibilitaet

Diese Liste beschreibt die bestehenden `unique_id`-Muster. Sie gelten als kompatibler Vertrag und duerfen ohne explizite Migration nicht geaendert werden.

## Stabile Account-Entities

- `octopus_<account>_electricity_price`
- `octopus_<account>_electricity_balance`
- `octopus_<account>_electricity_latest_reading`
- `octopus_<account>_gas_balance`
- `octopus_<account>_gas_tariff`
- `octopus_<account>_gas_malo_number`
- `octopus_<account>_gas_melo_number`
- `octopus_<account>_gas_meter`
- `octopus_<account>_gas_latest_reading`
- `octopus_<account>_heat_balance`

## Fahrzeug- und Geraete-Entities

Bestehende geraetebezogene IDs verwenden den normalisierten Anzeigenamen:

- `octopus_<account>_<device_name>_status`
- `octopus_<account>_<device_name>_soc`
- `octopus_<account>_<device_name>_battery_size`
- `octopus_<account>_<device_name>_active_power`
- `octopus_<account>_<device_name>_plugged`
- `octopus_<account>_<device_name>_smart_control`
- `octopus_<account>_<device_name>_boost_charge`

Eine Umstellung auf stabile API-Gerate-IDs waere langfristig besser, darf aber erst zusammen mit einer Home-Assistant-Entity-Registry-Migration erfolgen. Bis dahin bleiben bestehende IDs unveraendert.

## Bewusste Entscheidungen

- SoC und Battery Size bleiben erhalten.
- SoC Change und SoC Limit werden nicht wieder eingefuehrt.
- Schalter bleiben aus Rueckwaertskompatibilitaetsgruenden erhalten.
- Intelligent-Entities werden nur bei erkannter Intelligent-Capability erzeugt.
- BottlecapDave dient als Architektur- und UX-Referenz, nicht als Namens- oder API-Vertrag.
