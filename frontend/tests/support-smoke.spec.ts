import { expect, type Page, test } from "@playwright/test"

/**
 * Smoke-проверка новых разделов поддержки: страницы и вкладки админки должны
 * рендериться на реальных данных API без ошибок в консоли.
 *
 * Сценарий намеренно только читающий: он не создаёт запросы, тикеты и отзывы,
 * поэтому его можно гонять на рабочей базе разработки.
 */

const TABS = [
  "Метрики",
  "Очередь и журнал",
  "Тикеты",
  "База знаний",
  "Документы",
  "Категории и тэги",
  "Поиск",
  "Частые вопросы",
]

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
    page.getByRole("heading", { name: "Техподдержка университета" }),
  ).toBeVisible()
  await expect(page.getByPlaceholder(/Опишите ваш вопрос/)).toBeVisible()
  await expect(page.getByRole("button", { name: "Отправить" })).toBeVisible()

  // История либо содержит карточки обращений, либо показывает пустое состояние.
  // CardTitle — это div, поэтому ищем по тексту, а не по роли heading.
  await expect(page.getByText("История обращений")).toBeVisible()
  await expect(
    page.getByText(/Обращений пока нет|Вопрос|Ответ/).first(),
  ).toBeVisible()

  expect(consoleErrors).toEqual([])
})

test("admin support page renders all tabs with data", async ({ page }) => {
  const consoleErrors: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text())
  })

  await page.goto("/admin-support")
  await expect(
    page.getByRole("heading", { name: "Администрирование поддержки" }),
  ).toBeVisible()

  // Метрики: карточки со значениями (вкладка по умолчанию)
  await expect(page.getByText("Всего запросов")).toBeVisible()
  await expect(page.getByText("Средняя оценка")).toBeVisible()

  for (const tab of TABS) {
    await page.getByRole("tab", { name: tab }).click()
    await expect(page.getByRole("tab", { name: tab })).toHaveAttribute(
      "data-state",
      "active",
    )
  }

  // Тикеты: либо список тикетов, либо пустое состояние
  await page.getByRole("tab", { name: "Тикеты" }).click()
  await expect(cardTitle(page, "Тикеты")).toBeVisible()
  await expect(page.getByText(/активных из \d+|Тикетов нет/)).toBeVisible()

  // База знаний: таблица источников с колонкой действий
  await page.getByRole("tab", { name: "База знаний" }).click()
  await expect(cardTitle(page, "Источники знаний")).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Переиндексировать источники" }),
  ).toBeVisible()

  // Таксономия: формы создания категории и тэга
  await page.getByRole("tab", { name: "Категории и тэги" }).click()
  await expect(cardTitle(page, "Категории знаний")).toBeVisible()
  await expect(cardTitle(page, "Тэги")).toBeVisible()

  // Поиск: реальный запрос к API с фильтрами
  await page.getByRole("tab", { name: "Поиск" }).click()
  await page.getByPlaceholder("Поисковый запрос").fill("поступление")
  await page.getByRole("button", { name: "Найти" }).click()
  await expect(
    page.getByText(/Найдено фрагментов|Ничего не найдено/),
  ).toBeVisible({
    timeout: 15_000,
  })

  expect(consoleErrors).toEqual([])
})

test("taxonomy create and delete round trip", async ({ page }) => {
  const name = `smoke-category-${Date.now()}`
  await page.goto("/admin-support")
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
