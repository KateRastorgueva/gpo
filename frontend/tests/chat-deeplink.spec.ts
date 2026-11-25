import { expect, test } from "@playwright/test"

/** Ссылка на чат: /chat/<session_id> открывает ту же переписку. */
test("chat has a shareable url", async ({ page }) => {
  await page.goto("/support")
  await page.getByPlaceholder(/Опишите ваш вопрос/i).fill(
    "Как получить справку об обучении?",
  )
  await page.getByRole("button", { name: "Отправить" }).click()

  await page.waitForURL(/\/chat\/[0-9a-f-]+/, { timeout: 90000 })
  const url = page.url()
  await expect(page.getByText(/справк/i).first()).toBeVisible({
    timeout: 60000,
  })

  // Открываем ту же ссылку заново — чат восстанавливается из истории.
  await page.goto(url)
  await expect(page.locator('a[href*="/chat/"]').first()).toBeVisible({
    timeout: 30000,
  })
  await expect(page.getByText(/справк/i).first()).toBeVisible({
    timeout: 60000,
  })
})
