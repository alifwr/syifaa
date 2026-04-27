import { test, expect } from "@playwright/test"

const unique = () => `u${Date.now()}@test.example`
const API = "http://localhost:8000"

async function signupStubbed(
  page: import("@playwright/test").Page,
  email: string,
) {
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

  await page.goto("/signup", { waitUntil: "networkidle" })
  await page.fill('input[type="email"]', email)
  await page.fill('input[type="password"]', "correct horse battery staple")
  await page.click('button:has-text("Sign up")')
  await expect(page.getByText(`Welcome, ${email}`)).toBeVisible()
}

test("dashboard tile + score table render with stubbed data", async ({ page }) => {
  const email = unique()

  await signupStubbed(page, email)

  await page.route(`${API}/dashboard`, async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        concept_count: 17,
        sessions: [
          { started_at: "2026-04-25T10:00:00Z", quality_score: 0.78 },
          { started_at: "2026-04-24T10:00:00Z", quality_score: 0.62 },
        ],
      }),
    })
  })

  // Navigate client-side via nav link to preserve auth token (avoids SSR middleware redirect)
  await page.click('nav a[href="/dashboard"]')
  await expect(page.getByText("Dashboard")).toBeVisible()
  await expect(page.getByText("17", { exact: true })).toBeVisible()
  await expect(page.getByText("0.78")).toBeVisible()
  await expect(page.getByText("0.62")).toBeVisible()
})


test("review page lists due items and start button routes to feynman", async ({ page }) => {
  const email = unique()

  await signupStubbed(page, email)

  const itemId = "00000000-0000-0000-0000-000000000010"
  const sid = "00000000-0000-0000-0000-000000000020"

  await page.route(`${API}/review/due`, async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify([{
        id: itemId, concept_id: "c1", concept_name: "Self-attention",
        embed_dim: 1536, ease: 2.5, interval_days: 1,
        due_at: new Date().toISOString(), last_score: 0.7,
      }]),
    })
  })
  await page.route(`${API}/review/start`, async (route) => {
    await route.fulfill({
      status: 201, contentType: "application/json",
      body: JSON.stringify({
        id: sid, user_id: "u", paper_id: null,
        target_concept_id: "c1", kind: "scheduled",
        started_at: new Date().toISOString(), ended_at: null,
        quality_score: null, transcript: [],
      }),
    })
  })
  await page.route(`${API}/feynman/${sid}`, async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        id: sid, user_id: "u", paper_id: null,
        target_concept_id: "c1", kind: "scheduled",
        started_at: new Date().toISOString(), ended_at: null,
        quality_score: null, transcript: [],
      }),
    })
  })

  // Navigate client-side via nav link to preserve auth token (avoids SSR middleware redirect)
  await page.click('nav a[href="/review"]')
  await expect(page.getByText("Review queue")).toBeVisible()
  await expect(page.getByText("Self-attention")).toBeVisible()
  await page.click('button:has-text("Start review")')
  await expect(page).toHaveURL(new RegExp(`/feynman/${sid}$`))
})
