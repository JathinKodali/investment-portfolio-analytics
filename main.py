"""
main.py
-------
Runs the Investment Portfolio and Market Analytics pipeline.

  Phase 1      data foundation and cleaning
  Phase 2      market analytics (returns)
  Phase 3      portfolio performance (current value, profit / loss)
  Phase 4      risk and volatility (+ Sharpe ratio, max drawdown)
  Phase 5      sector exposure and concentration (HHI)
  Phase 6      benchmark comparison with the S&P 500
  Phases 7-9   goal simulator and projection table
  (Phases 10-12 are the interactive Tableau dashboards built by
   tableau/build_workbook.py from the files written here.)

How to run (from the investment-portfolio-analytics folder):
    python main.py              # use the raw data already saved in data/raw/
    python main.py --download   # download fresh prices first (needs yfinance)
"""

import argparse

from src.data_cleaning import (
    build_quality_report,
    clean_market_data,
    clean_portfolio_data,
    print_dataset_overview,
    save_quality_report,
)
from src.data_loader import (
    download_market_data,
    load_market_data,
    load_portfolio_data,
    save_raw_market_data,
)
from src.market_metrics import (
    build_tableau_allocation_data,
    build_tableau_market_data,
    calculate_market_metrics,
    export_tableau_files,
    summarise_stock_performance,
    validate_tableau_market_data,
)
from src.goal_simulator import (
    default_inputs,
    projection_table,
    simulate_goal,
    tableau_scaffold,
)
from src.portfolio_metrics import (
    calculate_holdings,
    calculate_portfolio_summary,
    calculate_sector_exposure,
    portfolio_value_history,
)
from src.risk_metrics import (
    build_benchmark_comparison,
    calculate_risk_metrics,
    download_benchmark_data,
    load_benchmark_data,
    summarise_benchmark,
)
from src.utils import (
    END_DATE,
    FINAL_SUMMARY_FILE,
    RAW_BENCHMARK_FILE,
    START_DATE,
    TABLEAU_BENCHMARK_FILE,
    TABLEAU_GOAL_PROJECTION_FILE,
    TABLEAU_GOAL_SCAFFOLD_FILE,
    TABLEAU_HOLDINGS_FILE,
    TABLEAU_RISK_FILE,
    TABLEAU_SECTOR_FILE,
    TABLEAU_SUMMARY_FILE,
    CLEAN_MARKET_FILE,
    CLEAN_PORTFOLIO_FILE,
    RAW_MARKET_FILE,
    STOCK_PERFORMANCE_FILE,
    print_header,
    save_csv,
)


def run_phase_1(download=False):
    """PHASE 1 - load the raw data, clean it, and report on its quality."""
    print_header("PHASE 1 - PROJECT STRUCTURE AND DATA FOUNDATION")

    # Step 1: get the raw market data (download only if asked or missing).
    if download or not RAW_MARKET_FILE.exists():
        print("Downloading market data from Yahoo Finance...")
        save_raw_market_data(download_market_data())

    print("Loading raw data...")
    raw_market = load_market_data()
    raw_portfolio = load_portfolio_data(raw_market)

    # Step 2: clean both datasets.
    print("Cleaning data...")
    clean_market, market_report = clean_market_data(raw_market)
    clean_portfolio, portfolio_report = clean_portfolio_data(raw_portfolio, clean_market)

    save_csv(clean_market, CLEAN_MARKET_FILE)
    save_csv(clean_portfolio, CLEAN_PORTFOLIO_FILE)

    # Step 3: validation printout required by the brief.
    print_dataset_overview(clean_market, "Clean market data")
    print_dataset_overview(clean_portfolio, "Clean portfolio data", date_column="Purchase_Date")

    report_text = build_quality_report(market_report, portfolio_report,
                                       clean_market, clean_portfolio)
    save_quality_report(report_text)
    print("\n" + report_text)
    print("\n  Saved: outputs/data_quality_report.txt")

    return clean_market, clean_portfolio


