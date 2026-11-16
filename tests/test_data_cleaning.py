"""Phase 1 tests: data cleaning rules."""
import pandas as pd
import pytest

from src.data_cleaning import clean_market_data, clean_portfolio_data


def make_market_rows(rows):
    """Build a small market DataFrame from (date, ticker, close) tuples."""
    return pd.DataFrame([{
        "Date": date, "Ticker": ticker, "Company": "Apple Inc.", "Sector": "Technology",
        "Open": close, "High": close + 1, "Low": close - 1, "Close": close,
        "Adjusted_Close": close, "Volume": 1000,
    } for date, ticker, close in rows])


def test_dates_are_converted_and_rows_sorted():
    raw = make_market_rows([("2025-01-03", "AAPL", 101), ("2025-01-02", "AAPL", 100)])
    clean, _ = clean_market_data(raw)
    assert pd.api.types.is_datetime64_any_dtype(clean["Date"])
    assert list(clean["Close"]) == [100, 101]


def test_duplicate_rows_are_removed():
    raw = make_market_rows([("2025-01-02", "AAPL", 100), ("2025-01-02", "AAPL", 100),
                            ("2025-01-03", "AAPL", 101)])
    clean, report = clean_market_data(raw)
    assert len(clean) == 2
    assert report["exact_duplicates_removed"] == 1


def test_same_ticker_and_date_twice_keeps_one_row():
    raw = make_market_rows([("2025-01-02", "AAPL", 100), ("2025-01-02", "AAPL", 105)])
    clean, report = clean_market_data(raw)
    assert len(clean) == 1
    assert report["ticker_date_duplicates_removed"] == 1


def test_negative_and_zero_prices_are_removed():
    raw = make_market_rows([("2025-01-02", "AAPL", 100), ("2025-01-03", "AAPL", -5),
                            ("2025-01-06", "AAPL", 0.5)])
    raw.loc[2, "Low"] = 0  # a price of 0 is impossible too
    clean, report = clean_market_data(raw)
    assert len(clean) == 1
    assert report["non_positive_prices_removed"] == 2


def test_text_values_in_price_columns_are_not_kept():
    raw = make_market_rows([("2025-01-02", "AAPL", 100), ("2025-01-03", "AAPL", 101)])
    raw["Close"] = raw["Close"].astype(object)
    raw.loc[1, "Close"] = "n/a"
    clean, report = clean_market_data(raw)
    assert len(clean) == 1
    assert report["rows_missing_prices_removed"] == 1


def test_invalid_dates_are_removed():
    raw = make_market_rows([("2025-01-02", "AAPL", 100), ("not a date", "AAPL", 101)])
    clean, report = clean_market_data(raw)
    assert len(clean) == 1
    assert report["invalid_dates_removed"] == 1


def test_missing_adjusted_close_falls_back_to_close():
    raw = make_market_rows([("2025-01-02", "AAPL", 100)]).drop(columns="Adjusted_Close")
    clean, _ = clean_market_data(raw)
    assert clean.loc[0, "Adjusted_Close"] == 100


def test_ticker_spacing_and_case_are_fixed():
    raw = make_market_rows([("2025-01-02", " aapl ", 100), ("2025-01-03", "AAPL", 101)])
    clean, _ = clean_market_data(raw)
    assert clean["Ticker"].unique().tolist() == ["AAPL"]


def test_missing_sector_is_filled_from_reference_list():
    raw = make_market_rows([("2025-01-02", "AAPL", 100)])
    raw["Sector"] = None
    clean, report = clean_market_data(raw)
    assert clean.loc[0, "Sector"] == "Technology"
    assert report["missing_sectors"] == []


def test_inconsistent_company_names_are_unified():
    raw = make_market_rows([("2025-01-02", "AAPL", 100), ("2025-01-03", "AAPL", 101),
                            ("2025-01-06", "AAPL", 102)])
    raw.loc[2, "Company"] = "Apple"
    clean, report = clean_market_data(raw)
    assert clean["Company"].unique().tolist() == ["Apple Inc."]
    assert len(report["ticker_conflicts_fixed"]) == 1


def test_missing_trading_days_are_reported():
    raw = make_market_rows([("2025-01-02", "AAPL", 100), ("2025-01-03", "AAPL", 101),
                            ("2025-01-02", "XOM", 50)])
    _, report = clean_market_data(raw)
    assert report["stocks_with_missing_days"] == {"XOM": 1}


def test_missing_required_column_raises_clear_error():
    raw = make_market_rows([("2025-01-02", "AAPL", 100)]).drop(columns="Close")
    with pytest.raises(ValueError, match="Close"):
        clean_market_data(raw)


def test_portfolio_investment_amount_is_recalculated():
    market, _ = clean_market_data(make_market_rows([("2025-01-02", "AAPL", 100)]))
    portfolio = pd.DataFrame([{"Ticker": "AAPL", "Quantity": 10, "Purchase_Price": 100,
                               "Investment_Amount": 999, "Purchase_Date": "2025-01-02"}])
    clean, report = clean_portfolio_data(portfolio, market)
    assert clean.loc[0, "Investment_Amount"] == 1000
    assert report["investment_amount_corrected"] == 1


def test_portfolio_rows_with_invalid_quantity_are_removed():
    market, _ = clean_market_data(make_market_rows([("2025-01-02", "AAPL", 100)]))
    portfolio = pd.DataFrame([
        {"Ticker": "AAPL", "Quantity": 10, "Purchase_Price": 100, "Purchase_Date": "2025-01-02"},
        {"Ticker": "AAPL", "Quantity": -3, "Purchase_Price": 100, "Purchase_Date": "2025-01-03"},
    ])
    clean, report = clean_portfolio_data(portfolio, market)
    assert len(clean) == 1
    assert report["invalid_rows_removed"] == 1


def test_portfolio_ticker_without_prices_is_reported():
    market, _ = clean_market_data(make_market_rows([("2025-01-02", "AAPL", 100)]))
    portfolio = pd.DataFrame([{"Ticker": "TSLA", "Quantity": 1, "Purchase_Price": 200,
                               "Purchase_Date": "2025-01-02"}])
    _, report = clean_portfolio_data(portfolio, market)
    assert report["tickers_without_market_data"] == ["TSLA"]
