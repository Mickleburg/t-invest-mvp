# Владение и интеграция

| Участник | Каталоги | Задачи |
| --- | --- | --- |
| 1 Frontend | frontend/ | Чат, план, риск, статусы, уведомления; HTTP/OpenAPI |
| 2 AI Agent | backend/app/agent/, backend/app/llm/ | Диалог, промпт, LLMProvider, черновик плана |
| 3 Backend/Risk/Monitoring | backend/app/api/, risk/, plans/, monitoring/, storage/, main.py, config.py, common.py; backend/tests/ | API, риск, миграции, версии/подтверждение, worker/уведомления |
| 4 MCP/Research/Integration | backend/app/integrations/, backend/scripts/, infra/, Dockerfiles | Источники, нормализация, окружения, сквозная интеграция |

interfaces.py, contracts/, backend/requirements*, общие docs/AGENTS — интегратор 4 и затронутые владельцы. Контракт: предложение → согласование потребителей → версия/совместимость → примеры/тесты → merge. Не перегенерировать схему ради зелёного теста.

Тесты согласуются с владельцем соответствующего модуля. Общие main.py и зависимости объединяются последовательно. Реальные имена/ревьюеры назначаются командой.

## Git-workflow

Пока нет Git/HEAD; контрольный коммит делает пользователь. Затем четыре отдельные ветки/worktree: work/frontend, work/agent, work/backend, work/integration. Собственное окружение в каждом checkout, без копирования БД/секретов.

Небольшой PR: одна задача, затронутые контракты, тесты и ограничения. Перед merge: backend/tests, check_contracts, frontend check; интегрирует участник 4. Общие файлы — один согласованный PR. Не запускать дополнительных coding-агентов без явного задания и не работать четырьмя агентами в одном checkout.
