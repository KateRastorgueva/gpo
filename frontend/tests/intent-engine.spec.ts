import { expect, test } from "@playwright/test"

/** Переключатель движка классификатора в админке: helpdesk ↔ kate. */
test("intent engine switch works in the admin panel", async ({ page }) => {
  await page.goto("/admin-system")


  const intentTab = page.getByRole("tab", { name: "Классификатор тем" })
  await expect(intentTab).toBeVisible({ timeout: 15000 })
  await intentTab.click()

  const helpdesk = page.getByRole("button", { name: /новая модель/i })
  const kate = page.getByRole("button", { name: /старая модель/i })
  await expect(helpdesk).toBeVisible({ timeout: 15000 })
  await expect(kate).toBeVisible()

  await helpdesk.click()
  await expect(page.getByText("Движок классификатора переключён")).toBeVisible({
    timeout: 15000,
  })
  await expect(page.getByText(/Тем у движка: 22/)).toBeVisible({
    timeout: 15000,
  })

  await kate.click()
  await expect(page.getByText(/Тем у движка: 24/)).toBeVisible({
    timeout: 15000,
  })
})
