2025-09-22 - Short release notes

Highlights
 - Fix: Boost Charge switch could become unavailable due to independent coordinator using an expired JWT. The boost switch now uses the main coordinator and shared token handling.
 - Fix: Restored `boost_charge_active` and `boost_charge_available` attributes on the Boost Charge switch.
 - Cleanup: Removed remnants of deprecated `set_vehicle_charge_preferences` service and consolidated to `set_device_preferences`.
 - Docs: Updated `custom_components/octopus_germany/README.md` and added `TECHNICAL_NOTES.md` describing architecture, token management, and availability rules for the boost switch.
 - Repository: Rebased local `main` onto `origin/main` to reconcile divergent branches.

Notes for integrators
 - Boost Charge switch availability depends on the device being LIVE, not suspended, and supporting smart control/smart charging on the account.
 - If you maintain CI or local clones, consider choosing a default pull behavior to avoid repeated hints from Git. Example to set rebase as default:

  git config pull.rebase true

Contact
 - For questions or if you observe regressions, open an issue or attach logs from your Home Assistant instance.
