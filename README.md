# saleacc-bot

Telegram-бот витрины `NH | STORE01` для продажи:

- `ChatGPT Plus` — `499 ₽/мес`
- `ChatGPT Pro` — `4 990 ₽/мес`
- `Google AI Ultra` — `7 990 ₽/мес`

## Что сейчас в проекте

- стартовый экран с двумя разделами: `ChatGPT` и `Gemini`
- карточки тарифов с актуальными ценами, официальной ценой и экономией
- оформление заказа через `ЮKassa`
- сохранение заказов в БД
- синхронизация заказов в Google Sheets
- админ-панель со статистикой и последними заказами

## Каталог

### ChatGPT

- `ChatGPT Plus`
- `ChatGPT Pro`

### Gemini

- `Google AI Ultra`

## Переменные окружения

Обязательные:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_IDS`
- `SUPPORT_URL`
- `PUBLIC_OFFER_URL`
- `DATABASE_URL`
- `GOOGLE_SHEET_ID`
- один из вариантов Google credentials:
  - `GOOGLE_SERVICE_ACCOUNT_FILE`
  - `GOOGLE_SERVICE_ACCOUNT_JSON`
  - `GOOGLE_SERVICE_ACCOUNT_JSON_B64`
- `YOOKASSA_SHOP_ID`
- `YOOKASSA_SECRET_KEY`
- `YOOKASSA_RETURN_URL`

Опциональные:

- `GOOGLE_ORDERS_WORKSHEET` default `orders`
- `YOOKASSA_API_BASE` default `https://api.yookassa.ru/v3`
- `YOOKASSA_VAT_CODE` default `1`
- `YOOKASSA_TAX_SYSTEM_CODE`

## Google Sheets

Перед первым запуском обязательно:

- включи `Google Sheets API` в Google Cloud project service account
- расшарь таблицу на service account email с правами `Editor`

Инициализация:

```bash
PYTHONPATH=src python3 scripts/init_google_sheet.py
```

Если в логах есть `APIError: [403]: Google Sheets API has not been used in project ... or it is disabled`, значит credentials валидны, но `Google Sheets API` выключен в GCP.

## Локальный запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
PYTHONPATH=src python3 -m saleacc_bot.main
```

Webhook:

```bash
PYTHONPATH=src uvicorn saleacc_bot.webhook_app:app --host 0.0.0.0 --port 8000
```

## Railway

- `bot`: `./scripts/start_bot_railway.sh`
- `webhook`: `./scripts/start_webhook_railway.sh`
- инструкция: `docs/deploy_railway.md`
