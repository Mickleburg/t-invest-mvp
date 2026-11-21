# Разработка и запуск

Команды из корня. Python 3.11+, Node 20+. Windows: backend/.venv/Scripts/python; Linux: backend/.venv/bin/python.

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
$env:LLM_PROVIDER='local_codex'
backend/.venv/Scripts/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8003
# Другой терминал:
npm --prefix frontend run dev
```

Открыть http://127.0.0.1:5173. API: http://127.0.0.1:8003/api/health. API_UPSTREAM/PORT/HOST настраивают frontend. TRADEGUARD_DATA переопределяет backend/runtime/. Не запускать несколько worker по одной SQLite до переработки восстановления ходов и конкурентности.

Codex CLI должен быть установлен и авторизован на хосте. LLM_PROVIDER=disabled запускает API без модели; ошибки честные, ответов-заглушек нет. external_api и LLM_API_* зарезервированы, адаптер ещё не реализован. В Linux: export LLM_PROVIDER=local_codex.

Токен sandbox MCP хранится вне проекта: на Windows DPAPI либо TINVEST_SANDBOX_TOKEN. Скрытый ввод: `backend/.venv/Scripts/python -m backend.app.integrations.credentials`. Не вставлять токен в команду или документы. Существующее внешнее DPAPI-хранилище переименовывать не требуется. Счетов и торговых вызовов нет.

Веб-исследование: `backend/.venv/Scripts/python -m playwright install chromium`. Chromium работает без авторизации. Страница не подтверждает событие автоматически; блокировки и недоступность сохраняются явно.

## Проверки

```powershell
backend/.venv/Scripts/python -m pytest -c backend/pytest.ini backend/tests -q -p no:cacheprovider
backend/.venv/Scripts/python -m backend.scripts.check_contracts
npm --prefix frontend run check
docker compose -f infra/compose.yaml config --quiet
```

Тесты используют явные doubles и временные каталоги, без финансовых сервисов/LLM. После согласованного изменения DTO: `backend/.venv/Scripts/python -m backend.scripts.export_contracts`, ревью diff и проверки. Перенос модулей не изменил HTTP-контракт.

## Docker

```powershell
Copy-Item infra/.env.example infra/.env
# Заполнить значения локально; Python автоматически .env не читает.
docker compose --env-file infra/.env -f infra/compose.yaml up --build
```

Backend, frontend, named volume mvp-data; порты на loopback. Runtime/venv/секреты исключены из образа. По умолчанию LLM отключена, Codex login и Chromium в образ не устанавливаются. Это заготовка для CP1/CP5. Docker Engine при подготовке был недоступен: сборка/запуск контейнеров не подтверждены.

## Git

В каталоге нет Git/HEAD. Пользователь выбирает remote или выполняет git init и контрольный коммит. Перед коммитом проверить staged diff и исключения runtime/секретов. Коммиты агент не выполняет. Далее — отдельные ветки/worktree по OWNERSHIP.md.
