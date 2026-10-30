"""Offline cost workbooks and quarter-hour CSVs from one report snapshot."""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

if TYPE_CHECKING:
    from pathlib import Path

    from xlsxwriter.format import Format
    from xlsxwriter.worksheet import Worksheet

_INTERVAL = timedelta(minutes=15)
_ZERO = Decimal(0)
_QUANTITY_LAST_COLUMN = 2


def _parse_reading(
    reading: dict[str, Any], expected: set[datetime]
) -> tuple[datetime, Decimal]:
    """Require an expected UTC slot and a finite nonnegative quarter-hour value."""
    at = datetime.fromisoformat(reading["start_time"])
    at = at.replace(tzinfo=UTC) if at.tzinfo is None else at
    at = at.astimezone(UTC)
    quantity = Decimal(str(reading["value"]))
    if not quantity.is_finite() or quantity < 0 or at not in expected:
        msg = "Invalid quarter-hour measurement"
        raise ValueError(msg)
    if reading.get("end_time"):
        until = datetime.fromisoformat(reading["end_time"])
        until = until.replace(tzinfo=UTC) if until.tzinfo is None else until
        if until.astimezone(UTC) - at != _INTERVAL:
            msg = "Measurement duration is not fifteen minutes"
            raise ValueError(msg)
    return at, quantity


