import { expect, test } from "@playwright/test"

import { firstSuperuser, firstSuperuserPassword } from "./config"

/** Прямая ссылка на тикет открывает переписку. */
test("ticket has a shareable url", async ({ page, request }) => {
  const tokenResponse = await request.post("/api/v1/login/access-token", {
    form: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  const token = (await tokenResponse.json()).access_token as string
  const queue = await (
    await request.get("/api/v1/admin/operator-queue", {
      headers: { Authorization: `Bearer ${token}` },
    })
  ).json()
  const ticket = queue.data.find((item: { status: string }) =>
    ["open", "in_progress"].includes(item.status),
  )
  expect(ticket).toBeTruthy()

  await page.goto(`/ticket/${ticket.ticket_id}`)
  // Открывается большой чат оператора: переписка и поле ответа.
  await expect(page.getByLabel("Ответ пользователю")).toBeVisible({
    timeout: 15000,
  })
  await expect(page.getByText(ticket.question).first()).toBeVisible({
    timeout: 15000,
  })
})
