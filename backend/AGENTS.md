# Backend — разработчики 2, 3, 4

Соблюдать корневой AGENTS.md и docs/OWNERSHIP.md. Единственная точка входа — backend.app.main:app. API не раздаёт frontend. CP6 реализован в plans/repository.py, risk/plan.py, monitoring/service.py и существующем Store; interfaces/Protocol сохраняют границы. Новые коммиты и их описания — на русском, author/committer пользователя.

Агент использует сменный LLMProvider. Локальный MCP/Codex — вариант разработки; pt/deepseek API-адаптер реализован; PT deepseek/Reply проверен live, публичный DeepSeek пока нет. CA/proxy: docs/PT_LLM.md. См. docs/DEVELOPMENT.md и docs/STATUS.md. Финансовые расчёты — risk/engine.py. Нормализация всего evidence пока не завершена: новый код должен двигаться к MarketDataProvider/ResearchProvider.

Подтверждение CP6 проверяет версию/хеш/риск/источники и атомарно сохраняет immutable snapshot. Worker читает только snapshot; ошибка/старые данные — insufficient_data. Не обходить CAS, immutable SQL triggers и source provenance. Сохранённое уведомление — stored; delivered появляется после подтверждения показа браузером. Сеть отдельно от offline тестов. CP6_EVALUATION.md описывает проверенное поведение и ограничения.

Из корня: `backend/.venv/Scripts/python -m pytest -c backend/pytest.ini backend/tests -q`, `backend/.venv/Scripts/python -m backend.scripts.check_contracts`. Контракт экспортировать через backend.scripts.export_contracts только после согласования. Healthcheck не доказывает готовность LLM/MCP. Runtime/БД не коммитить.
