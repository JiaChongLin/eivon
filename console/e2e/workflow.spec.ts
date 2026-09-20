import { expect, test } from "@playwright/test";
import { signInThroughUI } from "./auth";

test("setup, author, publish, branch, resume input, approve and inspect a workflow", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const setup = await signInThroughUI(page);
  // Synthetic dependencies, no external provider or API credentials.
  async function resource(kind: string, slug: string, spec: object) {
    const created = await page.request.post("/api/v1/resources", { headers: { "x-csrf-token": setup.csrf_token }, data: { kind, name: slug, slug, spec } });
    expect(created.status()).toBe(201);
    const item = await created.json();
    const published = await page.request.post(`/api/v1/resources/${item.id}/publish`, { headers: { "x-csrf-token": setup.csrf_token }, data: { revision: item.revision } });
    expect(published.status()).toBe(201);
  }
  await resource("model", "demo-model", { provider: "demo", model: "demo" });
  await resource("tool", "approval-echo", { description: "Echo after approval", entrypoint: "echo", effect: "write" });
  await page.getByRole("button", { name: "04 Workflows" }).click();
  await page.getByLabel("Name", { exact: true }).fill("Review flow");
  await page.getByLabel("Slug", { exact: true }).fill("review-flow");
  await page.getByText("Workflow input and output", { exact: true }).click();
  await page.getByRole("textbox", { name: "Input schema JSON", exact: true }).fill('{"type":"object","required":["skip","value"]}');
  await page.getByRole("textbox", { name: "Output template", exact: true }).fill("{{steps.tool_2.data}}");
  for (const type of ["Condition", "Input", "Tool", "Tool", "Prompt"]) await page.getByRole("button", { name: `+ ${type}`, exact: true }).click();
  const condition = page.getByRole("region", { name: "Step 1", exact: true });
  await condition.getByLabel("tool_1", { exact: true }).check();
  const firstTool = page.getByRole("region", { name: "Step 3", exact: true });
  await firstTool.getByLabel("Arguments JSON").fill('{"unwanted":true}');
  const keptTool = page.getByRole("region", { name: "Step 4", exact: true });
  await keptTool.getByLabel("Arguments JSON").fill('{"value":');
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("tool_2 arguments: enter valid JSON");
  await expect(keptTool.getByLabel("Arguments JSON")).toHaveValue('{"value":');
  await keptTool.getByLabel("Arguments JSON").fill('{"value":"{{input.value}}","answer":"{{steps.input_1}}"}');
  const prompt = page.getByRole("region", { name: "Step 5", exact: true });
  await prompt.getByLabel("Prompt template").fill("Summarize {{steps.tool_2.data}}");
  await page.getByRole("button", { name: "Save and publish", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Release published");
  await expect(page.getByRole("heading", { name: "Run published v1", exact: true })).toBeVisible();
  // Publishing increments the revision; an immediate subsequent save must work.
  await page.getByLabel("Description", { exact: true }).fill("Updated after publishing");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Draft saved");
  await page.getByRole("button", { name: "Review flow Published v1", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Output template", exact: true })).toHaveValue("{{steps.tool_2.data}}");
  await expect(page.getByRole("region", { name: "Step 1", exact: true }).getByLabel("Equals JSON")).toHaveValue("true");
  await expect(page.getByRole("region", { name: "Step 1", exact: true }).getByLabel("tool_1", { exact: true })).toBeChecked();
  await expect(page.getByRole("region", { name: "Step 5", exact: true }).getByLabel("Prompt template")).toHaveValue("Summarize {{steps.tool_2.data}}");
  await page.getByLabel("Run input JSON").fill('{"skip":true,"value":[3,false]}');
  const firstRunResponse = page.waitForResponse((response) => response.url().endsWith("/api/v1/runs") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Run published workflow", exact: true }).click();
  const firstRunId = (await (await firstRunResponse).json()).id;
  const inspector = page.getByRole("region", { name: "Run details" });
  await expect(inspector.getByRole("status")).toHaveText("waiting_input");
  await inspector.getByRole("textbox", { name: "Response JSON", exact: true }).fill("{}");
  await inspector.getByRole("button", { name: "Resume workflow", exact: true }).click();
  await expect(inspector.getByRole("status")).toHaveText("waiting_approval");
  await inspector.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(inspector.getByRole("status")).toHaveText("completed");
  await expect(inspector.getByTestId("run-output")).toHaveText('{"value": [3, false], "answer": {}}');
  await expect(inspector.getByText("workflow.step.skipped", { exact: true })).toBeVisible();
  // Invalid response text must not prevent cancelling a waiting run.
  await page.getByRole("button", { name: "Run published workflow", exact: true }).click();
  await expect(inspector.getByRole("status")).toHaveText("waiting_input");
  await inspector.getByRole("textbox", { name: "Response JSON", exact: true }).fill("{");
  await inspector.getByRole("button", { name: "Cancel run", exact: true }).click();
  await expect(inspector.getByRole("status")).toHaveText("cancelled");
  // Run history is a durable recovery entry point after leaving the editor.
  await page.getByRole("button", { name: "06 Run history", exact: true }).click();
  await page.getByRole("combobox", { name: "Status", exact: true }).selectOption("completed");
  await page.getByRole("button", { name: `Inspect run ${firstRunId}`, exact: true }).click();
  await expect(page.getByRole("region", { name: "Run details" }).getByRole("status")).toHaveText("completed");
  await expect(page.getByTestId("run-output")).toHaveText('{"value": [3, false], "answer": {}}');
  expect(pageErrors).toEqual([]);
});
