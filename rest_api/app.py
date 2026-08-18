from fastapi import FastAPI
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent / "stock_crawler"))
import stock_lib as sl
#
sys.path.append(str(Path(__file__).resolve().parent.parent / "lang-chain"))
import tools
from langchain.agents import create_agent
from langchain_google_genai.chat_models import ChatGoogleGenerativeAI
import os
from datetime import date, timedelta
from dotenv import load_dotenv
import pandas as pd
import numpy as np
from datetime import datetime as _datetime

load_dotenv()

app = FastAPI()
conversations = {}
API_KEY = os.getenv("GOOGLE_API_KEY")

# initiate agent
model = model = ChatGoogleGenerativeAI(model="gemma-4-31b-it", api_key=API_KEY)
agent = create_agent(
    model=model,
    tools=[
        tools.get_company,
        tools.spot_significant_dates,
        tools.get_article_context,
    ],
    system_prompt=f"""

Today's date is {date.today()}
The stock symbol that is used for this conversation is: {"NVDA"}
If the user asks about any other company just warn them.

You are a financial research assistant.

IMPORTANT: Conversation history is your primary source of information.

Tools:
1. get_company: Get detailed information about the company
2. spot_significant_dates: Get dates where significant event occurs. always look for the column "percent_change" and "percent_increase".
3. get_article_context: fetch articles given a specific time range. Check on the title, full_text, and linked_info columns and try to correlate with the articles.

Before using any tool:
1. Check previous assistant messages and tool results.
2. Determine whether the required information already exists.
3. Only call tools if the information is missing.

Do NOT call tools to retrieve information that has already been provided
earlier in the conversation.

Examples:

User:
"What happened to NVDA this June?"

Correct workflow:
- Use tools to find significant events and related news.

User:
"Why did they enter biomedical research?"
"Can you explain the June 23 event?"
"What does this mean?"

Do NOT call tools again.
Use the previous NVDA analysis and retrieved articles.

Only call tools when:
- The user asks EXPLICITLY about the company's information.
- The user asks about a new time period.
- The user requests updated information.
- Previous context does not contain enough evidence."""
)

@app.get("/chat")
def chat(symbol: str, msg: str):
    if symbol not in conversations:
        conversations[symbol] = []
    conversations[symbol].append({"role": "user", "content": msg})
    result = agent.invoke({"messages": conversations[symbol]})
    # get the last response
    last_result = result["messages"][-1].content[-1]["text"]
    conversations[symbol].append({"role": "assistant", "content": last_result})
    return conversations[symbol][-1]["content"]

# GET DATA FROM DB

@app.get("/get_stock")
def get_stock(symbol: str, date_start: date, date_end: date):
    result = sl.get_stock(symbol, date_start, date_end)
    # propagate error dicts from the library
    if isinstance(result, dict):
        return result
    # convert pandas DataFrame to JSON-serializable list of dicts
    if isinstance(result, pd.DataFrame):
        df = result.reset_index()
        # replace NaN (and other missing values) with None so JSON encoder accepts them
        df = df.where(pd.notnull(df), None)
        records = df.to_dict(orient="records")

        def convert(v):
            if isinstance(v, (np.integer,)):
                return int(v)
            if isinstance(v, (np.floating,)):
                return float(v)
            if isinstance(v, (np.bool_,)):
                return bool(v)
            if isinstance(v, (pd.Timestamp, _datetime)):
                return v.isoformat()
            return v

        for r in records:
            for k, v in list(r.items()):
                r[k] = convert(v)

        return records
    # fallback
    return result

@app.get("/get_company")
def get_company(symbol: str):
    result = sl.get_company(symbol)
    return result

# CRAWL AND UPSERT

@app.get("/new_stock")
def new_stock(symbol: str, date_start: date, date_end: date):
    try:
        # crawl and insert company
        crawl_company = sl.crawl_company(symbol)
        sl.upsert_company(crawl_company)
        # crawl and insert stock data
        crawl_stock = sl.crawl_stock(symbol, date_start, date_end)
        sl.upsert_stock(symbol, crawl_stock)
        # return serialized data using the existing endpoint logic
        return get_stock(symbol, date_start, date_end)
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.get("/update_stock")
def update_stock(symbol: str, date_start: date, date_end: date):
    try:
        # crawl and insert stock data
        crawl_stock = sl.crawl_stock(symbol, date_start, date_end)
        sl.upsert_stock(symbol, crawl_stock)
        # return serialized data using the existing endpoint logic
        return get_stock(symbol, date_start, date_end)
    except Exception as e:
        return {"status": "error", "error": str(e)}

