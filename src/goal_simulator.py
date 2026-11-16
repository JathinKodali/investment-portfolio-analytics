"""
goal_simulator.py
-----------------
PHASES 7-9: financial goal simulator (design: docs/goal_simulator_concept.md).

WHAT: Given an initial lump sum P, a monthly investment (SIP) PMT, an
      expected annual return r, a period of n years and a target amount,
      calculates:
        FV of initial      = P x (1 + r)^n          (compounds yearly)
        FV of SIP          = PMT x ((1 + i)^m - 1) / i,  i = r/12, m = 12n
                             (PMT x m when r = 0; paid at month end)
        Projected value    = FV of initial + FV of SIP
        Goal gap           = target - projected value
        Achievement %      = projected value / target   (decimal)
        Required SIP       = (target - FV of initial) / (((1 + i)^m - 1) / i)
                             (0 if the initial amount alone reaches the target)
      and a year-by-year projection table for Tableau.
WHY:  The same formulas are written as Tableau calculated fields (Phases
      10-12), so these Python results are the check that Tableau is right.

Amounts are in Indian rupees (₹); the simulator models a personal goal and is
independent of the USD market data.
"""

from dataclasses import dataclass

import pandas as pd

from src.utils import GOAL_DEFAULTS, GOAL_MAX_YEARS


@dataclass
class GoalInputs:
    initial_investment: float
    monthly_investment: float
    target_amount: float
    annual_return_pct: float   # entered as a percent: 12 means 12%
    years: int

    def validate(self):
        problems = []
        if self.initial_investment < 0:
            problems.append("Initial investment cannot be negative.")
        if self.monthly_investment < 0:
            problems.append("Monthly investment cannot be negative.")
        if self.target_amount <= 0:
            problems.append("Target amount must be greater than zero.")
        if self.years <= 0:
            problems.append("Investment period must be at least 1 year.")
        if self.annual_return_pct <= -100:
            problems.append("Expected annual return must be above -100%.")
        if problems:
            raise ValueError(" ".join(problems))
        return self

    @property
    def annual_rate(self):
        return self.annual_return_pct / 100


def default_inputs():
    return GoalInputs(**GOAL_DEFAULTS)


def sip_factor(annual_rate, months):
    """Future value of ₹1 paid at the end of every month for 'months' months."""
    monthly_rate = annual_rate / 12
    if monthly_rate == 0:
        return float(months)
    return ((1 + monthly_rate) ** months - 1) / monthly_rate


def future_value_initial(initial, annual_rate, years):
    return initial * (1 + annual_rate) ** years


def future_value_sip(monthly, annual_rate, years):
    return monthly * sip_factor(annual_rate, 12 * years)


def required_monthly_investment(inputs):
    """Monthly SIP needed to reach the target exactly (0 if already reached)."""
    inputs.validate()
    gap = inputs.target_amount - future_value_initial(
        inputs.initial_investment, inputs.annual_rate, inputs.years)
    if gap <= 0:
        return 0.0
    return gap / sip_factor(inputs.annual_rate, 12 * inputs.years)


def simulate_goal(inputs):
    """All simulator outputs for one set of inputs, as a dict."""
    inputs.validate()
    fv_initial = future_value_initial(inputs.initial_investment, inputs.annual_rate, inputs.years)
    fv_sip = future_value_sip(inputs.monthly_investment, inputs.annual_rate, inputs.years)
    projected = fv_initial + fv_sip
    contributions = inputs.initial_investment + inputs.monthly_investment * 12 * inputs.years
    return {
        "Initial_Investment": inputs.initial_investment,
        "Monthly_Investment": inputs.monthly_investment,
        "Target_Amount": inputs.target_amount,
        "Expected_Annual_Return": inputs.annual_rate,
        "Investment_Period_Years": inputs.years,
        "FV_Initial": fv_initial,
        "FV_SIP": fv_sip,
        "Projected_Value": projected,
        "Total_Contributions": contributions,
        "Estimated_Growth": projected - contributions,
        "Goal_Gap": inputs.target_amount - projected,
        "Goal_Achievement": projected / inputs.target_amount,
        "Goal_Achieved": "Yes" if projected >= inputs.target_amount else "No",
        "Required_Monthly_Investment": required_monthly_investment(inputs),
    }


def projection_table(inputs):
    """
    Year-by-year table (Phase 9). Year 0 is the start. Each year's ending
    balance uses the same closed-form formulas, so the last row equals
    simulate_goal()['Projected_Value'].
    """
    inputs.validate()
    rows = []
    previous_end = inputs.initial_investment
    for year in range(0, inputs.years + 1):
        end = (future_value_initial(inputs.initial_investment, inputs.annual_rate, year)
               + future_value_sip(inputs.monthly_investment, inputs.annual_rate, year))
        contribution = 0.0 if year == 0 else inputs.monthly_investment * 12
        start = inputs.initial_investment if year == 0 else previous_end
        rows.append({
            "Year": year,
            "Starting_Balance": start,
            "Contribution": contribution,
            "Investment_Return": end - start - contribution,
            "Ending_Balance": end,
            "Total_Contributions": inputs.initial_investment + inputs.monthly_investment * 12 * year,
            "Target_Amount": inputs.target_amount,
            "Goal_Achievement": end / inputs.target_amount,
        })
        previous_end = end
    return pd.DataFrame(rows).round(2)


def tableau_scaffold(max_years=GOAL_MAX_YEARS):
    """
    Rows for the interactive Tableau simulator: one row per year per series.
    The values are calculated in Tableau from the parameters, so this table
    only holds the Year and Series labels.
    """
    series = ["Projected Value", "Total Contributions", "Target Amount"]
    return pd.DataFrame([{"Year": y, "Series": s, "Series_Order": k + 1}
                         for y in range(max_years + 1) for k, s in enumerate(series)])
