import { expect, type Page, test } from "@playwright/test"

/**
 * Smoke-проверка новых разделов поддержки: страницы и вкладки админки должны
 * рендериться на реальных данных API без ошибок в консоли.
 *
 * Сценарий намеренно только читающий: он не создаёт запросы, тикеты и отзывы,
 * поэтому его можно гонять на рабочей базе разработки.
 */

/** Заголовок карточки: CardTitle рендерится как div, а не как heading. */
const cardTitle = (page: Page, text: string) =>
  page.locator('[data-slot="card-title"]', { hasText: text })

test("user support page renders form and history", async ({ page }) => {
  const consoleErrors: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text())
  })

  await page.goto("/support")

  await expect(
    page.getByRole("heading", { name: "Техподдержка" }),
  ).toBeVisible()
  await expect(page.getByPlaceholder(/Опишите ваш вопрос/)).toBeVisible()
  await expect(page.getByRole("button", { name: "Отправить" })).toBeVisible()

  // История либо содержит обращения, либо показывает пустое состояние чата.
  await expect(
    page.getByText(/Обращений пока нет|Вопрос|Ответ/).first(),
  ).toBeVisible()

  expect(consoleErrors).toEqual([])
})

test("admin sections render with data", async ({ page }) => {
  const consoleErrors: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text())
  })

  // Старый адрес «Управления» ведёт в первый доступный раздел.
  await page.goto("/admin-support")
  await expect(page).toHaveURL(/\/admin-knowledge/)

  // Метрики: карточки со значениями
  await page.goto("/admin-metrics")
  await expect(
    page.getByRole("heading", { name: "Метрики", exact: true }).first(),
  ).toBeVisible()
  await expect(page.getByText("Всего запросов")).toBeVisible()
  await expect(page.getByText("Средняя оценка")).toBeVisible()

  // Обращения: очередь и тикеты
  await page.goto("/admin-requests")
  await expect(
    page.getByRole("heading", { name: "Обращения", exact: true }),
  ).toBeVisible()
  await page.getByRole("tab", { name: "Тикеты" }).click()
  await expect(cardTitle(page, "Тикеты")).toBeVisible()
  await expect(page.getByText(/активных из \d+|Тикетов нет/)).toBeVisible()

  // Знания: источники, таксономия, проверка поиска
  await page.goto("/admin-knowledge")
  await expect(
    page.getByRole("heading", { name: "Знания", exact: true }),
  ).toBeVisible()
  await page.getByRole("tab", { name: "Источники" }).click()
  await expect(cardTitle(page, "Источники знаний")).toBeVisible()

  await page.getByRole("tab", { name: "Категории и тэги" }).click()
  await expect(cardTitle(page, "Категории знаний")).toBeVisible()
  await expect(cardTitle(page, "Тэги")).toBeVisible()

  await page.getByRole("tab", { name: "Проверка поиска" }).click()
  await page.getByPlaceholder("Поисковый запрос").fill("поступление")
  await page.getByRole("button", { name: "Найти" }).click()
  await expect(
    page.getByText(/Найдено фрагментов|Ничего не найдено/),
  ).toBeVisible({
    timeout: 15_000,
  })

  // Система: настройки, классификатор тем, пользователи
  await page.goto("/admin-system")
  await expect(
    page.getByRole("heading", { name: "Система", exact: true }),
  ).toBeVisible()
  for (const tab of ["Настройки", "Классификатор тем", "Пользователи"]) {
    await expect(page.getByRole("tab", { name: tab })).toBeVisible()
  }

  expect(consoleErrors).toEqual([])
})

test("taxonomy create and delete round trip", async ({ page }) => {
  const name = `smoke-category-${Date.now()}`
  await page.goto("/admin-knowledge")
  await page.getByRole("tab", { name: "Категории и тэги" }).click()

  const categoryCard = page.locator('[data-slot="card"]', {
    hasText: "Категории знаний",
  })

  // Создание: проверяем реальный POST /admin/categories
  await categoryCard.getByPlaceholder("Название категории").fill(name)
  await categoryCard.getByRole("button", { name: "Добавить" }).click()
  // Строка категории — это input с defaultValue, поэтому ищем по атрибуту value
  const createdInput = categoryCard.locator(`input[value="${name}"]`)
  await expect(createdInput).toBeVisible()

  // Уборка: удаляем созданную категорию (DELETE /admin/categories/{id})
  await createdInput
    .locator("xpath=..")
    .getByRole("button", { name: "Удалить" })
    .click()
  await expect(categoryCard.locator(`input[value="${name}"]`)).toHaveCount(0)
})
