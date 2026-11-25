import { expect, test } from "@playwright/test"

/**
 * В чате источники видны сразу (без раскрытия свёрнутого блока):
 * статьи Help Desk — ссылкой на подраздел, PDF — строкой «файл: …».
 */
test("chat shows sources: article link and pdf file name", async ({ page }) => {
  await page.goto("/support")
  const input = page.getByPlaceholder(/Опишите ваш вопрос/i)

  await input.fill("Как получить справку об обучении?")
  await page.getByRole("button", { name: "Отправить" }).click()
  await expect(page.getByText(/Источники \(\d+\)/).last()).toBeVisible({
    timeout: 120000,
  })
  await expect(page.locator('a[href*="knowledgebase.php"]').last()).toBeVisible({
    timeout: 60000,
  })

  await input.fill("Кто является учредителем ТУСУР?")
  await page.getByRole("button", { name: "Отправить" }).click()
  await expect(page.getByText(/файл: .*\.pdf/i).last()).toBeVisible({
    timeout: 120000,
  })
})
