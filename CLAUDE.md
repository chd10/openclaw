# Правила для Клока — OpenClaw

## Git
- Перед любой правкой файла делать коммит-снапшот: `git add -A && git commit -m "snapshot: before editing <filename>"`
- После правки коммитить: `git add -A && git commit -m "edit: <filename>"`
- После каждой сессии делать `git push`

## Docker
- Перед пересборкой проверять пути через `docker inspect`
- Контейнер: `openclaw`, порт 5000

## Безопасность
- Защита по MANAGER_CHAT_ID=40603594
- Ключи только в .env, не в коде
