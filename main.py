import os
import sys
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from openai import OpenAI


# =========================
# BASIC SETTINGS
# =========================

ALMATY_TZ = timezone(timedelta(hours=5))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

REQUEST_TIMEOUT = 20
OPENAI_TIMEOUT = 60

FINAL_PARAGRAPH = (
    "\n\n"
    "Айбар Олжаевтың болжамды посттары. "
    "Жазылыңыз https://t.me/euroaybar"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# =========================
# SOURCE LIST
# =========================

SOURCES = [
    {
        "name": "KASE Main News",
        "url": "https://kase.kz/ru/news/",
    },
    {
        "name": "Ministry of Finance Kazakhstan",
        "url": "https://www.gov.kz/memleket/entities/minfin/press/news",
    },
    {
        "name": "Bureau of National Statistics Kazakhstan",
        "url": "https://stat.gov.kz/ru/news/",
    },
    {
        "name": "Agency for Regulation and Development of Financial Market",
        "url": "https://www.gov.kz/memleket/entities/ardfm/press/news",
    },
    {
        "name": "National Bank of Kazakhstan",
        "url": "https://nationalbank.kz/ru/news",
    },
    {
        "name": "Kazakhstan Government News",
        "url": "https://primeminister.kz/ru/news",
    },
    {
        "name": "Federal Reserve Press Releases",
        "url": "https://www.federalreserve.gov/newsevents/pressreleases.htm",
    },
    {
        "name": "Federal Reserve Monetary Policy",
        "url": "https://www.federalreserve.gov/monetarypolicy.htm",
    },
    {
        "name": "European Central Bank Press",
        "url": "https://www.ecb.europa.eu/press/html/index.en.html",
    },
    {
        "name": "Bank of England News",
        "url": "https://www.bankofengland.co.uk/news",
    },
    {
        "name": "Bank of Japan News",
        "url": "https://www.boj.or.jp/en/about/press/index.htm",
    },
    {
        "name": "IMF News",
        "url": "https://www.imf.org/en/News",
    },
    {
        "name": "IMF Blog",
        "url": "https://www.imf.org/en/Blogs",
    },
    {
        "name": "World Bank News",
        "url": "https://www.worldbank.org/en/news",
    },
    {
        "name": "BIS Press Releases",
        "url": "https://www.bis.org/press/",
    },
    {
        "name": "MarketWatch Top Stories",
        "url": "https://www.marketwatch.com/",
    },
    {
        "name": "Investing.com Forex News",
        "url": "https://www.investing.com/news/forex-news",
    },
    {
        "name": "Investing.com Commodities News",
        "url": "https://www.investing.com/news/commodities-news",
    },
    {
        "name": "Yahoo Finance News",
        "url": "https://finance.yahoo.com/news/",
    },
]


# =========================
# VALIDATION
# =========================

def validate_env():
    missing = []

    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")

    if not TELEGRAM_CHANNEL_ID:
        missing.append("TELEGRAM_CHANNEL_ID")

    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")

    if missing:
        raise RuntimeError(f"Missing GitHub Secrets: {', '.join(missing)}")


# =========================
# HTTP HELPERS
# =========================

def safe_get(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.text

    except Exception as exc:
        logging.warning("Source failed: %s | %s", url, exc)
        return ""


def extract_text_from_html(html: str, max_chars: int = 3500) -> str:
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    text = " ".join(text.split())

    return text[:max_chars]


# =========================
# COLLECT SOURCES
# =========================

def collect_sources() -> str:
    logging.info("Start collecting sources")

    chunks = []

    for source in SOURCES:
        name = source["name"]
        url = source["url"]

        html = safe_get(url)
        text = extract_text_from_html(html)

        if text:
            logging.info("Source OK: %s | chars=%s", name, len(text))
            chunks.append(f"### {name}\n{text}\nURL: {url}")
        else:
            logging.warning("Source EMPTY: %s", name)

        time.sleep(0.5)

    if not chunks:
        raise RuntimeError("No source data collected")

    logging.info("Sources collected: %s", len(chunks))

    return "\n\n".join(chunks)


# =========================
# OPENAI
# =========================

def get_openai_client() -> OpenAI:
    return OpenAI(
        api_key=OPENAI_API_KEY,
        timeout=OPENAI_TIMEOUT,
    )


def clean_post(text: str) -> str:
    text = text.strip()

    unwanted_phrases = [
        "Айбар Олжаевтың болжамды посттары",
        "Жазылыңыз https://t.me/euroaybar",
        "https://t.me/euroaybar",
        "@euroaybar"
    ]

    lines = text.splitlines()
    cleaned_lines = []

    for line in lines:
        if any(phrase.lower() in line.lower() for phrase in unwanted_phrases):
            continue
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def add_final_paragraph(text: str) -> str:
    text = clean_post(text)

    max_telegram_length = 4096
    reserve = len(FINAL_PARAGRAPH) + 50

    if len(text) + reserve > max_telegram_length:
        text = text[: max_telegram_length - reserve]
        text = text.rsplit(" ", 1)[0].strip()

    return text + FINAL_PARAGRAPH


def generate_analytics_post(source_text: str) -> str:
    logging.info("Start AI generation: analytics post")

    client = get_openai_client()

    prompt = f"""
Сен Қазақстандағы қаржы, экономика және нарық тақырыптарын жазатын Telegram-арна авторысың.

Міндет: бір аналитикалық пост жазу.

Тіл талабы:
- тек қазақша жаз;
- орысша сөйлем қолданба;
- ресми аударма сияқты ауыр қылма;
- қазақша табиғи, қарапайым, түсінікті, бірақ қаржылық дәлдігі бар стиль керек;
- сөйлемдер тым ұзақ болмасын.

Стиль:
- Айбарлық стиль;
- қарапайым адам түсінетіндей жаз;
- бірақ қаржы маманы оқыса да ұят болмайтын аналитика болсын;
- тақырып нақты әрі тартымды болсын;
- артық пафоссыз, бірақ ойы өткір болсын.

Формат:
- күшті тақырып қой;
- 5-8 абзац жаз;
- тақырыптан кейін бірден негізгі ойға көш;
- Қазақстан, теңге, банктер, бюджет, мұнай, инфляция, базалық мөлшерлеме, әлемдік нарықтар контексін ескер;
- дерек жоқ жерде нақты факт ойдан шығарма;
- егер дерек әлсіз болса, нарықтық шолу форматында жаз;
- markdown-кесте қолданба;
- сілтеме қойма;
- хэштег қоспа;
- emoji қолданба;
- өзіңді жасанды интеллект деп айтпа;
- соңғы абзацқа канал туралы ештеңе жазба, оны жүйе өзі қосады.

Маңызды:
- материалдарда нақты цифр болса ғана цифр қолдан;
- нақты дерек жоқ болса, "нарық үшін маңызды белгі", "инвесторлар үшін сигнал", "теңге үшін қысым/қолдау факторы" сияқты абайлы тұжырым жаса;
- "анық өседі", "міндетті түрде құлайды" сияқты кесімді болжам айтпа.

Материалдар:
{source_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "Сен қазақ тілінде қаржы-экономикалық Telegram аналитика жазатын авторсың.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.7,
        max_tokens=1200,
    )

    text = response.choices[0].message.content.strip()

    if not text:
        raise RuntimeError("OpenAI returned empty analytics post")

    text = add_final_paragraph(text)

    logging.info("AI generation done: analytics post | chars=%s", len(text))

    return text


def generate_fx_forecast_post(source_text: str) -> str:
    logging.info("Start AI generation: FX forecast post")

    client = get_openai_client()

    today_almaty = datetime.now(ALMATY_TZ).strftime("%d.%m.%Y")

    prompt = f"""
Сен Қазақстандағы қаржы және валюта нарығын түсіндіретін Telegram-арна авторысың.

Міндет: {today_almaty} күніне арналған доллар/теңге бағамы бойынша күнделікті болжам пост жазу.

Тіл талабы:
- Айбарлық стиль;
- қарапайым адам түсінетіндей жаз;
- бірақ қаржы маманы оқыса да ұят болмайтын аналитика болсын;
- тақырып нақты әрі тартымды болсын;
- артық пафоссыз, бірақ ойы өткір болсын.

Міндетті мазмұн:
- тақырып қой;
- 5-8 абзац жаз;
- алдағы тәулікке USD/KZT бойынша күтілетін диапазон бер;
- диапазонды тым нақты емес, сақтықпен бер;
- диапазонды "базалық сценарий" деп түсіндір;
- мұнай бағасы, доллар индексі, рубль, Ұлттық банк, базалық мөлшерлеме, валютаға сұраныс, бюджет/салық төлемдері, сыртқы нарық факторларын түсіндір;
- Қазақстан ішіндегі факторларды бөлек атап өт;
- сыртқы нарық факторларын бөлек түсіндір;
- қорытындыда теңге үшін негізгі тәуекел мен негізгі қолдау факторын айт.

Шектеулер:
- дерек жоқ жерде нақты биржалық котировка ойдан шығарма;
- болжамды үзілді-кесілді айтпа;
- "теңге міндетті түрде нығаяды" немесе "доллар міндетті түрде қымбаттайды" деме;
- markdown-кесте қолданба;
- сілтеме қойма;
- хэштег қоспа;
- emoji қолданба;
- өзіңді жасанды интеллект деп айтпа;
- соңғы абзацқа канал туралы ештеңе жазба, оны жүйе өзі қосады.

Материалдар:
{source_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "Сен қазақ тілінде USD/KZT бойынша күнделікті болжам жазатын қаржы сарапшысысың.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.65,
        max_tokens=1300,
    )

    text = response.choices[0].message.content.strip()

    if not text:
        raise RuntimeError("OpenAI returned empty FX forecast post")

    text = add_final_paragraph(text)

    logging.info("AI generation done: FX forecast post | chars=%s", len(text))

    return text


# =========================
# TELEGRAM
# =========================

def send_telegram_message(text: str):
    logging.info("Start Telegram send")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    response = requests.post(
        url,
        data=payload,
        timeout=REQUEST_TIMEOUT,
    )

    try:
        response.raise_for_status()
    except Exception as exc:
        logging.error("Telegram response: %s", response.text)
        raise exc

    logging.info("Telegram send done")


# =========================
# POST MODES
# =========================

def run_analytics():
    logging.info("Run mode: analytics")

    source_text = collect_sources()
    post = generate_analytics_post(source_text)
    send_telegram_message(post)

    logging.info("Analytics post finished successfully")


def run_fx_forecast():
    logging.info("Run mode: fx_forecast")

    source_text = collect_sources()
    post = generate_fx_forecast_post(source_text)
    send_telegram_message(post)

    logging.info("FX forecast post finished successfully")


# =========================
# ENTRY POINT
# =========================

def main():
    validate_env()

    mode = "analytics"

    if len(sys.argv) >= 2:
        mode = sys.argv[1].strip().lower()

    logging.info("Selected mode: %s", mode)

    if mode == "analytics":
        run_analytics()

    elif mode in ["fx", "fx_forecast", "forecast"]:
        run_fx_forecast()

    else:
        raise RuntimeError(f"Unknown mode: {mode}")


if __name__ == "__main__":
    main()
