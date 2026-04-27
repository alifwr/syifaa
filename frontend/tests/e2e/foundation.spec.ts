import { test, expect } from "@playwright/test"

const unique = () => `u${Date.now()}@test.example`
const API = "http://localhost:8000"

test("signup, save llm config, test connection surfaces a result", async ({ page }) => {
  const email = unique()
  const password = "correct horse battery staple"

  const cfgId = "00000000-0000-0000-0000-000000000099"

  // Stub auth so tests run without a live backend
  await page.route(`${API}/auth/signup`, async (route) => {
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({}) })
  })
  await page.route(`${API}/auth/login`, async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ access_token: "tok", refresh_token: "rtok", token_type: "bearer" }),
    })
  })
  await page.route(`${API}/auth/me`, async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ id: "u1", email }),
    })
  })

  // Stub LLM config endpoints
  let savedConfig: object | null = null
  await page.route(`${API}/llm-config`, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify(savedConfig
          ? [savedConfig]
          : []),
      })
    } else {
      // POST — save and return the new config
      savedConfig = {
        id: cfgId, name: "fake",
        chat_model: "fake-chat", embed_model: "fake-embed", embed_dim: 1536,
        is_active: false,
        chat_base_url: "http://127.0.0.1:9/v1",
        embed_base_url: "http://127.0.0.1:9/v1",
      }
      await route.fulfill({
        status: 201, contentType: "application/json",
        body: JSON.stringify(savedConfig),
      })
    }
  })
  await page.route(`${API}/llm-config/${cfgId}/test`, async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ chat: "ok", embed: "ok" }),
    })
  })

  await page.goto("/signup", { waitUntil: "networkidle" })
  await page.fill('input[type="email"]', email)
  await page.fill('input[type="password"]', password)
  await page.click('button:has-text("Sign up")')
  await expect(page.getByText(`Welcome, ${email}`)).toBeVisible()

  // Navigate client-side (preserves in-memory auth token from SSR+SPA transition)
  await page.click('nav a[href="/settings/llm"]')
  await expect(page.getByRole("heading", { name: "LLM configuration" })).toBeVisible()
  await page.fill('input[placeholder="name (e.g. openrouter)"]', "fake")
  await page.fill('input[placeholder="chat base_url (https://...)"]', "http://127.0.0.1:9/v1")
  await page.fill('input[placeholder="chat model"]', "fake-chat")
  await page.fill('input[placeholder="chat API key"]', "sk-fake")
  await page.fill('input[placeholder="embed base_url"]', "http://127.0.0.1:9/v1")
  await page.fill('input[placeholder="embed model"]', "fake-embed")
  await page.fill('input[placeholder="embed API key"]', "sk-fake")
  await page.fill('input[placeholder="embed dim"]', "1536")
  await page.click('button:has-text("Save")')

  await expect(page.getByText("fake", { exact: true })).toBeVisible()
  await page.click('button:has-text("Test")')
  await expect(page.locator("p.font-mono")).toContainText(/(ok|error:)/)
})
