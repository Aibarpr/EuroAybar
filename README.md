# EuroAybar автоматический Telegram-канал

MVP для автоматической публикации коротких финансово-аналитических постов на казахском языке каждые 2 часа.

## Что делает бот

1. Собирает последние материалы из `sources.yaml`.
2. Отбирает финансово важные события.
3. Генерирует короткий казахский пост с авторской «Айбарской оценкой».
4. Публикует пост в Telegram-канал через Bot API.

## Быстрый запуск локально

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
# заполните OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
python main.py
```

Сначала оставьте `DRY_RUN=true`, чтобы увидеть пост в консоли без публикации. После проверки поставьте `DRY_RUN=false`.

## Telegram-настройка

1. Создайте канал `EuroAybar` в Telegram.
2. Через @BotFather создайте бота.
3. Добавьте бота администратором канала с правом публикации сообщений.
4. В `.env` укажите `TELEGRAM_CHANNEL_ID=@EuroAybar`.

## GitHub Actions

В репозитории добавьте Secrets:

- `OPENAI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHANNEL_ID`

Workflow `.github/workflows/euroaybar.yml` запускает публикацию каждые 2 часа.

## Политика качества

- Не копировать новости дословно.
- Не выдавать слухи за факты.
- Каждая публикация должна содержать смысл: что произошло, почему важно, что это значит для Казахстана/тенге/инвесторов.
- При низкой уверенности — писать осторожно: «мүмкін», «нарық мұны былай оқуы ықтимал».