def run_phase_2(clean_market, clean_portfolio):
    """PHASE 2 - calculate returns and export the Tableau datasets."""
    print_header("PHASE 2 - BASIC MARKET ANALYTICS")

    market_with_metrics = calculate_market_metrics(clean_market)

    tableau_market = build_tableau_market_data(market_with_metrics)
    tableau_allocation = build_tableau_allocation_data(clean_portfolio)

    # Verify the dataset before handing it to Tableau.
    problems = validate_tableau_market_data(tableau_market)
    if problems:
        raise ValueError("Tableau market data failed validation: " + "; ".join(problems))
    print("Tableau market data passed validation.")

    export_tableau_files(tableau_market, tableau_allocation)

    summary = summarise_stock_performance(market_with_metrics)
    save_csv(summary, STOCK_PERFORMANCE_FILE)

    # Readable summary: returns shown as percentages for people,
    # while the CSV files keep them as decimals for Tableau.
    print("\nStock performance over the full period (sorted by total return):")
    display = summary[["Ticker", "Company", "Start_Close", "End_Close",
                       "Period_Price_Change_Percentage", "Cumulative_Return"]].copy()
    display["Cumulative_Return"] = (display["Cumulative_Return"] * 100).map("{:+.1f}%".format)
    display["Period_Price_Change_Percentage"] = display["Period_Price_Change_Percentage"].map("{:+.1f}%".format)
    display.columns = ["Ticker", "Company", "Start $", "End $", "Price change", "Total return"]
    print(display.to_string(index=False, float_format="{:,.2f}".format))

    print("\nPortfolio allocation (SAMPLE / DEMO DATA):")
    allocation = tableau_allocation[["Ticker", "Company", "Investment_Amount"]].copy()
    allocation["Share"] = allocation["Investment_Amount"] / allocation["Investment_Amount"].sum()
    allocation["Share"] = (allocation["Share"] * 100).map("{:.1f}%".format)
    print(allocation.to_string(index=False, float_format="{:,.2f}".format))
    print(f"Total invested: ${tableau_allocation['Investment_Amount'].sum():,.2f}")

    return market_with_metrics


def pct(value):
    return f"{value * 100:+.1f}%"


