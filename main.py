import os
import re
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

STATE_FILE = "posted_hashes.txt"
MAX_ITEMS = 14

FINANCE_KEYWORDS = [
    "rate", "inflation", "tenge", "dollar", "currency", "bond", "yield", "oil", "brent",
    "bank", "kase", "stock", "market", "budget", "deficit", "debt", "gdp", "export",
    "import", "national bank", "ministry of finance", "fed", "ecb", "imf", "world bank",
    "ставка", "инфляция", "тенге", "доллар", "облигац", "доходност", "нефть",
    "банк", "рынок", "бюджет", "дефицит", "долг", "ввп", "экспорт", "импорт"
]


def load_sources() -> List[Dict[str, Any]]:
    with open("sources.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("feeds", [])


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def item_hash(item: Dict[str, str]) -> str:
    raw = f"{item.get('title','')}|{item.get('link','')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def load_posted_hashes() -> set:
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_posted_hash(h: str) -> None:
    with open(STATE_FILE, "a", encoding="utf-8") as f:
        f.write(h + "\n")


def looks_financial(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in FINANCE_KEYWORDS)


def fetch_feed_or_page(source: Dict[str, Any]) -> List[Dict[str, str]]:
    url = source["url"]
    name = source["name"]
    items: List[Dict[str, str]] = []

    try:
        parsed = feedparser.parse(url)
        if parsed.entries:
            for e in parsed.entries[:8]:
                title = normalize(e.get("title", ""))
                link = e.get("link", url)
                summary = normalize(BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" "))
                text = f"{title}. {summary}"
                if title and looks_financial(text):
                    items.append({"source": name, "title": title, "link": link, "summary": summary})
            return items
    except Exception:
        pass

    # Fallback: light extraction from public page headlines. For production, replace with official API/paid feed.
    try:
        headers = {"User-Agent": "EuroAybarBot/0.1 editorial research"}
        r = requests.get(url, timeout=12, headers=headers)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        candidates = []
        for tag in soup.find_all(["h1", "h2", "h3", "a"], limit=120):
            title = normalize(tag.get_text(" "))
            if len(title) < 20 or len(title) > 180:
                continue
            href = tag.get("href") or url
            if href.startswith("/"):
                from urllib.parse import urljoin
                href = urljoin(url, href)
            text = title
            if looks_financial(text):
                candidates.append({"source": name, "title": title, "link": href, "summary": ""})
        seen = set()
        for c in candidates:
            h = item_hash(c)
            if h not in seen:
                seen.add(h)
                items.append(c)
            if len(items) >= 6:
                break
    except Exception as exc:
        print(f"Source failed: {name}: {exc}")

    return items


def collect_items() -> List[Dict[str, str]]:
    posted = load_posted_hashes()
    all_items = []
    for src in load_sources():
        for item in fetch_feed_or_page(src):
            h = item_hash(item)
            if h not in posted:
                item["hash"] = h
                item["weight"] = src.get("weight", 3)
                all_items.append(item)
    all_items.sort(key=lambda x: x.get("weight", 3), reverse=True)
    return all_items[:MAX_ITEMS]


def build_prompt(items: List[Dict[str, str]]) -> str:
    bulletins = "\n".join(
        f"- [{i['source']}] {i['title']} — {i.get('summary','')} ({i['link']})" for i in items
    )
    return f"""
Сен EuroAybar Telegram-арнасының қаржы шолушысысың. Міндет: төмендегі жаңалықтардан ең маңызды 1 тақырыпты таңдап, қазақ тілінде қысқа аналитикалық пост жаз.

Стиль: Айбарлық баға. Яғни мәтін қысқа, дәл, сәл образды, бірақ фактіні бұрмаламайды. Пост оқырманға: «не болды?», «неге маңызды?», «Қазақстан/теңге/нарық үшін қандай белгі?» деген үш сұраққа жауап берсін.

Қатаң талаптар:
- 700-950 таңба.
- Қазақ тілінде.
- Бірінші сөйлем ілмек болсын.
- Факт пен авторлық бағаны ажырат.
- Сыбыс немесе болжам болса, нақты белгіле.
- Инвестициялық кеңес берме.
- Соңында 1 қысқа қорытынды сөйлем және #EuroAybar хэштегі болсын.
- Дереккөз атауын табиғи түрде атап өт, бірақ URL қоспа.

Материалдар:
{bulletins}
""".strip()


def generate_post(items: List[Dict[str, str]]) -> str:
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = build_prompt(items)
    resp = client.responses.create(
        model=MODEL,
        input=prompt,
        temperature=0.7,
    )
    return resp.output_text.strip()


def send_to_telegram(text: str) -> None:
    if DRY_RUN:
        print("\n--- DRY RUN POST ---\n")
        print(text)
        return
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()


def main() -> None:
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY")

    items = collect_items()
    if not items:
        print("No new finance items found.")
        return

    post = generate_post(items)
    send_to_telegram(post)

    for item in items[:5]:
        save_posted_hash(item["hash"])

    print(f"Done at {datetime.now(timezone.utc).isoformat()}. Items used: {len(items)}")


if __name__ == "__main__":
    main()
