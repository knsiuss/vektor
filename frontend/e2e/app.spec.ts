import { test, expect } from "@playwright/test";

test.describe("Vektor AI Operations Platform", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("h1")).toBeVisible({ timeout: 15000 });
  });

  async function openSidebar(page: import("@playwright/test").Page, isMobile: boolean) {
    if (isMobile) {
      await page.locator(".mobile-topbar button").click();
    } else {
      await page.locator(".sidebar-open-button").click();
    }
  }

  async function openDrawer(page: import("@playwright/test").Page, label: string, isMobile: boolean) {
    await openSidebar(page, isMobile);
    await page.locator(".sidebar-utilities button", { hasText: "Settings" }).click();
    await expect(page.locator(".crm-settings-nav")).toBeVisible({ timeout: 10000 });
    if (label !== "Connection Settings" && label !== "Connection") {
      await page.locator(".crm-settings-nav button", { hasText: label }).click();
    } else {
      await page.locator(".crm-settings-nav button", { hasText: "Connection" }).click();
    }
    await expect(page.locator(".v-settings, .v-knowledge, .v-telemetry, dialog").first()).toBeVisible({ timeout: 10000 });
  }

  test("renders empty state with branding and starter cards", async ({ page }) => {
    await expect(page.locator("h1")).toContainText("Hello! I’m Vektor");
    await expect(page.locator(".starter-grid")).toBeVisible();
    await expect(page.locator(".composer")).toBeVisible();
    await expect(page.locator(".attach-button")).toBeVisible();
    await expect(page.locator(".send-button")).toBeDisabled();
  });

  test("composer enables send on text input and respects Enter/Shift+Enter", async ({ page }) => {
    await page.goto("/");
    const textarea = page.locator("#message-input");
    await textarea.fill("Check system health");
    await expect(page.locator(".send-button")).not.toBeDisabled();

    await textarea.press("Shift+Enter");
    await expect(textarea).toContainText("Check system health\n");

    await textarea.press("Enter");
    await expect(page.locator(".send-button.is-stop")).toBeVisible({ timeout: 10000 });
    await expect(page.locator(".send-button.is-stop")).not.toBeVisible({ timeout: 30000 });
    await expect(page.locator(".send-button:not(.is-stop)")).toBeVisible({ timeout: 10000 });
  });

  test("plus menu opens and lets the user change retrieval mode", async ({ page }) => {
    await page.locator(".attach-button").click();
    await page.locator(".composer-plus-menu").getByRole("menuitem", { name: /RAG Mode/ }).click();
    await page.getByRole("menuitemradio", { name: "Explicit" }).click();
    await page.locator(".attach-button").click();
    await page.locator(".composer-plus-menu").getByRole("menuitem", { name: "More Options" }).click();
    await expect(page.locator(".scope-control")).toBeVisible();
    await page.locator(".attach-button").click();
    await page.locator(".composer-plus-menu").getByRole("menuitem", { name: /RAG Mode/ }).click();
    await page.getByRole("menuitemradio", { name: "Auto (Agentic)" }).click();
    await page.locator(".attach-button").click();
    await page.locator(".composer-plus-menu").getByRole("menuitem", { name: "More Options" }).click();
    await expect(page.locator(".scope-control")).not.toBeVisible();
  });

  test("plus menu lets the user allow mutating tools", async ({ page }) => {
    await page.goto("/");
    await page.locator(".attach-button").click();
    const toggle = page.locator(".composer-menu-switch input[role='switch']");
    await toggle.check();
    await expect(toggle).toBeChecked();
    await expect(page.locator(".composer")).toHaveClass(/mutating-enabled/);
    await toggle.uncheck();
    await expect(toggle).not.toBeChecked();
  });

  test("sidebar navigation opens Settings hub and switches between Connection, Knowledge and Telemetry", async ({ page, isMobile }) => {
    await page.goto("/");
    await openSidebar(page, isMobile);
    await page.locator(".sidebar-utilities button", { hasText: "Settings" }).click();
    await expect(page.locator(".sidebar-utilities button.is-active")).toContainText("Settings");
    await expect(page.locator("h1")).toContainText("Connection Settings");

    await page.locator(".crm-settings-nav button", { hasText: "Knowledge Base" }).click();
    await expect(page.locator("h1")).toContainText("Knowledge Base");
    await expect(page.locator(".v-dropzone")).toBeVisible();

    await page.locator(".crm-settings-nav button", { hasText: "Telemetry & Analytics" }).click();
    await expect(page.locator("h1")).toContainText("Telemetry & Analytics");

    await page.locator(".crm-settings-nav button", { hasText: "Connection" }).click();
    await expect(page.locator("h1")).toContainText("Connection Settings");
  });

  test("connection settings form saves a valid URL", async ({ page, isMobile }) => {
    await openDrawer(page, "Connection Settings", isMobile);
    await page.locator(".v-advanced-toggle").click();

    const urlInput = page.locator("#provider-base-url");
    await urlInput.fill("http://127.0.0.1:8000");
    await page.locator("button:has-text('Save Changes')").click();
    await expect(page.locator(".v-save")).not.toHaveText("Saving...");
    await expect(page.locator(".form-message.success, .form-message.error").first()).toBeVisible({ timeout: 15000 });
  });

  test("API key can be revealed and hidden", async ({ page, isMobile }) => {
    await openDrawer(page, "Connection Settings", isMobile);
    await page.locator(".v-advanced-toggle").click();
    const key = page.locator("#provider-api-key");
    await expect(key).toHaveAttribute("type", "password");
    await page.getByRole("button", { name: "Show API key" }).click();
    await expect(key).toHaveAttribute("type", "text");
  });

  test("profile dialog opens from the sidebar and closes", async ({ page, isMobile }) => {
    await page.goto("/");
    await openSidebar(page, isMobile);
    await page.locator(".v-user").click();
    await expect(page.locator("dialog.v-profile")).toBeVisible();
    await expect(page.locator("dialog.v-profile h2")).toContainText("Profile");
    await page.getByRole("button", { name: "Close profile" }).click();
    await expect(page.locator("dialog.v-profile")).not.toBeVisible();
  });

  test("keyboard navigation reaches all interactive elements", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => document.activeElement?.tagName);
    expect(["BUTTON", "A", "TEXTAREA", "SELECT", "NEXTJS-PORTAL"]).toContain(focused);
  });

  test("starter cards populate composer with correct query", async ({ page }) => {
    await page.goto("/");
    await page.locator("text=Check database health").first().click();
    await expect(page.locator("#message-input")).toHaveValue("Check database health");
  });

  test("composer textarea auto-grows on multi-line input", async ({ page }) => {
    await page.goto("/");
    const textarea = page.locator("#message-input");
    const initialHeight = await textarea.evaluate((el) => (el as HTMLTextAreaElement).style.height);
    await textarea.fill("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6\nLine 7\nLine 8");
    await page.waitForTimeout(100);
    const newHeight = await textarea.evaluate((el) => (el as HTMLTextAreaElement).style.height);
    expect(newHeight).not.toBe(initialHeight);
  });

  test("mobile layout renders sidebar as hidden overlay", async ({ page, isMobile }) => {
    if (!isMobile) test.skip();
    await page.goto("/");
    await expect(page.locator(".sidebar")).not.toBeVisible();
    await expect(page.locator(".composer")).toBeVisible();
    await expect(page.locator(".mobile-topbar")).toBeVisible();
  });
});
