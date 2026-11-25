import { expect, test } from "@playwright/test"

/** Ссылка на статью Help Desk приходит прямо в тексте ответа и кликабельна. */
test("answer text contains a clickable source link", async ({ page }) => {
  await page.goto("/support")
  await page.getByPlaceholder(/Опишите ваш вопрос/i).fill(
    "Как получить справку об обучении?",
  )
  await page.getByRole("button", { name: "Отправить" }).click()

  // Ссылка внутри абзаца ответа (а не только в блоке «Источники»).
  const linkInText = page.locator('p a[href*="knowledgebase.php"]').last()
  await expect(linkInText).toBeVisible({ timeout: 120000 })
})
