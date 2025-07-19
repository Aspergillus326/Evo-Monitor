# evo_monitor.py  –  v3  (2025‑07‑19)
"""
EVO Fund 日次モニター（GitHub Actions 用）
------------------------------------------------
* 12:30 JST に1回だけ起動させる想定（cron: "30 3 * * *"）
* やること
    1. EVO Japan Securities のニュースページをスクレイピング
    2. TDnet 当日インデックスをスクレイピング
    3. キーワードヒットを Discord Webhook へ即時投稿
    4. その日のヒットを Markdown にまとめ、GitHub Actions の
       `steps.digest.outputs.summary` に渡す（workflow 側で
       daily/ にコミット）
* 依存:  requests, beautifulsoup4, aiohttp, python-dotenv
"""
import asyncio, aiohttp, os, re, time, datetime, html
from bs4 import BeautifulSoup

# ------------ 設定 -----------------
KEYWORDS = [
    "第三者割当", "新株予約権", "行使", "TIP", "CB", "株式", "ワラント",
    "EVO", "Evolution", "capital", "fund"
]
TDNET_URL  = "https://release.tdnet.info/inbk/{year}/{today}/index.html"
EVO_NEWS_URL = "https://www.evofinancialgroup.com/ejs/news/"
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")
TIMEOUT_SEC = 5
HEADERS = {"User-Agent": "EvoMonitor/1.0"}
# -----------------------------------

def keyword_hit(text: str) -> bool:
    """英文混入もあるので大文字小文字無視。"""
    t = text.lower()
    return any(k.lower() in t for k in KEYWORDS)

async def fetch(session: aiohttp.ClientSession, url: str) -> str | None:
    try:
        async with session.get(url, timeout=TIMEOUT_SEC) as r:
            if r.status == 200:
                return await r.text()
    except Exception as e:
        print(f"⚠️  fetch error {url}: {e}")
    return None

async def parse_evo(session) -> list[dict]:
    html_text = await fetch(session, EVO_NEWS_URL)
    hits = []
    if not html_text:
        return hits
    soup = BeautifulSoup(html_text, "html.parser")
    for a in soup.select(".news__list a"):
        title = a.get_text(strip=True)
        if keyword_hit(title):
            href = a.get("href", "")
            hits.append({"type": "NEWS", "msg": f"{title} ({href})"})
    return hits

async def parse_tdnet(session) -> list[dict]:
    jst = datetime.datetime.now(datetime.timezone.utc).astimezone()
    today = jst.strftime("%Y%m%d")
    url = TDNET_URL.format(year=jst.year, today=today)
    html_text = await fetch(session, url)
    if not html_text:
        return []
    soup = BeautifulSoup(html_text, "html.parser")
    hits = []
    for a in soup.select("a"):
        text = a.get_text(" ", strip=True)
        if keyword_hit(text):
            href = f"https://release.tdnet.info{a.get('href')}"
            hits.append({"type": "TDnet", "msg": f"{text} ({href})"})
    return hits

async def send_discord(session, content: str):
    if not DISCORD_WEBHOOK:
        return
    try:
        await session.post(DISCORD_WEBHOOK, json={"content": content}, timeout=TIMEOUT_SEC)
    except Exception as e:
        print(f"⚠️  discord post error: {e}")

def build_digest(hits: list[dict]) -> str:
    if not hits:
        return ""
    today = datetime.date.today().isoformat()
    lines: list[str] = [f"# EVO DAILY DIGEST - {today}", ""]
    section = {"TDnet": [], "NEWS": []}
    for h in hits:
        section[h["type"]].append(h["msg"])
    if section["TDnet"]:
        lines.append("## TDnet ヒット")
        lines += [f"- {m}" for m in section["TDnet"]]
        lines.append("")
    if section["NEWS"]:
        lines.append("## EVO 公式ニュース")
        lines += [f"- {m}" for m in section["NEWS"]]
        lines.append("")
    lines.append("---")
    lines.append("**本日のまとめ**  \n- TDnet: {} 件  \n- NEWS: {} 件".format(
        len(section["TDnet"]), len(section["NEWS"]))
    )
    return "\n".join(lines)

async def main():
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tdnet_hits, news_hits = await asyncio.gather(
            parse_tdnet(session), parse_evo(session)
        )
        all_hits = tdnet_hits + news_hits
        # Discord 投稿
        for h in all_hits:
            await send_discord(session, f"[{h['type']}] {h['msg']}")
        # Digest 作成
        digest = build_digest(all_hits)
        if digest:
            escaped = digest.replace('%', '%25').replace('\n', '%0A')
            print(f"::set-output name=summary::{escaped}")

if __name__ == "__main__":
    asyncio.run(main())
