import { expect } from "@playwright/test";
import type { Page } from "@playwright/test";

export async function signInThroughUI(page: Page) {
  const state = await (await page.request.get("/api/v1/setup")).json();
  await page.goto("/");
  if (!state.initialized) {
    await page.getByLabel("Setup token").fill("eivon-browser-test");
    await page.getByLabel("Your name").fill("Framework tester");
  }
  await page.getByLabel("Email", { exact: true }).fill("browser@example.test");
  await page.getByLabel("Password", { exact: true }).fill("browser-test-password");
  await page.getByRole("button", { name: state.initialized ? "Sign in" : "Initialize Eivon", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
  return (await page.request.get("/api/v1/auth/me")).json();
}
