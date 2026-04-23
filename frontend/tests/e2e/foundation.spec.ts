import { test, expect } from "@playwright/test"

const unique = () => `u${Date.now()}@test.example`

test("signup, save llm config, test connection surfaces a result", async ({ page }) => {
  const email = unique()
  const password = "correct horse battery staple"

  await page.goto("/signup")
  await page.fill('input[type="email"]', email)
  await page.fill('input[type="password"]', password)
  await page.click('button:has-text("Sign up")')
  await expect(page.getByText(`Welcome, ${email}`)).toBeVisible()

  await page.goto("/settings/llm")
  await page.fill('input[placeholder="name (e.g. openrouter)"]', "fake")
  await page.fill('input[placeholder="chat base_url (https://...)"]', "http://127.0.0.1:9/v1")
  await page.fill('input[placeholder="chat model"]', "fake-chat")
  await page.fill('input[placeholder="chat API key"]', "sk-fake")
  await page.fill('input[placeholder="embed base_url"]', "http://127.0.0.1:9/v1")
  await page.fill('input[placeholder="embed model"]', "fake-embed")
  await page.fill('input[placeholder="embed API key"]', "sk-fake")
  await page.fill('input[placeholder="embed dim"]', "1536")
  await page.click('button:has-text("Save")')

  await expect(page.getByText("fake", { exact: false })).toBeVisible()
  await page.click('button:has-text("Test")')
  await expect(page.locator("text=chat:")).toContainText(/(ok|error:)/)
})
