# Railway Deploy

## Архитектура

Нужно поднять два сервиса из одного репозитория:

- `bot` - Telegram polling
- `webhook` - FastAPI endpoint для `ЮKassa`

Оба сервиса должны использовать одну и ту же `Postgres` базу и один набор переменных окружения.

## 1. Подключи репозиторий

Создай Railway project и подключи этот GitHub-репозиторий.

## 2. Создай Postgres

Добавь в проект Railway plugin `PostgreSQL`.

Затем прокинь в оба сервиса:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

## 3. Создай сервис `bot`

Настройки:

- Start Command: `./scripts/start_bot_railway.sh`

Переменные:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_IDS`
- `SUPPORT_URL`
- `PUBLIC_OFFER_URL`
- `DATABASE_URL`
- `GOOGLE_SHEET_ID`
- `GOOGLE_ORDERS_WORKSHEET`
- `GOOGLE_SERVICE_ACCOUNT_JSON_B64` или `GOOGLE_SERVICE_ACCOUNT_JSON`
- `YOOKASSA_SHOP_ID`
- `YOOKASSA_SECRET_KEY`
- `YOOKASSA_RETURN_URL`
- `YOOKASSA_API_BASE`
- `YOOKASSA_VAT_CODE`
- `YOOKASSA_TAX_SYSTEM_CODE`

Важно для Google credentials:

- `GOOGLE_SERVICE_ACCOUNT_JSON_B64` должен содержать base64 от полного JSON-файла service account
- это не `GOOGLE_SHEET_ID`, не числовой `project_id` и не отдельный ключ
- удобно сгенерировать так: `base64 < google-service-account.json | tr -d '\n'`

## 4. Создай сервис `webhook`

Настройки:

- Start Command: `./scripts/start_webhook_railway.sh`
- Healthcheck Path: `/health`

Переменные нужны те же, что и для `bot`.

После создания включи публичный домен Railway для `webhook`.

## 5. Настрой webhook в ЮKassa

В кабинете `ЮKassa` укажи webhook URL:

```text
https://<your-webhook-domain>/webhooks/yookassa
```

Рекомендуемые события:

- `payment.succeeded`
- `payment.canceled`

## 6. Проверка

- `bot` должен стартовать без ошибок миграции
- `webhook` должен отвечать `200 OK` на `/health`
- после тестовой оплаты заказ должен сменить статус в БД и в Google Sheets
