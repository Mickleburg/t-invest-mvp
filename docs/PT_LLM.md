# PT LLM: подключение и smoke

Исправления точечные: TLS остаётся проверяемым; PT-клиент обходит proxy при совпадении NO_PROXY, включая корпоративную форму `*.ptsecurity.com`; запрос Reply использует проверенный JSON object mode. OpenAI SDK, LLMProvider и схема Reply сохранены. Ретраев и автоматического переключения моделей нет.

## Проверенные результаты из backend

22 ноября 2026, Python из backend/.venv. Корпоративные root/issuing CA найдены среди доверенных сертификатов `ssl.create_default_context()`, прямой HTTPS прошёл без отключения проверки. Ключ прочитан из Windows User LLM_API_KEY в память процесса; значение не выводилось. Event hook подтвердил совпадение Bearer-заголовка с ключом и отсутствие `pt/` у модели.

| Проверка | HTTP | Исключение | Время, с | Результат |
| --- | --- | --- | --- | --- |
| GET /v1/models через унаследованный proxy | нет | ReadTimeout → ReadTimeout | 10.175 | NO_PROXY wildcard не применялся HTTPX |
| Тот же GET напрямую с TLS verify | 200 | нет | 0.493 | Endpoint доступен, CA доверен |
| POST /v1/chat/completions, deepseek, 128 output tokens | 200 | нет | 1.754 | chat.completion, одна choice, assistant content=str, два символа, OK, finish_reason=stop, usage есть |
| Reply без JSON object mode | 200 | нет на HTTP; Pydantic json_invalid | 4.865 / 4.268 | Обычный текст вместо JSON; успешный HTTP не означал валидный Reply |
| Reply с response_format=json_object | 200 | нет | 4.362 | Одна choice, content=str (1220 символов), finish_reason=stop, Reply valid; tool calls/reasoning отсутствуют |

Непосредственно перед разбором причины дополнительный запрос подтвердил обычный текст в content (JSONDecodeError в строке 1, столбце 1), без Markdown fence. Схема не ослаблялась и текст не извлекался эвристиками. После проверки JSON object mode включён только для PT; публичный DeepSeek не менялся. Запрос к qwen35-122b-a10b не потребовался: deepseek работает. Проверка не является оценкой качества всех моделей и торговых сценариев.

## Воспроизведение

Из корня, новый PowerShell после настройки пользовательских переменных:

```powershell
$env:LLM_PROVIDER='pt'
$env:LLM_BASE_URL='https://api-llm.ptsecurity.com/v1'
$env:LLM_MODEL='deepseek'
$env:NO_PROXY=($env:NO_PROXY + ',.ptsecurity.com').Trim(',')
backend/.venv/Scripts/python -m backend.scripts.smoke_pt_llm
backend/.venv/Scripts/python -m backend.scripts.smoke_pt_llm --reply --json-mode
```

Если текущий процесс не унаследовал сохранённый Windows User ключ, добавить `--windows-user-key`. Это явное чтение только в память, без записи env/файлов. Backend автоматически registry не читает: ему нужен LLM_API_KEY в собственном окружении. Каждая команда выполняет один потенциально платный запрос, без retries; minimal ограничен 128 output tokens, Reply — LLM_MAX_OUTPUT_TOKENS (2048 по умолчанию). Успех — exit 0; ошибка HTTP/transport/schema — exit 1. Диагностика содержит status, типы исключений, время, форму ответа, но не ключ, response body или reasoning.

Рабочий runtime сохраняет существующую проверку ценовых потолков/бюджета. Для ChatAPIProvider нужны согласованные LLM_INPUT_USD_PER_MILLION и LLM_OUTPUT_USD_PER_MILLION; ноль блокирует запросы ещё до сети, кроме явно подтверждённого бесплатного PT-тарифа с LLM_ZERO_COST_CONFIRMED=1. Smoke проверяет связь отдельно от этого бюджета, цены не выдумывает.

## CA и proxy

Клиент объединяет публичные корни certifi, системное доверие (включая Windows) и явный SSL_CERT_FILE. Проверка chain/hostname включена. Неверный/несуществующий CA-файл приводит к ошибке, а не к отключению TLS. REQUESTS_CA_BUNDLE и NODE_EXTRA_CA_CERTS не являются настройками этого Python-клиента.

Windows: если CA уже установлен корпоративным администратором, дополнительных действий нет. Для явной настройки получить проверенный PEM bundle root/issuing CA и задать `$env:SSL_CERT_FILE='C:\certs\pt-ca-chain.pem'` перед запуском. В bundle не должно быть private key. Не переносить Windows DPAPI или секреты в образ.

Docker в разрешённой корпоративной среде: смонтировать PEM bundle read-only, например `/run/certs/pt-ca-chain.pem`, передать `SSL_CERT_FILE=/run/certs/pt-ca-chain.pem` и `NO_PROXY=.ptsecurity.com` в backend. Пример Compose override:

```yaml
services:
  backend:
    volumes:
      - /srv/tradeguard/certs/pt-ca-chain.pem:/run/certs/pt-ca-chain.pem:ro
    environment:
      SSL_CERT_FILE: /run/certs/pt-ca-chain.pem
      NO_PROXY: .ptsecurity.com
```

Не добавлять CA в репозиторий/образ без необходимости. Скрипт smoke запускать внутри контейнера, чтобы проверить именно его сеть/доверие.

Linux/внутренний VPS: тот же PEM и `export SSL_CERT_FILE=/etc/tradeguard/pt-ca-chain.pem`, `export NO_PROXY=.ptsecurity.com`. Файл должен читаться пользователем backend; сеть обязана маршрутизировать внутренний адрес API. Windows trust store в Linux не существует. На стороннем публичном VPS корпоративные ключи/внутренние сервисы не разворачивать; существующий VPS overlay использует отдельный публичный DeepSeek.

NO_PROXY обход применяется только для совпавшего PT host; при отсутствии совпадения сохраняется стандартное поведение HTTPX и env proxy. Не отключать proxy глобально. В данном окружении API разрешается во внутренний адрес, а timeout возникал именно на proxy route.

MCP — отдельный transport/endpoint. Его ранее наблюдавшийся ReadTimeout не доказывает ошибку PT, не устраняется этим патчем и не смешивается с PT результатами. Повторный MCP вызов для этого исправления не выполнялся. Docker/VPS здесь не запускались: инструкции не выдаются за deployment-проверку.

В следующем сквозном прогоне пользователь подтвердил тариф PT 0; поддержка и результат живого MCP описаны в [MCP_SLICE.md](MCP_SLICE.md). Утверждение выше об отсутствии повторного MCP вызова относится только к этапу исправления PT.
