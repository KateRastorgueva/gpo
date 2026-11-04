#!/usr/bin/env bash
# Обновление хоста с версией сборки: git pull + пересборка backend/frontend.
# Подставляет GIT_SHA, GIT_BRANCH, BUILD_TIME, которые показывает /admin-support.
set -euo pipefail
cd "$(dirname "$0")/.."
git pull
export GIT_SHA="$(git rev-parse HEAD)"
export GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
export BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
docker compose -f compose.yml -f compose.override.yml up -d --build backend frontend
echo "Собрано: ${GIT_BRANCH}@${GIT_SHA:0:7} ${BUILD_TIME}"
