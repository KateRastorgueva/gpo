import { type APIRequestContext, expect, test } from "@playwright/test"

import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser, signUpNewUser } from "./utils/user"

/**
 * Разделение доступа по ролям во фронтенде.
 *
 * Проверяем то, что видит пользователь: набор ссылок в сайдбаре, доступность
 * разделов и доступность действий внутри них. Права берутся из `/users/me`.
 */

const apiBase = process.env.VITE_API_URL ?? "http://localhost:8000"

// В этом файле логинимся под разными пользователями, поэтому сохранённую
// сессию суперюзера не используем.
test.use({ storageState: { cookies: [], origins: [] } })

async function createUserWithRole(
  request: APIRequestContext,
  roleName: string,
) {
  const email = randomEmail()
  const password = randomPassword()

  const tokenResponse = await request.post(
    `${apiBase}/api/v1/login/access-token`,
    {
      form: { username: firstSuperuser, password: firstSuperuserPassword },
    },
  )
  expect(tokenResponse.ok()).toBeTruthy()
  const token = (await tokenResponse.json()).access_token as string

  const rolesResponse = await request.get(`${apiBase}/api/v1/users/roles`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(rolesResponse.ok()).toBeTruthy()
  const roles = (await rolesResponse.json()).data as {
    id: string
    name: string
  }[]
  const role = roles.find((item) => item.name === roleName)
  expect(role, `роль ${roleName} должна существовать`).toBeTruthy()

  const createResponse = await request.post(`${apiBase}/api/v1/users/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { email, password, role_id: role?.id, is_active: true },
  })
  expect(createResponse.ok()).toBeTruthy()
  const created = (await createResponse.json()) as { role_name: string }
  expect(created.role_name).toBe(roleName)

  return { email, password }
}

test("operator sees admin sections without knowledge editing", async ({
  page,
  request,
}) => {
  const { email, password } = await createUserWithRole(request, "operator")
  await logInUser(page, email, password)

  // Разделы в левом меню: знания, обращения, метрики
  for (const section of ["Тикеты", "Знания", "Метрики"]) {
    await expect(page.getByRole("link", { name: section })).toBeVisible()
  }

  // Знания доступны на чтение: формы создания источника и «Удалить» нет
  await page.goto("/admin-knowledge")
  await expect(
    page.getByRole("heading", { name: "Знания", exact: true }),
  ).toBeVisible()
  await expect(page.getByText(/Роль: operator/)).toBeVisible()
  await page.getByRole("tab", { name: "Источники" }).click()
  await expect(page.getByText("Источники знаний")).toBeVisible()
  await expect(page.getByText("Новый источник знаний")).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Удалить" })).toHaveCount(0)

  // Тикеты оператор может решать: предупреждение об отсутствии прав не показывается
  await page.goto("/admin-requests")
  await page.getByRole("tab", { name: "Очередь и журнал" }).click()
  await expect(page.getByText(/Действия недоступны/)).toHaveCount(0)

  // Управление пользователями закрыто (вкладки нет)
  await page.goto("/admin-system")
  await expect(page.getByRole("tab", { name: "Пользователи" })).toHaveCount(0)
})

test("regular user has only base sections", async ({ page }) => {
  const email = randomEmail()
  const password = randomPassword()
  await signUpNewUser(page, "Regular User", email, password)
  await logInUser(page, email, password)

  await expect(page.getByRole("link", { name: "Чат" })).toBeVisible()
  for (const section of ["Знания", "Обращения", "Метрики", "Система"]) {
    await expect(page.getByRole("link", { name: section })).toHaveCount(0)
  }

  // Админ-разделы закрыты: уводит в чат
  await page.goto("/admin-knowledge")
  await expect(page).toHaveURL(/\/support/)
  await page.goto("/admin-system")
  await expect(page).toHaveURL(/\/support/)

  // Пользовательский раздел поддержки остаётся доступным
  await page.goto("/support")
  await expect(page.getByRole("heading", { name: "Техподдержка" })).toBeVisible()
})
