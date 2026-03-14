# J.A.R.V.I.S

PC + 모바일 활동을 크롤링하여 맞춤형 브리핑을 제공하는 AI 비서.

## Quick Start

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows
pip install -e ".[dev]"

cp .env.example .env
python -m server.main
```

- Health check: `GET /health`
- Root: `GET /?locale=ko`

## Structure

```
server/       — FastAPI backend
pc-client/    — Windows activity tracker
shared/       — Constants & types
locale/       — i18n (ko, en)
mobile/       — Mobile companion (future)
```
