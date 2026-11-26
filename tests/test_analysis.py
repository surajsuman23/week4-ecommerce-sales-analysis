"""Tests for the sales analysis pipeline. Run with:  python -m pytest -v"""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402

DATA = ROOT / "data" / "sales_data.csv"


@pytest.fixture
def raw():
    return main.load_data(DATA)


@pytest.fixture
def clean(raw):
    df, _ = main.clean_data(raw)
    return df


@pytest.fixture
def results(clean):
    return main.analyze(clean)


def make_csv(tmp_path, text):
    p = tmp_path / "sample.csv"
    p.write_text(text)
    return p


HEADER = "Date,Product,Quantity,Price,Customer_ID,Region,Total_Sales\n"


# ---------- Loading ----------
def test_load_shape(raw):
    assert raw.shape == (100, 7)


def test_load_missing_file():
    with pytest.raises(FileNotFoundError):
        main.load_data("does_not_exist.csv")


def test_load_missing_columns(tmp_path):
    p = make_csv(tmp_path, "Date,Product\n2024-01-01,Phone\n")
    with pytest.raises(main.DataValidationError, match="Missing required columns"):
        main.load_data(p)


def test_load_empty_file(tmp_path):
    p = make_csv(tmp_path, "")
    with pytest.raises(main.DataValidationError):
        main.load_data(p)


def test_load_header_only(tmp_path):
    p = make_csv(tmp_path, HEADER)
    with pytest.raises(main.DataValidationError, match="no rows"):
        main.load_data(p)


# ---------- Cleaning ----------
def test_clean_real_data_keeps_all_rows(raw):
    df, log = main.clean_data(raw)
    assert len(df) == 100
    assert log["duplicates_removed"] == 0
    assert log["total_sales_recomputed"] == 0


def test_clean_types(clean):
    assert pd.api.types.is_datetime64_any_dtype(clean["Date"])
    assert pd.api.types.is_integer_dtype(clean["Quantity"])


def test_clean_handles_dirty_rows(tmp_path):
    p = make_csv(
        tmp_path,
        HEADER
        + "2024-01-01, phone ,2,100,C1, east ,200\n"   # whitespace + casing
        + "2024-01-01, phone ,2,100,C1, east ,200\n"   # exact duplicate
        + "2024-01-02,Laptop,3,50,C2,West,\n"          # missing total -> recomputed
        + "2024-01-03,Tablet,1,80,C3,North,999\n"      # wrong total -> recomputed
        + "not-a-date,Tablet,1,80,C4,North,80\n"       # bad date -> dropped
        + "2024-01-05,Tablet,-1,80,C5,North,-80\n"     # negative qty -> dropped
        + "2024-01-06,Monitor,abc,80,C6,South,80\n",   # non-numeric qty -> dropped
    )
    df, log = main.clean_data(main.load_data(p))
    assert len(df) == 3
    assert log["duplicates_removed"] == 1
    assert log["total_sales_recomputed"] == 2
    assert set(df["Product"]) == {"Phone", "Laptop", "Tablet"}
    assert "East" in set(df["Region"])
    assert (df["Total_Sales"] == df["Quantity"] * df["Price"]).all()


def test_clean_all_invalid_raises(tmp_path):
    p = make_csv(tmp_path, HEADER + "bad,Phone,0,0,C1,East,0\n")
    with pytest.raises(main.DataValidationError, match="No valid rows"):
        main.clean_data(main.load_data(p))


# ---------- Analysis ----------
def test_total_revenue(results, clean):
    assert results["metrics"]["total_revenue"] == clean["Total_Sales"].sum() == 12_365_048


def test_best_product_and_region(results):
    m = results["metrics"]
    assert m["best_product"] == "Laptop"
    assert m["best_region"] == "North"
    assert m["weakest_region"] == "West"


def test_shares_sum_to_100(results):
    assert results["by_product"]["Share_%"].sum() == pytest.approx(100, abs=0.2)
    assert results["by_region"]["Share_%"].sum() == pytest.approx(100, abs=0.2)


def test_group_totals_match(results):
    total = results["metrics"]["total_revenue"]
    assert results["by_product"]["Revenue"].sum() == total
    assert results["by_region"]["Revenue"].sum() == total
    assert results["by_month"]["Revenue"].sum() == total
    assert results["region_product"].values.sum() == total


def test_monthly_partial_month_detected(results):
    assert results["by_month"].loc["2024-04", "Active_Days"] == 9


def test_insights_generated(results):
    insights = main.generate_insights(results)
    assert len(insights) >= 5
    assert all(isinstance(s, str) and s for s in insights)


# ---------- End-to-end ----------
def test_full_pipeline(tmp_path):
    out = main.run(DATA, tmp_path)
    assert len(out["charts"]) == 5
    for chart in out["charts"]:
        assert chart.exists() and chart.stat().st_size > 10_000
    report = out["report"].read_text(encoding="utf-8")
    assert "Total revenue" in report and "Insights" in report
