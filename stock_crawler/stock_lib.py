import yfinance as yf
from datetime import date, datetime
from pathlib import Path
import sqlite3
import pandas as pd
from scipy.stats import norm

# DB LOCATION
DB_PATH = Path("../stocks.db")


# CRAWL FUNCTIONS
def crawl_stock(symbol:str, start_date: date, end_date: date):
    stock_hist = yf.Ticker(symbol).history(start=start_date, end=end_date)
    # stock_hist["percent_change"] = stock_hist["Close"].pct_change()
    return stock_hist

def crawl_company(symbol:str):
    company = yf.Ticker(symbol).info
    return company

# DB FUNCTIONS
def get_db_connection():
    return sqlite3.connect(DB_PATH)

# UPSERT DATA
def upsert_stock(symbol: str, df: pd.DataFrame):
    if df.empty:
        return {"status": "Upsert failed", "error": "Dataframe is empty"}

    sql = """
    INSERT INTO stock (symbol, date, open, close, high, low, volume, dividends, stock_split)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(symbol, date) DO UPDATE SET
        open = excluded.open,
        close = excluded.close,
        high = excluded.high,
        low = excluded.low,
        volume = excluded.volume,
        dividends = excluded.dividends,
        stock_split = excluded.stock_split
    """

    rows = []
    for date_index, row in df.iterrows():
        date_str = (
            date_index.strftime("%Y-%m-%d")
            if hasattr(date_index, "strftime")
            else str(date_index)
        )
        rows.append(
            (
                symbol,
                date_str,
                row.get("Open"),
                row.get("Close"),
                row.get("High"),
                row.get("Low"),
                row.get("Volume"),
                row.get("Dividends", 0),
                row.get("Stock Splits", 0),
            )
        )

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.executemany(sql, rows)
            conn.commit()
            return {"status": "Success", "rows": cur.rowcount}
    except sqlite3.DatabaseError as exc:
        return {"status": "Upsert failed", "error": str(exc)}

def upsert_company(company: dict):
    sql = """
        INSERT INTO company (symbol, name, sector, industry, description)
        VALUES (?,?,?,?,?)
        ON CONFLICT(symbol) DO UPDATE SET
            name = excluded.name,
            sector = excluded.sector,
            industry = excluded.industry,
            description = excluded.description
        """
    params = (
        company.get("symbol"),
        company.get("displayName"),
        company.get("sector"),
        company.get("industry"),
        company.get("longBusinessSummary"),
    )
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
            return {"status": "Success", "rows": cur.rowcount}
    except sqlite3.DatabaseError as exc:
        return {"status": "Upsert failed", "error": str(exc)}

# SELECT DATA
def get_stock(symbol: str, date_start: date, date_end: date):
    sql = """
    SELECT * FROM stock
    WHERE symbol = ? AND date BETWEEN ? AND ?
    ORDER BY date;
    """
    try:
        with get_db_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=(symbol, date_start, date_end), parse_dates=["date"])
            return df
    except sqlite3.DatabaseError as exc:
        return {"status": "Query failed", "error": str(exc)}

def get_company(symbol: str):
    sql = """
    SELECT * FROM company WHERE symbol = ?;
    """
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(sql, (symbol,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.DatabaseError as exc:
        return {"status": "Query failed", "error": str(exc)}

# DESCRIPTIVE STATISTIC
def adaptive_sig(date_start:date, date_end:date, expected_outlier_rate:int = 0.25):
    days_between = (date_end - date_start).days
    expected_outlier = days_between * expected_outlier_rate
    p = expected_outlier / (2 * days_between)
    z = norm.ppf(1 - p)
    return z

def desc_stat(df_stock: pd.DataFrame):
    return df_stock.describe()

def spot_significant_dates(df_stock: pd.DataFrame, column:str = "close", mean:bool = True, sig:float = 1.0, limit:int = 3, increase:bool = None):
    # 
    if column not in df_stock.columns:
        return {"status": "Failed", "error": "Column name doesn't exist"}
    # add percentage change
    df_stock["percent_change"] = df_stock[column].pct_change()
    df_stock["percent_increase"] = df_stock["percent_change"] >= 0
    # do descriptive statistic
    df_desc = df_stock.describe()
    center = upper_range = lower_range = 0.0
    if mean:
        std_dev = df_desc.loc["std", "percent_change"]
        center = df_desc.loc["mean", "percent_change"]
        lower_range = center - (sig*std_dev)
        upper_range = center + (sig*std_dev)
    else:
        center = df_desc.loc["50%", "percent_change"]
        q1 = df_desc.loc["25%", "percent_change"]
        q3 = df_desc.loc["75%", "percent_change"]
        iqr = q3 - q1
        sigma_est = iqr / 1.349
        lower_range = center - sig * sigma_est
        upper_range = center + sig * sigma_est
    #
    filtered = df_stock[
        (df_stock["percent_change"] < lower_range) | 
        (df_stock["percent_change"] > upper_range)
    ]
    # 
    if increase is True:
        filtered = filtered[filtered["percent_increase"] == True]
    elif increase is False:
        filtered = filtered.loc[filtered["percent_increase"] == False].copy()
    filtered.loc[:, "percent_change"] = filtered["percent_change"].abs()
    # make sure that there are not too many rows
    filtered = filtered.sort_values(by="percent_change", ascending=False)
    return filtered.iloc[:limit]