# Uranus-AI

Uranus-AI — открытая self-hosted агентская рабочая среда. Она принимает задачу, строит план, вызывает инструменты, показывает tool trace и требует подтверждения опасных действий. Проект вдохновлён наблюдаемыми рабочими сценариями Manus, но реализован независимо и не использует закрытые API Manus.

## Что уже работает

В репозитории есть Docker Compose-стек с четырьмя контейнерами: FastAPI API, изолированный sandbox, Playwright browser worker и React/Vite web-панель. Пользователь может выбрать модель, включить OpenRouter/Groq/OpenCode Zen/Gemini/Ollama/Qwen/Claude или совместимый endpoint, загрузить список моделей, протестировать провайдера, вести историю запусков и менять настройки из панели.

Агентский цикл поддерживает планы, SSE-стриминг текста, native tool calling для OpenAI-compatible API, Anthropic tool blocks, Ollama chat API, JSON-совместимые результаты инструментов, approvals, остановку запуска и лимит шагов. Workspace-инструменты ограничены смонтированной папкой. Terminal выполняется от non-root пользователя внутри sandbox-контейнера с таймаутом и лимитом вывода. Browser worker использует отдельный persistent Playwright-профиль и не получает cookies host-браузера.

## Быстрый запуск

```bash
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
# вставь результат в INTERNAL_SERVICE_TOKEN в .env

docker compose up --build
```

После запуска открой [http://localhost:5173](http://localhost:5173). Админка находится в разделе «Настройки». Для первого запуска local-first режим допускает дефолтный `ADMIN_TOKEN=change-me`; перед публикацией задай собственное значение и добавь reverse proxy/TLS. На Linux при нестандартном UID/GID владельца проекта замени `URANUS_UID` и `URANUS_GID` в `.env` значениями `id -u` и `id -g`.

Все данные сохраняются в `./data`, код, который агент меняет, — в `./workspace`, а профиль изолированного браузера — в `./data/browser-profile`. Эти каталоги добавлены в `.gitignore`.

## Настройка моделей

В админке открой карточку провайдера, задай ключ и при необходимости Base URL, нажми «Сохранить», затем «Модели». В чате модель имеет вид `provider:model`. OpenRouter, Groq, Gemini и Qwen используют OpenAI-compatible API. OpenCode Zen добавлен с публичным ключом по умолчанию, если endpoint сохраняет такую модель доступа. Ollama по умолчанию ожидается на `host.docker.internal:11434`; на Linux compose добавляет host-gateway. Claude имеет отдельный Anthropic Messages адаптер, а Claude через OpenRouter работает как обычный OpenAI-compatible provider.

Uranus-AI не делает скрытый fallback на другую модель и не знает, платная модель или бесплатная. Перед тестированием выбери модель с нулевой стоимостью или локальную Ollama-модель и проверь, что в админке указан именно этот ID. В проекте не зашиты пользовательские ключи.

## Безопасность

Режим `approval_mode=ask` включён по умолчанию. Запись/удаление файлов, terminal, project test, browser click/type/press/screenshot и публикация артефакта создают approval, который виден в чате. Внутренние sandbox/browser HTTP endpoints принимают только `X-Internal-Token`. Ключи провайдеров шифруются Fernet-ключом в `./data/.key`; API не отдаёт их frontend.

Контейнер sandbox запускается non-root, с `cap_drop: ALL`, `no-new-privileges`, read-only root filesystem, отдельным writable workspace, лимитами CPU/RAM/PIDs и таймаутами. Это сильнее старой реализации Quadrogent, но не является полноценной защитой от вредоносного кода при произвольном включении сетевого доступа. Для недоверенных пользователей нужен отдельный хост/VM, сетевой egress-контроль и reverse proxy с аутентификацией.

Веб-страницы, результаты поиска, файлы и вывод команд считаются данными, а не инструкциями. Внешние SaaS-интеграции сознательно не включены.

## Проверка

```bash
# статическая проверка Python
python3 -m py_compile api/app/*.py sandbox/server.py browser/server.py

# frontend
cd frontend
npm install
npm run build
```

Для smoke-проверки после запуска:

```bash
curl http://localhost:8000/health
curl -H 'X-Internal-Token: <INTERNAL_SERVICE_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{"command":"printf smoke-ok","timeout":10}' \
  http://localhost:8000/api/terminal/exec
```

## Критерий self-improvement

Попроси агента в чате: «Прочитай ARCHITECTURE.md, проверь структуру workspace, создай маленький файл `self-check.txt` с результатом проверки, запусти `git diff --check` и покажи diff». Агент должен построить план, запросить approval на запись и команду, выполнить их в sandbox и не заявить успех без результата проверки. Для теста лучше использовать отдельную копию репозитория в `./workspace`, а не рабочее дерево самого Uranus-AI.

## Структура

```text
api/app/       FastAPI, DB, provider gateway, tool registry, agent loop
sandbox/       ограниченное выполнение shell и файловых операций
browser/       Playwright Computer worker
frontend/      React/Vite интерфейс
skills/        пользовательские skill-пакеты
workspace/     рабочая папка агента, не коммитится
data/          SQLite, зашифрованные ключи и browser profile, не коммитится
```

## Источники дизайна

Функциональная модель сверялась с публичными материалами Manus о sandbox [1], My Computer [2], Browser Operator [3], Wide Research [4] и Agent Skills [5]. Подробные архитектурные решения находятся в [ARCHITECTURE.md](ARCHITECTURE.md).

[1]: https://manus.im/blog/manus-sandbox
[2]: https://manus.im/blog/manus-my-computer-desktop
[3]: https://manus.im/features/manus-browser-operator
[4]: https://manus.im/features/wide-research
[5]: https://manus.im/features/agent-skills
