import asyncio, os, textwrap
from enum import IntEnum
from dotenv import load_dotenv
from rich.markdown import Markdown
from rich.console import Console
from postmarker.core import PostmarkClient
# GOOGLE ADK
from google.adk.agents import Agent
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.adk.tools import google_search
from google.adk.tools.agent_tool import AgentTool
from google.genai import types
from pydantic import BaseModel
# Search
from tavily import TavilyClient
from serpapi import GoogleSearch
# TELEGRAM
from telegram.helpers import escape_markdown
from telegram.constants import ChatAction
from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder, ConversationHandler,
    CommandHandler, MessageHandler, ContextTypes, filters,
)

load_dotenv(override=True)
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
POSTMARK_TOKEN = os.getenv("POSTMARK_TOKEN")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
SERP_API_KEY = os.getenv("SERP_API_KEY")

def tavily_search(query: str) -> list[dict]:
    client = TavilyClient(api_key=TAVILY_API_KEY)
    response = client.search(query, topic="general", search_depth="advanced", max_results=5)

    context = {
        "topic": query,
        "sources": [
            {"url": result.get("url", ""), "title": result.get("title", "")} 
            for result in (response.get("results") or [])
        ],
    }

    urls_to_extract = [source["url"] for source in context["sources"] if source.get("url")]
    if not urls_to_extract:
        return context["sources"]

    extract_response = client.extract(urls_to_extract)

    for extracted in (extract_response.get("results") or []):
        for source in context["sources"]:
            if source["url"] == extracted.get("url"):
                source["content"] = extracted.get("raw_content", "")

    failed_urls = {item.get("url") for item in (extract_response.get("failed_results") or [])}
    if failed_urls:
        context["sources"] = [s for s in context["sources"] if s.get("url") not in failed_urls]

    return context["sources"]
def serp_search(query: str) -> list[str]:
    params = {
    "engine": "google",
    "q": query,
    "num": 5,
    "api_key": SERP_API_KEY,
    }
    results = GoogleSearch(params).get_dict()  # returns JSON as dict
    rows = []
    for item in (results.get("organic_results") or [])[:5]:
        rows.append({
            "url": item.get("link", ""),
            "title": item.get("title", ""),
            "content": item.get("snippet", ""),
        })
    return rows
def search_web(query: str) -> list[str]:
    return tavily_search(query) + serp_search(query)
# Agent definition
class WebSearchItem(BaseModel):
    reason: str
    "Your reasoning for why this search is important to the query."

    query: str
    "The search term to use for the web search."


class WebSearchPlan(BaseModel):
    searches: list[WebSearchItem]
    """A list of web searches to perform to best answer the query."""

