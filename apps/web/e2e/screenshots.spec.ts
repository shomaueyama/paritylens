import { expect, test } from "@playwright/test";

/**
 * Regenerates the screenshots in the README:
 *
 *   SCREENSHOTS=1 npm run test:e2e -- screenshots
 *
 * Skipped otherwise; it is a tool, not a test.
 */
const OUT = "../../docs/screenshots";
const OLD_API = process.env.E2E_OLD_API ?? "http://legacy-shop-api:8000";
const NEW_API = process.env.E2E_NEW_API ?? "http://modern-shop-api:8000";

const order = (items: { sku: string; quantity: number }[], customer: string | null = "John") => ({
  ...(customer ? { customer_name: customer } : {}),
  items,
});
const post = (json: unknown) => ({ request: { method: "POST", path: "/orders", json } });

const CASES = [
  { name: "Health check", steps: [{ request: { method: "GET", path: "/health" } }] },
  { name: "Create an order with one line", steps: [post(order([{ sku: "A-100", quantity: 3 }]))] },
  {
    name: "Create an order with two lines",
    steps: [post(order([{ sku: "B-200", quantity: 1 }, { sku: "A-100", quantity: 1 }]))],
  },
  {
    name: "Create an order without a customer name",
    steps: [post(order([{ sku: "A-100", quantity: 1 }], null))],
  },
  {
    name: "Fetch an order migrated from the legacy system",
    steps: [{ request: { method: "GET", path: "/orders/ORD-000001" } }],
  },
  {
    name: "Create an order, cancel it, and fetch it again",
    steps: [
      { id: "create", ...post(order([{ sku: "C-300", quantity: 1 }])), capture: { order_id: "$.id" } },
      { id: "cancel", request: { method: "DELETE", path: "/orders/{{order_id}}" } },
      { id: "fetch", request: { method: "GET", path: "/orders/{{order_id}}" } },
    ],
  },
];

test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to regenerate the README screenshots");

test("screenshots", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 860 });
  await page.goto("/login");
  await page.getByLabel("Email").fill(`demo-${Date.now()}@example.com`);
  await page.screenshot({ path: `${OUT}/login.png` });
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();

  // Set the project up through the API; the UI for that is covered elsewhere.
  const api = page.request;
  const headers = { origin: new URL(page.url()).origin };
  const project = await (
    await api.post("/api/v1/projects", {
      headers,
      data: {
        name: "Shop API migration",
        description: "Legacy order API to its FastAPI rewrite.",
        old_base_url: OLD_API,
        new_base_url: NEW_API,
      },
    })
  ).json();
  const base = `/api/v1/projects/${project.id}`;
  await api.post(`${base}/rules`, { headers, data: { kind: "unordered", path: "$.items", key: "sku" } });
  for (const testCase of CASES) {
    await api.post(`${base}/test-cases`, { headers, data: testCase });
  }

  await page.goto(`/projects/${project.id}/test-cases`);
  await page.screenshot({ path: `${OUT}/test-cases.png` });

  await page.goto(`/projects/${project.id}`);
  await page.getByRole("button", { name: "Run now" }).click();
  await expect(page.getByText(/of 6 cases compatible/)).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${OUT}/run-result.png`, fullPage: true });

  await page.getByRole("link", { name: "Create an order with two lines" }).last().click();
  await expect(page.getByText("Old API")).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 1080 });
  await page.screenshot({ path: `${OUT}/case-detail.png` });

  await page.goto(`/projects/${project.id}`);
  await page.screenshot({ path: `${OUT}/project-overview.png` });
});
