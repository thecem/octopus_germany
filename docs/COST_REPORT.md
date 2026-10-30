# Electricity Cost Report

`octopus_germany.export_cost_report` creates a daily and monthly estimate from Octopus agreement prices, smart-meter measurements, standing charges, and the grid-fee schedule returned for the metering point's network operator.

This is a calculation aid, not a supplier invoice or a legal decision about eligibility or enrollment under §14a EnWG. Missing prices and rates are not silently treated as zero.

## Export package: one fetch, two files

In **Developer Tools > Actions**, select `octopus_germany.export_cost_report`
and switch to UI mode. Enter the account number, year and (for monthly
reports) month, then select `package` for the format. After updating the
integration, restart Home Assistant and reload the browser to refresh
action descriptions.

Set `format: package` to generate an editable formula `.xlsx` and a
`_measurements_15min.csv` from the same
measurement fetch. No preceding `export_smart_meter_csv` call is needed.
One notification contains two independently scoped download links.
In package mode, `output_file` and `download_url` point to the XLSX. The response
adds `files`, with `type`, `output_file` and `download_url` for each file.
Omitting `format` preserves the existing cost-CSV-only behavior.
The separate measurement-CSV service remains available. Package mode does
not generate a cost CSV or delete previously exported files.

```yaml
action: octopus_germany.export_cost_report
data:
  account_number: A-REPLACE-ME
  period: month
  year: 2026
  month: 5
  format: package
  # Optional: omit to use the date-valid basis_rate_net_ct_per_kwh per agreement.
  network_comparison: contract_start
response_variable: cost_export
```

The workbook contains invoice, inputs, raw measurements, contract prices,
standing charges, network prices, intervals, daily breakdowns and source
basis sheets (German labels). Blue cells are editable. Excel formulas
recalculate prices, quantities, Module 1/3 effects and monthly invoices
offline, without macros, external links or API calls. Initial formula
results are included for viewers.
Monthly and overall total quantities and cost amounts are bold. Invoice
network details show consumption and positive gross prices in ct/kWh for
the comparison network and each NT/ST/HT band. If prices or VAT change,
these are consumption-weighted averages (gross network cost divided by
consumption); individual net rates remain in Netzpreise. Prices are blank
for zero consumption or incomplete data. These details are already
included in the invoice total and must not be added again.

Price zones come from the **valid contract**: for example GO/STANDARD
or Heat Low/Standard/High, never a fixed GO + STANDARD + HEAT model.
Heat activation windows are contract-dependent; website example prices
are not applied. Metering charges already included in the Heat standing
charge are not added again. Contract zones and network NT/ST/HT are
independent. Historical Intelligent GO extra slots are not reconstructed
from aggregate consumption; interval tariff IDs can be adjusted manually
when historical agreement pricing does not already reflect those slots.

For `network_comparison: current_year`, provide the documented normal
annual net grid fee in `standard_network_charge_ct_kwh`. The Module 3 ST
rate is not automatically that fee. The workbook first adjusts the
contract-included grid fee to the comparison fee, then subtracts the
comparison grid cost and adds actual band costs. Changing comparison
basis changes the displayed saving, not the effective total. Before
Module 3 applies, ordinary grid-fee changes are not shown as Module 3 savings.

Package validation expects 96 slots on normal local days, 92/100 on DST
transition days. Autumn repeated slots have explicit `(2)` CSV/matrix
columns; the workbook also retains UTC and local offsets. Nonexistent
spring slots do not count as missing. Exact raw CSV quantities are not
rounded. Missing values stay blank rather than becoming zero; missing
prices or readings block invoices. Missing readings may be filled offline;
invalid/duplicate source readings require a corrected export.

The annual comparison currently uses one manually documented fee for the
report year. In package intervals before Module 3 applies, this fee also
supplies the normal actual grid fee. Without it, variable ST rates are not
accepted as normal annual fees and affected invoices remain incomplete.
Actual price validity and contract changes are selected
per interval, with full source schedules retained in the Basis sheet.
Editing price IDs supports offline scenarios; editing schedule times does
not automatically rerun contract selection.

## How the calculation works

### Contract energy price and grid-fee adjustment

