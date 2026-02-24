# saleacc-bot

Telegram marketplace bot with Google Sheets inventory.

## What is implemented

- Inline UX flow (`/start` -> каталог -> сервис -> вариант тарифа -> количество -> crypto checkout).
- Stock is read from Google Sheet (`inventory` worksheet).
- On successful payment, bot marks rows as sold in Sheet and sends CSV to user.
- Sales log is written into `sales` worksheet.
- Admin block in bot (`Admin` button for admin IDs only).

## Required env

Use `.env.example` as template.

Key variables:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_IDS`
- `SUPPORT_URL` (direct `https://t.me/...` link for Support button)
- `DATABASE_URL`
- `EXPORT_DIR`
- `GOOGLE_SHEET_ID`
- `GOOGLE_SERVICE_ACCOUNT_FILE`
- `GOOGLE_INVENTORY_WORKSHEET` (default `inventory`)
- `GOOGLE_SALES_WORKSHEET` (default `sales`)
- `CRYPTOBOT_ENABLED`
- `CRYPTOBOT_API_BASE`
- `CRYPTOBOT_API_TOKEN`
- `CRYPTOBOT_ASSET`
- `TEST_MODE_ENABLED` (`true/false`) - allow issue without real payment
- `TEST_MODE_ADMIN_ONLY` (`true/false`) - show test button only for admins

## Google Sheet setup

1. Create a Google Sheet.
2. Create Google Cloud Service Account and download JSON key.
3. Share the sheet with service account email as `Editor`.
4. Put JSON file path into `GOOGLE_SERVICE_ACCOUNT_FILE`.
5. Put sheet ID into `GOOGLE_SHEET_ID`.
6. Initialize worksheet schema:

```bash
PYTHONPATH=src python3 scripts/init_google_sheet.py
```

This creates/updates worksheets:

- `inventory` with headers:
  - `item_id,product,status,access_login,access_secret,note,sold_to_tg_id,sold_to_username,sold_at,order_id,payment_method,extra_instruction,reserved_for_order_id,reserved_by_tg_id,reserved_until,reserved_at`
- `sales` with headers:
  - `sale_id,order_id,product,quantity,buyer_tg_id,buyer_username,payment_method,total_price,currency,delivered_item_ids,sold_at`

## Filling inventory manually

In worksheet `inventory`:

- `product` (one of):
  - `gpt-pro-1m`
  - `gpt-pro-3m`
  - `lovable-100`
  - `lovable-200`
  - `lovable-300`
  - `replit-core`
  - `replit-team`
- `status`: `free`
- `access_login`: login/email
- `access_secret`: secret/password/token
- `note`: optional
- `extra_instruction`: optional additional instruction for this account

Example row:

```text
item_id=gpt1m-001, product=gpt-pro-1m, status=free, access_login=user@example.com, access_secret=pass123
```

### RU: Что заполнять в таблице

Ты заполняешь руками только эти 4 поля:

- `product` -> SKU тарифа (`gpt-pro-1m`, `gpt-pro-3m`, `lovable-100`, `lovable-200`, `lovable-300`, `replit-core`, `replit-team`)
- `status` -> статус (`free`)
- `access_login` -> логин (gmail/почта аккаунта)
- `access_secret` -> пароль

Опционально:

- `note` -> комментарий
- `item_id` -> любой уникальный ID (если пусто, лучше все равно проставлять вручную)
- `extra_instruction` -> доп. инструкция для конкретного аккаунта (в CSV попадет только если заполнена хотя бы у одного выданного аккаунта)

Остальные колонки бот заполнит сам после продажи:

- `sold_to_tg_id`
- `sold_to_username`
- `sold_at`
- `order_id`
- `payment_method`
- `reserved_for_order_id`
- `reserved_by_tg_id`
- `reserved_until`
- `reserved_at`

### Reservation logic

- На этапе создания заказа под оплату бот резервирует выбранное количество аккаунтов.
- Статус строк меняется на `reserved` на 20 минут.
- Пока строка `reserved`, она не участвует в доступном остатке для других покупателей.
- Если оплата не прошла за 20 минут, резерв снимается автоматически и статус возвращается в `free`.
- После оплаты статус меняется в `sold`.

### Payment channels

- `Криптой` -> Crypto Bot API (`/createInvoice`) + webhook `/webhooks/cryptobot`

## CSV import helper

Import rows from CSV:

```bash
PYTHONPATH=src python3 scripts/load_inventory.py --product gpt-pro-1m --file ./inventory_gpt_1m.csv
```

CSV headers supported:

- `access_login,access_secret,note,extra_instruction`
- or `email,password,note,instruction`

## Run bot

```bash
PYTHONPATH=src python3 -m saleacc_bot.main
```

For local testing (always single instance, kill old process first):

```bash
./scripts/run_local_bot.sh
```

Stop local bot processes:

```bash
./scripts/stop_local_bot.sh
```

## Test mode without payment

Set in `.env`:

```env
TEST_MODE_ENABLED=true
TEST_MODE_ADMIN_ONLY=true
```

Then in product checkout screen admin will see button `Тест: без оплаты`.
It creates order, marks paid, updates Sheet and sends CSV immediately.

## Run webhook app

```bash
PYTHONPATH=src uvicorn saleacc_bot.webhook_app:app --host 0.0.0.0 --port 8000
```

Endpoints:

- `POST /webhooks/cryptobot`

## VPS Deployment

One-command Docker deploy is prepared:

- First install on VPS: `bash scripts/bootstrap_vps.sh`
- Next updates: `bash scripts/deploy_docker.sh`
- Full guide: `docs/deploy_vps.md`

Docker files:

- `Dockerfile`
- `docker-compose.yml`
- `requirements.txt`

## Railway Deploy

Use two Railway services from one repository:

- `bot` service (Telegram polling)
- `webhook` service (public HTTPS endpoint for CryptoBot)

### 1. Create shared Postgres

Add PostgreSQL in Railway project and use it for both services.

### 2. Create service `bot` from this repo

- Start Command: `./scripts/start_bot_railway.sh`
- Variables:
  - `DATABASE_URL` -> Postgres URL
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_ADMIN_IDS`
  - `SUPPORT_URL`
  - `GOOGLE_SHEET_ID`
  - `GOOGLE_SERVICE_ACCOUNT_JSON_B64` (base64 of Google SA JSON)
  - `CRYPTOBOT_ENABLED`
  - `CRYPTOBOT_API_TOKEN`
  - `CRYPTOBOT_ASSET`
  - `TEST_MODE_ENABLED`
  - `TEST_MODE_ADMIN_ONLY`

### 3. Create service `webhook` from this repo

- Start Command: `./scripts/start_webhook_railway.sh`
- Use the same variables as in `bot`.
- Generate public domain in Railway.

### 4. Configure webhook URL in CryptoBot

Set URL:

`https://<railway-webhook-domain>/webhooks/cryptobot`

Health check:

`https://<railway-webhook-domain>/health`

## Admin

- In bot main menu, admins see `Admin` button.
- Inside `Admin` there is inline menu:
  - `Статистика` (stock/reserved/sold + audience stats)
  - `Продажи` (recent sales from Google Sheet)
  - `Рассылка` (send next message as broadcast; supports text/media)
- All admin screens use inline navigation with `Назад`.
- Command `/admin` opens the same admin panel in chat.
- Existing command helpers:
  - `/stock`
  - `/sales`
  - `/mark_paid <order_id>`
  - `/broadcast <текст>`
  - `/broadcast` as reply to media/text message
