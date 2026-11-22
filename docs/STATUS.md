# Состояние на 22 ноября 2026

Ветка `work/integration-foundation`, исходный HEAD `5cf2510`, исходная main чистая. На этапе подготовки коммиты/push не выполнялись; новое поручение пользователя о коммитах записано в AGENTS.md. Существующая структура и публичные контракты сохранены; согласование контрактов командой не объявлено.

## Реализовано в этой ветке

- PT/DeepSeek через OpenAI SDK и прежний LLMProvider: конфигурация без изменения агента, allowlist HTTPS endpoints, timeout, без retries/redirects, валидация Reply, запрет неполных/пустых/невалидных ответов.
- Лимиты вызовов/входа/выхода и расчётный резерв токенов/USD с явными ценовыми потолками; параллельное резервирование и сохранение резерва после ошибки. Ограничения процесса описаны в DEVELOPMENT.
- Health отражает наличие ключа и цен для API-provider; это конфигурация, не live readiness. Артефакты больше не называют любую модель Codex.
- Отдельная opt-in сетевая диагностика; обновлены Compose/env, добавлен Caddy/HTTPS шаблон VPS с отдельным публичным ключом и basic auth.
- Актуализированы baseline/Git/срок, CP0–CP7, поведение агента, задачи четырёх владельцев, запуск и ограничения. Старый PREPARATION_REPORT — исторический документ.

## Проверки

Исходные: 26 offline тестов passed. Финальный прогон: **50 passed** (4.88 s), одно существующее предупреждение Starlette об устаревающем TestClient/httpx. Проверены в том числе 401/429/500/redirect, timeout, malformed/truncated Reply, недопустимый инструмент, отсутствие ключа/цен, лимиты, конкурентный резерв и HTTP → Service → SDK adapter → SQLite. Используется явный httpx MockTransport; это не реальные рыночные результаты.

OpenAPI/JSON Schema/examples: valid, drift отсутствует; planned routes не реализованы. Frontend check passed. Compose config базового и VPS overlay прошёл. pip check: no broken requirements. git diff --check passed. Docker Engine недоступен; build/run/HTTPS не проверены. Frontend/src не менялся; новый браузерный smoke не выполнялся.

## Отдельные сетевые результаты

- PT: первоначальный timeout воспроизведён на proxy route. После исправления NO_PROXY wildcard — models 200, минимальный deepseek Chat Completions 200 (1.754 s). Без JSON mode Reply отклонял обычный текст; с проверенным response_format=json_object — 200 и валидный Reply (4.362 s). Bearer и bare model ID проверены без вывода ключа. Детали и команды: PT_LLM.md.
- DeepSeek: GET /models без ключа вернул 401; endpoint достижим. Авторизованный вызов модели не выполнялся, публичного ключа в проверенных переменных нет.
- T-Invest sandbox MCP: токен в существующем внешнем хранилище есть; initialize/list_tools завершились ReadTimeout. Рыночные данные не получены, торговых вызовов нет.
- VPS не предоставлен; сетевую доступность с VPS проверить невозможно. Локальная доступность не доказывает доступ с VPS.

Пользователь уточнил, что найденный Windows User LLM_API_KEY относится к PT. Ключ не выводился, не записывался в проект и не отправлялся DeepSeek; использован только в процессе PT диагностики. Новый процесс обычно нужен для наследования сохранённых Windows env.

## Затронутые файлы

- Backend: app/llm/external.py (новый), app/llm/__init__.py, app/main.py, app/agent/service.py; scripts/probe_integrations.py (новый), tests/test_external_llm.py (новый); requirements.txt, requirements-lock.txt, AGENTS.md.
- Infra: compose.yaml, .env.example; compose.vps.yaml и Caddyfile (новые).
- Документы: BASELINE.md, ARCHITECTURE.md, OWNERSHIP.md, ROADMAP.md, DEVELOPMENT.md; AGENT.md, TEAM_TASKS.md, STATUS.md (новые); корневые README.md и AGENTS.md.
- Публичные contracts/, frontend/src, Risk Engine и рабочие базы не изменялись. OpenAPI/trade_plan schema и семь Protocol сохранены для командного ревью.

## Что остаётся и решения команды

Восстановить доступ MCP; получить отдельный публичный ключ и согласовать модель, ценовые потолки и бюджет; нормализовать источники/spec; реализовать TradePlan repository/confirmation/worker/уведомления; назначить ревьюеров и утвердить provisional контракты; предоставить VPS/domain и проверить сборку, HTTPS, доступы и восстановление. CP4–CP7 не закрыты. Следующий приоритет — доступ MCP и проверенная спецификация контракта для живого CP5.

## Точечное исправление PT

Исправлены только маршрутизация env proxy по корпоративному NO_PROXY wildcard, загрузка CA и формат PT Reply. Изменены llm/external.py, scripts/probe_integrations.py, tests/test_external_llm.py; добавлены scripts/smoke_pt_llm.py и docs/PT_LLM.md. Связанные инструкции актуализированы. TLS verify не отключался, MCP не менялся, архитектура/контракты/бюджеты не менялись.

После исправления: **59 passed** (15.88 s), одно прежнее предупреждение Starlette; check_contracts valid/no drift, frontend check passed. Proxy regression проверяет wildcard/exact/nonmatching hosts при обязательном CERT_REQUIRED/hostname verification; дополнительный CA загружается, отсутствующий файл вызывает ошибку; PT запрашивает bare model ID и JSON object mode. Новый GET probe: PT models 200, публичный DeepSeek 401 без ключа. Результаты live Chat Completions и команды воспроизведения — PT_LLM.md. На момент проверки PT коммитов/push не было; далее пользователь разрешил содержательные коммиты от его имени.

## Новое правило Git

Пользователь поручил после значимых проверенных изменений делать содержательные коммиты с его author/committer, без соавторства агента. GitHub SSH подтвердил аккаунт Mickleburg, текущая Git-идентичность соответствует исходному автору репозитория. Push отдельно не поручен. Предыдущие записи об отсутствии коммитов относятся к этапам до этого поручения.
