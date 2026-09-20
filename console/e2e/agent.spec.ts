import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { signInThroughUI } from "./auth";

test("configure an Agent in the UI, approve file creation, continue and recover a conversation", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await signInThroughUI(page);
  await page.getByRole("button", { name: "03 Resources", exact: true }).click();
  const creator = page.getByRole("dialog", { name: "Create resource" });
  const editor = page.getByRole("dialog", { name: "Edit resource" });
  async function startResource(type: string, name: string, slug: string) {
    await page.getByRole("button", { name: "+ New resource", exact: true }).click();
    await creator.getByRole("combobox", { name: "Type", exact: true }).selectOption(type);
    await creator.getByRole("textbox", { name: "Name", exact: true }).fill(name);
    await creator.getByRole("textbox", { name: "Slug", exact: true }).fill(slug);
  }
  async function openResource(name: string) {
    await page.getByRole("button").filter({ has: page.getByRole("heading", { name, exact: true }) }).click();
  }
  async function publish(name: string) {
    await openResource(name);
    await editor.getByRole("button", { name: "Publish release", exact: true }).click();
    await expect(editor).not.toBeVisible();
  }
  await startResource("model", "Chat model", "chat-model");
  await creator.getByRole("combobox", { name: "Provider", exact: true }).selectOption("openai_compatible");
  await creator.getByRole("textbox", { name: "Model", exact: true }).fill("browser-fixture");
  await creator.getByRole("textbox", { name: "Base URL", exact: true }).fill("https://model.example.test/v1");
  await creator.getByRole("button", { name: "Create draft", exact: true }).click();
  await publish("Chat model");
  await startResource("tool", "Report exporter", "report-exporter");
  await creator.getByRole("button", { name: "Create draft", exact: true }).click();
  await openResource("Report exporter");
  await editor.getByRole("textbox", { name: "Draft JSON", exact: true }).fill(JSON.stringify({ description: "Create a report file", adapter: "builtin", entrypoint: "export_text", effect: "write" }));
  await editor.getByRole("button", { name: "Save draft", exact: true }).click();
  await publish("Report exporter");
  const resources = (await (await page.request.get("/api/v1/resources?kind=tool")).json()).items;
  const tool = resources.find((item: { slug: string }) => item.slug === "report-exporter");
  await startResource("agent", "Report assistant", "report-assistant");
  await creator.getByRole("combobox", { name: "Published model", exact: true }).selectOption({ label: "Chat model · v1" });
  await creator.getByRole("button", { name: "Create draft", exact: true }).click();
  await openResource("Report assistant");
  const spec = JSON.parse(await editor.getByRole("textbox", { name: "Draft JSON", exact: true }).inputValue());
  spec.tool_refs = [{ id: tool.id, version: 1 }];
  await editor.getByRole("textbox", { name: "Draft JSON", exact: true }).fill(JSON.stringify(spec));
  await editor.getByRole("button", { name: "Save draft", exact: true }).click();
  await publish("Report assistant");

  await page.getByRole("button", { name: "05 Playground", exact: true }).click();
  await page.getByRole("combobox", { name: "Agent", exact: true }).selectOption({ label: "Report assistant · v1" });
  await page.getByRole("textbox", { name: "Message", exact: true }).fill("Create a report");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  const inspector = page.getByRole("region", { name: "Run details" });
  await expect(inspector.getByRole("status")).toHaveText("waiting_approval");
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeDisabled();
  await inspector.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(inspector.getByRole("status")).toHaveText("completed");
  const downloadPromise = page.waitForEvent("download");
  await inspector.getByRole("link", { name: "报告.md", exact: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("报告.md");
  expect(await readFile((await download.path())!, "utf8")).toBe("Browser acceptance report");
  await expect(page.getByRole("log", { name: "Conversation messages" })).toContainText("[Test fixture] Turn 1: Create a report");
  await inspector.getByText(/^Execution timeline ·/).click();
  await page.screenshot({ path: testInfo.outputPath("agent-conversation.png"), fullPage: true });
  await page.getByRole("textbox", { name: "Message", exact: true }).fill("Continue from that report");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(inspector.getByTestId("run-output")).toHaveText("[Test fixture] Turn 2: Continue from that report");
  // A new page instance reads saved history; it never replays a completed tool.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "05 Playground", exact: true }).click();
  await page.getByRole("navigation", { name: "Saved conversations" }).getByRole("button", { name: "Create a report Saved", exact: true }).click();
  await expect(page.getByRole("log", { name: "Conversation messages" })).toContainText("[Test fixture] Turn 2: Continue from that report");
  await page.getByRole("textbox", { name: "Message", exact: true }).fill("Hold for cancellation");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(inspector.getByRole("status")).toHaveText("running");
  await inspector.getByRole("button", { name: "Cancel run", exact: true }).click();
  await expect(inspector.getByRole("status")).toHaveText("cancelled");
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeEnabled();
  expect(errors).toEqual([]);
});
