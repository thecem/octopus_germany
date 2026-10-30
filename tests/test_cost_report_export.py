"""Regression tests for contract-specific offline export packages."""

# ruff: noqa: INP001, PLR2004, S101

import asyncio
import csv
import json
import tempfile
import threading
import unittest
from datetime import date
from decimal import Decimal
from math import isclose
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.service import _SERVICES_SCHEMA, _load_services_file
from homeassistant.util.yaml import load_yaml_dict

from custom_components.octopus_germany.const import DOMAIN
from custom_components.octopus_germany.cost_report import (
    agreement_key,
    build_daily_cost_report,
)
from custom_components.octopus_germany.cost_report_export import (
    prepare_package_readings,
    write_cost_workbook,
    write_measurements_csv,
)
from custom_components.octopus_germany.file_exports import (
    async_notify_export_package_ready,
)
from custom_components.octopus_germany.grid_fee_schedule import (
    contract_start_basis_period,
    load_grid_fee_schedule,
)
from custom_components.octopus_germany.service_handlers import async_register_services

DAY = date(2026, 5, 1)
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def test_action_descriptions_load_with_all_cost_fields() -> None:
    """Exercise HA's loader so invalid selectors cannot hide the action UI."""
    integration_path = (
        Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN
    )
    descriptions = _SERVICES_SCHEMA(
        load_yaml_dict(str(integration_path / "services.yaml"))
    )
    assert isinstance(descriptions, dict)
    cost_description = descriptions["export_cost_report"]
    assert isinstance(cost_description, dict)
    fields = cost_description["fields"]
    assert isinstance(fields, dict)
    assert {
        "account_number",
        "period",
        "year",
        "month",
        "format",
        "network_comparison",
        "standard_network_charge_ct_kwh",
        "contract_start_network_charge_ct_kwh",
        "module1_start_date",
        "module1_annual_credit_net_eur",
        "module3_start_date",
        "module3_rates_json",
        "vat_percent",
        "filename",
        "property_id",
    } == set(fields)
    assert (
        fields["standard_network_charge_ct_kwh"]["selector"]["number"]["step"] == "any"
    )
    assert not fields["contract_start_network_charge_ct_kwh"]["required"]
    assert "default" not in fields["contract_start_network_charge_ct_kwh"]
    assert {"csv", "package"} == set(fields["format"]["selector"]["select"]["options"])
    assert descriptions == _load_services_file(
        Mock(domain=DOMAIN, file_path=integration_path)
    )


def products(*, heat: bool = False) -> list[dict[str, Any]]:
    """Build sanitized contracts with genuine, independent tariff zones."""
    windows = (
        [
            ("Niedrig", "0.15", [("02:00:00", "06:00:00"), ("12:00:00", "16:00:00")]),
            (
                "Standard",
                "0.25",
                [
                    ("06:00:00", "12:00:00"),
                    ("16:00:00", "18:00:00"),
                    ("21:00:00", "02:00:00"),
                ],
            ),
            ("Hoch", "0.35", [("18:00:00", "21:00:00")]),
        ]
        if heat
        else [
            ("GO", "0.15", [("00:00:00", "05:00:00")]),
            ("STANDARD", "0.25", [("05:00:00", "00:00:00")]),
        ]
    )
    return [
        {
            "code": "EXAMPLE-HEAT" if heat else "EXAMPLE-GO",
            "name": "Example Heat" if heat else "Example GO",
            "type": "TimeOfUse",
            "validFrom": "2026-01-01T00:00:00+00:00",
            "prices": [
                {
                    "name": name,
                    "gross_eur_per_kwh": rate,
                    "vat_percent": "19",
                    "activation_rules": [
                        {"from_time": start, "to_time": end} for start, end in rules
                    ],
                }
                for name, rate, rules in windows
            ],
            "standing_charge_gross_rates": [{"gross_eur_per_month": "18"}],
        }
    ]


def grid_fees() -> dict[tuple[int, int], dict[str, Any]]:
    """Use network windows deliberately different from Heat price windows."""
    return {
        (2026, 5): {
            "module": "MODULE_3",
            "rates": [
                {
                    "rate_type": band,
                    "start_time": start,
                    "end_time": end,
                    "rate_eur_per_kwh": rate,
                }
                for band, start, end, rate in (
                    ("OFFPEAK", "00:00:00", "06:00:00", "0.02"),
                    ("STANDARD", "06:00:00", "17:00:00", "0.05"),
                    ("PEAK", "17:00:00", "22:00:00", "0.10"),
                    ("OFFPEAK", "22:00:00", "00:00:00", "0.02"),
                )
            ],
        }
    }