def prepare_package_readings(
    readings_by_date: dict[str, list[dict[str, Any]]],
    start_date: date,
    end_date: date,
    timezone: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Validate coverage against UTC slots, preserving missing values as missing."""
    zone = ZoneInfo(timezone)
    result: dict[str, list[dict[str, Any]]] = {}
    issues: dict[str, str] = {}
    day = start_date
    while day <= end_date:
        key = day.isoformat()
        start = datetime.combine(day, time.min, zone).astimezone(UTC)
        end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC)
        expected = []
        instant = start
        while instant < end:
            expected.append(instant)
            instant += _INTERVAL
        indexed: dict[datetime, dict[str, Any]] = {}
        errors = []
        expected_set = set(expected)
        for reading in readings_by_date.get(key, []):
            try:
                at, quantity = _parse_reading(reading, expected_set)
            except KeyError, TypeError, ValueError, InvalidOperation:
                errors.append("invalid reading")
                continue
            if at in indexed:
                errors.append("duplicate reading")
                continue
            indexed[at] = {**reading, "value": quantity}
        missing = len(expected) - len(indexed)
        if missing:
            errors.append(f"{missing} of {len(expected)} intervals missing")
        if errors:
            issues[key] = "; ".join(sorted(set(errors)))
        result[key] = [
            {
                **indexed.get(at, {}),
                "start_time": at.isoformat(),
                # Select prices for missing slots without exporting a zero measurement.
                "value": indexed[at]["value"] if at in indexed else _ZERO,
                "reading_status": "OK" if at in indexed else "MISSING",
            }
            for at in expected
        ]
        day += timedelta(days=1)
    return result, issues


def measurement_columns(
    readings: list[dict[str, Any]], timezone: str
) -> list[tuple[str, dict[str, Any]]]:
    """Map repeated local times to explicit second-occurrence columns."""
    zone = ZoneInfo(timezone)
    seen: set[str] = set()
    result = []
    for reading in readings:
        local = datetime.fromisoformat(reading["start_time"]).astimezone(zone)
        label = local.strftime("%H:%M")
        if label in seen:
            label += " (2)"
        seen.add(local.strftime("%H:%M"))
        result.append((label, reading))
    return result


def write_measurements_csv(
    path: Path,
    readings_by_date: dict[str, list[dict[str, Any]]],
    timezone: str,
    issues: dict[str, str],
) -> None:
    """Write exact quantities, 96 regular slots and explicit autumn extras."""
    regular = [f"{slot // 4:02}:{slot % 4 * 15:02}" for slot in range(96)]
    extra = sorted(
        {
            label
            for readings in readings_by_date.values()
            for label, _reading in measurement_columns(readings, timezone)
            if label not in regular
        }
    )
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["date", *regular, *extra, "expected_intervals", "status"])
        for day, readings in readings_by_date.items():
            values = {
                label: format(reading["value"], "f").replace(".", ",")
                if reading["reading_status"] == "OK"
                else ""
                for label, reading in measurement_columns(readings, timezone)
            }
            writer.writerow(
                [
                    day,
                    *(values.get(label, "") for label in [*regular, *extra]),
                    len(readings),
                    issues.get(day, "complete"),
                ]
            )


def write_cost_workbook(  # noqa: C901, PLR0912, PLR0913, PLR0915
    path: Path,
    readings_by_date: dict[str, list[dict[str, Any]]],
    details: list[dict[str, Any]],
    daily_rows: list[dict[str, Any]],
    basis_rows: list[dict[str, Any]],
    timezone: str,
    baseline: Decimal,
    module1_annual: Decimal | None,
    module1_start: date | None,
    vat: Decimal,
    comparison: str,
    current_network: Decimal | None,
    warnings: list[str],
) -> None:
    """Write contract-specific invoice lines and editable offline Excel formulas."""
    by_instant = {item["start"]: item for item in details}
    tariff_keys = {
        (item["agreement"], item["tariff"], item["gross_rate"], item["vat"])
        for item in details
    }
    tariffs = sorted(tariff_keys, key=str)
    networks = sorted(
        {
            (item["band"], item["network_rate"], item["network_source"])
            for item in details
        },
        key=str,
    )
    tariff_indices = {key: index + 1 for index, key in enumerate(tariffs)}
    network_indices = {key: index + 1 for index, key in enumerate(networks)}
    standing_rates = sorted(
        {
            (item["tariff_agreement"], item["standing_charge_gross_eur"])
            for item in daily_rows
            if item["standing_charge_gross_eur"] is not None
        },
        key=str,
    )
    standing_indices = {key: index + 2 for index, key in enumerate(standing_rates)}
    with xlsxwriter.Workbook(
        path, {"strings_to_formulas": False, "strings_to_urls": False}
    ) as book:
        book.set_calc_mode("auto")
        book.set_properties(
            {"title": "Octopus Stromkosten", "author": "Octopus Germany"}
        )
        header = book.add_format(
            {
                "bold": True,
                "bg_color": "#153E56",
                "font_color": "#FFFFFF",
                "text_wrap": True,
            }
        )
        note = book.add_format({"text_wrap": True, "valign": "top"})
        warning_fmt = book.add_format({"text_wrap": True, "bg_color": "#FFF2CC"})
        absent_fmt = book.add_format({"bg_color": "#E7E7E7", "font_color": "#666666"})
        input_fmt = book.add_format({"bg_color": "#E5F3FF", "num_format": "0.000000"})
        number_fmt = book.add_format({"num_format": "0.000000"})
        money = book.add_format({"num_format": '#,##0.00 "EUR"'})
        quantity_fmt = book.add_format({"num_format": '0.000 "kWh"'})
        total_money = book.add_format({"bold": True, "num_format": '#,##0.00 "EUR"'})
        total_quantity = book.add_format({"bold": True, "num_format": '0.000 "kWh"'})
        date_fmt = book.add_format({"num_format": "dd.mm.yyyy"})
        date_input_fmt = book.add_format(
            {"num_format": "dd.mm.yyyy", "bg_color": "#E5F3FF"}
        )
        title = book.add_format({"bold": True, "font_size": 18})
        sheets = {
            name: book.add_worksheet(name)
            for name in (
                "Rechnung",
                "Eingaben",
                "Messwerte",
                "Tarifpreise",
                "Grundpreise",
                "Netzpreise",
                "Intervalle",
                "Tageswerte",
                "Basis",
            )
        }
        for sheet in sheets.values():
            sheet.freeze_panes(1, 1)
            sheet.set_column(0, 0, 24)
            sheet.set_column(1, 25, 20)

        def formula(  # noqa: PLR0913
            sheet: Worksheet,
            row: int,
            col: int,
            text: str,
            cached: Any = 0,
            fmt: Format = money,
        ) -> None:
            value = float(cached) if isinstance(cached, Decimal) else cached
            # XlsxWriter infers int from its default, but supports float/string caches.
            sheet.write_formula(row, col, text, fmt, value)  # pyright: ignore[reportArgumentType]

        def heading(sheet: Worksheet, labels: list[str]) -> None:
            sheet.write_row(0, 0, labels, header)
            sheet.set_row(0, 42)

        inputs = sheets["Eingaben"]
        heading(inputs, ["Eingabe", "Wert", "Erlaeuterung"])
        entries = [
            (
                "Vertragsnetz netto ct/kWh",
                baseline,
                "Bereits im Vertrags-AP enthalten.",
            ),
            (
                "Modul 3 Vergleich",
                comparison,
                "contract_start oder current_year; ST ist kein normales Jahresentgelt.",
            ),
            (
                "Normales Jahresnetz netto ct/kWh",
                current_network,
                "Nur dokumentierten normalen Satz eingeben, nicht Modul-3-ST.",
            ),
            (
                "Modul 1 netto EUR/Jahr",
                module1_annual,
                "Zeitanteilige Gutschrift, keine Netzzeitzone.",
            ),
            ("USt Ersatzwert (Anteil)", vat, "Tarif-USt hat fuer Verbrauch Vorrang."),
            ("Modul 1 wirksam ab", module1_start, "Leer bedeutet: keine Gutschrift."),
        ]
        for row, (label, value, explanation) in enumerate(entries, 1):
            inputs.write(row, 0, label)
            if isinstance(value, date):
                inputs.write_datetime(
                    row, 1, datetime.combine(value, time.min), date_input_fmt
                )
            elif value is None:
                inputs.write_blank(row, 1, None, input_fmt)
            else:
                inputs.write(
                    row,
                    1,
                    float(value) if isinstance(value, Decimal) else value,
                    input_fmt,
                )
            inputs.write(row, 2, explanation, note)
        inputs.data_validation(
            2,
            1,
            2,
            1,
            {"validate": "list", "source": ["contract_start", "current_year"]},
        )
        for input_row in (1, 3, 4, 5):
            inputs.data_validation(
                input_row,
                1,
                input_row,
                1,
                {"validate": "decimal", "criteria": ">=", "value": 0},
            )
        inputs.set_column(0, 0, 38)
        inputs.set_column(2, 2, 90)
        inputs.write(8, 0, "Vergleichsnetz netto ct/kWh")
        reference = baseline if comparison == "contract_start" else current_network
        formula(
            inputs,
            8,
            1,
            '=IF(B3="contract_start",B2,IF(ISNUMBER(B4),B4,""))',
            reference if reference is not None else "",
            number_fmt,
        )
        inputs.write(9, 0, "Eingabestatus")
        formula(
            inputs,
            9,
            1,
            "=IF(AND(ISNUMBER(B2),B2>=0,ISNUMBER(B5),B5>=0,"
            "ISNUMBER(B6),B6>=0,B6<=1,ISNUMBER(B9),B9>=0,"
            'OR(B7="",ISNUMBER(B7))),"OK","EINGABE UNGUELTIG")',
            "OK" if reference is not None else "EINGABE UNGUELTIG",
            note,
        )
        inputs.write(10, 0, "Grundgebuehr")
        inputs.write(
            10,
            2,
            "Monatspreise im Blatt Grundpreise editieren: x 12 / 365 je Tag. "
            "Heat-Messentgelte sind bereits enthalten.",
            note,
        )
        inputs.write(11, 0, "Datenqualitaet")
        inputs.write(
            11,
            2,
            "Leere Messwerte sind fehlend, 0 ist gueltig. "
            "92/100 Intervalle bei Zeitumstellung. "
            "Ungueltige/duplizierte Quelldaten bleiben als Warnung gesperrt.",
            note,
        )
        inputs.write(12, 0, "Tarifzuordnung")
        inputs.write(
            12,
            2,
            "Vertragspreiszonen aus dem gueltigen Agreement, "
            "nicht aus Website-Vorgaben. Historische Intelligent-Zusatzslots "
            "sind nur erfasst, wenn die gelieferten Preise sie abbilden; "
            "keine Rekonstruktion aus Tageswerten.",
            warning_fmt,
        )
        for explanation_row in (10, 11, 12):
            inputs.set_row(explanation_row, 46)
        for row, text in enumerate(warnings, 14):
            inputs.write(row, 0, "Warnung", warning_fmt)
            inputs.merge_range(row, 1, row, 4, text, warning_fmt)

        tariff_sheet = sheets["Tarifpreise"]
        heading(
            tariff_sheet,
            ["ID", "Vertrag", "Preiszone", "AP brutto EUR/kWh", "USt Anteil"],
        )
        for index, (agreement, label, rate, tax) in enumerate(tariffs, 1):
            tariff_sheet.write_row(index, 0, [index, agreement, label])
            tariff_sheet.write_number(index, 3, float(rate), input_fmt)
            tariff_sheet.write_number(index, 4, float(tax), input_fmt)
        tariff_end = max(2, len(tariffs) + 1)
        tariff_range = f"Tarifpreise!$A$2:$E${tariff_end}"
        standing_sheet = sheets["Grundpreise"]
        heading(standing_sheet, ["Vertrag", "Grundpreis brutto EUR/Monat"])
        standing_sheet.set_column(0, 0, 60)
        for index, (agreement, standing) in enumerate(standing_rates, 1):
            standing_sheet.write(index, 0, agreement)
            standing_sheet.write_number(index, 1, float(standing * 365 / 12), input_fmt)
        network_sheet = sheets["Netzpreise"]
        heading(network_sheet, ["ID", "Netzband", "Netto ct/kWh", "Quelle"])
        for index, (band, rate, source) in enumerate(networks, 1):
            network_sheet.write_row(index, 0, [index, band])
            if rate is not None:
                network_sheet.write_number(index, 2, float(rate * 100), input_fmt)
            else:
                network_sheet.write_blank(index, 2, None, input_fmt)
            network_sheet.write(index, 3, source, note)
        network_end = max(2, len(networks) + 1)
        network_range = f"Netzpreise!$A$2:$D${network_end}"

        regular = [f"{slot // 4:02}:{slot % 4 * 15:02}" for slot in range(96)]
        extra = sorted(
            {
                label
                for readings in readings_by_date.values()
                for label, _ in measurement_columns(readings, timezone)
                if label not in regular
            }
        )
        columns = [*regular, *extra]
        matrix = sheets["Messwerte"]
        heading(matrix, ["Datum", *columns, "Erwartete Intervalle"])
        matrix.set_column(1, len(columns), 12, input_fmt)
        cells = {}
        for row, (day, readings) in enumerate(readings_by_date.items(), 1):
            matrix.write_datetime(row, 0, datetime.fromisoformat(day), date_fmt)
            mapped = measurement_columns(readings, timezone)
            available = {label for label, _ in mapped}
            for col, label in enumerate(columns, 1):
                if label not in available:
                    matrix.write(row, col, "nicht vorhanden", absent_fmt)
            for label, reading in mapped:
                col = columns.index(label) + 1
                at = datetime.fromisoformat(reading["start_time"])
                cells[at] = f"Messwerte!{xl_col_to_name(col)}{row + 1}"
                if reading["reading_status"] == "OK":
                    matrix.write_number(row, col, float(reading["value"]), input_fmt)
                else:
                    matrix.write_blank(row, col, None, input_fmt)
                matrix.data_validation(
                    row,
                    col,
                    row,
                    col,
                    {"validate": "decimal", "criteria": ">=", "value": 0},
                )
            matrix.write(row, len(columns) + 1, len(readings))

        interval_sheet = sheets["Intervalle"]
        heading(
            interval_sheet,
            [
                "UTC ab",
                "Datum lokal",
                "Uhrzeit / UTC-Offset",
                "Verbrauch kWh",
                "Tarif-ID (editierbar)",
                "Vertragspreiszone",
                "AP brutto EUR/kWh",
                "USt Anteil",
                "Netz-ID (editierbar)",
                "Netzband",
                "Netto ct/kWh",
                "Status",
                "Tarifkosten EUR",
                "Vergleichsanpassung EUR",
                "Vergleichsnetz abziehen EUR",
                "Netzentgelt EUR",
                "Modul 3 Einsparung EUR",
                "Energie gesamt EUR",
                "Modul 3 aktiv",
            ],
        )
        daily_ranges = {}
        cached_intervals: dict[str, list[dict[str, Any]]] = {}
        row = 1
        for day, readings in readings_by_date.items():
            first = row + 1
            cached_intervals[day] = []
            for reading in readings:
                at = datetime.fromisoformat(reading["start_time"])
                local = at.astimezone(ZoneInfo(timezone))
                item = by_instant.get(at)
                r = row + 1
                interval_sheet.write(row, 0, at.isoformat())
                interval_sheet.write_datetime(
                    row, 1, datetime.fromisoformat(day), date_fmt
                )
                interval_sheet.write(row, 2, local.strftime("%H:%M %z"))
                present = reading["reading_status"] == "OK"
                q = reading["value"] if present else _ZERO
                formula(
                    interval_sheet,
                    row,
                    3,
                    f'=IF({cells[at]}="","",{cells[at]})',
                    q if present else "",
                    quantity_fmt,
                )
                tariff_key = (
                    (item["agreement"], item["tariff"], item["gross_rate"], item["vat"])
                    if item
                    else None
                )
                network_key = (
                    (item["band"], item["network_rate"], item["network_source"])
                    if item
                    else None
                )
                tariff_id = (
                    tariff_indices.get(tariff_key, 0) if tariff_key is not None else 0
                )
                network_id = (
                    network_indices.get(network_key, 0)
                    if network_key is not None
                    else 0
                )
                interval_sheet.write_number(row, 4, tariff_id, input_fmt)
                interval_sheet.write_number(row, 8, network_id, input_fmt)
                module3 = bool(item and item["module3_selected"])
                interval_sheet.write_number(row, 18, int(module3))
                for col, expression, cached in (
                    (
                        5,
                        f'IFERROR(VLOOKUP(E{r},{tariff_range},3,FALSE),"")',
                        item["tariff"] if item else "",
                    ),
                    (
                        6,
                        f'IF(E{r}=0,"",VLOOKUP(E{r},{tariff_range},4,FALSE))',
                        item["gross_rate"] if item else "",
                    ),
                    (
                        7,
                        f'IF(E{r}=0,"",VLOOKUP(E{r},{tariff_range},5,FALSE))',
                        item["vat"] if item else "",
                    ),
                    (
                        9,
                        f'IFERROR(VLOOKUP(I{r},{network_range},2,FALSE),"")',
                        item["band"] if item else "",
                    ),
                    (
                        10,
                        f'IF(OR(I{r}=0,COUNT(INDEX(Netzpreise!$C$2:$C${network_end},I{r}))=0),"",VLOOKUP(I{r},{network_range},3,FALSE))',
                        item["network_rate"] * 100
                        if item and item["network_rate"] is not None
                        else "",
                    ),
                ):
                    formula(
                        interval_sheet,
                        row,
                        col,
                        f"={expression}",
                        cached,
                        number_fmt if col in (6, 7, 10) else note,
                    )
                complete = (
                    present
                    and item is not None
                    and item["network_rate"] is not None
                    and reference is not None
                )
                formula(
                    interval_sheet,
                    row,
                    11,
                    f'=IF(D{r}="","MESSWERT FEHLT",'
                    f'IF(NOT(ISNUMBER(D{r})),"MESSWERT UNGUELTIG",'
                    f'IF(D{r}<0,"MESSWERT UNGUELTIG",'
                    f"IF(OR(NOT(ISNUMBER(G{r})),NOT(ISNUMBER(H{r})),"
                    f'NOT(ISNUMBER(K{r})),Eingaben!$B$10<>"OK"),"PREIS FEHLT",'
                    f'IF(OR(H{r}<0,H{r}>1,K{r}<0),"PREIS UNGUELTIG","OK")))))',
                    "OK" if complete else "UNVOLLSTAENDIG",
                    note,
                )
                base = q * item["gross_rate"] if item else _ZERO
                tax = item["vat"] if item else vat
                ref = (
                    (reference if reference is not None else _ZERO)
                    if module3
                    else (
                        item["network_rate"] * 100
                        if item and item["network_rate"] is not None
                        else _ZERO
                    )
                )
                adjust = q * (ref - baseline) * (1 + tax) / 100
                remove = -q * ref * (1 + tax) / 100
                network = (
                    q * item["network_rate"] * (1 + tax)
                    if item and item["network_rate"] is not None
                    else _ZERO
                )
                saving = -remove - network
                amounts = [
                    base,
                    adjust,
                    remove,
                    network,
                    saving,
                    base + adjust - saving,
                ]
                ref_formula = f"IF(S{r}=1,Eingaben!$B$9,K{r})"
                expressions = [
                    f"D{r}*G{r}",
                    f"D{r}*({ref_formula}-Eingaben!$B$2)*(1+H{r})/100",
                    f"-D{r}*{ref_formula}*(1+H{r})/100",
                    f"D{r}*K{r}*(1+H{r})/100",
                    f"-O{r}-P{r}",
                    f"M{r}+N{r}-Q{r}",
                ]
                for col, expression, amount in zip(
                    range(12, 18), expressions, amounts, strict=True
                ):
                    formula(
                        interval_sheet,
                        row,
                        col,
                        f'=IF(L{r}<>"OK","",{expression})',
                        amount if complete else "",
                    )
                cached_intervals[day].append(
                    {
                        "tariff_id": tariff_id,
                        "quantity": q,
                        "amounts": amounts,
                        "complete": complete,
                    }
                )
                row += 1
            daily_ranges[day] = (first, row)
        interval_sheet.autofilter(0, 0, row - 1, 17)
        for col, upper in ((4, len(tariffs)), (8, len(networks))):
            if upper:
                interval_sheet.data_validation(
                    1,
                    col,
                    row - 1,
                    col,
                    {
                        "validate": "integer",
                        "criteria": "between",
                        "minimum": 1,
                        "maximum": upper,
                    },
                )

        daily_sheet = sheets["Tageswerte"]
        band_names = sorted({item["band"] for item in details})
        breakdown_labels = [
            title
            for agreement, label, _rate, _tax in tariffs
            for title in (
                f"{label} / {agreement} kWh",
                f"{label} / {agreement} Kosten EUR",
            )
        ] + [
            title
            for band in band_names
            for title in (f"Netz {band} kWh", f"Netz {band} Kosten EUR")
        ]
        heading(
            daily_sheet,
            [
                "Datum",
                "Status",
                "Verbrauch kWh",
                "Tarifkosten EUR",
                "Referenzanpassung EUR",
                "Netzreferenz abziehen EUR",
                "NT/ST/HT Netz EUR",
                "Modul 3 Einsparung EUR",
                "Grundgebuehr EUR/Tag",
                "Modul 1 Abzug EUR",
                "Gesamtkosten EUR",
                "Quellstatus",
                *breakdown_labels,
            ],
        )
        day_caches = []
        for index, daily in enumerate(daily_rows, 1):
            day = daily["date"]
            first, last = daily_ranges[day]
            r = index + 1
            day_date = date.fromisoformat(day)
            daily_sheet.write_datetime(
                index, 0, datetime.combine(day_date, time.min), date_fmt
            )
            source_status = daily["status"]
            # Missing slots are repairable offline; invalid sources are not.
            blocked = (
                "invalid reading" in source_status
                or "duplicate reading" in source_status
            )
            daily_sheet.write(index, 11, source_status, warning_fmt)
            valid = (
                not blocked
                and all(item["complete"] for item in cached_intervals[day])
                and daily["standing_charge_gross_eur"] is not None
            )
            formula(
                daily_sheet,
                index,
                1,
                f'=IF(OR(COUNTIF(Intervalle!L{first}:L{last},"OK")<>{last - first + 1},'
                f'NOT(ISNUMBER(I{r})),I{r}<0,LEFT(L{r},12)="SOURCE ERROR"),'
                '"UNVOLLSTAENDIG","OK")',
                "OK" if valid else "UNVOLLSTAENDIG",
                note,
            )
            if blocked:
                daily_sheet.write(
                    index, 11, f"SOURCE ERROR: {source_status}", warning_fmt
                )
            amounts = [
                sum(item["amounts"][i] for item in cached_intervals[day])
                for i in range(6)
            ]
            day_quantity = sum(item["quantity"] for item in cached_intervals[day])
            for col, source_col, cache in (
                (2, "D", day_quantity),
                (3, "M", amounts[0]),
                (4, "N", amounts[1]),
                (5, "O", amounts[2]),
                (6, "P", amounts[3]),
                (7, "Q", amounts[4]),
            ):
                formula(
                    daily_sheet,
                    index,
                    col,
                    f'=IF(B{r}<>"OK","",SUM(Intervalle!{source_col}{first}:{source_col}{last}))',
                    cache if valid else "",
                    quantity_fmt if col == _QUANTITY_LAST_COLUMN else money,
                )
            standing = daily["standing_charge_gross_eur"]
            if standing is not None:
                standing_row = standing_indices[(daily["tariff_agreement"], standing)]
                formula(
                    daily_sheet,
                    index,
                    8,
                    f'=IF(ISNUMBER(Grundpreise!B{standing_row}),Grundpreise!B{standing_row}*12/365,"")',
                    standing,
                )
            else:
                daily_sheet.write_blank(index, 8, None, input_fmt)
            credit = daily["module1_credit_gross_eur"]
            formula(
                daily_sheet,
                index,
                9,
                f"=IF(AND(ISNUMBER(Eingaben!$B$7),A{r}>=Eingaben!$B$7),-Eingaben!$B$5*(1+Eingaben!$B$6)/(DATE(YEAR(A{r})+1,1,1)-DATE(YEAR(A{r}),1,1)),0)",
                -credit,
            )
            total = amounts[5] + (standing or _ZERO) - credit
            formula(
                daily_sheet,
                index,
                10,
                f'=IF(B{r}<>"OK","",D{r}+E{r}-H{r}+I{r}+J{r})',
                total if valid else "",
            )
            day_caches.append(
                {
                    "day": day,
                    "valid": valid,
                    "amounts": amounts,
                    "quantity": day_quantity,
                    "standing": standing or _ZERO,
                    "credit": credit,
                    "total": total,
                }
            )
            col = 12
            for tariff_id in range(1, len(tariffs) + 1):
                selected_items = [
                    item
                    for item in cached_intervals[day]
                    if item["tariff_id"] == tariff_id
                ]
                for source_col, cached, fmt in (
                    (
                        "D",
                        sum(item["quantity"] for item in selected_items),
                        quantity_fmt,
                    ),
                    ("M", sum(item["amounts"][0] for item in selected_items), money),
                ):
                    formula(
                        daily_sheet,
                        index,
                        col,
                        f'=IF(B{r}<>"OK","",SUMIF(Intervalle!E{first}:E{last},{tariff_id},'
                        f"Intervalle!{source_col}{first}:{source_col}{last}))",
                        cached if valid else "",
                        fmt,
                    )
                    col += 1
            for band in band_names:
                band_literal = band.replace('"', '""')
                selected_items = [
                    item
                    for item in details
                    if item["local_start"].date().isoformat() == day
                    and item["band"] == band
                    and item["reading_status"] == "OK"
                ]
                for source_col, cached, fmt in (
                    (
                        "D",
                        sum(item["quantity"] for item in selected_items),
                        quantity_fmt,
                    ),
                    (
                        "P",
                        sum(
                            item["quantity"] * item["network_rate"] * (1 + item["vat"])
                            for item in selected_items
                            if item["network_rate"] is not None
                        ),
                        money,
                    ),
                ):
                    formula(
                        daily_sheet,
                        index,
                        col,
                        f'=IF(B{r}<>"OK","",SUMIF(Intervalle!J{first}:J{last},'
                        f'"{band_literal}",Intervalle!{source_col}{first}:{source_col}{last}))',
                        cached if valid else "",
                        fmt,
                    )
                    col += 1

        invoice = sheets["Rechnung"]
        invoice.set_column(0, 0, 54)
        invoice.set_column(1, 3, 22)
        invoice.merge_range(0, 0, 0, 3, "Stromkosten - Monatsrechnungen", title)
        invoice.merge_range(
            1,
            0,
            2,
            3,
            f"Zeitraum {daily_rows[0]['date']} bis {daily_rows[-1]['date']}. "
            "Offline-Berechnung, keine Lieferantenrechnung. Blau = Eingaben. "
            "Vertragszonen und Netzzeitzonen sind unabhaengig. "
            "Modul 1 ist eine Pauschalgutschrift; "
            "Heat-Messentgelte sind bereits im Grundpreis enthalten.",
            note,
        )
        invoice.set_row(1, 36)
        invoice.set_row(2, 36)
        months = sorted({item["day"][:7] for item in day_caches})
        invoice_row = 5
        for month in months:
            selected = [item for item in day_caches if item["day"].startswith(month)]
            first_day = next(
                i + 2
                for i, item in enumerate(day_caches)
                if item["day"].startswith(month)
            )
            last_day = first_day + len(selected) - 1
            first_slot = daily_ranges[selected[0]["day"]][0]
            last_slot = daily_ranges[selected[-1]["day"]][1]
            valid = all(item["valid"] for item in selected)
            invoice.merge_range(
                invoice_row, 0, invoice_row, 3, f"Monat {month}", header
            )
            invoice_row += 1
            status_cell = f"D{invoice_row + 1}"
            invoice.write(invoice_row, 0, "Datenstatus")
            formula(
                invoice,
                invoice_row,
                3,
                f'=IF(COUNTIF(Tageswerte!B{first_day}:B{last_day},"OK")='
                f'{len(selected)},"OK","UNVOLLSTAENDIG")',
                "OK" if valid else "UNVOLLSTAENDIG",
                warning_fmt,
            )
            invoice_row += 1
            invoice.write_row(
                invoice_row,
                0,
                ["Position", "Menge kWh", "Brutto ct/kWh", "Betrag brutto EUR"],
                header,
            )
            invoice.set_row(invoice_row, 32)
            invoice_row += 1
            line_rows = []
            # Derive zones from priced intervals, not a fixed GO/Heat schema.
            active_ids = range(1, len(tariffs) + 1)
            for tariff_id in active_ids:
                agreement, label, _rate, _tax = tariffs[tariff_id - 1]
                cached = [
                    item
                    for day in selected
                    for item in cached_intervals[day["day"]]
                    if item["tariff_id"] == tariff_id
                ]
                formula(
                    invoice,
                    invoice_row,
                    0,
                    f"=IF(COUNTIF(Intervalle!E{first_slot}:E{last_slot},"
                    f'{tariff_id})=0,"",Tarifpreise!C{tariff_id + 1}&'
                    f'" - "&Tarifpreise!B{tariff_id + 1})',
                    f"{label} - {agreement}" if cached else "",
                    note,
                )
                invoice.set_row(invoice_row, 32)
                formula(
                    invoice,
                    invoice_row,
                    1,
                    f"=SUMIF(Intervalle!E{first_slot}:E{last_slot},{tariff_id},Intervalle!D{first_slot}:D{last_slot})",
                    sum(item["quantity"] for item in cached),
                    quantity_fmt,
                )
                formula(
                    invoice,
                    invoice_row,
                    2,
                    f"=Tarifpreise!D{tariff_id + 1}*100",
                    _rate * 100,
                    number_fmt,
                )
                formula(
                    invoice,
                    invoice_row,
                    3,
                    f'=IF({status_cell}<>"OK","",SUMIF(Intervalle!E{first_slot}:E{last_slot},{tariff_id},Intervalle!M{first_slot}:M{last_slot}))',
                    sum(item["amounts"][0] for item in cached) if valid else "",
                )
                line_rows.append(invoice_row + 1)
                invoice_row += 1
            for label, col, cached in (
                (
                    "Grundgebuehr (Messentgelte enthalten)",
                    "I",
                    sum(item["standing"] for item in selected),
                ),
                (
                    "Anpassung Vertragsnetz an Vergleichsnetz",
                    "E",
                    sum(item["amounts"][1] for item in selected),
                ),
                (
                    "Abzueglich Modul 1 - pauschale Gutschrift",
                    "J",
                    -sum(item["credit"] for item in selected),
                ),
                (
                    "Abzueglich Modul 3 - Einsparung / Mehrkosten",
                    "H",
                    -sum(item["amounts"][4] for item in selected),
                ),
            ):
                invoice.write(invoice_row, 0, label)
                sign = "-" if col == "H" else ""
                formula(
                    invoice,
                    invoice_row,
                    3,
                    f'=IF({status_cell}<>"OK","",{sign}SUM(Tageswerte!{col}{first_day}:{col}{last_day}))',
                    cached if valid else "",
                )
                line_rows.append(invoice_row + 1)
                invoice_row += 1
            invoice.write(invoice_row, 0, "GESAMTKOSTEN", header)
            month_quantity = sum(item["quantity"] for item in selected)
            formula(
                invoice,
                invoice_row,
                1,
                f'=IF({status_cell}<>"OK","",SUM(Tageswerte!C{first_day}:C{last_day}))',
                month_quantity if valid else "",
                total_quantity,
            )
            invoice_sum = ",".join(f"D{r}" for r in line_rows)
            formula(
                invoice,
                invoice_row,
                3,
                f'=IF({status_cell}<>"OK","",SUM({invoice_sum}))',
                sum(item["total"] for item in selected) if valid else "",
                total_money,
            )
            invoice_row += 2
            for label, col, cache_index in (
                ("Modul 3 Detail: Vergleichsnetz abziehen", "O", 2),
            ):
                invoice.write(invoice_row, 0, label)
                r = invoice_row + 1
                formula(
                    invoice,
                    invoice_row,
                    1,
                    f'=IF({status_cell}<>"OK","",'
                    f"SUM(Tageswerte!C{first_day}:C{last_day}))",
                    month_quantity if valid else "",
                    quantity_fmt,
                )
                formula(
                    invoice,
                    invoice_row,
                    2,
                    f'=IF({status_cell}<>"OK","",IF(B{r}=0,"",-D{r}/B{r}*100))',
                    -sum(item["amounts"][cache_index] for item in selected)
                    / month_quantity
                    * 100
                    if valid and month_quantity
                    else "",
                    number_fmt,
                )
                formula(
                    invoice,
                    invoice_row,
                    3,
                    f'=IF({status_cell}<>"OK","",'
                    f"SUM(Intervalle!{col}{first_slot}:{col}{last_slot}))",
                    sum(item["amounts"][cache_index] for item in selected)
                    if valid
                    else "",
                )
                invoice_row += 1
            for band in sorted(
                {
                    item["band"]
                    for item in details
                    if item["local_start"].strftime("%Y-%m") == month
                }
            ):
                band_literal = band.replace('"', '""')
                band_label = {
                    "OFFPEAK": "NT (Niedertarif)",
                    "STANDARD": "ST (Standardtarif)",
                    "PEAK": "HT (Hochtarif)",
                }.get(band, band)
                r = invoice_row + 1
                invoice.write(invoice_row, 0, f"Netzentgelt {band_label} hinzufuegen")
                band_items = [
                    item
                    for item in details
                    if item["local_start"].strftime("%Y-%m") == month
                    and item["band"] == band
                ]
                band_quantity = sum(
                    item["quantity"]
                    for item in band_items
                    if item["reading_status"] == "OK"
                )
                band_cost = sum(
                    item["quantity"] * item["network_rate"] * (1 + item["vat"])
                    for item in band_items
                    if item["reading_status"] == "OK"
                    and item["network_rate"] is not None
                )
                formula(
                    invoice,
                    invoice_row,
                    1,
                    f"=SUMIF(Intervalle!J{first_slot}:J{last_slot},"
                    f'"{band_literal}",Intervalle!D{first_slot}:D{last_slot})',
                    band_quantity,
                    quantity_fmt,
                )
                formula(
                    invoice,
                    invoice_row,
                    2,
                    f'=IF({status_cell}<>"OK","",IF(B{r}=0,"",D{r}/B{r}*100))',
                    band_cost / band_quantity * 100 if valid and band_quantity else "",
                    number_fmt,
                )
                formula(
                    invoice,
                    invoice_row,
                    3,
                    f'=IF({status_cell}<>"OK","",'
                    f'SUMIF(Intervalle!J{first_slot}:J{last_slot},"{band_literal}",'
                    f"Intervalle!P{first_slot}:P{last_slot}))",
                    band_cost if valid else "",
                )
                invoice_row += 1
            invoice.merge_range(
                invoice_row,
                0,
                invoice_row,
                3,
                "Details oben bereits verrechnet - nicht erneut addieren. "
                "Netzpreise: verbrauchsgewichtete Bruttopreise in ct/kWh; "
                "bei 0 kWh leer. Einzelpreise im Blatt Netzpreise.",
                note,
            )
            invoice.set_row(invoice_row, 48)
            invoice_row += 3
        if len(months) > 1:
            invoice.write(invoice_row, 0, "GESAMTER BERICHTSZEITRAUM", header)
            valid = all(item["valid"] for item in day_caches)
            formula(
                invoice,
                invoice_row,
                1,
                f'=IF(COUNTIF(Tageswerte!B2:B{len(day_caches) + 1},"OK")='
                f"{len(day_caches)},"
                f'SUM(Tageswerte!C2:C{len(day_caches) + 1}),"")',
                sum(item["quantity"] for item in day_caches) if valid else "",
                total_quantity,
            )
            formula(
                invoice,
                invoice_row,
                3,
                f'=IF(COUNTIF(Tageswerte!B2:B{len(day_caches) + 1},"OK")='
                f"{len(day_caches)},"
                f'SUM(Tageswerte!K2:K{len(day_caches) + 1}),"")',
                sum(item["total"] for item in day_caches) if valid else "",
                total_money,
            )
            invoice_row += 1
        invoice.set_landscape()
        invoice.fit_to_pages(1, 0)
        invoice.print_area(0, 0, invoice_row, 3)
        invoice.activate()
        basis_sheet = sheets["Basis"]
        heading(
            basis_sheet,
            [
                "Schluessel",
                "Gespeicherte Vertrags-/API-Daten (Gueltigkeit und Zeitfenster)",
            ],
        )
        basis_sheet.set_column(1, 1, 120)
        row = 1
        for item in basis_rows:
            text = str(item["basis_value"])
            for offset in range(0, max(1, len(text)), 32000):
                basis_sheet.write(
                    row, 0, f"{item['basis_key']} [{offset // 32000 + 1}]"
                )
                basis_sheet.write(row, 1, text[offset : offset + 32000], note)
                row += 1
