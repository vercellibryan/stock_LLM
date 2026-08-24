from flask import Flask, render_template, request, Response, stream_with_context, jsonify
from pathlib import Path
import sys
import os
#
from dotenv import load_dotenv
sys.path.append(str(Path(__file__).resolve().parent.parent / "lang-chain"))
import tools
sys.path.append(str(Path(__file__).resolve().parent.parent / "stock_crawler"))
import stock_lib as sl
from langchain.agents import create_agent
from langchain_google_genai.chat_models import ChatGoogleGenerativeAI
#
from datetime import date

load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
# initiate the agent
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
conversations = {}

#
app = Flask(__name__)

#
@app.route('/')
def home():
    return render_template(
        'index.html'
    )

@app.route('/chat', methods=['GET'])
def chat():
    symbol = request.args.get('symbol', '')
    msg = request.args.get('msg', '')
    
    if symbol not in conversations:
        conversations[symbol] = []
        
    conversations[symbol].append({"role": "user", "content": msg})

    def generate():
        full_response = []
        for item in agent.stream({"messages": conversations[symbol]}, stream_mode="messages"):
            chunk = item[0] if isinstance(item, tuple) else item
            content = getattr(chunk, "content", None)
            print(f"DEBUG CHUNK TYPE: {type(chunk)} | CONTENT: {repr(content)}")            
            if isinstance(content, str) and content:
                full_response.append(content)
                safe_content = content.replace("\n", "\\n")
                yield f"data: {safe_content}\n\n"
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_val = block.get("text", "")
                        if text_val:
                            full_response.append(text_val)
                            yield f"data: {text_val}\n\n"
        complete_text = "".join(full_response)
        if complete_text:
            conversations[symbol].append({"role": "assistant", "content": complete_text})

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

# SELECT FUNTIONS

@app.route('/get_stock', methods=['GET'])
def get_stock():
    symbol = request.args.get('symbol', '')
    date_start = request.args.get('date_start', '')
    date_end = request.args.get('date_end', '')
    #
    df = sl.get_stock(symbol, date_start, date_end)
    if 'date' not in df.columns:
        df = df.reset_index()
    return jsonify(df.to_dict(orient='records'))

@app.route('/get_company', methods=['GET'])
def get_company():
    symbol = request.args.get('symbol', '')
    return sl.get_company(symbol)

# UPSERT FUNCTIONS

@app.route('/new_stock', methods=['GET'])
def new_stock(symbol: str, date_start: date, date_end: date):
    symbol = request.args.get('symbol', '')
    date_start = request.args.get('date_start', '')
    date_end = request.args.get('date_end', '')
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

@app.route('/update_stock', methods=['GET'])
def update_stock(symbol: str, date_start: date, date_end: date):
    symbol = request.args.get('symbol', '')
    date_start = request.args.get('date_start', '')
    date_end = request.args.get('date_end', '')
    try:
        # crawl and insert stock data
        crawl_stock = sl.crawl_stock(symbol, date_start, date_end)
        sl.upsert_stock(symbol, crawl_stock)
        # return serialized data using the existing endpoint logic
        return get_stock(symbol, date_start, date_end)
    except Exception as e:
        return {"status": "error", "error": str(e)}

if __name__ == '__main__':
    app.run(debug=True)