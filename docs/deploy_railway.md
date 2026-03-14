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
- Replicas: `1`

Переменные:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_IDS`
- `SUPPORT_URL`
- `PUBLIC_OFFER_URL`
- `DATABASE_URL`
- `GOOGLE_SHEET_ID`
- `GOOGLE_INVENTORY_WORKSHEET`
- `GOOGLE_SALES_WORKSHEET`
- `GOOGLE_ORDERS_WORKSHEET`
- `GOOGLE_SERVICE_ACCOUNT_JSON_B64` или `GOOGLE_SERVICE_ACCOUNT_JSON`
- `CHATGPT_STOCK_RESERVE_MINUTES`
- `YOOKASSA_SHOP_ID`
- `YOOKASSA_SECRET_KEY`
- `YOOKASSA_RETURN_URL`

Важно для ссылок:

- `SUPPORT_URL` должен быть полным `https://...` URL или `@username`
- `PUBLIC_OFFER_URL` должен быть полным `https://...` URL

Важно для Google credentials:

- `GOOGLE_SERVICE_ACCOUNT_JSON_B64` должен содержать base64 от полного JSON-файла service account
- это не `GOOGLE_SHEET_ID`, не числовой `project_id` и не отдельный ключ
- удобно сгенерировать так: `base64 < google-service-account.json | tr -d '\n'`
- в Google Cloud project этого service account должен быть включен `Google Sheets API`
- саму таблицу нужно расшарить на service account email минимум с правами `Editor`
- бот автосоздает и обновляет листы `inventory` и `sales`, если у service account есть доступ к таблице

Важно для GPT-стока:

- лист `inventory` в Google Sheets является основным складом GPT-аккаунтов
- свободные строки должны иметь `status=available`
- для выдачи обязательны `product_key`, `access_login`, `access_secret`
- `note` отправляется пользователю вместе с логином и паролем после успешной оплаты
- резерв GPT-аккаунта держится `20 минут` с момента выдачи ссылки на оплату
- для `Gemini` автовыдача не используется, после оплаты бот сообщает срок `1–24 часа`

## 4. Создай сервис `webhook`

Настройки:

- Start Command: `./scripts/start_webhook_railway.sh`
- Healthcheck Path: `/health`

Важно:

- у `webhook` обязательно должен быть свой `Start Command`
- если оставить сервис без него, Railway возьмет `Dockerfile CMD` и может поднять второй polling-бот вместо webhook

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
- у `bot` должен быть только один активный инстанс, иначе будет `TelegramConflictError`
- `webhook` должен отвечать `200 OK` на `/health`
- после тестовой оплаты заказ должен сменить статус в БД и в Google Sheets
