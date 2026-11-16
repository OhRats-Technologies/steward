# ledgerlite

Reads expense records from CSV and prints monthly totals.

Spec:
- CSV fields may be quoted and may contain commas: `2026-03-01,"Lunch, team",12.50`.
- Amounts are money: sums are exact, and totals round half up to cents (0.125 -> 0.13).
- `month_total(records, "2026-03")` includes every day of the month, the last day too.
- The public API is `parse`, `total`, `month_total`. Do not rename or remove them.
