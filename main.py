import os
import re
import time
import yaml
import html
import random
import logging
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from openai import OpenAI


# =========================
# EuroAybar configuration
# =========================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
MODE = os.getenv("MODE", "news")

MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
SOURCES_FILE = os.getenv("SOURCES_FILE", "sources.yaml")

MAX_ITEMS = int(os.getenv("MAX_ITEMS", "14"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))

FINAL_LINE = "Айбар Олжаевтың болжамды посттары. Жазылыңыз https://t.me/euroaybar"

client = OpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# =========================
# Basic helpers
# =========================

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_url(url: str) -> str:
    return (url or "").strip()


def now_almaty() -> str:
    almaty_tz = timezone(timedelta(hours=5))
    return datetime.now(almaty_tz).strftime("%Y-%m-%d %H:%M:%S Алматы уақыты")


def load_sources() -> list:
    if not os.path.exists(SOURCES_FILE):
        logging.warning("sources.yaml not found. Using fallback sources.")
        return fallback_sources()

    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Supports both formats:
    # feeds:
    #   - name: ...
    # sources:
    #   - name: ...
    feeds = data.get("feeds") or data.get("sources") or []
    if not feeds:
        logging.warning("No feeds found in sources.yaml. Using fallback sources.")
        return fallback_sources()

    return feeds


def fallback_sources() -> list:
    return [
        {
            "name": "KASE Market and Company News",
            "url": "https://kase.kz/en/information/news/all/",
            "region": "KZ",
            "weight": 5,
        },
        {
            "name": "Federal Reserve All Press Releases",
            "url": "https://www.federalreserve.gov/feeds/press_all.xml",
            "region": "US",
            "weight": 5,
        },
        {
            "name": "European Central Bank Press",
            "url": "https://www.ecb.europa.eu/rss/press.html",
            "region": "EU",
            "weight": 5,
        },
        {
            "name": "BIS Press Releases",
            "url": "https://www.bis.org/list/press_releases/index.rss",
            "region": "GLOBAL",
            "weight": 4,
        },
        {
            "name": "MarketWatch Top Stories",
            "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
            "region": "GLOBAL_MARKETS",
            "weight": 3,
        },
        {
            "name": "Investing.com Latest News",
            "url": "https://www.investing.com/rss/news.rss",
            "region": "GLOBAL_MARKETS",
            "weight": 3,
        },
    ]


# =========================
# Source collection
# =========================

def fetch_rss(source: dict) -> list:
    url = normalize_url(source.get("url"))
    name = source.get("name", "Unknown source")
    weight = int(source.get("weight", 3))
    region = source.get("region", "")

    parsed = feedparser.parse(url)
    items = []

    for entry in parsed.entries[:10]:
        title = clean_text(entry.get("title", ""))
        summary = clean_text(entry.get("summary", "") or entry.get("description", ""))
        link = entry.get("link", "")

        if not title:
            continue

        items.append({
            "source": name,
            "region": region,
            "weight": weight,
            "title": title,
            "summary": summary[:600],
            "url": link,
        })

    return items


