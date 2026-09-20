# Entity-Kompatibilitaet

Diese Liste beschreibt die bestehenden `unique_id`-Muster. Sie gelten als kompatibler Vertrag und duerfen ohne explizite Migration nicht geaendert werden.

## Stabile Account-Entities

- `octopus_<account>_electricity_price`
- `octopus_<account>_electricity_balance`
- `octopus_<account>_electricity_latest_reading`
- `octopus_<account>_14a_module`
- `octopus_<account>_variable_grid_fee`
- `octopus_<account>_gas_balance`
- `octopus_<account>_gas_tariff`
- `octopus_<account>_gas_malo_number`
- `octopus_<account>_gas_melo_number`
- `octopus_<account>_gas_meter`
- `octopus_<account>_gas_latest_reading`
- `octopus_<account>_heat_balance`

## Fahrzeug- und Geraete-Entities

Geraetebezogene IDs verwenden die stabile API-Geraete-ID:

- `octopus_<account>_<device_id>_status`
- `octopus_<account>_<device_id>_soc`
- `octopus_<account>_<device_id>_battery_size`
- `octopus_<account>_<device_id>_active_power`
- `octopus_<account>_<device_id>_plugged`
- `octopus_<account>_<device_id>_smart_control`
- `octopus_<account>_<device_id>_boost_charge`

Nach dem Upgrade werden die neuen UUID-basierten IDs als neue Home-Assistant-Entities angelegt; bestehende name-basierte IDs koennen als veraltete Registry-Eintraege bestehen bleiben.

## Bewusste Entscheidungen

- SoC und Battery Size bleiben erhalten.
- SoC Change und SoC Limit werden nicht wieder eingefuehrt.
- Schalter bleiben aus Rueckwaertskompatibilitaetsgruenden erhalten.
- Intelligent-Entities werden nur bei erkannter Intelligent-Capability erzeugt.
- BottlecapDave dient als Architektur- und UX-Referenz, nicht als Namens- oder API-Vertrag.