def run_phases_3_to_6(market_with_metrics, clean_portfolio, download=False):
    """PHASES 3-6 - portfolio value, risk, sector exposure, benchmark."""
    print_header("PHASE 3 - PORTFOLIO PERFORMANCE (SAMPLE / DEMO DATA)")
    holdings = calculate_holdings(clean_portfolio, market_with_metrics)
    sectors = calculate_sector_exposure(holdings)
    summary = calculate_portfolio_summary(holdings, sectors)

    show = holdings[["Ticker", "Investment_Amount", "Current_Value", "Profit_Loss",
                     "Return_Percentage", "Portfolio_Weight"]].copy()
    show["Return_Percentage"] = show["Return_Percentage"].map(pct)
    show["Portfolio_Weight"] = (show["Portfolio_Weight"] * 100).map("{:.1f}%".format)
    print(show.to_string(index=False, float_format="{:,.2f}".format))
    k = summary.iloc[0]
    print(f"\nInvested ${k.Total_Investment:,.2f} -> worth ${k.Current_Value:,.2f} on "
          f"{k.Valuation_Date:%d %b %Y}: P/L ${k.Total_Profit_Loss:,.2f} ({pct(k.Portfolio_Return)})")
    print(f"Best: {k.Best_Asset} {pct(k.Best_Asset_Return)} | Worst: {k.Worst_Asset} {pct(k.Worst_Asset_Return)}")

    print_header("PHASE 4 - RISK AND VOLATILITY")
    if download or not RAW_BENCHMARK_FILE.exists():
        print("Downloading S&P 500 prices from Yahoo Finance...")
        download_benchmark_data(START_DATE, END_DATE)
    benchmark = load_benchmark_data()
    risk = calculate_risk_metrics(market_with_metrics, benchmark)
    show = risk[["Ticker", "Annualized_Return", "Annualized_Volatility", "Sharpe_Ratio",
                 "Max_Drawdown", "Risk_Group"]].copy()
    for col in ["Annualized_Return", "Annualized_Volatility", "Max_Drawdown"]:
        show[col] = (show[col] * 100).map("{:.1f}%".format)
    print(show.to_string(index=False, float_format="{:.2f}".format))

    print_header("PHASE 5 - SECTOR EXPOSURE AND CONCENTRATION")
    show = sectors[["Sector", "Current_Value", "Sector_Weight"]].copy()
    show["Sector_Weight"] = (show["Sector_Weight"] * 100).map("{:.1f}%".format)
    print(show.to_string(index=False, float_format="{:,.2f}".format))
    print(f"HHI (holdings) = {k.HHI_Holdings:.3f} -> {k.Concentration_Level}, "
          f"equivalent to {k.Effective_Holdings:.1f} equal-sized holdings")

    print_header("PHASE 6 - BENCHMARK COMPARISON (S&P 500)")
    history = portfolio_value_history(clean_portfolio, market_with_metrics)
    comparison = build_benchmark_comparison(history, benchmark)
    bench = summarise_benchmark(comparison)
    print(f"Sample portfolio {pct(bench['Portfolio_Growth'])} vs S&P 500 "
          f"{pct(bench['Benchmark_Growth'])} (price only) -> excess {pct(bench['Excess_Return'])}")

    summary["Portfolio_Growth_vs_Start"] = bench["Portfolio_Growth"]
    summary["Benchmark_Growth"] = bench["Benchmark_Growth"]
    summary["Excess_Return_vs_Benchmark"] = bench["Excess_Return"]

    # Risk highlights for the Risk & Return dashboard KPI tiles.
    stocks = risk[risk["Risk_Group"] != "Benchmark"]
    index_row = risk[risk["Risk_Group"] == "Benchmark"].iloc[0]
    highlights = {
        "Most_Volatile": stocks.loc[stocks["Annualized_Volatility"].idxmax()],
        "Least_Volatile": stocks.loc[stocks["Annualized_Volatility"].idxmin()],
        "Best_Sharpe": stocks.loc[stocks["Sharpe_Ratio"].idxmax()],
        "Deepest_Drawdown": stocks.loc[stocks["Max_Drawdown"].idxmin()],
    }
    for key, row in highlights.items():
        summary[key] = row["Company"]
    summary["Most_Volatile_Value"] = highlights["Most_Volatile"]["Annualized_Volatility"]
    summary["Least_Volatile_Value"] = highlights["Least_Volatile"]["Annualized_Volatility"]
    summary["Best_Sharpe_Value"] = highlights["Best_Sharpe"]["Sharpe_Ratio"]
    summary["Deepest_Drawdown_Value"] = highlights["Deepest_Drawdown"]["Max_Drawdown"]
    summary["Benchmark_Volatility"] = index_row["Annualized_Volatility"]
    summary["Benchmark_Max_Drawdown"] = index_row["Max_Drawdown"]

    print("\nSaving Tableau files...")
    save_csv(holdings.round(6), TABLEAU_HOLDINGS_FILE)
    save_csv(summary.round(6), TABLEAU_SUMMARY_FILE)
    save_csv(sectors.round(6), TABLEAU_SECTOR_FILE)
    save_csv(risk.round(6), TABLEAU_RISK_FILE)
    save_csv(comparison, TABLEAU_BENCHMARK_FILE)
    return summary, risk, bench


