# VPS Deploy

## Быстрый старт

1. Клонируй проект:

```bash
git clone <your_repo_url> saleacc
cd saleacc
```

2. Подготовь переменные:

```bash
cp .env.example .env
```

3. Подготовь Google credentials любым одним способом:

- положи файл в `keys/google-sa.json`
- или пропиши `GOOGLE_SERVICE_ACCOUNT_JSON`
- или пропиши `GOOGLE_SERVICE_ACCOUNT_JSON_B64`

4. Для автовыдачи `ChatGPT` настрой источник CSV-стока:

- пропиши `CHATGPT_STOCK_CSV_URL`
- или `CHATGPT_STOCK_CSV_PATH`

5. Первый деплой:

```bash
bash scripts/bootstrap_vps.sh
```

## Что поднимется

- `bot` - Telegram polling
- `webhook` - FastAPI на порту `8000` для `ЮKassa`

## Следующие деплои

```bash
git pull
bash scripts/deploy_docker.sh
```

## Полезные команды

```bash
docker compose ps
docker compose logs -f bot
docker compose logs -f webhook
docker compose restart bot
docker compose restart webhook
```

## Проверка

- healthcheck: `http://<server>:8000/health`
- webhook `ЮKassa`: `http://<server>:8000/webhooks/yookassa`
