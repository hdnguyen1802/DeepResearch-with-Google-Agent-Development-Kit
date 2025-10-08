## Deep Search Agent

An AI-powered research assistant that clarifies a user's query, plans searches, gathers evidence from the web, and writes a long-form, citation-rich report. It runs as a Telegram bot and can optionally email the generated report.

[VIDEO DEMO](https://drive.google.com/file/d/1LWia2PmKsKrRbAZ6n0hlcLmlo-yGiTir/view?usp=sharing)

### Key Features
- Clarifies user queries with follow-up questions
- Plans searches using agentic planning
- Searches the web via Tavily and SerpAPI Google Search
- Writes a detailed report with inline citations and references
- Sends the report to a user via Telegram, and optionally via email (Postmark)

## How It Works (High-Level Flow)

1. User sends a question → stored in session.
2. `clarify_agent` asks 3 follow-ups; answers are saved.
3. `refined_query_agent` merges the question and answers.
4. `search_planner_agent` proposes searches.
5. `search_agent` calls `search_web`:
   - `tavily_search` fetches URLs and extracts raw content when possible.
   - `serp_search` fetches top organic results via SerpAPI with GoogleSearch.
6. `writer_agent` produces a 1500–2500 word report with inline citations [^n] and a References list.
7. Bot sends the report in Telegram; optionally emails it via `email_agent` (Postmark).
   
## Architecture

- `deep_search_agent/agent.py` defines several Google ADK agents and a simple Telegram bot conversation flow.
  - `clarify_agent`: Asks 3 targeted questions (uses `google_search` tool from Google ADK).
  - `refined_query_agent`: Merges the original query with the user's answers.
  - `search_planner_agent`: Produces a small plan of searches to run.
  - `search_agent`: Executes `search_web` (Tavily + SerpAPI), summarizes evidence, and returns structured results.
  - `writer_agent`: Produces a long report with citations and a References section, using only gathered evidence.
  - `email_agent`: Sends the report via Postmark.
  - A Telegram conversation manages stages: WAITING_QUERY → ASKING → EMAIL_DECISION → EMAIL_ADDR.

Under the hood, runners from Google ADK (`Runner`) orchestrate asynchronous agent execution with an in-memory session store.

## Prerequisites

- Python 3.11+ (Python 3.12 supported)
- A Telegram Bot token (via `@BotFather`)
- Postmark server token (if you plan to email reports)
- Tavily API key (`tavily.ai`)
- SerpAPI key (`serpapi.com`)

## Installation

1) Clone or download this repository.

2) Create and activate a virtual environment (recommended).

```bash
python -m venv .venv
. .venv/Scripts/activate  # PowerShell: .\.venv\Scripts\Activate.ps1
```

3) Install dependencies from `requirements.txt` (located at repo root).

```bash
pip install -r requirements.txt
```

If you do not have a root `requirements.txt`, ensure these packages are installed:

```bash
pip install python-telegram-bot google-adk pydantic python-dotenv \
            google-cloud-aiplatform vertexai ipykernel postmarker rich \
            tavily-python google-genai google-search-results
```

## Configuration

Create a `.env` file at the project root with the following keys:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
POSTMARK_TOKEN=your_postmark_server_token
TAVILY_API_KEY=your_tavily_api_key
SERP_API_KEY=your_serpapi_key
```

Notes:
- The sender address used in `send_email` must be a verified sender in Postmark.
- For SerpAPI, the Python package is `google-search-results`; it exposes `from serpapi import GoogleSearch`.

## Running

Run the Telegram bot from the repository root:

```bash
python deep_search_agent/agent.py
```

Then open Telegram, find your bot, and send any research question. The bot will:
- Ask you 3 clarifying questions
- Generate a report with citations
- Offer to email you the report

## Project Structure

```
deep_search/
  deep_search_agent/
    __init__.py
    agent.py
  requirements.txt
```

## Troubleshooting

- ImportError: `cannot import name 'GoogleSearch' from 'serpapi'`
  - Ensure the correct package is installed: `pip install google-search-results`.
  - Quick test: `python -c "from serpapi import GoogleSearch; print('ok')"`.

- RuntimeError: `TELEGRAM_TOKEN missing in environment`
  - Create `.env` at project root and set `TELEGRAM_TOKEN`.

- Tavily extraction errors or missing content
  - Ensure `TAVILY_API_KEY` is valid.
  - The code skips failed extractions and returns available sources gracefully.

- Postmark: email not sending
  - Verify `POSTMARK_TOKEN` and that the `From` address is a verified sender signature in Postmark.

## Security Notes

- Keep your `.env` out of source control.
- Avoid logging secrets. Rotate keys if they become exposed.