For each measurement interval, the report selects the agreement valid at that time, then the price tier whose validity and activation window match. It keeps the agreement's own price label, including heat-tariff labels. The selected gross contract price is adjusted only by the difference between the current net grid fee and the net grid-fee component already included in the original contract price:

```text
adjusted gross unit price [EUR/kWh]
  = contracted gross unit price [EUR/kWh]
  + ((current network fee [ct/kWh] - contract-start baseline [ct/kWh]) / 100)
    * (1 + VAT fraction)
```

The interval's adjusted energy cost is its kWh multiplied by that adjusted unit price. The network-fee difference is converted from cents to euros before it is added. VAT from the applicable agreement price is used when present; otherwise `vat_percent` is used.

`contract_start_network_charge_ct_kwh` is the **net grid-fee component already embedded in the original gross contract unit price**. It is not the full current network fee, and it is not a value inferred from a tariff name. An explicitly supplied value, including `0`, takes precedence. When omitted, the report uses each agreement's `validFrom` date and the matching network-operator/year entry in the local schedule file to find the unique period whose `valid_from` is inclusive and `valid_to` is exclusive. It uses that period's documented `basis_rate_net_ct_per_kwh`, not a Module 3 ST band. Ensure the file records the network-fee component from the original contract; there is no silent `7.65` or zero fallback. Missing contract dates or a missing/ambiguous basis value produce a warning and mark affected calculations incomplete until a value is entered manually.

### Module 3 grid fees

Grid-fee schedules are requested for the relevant dates and network operator. The service re-queries at API validity boundaries, so shorter validity periods are respected. The API's reported module, rate types, time windows, and validity dates are recorded separately from the customer's selected effective date.

`module3_start_date` is the date the customer declared or selected Module 3 for this metering point. From that date, time-variable API rates are used even if the API still reports `MODULE_1`; the API label alone does not establish the customer's selection.

`module3_rates_json` is an optional array of manually supplied **net** rates, in ct/kWh, for intervals missing from the API. Each entry uses:

- `rate_type`: `OFFPEAK`, `STANDARD`, or `PEAK`
- `start_time`, `end_time`: local interval boundaries in `HH:MM:SS`
- `rate_cents_per_kwh`: net rate in ct/kWh
- `valid_from`, `valid_to`: optional ISO timestamps; `valid_to` is exclusive

A matching API interval takes precedence; manual entries fill missing intervals. If no Module 3 rate is available, the report can use an applicable API `STANDARD` grid-fee rate as an explicitly marked fallback (`module3_rate_basis`). This is a STANDARD grid-fee rate, not a separate “Module 1 ST” price. If no usable rate is available, affected consumption is identified as missing and the monthly total remains blank when a day is incomplete.

The service form includes one network operator's 2025 schedule as a convenience preset. It is applied only when the detected network-operator code matches that preset. It is valid from 1 April through 31 December 2025; replace it with the relevant operator's rates for other operators or periods. Do not use the 2025 preset for February 2026.

### User-maintained schedule file

The service can also read `/config/octopus_germany/grid_fee_schedules.json`, selecting an entry by the network-operator code detected from the account and the requested report year. A starter file containing the example data is available as [`grid_fee_schedules.example.json`](examples/grid_fee_schedules.example.json). Copy it to the config path, replace the operator-code placeholder, and verify every amount and validity period against current documents for the metering point.

Each year contains a `schedules` array for one or more non-overlapping validity periods. Each period includes `valid_from`, exclusive `valid_to`, net `rates_net_ct_per_kwh`, and exactly 24 `hourly_rate_types` entries indexed from 0 through 23. Adjacent hours remain separate. `NT`/`ST`/`HT` and `OFFPEAK`/`STANDARD`/`PEAK` are accepted labels; `null` means no file rate for that hour. API rates take precedence, then explicit service JSON rates, then matching file rates fill any remaining gaps.

The year's optional `module1_credit_net_eur` is used only when `module1_annual_credit_net_eur` is blank in the service call. An explicit service value, including zero, takes precedence. `basis_rate_net_ct_per_kwh` is the normal net basis used for the contract-start fallback above; it must reflect the original contract and is never inferred from variable Module 3 hourly rates. The matched schedule, validity period, selected baseline, contract start and source are recorded in the CSV `BASIS` rows and XLSX. The XLSX `Eingaben` sheet also lists the schedule validity periods and basis values. Missing, invalid, or unmatched entries generate a service warning rather than being silently ignored.

