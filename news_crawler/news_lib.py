import requests
import feedparser
from googlenewsdecoder import gnewsdecoder as gnd
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import trafilatura
from pathlib import Path
import sqlite3
import pandas as pd
import sys
sys.path.append(str(Path.cwd().parent / "stock_crawler"))

# DB LOCATION
DB_PATH = Path("../stocks.db")

#
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# CRAWL NEWS
def query_builder(ticker: str, start_date: date, end_date: date, sites: list[str]):
    query = f"({ticker})"
    if len(sites) == 1:
        query += f" site:{sites[0]}"
    else:
        site_join = " OR ".join(f"site:{s}" for s in sites)
        query += f" ({site_join})"
    
    query += f" after:{start_date.isoformat()} before:{end_date.isoformat()}"
    params = {
        "q": query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    return f"https://news.google.com/rss/search?{urlencode(params)}"

def news_filter(link: str, start_date: date, end_date: date, sites: list[str], limit:int = 0):
    req = requests.get(link, headers=HEADERS)
    if req.status_code != 200:
        return None
    parsed_req = feedparser.parse(req.content)
    filtered_entries = []
    for entry in parsed_req.entries:
        # CHECK DATE RANGE
        pub_date = datetime(*entry["published_parsed"][:6]).date()
        entry["published_time_formated"] = pub_date.strftime("%Y-%m-%d")
        if not (start_date <= pub_date <= end_date):
            continue
        # CHECK SITES
        source_href = entry.get("source", {}).get("href", "")
        domain = urlparse(source_href).netloc.replace("www.", "")
        if not any(domain == site or domain.endswith(f".{site}") for site in sites):
            continue
        filtered_entries.append(entry)
    # add hard limit
    if limit > 0:
        filtered_entries = filtered_entries[:limit]
    return filtered_entries

def decode_url(gnews_link: str, retries: int = 2, delay:float = 5):
    for attept in range(retries):
        result = gnd(gnews_link)
        if result.get("status"):
            return result["decoded_url"]
        time.sleep(delay * (attept + 1))
    return None

def get_article_full_text(url: str):
    res = requests.get(url, headers=HEADERS, timeout=10)
    if res.status_code != 200:
        return None
    return trafilatura.extract(res.text, include_comments=False, include_tables=False)

def process_item(item:dict):
    decoded = decode_url(item["link"])
    # decode link
    item["link_decoded"] = decoded
    # crawl full text
    item["full_text"] = get_article_full_text(item["link_decoded"]) if decoded else None
    return item

def crawl_full_text(items: list[dict], max_workers: int = 5) -> list[dict]:
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_item, row): row for row in items}
        for future in as_completed(futures):
            results.append(future.result())
    return results

# DB FUNCTIONS
def get_db_connection():
    return sqlite3.connect(DB_PATH)

# UPSERT ARTICLES
def upsert_articles(symbol: str, items: list[dict]):
    if not items:
        return {"status": "Upsert failed", "error": "No articles to insert"}
    sql = """
    INSERT INTO article (url, symbol, title, date, source, full_text)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(url) DO UPDATE SET
        symbol = excluded.symbol,
        title = excluded.title,
        date = excluded.date,
        source = excluded.source,
        full_text = excluded.full_text
    """
    rows = []
    for row in items:
        url = row.get("link_decoded")
        if not url:
            continue
        rows.append(
            (
                url,
                symbol,
                row.get("title"),
                row.get("published_time_formated"),
                row.get("source", {}).get("title"),
                row.get("full_text"),
            )
        )

    if not rows:
        return {"status": "Upsert failed", "error": "No valid article URLs found"}

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.executemany(sql, rows)
            conn.commit()
            return {"status": "Success", "rows": cur.rowcount}
    except sqlite3.DatabaseError as exc:
        return {"status": "Upsert failed", "error": str(exc)}

# SELECT DATA
def get_articles(symbol: str, date_start: date, date_end: date):
    sql = """
    SELECT * FROM article
    WHERE symbol = ? AND date BETWEEN ? AND ?
    ORDER BY date;
    """
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(sql, (symbol, date_start, date_end))
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.DatabaseError as exc:
        return {"status": "Query failed", "error": str(exc)}
