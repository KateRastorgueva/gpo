# Testing

Короткий guide для новичка: что запускать и в каком порядке.

## 1. Backend (основное)

Полный прогон backend-тестов:

```bash
docker compose exec backend bash scripts/tests-start.sh
```

Точечно для support:

```bash
docker compose exec backend pytest tests/api/routes/test_support.py
```

## 2. Frontend e2e (smoke)

```bash
bun run test
```

## 3. Рекомендуемый порядок перед PR

1. Точечные backend-тесты по измененной зоне.
2. Полный backend-тест прогон.
3. E2E smoke для критичных пользовательских сценариев.