Each year may also contain `module1_start_date` (Module 1 eligibility date)
and `module3_start_date` (customer-selected Module 3 effective date), using
`YYYY-MM-DD`. These are customer-specific dates, not the operator's rate
validity dates. Explicit action dates take precedence; otherwise the matching
file dates are used. Omit these keys or use `null` when unknown; the example
does not assume eligibility or enrollment. If neither source supplies an annual
credit, it stays unset in the calculation inputs and no credit is applied.

### Standing charge

The report uses the agreement's validity-dated gross monthly standing charge when available. If only the net monthly amount is available, it applies the VAT fallback. The monthly amount is converted to a daily amount using `monthly amount * 12 / 365`, then applied to each actual day in the report period. This reflects tariffs billed by day rather than assigning the same standing charge to every calendar month.

### Module 1 credit

When both the Module 1 start date and annual credit are available from the action or matching schedule, the annual credit is divided by the number of days in each calendar year and applied from that date onward. The report converts the daily net credit to gross using the VAT fallback and subtracts it from the gross total. Enter the annual amount that applies to the selected report year. Unknown amounts and dates remain unset; an explicit zero credit in the action disables the credit even if the file provides an amount.

## Parameters

| Parameter | Why it is used |
| --- | --- |
| `account_number` | Required account whose agreements and readings are exported. |
| `property_id` | Optional electricity property; defaults to the first property. |
| `period`, `year`, `month` | Select month or calendar year; `month` is required for a monthly report. Current-year data ends two days before today. |
| `contract_start_network_charge_ct_kwh` | Optional documented net contract-start baseline in ct/kWh; explicit values (including zero) win, otherwise each agreement's validFrom date resolves a unique local schedule basis rate. |
| `module3_start_date` | Optional customer-declared/selected Module 3 effective date; falls back to the matching file date and controls when time-variable rates are used. |
| `module3_rates_json` | Optional manual net-rate intervals for periods when the API lacks matching rates. |
| `module1_start_date` | Optional eligibility date for prorating the Module 1 credit; falls back to the matching file date. |
| `module1_annual_credit_net_eur` | Optional net annual credit for the selected report year; an explicit value (including zero) wins, otherwise the matching file value is used. If neither supplies a value, it remains unset and no credit is applied. |
| `vat_percent` | VAT fallback when an agreement price tier has no VAT value; defaults to 19%. |
| `filename` | Optional output filename. |

## CSV structure

Rows are identified by `record_type`:

- `DAY`: local-day consumption and costs by agreement tariff label and grid-fee time block; includes the API-reported module, rate basis, applied net/gross grid-fee rates, missing kWh, and status.
- `MONTH_TOTAL`: sums each tariff/grid-fee block and shows the monthly gross standing charge, Module 1 credit, and gross monthly total. Applied rates are consumption-weighted when they change during the month.
- `TOTAL`: report-period totals.
- `BASIS`: audit rows after the total. They include input assumptions, agreement prices and standing-charge rates, and each month's API grid-fee response with validity details.

The monthly calculation is:

```text
gross energy cost after grid-fee adjustment
+ gross standing charge
- gross Module 1 credit
= gross monthly total
```

If any day is incomplete, the `MONTH_TOTAL` amount is blank. Check `status`, `unpriced_kwh`, and `network_rate_missing_kwh`; an incomplete total must not be read as zero. CSV columns use semicolons and German decimal commas. Consumption is displayed to three decimal places, euro amounts to cents, and unit rates to six decimal places; calculations retain full precision until formatting.

Files are saved under `/config/octopus_germany/exports`. Home Assistant creates a persistent notification with a file-scoped browser download link that expires after 30 days.

## Legal and regulatory context

The calculation's regulatory context is §14a EnWG, Bundesnetzagentur determination BK6-22-300 for the market process, and BK8-22/010-A for network-charge rules and calculation. Those references do not provide a customer's contract baseline or prove that Module 3 was selected. The integration does not determine legal entitlement, validate an effective date, or replace a supplier invoice. Confirm the declaration/effective date, baseline, and any manual historical rates against the customer's contract and documents from the responsible network operator.