def fetch_web_page(source: dict) -> list:
    url = normalize_url(source.get("url"))
    name = source.get("name", "Unknown source")
    weight = int(source.get("weight", 3))
    region = source.get("region", "")

    headers = {
        "User-Agent": "Mozilla/5.0 EuroAybarBot/1.0 financial media research"
    }

    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    candidates = []

    # Collect visible headings and meaningful links
    for element in soup.find_all(["h1", "h2", "h3", "a"]):
        text = clean_text(element.get_text(" "))
        if len(text) < 25:
            continue
        if len(text) > 220:
            text = text[:220]

        link = element.get("href", "")
        if link and link.startswith("/"):
            base = re.match(r"^https?://[^/]+", url)
            if base:
                link = base.group(0) + link

        candidates.append({
            "source": name,
            "region": region,
            "weight": weight,
            "title": text,
            "summary": "",
            "url": link or url,
        })

    # Deduplicate by title
    seen = set()
    unique = []
    for item in candidates:
        key = item["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return unique[:10]


def fetch_source(source: dict) -> list:
    url = normalize_url(source.get("url"))

    try:
        if url.endswith(".xml") or url.endswith(".rss") or "rss" in url.lower() or "feeds." in url.lower():
            items = fetch_rss(source)
        else:
            # Try RSS parser first anyway; if empty, use page parser
            rss_items = fetch_rss(source)
            items = rss_items if rss_items else fetch_web_page(source)

        logging.info("Source OK: %s | items=%s", source.get("name"), len(items))
        return items

    except Exception as e:
        logging.warning("Source failed: %s: %s", source.get("name"), str(e))
        return []


def collect_items() -> list:
    sources = load_sources()
    all_items = []

    for source in sources:
        items = fetch_source(source)
        all_items.extend(items)
        time.sleep(0.3)

    if not all_items:
        logging.warning("No source items collected.")
        return []

    filtered = []
    keywords = [
        "rate", "inflation", "tenge", "dollar", "oil", "brent", "bond",
        "market", "bank", "central bank", "fed", "ecb", "imf", "world bank",
        "kazakhstan", "kase", "currency", "yield", "debt", "budget",
        "growth", "gdp", "trade", "export", "import", "recession",
        "monetary", "finance", "stock", "commodities", "gold", "rub"
    ]

    for item in all_items:
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        score = int(item.get("weight", 3))

        for kw in keywords:
            if kw in text:
                score += 2

        item["score"] = score
        filtered.append(item)

    filtered.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Small shuffle among top items so channel is not repetitive
    top = filtered[:25]
    random.shuffle(top)
    top.sort(key=lambda x: x.get("score", 0), reverse=True)

    selected = top[:MAX_ITEMS]
    logging.info("Collected total=%s | selected=%s", len(all_items), len(selected))
    return selected


def format_items_for_prompt(items: list) -> str:
    if not items:
        return "Нарықтық дерек аз. Жалпы қаржы нарығы бойынша сақ аналитикалық пост жаз."

    lines = []
    for i, item in enumerate(items, start=1):
        title = item.get("title", "")
        source = item.get("source", "")
        region = item.get("region", "")
        summary = item.get("summary", "")
        url = item.get("url", "")

        lines.append(
            f"{i}. Source: {source} | Region: {region}\n"
            f"Title: {title}\n"
            f"Summary: {summary}\n"
            f"URL: {url}\n"
        )

    return "\n".join(lines)


# =========================
# OpenAI generation
# =========================

def enforce_final_line(text: str) -> str:
    text = text.strip()

    # Remove old hashtags / old endings if model adds them
    text = re.sub(r"#EuroAybar", "", text, flags=re.IGNORECASE)
    text = re.sub(r"#Euroайбар", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()

    # Keep paragraph breaks readable
    text = text.replace("Айбарлық баға:", "\n\nАйбарлық баға:")
    text = text.replace("Бұл инвестициялық кеңес емес", "\n\nБұл инвестициялық кеңес емес")

    if FINAL_LINE not in text:
        text = text.rstrip() + "\n\n" + FINAL_LINE
    else:
        # Ensure final line is actually final
        text = text.replace(FINAL_LINE, "").strip()
        text = text + "\n\n" + FINAL_LINE

    return text.strip()


def generate_news_post(items: list) -> str:
    source_digest = format_items_for_prompt(items)

    prompt = f"""
Сен EuroАйбар атты Telegram қаржы-аналитикалық арнасының авторысың.
Арна авторы — Айбар Олжаев. Стиль: қысқа, нақты, интеллектуалды, қаржы нарығын қарапайым адамға түсіндіретін, бірақ сараптамалық салмағы бар.

Міндет:
Төмендегі әлемдік және қазақстандық қаржы дереккөздерінен қысқа аналитикалық пост жаз.
Пост қазақ тілінде болуы керек.
Постта жай жаңалық емес, авторлық Айбарлық баға болуы керек.

Қазіргі уақыт:
{now_almaty()}

Дереккөздер:
{source_digest}

Қатаң талаптар:
- 700-1100 таңба.
- Қазақ тілінде жаз.
- Бірінші сөйлем ілмек болсын.
- Факт пен авторлық бағаны ажырат.
- Сыбыс немесе болжам болса, нақты белгіле.
- Инвестициялық кеңес берме.
- Дереккөз атауын табиғи түрде атап өт, бірақ URL қоспа.
- #EuroAybar немесе басқа хэштег қоспа.
- Посттың ең соңғы жолы дәл мына мәтін болсын:
{FINAL_LINE}

Формат:
1) Қысқа ілмек.
2) Негізгі факт.
3) Қазақстанға немесе теңгеге/мұнайға/нарыққа ықпалы.
4) "Айбарлық баға:" деген бөлек сөйлем.
5) Соңғы жол: {FINAL_LINE}
"""

    response = client.responses.create(
        model=MODEL,
        input=prompt,
    )

    return enforce_final_line(response.output_text)


def generate_fx_forecast(items: list) -> str:
    source_digest = format_items_for_prompt(items)

    prompt = f"""
Сен EuroАйбар арнасының қаржы-валюта шолушысысың.
Автор — Айбар Олжаев.

Міндет:
USD/KZT бойынша ертеңгі күнге авторлық болжам жаз.
Бұл нақты инвестициялық кеңес емес, нарықтық факторларға сүйенген авторлық болжам болуы керек.

Қазіргі уақыт:
{now_almaty()}

Қолдағы нарықтық және қаржы деректері:
{source_digest}

Талдауда ескер:
- USD/KZT бағыты
- Brent мұнайы
- АҚШ долларының жаһандық күшеюі/әлсіреуі
- ФРЖ/ЕОБ риторикасы
- рубль факторы
- Қазақстандағы ішкі валюта сұранысы
- KASE, НБК, макро және нарық фоны
- егер нақты сандық дерек жеткіліксіз болса, тым батыл нақты курс айтпа, сақ диапазон бер

Қатаң талаптар:
- Қазақ тілінде.
- 900-1300 таңба.
- Тақырып бірінші жолда болсын: USD/KZT бойынша ертеңгі Айбарлық болжам
- Бірінші абзацта ертеңге күтілетін дәлізді көрсет. Мысалы: "Менің ертеңгі күтуім: доллар 000–000 теңге дәлізінде саудалануы мүмкін."
- Дәліз тым кең болмасын, бірақ нақты дерек аз болса сақ бол.
- "Айбарлық баға:" деген бөлек аналитикалық сөйлем болсын.
- Міндетті түрде мына сөйлем болсын: Бұл инвестициялық кеңес емес, авторлық болжам.
- #EuroAybar немесе басқа хэштег қоспа.
- Посттың ең соңғы жолы дәл мына мәтін болсын:
{FINAL_LINE}

Маңызды:
- Курсқа кепілдік берме.
- "Міндетті түрде болады" деп жазба.
- "Мүмкін", "ықтимал", "негізгі сценарий" деген сақ формулировкаларды қолдан.
- Авторлық стиль салмақты болсын.
"""

    response = client.responses.create(
        model=MODEL,
        input=prompt,
    )

    text = response.output_text.strip()

    if "Бұл инвестициялық кеңес емес, авторлық болжам." not in text:
        text += "\n\nБұл инвестициялық кеңес емес, авторлық болжам."

    return enforce_final_line(text)


# =========================
# Telegram sending
# =========================

def send_telegram(text: str) -> None:
    if DRY_RUN:
        logging.info("DRY_RUN=true. Telegram message not sent.")
        print("\n--- GENERATED POST ---\n")
        print(text)
        return

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing.")

    if not TELEGRAM_CHANNEL_ID:
        raise RuntimeError("TELEGRAM_CHANNEL_ID is missing.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "disable_web_page_preview": False,
    }

    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    logging.info("Telegram post sent successfully.")


# =========================
# Main
# =========================

def main() -> None:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    logging.info("EuroAybar started. MODE=%s | MODEL=%s", MODE, MODEL)

    items = collect_items()

    if MODE == "fx_forecast":
        post = generate_fx_forecast(items)
    else:
        post = generate_news_post(items)

    send_telegram(post)

    logging.info(
        "Done at %s. Items used: %s",
        datetime.now(timezone.utc).isoformat(),
        len(items)
    )


if __name__ == "__main__":
    main()
