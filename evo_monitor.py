"""evo_monitor.py  –  v2 (2025‑07‑19)
One‑shot scanner for EVO関連ニュース & TDnet PDF hits.
Designed to be executed once by GitHub Actions (or cron) and exit within
~10 s. All scheduling is handled by the CI, so the script contains **no
while‑loops**.

* データソース
    - EVO Japan Securities ニュースページ
      https://www.evofinancialgroup.com/ejs/news/
    - TDnet 当日インデックス (release.tdnet.info)
* 通知: Discord Webhook  (環境変数 DISCORD_WEBHOOK_URL)
* 依存: requests, beautifulsoup4, aiohttp  (requirements.txt も更新要)
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
import sys
from typing import List, Tuple

import aiohttp
from bs4 import BeautifulSoup as BS

WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")
TIMEOUT = aiohttp.ClientTimeout(total=5)
HEADERS = {"User-Agent": "EvoMonitor/2.0 (GitHub Actions)"}

KEYWORDS = [
    "第三者割当",
    "新株予約権",
    "行使価額",
    "EVO FUND",
    "Evolution Capital",
]

EVO_NEWS = "https://www.evofinancialgroup.com/ejs/news/"
TDNET_BASE = "https://release.tdnet.info"


async def fetch(session: aiohttp.ClientSession, url: str) -> str | None:
    """Return text of url or None on error (silent)."""
    try:
        async with session.get(url, timeout=TIMEOUT) as resp:
            if resp.status == 200:
                return await resp.text()
    except Exception as exc:  # pragma: no cover
        print(f"⚠️  fetch error {url}: {exc}", file=sys.stderr)
    return None


def hit(title: str) -> bool:
    return any(k in title for k in KEYWORDS)


async def scan_evo(session: aiohttp.ClientSession) -> List[Tuple[str, str]]:
    html = await fetch(session, EVO_NEWS)
    if not html:
        return []
    soup = BS(html, "html.parser")
    items = []
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if hit(title):
            href = a.get("href")
            if href and not href.startswith("http"):
                href = os.path.join(EVO_NEWS, href.lstrip("/"))
            items.append((title, href or EVO_NEWS))
    return items


async def scan_tdnet(session: aiohttp.ClientSession) -> List[Tuple[str, str]]:
    jst_today = dt.datetime.utcnow() + dt.timedelta(hours=9)
    url = f"{TDNET_BASE}/inbk/{jst_today:%Y}/{jst_today:%Y%m%d}/index.html"
    html = await fetch(session, url)
    if not html:
        return []
    soup = BS(html, "html.parser")
    items = []
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if hit(title):
            href = a.get("href")
            if href and href.startswith("./"):
                href = f"{TDNET_BASE}{href[1:]}"
            items.append((title, href or url))
    return items


async def discord_send(content: str) -> None:
    if not WEBHOOK:
        print("⚠️  DISCORD_WEBHOOK_URL not set – skipping send", file=sys.stderr)
        return
    async with aiohttp.ClientSession() as s:
        await s.post(WEBHOOK, json={"content": content[:1900]})  # 2k limit


async def main() -> None:
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        evo, tdnet = await asyncio.gather(scan_evo(session), scan_tdnet(session))
        hits = [*(f"[EVO NEWS] {t}\n{u}" for t, u in evo),
                * (f"[TDNET] {t}\n{u}" for t, u in tdnet)]
        if hits:
            await discord_send("\n\n".join(hits))
        else:
            print("No matches today – OK")

if __name__ == "__main__":
    asyncio.run(main())
# ==== ここから追記 ====
def build_digest(hits):
    """hits = [{'type': 'TDnet', 'msg': '…'}, …] を受け取り Markdown 文字列を返す"""
    if not hits:
        return ""  # 0件なら空文字（あとでスキップ）
    lines = ["# EVO DAILY DIGEST - " + time.strftime("%Y-%m-%d"), ""]
    tdnet = [h for h in hits if h["type"] == "TDnet"]
    news  = [h for h in hits if h["type"] == "NEWS"]
    if tdnet:
        lines.append("## TDnet ヒット")
        for h in tdnet:
            lines.append(f"- {h['msg']}")
        lines.append("")
    if news:
        lines.append("## EVO 公式ニュース")
        for h in news:
            lines.append(f"- {h['msg']}")
        lines.append("")
    lines.append("---\n**本日のまとめ**  \n- 新規ディール: "
                 f"{len(tdnet)} 件  \n- 公式ニュース: {len(news)} 件")
    return "\n".join(lines)

# メイン処理の最後付近で…
digest = build_digest(all_hits)       # all_hits は既に作ってあるリストを想定
print("::set-output name=summary::" + digest.replace("%", "%25").replace("\n", "%0A"))
# ↑ GitHub Actions で steps.digest.outputs.summary として受け取れる
