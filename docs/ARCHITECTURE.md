# Архитектура TradeGuard

## Реализовано

frontend/src → HTTP /api/ через Node proxy → backend/app/main.py → api/routes.py → agent/service.py. Backend на 8003 обслуживает API, frontend на 5173 — интерфейс. Старые приложения 8000–8002 выведены из проекта по прямому требованию пользователя завершить переход к единственной структуре.

| Модуль backend/app | Содержание |
| --- | --- |
| api/ | Маршруты диалогов, wire DTO, health |
| agent/ | Контекст, ограниченные раунды инструментов, промпт, модели ответа, LLM MCP server |
| llm/ | LLMProvider binding, MCP client, structured Codex invocation |
| integrations/ | T-Invest MCP transport, read-only диспетчер, поиск бумаг, Decimal-значения, Chromium research и MCP bridge |
| risk/ | Программный расчёт, проверка чисел и единиц по исходным цитатам |
| storage/ | SQLite sessions/messages/turns/evidence |
| plans/, monitoring/ | Контракты будущих реализаций CP3 |

Это перенос использовавшегося кода без второй реализации агента или Risk Engine. Из старого карточного PoC взяты только нужные функции идентификации бумаг и чтения Decimal.

Композиция внедряет LLMProvider.complete в Service. local_codex использует локальный MCP → Codex CLI; disabled и зарезервированный external_api возвращают недоступность. pt/deepseek используют OpenAI SDK через llm/external.py: HTTPS, тайм-аут, без SDK retries/native tools, локальная валидация Reply и лимиты. PT deepseek проверен live с JSON object mode; публичный DeepSeek не проверен. TLS/NO_PROXY — docs/PT_LLM.md. Инструкции диалога остались tradeguard-dialogue-v2.

Данные — backend/runtime/ либо TRADEGUARD_DATA. Runtime нового MVP перемещён без изменения схемы и копирования БД. Старые базы не объединялись. Пока допустим один процесс backend: startup сбрасывает прерванные ходы.

## Границы и долги

LLMProvider реально внедрён. Остальные Protocol/DTO в interfaces.py задают командные границы. Service пока вызывает tools/risk напрямую, evidence местами содержит сырой MCP. Полная нормализация — CP1, не результат переноса файлов.

Текущий Reply.plan — предварительная сводка, а не версионированный TradePlan. JSON Schema и planned OpenAPI описывают будущую модель; плановые маршруты не обслуживаются и возвращают 404.

## Подтверждение и мониторинг: проект CP3

Подтверждение сравнивает version/hash, проверяет источники/свежесть/расчёт и транзакционно сохраняет неизменяемый снимок. Несовпадение версии → 409; недостаток данных → 422. Сервер проверяет финансовые инварианты, принадлежность источников инструменту и равенство confirmation.version — JSON Schema этого не доказывает.

Worker читает confirmed snapshot, сохраняет версию, данные, источник и время проверки, дедуплицирует уведомления. Ошибка или устаревшие данные → insufficient_data. Состояния stored/delivered/failed различаются. Реализации workflow пока нет. Торговых заявок нет.

ProviderUnavailable означает недоступность провайдера, ContractViolation — нарушение контракта. Пользовательская ошибка не содержит токенов/заголовков/сырого текста сервера. Health проверяет процесс и конфигурацию без внешних вызовов. Подмены живых данных моками нет.

## Дополнение аудита 22 ноября

API-provider внедряется через прежний LLMProvider.complete; агент не меняется при смене pt/deepseek. Цены задаются явно; нулевые цены блокируют запросы, кроме явно подтверждённого бесплатного PT-тарифа. Бюджет резервируется на процесс и сбрасывается при рестарте; это не общий биллинг. Подробные ограничения — DEVELOPMENT.md. Caddy/VPS overlay — шаблон, не состоявшийся deployment. Worker не создавался: без confirmed repository он не мог бы проверять подтверждённые условия. Нумерация CP заменена в ROADMAP.md; старые CP3 в этом тексте означают будущий workflow CP6.

Живой локальный путь frontend → PT → sandbox MCP → Decimal → UI проверен для SiZ6; транспорт MCP использует явную настройку proxy. Чтение валюты стоимости шага исправлено для Quotation; цены фьючерса проверяются в пунктах и по шагу. Протокол и ограничения — MCP_SLICE.md.
