"""Tests for Phases 3-9: portfolio value, risk, concentration, benchmark, goal simulator."""
import math

import numpy as np
import pandas as pd
import pytest

from src.goal_simulator import (
    GoalInputs,
    projection_table,
    required_monthly_investment,
    simulate_goal,
    sip_factor,
    tableau_scaffold,
)
from src.portfolio_metrics import (
    calculate_holdings,
    calculate_portfolio_summary,
    calculate_sector_exposure,
    concentration_label,
    herfindahl_index,
    portfolio_value_history,
)
from src.risk_metrics import (
    BENCHMARK_GROUP,
    annualized_volatility,
    assign_risk_groups,
    build_benchmark_comparison,
    calculate_risk_metrics,
    max_drawdown,
    sharpe_ratio,
)


@pytest.fixture
def market():
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    rows = []
    for ticker, sector, closes in [("AAA", "Tech", [10, 11, 12]), ("BBB", "Energy", [20, 18, 19])]:
        for d, c in zip(dates, closes):
            rows.append({"Date": d, "Ticker": ticker, "Company": ticker + " Inc.", "Sector": sector,
                         "Close": float(c), "Adjusted_Close": float(c)})
    df = pd.DataFrame(rows)
    df["Daily_Return"] = df.groupby("Ticker")["Adjusted_Close"].pct_change()
    return df


@pytest.fixture
def portfolio():
    return pd.DataFrame({
        "Ticker": ["AAA", "BBB"], "Company": ["AAA Inc.", "BBB Inc."], "Sector": ["Tech", "Energy"],
        "Quantity": [10, 5], "Purchase_Price": [10.0, 20.0], "Investment_Amount": [100.0, 100.0],
        "Purchase_Date": pd.to_datetime(["2025-01-02", "2025-01-02"]),
        "Data_Label": ["SAMPLE / DEMO DATA"] * 2,
    })


# ---------------------------- Phase 3 ----------------------------
def test_holdings_value_and_profit_loss(portfolio, market):
    h = calculate_holdings(portfolio, market).set_index("Ticker")
    assert h.loc["AAA", "Current_Value"] == pytest.approx(120.0)   # 10 x 12
    assert h.loc["BBB", "Profit_Loss"] == pytest.approx(-5.0)      # 5 x 19 - 100
    assert h.loc["AAA", "Return_Percentage"] == pytest.approx(0.20)
    assert h["Portfolio_Weight"].sum() == pytest.approx(1.0)
    assert h["Investment_Weight"].sum() == pytest.approx(1.0)


def test_holdings_missing_price_raises(portfolio, market):
    with pytest.raises(ValueError):
        calculate_holdings(portfolio, market[market["Ticker"] == "AAA"])


def test_portfolio_summary_kpis(portfolio, market):
    h = calculate_holdings(portfolio, market)
    s = calculate_portfolio_summary(h, calculate_sector_exposure(h)).iloc[0]
    assert s.Total_Investment == pytest.approx(200.0)
    assert s.Current_Value == pytest.approx(215.0)
    assert s.Portfolio_Return == pytest.approx(0.075)
    assert s.Best_Asset_Ticker == "AAA" and s.Worst_Asset_Ticker == "BBB"


def test_portfolio_value_history(portfolio, market):
    v = portfolio_value_history(portfolio, market)
    assert v["Portfolio_Value"].tolist() == pytest.approx([200.0, 200.0, 215.0])


# ---------------------------- Phase 4 ----------------------------
def test_volatility_of_constant_returns_is_zero():
    assert annualized_volatility([0.01] * 10) == pytest.approx(0.0)


def test_max_drawdown():
    assert max_drawdown([100, 120, 90, 130, 117]) == pytest.approx(-0.25)
    assert max_drawdown([1, 2, 3]) == 0.0


def test_sharpe_ratio_handles_zero_volatility():
    assert sharpe_ratio(0.10, 0.20, 0.04) == pytest.approx(0.3)
    assert math.isnan(sharpe_ratio(0.10, 0.0))


