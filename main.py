"""
Week 4 - Complete Data Analysis Project: E-commerce Sales Analysis

Pipeline: load -> validate & clean -> analyze -> visualize -> report

Run:
    python main.py
    python main.py --data data/sales_data.csv --out .
"""

import argparse
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # render charts to files without needing a display
import matplotlib.pyplot as plt
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
REQUIRED_COLUMNS = ["Date", "Product", "Quantity", "Price", "Customer_ID", "Region", "Total_Sales"]
NUMERIC_COLUMNS = ["Quantity", "Price", "Total_Sales"]
TEXT_COLUMNS = ["Product", "Customer_ID", "Region"]

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("sales_analysis")
logging.getLogger("matplotlib").setLevel(logging.WARNING)  # hide matplotlib's info-level chatter


class DataValidationError(Exception):
    """Raised when the input data cannot be analysed."""


# --------------------------------------------------------------------------- #
# 1. LOAD
# --------------------------------------------------------------------------- #
def load_data(path):
    """Read the CSV and make sure every required column is present."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError as exc:
        raise DataValidationError(f"Data file is empty: {path}") from exc

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataValidationError(f"Missing required columns: {missing}")
    if df.empty:
        raise DataValidationError("Data file has headers but no rows")

    log.info("Loaded %d rows x %d columns from %s", len(df), df.shape[1], path.name)
    return df


# --------------------------------------------------------------------------- #
# 2. CLEAN
# --------------------------------------------------------------------------- #
def clean_data(df):
    """
    Return a cleaned copy of the data plus a dict describing what was changed.

    Steps:
      - trim whitespace / standardise text casing
      - convert Date and numeric columns (bad values become NaN)
      - drop exact duplicate rows
      - drop rows missing values we cannot sensibly fill
      - drop rows with zero/negative quantity or price
      - recompute Total_Sales where it is missing or does not equal Quantity x Price
    """
    df = df.copy()
    log_info = {"rows_in": len(df)}

    for col in TEXT_COLUMNS:
        df[col] = df[col].astype("string").str.strip()
    df["Product"] = df["Product"].str.title()
    df["Region"] = df["Region"].str.title()

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    log_info["missing_values_before"] = int(df.isna().sum().sum())

    before = len(df)
    df = df.drop_duplicates()
    log_info["duplicates_removed"] = before - len(df)

    before = len(df)
    df = df.dropna(subset=["Date", "Product", "Quantity", "Price", "Region"])
    log_info["rows_missing_key_fields_removed"] = before - len(df)

    before = len(df)
    df = df[(df["Quantity"] > 0) & (df["Price"] > 0)]
    log_info["invalid_quantity_or_price_removed"] = before - len(df)

    expected = df["Quantity"] * df["Price"]
    mismatch = df["Total_Sales"].isna() | (df["Total_Sales"] != expected)
    df.loc[mismatch, "Total_Sales"] = expected[mismatch]
    log_info["total_sales_recomputed"] = int(mismatch.sum())

    df["Quantity"] = df["Quantity"].astype(int)
    df["Month"] = df["Date"].dt.to_period("M").astype(str)
    df = df.sort_values("Date").reset_index(drop=True)

    log_info["rows_out"] = len(df)
    if df.empty:
        raise DataValidationError("No valid rows left after cleaning")

    log.info("Cleaning summary: %s", log_info)
    return df, log_info


# --------------------------------------------------------------------------- #
# 3. ANALYZE
# --------------------------------------------------------------------------- #
def analyze(df):
    """Calculate the headline metrics and the grouped tables used for charts."""
    by_product = (
        df.groupby("Product")
        .agg(Revenue=("Total_Sales", "sum"), Units=("Quantity", "sum"), Orders=("Total_Sales", "size"))
        .sort_values("Revenue", ascending=False)
    )
    by_product["Share_%"] = (by_product["Revenue"] / by_product["Revenue"].sum() * 100).round(1)
    by_product["Avg_Order_Value"] = (by_product["Revenue"] / by_product["Orders"]).round(0)

    by_region = (
        df.groupby("Region")
        .agg(Revenue=("Total_Sales", "sum"), Orders=("Total_Sales", "size"))
        .sort_values("Revenue", ascending=False)
    )
    by_region["Share_%"] = (by_region["Revenue"] / by_region["Revenue"].sum() * 100).round(1)

    by_month = df.groupby("Month").agg(
        Revenue=("Total_Sales", "sum"),
        Orders=("Total_Sales", "size"),
        Active_Days=("Date", "nunique"),
    )
    # Average revenue per trading day makes a partial month comparable with full months
    by_month["Revenue_per_Day"] = (by_month["Revenue"] / by_month["Active_Days"]).round(0)

    region_product = df.pivot_table(
        index="Region", columns="Product", values="Total_Sales", aggfunc="sum", fill_value=0
    )

    top_order = df.loc[df["Total_Sales"].idxmax()]
    metrics = {
        "total_revenue": int(df["Total_Sales"].sum()),
        "total_orders": int(len(df)),
        "total_units": int(df["Quantity"].sum()),
        "avg_order_value": round(float(df["Total_Sales"].mean()), 2),
        "median_order_value": round(float(df["Total_Sales"].median()), 2),
        "avg_unit_price": round(float(df["Price"].mean()), 2),
        "unique_customers": int(df["Customer_ID"].nunique()),
        "date_start": df["Date"].min().date().isoformat(),
        "date_end": df["Date"].max().date().isoformat(),
        "best_product": by_product.index[0],
        "best_product_revenue": int(by_product["Revenue"].iloc[0]),
        "most_units_product": by_product["Units"].idxmax(),
        "best_region": by_region.index[0],
        "weakest_region": by_region.index[-1],
        "best_month": by_month["Revenue_per_Day"].idxmax(),
        "largest_order_value": int(top_order["Total_Sales"]),
        "largest_order_product": top_order["Product"],
        "largest_order_date": top_order["Date"].date().isoformat(),
        "price_qty_correlation": round(float(df["Price"].corr(df["Quantity"])), 3),
    }

    return {
        "metrics": metrics,
        "by_product": by_product,
        "by_region": by_region,
        "by_month": by_month,
        "region_product": region_product,
    }


# --------------------------------------------------------------------------- #
# 4. VISUALIZE
# --------------------------------------------------------------------------- #
COLORS = ["#2E86AB", "#F18F01", "#C73E1D", "#3B8B5A", "#6C4E9B"]


def _rupees(x, _pos=None):
    """Axis formatter: 1250000 -> ₹12.5L (Indian lakh notation)."""
    return f"₹{x / 1e5:.1f}L"


def _save(fig, out_dir, name):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    log.info("Saved chart: %s", path.relative_to(out_dir.parent) if out_dir.parent in path.parents else path)
    return path


def plot_revenue_by_product(by_product, out_dir):
    """Bar chart: compare revenue across product categories."""
    fig, ax = plt.subplots(figsize=(9, 5.5))
    bars = ax.bar(by_product.index, by_product["Revenue"], color=COLORS[: len(by_product)])
    for bar, share in zip(bars, by_product["Share_%"]):
        ax.annotate(
            f"{_rupees(bar.get_height())}\n({share}%)",
            (bar.get_x() + bar.get_width() / 2, bar.get_height()),
            ha="center", va="bottom", fontsize=9, xytext=(0, 3), textcoords="offset points",
        )
    ax.set_title("Revenue by Product Category", fontsize=14, fontweight="bold")
    ax.set_xlabel("Product")
    ax.set_ylabel("Revenue (₹ lakh)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_rupees))
    ax.set_ylim(0, by_product["Revenue"].max() * 1.18)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    return _save(fig, out_dir, "1_revenue_by_product_bar.png")


def plot_monthly_trend(by_month, out_dir):
    """Line chart: monthly revenue trend (total and per-day average)."""
    fig, ax1 = plt.subplots(figsize=(9, 5.5))
    months = by_month.index.tolist()

    ax1.plot(months, by_month["Revenue"], marker="o", linewidth=2.5, color=COLORS[0], label="Total revenue")
    ax1.set_ylabel("Total revenue (₹ lakh)", color=COLORS[0])
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(_rupees))
    ax1.tick_params(axis="y", labelcolor=COLORS[0])

    ax2 = ax1.twinx()
    ax2.plot(months, by_month["Revenue_per_Day"], marker="s", linestyle="--", linewidth=2,
             color=COLORS[1], label="Avg revenue per day")
    ax2.set_ylabel("Avg revenue per day (₹)", color=COLORS[1])
    ax2.tick_params(axis="y", labelcolor=COLORS[1])
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"₹{x / 1e3:.0f}K"))

    for m, days in zip(months, by_month["Active_Days"]):
        if days < 28:
            ax1.annotate(f"partial month\n({days} days)", (m, by_month.loc[m, "Revenue"]),
                         xytext=(-10, 0), textcoords="offset points", ha="right", va="center",
                         fontsize=8, color="gray")

    ax1.set_title("Monthly Sales Trend", fontsize=14, fontweight="bold")
    ax1.set_xlabel("Month")
    ax1.grid(alpha=0.3)
    lines = ax1.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
    labels = ax1.get_legend_handles_labels()[1] + ax2.get_legend_handles_labels()[1]
    ax1.legend(lines, labels, loc="lower left")
    return _save(fig, out_dir, "2_monthly_trend_line.png")


def plot_region_share(by_region, out_dir):
    """Pie chart: share of total revenue by region."""
    fig, ax = plt.subplots(figsize=(7, 7))
    explode = [0.06 if i == 0 else 0 for i in range(len(by_region))]
    ax.pie(
        by_region["Revenue"], labels=by_region.index, autopct="%1.1f%%", startangle=90,
        colors=COLORS[: len(by_region)], explode=explode,
        wedgeprops={"edgecolor": "white", "linewidth": 2}, textprops={"fontsize": 11},
    )
    ax.set_title("Revenue Share by Region", fontsize=14, fontweight="bold")
    return _save(fig, out_dir, "3_region_share_pie.png")


def plot_region_product_heatmap(region_product, out_dir):
    """Heatmap: which product sells best in which region."""
    fig, ax = plt.subplots(figsize=(9, 5))
    im = ax.imshow(region_product.values, cmap="Blues")
    ax.set_xticks(range(len(region_product.columns)), region_product.columns)
    ax.set_yticks(range(len(region_product.index)), region_product.index)
    threshold = region_product.values.max() * 0.6
    for i in range(region_product.shape[0]):
        for j in range(region_product.shape[1]):
            val = region_product.iat[i, j]
            ax.text(j, i, _rupees(val), ha="center", va="center", fontsize=9,
                    color="white" if val > threshold else "black")
    fig.colorbar(im, ax=ax, format=plt.FuncFormatter(_rupees), label="Revenue")
    ax.set_title("Revenue by Region and Product", fontsize=14, fontweight="bold")
    return _save(fig, out_dir, "4_region_product_heatmap.png")


def plot_order_value_distribution(df, out_dir):
    """Histogram: how order values are spread out."""
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(df["Total_Sales"], bins=15, color=COLORS[3], edgecolor="white")
    mean, median = df["Total_Sales"].mean(), df["Total_Sales"].median()
    ax.axvline(mean, color=COLORS[2], linestyle="--", label=f"Mean {_rupees(mean)}")
    ax.axvline(median, color=COLORS[1], linestyle=":", linewidth=2, label=f"Median {_rupees(median)}")
    ax.set_title("Distribution of Order Values", fontsize=14, fontweight="bold")
    ax.set_xlabel("Order value (₹ lakh)")
    ax.set_ylabel("Number of orders")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(_rupees))
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    return _save(fig, out_dir, "5_order_value_histogram.png")


def create_visualizations(df, results, out_dir):
    return [
        plot_revenue_by_product(results["by_product"], out_dir),
        plot_monthly_trend(results["by_month"], out_dir),
        plot_region_share(results["by_region"], out_dir),
        plot_region_product_heatmap(results["region_product"], out_dir),
        plot_order_value_distribution(df, out_dir),
    ]


# --------------------------------------------------------------------------- #
# 5. INSIGHTS & REPORT
# --------------------------------------------------------------------------- #
def generate_insights(results):
    """Turn the numbers into plain-English findings."""
    m = results["metrics"]
    bp, br, bm = results["by_product"], results["by_region"], results["by_month"]
    rp = results["region_product"]

    top2_share = bp["Share_%"].iloc[:2].sum()
    bottom2 = bp.index[-2:].tolist()
    top2_regions = br.index[:2].tolist()
    full_months = bm[bm["Active_Days"] >= 28]
    weakest_full = full_months["Revenue"].idxmin() if not full_months.empty else None
    best_cell = rp.stack().idxmax()

    first = (
        f"{m['best_product']} is the top revenue product at ₹{m['best_product_revenue']:,} "
        f"({bp['Share_%'].iloc[0]}% of revenue)"
    )
    most_orders = bp["Orders"].idxmax()
    if most_orders != m["best_product"]:
        first += (
            f", even though {most_orders} had more orders ({bp['Orders'].max()}). "
            f"{m['best_product']} wins on order value (₹{bp['Avg_Order_Value'].iloc[0]:,.0f} per order), not order count."
        )
    else:
        first += "."

    weak = m["weakest_region"]
    weak_aov = br.loc[weak, "Revenue"] / br.loc[weak, "Orders"]
    insights = [
        first,
        f"The top two products ({bp.index[0]} and {bp.index[1]}) bring in {top2_share:.1f}% of revenue. "
        f"{bottom2[0]} and {bottom2[1]} together add only {bp.loc[bottom2, 'Share_%'].sum():.1f}%.",
        f"{top2_regions[0]} and {top2_regions[1]} together generate {br['Share_%'].iloc[:2].sum():.1f}% of revenue. "
        f"{weak} is the weakest region at {br['Share_%'].iloc[-1]}% despite {br.loc[weak, 'Orders']} orders, "
        f"because its average order is only ₹{weak_aov:,.0f} vs ₹{m['avg_order_value']:,.0f} overall.",
        f"The strongest region-product pair is {best_cell[1]} in {best_cell[0]} "
        f"(₹{int(rp.stack().max()):,}).",
    ]
    if weakest_full is not None and len(full_months) > 1:
        dip = (1 - full_months.loc[weakest_full, "Revenue_per_Day"] / full_months["Revenue_per_Day"].max()) * 100
        insights.append(
            f"{weakest_full} was the slowest full month: revenue per day was {dip:.0f}% below the best month "
            f"({m['best_month']})."
        )
    insights.append(
        f"Average order value is ₹{m['avg_order_value']:,.0f} but the median is ₹{m['median_order_value']:,.0f}, "
        f"so a few very large orders (up to ₹{m['largest_order_value']:,}) pull the average up."
    )
    insights.append(
        f"Price and quantity are almost unrelated (correlation {m['price_qty_correlation']}), "
        f"so customers are not buying fewer units of expensive items in this data."
    )
    return insights


def recommendations(results):
    m = results["metrics"]
    bp = results["by_product"]
    low = " and ".join(bp.index[-2:])
    return [
        f"Protect the {m['best_product']} line: keep stock and promotions focused on it, since it drives the most revenue.",
        f"Investigate the {m['weakest_region']} region - test regional offers or bundles to lift its smaller average order size.",
        f"Bundle {low} with {bp.index[0]} purchases to lift the two lowest-revenue categories.",
        "Plan a promotion for the slowest month to smooth out the dip seen in the monthly trend.",
        "Collect more months of data before drawing firm seasonal conclusions (only ~3 months available).",
    ]


def write_report(df, results, clean_log, chart_paths, out_dir):
    """Write a Markdown report with metrics, tables, charts and insights."""
    m = results["metrics"]
    out_dir.mkdir(parents=True, exist_ok=True)
    rel = lambda p: "../visualizations/" + Path(p).name  # noqa: E731

    def table(frame, money_cols):
        f = frame.copy()
        for c in money_cols:
            f[c] = f[c].map(lambda v: f"₹{v:,.0f}")
        return f.to_markdown()

    lines = [
        "# E-commerce Sales Analysis Report",
        "",
        f"**Data:** `data/sales_data.csv` - {m['total_orders']} orders, {m['date_start']} to {m['date_end']}",
        "",
        "## 1. Key Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total revenue | ₹{m['total_revenue']:,} |",
        f"| Total orders | {m['total_orders']} |",
        f"| Units sold | {m['total_units']} |",
        f"| Average order value | ₹{m['avg_order_value']:,.2f} |",
        f"| Median order value | ₹{m['median_order_value']:,.2f} |",
        f"| Unique customers | {m['unique_customers']} |",
        f"| Best-selling product (revenue) | {m['best_product']} |",
        f"| Most units sold | {m['most_units_product']} |",
        f"| Top region | {m['best_region']} |",
        f"| Largest single order | ₹{m['largest_order_value']:,} ({m['largest_order_product']}, {m['largest_order_date']}) |",
        "",
        "## 2. Data Cleaning",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    lines += [f"| {k.replace('_', ' ').capitalize()} | {v} |" for k, v in clean_log.items()]
    lines += [
        "",
        "## 3. Revenue by Product",
        "",
        table(results["by_product"], ["Revenue", "Avg_Order_Value"]),
        "",
        f"![Revenue by product]({rel(chart_paths[0])})",
        "",
        "## 4. Monthly Trend",
        "",
        table(results["by_month"], ["Revenue", "Revenue_per_Day"]),
        "",
        "_April 2024 has only 9 days of data, so compare months using revenue per day._",
        "",
        f"![Monthly trend]({rel(chart_paths[1])})",
        "",
        "## 5. Revenue by Region",
        "",
        table(results["by_region"], ["Revenue"]),
        "",
        f"![Region share]({rel(chart_paths[2])})",
        "",
        f"![Region x product]({rel(chart_paths[3])})",
        "",
        "## 6. Order Value Distribution",
        "",
        f"![Order values]({rel(chart_paths[4])})",
        "",
        "## 7. Insights",
        "",
    ]
    lines += [f"{i}. {text}" for i, text in enumerate(generate_insights(results), 1)]
    lines += ["", "## 8. Recommendations", ""]
    lines += [f"- {text}" for text in recommendations(results)]
    lines += [
        "",
        "## 9. Limitations",
        "",
        "- Only 100 orders across ~3.3 months, so trends are indicative, not conclusive.",
        "- Every order has a different Customer_ID, so repeat-purchase behaviour cannot be analysed.",
        "- No cost data, so this report covers revenue, not profit.",
        "",
    ]

    path = out_dir / "analysis_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")

    summary_path = out_dir / "summary_tables.xlsx"
    try:
        with pd.ExcelWriter(summary_path) as xl:
            results["by_product"].to_excel(xl, sheet_name="By Product")
            results["by_region"].to_excel(xl, sheet_name="By Region")
            results["by_month"].to_excel(xl, sheet_name="By Month")
            results["region_product"].to_excel(xl, sheet_name="Region x Product")
    except ImportError:
        log.warning("openpyxl not installed - skipping Excel summary")

    log.info("Report written: %s", path)
    return path


def print_summary(results):
    m = results["metrics"]
    print("\n" + "=" * 52)
    print("        E-COMMERCE SALES ANALYSIS - SUMMARY")
    print("=" * 52)
    print(f"Period            : {m['date_start']} to {m['date_end']}")
    print(f"Total Revenue     : ₹{m['total_revenue']:,}")
    print(f"Total Orders      : {m['total_orders']}")
    print(f"Units Sold        : {m['total_units']}")
    print(f"Avg Order Value   : ₹{m['avg_order_value']:,.2f}")
    print(f"Best Product      : {m['best_product']} (₹{m['best_product_revenue']:,})")
    print(f"Top Region        : {m['best_region']}")
    print(f"Weakest Region    : {m['weakest_region']}")
    print("-" * 52)
    print("KEY INSIGHTS")
    for i, text in enumerate(generate_insights(results), 1):
        print(f" {i}. {text}")
    print("=" * 52 + "\n")


# --------------------------------------------------------------------------- #
# MAIN
# --------------------------------------------------------------------------- #
def run(data_path, out_root):
    out_root = Path(out_root)
    df_raw = load_data(data_path)
    df, clean_log = clean_data(df_raw)
    results = analyze(df)
    charts = create_visualizations(df, results, out_root / "visualizations")
    report = write_report(df, results, clean_log, charts, out_root / "report")
    print_summary(results)
    return {"df": df, "results": results, "charts": charts, "report": report}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="E-commerce sales analysis")
    p.add_argument("--data", default=BASE_DIR / "data" / "sales_data.csv", help="Path to sales CSV")
    p.add_argument("--out", default=BASE_DIR, help="Folder to write visualizations/ and report/ into")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    try:
        run(args.data, args.out)
    except (FileNotFoundError, DataValidationError) as err:
        log.error(err)
        sys.exit(1)
