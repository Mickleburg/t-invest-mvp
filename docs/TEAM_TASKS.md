# Независимые задания четырём разработчикам

Имена/ревьюеры назначает команда. Контракты provisional, утверждение людьми не объявлено. Ветки/worktree отдельные; дополнительные coding-агенты автоматически не запускаются.

| Владелец / ветка | Файлы и задача | Зависимость | Приёмка |
| --- | --- | --- | --- |
| 1 / work/frontend | frontend/src: данные/риск, неполный TradePlan, ошибки, версии и уведомления | OpenAPI/examples; planned API только в явном mock режиме | unknown видны; fixtures подписаны; чат/история/мобильная ширина и npm check |
| 2 / work/agent | agent/, llm/: этапы AGENT.md, draft, сравнение провайдеров | Frozen Reply/API; источники от 4; цены/ключи | Golden cases, без LLM-арифметики, лимиты/ошибки; live smoke отдельно |
| 3 / work/backend | api/risk/plans/monitoring/storage: версии, CAS/hash/confirmation, immutable snapshot, затем worker | CP2; snapshot/spec от 4; draft от 2 | 409 stale version, 422 unsafe/missing, идемпотентность/rollback; worker только confirmed; restart/дедупликация/источник/время |
| 4 / work/integration | integrations/scripts/infra/Dockerfiles: MCP/DTO/свежесть/spec, VPS/HTTPS, live traces | Sandbox доступ, публичный ключ, VPS/domain; review 1–3 | Live read-only trace, единицы/инструмент, stale/failure, Docker build/run/restore, VPS egress, CP5 |

Общие interfaces.py, main.py, requirements*, contracts/, docs — последовательные изменения через интегратора и затронутых владельцев. Новый API-provider передаётся владельцу 2 после ревью; infra — владельцу 4. Схемы не регенерировать ради зелёного теста.

Порядок: CP1/CP2 review → snapshot/spec + provider → draft/риск → confirmation → worker + UI → live trace → VPS. Перед передачей backend/tests, check_contracts, frontend check; сетевые/платные проверки отдельно. По поручению пользователя агент делает содержательные коммиты с author/committer пользователя после проверок; push требует отдельного поручения.
