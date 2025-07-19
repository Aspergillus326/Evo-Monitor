# evo_monitor.py – v4 (2025‑07‑19)
"""
EVO Fund 日次モニター（GitHub Actions 専用）
================================================
* 12:30 JST に **1 回だけ** 実行させるワンショット設計。
* スクリプト自体は 10〜15 秒で終了。ループは一切持たない。

機能一覧
--------
1. **EVO Japan Securities ニュースページ**をスクレイピングしてキーワード判定
2. **TDnet 当日インデックス**をスクレイピングしてキーワード判定
3. 当日ヒットを Discord Webhook へ即時投稿
4. 同じヒットを Markdown 形式にまとめ、GitHub Actions 経由で
   `steps.digest.outputs.summary` に渡す（workflow 側で `/daily/…md` にコミット）

依存ライブラリ
--------------
requests / beautifulsoup4 / aiohttp / python-dotenv

環境変数
--------
DISCORD_WEBHOOK_URL  … Discord の投稿先 Webhook
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import time
from typing import List, Tuple

import aiohttp
from bs4 import BeautifulSoup as BS

# ----------- 定数 -----------------
WEBHOOK  = os.getenv("DISCORD_WEBHOOK_URL")
TIMEOUT  = aiohttp.ClientTimeout(total=5)
HEADERS  = {"User-Agent": "EvoMonitor/4.0 (GitHub Actions)"}

KEYWORDS = [
    "第三者割当",
    "新株予約権",
    "行使価額",
    "MSワラント",
    "EVO FUND",
    "Evolution Capital",
]

EVO_NEWS   = "https://www.evofinancialgroup.com/ejs/news/"
TDNET_BASE = "https://release.tdnet.info"

# ---------- 汎用 fetch --------------

async def fetch(session: aiohttp.ClientSession, url: str) -> str | None:
    try:
        async with session.get(url, timeout=TIMEOUT) as resp:
            if resp.status == 200:
                return await resp.text()
    except Exception as exc:
        print(f"⚠️  fetch error {url}: {exc}", file=sys.stderr)
    return None


def hit(title: str) -> bool:
    return any(k in title for k in KEYWORDS)

# ---------- スクレイパ -----------

async def scan_evo(session: aiohttp.ClientSession) -> List[Tuple[str, str]]:
    html = await fetch(session, EVO_NEWS)
    if not html:
        return []
    soup = BS(html, "html.parser")
    items = []
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if hit(title):
            href = a.get("href") or ""
            if href and not href.startswith("http"):
                href = os.path.join(EVO_NEWS, href.lstrip("/"))
            items.append((title, href))
    return items


async def scan_tdnet(session: aiohttp.ClientSession) -> List[Tuple[str, str]]:
    jst = dt.datetime.utcnow() + dt.timedelta(hours=9)
    url = f"{TDNET_BASE}/inbk/{jst:%Y}/{jst:%Y%m%d}/index.html"
    html = await fetch(session, url)
    if not html:
        return []
    soup = BS(html, "html.parser")
    items = []
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if hit(title):
            href = a.get("href") or ""
            if href.startswith("./"):
                href = f"{TDNET_BASE}{href[1:]}"
            items.append((title, href))
    return items

# ---------- Discord 投稿 -----------

async def discord_send(content: str) -> None:
    if not WEBHOOK:
        print("⚠️  DISCORD_WEBHOOK_URL not set – skipping Discord", file=sys.stderr)
        return
    async with aiohttp.ClientSession() as s:
        await s.post(WEBHOOK, json={"content": content[:1900]})

# ---------- Digest 生成 ------------

def build_digest(hits: list[dict]) -> str:
    if not hits:
        return ""
    lines: list[str] = ["# EVO DAILY DIGEST - " + time.strftime("%Y-%m-%d"), ""]
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

# ---------- メイン ---------------

async def main() -> None:
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        evo, tdnet = await asyncio.gather(scan_evo(session), scan_tdnet(session))

    # Discord へ即時送信用文字列（2k 文字制限対応）
    instant_hits = [*(f"[EVO NEWS] {t}\n{u}" for t, u in evo),
                    *(f"[TDNET] {t}\n{u}"    for t, u in tdnet)]
    if instant_hits:
        await discord_send("\n\n".join(instant_hits))

    # Digest 用に dict へ整形
    all_hits = (
        [{"type": "NEWS",  "msg": f"{t}\n{u}"}  for t, u in evo] +
        [{"type": "TDnet", "msg": f"{t}\n{u}"}  for t, u in tdnet]
    )
    digest = build_digest(all_hits)
    if digest:
        print("::set-output name=summary::" +
              digest.replace('%', '%25').replace('\n', '%0A'))

if __name__ == "__main__":
    asyncio.run(main())
