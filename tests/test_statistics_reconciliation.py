"""Regression tests for correction-aware external consumption statistics."""

# Mock fixtures intentionally mirror the production callback signatures.
# ruff: noqa: ANN001, ANN002, ANN201, ANN202, ARG001, ARG002, ARG005
# ruff: noqa: C408, D101, D102, D103, INP001, PT009, PT027, SIM117, SLF001

import asyncio
import tempfile
import types
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import homeassistant  # noqa: F401
from homeassistant import loader
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import frame
from homeassistant.helpers.recorder import async_initialize_recorder
from homeassistant.setup import async_setup_component

from custom_components.octopus_germany import diagnostics
from custom_components.octopus_germany import statistics as s
from custom_components.octopus_germany import statistics_reconciliation as r

AT = datetime(2026, 10, 18, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)


def quarters(at=AT, values=(".1", ".2", ".3", ".4")):
    return [
        {
            "start_time": (at + i * r.QUARTER).isoformat(),
            "end_time": (at + (i + 1) * r.QUARTER).isoformat(),
            "value": value,
            "unit": "kwh",
            "reading_quality": "COMBINED",
        }
        for i, value in enumerate(values)
    ]


def merge(cache, rows):
    return r.merge_measurements(
        cache, rows, AT, AT + timedelta(days=1), AT, NOW, "malo"
    )


