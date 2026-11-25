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
  await page.goto("/admin-system")
  await page.getByRole("tab", { name: "Пользователи" }).click()
  await expect(page.getByRole("button", { name: "Add User" })).toBeVisible()

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
  await page.waitForURL(/\/(support|admin-)/)
  await expect(page.getByRole("link", { name: "Тикеты" })).toBeVisible()
  await expect(page.getByRole("link", { name: "Метрики" })).toBeVisible()
})

test("operator answers an escalated question and the user sees the answer", async ({
  browser,
  request,
}) => {
  // Вопрос, который сейчас гарантированно уходит оператору: документ о сроках
  // рассмотрения обращений — скан без текстового слоя, в базе знаний его нет.
  // Заведомо вне базы знаний: такой вопрос гарантированно уходит оператору.
  const question = `Посоветуйте рецепт борща, кейс ${Date.now()}`
  const article = "https://help.tusur.ru/knowledgebase.php?article=105"
  const answer = `Ответ оператора: смотрите [инструкцию по общежитиям](${article}). ${Date.now()}`

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
  await expect(
    userPage.getByText(/Автоматический ответ недоступен/),
  ).toBeVisible({
    timeout: 60_000,
  })

  // Оператор видит тикет и отвечает на него
  const operator = await createUserWithRole(request, "operator")
  const operatorContext = await browser.newContext()
  const operatorPage = await operatorContext.newPage()
  await logInUser(operatorPage, operator.email, operator.password)
  await operatorPage.goto("/admin-requests")
  await operatorPage.getByRole("tab", { name: "Тикеты" }).click()

  const card = operatorPage
    .getByTestId("ticket-card")
    .filter({ hasText: question })
  await expect(card).toBeVisible({ timeout: 15_000 })
  await expect(card).toContainText("Открыт")

  // Переписка открывается на отдельной странице — большой чат оператора.
  await card.getByRole("button", { name: "Открыть переписку" }).click()
  await expect(operatorPage).toHaveURL(/\/ticket\//, { timeout: 15_000 })
  const replyBox = operatorPage.getByLabel("Ответ пользователю")
  await expect(replyBox).toBeVisible({ timeout: 15_000 })
  await replyBox.fill(answer)
  await operatorPage.getByRole("button", { name: "Ответить и решить" }).click()
  await expect(operatorPage.getByText("Переоткрыть")).toBeVisible({
    timeout: 15_000,
  })

  // Ответ оператора появляется в истории пользователя (и в карточке ответа, поэтому first)
  await userPage.reload()
  // Ответ оператора приходит в чат пользователя кликабельной ссылкой.
  await expect(
    userPage.getByRole("link", { name: "инструкцию по общежитиям" }).first(),
  ).toBeVisible({ timeout: 15_000 })
  // Форма оценки спрятана в свёрнутый блок «Оценить ответ».
  await userPage.getByText("Оценить ответ").first().click()
  await expect(userPage.getByText("Оцените ответ").first()).toBeVisible()

  await userContext.close()
  await operatorContext.close()
})