def run_phases_7_to_9():
    """PHASES 7-9 - goal simulator with the default inputs."""
    print_header("PHASES 7-9 - GOAL SIMULATOR (default inputs, amounts in Rs)")
    inputs = default_inputs()
    result = simulate_goal(inputs)
    print(f"Initial Rs {inputs.initial_investment:,.0f} + Rs {inputs.monthly_investment:,.0f}/month "
          f"for {inputs.years} years at {inputs.annual_return_pct:.0f}% -> target Rs {inputs.target_amount:,.0f}")
    print(f"  Projected value       Rs {result['Projected_Value']:,.0f}")
    print(f"  Total contributions   Rs {result['Total_Contributions']:,.0f}")
    print(f"  Estimated growth      Rs {result['Estimated_Growth']:,.0f}")
    print(f"  Goal gap              Rs {result['Goal_Gap']:,.0f}")
    print(f"  Goal achievement      {result['Goal_Achievement'] * 100:.1f}%  (achieved: {result['Goal_Achieved']})")
    print(f"  Required monthly SIP  Rs {result['Required_Monthly_Investment']:,.2f}")

    save_csv(projection_table(inputs), TABLEAU_GOAL_PROJECTION_FILE)
    save_csv(tableau_scaffold(), TABLEAU_GOAL_SCAFFOLD_FILE)
    return result


def write_final_summary(summary, risk, bench, goal):
    k = summary.iloc[0]
    stocks = risk[risk["Risk_Group"] != "Benchmark"]
    lines = [
        "INVESTMENT PORTFOLIO AND MARKET ANALYTICS - FINAL SUMMARY",
        "=" * 60,
        f"Market data: {START_DATE} to {END_DATE}, 6 US stocks + S&P 500 (Yahoo Finance, USD)",
        "Portfolio: SAMPLE / DEMO holdings bought on the first trading day",
        "",
        "Portfolio (Phase 3)",
        f"  Invested            ${k.Total_Investment:,.2f}",
        f"  Current value       ${k.Current_Value:,.2f}  ({k.Valuation_Date:%d %b %Y})",
        f"  Profit / loss       ${k.Total_Profit_Loss:,.2f}  ({pct(k.Portfolio_Return)})",
        f"  Best / worst        {k.Best_Asset} {pct(k.Best_Asset_Return)} / {k.Worst_Asset} {pct(k.Worst_Asset_Return)}",
        "",
        "Risk (Phase 4)",
        f"  Most volatile       {stocks.iloc[-1].Company} ({stocks.iloc[-1].Annualized_Volatility * 100:.1f}% a year)",
        f"  Least volatile      {stocks.iloc[0].Company} ({stocks.iloc[0].Annualized_Volatility * 100:.1f}% a year)",
        f"  Best Sharpe ratio   {stocks.loc[stocks.Sharpe_Ratio.idxmax()].Company} ({stocks.Sharpe_Ratio.max():.2f})",
        "",
        "Diversification (Phase 5)",
        f"  HHI {k.HHI_Holdings:.3f} -> {k.Concentration_Level} ({k.Effective_Holdings:.1f} effective holdings)",
        "",
        "Benchmark (Phase 6)",
        f"  Portfolio {pct(bench['Portfolio_Growth'])} vs S&P 500 {pct(bench['Benchmark_Growth'])}"
        f" -> excess {pct(bench['Excess_Return'])}",
        "",
        "Goal simulator (Phases 7-9, default inputs, Rs)",
        f"  Projected value {goal['Projected_Value']:,.0f} of target {goal['Target_Amount']:,.0f}"
        f" ({goal['Goal_Achievement'] * 100:.1f}%)",
        f"  Required monthly SIP {goal['Required_Monthly_Investment']:,.0f}",
    ]
    FINAL_SUMMARY_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))
    print("\n  Saved: outputs/final_project_summary.txt")


def main():
    parser = argparse.ArgumentParser(description="Run the full analytics pipeline (Phases 1-9).")
    parser.add_argument("--download", action="store_true",
                        help="download fresh market data from Yahoo Finance first")
    args = parser.parse_args()

    clean_market, clean_portfolio = run_phase_1(download=args.download)
    market_with_metrics = run_phase_2(clean_market, clean_portfolio)
    summary, risk, bench = run_phases_3_to_6(market_with_metrics, clean_portfolio, args.download)
    goal = run_phases_7_to_9()
    write_final_summary(summary, risk, bench, goal)

    print_header("DONE - all analytics phases completed")
    print("Next: python tableau/build_workbook.py, then open tableau/Investment_Portfolio_Analytics.twbx")


if __name__ == "__main__":
    main()
