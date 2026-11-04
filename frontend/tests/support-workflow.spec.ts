import { type APIRequestContext, expect, test } from "@playwright/test"

import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser, signUpNewUser } from "./utils/user"

/**
 * Сквозные сценарии, о которых чаще всего спрашивают:
 * 1) выдача роли пользователю в админке (и её эффект для самого пользователя);
 * 2) ответ оператора на вопрос, который ушёл в эскалацию.
 *
 * Оба идут через интерфейс, а не через API: именно UI-путь ломался чаще всего.
 */

const apiBase = process.env.VITE_API_URL ?? "http://localhost:8000"

test.use({ storageState: { cookies: [], origins: [] } })

async function createUserWithRole(
  request: APIRequestContext,
  roleName: string,
) {
  const email = randomEmail()
  const password = randomPassword()

  const tokenResponse = await request.post(
    `${apiBase}/api/v1/login/access-token`,
    { form: { username: firstSuperuser, password: firstSuperuserPassword } },
  )
  expect(tokenResponse.ok()).toBeTruthy()
  const token = (await tokenResponse.json()).access_token as string

  const rolesResponse = await request.get(`${apiBase}/api/v1/users/roles`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const roles = (await rolesResponse.json()).data as {
    id: string
    name: string
  }[]
  const role = roles.find((item) => item.name === roleName)

  const createResponse = await request.post(`${apiBase}/api/v1/users/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { email, password, role_id: role?.id, is_active: true },
  })
  expect(createResponse.ok()).toBeTruthy()
  return { email, password }
}

test("admin grants a role in the panel and the user gets access", async ({
  page,
}) => {
  const email = randomEmail()
  const password = randomPassword()

  await logInUser(page, firstSuperuser, firstSuperuserPassword)
  await page.goto("/admin")
  await expect(page.getByRole("heading", { name: "Users" })).toBeVisible()

  // Создание пользователя с ролью оператора через форму
  await page.getByRole("button", { name: "Add User" }).click()
  await page.getByPlaceholder("Email").fill(email)
  await page.getByPlaceholder("Password").first().fill(password)
  await page.getByPlaceholder("Password").last().fill(password)
  await page.getByRole("combobox").click()
  await page.getByRole("option", { name: "operator" }).click()
  await page.getByLabel("Is active?").check()
  await page.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("User created successfully")).toBeVisible()

  const row = page.getByRole("row").filter({ hasText: email })
  await expect(row.getByText("operator")).toBeVisible()

  // Смена роли у существующего пользователя
  await row.getByRole("button").last().click()
  await page.getByRole("menuitem", { name: "Edit User" }).click()
  await page.getByRole("combobox").click()
  await page.getByRole("option", { name: "admin" }).click()
  await page.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("User updated successfully")).toBeVisible()
  await expect(
    page.getByRole("row").filter({ hasText: email }).getByText("admin"),
  ).toBeVisible()

  // Выданная роль реально работает: пользователь получает админские разделы
  await page.getByTestId("user-menu").click()
  await page.getByRole("menuitem", { name: "Log out" }).click()
  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/")
  await expect(
    page.getByRole("link", { name: "Admin", exact: true }),
  ).toBeVisible()
  await expect(page.getByRole("link", { name: "Support Admin" })).toBeVisible()
})

test("operator answers an escalated question and the user sees the answer", async ({
  browser,
  request,
}) => {
  const question = `Сколько стоит проживание в общежитии? кейс ${Date.now()}`
  const answer = `Ответ оператора: стоимость проживания уточняется в деканате. ${Date.now()}`

  // Пользователь задаёт вопрос, который уходит оператору
  const userContext = await browser.newContext()
  const userPage = await userContext.newPage()
  const userEmail = randomEmail()
  const userPassword = randomPassword()
  await signUpNewUser(userPage, "Support User", userEmail, userPassword)
  await logInUser(userPage, userEmail, userPassword)
  await userPage.goto("/support")
  await userPage.getByPlaceholder(/Опишите ваш вопрос/).fill(question)
  await userPage.getByRole("button", { name: "Отправить" }).click()
  await expect(userPage.getByText("Вопрос передан оператору")).toBeVisible({
    timeout: 60_000,
  })

  // Оператор видит тикет и отвечает на него
  const operator = await createUserWithRole(request, "operator")
  const operatorContext = await browser.newContext()
  const operatorPage = await operatorContext.newPage()
  await logInUser(operatorPage, operator.email, operator.password)
  await operatorPage.goto("/admin-support")
  await operatorPage.getByRole("tab", { name: "Обращения" }).click()
  await operatorPage.getByRole("tab", { name: "Тикеты" }).click()

  const card = operatorPage
    .getByTestId("ticket-card")
    .filter({ hasText: question })
  await expect(card).toBeVisible({ timeout: 15_000 })
  await expect(card.getByText("Открыт")).toBeVisible()

  await card.getByRole("button", { name: "Ответить и решить" }).click()
  await operatorPage
    .getByPlaceholder("Итоговое решение для пользователя")
    .fill(answer)
  await operatorPage.getByRole("button", { name: "Сохранить решение" }).click()
  await expect(card.getByText("Решён", { exact: true })).toBeVisible({
    timeout: 15_000,
  })

  // Ответ оператора появляется в истории пользователя (и в карточке ответа, поэтому first)
  await userPage.reload()
  await expect(userPage.getByText(answer).first()).toBeVisible({
    timeout: 15_000,
  })
  await expect(userPage.getByText("Оцените ответ").first()).toBeVisible()

  await userContext.close()
  await operatorContext.close()
})