search_planner_agent = Agent(
    name = "search_planner_agent",
    model = "gemini-2.5-flash",
    description = "Search planner agent",
    instruction = """
    You are a helpful research assistant. Given a query, come up with a set of web searches 
    to perform to best answer the query. Output 3 terms to query for.
    """,
    output_schema = WebSearchPlan,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
clarify_agent = Agent(
    name = "clarify_agent",
    model = "gemini-2.5-flash",
    description = "Clarify agent",
    instruction = """
    You are a clarify agent. You will receive a query and your task is to generate 3 questions 
    to the user to narrow down the search. Before asking a question, you should use google_search tool to search the web for the best follow up questions.
    The questions should be specific and relevant to the query.
    """,
    tools = [google_search],
)
refined_query_agent = Agent(
    name = "refined_query_agent",
    model = "gemini-2.5-flash",
    description = "Refined query agent",
    instruction = """
    You are a refined query agent. You will receive a query and addtional questions and answers.
    Your task is to combine the query and the answers to generate a new query.
    """,
)
search_agent = Agent(
    name = "search_agent",
    model = "gemini-2.5-flash",
    description = "Search agent",
    instruction = """
    You are a search agent. You will receive a list of 3 pairs of query and reason why this search is important to the query.
    Your task is to choose the best query to search the web for the best answer to the query,
    You will then produce a concise summary of the results. The summary must 2-3 paragraphs and less than 300 "
    "words. Capture the main points. Write succintly, no need to have complete sentences or good "
    "grammar. This will be consumed by someone synthesizing a report, so its vital you capture the "
    "essence and ignore any fluff. Do not include any additional commentary other than the summary itself."
    You have access and must use this tool to search the web:
    - search_web: to search the web for the best answer to the query.
    """,
    tools = [search_web],
)
writer_agent = Agent(
    name = "writer_agent",
    model = "gemini-2.5-pro",
    description = "Writer agent",
    instruction =  "You are a senior researcher. Build an outline, then a cohesive report with natural language.\n"
    "Use ONLY the provided EVIDENCE list (url,title,snippet,content). No other knowledge.\n"
    "Every paragraph must include bracketed citations like [^1], [^2].\n"
    "Append a References section mapping [^n] -> URL.\n"
    "Compress long quotes; synthesize. 1500–2500 words.",
    )
def send_email(subject: str, html_body: str, email: str) -> dict[str,str]:
    """ Send an email with subject, HTML body, email"""
    postmark = PostmarkClient(server_token=POSTMARK_TOKEN)
    postmark.emails.send(
        From='hdnguyen4-c@my.cityu.edu.hk',  # Must be a verified sender signature in Postmark
        To=email,
        Subject=subject,
        HtmlBody=html_body,
    )
    return {"status": "success"}
email_agent = Agent(
    name = "email_agent",
    model = "gemini-2.5-flash",
    description = "Email agent",
    instruction = """
    You are able to send a nicely formatted HTML email based on a detailed report.
    You will be provided with a detailed report and the email you need to send to. 
    Providing the report converted into clean, well presented HTML with an appropriate subject line.
    You should use your tool send_email with the following parameters:
    - subject: the subject of the email
    - html_body: the body of the email
    - email: the email you need to send to
    to send the email.
    """,
    tools = [send_email],
)
ask_agent = Agent(
    name = "ask_agent",
    model = "gemini-2.5-flash",
    description = "Ask agent",
    instruction=(
        "You receive a detailed report. "
        "Ask the user if they want it emailed. "
        "If yes, ask for address, then call email_agent and respond Sent!."
        
    ),
    tools = [AgentTool(agent = email_agent)],
)
# Session and Runner
APP_NAME = "deep_search_agent"
session_service = InMemorySessionService()

RUNNERS = {
    "clarify": Runner(agent = clarify_agent, app_name = APP_NAME, session_service = session_service),
    "refine":  Runner(agent = refined_query_agent, app_name = APP_NAME, session_service = session_service),
    "planner": Runner(agent = search_planner_agent, app_name = APP_NAME, session_service = session_service),
    "search":  Runner(agent = search_agent, app_name = APP_NAME, session_service = session_service),
    "writer":  Runner(agent = writer_agent, app_name = APP_NAME, session_service = session_service),
    "email":   Runner(agent = email_agent, app_name = APP_NAME, session_service = session_service),
}


async def create_report_pipline(user_id: str, query: str, answers : dict[str, str]) -> str:
    """
    refine the query -> plan the search -> search the web -> write the report 
    Return report in markdown format
    """
    # 1. Clarify the query
    session_id = f"tg_{user_id}"
    
    combined_query = f"User query: {query}\n\n"
    combined_query += "\n".join(f"{q}->{a}" for q, a in answers.items())

    msg = types.Content(role="user", parts=[types.Part(text=combined_query)])
    # Refine the query
 
    async for event in RUNNERS["refine"].run_async(user_id = user_id, session_id = session_id, new_message = msg):
        if event.is_final_response() and event.content.parts:
            refined_query = event.content.parts[0].text
            break
        
    print(refined_query)
    # Plan the search
    msg = types.Content(role="user", parts=[types.Part(text=refined_query)])
    async for event in RUNNERS["planner"].run_async(user_id = user_id, session_id = session_id, new_message = msg):
        if event.is_final_response() and event.content:
            search_plan = event.content.parts[0].text
            break
    # Search the web
    msg = types.Content(role="user", parts=[types.Part(text=search_plan)])
    search_results = []
    async for event in RUNNERS["search"].run_async(user_id = user_id, session_id = session_id, new_message = msg):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if hasattr(part, "text"):
                    search_results.append(part.text)
    search_results = "\n".join(search_results)
    
    # Write the report
    msg = types.Content(role="user", parts=[types.Part(text=search_results)])
    full_report_parts = []
    async for event in RUNNERS["writer"].run_async(user_id = user_id, session_id = session_id, new_message = msg):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if hasattr(part, "text"):
                    full_report_parts.append(part.text)
    report = "\n".join(full_report_parts)
    return report
# Define the stages of the conversation
class Stage(IntEnum):
    WAITING_QUERY = 0
    ASKING        = 1
    EMAIL_DECISION = 2
    EMAIL_ADDR     = 3
# /start command for telegram bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["stage"] = Stage.WAITING_QUERY
    await update.message.reply_text(
        "👋 Hi! I'm a research assistant.Send me any research question and I'll investigate.")
# /cancel command for telegram bot
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Conversation cancelled. /start to begin anew.")

# /cancel command for telegram bot
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Bye! See you next time.")
    
def _split_message(md: str, limit: int = 4096) -> list[str]:
    """Split long markdown into chunks <= limit without breaking words."""
    lines = md.splitlines(keepends=True)
    out, buf = [], ""
    for line in lines:
        if len(buf) + len(line) > limit:
            out.append(buf)
            buf = ""
        buf += line
    if buf:
        out.append(buf)
    return out

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stage= context.user_data.get("stage", Stage.WAITING_QUERY)
    uid   = str(update.effective_user.id)
    text  = update.message.text.strip()
    
    if stage == Stage.WAITING_QUERY:
        await update.message.chat.send_action(ChatAction.TYPING)
        
        msg = types.Content(role="user", parts=[types.Part(text=text)])
        questions = []
        await session_service.create_session(
            user_id = uid, app_name = APP_NAME, session_id = f"tg_{uid}")
        async for event in RUNNERS["clarify"].run_async(user_id = uid, session_id = f"tg_{uid}", new_message = msg):
            if event.is_final_response() and event.content:
                text = event.content.parts[0].text
                questions = [q.strip() for q in text.split("\n") if q.strip()]
        questions = questions[1:]
        context.user_data.update({
            "stage" : Stage.ASKING,
            "questions" : questions,
            "query" : msg.parts[0].text,
            "answers" : {},
            "q_idx": 0,
            }
        )
        await update.message.reply_text(f"{questions[0]}",parse_mode=None)
        return
    if stage == Stage.ASKING:
        q_idx = context.user_data["q_idx"]
        questions = context.user_data["questions"]
        current_q = questions[q_idx]
        context.user_data["answers"][current_q] = text
        context.user_data["q_idx"] = q_idx+1
        if q_idx < 2:
            await update.message.reply_text(f"{questions[q_idx+1]}",parse_mode=None)
            return
        else:
            await update.message.reply_text("I have all the information I need. I'm working on your report now.")
            await update.message.chat.send_action(ChatAction.TYPING)
            report = await create_report_pipline(uid, context.user_data["query"], context.user_data["answers"])
            # send answer to user
            context.user_data["report"] = report
            for chunk in _split_message(report):
                escaped = escape_markdown(chunk, version=2)   # 🔑
                await update.message.reply_text(
                    escaped,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                )
            # change stage to email decision
            context.user_data["stage"] = Stage.EMAIL_DECISION
            await update.message.reply_text("Do you want to email the report to yourself? (yes/no)")
            return
    if stage == Stage.EMAIL_DECISION:
        if text.lower() in ("yes", "y", "yeah", "sure"):
            context.user_data["stage"] = Stage.EMAIL_ADDR
            await update.message.reply_text("Great! Please provide the email address.")
        else:
            await update.message.reply_text("No problem. Do you have any question?")
            context.user_data["stage"] = Stage.WAITING_QUERY
        return
    if stage == Stage.EMAIL_ADDR:
        email = text.strip()
        if "@" not in email:
            await update.message.reply_text("That doesn't look like an e-mail address. Try again.")
            return
        await update.message.chat.send_action(ChatAction.TYPING)
        # invoke email_agent
        session_id = f"tg_{uid}"
        prompt = (
            f"Report to send:\n\n{context.user_data['report']}\n\n"
            f"E-mail address: {email}"
        )
        msg = types.Content(role="user", parts=[types.Part(text=prompt)])
        async for ev in RUNNERS["email"].run_async(user_id = uid, session_id = session_id, new_message = msg):
            if ev.is_final_response():
                break
        await update.message.reply_text("Sent! ✅")
        context.user_data["stage"] = Stage.WAITING_QUERY
        return
        
def main():
    if not TG_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN missing in environment")
    app: Application = ApplicationBuilder().token(TG_TOKEN).build()

    # Generic text handler (we manage state ourselves)
    text_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(text_handler)

    app.run_polling()   # shares asyncio loop  :contentReference[oaicite:4]{index=4}

if __name__ == "__main__":
    asyncio.run(main())