def readings(
    day: date = DAY, until: date | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Create a complete UTC quarter-hour fixture, respecting local DST."""
    expected, _ = prepare_package_readings({}, day, until or day, "Europe/Berlin")
    return {
        key: [{**item, "value": "1"} for item in items]
        for key, items in expected.items()
    }


def sheet_cells(path: Path, sheet_number: int) -> dict[str, ET.Element]:
    """Read cell XML without needing a spreadsheet application."""
    with ZipFile(path) as archive:
        root = ET.fromstring(  # noqa: S314 -- XML generated locally by the test.
            archive.read(f"xl/worksheets/sheet{sheet_number}.xml")
        )
    return {cell.attrib["r"]: cell for cell in root.findall(".//s:c", NS)}


def sheet_text(path: Path, sheet_number: int, reference: str) -> str:
    """Read a visible cell string, resolving shared-string references."""
    with ZipFile(path) as archive:
        cell = sheet_cells(path, sheet_number)[reference]
        value = cell.findtext("s:v", namespaces=NS) or ""
        if cell.attrib.get("t") != "s":
            return value
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))  # noqa: S314
    strings = ["".join(node.itertext()) for node in root.findall("s:si", NS)]
    return strings[int(value)]


def cached_number(cell: ET.Element) -> float:
    """Read an XLSX cached numeric value."""
    value = cell.find("s:v", NS)
    assert value is not None
    assert value.text is not None
    return float(value.text)


def invoice_labels(path: Path) -> dict[str, str]:
    """Locate invoice positions by their visible labels."""
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))  # noqa: S314
    strings = ["".join(node.itertext()) for node in root.findall("s:si", NS)]
    labels = {}
    for ref, cell in sheet_cells(path, 1).items():
        if ref.startswith("A") and cell.attrib.get("t") == "s":
            value = cell.findtext("s:v", namespaces=NS)
            assert value is not None
            labels[strings[int(value)]] = ref[1:]
    return labels


class CostExportTest(unittest.TestCase):
    """Check raw data, pricing parity, workbook formulas and DST coverage."""

    def build(  # noqa: PLR0913
        self,
        directory: str,
        *,
        heat: bool = False,
        comparison: str = "contract_start",
        current: Decimal | None = None,
        source: dict[str, list[dict[str, Any]]] | None = None,
        fees: dict[tuple[int, int], dict[str, Any]] | None = None,
        module3: date | None = DAY,
    ) -> tuple[
        Path,
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, list[dict[str, Any]]],
    ]:
        """Generate a one-day workbook through the shared pricing pipeline."""
        prepared, issues = prepare_package_readings(
            source if source is not None else readings(), DAY, DAY, "Europe/Berlin"
        )
        details = []
        daily = build_daily_cost_report(
            prepared,
            products(heat=heat),
            fees if fees is not None else grid_fees(),
            DAY,
            DAY,
            "Europe/Berlin",
            Decimal(7),
            DAY,
            Decimal(100),
            Decimal("0.19"),
            module3,
            interval_details=details,
        )
        for row in daily:
            if row["date"] in issues:
                row["status"] = f"incomplete: {issues[row['date']]}"
        path = Path(directory) / "example.xlsx"
        write_cost_workbook(
            path,
            prepared,
            details,
            daily,
            [],
            "Europe/Berlin",
            Decimal(7),
            Decimal(100),
            DAY,
            Decimal("0.19"),
            comparison,
            current,
            [],
        )
        return path, daily, details, prepared

    def test_workbook_matches_shared_daily_costs(self) -> None:
        """Keep cached workbook totals identical to the shared report."""
        with tempfile.TemporaryDirectory() as directory:
            path, daily, details, _ = self.build(directory)
            cells = sheet_cells(path, 8)
            assert isclose(
                cached_number(cells["K2"]),
                float(daily[0]["total_after_module1_gross_eur"]),
            )
            assert len(details) == 96
            assert cells["K2"].find("s:f", NS) is not None
            with ZipFile(path) as archive:
                assert archive.testzip() is None
                assert not any("externalLinks" in name for name in archive.namelist())
                assert not any("vbaProject" in name for name in archive.namelist())

    def test_invoice_network_quantities_prices_and_bold_totals(self) -> None:
        """Show positive gross reference/band prices and bold numeric totals."""
        for comparison, current, reference_rate in (
            ("contract_start", None, 8.33),
            ("current_year", Decimal(8), 9.52),
        ):
            with tempfile.TemporaryDirectory() as directory:
                path, daily, _, _ = self.build(
                    directory, comparison=comparison, current=current
                )
                cells = sheet_cells(path, 1)
                labels = invoice_labels(path)
                total = labels["GESAMTKOSTEN"]
                assert cached_number(cells[f"B{total}"]) == 96
                assert isclose(
                    cached_number(cells[f"D{total}"]),
                    float(daily[0]["total_after_module1_gross_eur"]),
                )
                reference = labels["Modul 3 Detail: Vergleichsnetz abziehen"]
                assert cached_number(cells[f"B{reference}"]) == 96
                assert isclose(cached_number(cells[f"C{reference}"]), reference_rate)
                assert cached_number(cells[f"D{reference}"]) < 0
                for band, quantity, price in (
                    ("NT (Niedertarif)", 32, 2.38),
                    ("ST (Standardtarif)", 44, 5.95),
                    ("HT (Hochtarif)", 20, 11.9),
                ):
                    row = labels[f"Netzentgelt {band} hinzufuegen"]
                    assert cached_number(cells[f"B{row}"]) == quantity
                    assert isclose(cached_number(cells[f"C{row}"]), price)
                    assert isclose(
                        cached_number(cells[f"D{row}"]), quantity * price / 100
                    )
                    assert cells[f"C{row}"].find("s:f", NS) is not None
                with ZipFile(path) as archive:
                    styles = ET.fromstring(archive.read("xl/styles.xml"))  # noqa: S314
                formats = styles.findall("s:cellXfs/s:xf", NS)
                fonts = styles.findall("s:fonts/s:font", NS)
                for column in ("B", "D"):
                    style = formats[int(cells[f"{column}{total}"].attrib["s"])]
                    assert (
                        fonts[int(style.attrib["fontId"])].find("s:b", NS) is not None
                    )

    def test_invoice_network_price_is_consumption_weighted(self) -> None:
        """Do not present one arbitrary price when an NT rate changes."""
        fees = grid_fees()
        fees[(2026, 5)]["rates"][-1]["rate_eur_per_kwh"] = "0.03"
        source = readings()
        # Four kWh per slot in the final eight slots, otherwise one kWh.
        for item in source[str(DAY)][-8:]:
            item["value"] = "4"
        with tempfile.TemporaryDirectory() as directory:
            path, _, _, _ = self.build(directory, source=source, fees=fees)
            cells = sheet_cells(path, 1)
            row = invoice_labels(path)["Netzentgelt NT (Niedertarif) hinzufuegen"]
            assert cached_number(cells[f"B{row}"]) == 56
            assert isclose(
                cached_number(cells[f"C{row}"]),
                (24 * 2 + 32 * 3) / 56 * 1.19,
            )

    def test_invoice_overall_quantity_and_cost_are_bold(self) -> None:
        """Keep the multi-month aggregate consistent with monthly totals."""
        start, end = date(2026, 5, 31), date(2026, 6, 1)
        source, issues = prepare_package_readings(
            readings(start, end), start, end, "Europe/Berlin"
        )
        assert not issues
        fees = {**grid_fees(), (2026, 6): grid_fees()[(2026, 5)]}
        details = []
        daily = build_daily_cost_report(
            source,
            products(),
            fees,
            start,
            end,
            "Europe/Berlin",
            Decimal(7),
            DAY,
            Decimal(100),
            Decimal("0.19"),
            DAY,
            interval_details=details,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "two-months.xlsx"
            write_cost_workbook(
                path,
                source,
                details,
                daily,
                [],
                "Europe/Berlin",
                Decimal(7),
                Decimal(100),
                DAY,
                Decimal("0.19"),
                "contract_start",
                None,
                [],
            )
            cells = sheet_cells(path, 1)
            row = invoice_labels(path)["GESAMTER BERICHTSZEITRAUM"]
            assert cached_number(cells[f"B{row}"]) == 192
            assert isclose(
                cached_number(cells[f"D{row}"]),
                sum(float(item["total_after_module1_gross_eur"]) for item in daily),
            )
            with ZipFile(path) as archive:
                styles = ET.fromstring(archive.read("xl/styles.xml"))  # noqa: S314
            formats = styles.findall("s:cellXfs/s:xf", NS)
            fonts = styles.findall("s:fonts/s:font", NS)
            for column in ("B", "D"):
                style = formats[int(cells[f"{column}{row}"].attrib["s"])]
                assert fonts[int(style.attrib["fontId"])].find("s:b", NS) is not None

    def test_invoice_zero_and_missing_values_do_not_show_false_prices(self) -> None:
        """Avoid division by zero and block reference prices for missing data."""
        for missing in (False, True):
            source = readings()
            for item in source[str(DAY)]:
                item["value"] = "0"
            if missing:
                source[str(DAY)].pop()
            with tempfile.TemporaryDirectory() as directory:
                path, _, _, _ = self.build(directory, source=source)
                cells = sheet_cells(path, 1)
                labels = invoice_labels(path)
                for label in (
                    "Modul 3 Detail: Vergleichsnetz abziehen",
                    "Netzentgelt NT (Niedertarif) hinzufuegen",
                    "Netzentgelt ST (Standardtarif) hinzufuegen",
                    "Netzentgelt HT (Hochtarif) hinzufuegen",
                ):
                    assert cells[f"C{labels[label]}"].findtext(
                        "s:v", namespaces=NS
                    ) in (None, "")
                if missing:
                    assert cells[f"B{labels['GESAMTKOSTEN']}"].findtext(
                        "s:v", namespaces=NS
                    ) in (None, "")

    def test_heat_has_three_contract_zones_not_go_plus_heat(self) -> None:
        """Select Heat zones without adding unrelated GO positions."""
        with tempfile.TemporaryDirectory() as directory:
            path, daily, details, _ = self.build(directory, heat=True)
            quantities = {
                name: sum(
                    item["quantity"] for item in details if item["tariff"] == name
                )
                for name in ("Niedrig", "Standard", "Hoch")
            }
            assert quantities == {"Niedrig": 32, "Standard": 52, "Hoch": 12}
            assert not any(item["tariff"] == "GO" for item in details)
            at_17 = next(item for item in details if item["local_start"].hour == 17)
            assert at_17["tariff"] == "Standard"
            assert at_17["band"] == "PEAK"
            assert isclose(
                cached_number(sheet_cells(path, 8)["K2"]),
                float(daily[0]["total_after_module1_gross_eur"]),
            )

    def test_comparison_changes_saving_not_final_cost(self) -> None:
        """Change the savings comparison without changing actual costs."""
        with tempfile.TemporaryDirectory() as directory:
            path, _, _, _ = self.build(directory)
            start = sheet_cells(path, 8)
            total = cached_number(start["K2"])
            saving = cached_number(start["H2"])
            path, _, _, _ = self.build(
                directory, comparison="current_year", current=Decimal(8)
            )
            current = sheet_cells(path, 8)
            assert isclose(cached_number(current["K2"]), total)
            assert cached_number(current["H2"]) > saving

    def test_non_module3_year_change_is_not_module3_saving(self) -> None:
        """Do not attribute ordinary annual network changes to Module 3."""
        fees = {
            (2026, 5): {
                "module": "MODULE_1",
                "rates": [
                    {
                        "rate_type": "STANDARD",
                        "start_time": "00:00:00",
                        "end_time": "00:00:00",
                        "rate_eur_per_kwh": "0.08",
                    },
                ],
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path, daily, _, _ = self.build(directory, fees=fees, module3=None)
            cells = sheet_cells(path, 8)
            assert isclose(cached_number(cells["H2"]), 0, abs_tol=1e-9)
            assert cached_number(cells["E2"]) > 0
            assert isclose(
                cached_number(cells["K2"]),
                float(daily[0]["total_after_module1_gross_eur"]),
            )

    def test_variable_st_is_not_a_normal_annual_fee(self) -> None:
        """Require a normal rate before Module 3 when the API only has bands."""
        prepared, _ = prepare_package_readings(readings(), DAY, DAY, "Europe/Berlin")
        common = (
            prepared,
            products(),
            grid_fees(),
            DAY,
            DAY,
            "Europe/Berlin",
            Decimal(7),
            None,
            Decimal(0),
            Decimal("0.19"),
        )
        legacy = build_daily_cost_report(*common, module3_start_date=date(2026, 6, 1))
        assert legacy[0]["status"] == "complete"
        strict = build_daily_cost_report(
            *common,
            module3_start_date=date(2026, 6, 1),
            strict_standard_grid_fee=True,
        )
        assert strict[0]["status"] == "incomplete: network rate missing"
        details = []
        manual = build_daily_cost_report(
            *common,
            module3_start_date=date(2026, 6, 1),
            strict_standard_grid_fee=True,
            normal_network_charge_ct_kwh=Decimal(8),
            interval_details=details,
        )
        assert manual[0]["status"] == "complete"
        assert all(item["network_rate"] == Decimal("0.08") for item in details)

    def test_zero_vat_fallback_is_not_replaced_with_nineteen_percent(self) -> None:
        """Honor an explicit zero VAT input for the Module 1 annual credit."""
        daily = build_daily_cost_report(
            readings(),
            products(),
            grid_fees(),
            DAY,
            DAY,
            "Europe/Berlin",
            Decimal(7),
            DAY,
            Decimal(100),
            Decimal(0),
        )
        assert daily[0]["module1_credit_gross_eur"] == Decimal(100) / 365

    def test_contract_switch_uses_both_valid_contracts(self) -> None:
        """Apply the valid contract independently on both sides of a change."""
        go = products()[0]
        heat = products(heat=True)[0]
        go["validTo"] = "2026-05-01T10:00:00+00:00"
        heat["validFrom"] = go["validTo"]
        with tempfile.TemporaryDirectory() as directory:
            with patch(f"{__name__}.products", return_value=[go, heat]):
                path, daily, details, _ = self.build(directory)
            assert {item["agreement"] for item in details} == {
                "Example GO",
                "Example Heat",
            }
            assert all(item["agreement"] == "Example GO" for item in details[:48])
            assert all(item["agreement"] == "Example Heat" for item in details[48:])
            assert isclose(
                cached_number(sheet_cells(path, 8)["K2"]),
                float(daily[0]["total_after_module1_gross_eur"]),
            )

    def test_contract_baselines_follow_each_agreement_and_explicit_zero_wins(
        self,
    ) -> None:
        """Resolve per-agreement baselines while preserving explicit zero."""
        go = products()[0]
        heat = products(heat=True)[0]
        go["validTo"] = "2026-05-01T10:00:00+00:00"
        heat["validFrom"] = go["validTo"]
        agreements = [go, heat]
        baselines = {
            agreement_key(go): Decimal("7.65"),
            agreement_key(heat): Decimal("5.48"),
        }
        details: list[dict[str, Any]] = []
        daily = build_daily_cost_report(
            readings(),
            agreements,
            grid_fees(),
            DAY,
            DAY,
            "Europe/Berlin",
            None,
            DAY,
            Decimal(100),
            Decimal("0.19"),
            DAY,
            interval_details=details,
            contract_start_baselines=baselines,
        )
        assert [
            item["contract_start_network_charge_ct_kwh"] for item in details[:48]
        ] == [Decimal("7.65")] * 48
        assert [
            item["contract_start_network_charge_ct_kwh"] for item in details[48:]
        ] == [Decimal("5.48")] * 48
        assert daily[0]["status"] == "complete"

        explicit_details: list[dict[str, Any]] = []
        build_daily_cost_report(
            readings(),
            agreements,
            grid_fees(),
            DAY,
            DAY,
            "Europe/Berlin",
            Decimal(0),
            DAY,
            Decimal(100),
            Decimal("0.19"),
            DAY,
            interval_details=explicit_details,
            contract_start_baselines=baselines,
        )
        assert all(
            item["contract_start_network_charge_ct_kwh"] == 0
            and item["contract_start_baseline_source"] == "explicit"
            for item in explicit_details
        )

        incomplete = build_daily_cost_report(
            readings(),
            agreements,
            grid_fees(),
            DAY,
            DAY,
            "Europe/Berlin",
            None,
            DAY,
            Decimal(100),
            Decimal("0.19"),
            DAY,
            contract_start_baselines={agreement_key(go): Decimal("7.65")},
        )
        assert incomplete[0]["status"] == (
            "incomplete: contract-start network charge missing"
        )
        assert incomplete[0]["contract_start_baseline_missing_kwh"] > 0

    def test_missing_values_are_blank_and_block_total(self) -> None:
        """Keep missing inputs blank and refuse an incomplete invoice."""
        source = readings()
        source[str(DAY)].pop()
        with tempfile.TemporaryDirectory() as directory:
            path, _, _, prepared = self.build(directory, source=source)
            cells = sheet_cells(path, 8)
            value = cells["K2"].find("s:v", NS)
            assert value is not None
            assert value.text is None
            csv_path = Path(directory) / "readings.csv"
            write_measurements_csv(
                csv_path, prepared, "Europe/Berlin", {str(DAY): "missing"}
            )
            with csv_path.open(encoding="utf-8-sig") as stream:
                rows = list(csv.DictReader(stream, delimiter=";"))
            assert rows[0]["23:45"] == ""
            assert rows[0]["00:00"] == "1"

    def test_exact_csv_quantities_and_zero_are_preserved(self) -> None:
        """Keep full source precision and genuine zero measurements."""
        source = readings()
        source[str(DAY)][0]["value"] = "0.123456789"
        source[str(DAY)][1]["value"] = "0"
        prepared, issues = prepare_package_readings(source, DAY, DAY, "Europe/Berlin")
        assert not issues
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "readings.csv"
            write_measurements_csv(path, prepared, "Europe/Berlin", issues)
            with path.open(encoding="utf-8-sig") as stream:
                row = next(csv.DictReader(stream, delimiter=";"))
            assert row["00:00"] == "0,123456789"
            assert row["00:15"] == "0"

    def test_dst_and_duplicate_invalid_readings(self) -> None:
        """Validate DST coverage and reject invalid or duplicate readings."""
        for day, count in (
            (date(2026, 3, 29), 92),
            (DAY, 96),
            (date(2026, 10, 25), 100),
        ):
            prepared, issues = prepare_package_readings(
                readings(day), day, day, "Europe/Berlin"
            )
            assert len(prepared[str(day)]) == count
            assert not issues
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "readings.csv"
                write_measurements_csv(path, prepared, "Europe/Berlin", issues)
                with path.open(encoding="utf-8-sig") as stream:
                    row = next(csv.DictReader(stream, delimiter=";"))
                if count == 100:
                    assert row["02:00 (2)"] == "1"
                if count == 92:
                    assert row["02:00"] == ""
        for value in ("NaN", "-1", "invalid"):
            source = readings()
            source[str(DAY)][0]["value"] = value
            source[str(DAY)].append(source[str(DAY)][1])
            _, issues = prepare_package_readings(source, DAY, DAY, "Europe/Berlin")
            assert "invalid reading" in issues[str(DAY)]
            assert "duplicate reading" in issues[str(DAY)]
        source = readings()
        source[str(DAY)][0]["end_time"] = "2026-04-30T22:30:00+00:00"
        _, issues = prepare_package_readings(source, DAY, DAY, "Europe/Berlin")
        assert "invalid reading" in issues[str(DAY)]

    def test_spreadsheet_formula_injection_is_disabled(self) -> None:
        """Write formula-shaped API labels as ordinary text."""
        with tempfile.TemporaryDirectory() as directory:
            path, _, _, _ = self.build(directory)
            # All API labels are written as strings, even when they look like formulas.
            with patch(
                f"{__name__}.products",
                return_value=[
                    {
                        **products()[0],
                        "name": "=1+1",
                    }
                ],
            ):
                path, _, _, _ = self.build(directory)
            cell = sheet_cells(path, 4)["B2"]
            assert cell.attrib["t"] == "s"
            assert cell.find("s:f", NS) is None


@pytest.mark.parametrize(
    ("schedule_credit", "action_credit", "expected_credit"),
    [
        (365, None, "365"),
        (365, "", "365"),
        (365, 730, "730"),
        (365, 0, "0"),
        (0, None, "0"),
        (None, None, None),
        (None, "", None),
        (None, 730, "730"),
    ],
)
def test_schedule_credit_and_date_fallbacks(
    tmp_path: Path,
    schedule_credit: int | None,
    action_credit: int | str | None,
    expected_credit: str | None,
) -> None:
    """Resolve optional schedule inputs without replacing explicit action values."""

    async def exercise() -> None:
        hass = Mock()
        hass.config.time_zone = "Europe/Berlin"
        hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
        hass.async_add_executor_job = AsyncMock(side_effect=asyncio.to_thread)
        schedule_path = tmp_path / "octopus_germany/grid_fee_schedules.json"
        schedule_path.parent.mkdir()
        entry = {
            "year": 2026,
            "module1_start_date": "2026-05-16",
            "module3_start_date": "2026-05-17",
            "hourly_rate_types": [None] * 24,
            "rates_net_ct_per_kwh": {},
        }
        if schedule_credit is not None:
            entry["module1_credit_net_eur"] = schedule_credit
        schedule_path.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "grid_operators": [
                        {"grid_operator_code": "EXAMPLE", "years": [entry]}
                    ],
                }
            ),
            encoding="utf-8",
        )
        client = Mock()
        client.fetch_electricity_measurements_range = AsyncMock(
            return_value=[
                item
                for items in readings(DAY, date(2026, 5, 31)).values()
                for item in items
            ]
        )
        coordinator = Mock(
            data={
                "A-EXAMPLE": {
                    "products": products(),
                    "property_ids": ["EXAMPLE"],
                    "malo_number": "EXAMPLE",
                    "grid_operator_code": "EXAMPLE",
                }
            }
        )
        await async_register_services(hass, Mock(), Mock(), Mock(), None)
        handler = next(
            call.args[2]
            for call in hass.services.async_register.call_args_list
            if call.args[1] == "export_cost_report"
        )
        fields = {
            "account_number": "A-EXAMPLE",
            "period": "month",
            "year": 2026,
            "month": 5,
            "module3_rates_json": [
                {
                    "rate_type": "STANDARD",
                    "start_time": "00:00:00",
                    "end_time": "00:00:00",
                    "rate_cents_per_kwh": 5,
                }
            ],
        }
        if action_credit is not None:
            fields["module1_annual_credit_net_eur"] = action_credit
        with (
            patch(
                "custom_components.octopus_germany.service_handlers._resolve_account_context",
                return_value=(coordinator, client),
            ),
            patch(
                "custom_components.octopus_germany.service_handlers._fetch_grid_fee_schedules",
                new=AsyncMock(return_value=grid_fees()[(2026, 5)]),
            ),
            patch(
                "custom_components.octopus_germany.service_handlers.async_notify_export_ready",
                new=AsyncMock(return_value="/download/cost.csv"),
            ),
        ):
            for explicit_dates in (False, True):
                if explicit_dates:
                    fields["module1_start_date"] = "2026-05-20"
                    fields["module3_start_date"] = "2026-05-21"
                result = await handler(
                    ServiceCall(hass, DOMAIN, "export_cost_report", fields)
                )
                contents = await asyncio.to_thread(
                    Path(result["output_file"]).read_text, encoding="utf-8-sig"
                )
                rows = list(csv.DictReader(contents.splitlines(), delimiter=";"))
                parameters = json.loads(
                    next(
                        row["basis_value"]
                        for row in rows
                        if row["basis_key"] == "calculation_parameters"
                    )
                )
                assert parameters["module1_annual_credit_net_eur"] == expected_credit
                assert parameters["module1_effective_date"] == (
                    "2026-05-20" if explicit_dates else "2026-05-16"
                )
                assert parameters["module3_effective_date"] == (
                    "2026-05-21" if explicit_dates else "2026-05-17"
                )
                day = next(row for row in rows if row["date"] == "2026-05-20")
                assert Decimal(day["module1_credit_net_eur"].replace(",", ".")) == (
                    Decimal(expected_credit) / 365
                    if expected_credit is not None
                    else Decimal(0)
                )
                before = next(row for row in rows if row["date"] == "2026-05-15")
                assert Decimal(before["module1_credit_net_eur"].replace(",", ".")) == 0
                if expected_credit is None:
                    assert any(
                        "no credit is applied" in warning
                        for warning in result["warnings"]
                    )

    asyncio.run(exercise())


@pytest.mark.parametrize("field", ["module1_start_date", "module3_start_date"])
def test_schedule_dates_are_optional_and_validated(tmp_path: Path, field: str) -> None:
    """Keep unknown dates and credit unset and reject malformed dates."""
    entry = {
        "year": 2026,
        "hourly_rate_types": [None] * 24,
        "rates_net_ct_per_kwh": {},
    }
    document = {
        "format_version": 1,
        "grid_operators": [{"grid_operator_code": "EXAMPLE", "years": [entry]}],
    }
    path = tmp_path / "grid_fee_schedules.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    loaded = load_grid_fee_schedule(path, "EXAMPLE", 2026, "Europe/Berlin")
    assert loaded is not None
    assert loaded["module1_credit_net_eur"] is None
    assert loaded["module1_start_date"] is None
    assert loaded["module3_start_date"] is None
    for value in ("2026-02-30", "not-a-date"):
        entry[field] = value
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ValueError, match=field):
            load_grid_fee_schedule(path, "EXAMPLE", 2026, "Europe/Berlin")


def test_contract_start_basis_period_uses_inclusive_exclusive_boundaries() -> None:
    """Select the basis rate only inside one unique dated schedule period."""
    schedule = {
        "schedules": [
            {
                "valid_from": "2024-01-01",
                "valid_to": "2024-07-01",
                "basis_rate_net_ct_per_kwh": Decimal("7.65"),
            },
            {
                "valid_from": "2024-07-01",
                "valid_to": "2025-01-01",
                "basis_rate_net_ct_per_kwh": Decimal("6.64"),
            },
        ]
    }

    assert contract_start_basis_period(schedule, date(2024, 1, 1))[
        "basis_rate_net_ct_per_kwh"
    ] == Decimal("7.65")
    assert contract_start_basis_period(schedule, date(2024, 6, 30))[
        "basis_rate_net_ct_per_kwh"
    ] == Decimal("7.65")
    assert contract_start_basis_period(schedule, date(2024, 7, 1))[
        "basis_rate_net_ct_per_kwh"
    ] == Decimal("6.64")
    assert contract_start_basis_period(schedule, date(2025, 1, 1)) is None
    schedule["schedules"][1]["basis_rate_net_ct_per_kwh"] = None
    assert contract_start_basis_period(schedule, date(2024, 7, 1)) is None
    schedule["schedules"][1]["valid_from"] = "2024-06-30"
    with pytest.raises(ValueError, match="multiple"):
        contract_start_basis_period(schedule, date(2024, 6, 30))


class ExportPackageServiceTest(unittest.TestCase):
    """Exercise registration, one-fetch package output and download response."""

    def test_package_fetches_once_and_retains_default_csv(self) -> None:  # noqa: PLR0915
        """Persist only XLSX/raw CSV while retaining the separate cost CSV mode."""

        async def exercise(directory: str) -> None:  # noqa: PLR0915
            hass = Mock()
            hass.config.time_zone = "Europe/Berlin"
            hass.config.path = lambda *parts: str(Path(directory).joinpath(*parts))
            hass.async_add_executor_job = AsyncMock(side_effect=asyncio.to_thread)
            schedule_path = Path(directory) / "octopus_germany/grid_fee_schedules.json"
            await asyncio.to_thread(schedule_path.parent.mkdir, parents=True)
            schedule_document = {
                "format_version": 1,
                "grid_operators": [
                    {
                        "grid_operator_code": "EXAMPLE",
                        "years": [
                            {
                                "year": 2024,
                                "schedules": [
                                    {
                                        "valid_from": "2024-01-01",
                                        "valid_to": "2025-01-01",
                                        "basis_rate_net_ct_per_kwh": 7.65,
                                        "hourly_rate_types": [None] * 24,
                                        "rates_net_ct_per_kwh": {},
                                    }
                                ],
                            },
                            {
                                "year": 2026,
                                "schedules": [
                                    {
                                        "valid_from": "2026-01-01",
                                        "valid_to": "2027-01-01",
                                        "basis_rate_net_ct_per_kwh": 5.48,
                                        "hourly_rate_types": [None] * 24,
                                        "rates_net_ct_per_kwh": {},
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
            await asyncio.to_thread(
                schedule_path.write_text,
                json.dumps(schedule_document),
                encoding="utf-8",
            )
            event_loop_thread = threading.get_ident()
            original_open = Path.open
            original_is_file = Path.is_file
            schedule_io = []

            def checked_open(path: Path, *args: Any, **kwargs: Any) -> Any:
                if path == schedule_path:
                    assert threading.get_ident() != event_loop_thread
                    schedule_io.append("open")
                return original_open(path, *args, **kwargs)

            def checked_is_file(path: Path) -> bool:
                if path == schedule_path:
                    assert threading.get_ident() != event_loop_thread
                    schedule_io.append("is_file")
                return original_is_file(path)

            client = Mock()
            client.fetch_electricity_measurements_range = AsyncMock(
                return_value=[
                    item
                    for items in readings(DAY, date(2026, 5, 31)).values()
                    for item in items
                ]
            )
            coordinator = Mock(
                data={
                    "A-EXAMPLE": {
                        "products": [
                            {
                                **products()[0],
                                "validFrom": "2024-01-01T00:00:00+00:00",
                            }
                        ],
                        "property_ids": ["EXAMPLE"],
                        "malo_number": "EXAMPLE",
                        "grid_operator_code": "EXAMPLE",
                    }
                }
            )
            await async_register_services(hass, Mock(), Mock(), Mock(), None)
            handler = next(
                call.args[2]
                for call in hass.services.async_register.call_args_list
                if call.args[1] == "export_cost_report"
            )
            fields = {
                "account_number": "A-EXAMPLE",
                "period": "month",
                "year": 2026,
                "month": 5,
                "format": "package",
                "module3_start_date": "2026-05-01",
            }
            with (
                patch.object(Path, "open", checked_open),
                patch.object(Path, "is_file", checked_is_file),
                patch(
                    "custom_components.octopus_germany.service_handlers._resolve_account_context",
                    return_value=(coordinator, client),
                ),
                patch(
                    "custom_components.octopus_germany.service_handlers._fetch_grid_fee_schedules",
                    new=AsyncMock(return_value=grid_fees()[(2026, 5)]),
                ),
                patch(
                    "custom_components.octopus_germany.service_handlers.async_notify_export_package_ready",
                    new=AsyncMock(
                        side_effect=lambda _hass, names, _description: {
                            name: f"/download/{name}" for name in names
                        }
                    ),
                ),
                patch(
                    "custom_components.octopus_germany.service_handlers.async_notify_export_ready",
                    new=AsyncMock(return_value="/download/cost.csv"),
                ) as single,
            ):
                result = await handler(
                    ServiceCall(hass, DOMAIN, "export_cost_report", fields)
                )
                assert result["incomplete_days"] == 0
                assert result["grid_fee_schedule_file_status"] == "matched"
                assert schedule_io == ["is_file", "open", "is_file", "open"]
                annual_input = sheet_cells(Path(result["output_file"]), 2)["B5"]
                assert annual_input.find("s:v", NS) is None
                inputs = sheet_cells(Path(result["output_file"]), 2)
                assert cached_number(inputs["F2"]) == 7.65
                assert sheet_text(Path(result["output_file"]), 2, "H2") == "2024-01-01"
                assert sheet_text(Path(result["output_file"]), 2, "I2") == "2025-01-01"
                assert cached_number(inputs["N2"]) == 7.65
                assert cached_number(inputs["N3"]) == 5.48
                assert len(result["files"]) == 2
                assert {item["type"] for item in result["files"]} == {
                    "xlsx",
                    "measurements_csv",
                }
                assert result["output_file"].endswith(".xlsx")
                assert result["download_url"] == result["files"][0]["download_url"]
                assert {
                    path.name for path in Path(result["output_file"]).parent.iterdir()
                } == {Path(item["output_file"]).name for item in result["files"]}
                for item in result["files"]:
                    assert await asyncio.to_thread(Path(item["output_file"]).is_file)
                assert not single.called
                fields["contract_start_network_charge_ct_kwh"] = 0
                explicit = await handler(
                    ServiceCall(hass, DOMAIN, "export_cost_report", fields)
                )
                interval_cells = sheet_cells(Path(explicit["output_file"]), 7)
                assert cached_number(interval_cells["T2"]) == 0
                assert sheet_text(Path(explicit["output_file"]), 7, "U2") == "explicit"
                fields.pop("format")
                fields.pop("contract_start_network_charge_ct_kwh")
                csv_result = await handler(
                    ServiceCall(hass, DOMAIN, "export_cost_report", fields)
                )
                with Path(csv_result["output_file"]).open(
                    encoding="utf-8-sig"
                ) as stream:
                    csv_rows = list(csv.DictReader(stream, delimiter=";"))
                resolution = json.loads(
                    next(
                        row["basis_value"]
                        for row in csv_rows
                        if row["basis_key"] == "contract_start_baseline_resolution"
                    )
                )
                assert resolution[0]["contract_start_date"] == "2024-01-01"
                assert resolution[0]["value"] == "7.65"
                assert resolution[0]["valid_from"] == "2024-01-01"
                assert resolution[0]["valid_to"] == "2025-01-01"
                single.assert_awaited_once()
                client.fetch_electricity_measurements_range.assert_awaited()
                await asyncio.to_thread(schedule_path.unlink)
                default = await handler(
                    ServiceCall(hass, DOMAIN, "export_cost_report", fields)
                )
                assert "files" not in default
                assert default["output_file"].endswith(".csv")
                assert (
                    Path(default["output_file"]).stem
                    == Path(result["output_file"]).stem
                )
                assert default["grid_fee_schedule_file_status"] == "missing"
                assert any(
                    "contract-start" in warning for warning in default["warnings"]
                )
                assert single.await_count == 2
                for document, expected_status in (
                    ("{", "invalid"),
                    (
                        json.dumps({"format_version": 1, "grid_operators": []}),
                        "unmatched",
                    ),
                ):
                    await asyncio.to_thread(
                        schedule_path.write_text, document, encoding="utf-8"
                    )
                    response = await handler(
                        ServiceCall(hass, DOMAIN, "export_cost_report", fields)
                    )
                    assert response["grid_fee_schedule_file_status"] == expected_status
                fields["format"] = "package"
                fields["network_comparison"] = "current_year"
                with pytest.raises(ServiceValidationError):
                    await handler(
                        ServiceCall(hass, DOMAIN, "export_cost_report", fields)
                    )
                fields["network_comparison"] = "contract_start"
                with (
                    patch(
                        "custom_components.octopus_germany.service_handlers.write_cost_workbook",
                        side_effect=OSError("disk unavailable"),
                    ),
                    pytest.raises(HomeAssistantError),
                ):
                    await handler(
                        ServiceCall(hass, DOMAIN, "export_cost_report", fields)
                    )
                assert not any(
                    path.is_dir()
                    for path in Path(result["output_file"]).parent.iterdir()
                )

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(directory))

    def test_one_notification_has_two_scoped_links(self) -> None:
        """Create one notification while keeping separate filename tokens."""

        async def exercise() -> None:
            view = Mock(
                async_issue_download_token=AsyncMock(side_effect=["one", "two"])
            )
            with (
                patch(
                    "custom_components.octopus_germany.file_exports.async_register_export_download_view",
                    new=AsyncMock(return_value=view),
                ),
                patch(
                    "custom_components.octopus_germany.file_exports.persistent_notification.async_create"
                ) as notify,
            ):
                result = await async_notify_export_package_ready(
                    Mock(), ["cost.xlsx", "raw.csv"], "Example"
                )
                assert len(result) == 2
                assert result["cost.xlsx"] != result["raw.csv"]
                assert view.async_issue_download_token.await_count == 2
                notify.assert_called_once()
                assert notify.call_args.args[1].count("<a ") == 2

        asyncio.run(exercise())
