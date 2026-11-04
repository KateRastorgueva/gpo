# Версия сборки на экране

В «Управлении» (`/admin-support`) под заголовком и в футере любой страницы показана
строка вида `a1b2c3d · master · 2026-11-04 19:30 UTC · RAG: anythingllm · вектор: вкл · офтоп: выкл`.
Данные отдаёт `GET /api/v1/utils/version` (нужен вход в систему).

Коммит, ветка и время приходят из build-аргументов образа backend:
`GIT_SHA`, `GIT_BRANCH`, `BUILD_TIME` (compose передаёт их из окружения оболочки,
по умолчанию `unknown`). RAG-провайдер и флаги читаются из настроек в момент запроса.

## Обновление хоста (версия подставляется сама)

Linux/macOS/Git Bash: `./scripts/host-update.sh`

PowerShell:

```powershell
git pull
$env:GIT_SHA = (git rev-parse HEAD)
$env:GIT_BRANCH = (git rev-parse --abbrev-ref HEAD)
$env:BUILD_TIME = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
docker compose -f compose.yml -f compose.override.yml up -d --build backend frontend
```

Без этих переменных (обычный `docker compose up --build`) покажется `unknown`.
Если слой с кодом взят из кэша, значения тоже останутся прежними: после `git pull`
код меняется, так что слой пересобирается.