def test_risk_groups_are_terciles():
    groups = assign_risk_groups([0.30, 0.10, 0.20, 0.25, 0.15, 0.35]).tolist()
    assert groups == ["High", "Low", "Medium", "Medium", "Low", "High"]


def test_risk_table_includes_benchmark(market):
    bench = market[market["Ticker"] == "AAA"][["Date", "Adjusted_Close", "Daily_Return"]]
    risk = calculate_risk_metrics(market, bench)
    assert (risk["Risk_Group"] == BENCHMARK_GROUP).sum() == 1
    assert len(risk) == 3


# ---------------------------- Phase 5 ----------------------------
def test_hhi_equal_weights_and_single_holding():
    assert herfindahl_index([1, 1, 1, 1]) == pytest.approx(0.25)
    assert herfindahl_index([5]) == pytest.approx(1.0)
    assert concentration_label(0.10) == "Diversified"
    assert concentration_label(0.20) == "Moderately concentrated"
    assert concentration_label(0.50) == "Concentrated"


def test_sector_weights_add_to_one(portfolio, market):
    sectors = calculate_sector_exposure(calculate_holdings(portfolio, market))
    assert sectors["Sector_Weight"].sum() == pytest.approx(1.0)


# ---------------------------- Phase 6 ----------------------------
def test_benchmark_comparison_starts_at_100(portfolio, market):
    history = portfolio_value_history(portfolio, market)
    bench = pd.DataFrame({"Date": history["Date"], "Close": [50.0, 55.0, 60.0]})
    out = build_benchmark_comparison(history, bench)
    first = out.sort_values("Date").groupby("Series").head(1)
    assert first["Index_Value"].tolist() == pytest.approx([100.0, 100.0])
    last = out[out["Series"] == "S&P 500"].iloc[-1]
    assert last["Index_Value"] == pytest.approx(120.0)


# ---------------------------- Phases 7-9 ----------------------------
def brief_example(**changes):
    values = dict(initial_investment=200_000, monthly_investment=5_000, target_amount=1_000_000,
                  annual_return_pct=12, years=5)
    values.update(changes)
    return GoalInputs(**values)


def test_required_sip_matches_worked_example():
    assert required_monthly_investment(brief_example()) == pytest.approx(7928.67, abs=0.01)


def test_required_sip_reaches_target_exactly():
    sip = required_monthly_investment(brief_example())
    result = simulate_goal(brief_example(monthly_investment=sip))
    assert result["Projected_Value"] == pytest.approx(1_000_000, rel=1e-9)
    assert result["Goal_Achieved"] == "Yes"


def test_zero_return_edge_case():
    assert sip_factor(0.0, 60) == 60
    result = simulate_goal(brief_example(annual_return_pct=0))
    assert result["Projected_Value"] == pytest.approx(200_000 + 5_000 * 60)
    assert required_monthly_investment(brief_example(annual_return_pct=0)) == pytest.approx(800_000 / 60)


def test_target_already_reached_needs_no_sip():
    assert required_monthly_investment(brief_example(initial_investment=2_000_000)) == 0.0


@pytest.mark.parametrize("bad", [dict(initial_investment=-1), dict(monthly_investment=-1),
                                 dict(target_amount=0), dict(years=0)])
def test_invalid_inputs_rejected(bad):
    with pytest.raises(ValueError):
        simulate_goal(brief_example(**bad))


def test_projection_table_matches_simulation():
    table = projection_table(brief_example())
    assert table["Year"].tolist() == list(range(6))
    assert table.iloc[-1]["Ending_Balance"] == pytest.approx(
        simulate_goal(brief_example())["Projected_Value"], abs=0.01)
    # Each year: start + contribution + growth = end.
    rows = table.iloc[1:]
    assert np.allclose(rows["Starting_Balance"] + rows["Contribution"] + rows["Investment_Return"],
                       rows["Ending_Balance"], atol=0.02)


def test_scaffold_has_three_series_per_year():
    s = tableau_scaffold(10)
    assert len(s) == 33 and set(s["Series"]) == {"Projected Value", "Total Contributions", "Target Amount"}
