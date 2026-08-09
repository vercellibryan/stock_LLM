from pathlib import Path
import sys
from datetime import date, timedelta
import pandas as pd

sys.path.append(str(Path.cwd().parent / "stock_crawler"))
import stock_lib as sl

sys.path.append(str(Path.cwd().parent / "news_crawler"))
import news_lib as nl

from langchain.tools import tool

# LIST OF SITES
FINANCE_PUBLISHERS = ["finance.yahoo.com", "benzinga.com"]

# SELECT DATA FROM DATABASE
@tool
def get_company(symbol: str):
    """
    Retrieve metadata about a publicly traded company from its stock ticker.

    Use this tool when you need company information such as the company name,
    industry, sector, exchange, or other basic details before performing
    further analysis.

    Args:
        symbol: Stock ticker symbol (e.g. AAPL, MSFT, NVDA).

    Returns:
        Company metadata.
    """
    return sl.get_company(symbol)

# FILTER SIGNIFICANT DATES 
@tool
def spot_significant_dates(symbol: str, start_date: date, end_date: date, column:str = "close", increase:bool = None, mean:bool = True, limit:int = 10):
    """
    Detect statistically significant stock price movements within a historical
    price series.

    ONLY use this tool when the user STRICTLY asks for dates where shocks happened (NO NEWS).

    The tool ranks significant dates based on statistical deviation from the
    normal price movement and returns the most significant events.

    Args:
        symbol: Stock ticker symbol (e.g. AAPL, NVDA).
        start_date: Start of the analysis period.
        end_date: End of the analysis period.
        column: Price column to analyze (default: "Close").
        increase: Filters by move direction.
            - True: only flag significant increases (user asked about rallies/spikes/gains)
            - False: only flag significant decreases (user asked about drops/crashes/losses)
            - None: flag both directions (default — use for general "what happened" queries)
        mean: Whether to compare movements against the historical mean.
        limit: Maximum number of significant dates to return.

    Returns:
        A list of statistically significant dates and their corresponding
        price movements.
    """
    sig = sl.adaptive_sig(start_date, end_date)
    df_stock = sl.get_stock(symbol, start_date, end_date, increase = increase)
    if len(df_stock) == 0:
        return {"status": "Failed", "error": "No rows."}
    return sl.spot_significant_dates(df_stock, column, mean, sig, limit)

# FETCH NEWS BASED OF DATES
FINANCE_PUBLISHERS = ["finance.yahoo.com", "benzinga.com"]
@tool
def get_article_context(symbol: str, start_date: date, end_date: date, col:str = "close", increase:bool = None, limit:int = 10, window:int = 2):
    """
    Retrieve news articles related to statistically significant stock price
    movements within a specified date range.

    This tool first identifies significant price movements for the stock, then
    collects news articles published within a configurable window around each
    significant date. Retrieved articles are enriched with metadata linking them
    to nearby price movements, making them suitable for explaining potential
    market catalysts.

    Use this tool when you need supporting news to explain why a stock experienced
    an unusual price movement. Prefer this tool over searching for news manually,
    as it automatically associates articles with significant trading events.

    Args:
        symbol: Stock ticker symbol (e.g. AAPL, NVDA).
        start_date: Beginning of the analysis period.
        end_date: End of the analysis period.
        col: Stock price column used for detecting significant movements.
            Defaults to "close".
        increase:
            Filters by move direction.
            - True: only flag significant increases (user asked about rallies/spikes/gains)
            - False: only flag significant decreases (user asked about drops/crashes/losses)
            - None: flag both directions (default — use for general "what happened" queries)
        window: Number of calendar days before and after each significant date to
            search for related news. Defaults to 2.

    Returns:
        A DataFrame of relevant news articles. Each article includes publication
        details, article content, and metadata describing the associated
        significant stock movement(s), including the event date, percentage price
        change, and the number of days between the article and the market event.
    """
    df_stock = sl.get_stock(symbol, start_date, end_date)
    if len(df_stock) == 0:
        return {"status": "Failed", "error": "No rows."}
    sig = sl.adaptive_sig(start_date, end_date)
    df_sig_dates = sl.spot_significant_dates(df_stock, col, limit = limit, sig = sig, increase = increase)
    news_arr = []
    for i, v in enumerate(df_sig_dates.itertuples()):
        start_date = (v.date - timedelta(days=window)).date()
        end_date = (v.date + timedelta(days=window)).date()
        symbol = v.symbol
        # check db for the news
        news = nl.get_articles(symbol, start_date, end_date)
        if len(news) < 1:
            # CRAWL NEW NEWS
            # build RSS query
            query = nl.query_builder(symbol, start_date, end_date, FINANCE_PUBLISHERS)
            # fetch news from google news
            fetched_news = nl.news_filter(query, start_date, end_date, FINANCE_PUBLISHERS, limit=3)
            # CRAWL FULL TEXTS
            complete_news = nl.crawl_full_text(fetched_news)
            # UPSERT INTO DB
            nl.upsert_articles(symbol, complete_news)
            # GET THE ARTICLE
            news = nl.get_articles(symbol, start_date, end_date)
        else:
            news_arr.append(news)
    # ATTACH CHANGES TO THE ARTICLES
    flat_news = [article for sublist in news_arr for article in sublist]
    df_news = pd.DataFrame(flat_news)
    df_news = df_news.drop_duplicates(subset="url")
    #
    df_news["date"] = pd.to_datetime(df_news["date"])
    df_sig_dates['date'] = pd.to_datetime(df_sig_dates["date"], errors='coerce')
    df_sig_dates = df_sig_dates.set_index("date")
    # function to attach the percent change
    def get_linked_info(article_date):
        window_start = article_date - pd.Timedelta(days=window)
        window_end = article_date + pd.Timedelta(days=window)
        in_window = df_sig_dates[(df_sig_dates.index >= window_start) & (df_sig_dates.index <= window_end)]
        return [
            {
                "date": str(d.date()),
                "percent_change": row["percent_change"] * (-1 if not row["percent_increase"] else 1),
                "days_from_publish": (article_date - d).days,
            }
            for d, row in in_window.iterrows()
        ]
    df_news["linked_info"] = df_news["date"].apply(get_linked_info)
    return df_news

