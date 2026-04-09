# Getting Started Backend

Документ для новичка в backend: как запустить проект, проверить, что всё живо, и куда вносить первые изменения.

## 1. Предусловия

- Docker Desktop запущен.
- В корне проекта есть заполненный `.env` (создайте из `.env.example`).

Быстрое создание `.env`:

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

## 2. Первый запуск (канонический путь)

Из корня проекта:

```bash
docker compose up -d
docker compose ps
```

Проверка доступности:

- Backend docs: <http://localhost:8000/docs>
- Frontend: <http://localhost:5173>
- Support UI: <http://localhost:5173/support>
- Admin Support UI: <http://localhost:5173/admin-support>

## 3. Базовая рабочая сессия backend

### Где находится код

- API routes: `backend/app/api/routes/`
- Конфиг и БД: `backend/app/core/`
- Бизнес-логика: `backend/app/services/`
- Модели и схемы: `backend/app/models.py`
- Тесты: `backend/tests/`

### Что менять первым

1. Добавить/обновить endpoint: `backend/app/api/routes/*.py`
2. Обновить бизнес-логику: `backend/app/services/*.py`
3. Обновить схемы/типы ответа: `backend/app/models.py`
4. Добавить/обновить тест в `backend/tests/...`

## 4. Тесты (минимум перед PR)

Полный backend:

```bash
docker compose exec backend bash scripts/tests-start.sh
```

Точечно по support:

```bash
docker compose exec backend pytest tests/api/routes/test_support.py
```

## 5. Частые проблемы

### Docker завис в `starting`

1. Закрыть Docker Desktop.
2. Выполнить:

```bash
wsl --shutdown
```

3. Запустить Docker Desktop снова.

### Безопасное завершение сессии

```bash
docker compose down --remove-orphans
```

`-v` использовать только если действительно нужно удалить volume-данные.
