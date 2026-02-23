# VPS Deploy (One Command, Docker)

## Quick start

1. Clone project on VPS:

```bash
git clone <your_repo_url> saleacc
cd saleacc
```

2. Prepare env and key:

```bash
cp .env.example .env
# fill .env values
mkdir -p keys
# put service account file as: keys/google-sa.json
```

3. First deploy (installs Docker on Debian/Ubuntu if needed):

```bash
bash scripts/bootstrap_vps.sh
```

That is it. Bot is built and started via Docker Compose.

## Next deploys (update to latest code)

```bash
git pull
bash scripts/deploy_docker.sh
```

This command:
- rebuilds image
- runs `init_google_sheet.py`
- recreates bot container (single latest container only)

## Optional: webhook service

If you also need webhook API (`/webhooks/tribute`, `/webhooks/cryptobot`):

```bash
ENABLE_WEBHOOK=1 bash scripts/deploy_docker.sh
```

`webhook` service will run on port `8000`.

## Useful commands

```bash
docker compose ps
docker compose logs -f bot
docker compose logs -f webhook
docker compose restart bot
```
