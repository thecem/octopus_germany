# Daily Meter Reading Upload Example

This example shows how to upload one daily meter end value to the OE API from a Home Assistant automation.

Important:

- This integration only supports **daily values** for submission.
- Do **not** try to submit 15-minute intervals to the OE write mutation.
- The value you send should be the final daily end value for the previous day.

## Example Automation

```yaml
alias: Upload daily meter reading to Octopus
description: Upload the previous day's final meter reading once per day.
trigger:
  - platform: time
    at: "00:30:00"
condition:
  - condition: template
    value_template: >-
      {{ states('sensor.ppc_smgw_zahlerstand_verbrauch_endstand_vortag') not in ['unknown', 'unavailable', 'none'] }}
action:
  - service: octopus_germany.submit_meter_readings
    data:
      meter_type: electricity
      meter_id: "1234567890"
      reading_date: "{{ (now().date() - timedelta(days=1)).isoformat() }}"
      readings_json: >-
        [{"value": {{ states('sensor.ppc_smgw_zahlerstand_verbrauch_endstand_vortag') | float }}, "register_obis_code": "1-0:1.8.0"}]
mode: single
```

## Notes

- Replace `meter_id` with the OE meter ID from the meter entity attributes.
- Replace the sensor entity with the daily end value sensor from `ha-ppc-smgw-han` or another source.
- For multi-register meters, include multiple objects in `readings_json`.
