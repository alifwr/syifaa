import { test, expect } from "@playwright/test"

const unique = () => `u${Date.now()}@test.example`

test("teach-back: start, message stream, end with score", async ({ page }) => {
  const email = unique()
  const password = "correct horse battery staple"

  await page.goto("/signup", { waitUntil: "networkidle" })
  await page.fill('input[type="email"]', email)
  await page.fill('input[type="password"]', password)
  await page.click('button:has-text("Sign up")')
  await expect(page.getByText(`Welcome, ${email}`)).toBeVisible()

  const sid = "00000000-0000-0000-0000-000000000001"
  const cid = "00000000-0000-0000-0000-000000000002"

  // Stub only API calls (localhost:8000), not Nuxt page navigations (localhost:3000)
  const API = "http://localhost:8000"
  await page.route(`${API}/feynman/start`, async (route) => {
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: sid, user_id: "u", paper_id: null,
        target_concept_id: cid, kind: "fresh",
        started_at: new Date().toISOString(), ended_at: null,
        quality_score: null,
        transcript: [{ role: "system", content: "sys", ts: "" }],
      }),
    })
  })
  await page.route(`${API}/feynman/${sid}`, async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        id: sid, user_id: "u", paper_id: null,
        target_concept_id: cid, kind: "fresh",
        started_at: new Date().toISOString(), ended_at: null,
        quality_score: null,
        transcript: [{ role: "system", content: "sys", ts: "" }],
      }),
    })
  })
  await page.route(`${API}/feynman/${sid}/message`, async (route) => {
    const body = "data: Why\n\ndata:  self-attention?\n\ndata: [DONE]\n\n"
    await route.fulfill({
      status: 200, contentType: "text/event-stream", body,
    })
  })
  await page.route(`${API}/feynman/${sid}/end`, async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ quality_score: 0.42 }),
    })
  })

  // /feynman/* is not in PROTECTED routes, so page.goto works after signup
  await page.goto(`/feynman/${sid}`)
  await expect(page.getByText("Feynman session")).toBeVisible()

  await page.fill('input[placeholder="explain it back…"]', "self-attention is when…")
  await page.click('button:has-text("Send")')
  await expect(page.getByText(/Why\s+self-attention\?/)).toBeVisible({ timeout: 5_000 })

  await page.getByRole("button", { name: "End", exact: true }).click()
  await expect(page.getByText("0.42", { exact: true })).toBeVisible()
})
