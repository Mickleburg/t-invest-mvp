# Контракты v0.1

Статус provisional: технически зафиксированы, требуется ревью команды. Изменения согласуют интегратор 4 и потребители; агент не объявляет утверждение людьми состоявшимся.

openapi.yaml — OpenAPI 3.1. Реальные операции генерируются из приложения и помечены x-implementation-status: implemented. Плановые методы — planned, в runtime отсутствуют и отвечают 404. Их 200/409/422/503 — будущее поведение. История сейчас доступна в SessionState.messages. Текущий Reply.plan не равен новой сущности TradePlan.

trade_plan.schema.json — JSON Schema 2020-12, Decimal в строках, неполный draft допустим. Confirmed требует условия/параметры/расчёт/источники; фьючерс — стоимость пункта/валюту/лот/ссылку на спецификацию. Неучебный confirmed запрещает synthetic/stale/unknown источники. Схема не доказывает арифметику или истинность источника.

Сервер CP3 обязан проверить version/confirmation.version, hash, принадлежность спецификации/правил инструменту, стоп/лотность/валюты/лимиты, свежесть и происхождение. Подтверждение атомарно, идемпотентно и не совершает заявку. Подтверждённые версии неизменяемы; изменения draft — через expected_version. Эти операции ещё не реализованы.

examples/ — явно учебные моки. Пример confirmed не доказывает работу workflow. Внутренние интерфейсы: backend/app/interfaces.py и plans/monitoring/contracts.py. Нормализация всего evidence — CP1.

Из корня: `backend/.venv/Scripts/python -m backend.scripts.check_contracts`. Экспорт после согласования: `backend/.venv/Scripts/python -m backend.scripts.export_contracts`.
