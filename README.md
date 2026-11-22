# TradeGuard

AI-помощник для разбора торговой идеи и программного расчёта риска. Один FastAPI backend и отдельный frontend. Реальных торговых операций нет.

```text
frontend/   интерфейс чата и HTTP proxy
backend/    API, агент, LLM, MCP/Research, риск, хранение, тесты
contracts/  OpenAPI, схема плана и учебные примеры
infra/      Compose и пример окружения
docs/       продукт, архитектура, ответственность, этапы и запуск
```

## Локальный запуск

Из корня проекта, Python 3.11+, Node 20+:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
$env:LLM_PROVIDER='local_codex'
backend/.venv/Scripts/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8003
# В другом терминале:
npm --prefix frontend run dev
```

Интерфейс: http://127.0.0.1:5173. Локальный LLM требует установленного и авторизованного Codex CLI. `LLM_PROVIDER=disabled` запускает API без модели; недоступность указывается явно. Данные — backend/runtime/, секреты — вне проекта.

```powershell
backend/.venv/Scripts/python -m pytest -c backend/pytest.ini backend/tests -q -p no:cacheprovider
backend/.venv/Scripts/python -m backend.scripts.check_contracts
npm --prefix frontend run check
docker compose -f infra/compose.yaml config --quiet
```

Linux: backend/.venv/bin/python и export LLM_PROVIDER=local_codex.

Работают диалог, ограниченные read-only инструменты, история SQLite и расчёт риска. Версионированное подтверждение планов и мониторинг запланированы. PT/DeepSeek API-адаптер реализован; PT deepseek/Reply проверен live. [PT: CA, proxy и smoke](docs/PT_LLM.md). Публичный DeepSeek не проверен. [Запуск](docs/DEVELOPMENT.md), [архитектура](docs/ARCHITECTURE.md), [результаты подготовки](docs/PREPARATION_REPORT.md), [этапы](docs/ROADMAP.md).

Актуальные результаты: [STATUS](docs/STATUS.md), [задания команды](docs/TEAM_TASKS.md), [поведение агента](docs/AGENT.md). Цель MVP — до 1 декабря 2026; Demo Day — 5 декабря.
