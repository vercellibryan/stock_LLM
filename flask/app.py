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
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk, ToolMessage
#
from datetime import date
import json

load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
# initiate the agent
def initiate_agent(symbol):
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
    The stock symbol that is used for this conversation is: {symbol}
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
    return agent

agent = None
conversations = {}

#
app = Flask(__name__)

# INITIATE THE AGENT
@app.route('/state', methods=['POST'])
def chat_state():
    global agent
    data = request.get_json() or {}
    symbol = data.get('symbol', '').upper()
    # symbol = request.args.get('symbol', '').strip().upper()
    if not symbol:
        return jsonify({
            "status": "ERROR",
            "message": "Query parameter 'symbol' is required."
        }), 400
    try:
        agent = initiate_agent(symbol)
        return jsonify({"status": "OK", "symbol": symbol}), 200
    except ValueError as ve:
        return jsonify({
            "status": "ERROR",
            "message": f"{ve}"
        }), 500
    except Exception as e:
        return jsonify({
            "status": "ERROR",
            "message": f"{e}"
        }), 500

@app.route('/')
def home():
    return render_template(
        'index.html'
    )

@app.route('/chat', methods=['POST'])
def chat():
    # symbol = request.args.get('symbol', '')
    # msg = request.args.get('message', '')
    data = request.get_json() or {}
    symbol = data.get('symbol', '')
    msg = data.get('message', '')

    # check if there's a chat history
    if symbol not in conversations:
        conversations[symbol] = []
    conversations[symbol].append(HumanMessage(content=msg))
    curr_symbol = symbol

    # handle message streaming
    def generate():
        full_text = ""
        tool_calls = []
        try:
            for chunk, metadata in agent.stream(
                {"messages": conversations[symbol]},
                stream_mode="messages"):
                if isinstance(chunk, AIMessageChunk):
                    # final response
                    if isinstance(chunk.content, str):
                        full_text += chunk.content
                        yield chunk.content.encode('utf-8')
                    # tool call chunks
                    if chunk.tool_call_chunks:
                        for a in chunk.tool_call_chunks:
                            if a.get("name"): 
                                args = a.get("args", {})
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args)
                                    except json.JSONDecodeError:
                                        args = {}
                                tool_calls.append({
                                    "name": a["name"],
                                    "args": args,
                                    "id": a.get("id", "")
                                })
                                #yield a["name"]
                    # thinking chunk
                    # if isinstance(chunk.content, list):
                    #     for a in chunk.content:
                    #         if isinstance(a, dict):
                    #             if a.get("type", "") == "thinking":
                    #                 thinking_block = a.get("thinking")
                    #                 yield thinking_block.encode('utf-8')
                elif isinstance(chunk, ToolMessage):
                    #print(chunk.content)
                    conversations[symbol].append(chunk)
                    #yield chunk.content.encode('utf-8')
            # insert into history
            if full_text or tool_calls:
                final = AIMessage(
                    content=full_text,
                    tool_calls=tool_calls)
                conversations[symbol].append(final)
        
        except Exception as e:
            print(e)
    return Response(stream_with_context(generate()), mimetype='text/plain; charset=utf-8')

# LLM DEBUG
@app.route('/chat2', methods=['GET'])
def chat2():
    global agent
    symbol = request.args.get('symbol', '').strip()
    msg = request.args.get('message', '').strip()

    # check if there's a chat history
    if symbol not in conversations:
        conversations[symbol] = []
    conversations[symbol].append(HumanMessage(content=msg))
    # handle message streaming
    def generate():
        full_text = ""
        tool_calls = []
        try:
            for chunk, metadata in agent.stream(
                {"messages": conversations[symbol]},
                stream_mode="messages"):
                if isinstance(chunk, AIMessageChunk):
                    # final response
                    if isinstance(chunk.content, str):
                        full_text += chunk.content
                        yield chunk.content.encode('utf-8')
                    # tool call chunks
                    if chunk.tool_call_chunks:
                        for a in chunk.tool_call_chunks:
                            if a.get("name"): 
                                args = a.get("args", {})
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args)
                                    except json.JSONDecodeError:
                                        args = {}
                                tool_calls.append({
                                    "name": a["name"],
                                    "args": args,
                                    "id": a.get("id", "")
                                })

                                yield a["name"]
                    # thinking chunk
                    if isinstance(chunk.content, list):
                        for a in chunk.content:
                            if isinstance(a, dict):
                                if a.get("type", "") == "thinking":
                                    thinking_block = a.get("thinking")
                                    yield thinking_block.encode('utf-8')
                elif isinstance(chunk, ToolMessage):
                    #print(chunk.content)
                    conversations[symbol].append(chunk)
                    yield chunk.content.encode('utf-8')
            # insert into history
            if full_text or tool_calls:
                final = AIMessage(
                    content=full_text,
                    tool_calls=tool_calls)
                conversations[symbol].append(final)
        
        except Exception as e:
            print(e)
    return Response(stream_with_context(generate()), mimetype='text/plain; charset=utf-8')

# PRESIST
@app.route('/history', methods=['GET'])
def get_hist():
    symbol = request.args.get('symbol', '')
    history = conversations.get(symbol, [])
    #
    formatted_msg = []
    for msg in history:
        # Identify message role
        if msg.type == "human":
            role = "user"
        elif msg.type == "ai":
            role = "assistant"
        elif msg.type == "tool":
            role = "tool"
        else:
            continue

        formatted_msg.append({
            "role": role,
            "content": msg.content
        })
    return jsonify(formatted_msg)

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

@app.route('/list_company', methods=['GET'])
def list_company():
    return sl.list_company()

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