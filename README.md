# saleacc-bot

Telegram-бот для продажи подписок `ChatGPT Plus` и `ChatGPT Pro`.

## Что внутри

- Каталог из четырех тарифов:
  - `ChatGPT Plus · 1 месяц` - `499 RUB`
  - `ChatGPT Pro · 1 месяц` - `4 990 RUB`
  - `ChatGPT Pro · 3 месяца` - `9 990 RUB`
  - `ChatGPT Pro · 6 месяцев` - `13 990 RUB`
- Перед оплатой бот обязательно запрашивает `e-mail` для чека.
- Оплата создается через `ЮKassa` с `redirect confirmation_url`.
- Статусы заказов пишутся в локальную БД и дублируются в Google Sheets.
- После успешной оплаты бот отправляет уведомление клиенту и администраторам.
- Есть простая админ-панель: сводка по заказам и последние продажи.

## Логика продажи

1. Пользователь открывает каталог.
2. Выбирает нужный тариф `Plus` или вариант `Pro`.
3. Бот берет сохраненный `e-mail` или просит ввести новый.
4. Создается заказ в БД.
5. Через API создается платеж в `ЮKassa`.
6. Пользователь оплачивает заказ по ссылке.
7. Webhook `ЮKassa` подтверждает оплату и обновляет заказ.
8. Заказ синхронизируется в Google Sheets.

## Состав продуктов

### ChatGPT Plus · 1 месяц

- Доступ к `ChatGPT Plus`
- `Codex` для кода и рабочих сценариев
- Работа с файлами, изображениями и документами
- Расширенный голосовой режим
- Доступ к `Sora` в лимитах тарифа Plus
- Приоритет относительно бесплатного плана

### ChatGPT Pro · 1 / 3 / 6 месяцев

- Все из `ChatGPT Plus`
- Повышенные лимиты на модели и инструменты
- Расширенный доступ к `Codex`
- Больше лимитов на `Sora` и исследовательские функции
- Приоритетный доступ к новым возможностям OpenAI
- Тариф под интенсивную ежедневную работу

## Переменные окружения

Используй `.env.example` как шаблон.

Обязательные переменные:

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

Опционально:

- `GOOGLE_ORDERS_WORKSHEET` (default `orders`)
- `YOOKASSA_API_BASE` (default `https://api.yookassa.ru/v3`)
- `YOOKASSA_VAT_CODE` (default `1`)
- `YOOKASSA_TAX_SYSTEM_CODE`

## Google Sheets

Инициализируй таблицу:

```bash
PYTHONPATH=src python3 scripts/init_google_sheet.py
```

Создается лист `orders` со схемой:

```text
order_id,created_at,updated_at,status,product_slug,product_title,quantity,customer_email,buyer_tg_id,buyer_username,unit_price,total_price,currency,payment_method,payment_id,payment_status,confirmation_url,paid_at,cancelled_at,cancellation_reason
```

## Запуск локально

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

Healthcheck:

```text
GET /health
```

Webhook endpoint:

```text
POST /webhooks/yookassa
```

## Docker

Поднят `docker-compose.yml` с двумя сервисами:

- `bot` - polling Telegram-бота
- `webhook` - FastAPI для `ЮKassa`

```bash
cp .env.example .env
bash scripts/deploy_docker.sh
```

## Railway

- service `bot`: `./scripts/start_bot_railway.sh`
- service `webhook`: `./scripts/start_webhook_railway.sh`
- подробная инструкция: `docs/deploy_railway.md`

Для Railway можно передавать Google credentials через:

- `GOOGLE_SERVICE_ACCOUNT_JSON_B64`
- или `GOOGLE_SERVICE_ACCOUNT_JSON`

Если используешь `GOOGLE_SERVICE_ACCOUNT_JSON_B64`, туда нужно класть base64 от всего файла service account JSON, а не `project_id`, не `client_id` и не `GOOGLE_SHEET_ID`.

Пример для macOS/Linux:

```bash
base64 < google-service-account.json | tr -d '\n'
```

## Важно по ЮKassa

- бот собирает `e-mail` до создания платежа, чтобы передать его в `receipt.customer.email`
- webhook лучше настроить на события `payment.succeeded` и `payment.canceled`
- после изменения `.env` перезапусти и бота, и webhook-сервис
