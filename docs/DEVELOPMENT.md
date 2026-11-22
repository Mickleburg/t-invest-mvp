# Запуск, интеграции и восстановление

Команды из корня. Python 3.11+, Node 20+. Windows: backend/.venv/Scripts/python; Linux: backend/.venv/bin/python. Git уже существует; по поручению пользователя агент делает содержательные коммиты после значимых проверенных изменений с авторством пользователя. Push требует отдельного поручения. Отдельные ветки/worktree — OWNERSHIP.md.

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
$env:LLM_PROVIDER='disabled'
backend/.venv/Scripts/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8003
# Другой терминал:
npm --prefix frontend run dev
```

UI http://127.0.0.1:5173, health http://127.0.0.1:8003/api/health. API_UPSTREAM/PORT/HOST настраивают frontend. TRADEGUARD_DATA переопределяет backend/runtime/. Один backend процесс: startup recovery и session locks не рассчитаны на несколько процессов. disabled честно возвращает ошибку модели. local_codex сохраняет прежний вариант разработки, требует установленного/авторизованного CLI; VPS его не использует.

## API-provider

```powershell
$env:LLM_PROVIDER='pt'
$env:LLM_BASE_URL='https://api-llm.ptsecurity.com/v1'
$env:LLM_MODEL='deepseek'
# Для публичного сервиса в ОТДЕЛЬНОМ окружении:
# LLM_PROVIDER=deepseek
# LLM_BASE_URL=https://api.deepseek.com
# LLM_MODEL=deepseek-flash
```

LLM_API_KEY принадлежит выбранному провайдеру. Не переиспользовать PT ключ для DeepSeek. В текущем Windows User env найден ключ PT; процесс Codex изначально его не наследовал. Для локального запуска после настройки env открыть новый терминал. Python .env автоматически не читает.

Если отдельного публичного ключа ещё нет, получить его у DeepSeek и в новом PowerShell задать скрытым вводом только для процесса:

```powershell
$llmCredential = Read-Host 'Public DeepSeek API key' -AsSecureString
$env:LLM_API_KEY = [System.Net.NetworkCredential]::new('', $llmCredential).Password
Remove-Variable llmCredential
# Запустить backend из этого же терминала с LLM_PROVIDER=deepseek.
```

Не вводить ключ в чат, литерал shell-команды или Git. Для постоянного Windows User env можно сохранить через системный редактор переменных среды; это не зашифрованный vault. На VPS использовать только отдельный публичный ключ в защищённом серверном env/secret manager, без корпоративных секретов.

Параметры: LLM_TIMEOUT_SECONDS=45, LLM_MAX_OUTPUT_TOKENS=2048, LLM_MAX_INPUT_BYTES=60000, LLM_MAX_CALLS=30, LLM_MAX_RESERVED_TOKENS=200000, LLM_MAX_COST_USD=1. Указать проверенные верхние цены LLM_INPUT_USD_PER_MILLION и LLM_OUTPUT_USD_PER_MILLION; ноль блокирует запросы без явного подтверждения бесплатного PT-тарифа (LLM_ZERO_COST_CONFIRMED=1). Цены намеренно не придуманы. Пользователь подтвердил нулевой тариф PT: для него допустим LLM_ZERO_COST_CONFIRMED=1 при обеих ценах 0. Для публичного провайдера это исключение не действует.

Резерв: байты UTF-8 входа + 1024 на envelope как оценка токенов, плюс max output; стоимость Decimal по заданным потолкам. Это консервативная оценка, не доказательство токенизации или точного счёта провайдера. Счётчик общий для экземпляра provider, учитывает неудачные запросы, сбрасывается при рестарте. Нет постоянного/суточного/межпроцессного биллинга: для общего денежного потолка нужны лимиты аккаунта и будущий durable ledger. SDK retries/redirects отключены. Одна реплика backend обязательна.

Для PT после live проверки включён response_format=json_object; Reply дополнительно проверяется локально Pydantic. Native JSON schema mode/tool calling не включены. Шаги инструментов выполняет существующий диспетчер. Текущий кандидат deepseek-flash указан в [официальной Chat Completions документации](https://api-docs.deepseek.com/api/create-chat-completion/); выбор по качеству и live совместимость ещё не подтверждены.

## MCP и Research

Sandbox токен вне проекта: Windows DPAPI либо TINVEST_SANDBOX_TOKEN. Скрытый ввод: `backend/.venv/Scripts/python -m backend.app.integrations.credentials`. Linux/VPS использует env: DPAPI Windows туда не переносится. Доступ только к sandbox MCP allowlist, без счетов/заявок/переводов. Research требует `backend/.venv/Scripts/python -m playwright install chromium`; браузер в Docker пока не установлен. Недоступность/блокировка страницы не подтверждают событие.

## Offline и network проверки

```powershell
backend/.venv/Scripts/python -m pytest -c backend/pytest.ini backend/tests -q -p no:cacheprovider
backend/.venv/Scripts/python -m backend.scripts.check_contracts
npm --prefix frontend run check
docker compose -f infra/compose.yaml config --quiet
docker compose -f infra/compose.yaml -f infra/compose.vps.yaml config --quiet
```

После согласованного изменения DTO — export_contracts и ревью diff. Не регенерировать frozen схему автоматически.

Отдельно, только с сетью: `python -m backend.scripts.probe_integrations --mcp`. Только при настроенном соответствующем ключе: `python -m backend.scripts.probe_integrations --llm` — одна потенциально платная попытка, max 2048 output tokens, без retries, без ограничения денежного счёта. Это smoke совместимости Reply, не runtime budget и не качество торгового анализа. Не включать в offline CI. Диагностика выводит только статусы. Native JSON/tools эта проверка не доказывает.

## Docker / VPS

```powershell
Copy-Item infra/.env.example infra/.env
# Заполнить env локальным редактором, не выводя секреты.
docker compose --env-file infra/.env -f infra/compose.yaml up --build -d
```

По умолчанию LLM disabled; loopback порты, volume mvp-data, backend healthcheck. Не выполнять `docker compose config` без --quiet с заполненными секретами: он разворачивает значения. Не публиковать inspect/env/logs с ключами. Docker Engine при текущей проверке недоступен; build/run не доказаны.

VPS overlay: `docker compose --env-file infra/.env -f infra/compose.yaml -f infra/compose.vps.yaml up --build -d`. Указать TRADEGUARD_DOMAIN с DNS на VPS, AUTH_USER и AUTH_PASSWORD_HASH (Caddy hash-password через скрытый интерактивный ввод), отдельный DEEPSEEK_API_KEY, цены и sandbox токен. Хеш с `$` хранить в .env в одинарных кавычках. Защитить env правами владельца (Linux chmod 600). Порты 80/443 — proxy; backend/frontend остаются loopback. Caddy получает сертификат автоматически при доступных DNS/ACME/портах. Пустой hash не даёт готовую авторизацию: сначала validate Caddyfile. Basic auth — единый закрытый демо-доступ; разделения пользователей внутри API нет.

Overlay принудительно выбирает публичный DeepSeek и читает отдельный DEEPSEEK_API_KEY; корпоративный LLM_API_KEY не переносить на VPS. Исходящие зависимости: DeepSeek HTTPS, T-Invest sandbox MCP HTTPS/streamable HTTP, Research сайты и ACME. На VPS повторить диагностику, live сценарий, HTTPS/auth, restart/volume persistence и restore drill. Результат с ноутбука не заменяет VPS проверку.

Отдельный monitoring worker пока отсутствует: его можно подключать только после confirmed repository/версий и тестов snapshot, дедупликации, перезапуска. Не запускать фиктивный worker, проверяющий draft.

## Диагностика и восстановление

Health — процесс/конфигурация, не готовность LLM/MCP. Проверить точный provider/model, новый процесс с env, доступ к endpoint, лимиты и наличие цен. Временные provider ошибки не превращать в данные. Не логировать Authorization, error body, токены и reasoning.

Перед изменением схемы storage — согласованная миграция и серверный SQLite backup при остановленной записи. Резервные копии содержат пользовательские диалоги: только защищённое серверное хранилище, никогда Git/артефакты задачи. Восстановление: остановить backend, восстановить совместимый backup в тот же volume, проверить права, запустить одну реплику и проверить историю/health. В этой работе рабочие базы не копировались и restore не выполнялся. Для rollback образа сохранить volume и совместимость схемы; удаление volume с данными не является rollback.

PT: исправление proxy/CA, реальные результаты и отдельный smoke — [PT_LLM.md](PT_LLM.md). Windows использует системные CA; Docker/Linux — read-only PEM через SSL_CERT_FILE. MCP timeout диагностируется независимо.

Живой MCP и сценарий SiZ6: [MCP_SLICE.md](MCP_SLICE.md). TINVEST_MCP_USE_PROXY=0 задаёт прямой sandbox SSE transport; 1 использует env proxy. Проверяемый UI smoke запускается на отдельных портах с временной БД и реальными PT/MCP.
