# Backend — разработчики 2, 3, 4

Соблюдать корневой AGENTS.md и docs/OWNERSHIP.md. Единственная точка входа — backend.app.main:app. API не раздаёт frontend. Реализации находятся в app/api, agent, llm, integrations, risk, storage; plans/contracts.py и monitoring/contracts.py содержат только интерфейсы будущего CP3.

Агент использует сменный LLMProvider. Локальный MCP/Codex — вариант разработки; pt/deepseek API-адаптер реализован; PT deepseek/Reply проверен live, публичный DeepSeek пока нет. CA/proxy: docs/PT_LLM.md. См. docs/DEVELOPMENT.md и docs/STATUS.md. Финансовые расчёты — risk/engine.py. Нормализация всего evidence пока не завершена: новый код должен двигаться к MarketDataProvider/ResearchProvider.

Подтверждение CP3 потребует версии, хеша, транзакции, идемпотентности и неизменяемого снимка. Worker читает подтверждённую версию. Сбой источника не равен выполнению условия; сохранение уведомления не равно доставке. Не реализовывать эти этапы в рамках очистки.

Из корня: `backend/.venv/Scripts/python -m pytest -c backend/pytest.ini backend/tests -q`, `backend/.venv/Scripts/python -m backend.scripts.check_contracts`. Контракт экспортировать через backend.scripts.export_contracts только после согласования. Healthcheck не доказывает готовность LLM/MCP. Runtime/БД не коммитить.
