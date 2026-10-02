import { expect, test } from "@playwright/test";

// Inside docker compose the worker reaches the demo APIs by service name.
const OLD_API = process.env.E2E_OLD_API ?? "http://legacy-shop-api:8000";
const NEW_API = process.env.E2E_NEW_API ?? "http://modern-shop-api:8000";

/**
 * The whole product in one path: sign in, describe a migration, run it,
 * and read what broke. If this passes, the pieces fit together.
 */
test("a migration is set up, run, and its breaking changes are shown", async ({ page }) => {
  // A fresh account per run, so earlier runs leave nothing behind.
  const email = `e2e-${Date.now()}@example.com`;

  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();

  // --- the project -----------------------------------------------------------
  await page.getByRole("link", { name: "New project" }).click();
  await page.getByLabel("Name").fill("Shop API migration");
  await page.getByLabel("Old API base URL").fill(OLD_API);
  await page.getByLabel("New API base URL").fill(NEW_API);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name: "Shop API migration" })).toBeVisible();
  await expect(page.getByText("Add a test case first.")).toBeVisible();

  // --- a rule: order lines are matched by SKU ---------------------------------
  await page.getByRole("link", { name: "Rules" }).click();
  await page.getByLabel("Kind").selectOption("unordered");
  await page.getByLabel("Path").fill("$.items");
  await page.getByLabel("Key (optional)").fill("sku");
  await page.getByRole("button", { name: "Add rule" }).click();
  await expect(page.getByText("$.items", { exact: true })).toBeVisible();

  // --- a test case: an order with two lines -----------------------------------
  await page.getByRole("link", { name: "Test cases" }).click();
  await page.getByRole("link", { name: "New test case" }).click();
  await page.getByLabel("Name").fill("Create an order with two lines");
  await page.getByLabel("Method").selectOption("POST");
  await page.getByLabel("Path").fill("/orders");
  await page.getByLabel("JSON body (optional)").fill(
    JSON.stringify({
      customer_name: "John",
      items: [
        { sku: "B-200", quantity: 1 },
        { sku: "A-100", quantity: 1 },
      ],
    }),
  );
  await page.getByRole("button", { name: "Create test case" }).click();
  await expect(page.getByRole("link", { name: "Create an order with two lines" })).toBeVisible();

  // --- run it -------------------------------------------------------------------
  await page.getByRole("link", { name: "Overview" }).click();
  await page.getByRole("button", { name: "Run now" }).click();
  await expect(page.getByRole("heading", { name: "Compatibility result" })).toBeVisible();

  // The page polls until the worker has finished, then shows the result.
  await expect(page.getByText("0 of 1 cases compatible")).toBeVisible({ timeout: 30_000 });

  // The one-yen tax difference, found and rated critical.
  const breaking = page.locator("section", { hasText: "Potential breaking changes" });
  await expect(breaking.getByText("$.total", { exact: true })).toBeVisible();
  await expect(breaking.getByText("332 → 333")).toBeVisible();
  await expect(breaking.getByText("critical").first()).toBeVisible();
  // The quantity type change is in both order lines, and listed once.
  await expect(breaking.getByText("$.items[*].quantity")).toHaveCount(1);

  // IDs and timestamps were recognised as noise, without any rule saying so.
  const safe = page.locator("section", { hasText: "Safe differences" });
  await expect(safe.getByText("$.id")).toBeVisible();
  await expect(safe.getByText("$.created_at")).toBeVisible();

  // --- the case: both responses side by side --------------------------------------
  await page.getByRole("link", { name: "Create an order with two lines" }).first().click();
  await expect(page.getByText("Old API")).toBeVisible();
  await expect(page.getByText("New API")).toBeVisible();
  await expect(page.getByText('"total": 332')).toBeVisible();
  await expect(page.getByText('"total": 333')).toBeVisible();

  // --- "this one does not matter" becomes a rule -------------------------------------
  const currency = page.locator("li", { hasText: "$.currency" });
  await currency.getByRole("button", { name: "Ignore this" }).click();
  await expect(currency.getByText("Ignored from the next run on.")).toBeVisible();

  // --- another account sees none of it -----------------------------------------------
  const runUrl = page.url();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Email").fill(`other-${Date.now()}@example.com`);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("No projects yet.")).toBeVisible();
  await page.goto(runUrl);
  await expect(page.getByText("This page could not be found")).toBeVisible();
});

/**
 * AI analysis, with the deployment's provider set to "fake" (canned
 * answers, no network). What matters here is the wiring and the framing:
 * opinions appear only after the project opts in, next to the findings,
 * labelled as opinions, and the result itself does not move.
 */
test("AI opinions appear beside the findings and change nothing", async ({ page }) => {
  test.skip(process.env.E2E_AI !== "1", "needs PARITYLENS_LLM_PROVIDER=fake (set E2E_AI=1)");

  await page.goto("/login");
  await page.getByLabel("Email").fill(`e2e-ai-${Date.now()}@example.com`);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("link", { name: "New project" }).click();
  await page.getByLabel("Name").fill("With AI");
  await page.getByLabel("Old API base URL").fill(OLD_API);
  await page.getByLabel("New API base URL").fill(NEW_API);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name: "With AI" })).toBeVisible();

  // Off by default; the project opts in, and is told what that means.
  await page.getByRole("link", { name: "Settings" }).click();
  const optIn = page.getByLabel(/Explain differences with AI/);
  await expect(optIn).not.toBeChecked();
  await expect(page.getByText(/sent to the model provider/)).toBeVisible();
  await optIn.check();
  await expect(optIn).toBeChecked();

  await page.getByRole("link", { name: "Test cases" }).click();
  await page.getByRole("link", { name: "New test case" }).click();
  await page.getByLabel("Name").fill("Fetch a migrated order");
  await page.getByLabel("Path").fill("/orders/ORD-000001");
  await page.getByRole("button", { name: "Create test case" }).click();

  await page.getByRole("link", { name: "Overview" }).click();
  await page.getByRole("button", { name: "Run now" }).click();
  await expect(page.getByText("0 of 1 cases compatible")).toBeVisible({ timeout: 30_000 });

  // The opinions arrive after the result, without a reload.
  await expect(page.getByText(/AI opinion/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/AI opinions are advisory/)).toBeVisible();
  // The result is what it was before the model spoke.
  await expect(page.getByText("0 of 1 cases compatible")).toBeVisible();
});
