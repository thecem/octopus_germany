2025-02-16 19:46:46.314 ERROR (MainThread) [homeassistant.components.sensor] Error adding entity sensor.octopus_a_66df80ae_account_number for domain sensor with platform octopus_germany
Traceback (most recent call last):
  File "/workspaces/core/homeassistant/helpers/entity_platform.py", line 633, in _async_add_entities
    await coro
  File "/workspaces/core/homeassistant/helpers/entity_platform.py", line 972, in _async_add_entity
    await entity.add_to_platform_finish()
  File "/workspaces/core/homeassistant/helpers/entity.py", line 1383, in add_to_platform_finish
    await self.async_added_to_hass()
          ~~~~~~~~~~~~~~~~~~~~~~~~^^
TypeError: OctopusAccountNumberSensor.async_added_to_hass() takes 0 positional arguments but 1 was given