class ReconciliationTests(unittest.TestCase):
    def test_duplicate_and_idempotence(self):
        cache, counts, conflicts = merge({}, quarters() * 2)
        self.assertEqual(counts["added"], 4)
        self.assertEqual(r.complete_hours(cache, conflicts), {AT: Decimal("1.0")})
        again, counts, conflicts = merge(cache, quarters())
        self.assertEqual(counts["identical"], 4)
        self.assertEqual(r.complete_hours(again, conflicts), {AT: Decimal("1.0")})

    def test_partial_then_late_delivery(self):
        cache, _, _ = merge({}, quarters()[:2])
        self.assertEqual(r.complete_hours(cache, set()), {})
        cache, _, _ = merge(cache, quarters()[2:])
        self.assertEqual(r.complete_hours(cache, set())[AT], Decimal(1))

    def test_missing_and_invalid_do_not_zero(self):
        cache, _, _ = merge({}, quarters())
        for value in (None, "NaN", "Infinity", "-1", True, "bad"):
            changed = quarters(values=(value, ".2", ".3", ".4"))
            result, counts, _ = merge(cache, changed)
            self.assertEqual(counts["invalid"], 1)
            self.assertEqual(r.complete_hours(result, set())[AT], Decimal(1))
        result, _, _ = merge(cache, [])
        self.assertEqual(result, cache)

    def test_conflicting_duplicates_not_adopted(self):
        cache, _, _ = merge({}, quarters())
        rows = quarters() + quarters(values=("9", ".2", ".3", ".4"))[:1]
        result, counts, conflicts = merge(cache, rows)
        self.assertEqual(counts["conflicts"], 1)
        self.assertEqual(Decimal(result[AT.isoformat()]["value_kwh"]), Decimal(".1"))
        self.assertEqual(r.complete_hours(result, conflicts), {})

    def test_correction_up_down_and_real_zero(self):
        cache, _, _ = merge({}, quarters())
        for value, expected in (("1.1", "2"), ("0", ".9")):
            result, counts, conflicts = merge(
                cache, quarters(values=(value, ".2", ".3", ".4"))
            )
            self.assertEqual(counts["corrected"], 1)
            self.assertEqual(r.complete_hours(result, conflicts)[AT], Decimal(expected))

    def test_metadata_preserved_without_original_inference(self):
        cache, _, _ = merge({}, quarters())
        self.assertEqual(cache[AT.isoformat()]["reading_quality"], "COMBINED")
        self.assertIsNone(cache[AT.isoformat()]["source"])
        self.assertEqual(cache[AT.isoformat()]["fetched_at"], NOW.isoformat())

    def test_validation_unit_time_meter_and_direction(self):
        for field, value in (
            ("unit", "watts"),
            ("start_time", "2026-10-18T00:00:00"),
            ("end_time", (AT + timedelta(minutes=10)).isoformat()),
            ("market_supply_point_id", "wrong"),
            ("reading_direction", "EXPORT"),
        ):
            rows = quarters()
            rows[0][field] = value
            _, counts, _ = merge({}, rows)
            self.assertEqual(counts["invalid"], 1, field)
        rows = quarters()
        rows[0].update(value="100", unit="Wh")
        cache, _, _ = merge({}, rows)
        self.assertEqual(r.complete_hours(cache, set())[AT], Decimal(1))

    def test_cumulative_rebase_retains_legacy_and_older_history(self):
        rows = [
            dict(start=AT - timedelta(hours=1), state=7, sum=100),
            dict(start=AT, state=1, sum=101),
            dict(start=AT + timedelta(hours=1), state=2, sum=103),
        ]
        untouched = deepcopy(rows)
        changes, unknown = r.rebuild_statistics(rows, {AT: Decimal(".5")}, AT, NOW)
        self.assertEqual(unknown, 1)
        self.assertEqual(
            [(x["state"], x["sum"]) for x in changes], [(0.5, 100.5), (2, 102.5)]
        )
        self.assertEqual(rows, untouched)
        self.assertTrue(all(x["start"] >= AT for x in changes))
        current = [rows[0], *changes]
        self.assertEqual(
            r.rebuild_statistics(current, {AT: Decimal(".5")}, AT, NOW)[0], []
        )

    def test_insertion_and_sparse_anchor(self):
        rows = [
            dict(start=AT - timedelta(days=90), state=7, sum=100),
            dict(start=AT + timedelta(hours=1), state=2, sum=102),
        ]
        changes, _ = r.rebuild_statistics(rows, {AT: Decimal(1)}, AT, NOW)
        self.assertEqual([x["sum"] for x in changes], [101, 103])

    def test_missing_baseline_keeps_initial_offset(self):
        rows = [dict(start=AT, state=1, sum=101)]
        changes, _ = r.rebuild_statistics(rows, {AT: Decimal(2)}, AT, NOW)
        self.assertEqual(changes[0]["sum"], 102)

    def test_insertion_before_unknown_legacy_baseline_is_rejected(self):
        rows = [dict(start=AT + timedelta(hours=1), state=1, sum=101)]
        with self.assertRaises(ValueError):
            r.rebuild_statistics(rows, {AT: Decimal(2)}, AT, NOW)

    def test_insertion_before_zero_legacy_baseline_is_safe(self):
        rows = [dict(start=AT + timedelta(hours=1), state=1, sum=1)]
        changes, _ = r.rebuild_statistics(rows, {AT: Decimal(2)}, AT, NOW)
        self.assertEqual([row["sum"] for row in changes], [2, 3])

    def test_dst_and_local_midnight(self):
        for now, hours in (
            (datetime(2026, 3, 30, 12, tzinfo=UTC), 23),
            (datetime(2026, 10, 26, 12, tzinfo=UTC), 25),
        ):
            start, end = r.window_bounds(now, "Europe/Berlin", 1)
            rows = []
            at = start
            while at < end:
                rows.extend(quarters(at, ("0",) * 4))
                at += timedelta(hours=1)
            cache, counts, conflicts = r.merge_measurements(
                {}, rows, start, end, start, now, "malo"
            )
            self.assertEqual(counts["missing"], 0)
            self.assertEqual(len(r.complete_hours(cache, conflicts)), hours)
        start, end = r.window_bounds(
            datetime(2026, 10, 20, 22, 30, tzinfo=UTC), "Europe/Berlin", 1
        )
        self.assertEqual(end, datetime(2026, 10, 20, 22, tzinfo=UTC))

    def test_cache_retention_and_partial_legacy_hour(self):
        cache, _, _ = merge({}, quarters())
        next_day = AT + timedelta(days=1)
        pruned, _, _ = r.merge_measurements(
            cache, [], next_day, next_day + timedelta(days=1), next_day, NOW, "malo"
        )
        self.assertEqual(pruned, {})
        partial, _, _ = merge({}, quarters()[:3])
        rows = [dict(start=AT, state=2, sum=102)]
        changes, _ = r.rebuild_statistics(
            rows, r.complete_hours(partial, set()), AT, NOW
        )
        self.assertEqual(changes, [])


class ImporterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.persisted = None
        self.rows = []
        self.api = types.SimpleNamespace(
            fetch_electricity_measurements_range=AsyncMock(return_value=quarters())
        )
        self.coordinator = types.SimpleNamespace(
            data={
                "A-TEST": {
                    "property_ids": ["p"],
                    "malo_number": "malo",
                    "meter": {"number": "test"},
                }
            },
            async_add_listener=MagicMock(return_value=MagicMock()),
        )
        self.hass = types.SimpleNamespace(
            config=types.SimpleNamespace(time_zone="Europe/Berlin"),
            loop=asyncio.get_running_loop(),
            async_create_background_task=lambda coro, name: asyncio.create_task(coro),
        )
        self.store = types.SimpleNamespace(
            async_load=AsyncMock(return_value=None),
            async_save=AsyncMock(side_effect=self.save),
        )
        self.recorder = types.SimpleNamespace(
            async_add_executor_job=AsyncMock(side_effect=self.read),
            async_block_till_done=AsyncMock(),
            queue_task=MagicMock(side_effect=lambda task: task.future.set_result(None)),
        )
        self.patches = [
            patch.object(s, "Store", return_value=self.store),
            patch.object(s, "get_instance", return_value=self.recorder),
            patch.object(s, "async_add_external_statistics", side_effect=self.write),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        self.importer = s.StatisticsReconciler(
            self.hass, self.api, self.coordinator, ["A-TEST"], "entry"
        )

    async def save(self, data):
        self.persisted = deepcopy(data)

    async def read(self, fn, hass, start, end, ids, *args):
        return {
            next(iter(ids)): [deepcopy(x) for x in self.rows if x["start"] >= start]
        }

    def write(self, hass, metadata, changes):
        rows = {x["start"]: x for x in self.rows}
        rows.update({x["start"]: deepcopy(x) for x in changes})
        self.rows = list(rows.values())

    async def test_first_30_then_7_then_daily_30_and_restart(self):
        await self.importer.async_run(NOW)
        first = self.api.fetch_electricity_measurements_range.call_args.args
        self.assertEqual(
            first[2], r.window_bounds(NOW, "Europe/Berlin", 30)[0].isoformat()
        )
        await self.importer.async_run(NOW)
        self.assertEqual(
            self.api.fetch_electricity_measurements_range.call_args.args[2],
            r.window_bounds(NOW, "Europe/Berlin", 7)[0].isoformat(),
        )
        self.assertEqual(len(self.rows), 1)
        self.store.async_load.return_value = deepcopy(self.persisted)
        restarted = s.StatisticsReconciler(
            self.hass, self.api, self.coordinator, ["A-TEST"], "entry"
        )
        await restarted.async_load()
        await restarted.async_run(NOW)
        self.assertEqual(restarted.data, self.persisted)
        tomorrow = NOW + timedelta(days=1)
        await restarted.async_run(tomorrow.replace(hour=2))  # 04:00 local: recent only
        self.assertEqual(
            self.api.fetch_electricity_measurements_range.call_args.args[2],
            r.window_bounds(tomorrow, "Europe/Berlin", 7)[0].isoformat(),
        )
        await restarted.async_run(tomorrow)
        self.assertEqual(
            self.api.fetch_electricity_measurements_range.call_args.args[2],
            r.window_bounds(tomorrow, "Europe/Berlin", 30)[0].isoformat(),
        )

    async def test_api_failure_and_empty_do_not_checkpoint(self):
        self.api.fetch_electricity_measurements_range.side_effect = RuntimeError(
            "API down"
        )
        with self.assertLogs(s._LOGGER, level="ERROR"):
            await self.importer.async_run(NOW)
        self.assertIsNone(self.persisted)
        self.assertEqual(self.rows, [])
        self.api.fetch_electricity_measurements_range.side_effect = None
        self.api.fetch_electricity_measurements_range.return_value = []
        with self.assertLogs(s._LOGGER, level="WARNING"):
            await self.importer.async_run(NOW)
        self.assertIsNone(self.persisted)

    async def test_readback_failure_retains_checkpoint_and_can_retry(self):
        with patch.object(s, "async_add_external_statistics"):
            with self.assertLogs(s._LOGGER, level="ERROR"):
                await self.importer.async_run(NOW)
        self.assertFalse(self.importer.stopped)
        checkpoint = self.persisted["accounts"]["A-TEST"]
        self.assertNotIn("last_success", checkpoint)
        self.assertEqual(checkpoint["pending_statistics"][0]["sum"], 1)
        self.assertIn("verification_error", self.importer.status)
        await self.importer.async_run(NOW)
        self.assertEqual(self.importer.status["phase"], "complete")
        self.assertEqual(len(self.rows), 1)
        self.assertNotIn("pending_statistics", self.persisted["accounts"]["A-TEST"])

    async def test_readback_value_mismatch_is_reported_and_retried(self):
        def wrong_write(hass, metadata, changes):
            self.write(hass, metadata, changes)
            self.rows[-1]["sum"] += 0.1

        with patch.object(s, "async_add_external_statistics", side_effect=wrong_write):
            with self.assertLogs(s._LOGGER, level="ERROR") as logs:
                await self.importer.async_run(NOW)
        self.assertIn("expected", "\n".join(logs.output))
        self.assertIn("received", "\n".join(logs.output))
        self.assertFalse(self.importer.stopped)
        self.assertNotIn("last_success", self.persisted["accounts"]["A-TEST"])
        self.store.async_load.return_value = deepcopy(self.persisted)
        restarted = s.StatisticsReconciler(
            self.hass, self.api, self.coordinator, ["A-TEST"], "entry"
        )
        await restarted.async_load()
        await restarted.async_run(NOW)
        self.assertEqual(self.rows[-1]["sum"], 1)
        self.assertEqual(restarted.status["phase"], "complete")

    async def test_nonfinite_readback_does_not_advance_checkpoint(self):
        def invalid_write(hass, metadata, changes):
            self.write(hass, metadata, changes)
            self.rows[-1]["sum"] = float("nan")

        with patch.object(
            s, "async_add_external_statistics", side_effect=invalid_write
        ):
            with self.assertLogs(s._LOGGER, level="ERROR"):
                await self.importer.async_run(NOW)
        self.assertNotIn("last_success", self.persisted["accounts"]["A-TEST"])
        await self.importer.async_run(NOW)
        self.assertEqual(self.rows[-1]["sum"], 1)

    async def test_expected_fetch_failure_retains_data_without_traceback(self):
        self.api.fetch_electricity_measurements_range.side_effect = (
            s.SmartMeterFetchError("API rate limit")
        )
        with self.assertLogs(s._LOGGER, level="WARNING") as logs:
            await self.importer.async_run(NOW)
        self.assertIsNone(self.persisted)
        self.assertTrue(all(record.exc_info is None for record in logs.records))
        self.assertEqual(self.importer.status["phase"], "fetch_failed")

    async def test_missing_intervals_are_informational(self):
        with self.assertLogs(s._LOGGER, level="INFO") as logs:
            await self.importer.async_run(NOW)
        self.assertTrue(self.persisted["accounts"]["A-TEST"]["diagnostics"]["missing"])
        self.assertTrue(all(record.levelname == "INFO" for record in logs.records))

    async def test_history_and_readback_explicitly_request_kwh(self):
        await self.importer.async_run(NOW)
        self.recorder.async_block_till_done.assert_not_awaited()
        self.assertIsInstance(
            self.recorder.queue_task.call_args.args[0], s.SynchronizeTask
        )
        for call in self.recorder.async_add_executor_job.await_args_list:
            self.assertEqual(call.args[6], {"energy": "kWh"})

    async def test_intelligent_notifications_do_not_repeat_statistics_scans(self):
        with patch.object(s, "datetime", wraps=datetime) as clock:
            clock.now.return_value = NOW
            self.importer.schedule()
            await self.importer.task
            first = self.importer.task
            for minutes in (3, 6, 15, 29):
                clock.now.return_value = NOW + timedelta(minutes=minutes)
                self.importer.schedule()
                await self.importer.task
                self.assertIs(self.importer.task, first)
            self.assertEqual(
                self.api.fetch_electricity_measurements_range.call_count, 1
            )
            clock.now.return_value = NOW + timedelta(minutes=30)
            self.importer.schedule()
            await self.importer.task
            self.assertEqual(
                self.api.fetch_electricity_measurements_range.call_count, 2
            )

    async def test_live_correction_is_idempotent_and_keeps_older_rows(self):
        old_at = NOW - timedelta(days=100)
        old = dict(start=old_at, state=1, sum=100)
        self.rows = [old]
        await self.importer.async_run(NOW)
        self.api.fetch_electricity_measurements_range.return_value = quarters(
            values=("0", ".2", ".3", ".4")
        )
        await self.importer.async_run(NOW)
        self.assertEqual(self.rows[0], old)
        self.assertEqual(self.rows[-1]["state"], 0.9)
        self.assertEqual(self.rows[-1]["sum"], 100.9)
        before = deepcopy(self.rows)
        await self.importer.async_run(NOW)
        self.assertEqual(self.rows, before)

    async def test_storage_failure_retry_does_not_double_count(
        self,
    ):
        self.store.async_save.side_effect = OSError("disk unavailable")
        with self.assertLogs(s._LOGGER, level="ERROR"):
            await self.importer.async_run(NOW)
        self.assertEqual(self.importer.data, {"accounts": {}})
        self.assertEqual(len(self.rows), 0)
        self.store.async_save.side_effect = self.save
        await self.importer.async_run(NOW)
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(self.rows[0]["sum"], 1)

    async def test_final_checkpoint_failure_replays_original_batch(self):
        async def fail_final_save(data):
            if "pending_statistics" not in data["accounts"]["A-TEST"]:
                message = "disk unavailable"
                raise OSError(message)
            await self.save(data)

        self.store.async_save.side_effect = fail_final_save
        with self.assertLogs(s._LOGGER, level="ERROR"):
            await self.importer.async_run(NOW)
        self.assertEqual(self.rows[0]["sum"], 1)
        self.assertIn("pending_statistics", self.persisted["accounts"]["A-TEST"])
        self.store.async_save.side_effect = self.save
        await self.importer.async_run(NOW)
        self.assertEqual(self.rows[0]["sum"], 1)
        self.assertNotIn("pending_statistics", self.persisted["accounts"]["A-TEST"])

    async def test_boot_before_6_does_not_skip_daily_full_scan(self):
        await self.importer.async_run(NOW.replace(hour=2))
        await self.importer.async_run(NOW)
        self.assertEqual(
            self.api.fetch_electricity_measurements_range.call_args.args[2],
            r.window_bounds(NOW, "Europe/Berlin", 30)[0].isoformat(),
        )

    async def test_no_overlap_and_unload_cleanup(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow(*args):
            entered.set()
            await release.wait()
            return quarters()

        self.api.fetch_electricity_measurements_range.side_effect = slow
        self.importer.schedule()
        await entered.wait()
        first = self.importer.task
        self.importer.schedule()
        await self.importer.async_run(NOW)
        self.assertIs(self.importer.task, first)
        self.assertEqual(self.api.fetch_electricity_measurements_range.call_count, 1)
        self.importer.stop()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertIsNone(self.persisted)

    async def test_listener_registered_for_unload(self):
        entry = types.SimpleNamespace(entry_id="entry", async_on_unload=MagicMock())
        with patch.object(s.StatisticsReconciler, "schedule"):
            await s.async_setup_statistics_import(
                self.hass, self.api, self.coordinator, ["A-TEST"], entry
            )
        self.assertEqual(entry.async_on_unload.call_count, 2)

    async def test_diagnostics_exclude_credentials_and_raw_readings(self):
        self.hass.data = {s.DOMAIN: {"entry": {"statistics_reconciler": self.importer}}}
        entry = types.SimpleNamespace(entry_id="entry")
        await self.importer.async_run(NOW)
        result = await diagnostics.async_get_config_entry_diagnostics(self.hass, entry)
        self.assertEqual(result["reconciliation"]["status"]["phase"], "complete")
        self.assertNotIn("A-TEST", str(result))
        self.assertNotIn("readings", str(result))


class RealRecorderTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_correction_and_readback_with_real_recorder(self):
        with tempfile.TemporaryDirectory(prefix="octopus-recorder-test-") as directory:
            hass = HomeAssistant(directory)
            hass.config.time_zone = "Europe/Berlin"
            loader.async_setup(hass)
            frame.async_setup(hass)
            async_initialize_recorder(hass)
            hass.config_entries = ConfigEntries(hass, {})
            await hass.config_entries.async_initialize()
            try:
                self.assertTrue(
                    await async_setup_component(
                        hass,
                        "recorder",
                        {
                            "recorder": {
                                "db_url": f"sqlite:///{directory}/recorder.db",
                                "auto_purge": False,
                                "auto_repack": False,
                            }
                        },
                    )
                )
                await hass.async_start()
                api = types.SimpleNamespace(
                    fetch_electricity_measurements_range=AsyncMock(
                        return_value=quarters()
                    )
                )
                coordinator = types.SimpleNamespace(
                    data={"A-TEST": {"property_ids": ["p"], "malo_number": "malo"}}
                )
                importer = s.StatisticsReconciler(
                    hass, api, coordinator, ["A-TEST"], "test-entry"
                )
                await importer.async_run(NOW)
                self.assertEqual(importer.status["phase"], "complete")
                api.fetch_electricity_measurements_range.return_value = quarters(
                    values=("0", ".2", ".3", ".4")
                )
                recorder = s.get_instance(hass)
                with patch.object(
                    recorder, "async_get_commit_future", return_value=None
                ) as optimized_wait:
                    await importer.async_run(NOW)
                    optimized_wait.assert_not_called()
                self.assertEqual(importer.status["phase"], "complete")
                await importer.async_run(NOW)
                recorder = s.get_instance(hass)
                statistic_id = "octopus_germany:electricity_a_test_consumption"
                result = await recorder.async_add_executor_job(
                    s.statistics_during_period,
                    hass,
                    AT,
                    None,
                    {statistic_id},
                    "hour",
                    {"energy": "kWh"},
                    {"state", "sum"},
                )
                rows = result[statistic_id]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["state"], 0.9)
                self.assertEqual(rows[0]["sum"], 0.9)
                self.assertNotIn(
                    "pending_statistics", importer.data["accounts"]["A-TEST"]
                )
            finally:
                await hass.async_stop()
