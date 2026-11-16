"""Phase 1 tests: sample portfolio creation."""
import pandas as pd
import pytest

from src.data_loader import create_sample_portfolio
from src.utils import SAMPLE_DATA_LABEL


def make_market():
    return pd.DataFrame({
        "Date": ["2025-01-03", "2025-01-02", "2025-01-02"],
        "Ticker": ["AAA", "AAA", "BBB"],
        "Company": ["A Corp", "A Corp", "B Corp"],
        "Sector": ["Tech", "Tech", "Energy"],
        "Close": [12.0, 10.0, 50.0],
    })


def test_sample_portfolio_uses_real_first_day_close():
    portfolio = create_sample_portfolio(make_market(), quantities={"AAA": 5, "BBB": 2})
    aaa = portfolio[portfolio["Ticker"] == "AAA"].iloc[0]
    assert aaa["Purchase_Price"] == 10.0                     # first trading day, not 12.0
    assert aaa["Investment_Amount"] == pytest.approx(50.0)   # 5 x 10


def test_sample_portfolio_is_clearly_labelled():
    portfolio = create_sample_portfolio(make_market(), quantities={"AAA": 1})
    assert (portfolio["Data_Label"] == SAMPLE_DATA_LABEL).all()


def test_ticker_without_prices_is_skipped():
    portfolio = create_sample_portfolio(make_market(), quantities={"AAA": 1, "ZZZ": 3})
    assert portfolio["Ticker"].tolist() == ["AAA"]
