import { test, expect } from "@playwright/test"
import { resolve } from "path"
import { fileURLToPath } from "url"

const __filename = fileURLToPath(import.meta.url)
const __dirname = resolve(__filename, "..")

const unique = () => `u${Date.now()}@test.example`

test("signup, seed llm-config, upload paper, see it in list", async ({ page }) => {
  const email = unique()
  const password = "correct horse battery staple"

  // Signup — full page load is fine here (unprotected route)
  await page.goto("/signup", { waitUntil: "networkidle" })
  await page.fill('input[type="email"]', email)
  await page.fill('input[type="password"]', password)
  await page.click('button:has-text("Sign up")')
  await expect(page.getByText(`Welcome, ${email}`)).toBeVisible()

  // Navigate to LLM settings via client-side link (preserves auth token in memory)
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
  await page.click('button:has-text("Activate")')

  // Navigate to Papers via client-side link
  await page.click('nav a[href="/papers"]')
  await expect(page.getByRole("heading", { name: "Papers" })).toBeVisible()
  await page.fill('input[placeholder="title"]', "Fixture paper")
  await page.setInputFiles('input[type="file"]', resolve(__dirname, "fixtures/sample.pdf"))
  await page.click('button:has-text("Upload")')
  await expect(page.getByText("Fixture paper")).toBeVisible()
})
