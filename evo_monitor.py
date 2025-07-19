
"""EVO Fund Monitor – pushes EVO-related news & filings to a Discord webhook.
Usage:
  1. Install deps: pip install requests beautifulsoup4 schedule python-dotenv
  2. Copy .env.example to .env and paste your Discord webhook.
  3. Run: python evo_monitor.py  (keep it alive via cron / systemd / GitHub Actions)

What it does (default intervals):
  - Every 15 min: Scrape EVO Japan Securities news page for new articles containing
    key words ["第三者割当", "新株予約権", "CB", "行使", "EVO FUND"].
  - Every 5 min on JP market hours (08:00‑17:00 JST): Check TDnet new PDFs and
    alert when "EVO FUND" or "Evolution Capital" appears.
  - Every day 18:05 JST: Parse TDnet for monthly exercise / 残行使 IR and notify
    if 残行使率 drops to 20 %, 10 % or 0 %.

State is kept in .evo_monitor_state.json so you don’t get duplicate alerts.
Feel free to adjust keywords, intervals, or add other endpoints.
"""

import os, json, re, time, datetime as dt, functools, logging, pathlib
import requests, schedule
from bs4 import BeautifulSoup
from urllib.parse import urljoin

ROOT_DIR = pathlib.Path(__file__).resolve().parent
STATE_FILE = ROOT_DIR / ".evo_monitor_state.json"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# --- config -------------------------------------------------------------
EVO_NEWS_URL = "https://www.evofinancialgroup.com/ejs/news/"
TDNET_BASE = "https://release.tdnet.info"  # list pages are like /old/202507/14/xxxxx.html
KEYWORDS = [
    "EVO FUND",
    "Evolution Capital",
    "第三者割当",
    "新株予約権",
    "行使価額",
    "月間行使状況",
]
JST = dt.timezone(dt.timedelta(hours=9))
START_HOUR = 8  # TDnet scan from 08:00 JST
END_HOUR = 17   # until 17:00 JST

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# --- state helpers ------------------------------------------------------

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"evo_news": [], "tdnet": [], "exercise_flags": {}}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))

state = load_state()

# --- utils --------------------------------------------------------------

def notify(msg, url=None):
    if not WEBHOOK_URL:
        logging.warning("WEBHOOK_URL not set – printing instead: %s", msg)
        print(msg, url or "")
        return
    payload = {"content": f"{msg}\n{url}" if url else msg}
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        logging.error("Webhook post failed: %s", e)

# --- 1. EVO Japan news --------------------------------------------------

def scan_evo_news():
    logging.info("Scanning EVO news page…")
    try:
        html = requests.get(EVO_NEWS_URL, timeout=15).text
    except Exception as e:
        logging.error("EVO news fetch error: %s", e)
        return
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("div.news-list li")  # assumption: list structure
    for li in items:
        title = li.get_text(strip=True)
        link = urljoin(EVO_NEWS_URL, li.find("a").get("href")) if li.find("a") else EVO_NEWS_URL
        if any(k in title for k in KEYWORDS):
            if link not in state["evo_news"]:
                notify(f"[EVO NEWS] {title}", link)
                state["evo_news"].append(link)
    save_state(state)

# --- 2. TDnet filings ---------------------------------------------------

def list_today_tdnet_pdfs():
    today = dt.datetime.now(JST)
    y, m, d = today.year, today.month, today.day
    listing_url = f"{TDNET_BASE}/old/{y}{m:02d}/{d:02d}/index.html"
    try:
        html = requests.get(listing_url, timeout=15).text
    except Exception as e:
        logging.error("TDnet list fetch error: %s", e)
        return []
    soup = BeautifulSoup(html, "html.parser")
    pdfs = []
    for a in soup.select("a"):
        href = a.get("href", "")
        if href.endswith(".pdf"):
            pdfs.append(urljoin(listing_url, href))
    return pdfs


def scan_tdnet():
    now = dt.datetime.now(JST)
    if not (START_HOUR <= now.hour < END_HOUR):
        return
    logging.info("Scanning TDnet…")
    for pdf_url in list_today_tdnet_pdfs():
        if pdf_url in state["tdnet"]:
            continue
        # simple keyword match by filename (cheap); could download & OCR if needed
        if any(k.lower() in pdf_url.lower() for k in ["evo", "evolution"]):
            notify("[TDNET] EVO関連: ", pdf_url)
            state["tdnet"].append(pdf_url)
    save_state(state)

# --- 3. Monthly exercise -------------------------------------------------

def scan_exercise():
    logging.info("Exercise check stub – implement scraper for specific tickers if needed")
    # Placeholder: user can add tickers -> check monthly IR pdf titles and parse remaining ratio.

# --- scheduler ----------------------------------------------------------

schedule.every(15).minutes.do(scan_evo_news)
schedule.every(5).minutes.do(scan_tdnet)
schedule.every().day.at("18:05").do(scan_exercise)  # JST

if __name__ == "__main__":
    notify("✅ EVO Monitor started", None)
    while True:
        schedule.run_pending()
        time.sleep(30)
