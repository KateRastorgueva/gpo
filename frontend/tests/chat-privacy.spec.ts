import { expect, test } from "@playwright/test"

import { firstSuperuser, firstSuperuserPassword } from "./config"

/**
 * Приватность чатов: на одном браузере следующий вошедший не должен видеть
 * чаты предыдущего — ни из localStorage, ни с сервера.
 *
 * Регрессия: раньше список чатов лежал в общем ключе `support_chats`, поэтому
 * после смены аккаунта в том же браузере показывались чужие обращения.
 */
test("chats are not shared between users on the same browser", async ({
  page,
}) => {
  // Чистый старт: ни токена, ни чатов.
  await page.goto("/login")
  await page.evaluate(() => localStorage.clear())

  // Готовим временного пользователя через API администратора.
  const tokenResponse = await page.request.post("/api/v1/login/access-token", {
    form: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  const adminToken = (await tokenResponse.json()).access_token as string
  const probeEmail = `leak_${Date.now()}@example.com`
  const probePassword = "ProbePass123!"
  const created = await page.request.post("/api/v1/users/", {
    headers: { Authorization: `Bearer ${adminToken}` },
    data: { email: probeEmail, password: probePassword, role_name: "user" },
  })
  expect(created.ok()).toBeTruthy()
  const probeId = (await created.json()).id as string

  try {
    // 1) Админ: у него в списке есть чаты.
    await page.goto("/login")
    await page.fill('input[type="email"]', firstSuperuser)
    await page.fill('input[type="password"]', firstSuperuserPassword)
    await page.click('button[type="submit"]')
    await page.waitForURL(/admin-support/)
    await page.goto("/support")
    await expect(page.getByLabel("Удалить чат").first()).toBeVisible({
      timeout: 30000,
    })
    expect(await page.getByLabel("Удалить чат").count()).toBeGreaterThan(0)

    // 2) Тот же браузер: убираем только токен — чаты админа остаются в localStorage.
    await page.evaluate(() => localStorage.removeItem("access_token"))

    // 3) Входим новым пользователем — его список должен быть пуст.
    await page.goto("/login")
    await page.fill('input[type="email"]', probeEmail)
    await page.fill('input[type="password"]', probePassword)
    await page.click('button[type="submit"]')
    await page.waitForURL(/support/)
    await page.waitForTimeout(2500)

    expect(await page.getByLabel("Удалить чат").count()).toBe(0)
  } finally {
    await page.request.delete(`/api/v1/users/${probeId}`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    })
  }
})
