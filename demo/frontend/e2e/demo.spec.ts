import { test, expect } from "@playwright/test";

test.describe("Full-stack demo", () => {
  test("page loads and shows Run button and computational graph", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: /run/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Computational graph" })).toBeVisible();
    await expect(page.getByText(/Computational graph \(from code\)/i)).toBeVisible({ timeout: 10000 });
  });

  test("Run executes pipeline and graph shows nodes, clicking node shows details", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByText(/Computational graph \(from code\)/i)).toBeVisible({ timeout: 10000 });

    await page.getByRole("button", { name: /run/i }).click();
    const graphNode = page.getByTestId("graph-node-0");
    await expect(graphNode).toBeVisible({ timeout: 5000 });
    await graphNode.click();

    await expect(page.getByText(/select a node in the graph/i)).not.toBeVisible();
    await expect(page.getByRole("heading", { name: /data summary|generated code/i })).toBeVisible({ timeout: 5000 });
  });

  test("Load script buttons work", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Simple" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Medium" })).toBeVisible();
    await expect(page.getByRole("button", { name: /full/i })).toBeVisible();

    await page.getByRole("button", { name: "Medium" }).click();
    await page.waitForTimeout(800);
    await expect(page.getByText(/medium/i)).toBeVisible();
  });
});
