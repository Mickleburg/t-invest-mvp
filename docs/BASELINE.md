# Проверенное исходное состояние

Аудит 22 ноября 2026. До изменений: чистая main, HEAD `5cf2510` (first commit). Работа в `work/integration-foundation`; коммитов, push, reset и Git init агент не выполнял. Прежние сведения об отсутствии Git устарели.

Структура: frontend/, backend/, contracts/, infra/, docs/. Старые приложения убраны ранее по прямому решению пользователя; не восстанавливаются. Runtime/.venv исключены из Git и Docker context. Рабочие БД не копировались.

## Работают и пригодны для переиспользования

- `backend.app.main:app`, api/routes.py, api/models.py: HTTP диалоги, история, health; frontend/src через Node proxy 5173 обращается к backend 8003.
- storage/repository.py: SQLite sessions/messages/turns/evidence; тесты истории, идемпотентности, восстановления.
- risk/engine.py, risk/grounding.py: Python/Decimal, цитаты параметров, валюты, lot/point value, нехватка спецификации. Риск не рассчитывается моделью.
- contracts/: OpenAPI 3.1, TradePlan JSON Schema 2020-12, явно учебные примеры; offline gate проверяет drift и planned.

## Работают, но требуют доработки

- agent/service.py: до трёх раундов модели и трёх read-only вызовов, валидация Reply/evidence_id. Семантическая истинность фактов не доказана; evidence местами сырой.
- llm/client.py, structured.py: сохранён локальный Codex/MCP; текущий доступ CLI не проверялся. Новый PT/DeepSeek адаптер проверен offline.
- integrations/tinvest.py, tools.py, market.py: allowlist, JSON Schema аргументов, частичная нормализация. Живой MCP initialize завершился ReadTimeout.
- Chromium Research существует, но свежий live прогон отсутствует; браузер в Docker не установлен.
- Docker/Compose, health, постоянный volume: конфигурация отдельно от сборки; Docker Engine недоступен.

## Экспериментальные и подлежащие замене

- Reply.plan — неверсионированная сводка, не подтверждённый TradePlan, позиция или заявка.
- Raw MCP/evidence агенту — заменить границами MarketDataProvider/ResearchProvider без второй реализации Risk Engine.
- Сброс processing при старте и asyncio locks — только для одного backend процесса, не координация нескольких.

## Отсутствующие

Версионированный PlanRepository, серверные инварианты подтверждения, immutable snapshot, CAS/hash/idempotency подтверждения, автоматический worker, доставка уведомлений, изоляция пользователей, проверенный VPS/публичный DeepSeek и live сквозной сценарий. Planned маршруты отвечают 404; схема не заменяет реализацию.

Исходные проверки: 26 passed, контракт без drift, frontend check passed. Исторические 182/192 теста старых приложений не относятся к текущему MVP. Новые результаты — STATUS.md.
