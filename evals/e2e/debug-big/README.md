# ledgerlite

Reads expense records from CSV and prints monthly totals.

Spec:
- CSV fields may be quoted and may contain commas: `2026-03-01,"Lunch, team",12.50`.
- Amounts are money: sums are exact, and totals round half up to cents (0.125 -> 0.13).
- `month_total(records, "2026-03")` includes every day of the month, the last day too.
- The public API is `parse`, `total`, `month_total`. Do not rename or remove them.
- Dates may be written without zero padding (`2026-3-1`); they mean `2026-03-01`.
- `convert(amount, "EUR", rates)` turns USD into EUR using `rates["EUR"]`, the number of EUR per USD.
- `by_category(records, "food")` matches categories case-insensitively and ignores surrounding spaces.
- `to_json(records)` writes amounts as strings, never floats, so no precision is lost.
- `util.norm(s)` is the one place text is normalised: stripped and lowercased.
