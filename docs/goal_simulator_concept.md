# Goal Simulator — Concept (Phases 7–12)

**Status: built.** Python: `src/goal_simulator.py` (tested in `tests/test_phases_3_to_9.py`). Tableau: the **Goal Simulator** dashboard, where the inputs are parameters and the formulas below are calculated fields. This page is the design the code was checked against.

## What it answers

"If I invest a lump sum now and a fixed amount every month, will I reach my target in time? If not, how much do I need to invest each month?"

## Inputs (Tableau parameters)

| Input | Example | Notes |
|---|---|---|
| Initial Investment | ₹2,00,000 | must be ≥ 0 |
| Monthly Investment (SIP) | ₹5,000 | must be ≥ 0 |
| Target Amount | ₹10,00,000 | must be > 0 |
| Expected Annual Return | 12% | entered as a percent, converted to a decimal (0.12) |
| Investment Period | 5 years | must be > 0 |

## Formulas

Let `r` = annual return (decimal), `i = r / 12` (monthly rate), `n` = years, `m = 12 × n` (months).

| Quantity | Formula |
|---|---|
| Future value of the initial amount | `P × (1 + r)^n` |
| Future value of the monthly SIP | `PMT × ((1 + i)^m − 1) / i`; if `r = 0`, then `PMT × m` |
| Projected Portfolio Value | FV of initial + FV of SIP |
| Total Contributions | `P + PMT × m` |
| Estimated Investment Growth | Projected Value − Total Contributions |
| Goal Gap | Target − Projected Value (0 or negative means the goal is reached) |
| Goal Achievement % | Projected Value ÷ Target × 100 |
| Required Monthly Investment | `(Target − FV of initial) / (((1 + i)^m − 1) / i)`; if `r = 0`, then `(Target − P) / m`; 0 if the target is already reached |

SIP contributions are assumed to be paid at the end of each month (an "ordinary annuity"). The initial amount compounds yearly, as written in the project brief.

## Worked example (checked in Python)

Target ₹10,00,000, initial ₹2,00,000, 5 years, 12% expected return:

- Initial amount grows to `2,00,000 × 1.12^5 = ₹3,52,468`
- Remaining gap = ₹6,47,532
- SIP factor = `(1.01^60 − 1) / 0.01 = 81.67`
- **Required monthly investment = ₹7,929** (₹7,928.67), which reaches exactly ₹10,00,000

The brief's sample output said "₹8,XXX". That was a placeholder; the exact formula gives ₹7,929.

## Edge cases to handle

0% expected return, 0 monthly investment, target already reached, negative inputs (rejected), zero investment period (rejected).

## Planned dashboard (Phase 12)

```text
GOAL SIMULATOR
Inputs:  Initial | Monthly | Target | Return % | Years      (parameter controls)
KPIs:    Projected Value | Required SIP | Goal Gap | Achievement %
Chart:   Portfolio Growth Projection (line, X = Year, Y = Value, reference line = Target)
Chart:   Goal Progress (bullet chart: bar = Projected Value, marker = Target)
```

The year-by-year projection (Phase 9) will be exported as `data/tableau/tableau_goal_projection.csv` with Period, Starting Balance, Contribution, Investment Return, Ending Balance, Target Amount and Goal Achievement %.
