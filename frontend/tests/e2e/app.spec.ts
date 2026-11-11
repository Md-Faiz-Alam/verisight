import { expect, test, type Page, type Request, type Route } from "@playwright/test";

const DATASET = {
  dataset_id: "d1",
  files: [{ name: "orders.csv", size_bytes: 120 }],
  expires_in_seconds: 3600,
  profile: {
    schema: {
      tables: [
        {
          relation_name: "orders",
          row_count: 3,
          column_count: 2,
          columns: [
            { name: "region", logical_type: "string" },
            { name: "amount", logical_type: "float" },
          ],
        },
      ],
    },
    profiles: { tables: [{ relation_name: "orders", columns: [] }] },
    quality_findings: [],
  },
};

const DASHBOARD = {
  relation: "orders",
  relations: [{ name: "orders", rows: 3 }],
  domain: { key: "sales", label: "Sales", focus: "Revenue and orders", confidence: "high", matched: ["amount"] },
  filters: [],
  excluded_totals: [],
  kpis: [{ label: "Total amount", value: 350, sql: "SELECT SUM(amount) FROM orders" }],
  trend: null,
  breakdowns: [],
  histograms: [],
  insights: [],
  suggestions: ["What is the total amount?"],
  time: null,
  links: [],
};

const SQL = "SELECT 11.518049 AS high, 9.926478 AS low, 1.591571 AS difference";

function answer(level: string, outcome: "verified" | "unverified", value: string | null) {
  return {
    outcome,
    status: value === null ? "incomplete" : "complete",
    answer: value === null ? "No number could be checked." : `The answer is ${value}.`,
    claims: value === null ? [] : [{ claim: { operation: "value", expected: value }, verification: { status: "supported", actual: value } }],
    steps: [{ question: "q", sql: SQL, columns: ["high", "low", "difference"], rows: [[11.518049, 9.926478, value ?? 0]] }],
    cross_check: { status: "agreed", sql: "SELECT 1.591571 AS cross_check_answer", independent_value: value },
    trust: {
      level,
      checks: [
        { name: "number_matches_sql", status: value === null ? "failed" : "passed", detail: "d" },
        { name: "sql_audit", status: level === "needs_review" ? "failed" : "passed", detail: "d" },
      ],
    },
    failure: null,
    model_calls: [{}, {}, {}],
    elapsed_seconds: 4.2,
  };
}

type Reply = { status?: number; json?: unknown; abort?: boolean };

async function stub(page: Page, ask: (body: any, index: number) => Reply, upload?: Reply) {
  const asked: any[] = [];
  const removed: string[] = [];
  await page.route("**/api/**", async (route: Route, request: Request) => {
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (path === "/api/config") return route.fulfill({ json: { server_key: false, max_upload_mb: 20 } });
    if (path === "/api/datasets" && method === "POST") {
      return route.fulfill({ status: upload?.status ?? 201, json: upload?.json ?? DATASET });
    }
    if (path.endsWith("/dashboard")) return route.fulfill({ json: DASHBOARD });
    if (path.endsWith("/ask")) {
      const body = request.postDataJSON();
      asked.push(body);
      const reply = ask(body, asked.length - 1);
      if (reply.abort) return route.abort();
      return route.fulfill({ status: reply.status ?? 200, json: reply.json });
    }
    if (method === "DELETE") {
      removed.push(path);
      return route.fulfill({ status: 204, body: "" });
    }
    return route.fulfill({ status: 404, json: { code: "not_found", message: "Not found." } });
  });
  return { asked, removed };
}

async function openWorkspace(page: Page) {
  await page.goto("/static/");
  await page.locator("input[type=file]").setInputFiles({
    name: "orders.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("region,amount\nEast,100\n"),
  });
  await expect(page.getByRole("heading", { name: "Sales" })).toBeVisible();
}

async function ask(page: Page, question: string) {
  await page.getByRole("navigation", { name: "Views" }).getByRole("button", { name: "Ask" }).click();
  await page.getByLabel("Your question").fill(question);
  await page.getByLabel("Your question").press("Enter");
}

async function noSidewaysScroll(page: Page) {
  const width = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(width).toBeLessThanOrEqual(0);
}

test("a verified answer shows the exact number and its evidence", async ({ page }) => {
  await stub(page, () => ({ json: answer("verified", "verified", "1234567.891") }));
  await openWorkspace(page);
  await ask(page, "How much?");

  await expect(page.locator(".answer-num")).toHaveText("1,234,567.891");
  await expect(page.locator(".turn .badge")).toHaveText(/Verified/);
  const evidence = page.getByRole("complementary", { name: "Evidence for the selected answer" });
  await expect(evidence.getByText("SELECT 1.591571 AS cross_check_answer")).toBeVisible();
  await expect(evidence.getByText("3 model calls", { exact: false })).toBeVisible();
  await noSidewaysScroll(page);
});

test("a long number is never rounded", async ({ page }) => {
  await stub(page, () => ({ json: answer("verified", "verified", "12345678901234567.123456") }));
  await openWorkspace(page);
  await ask(page, "How much?");

  await expect(page.locator(".answer-num")).toHaveText("12,345,678,901,234,567.123456");
});

test("the cited cell is the one that holds the answer", async ({ page }) => {
  await stub(page, () => ({ json: answer("verified", "verified", "1.591571") }));
  await openWorkspace(page);
  await ask(page, "What is the gap?");

  await expect(page.locator("td.cited")).toHaveText("1.591571");
});

test("the cited cell is found when the answer is not the last column", async ({ page }) => {
  const reply = answer("verified", "verified", "24.665261");
  reply.steps = [
    { question: "q", sql: "SELECT 1", columns: ["difference", "older", "younger"], rows: [[24.665261, 46.973463, 22.308202]] },
  ];
  await stub(page, () => ({ json: reply }));
  await openWorkspace(page);
  await ask(page, "What is the gap?");

  await expect(page.locator("td.cited")).toHaveText("24.665261");
});

test("no cell is cited when the answer appears in none", async ({ page }) => {
  const reply = answer("verified", "verified", "350");
  reply.steps = [{ question: "q", sql: "SELECT 1", columns: ["a", "b"], rows: [[1, 2]] }];
  await stub(page, () => ({ json: reply }));
  await openWorkspace(page);
  await ask(page, "How much?");

  await expect(page.locator(".answer-num")).toHaveText("350");
  await expect(page.locator("td.cited")).toHaveCount(0);
});

for (const [level, label] of [
  ["number_matched", "Number matches SQL only"],
  ["needs_review", "Needs review"],
] as const) {
  test(`an answer that is ${level} shows no headline number`, async ({ page }) => {
    await stub(page, () => ({ json: answer(level, "unverified", "350") }));
    await openWorkspace(page);
    await ask(page, "How much?");

    await expect(page.locator(".turn .badge")).toHaveText(new RegExp(label));
    await expect(page.locator(".answer-num")).toHaveCount(0);
  });
}

test("an answer with no checked number says so", async ({ page }) => {
  await stub(page, () => ({ json: answer("not_verified", "unverified", null) }));
  await openWorkspace(page);
  await ask(page, "How much?");

  await expect(page.locator(".answer-num")).toHaveCount(0);
  await expect(page.locator(".notice.warn")).toContainText("does not show one");
});

test("an explained refusal is not called a failure", async ({ page }) => {
  const refusal = {
    ...answer("not_verified", "unverified", null),
    status: "complete",
    answer: "The file has no year information, so the total for 2008 cannot be found.",
  };
  await stub(page, () => ({ json: refusal }));
  await openWorkspace(page);
  await ask(page, "What was the total in 2008?");

  await expect(page.locator(".answer-num")).toHaveCount(0);
  await expect(page.locator(".notice.warn")).toHaveText("No number was given. The answer above explains why.");
});

test("an answer about something the data does not hold shows no number", async ({ page }) => {
  const hidden = {
    ...answer("not_verified", "unverified", "8.847"),
    answer: "No number is shown. The question asks for money, but acidity does not hold money amounts.",
    failure: { kind: "measure_not_in_data" },
  };
  await stub(page, () => ({ json: hidden }));
  await openWorkspace(page);
  await ask(page, "What is the average price in euros?");

  await expect(page.locator(".answer-num")).toHaveCount(0);
  await expect(page.locator(".turn")).not.toContainText("8.847");
  await expect(page.locator(".notice.warn")).toContainText("does not appear to hold what was asked");
});

test("an answer computed without AI shows its number and no model calls", async ({ page }) => {
  const direct = { ...answer("computed", "verified", "350"), model_calls: [], cross_check: null };
  await stub(page, () => ({ json: direct }));
  await openWorkspace(page);
  await ask(page, "What is the total amount?");

  await expect(page.locator(".answer-num")).toHaveText("350");
  await expect(page.locator(".turn .badge")).toHaveText(/Computed without AI/);
  await expect(page.getByText("no AI used", { exact: false })).toBeVisible();
});

test("consent is asked for before AI is used", async ({ page }) => {
  const calls = await stub(page, (body) =>
    body.consent
      ? { json: answer("verified", "verified", "350") }
      : { status: 400, json: { code: "consent_required", message: "Confirm first." } },
  );
  await openWorkspace(page);
  await ask(page, "How much?");
  await page.getByRole("button", { name: "Allow and ask" }).click();

  await expect(page.locator(".answer-num")).toHaveText("350");
  expect(calls.asked.map((body) => body.consent)).toEqual([false, true]);
});

test("a busy server and a lost connection are explained", async ({ page }) => {
  await stub(page, (_, index) =>
    index === 0 ? { status: 503, json: { code: "busy", message: "VeriSight is answering other questions." } } : { abort: true },
  );
  await openWorkspace(page);
  await ask(page, "First?");
  await expect(page.locator(".notice.bad").first()).toHaveText("VeriSight is answering other questions.");
  await page.getByLabel("Your question").fill("Second?");
  await page.getByLabel("Your question").press("Enter");

  await expect(page.locator(".notice.bad").nth(1)).toContainText("Could not reach the VeriSight server");
});

test("a rejected upload explains why", async ({ page }) => {
  await stub(page, () => ({}), {
    status: 415,
    json: { code: "unsupported_file_type", message: "notes.pdf: use a CSV, TSV, JSON, JSONL, XLSX or XLS file." },
  });
  await page.goto("/static/");
  await page.locator("input[type=file]").setInputFiles({ name: "notes.pdf", mimeType: "application/pdf", buffer: Buffer.from("x") });

  await expect(page.getByRole("alert")).toContainText("use a CSV");
  await noSidewaysScroll(page);
});

test("a question with two meanings offers each one", async ({ page }) => {
  const calls = await stub(page, (_, index) =>
    index === 0
      ? { json: { outcome: "clarify", status: "needs_clarification", answer: "Which column?", options: ["Use region", "Use city"] } }
      : { json: answer("computed", "verified", "2") },
  );
  await openWorkspace(page);
  await ask(page, "How many in East?");
  await page.getByRole("button", { name: "Use city" }).click();

  await expect(page.locator(".answer-num")).toHaveText("2");
  expect(calls.asked[1].question).toBe("Use city");
});

test("the keyboard reaches every view and sends questions", async ({ page }) => {
  const calls = await stub(page, () => ({ json: answer("verified", "verified", "350") }));
  await openWorkspace(page);
  await page.keyboard.press("Control+k");
  const search = page.getByLabel("Search commands");
  await expect(search).toBeFocused();
  await search.fill("Go to Quality");
  await search.press("Enter");
  await expect(page.getByRole("heading", { name: "Quality" })).toBeVisible();

  await page.keyboard.press("Control+k");
  await page.getByLabel("Search commands").press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.getByRole("navigation", { name: "Views" }).getByRole("button", { name: "Ask" }).focus();
  await page.keyboard.press("Enter");
  const box = page.getByLabel("Your question");
  await box.fill("line one");
  await box.press("Shift+Enter");
  await box.press("Enter");

  await expect.poll(() => calls.asked.length).toBe(1);
  expect(calls.asked[0].question).toBe("line one");
});

test("removing the data returns to the start and deletes the upload", async ({ page }) => {
  const calls = await stub(page, () => ({}));
  await openWorkspace(page);
  await page.keyboard.press("Control+k");
  await page.getByLabel("Search commands").fill("Remove data");
  await page.getByLabel("Search commands").press("Enter");

  await expect(page.getByRole("button", { name: "Open the sample workspace" })).toBeVisible();
  expect(calls.removed).toEqual(["/api/datasets/d1"]);
});

test("one visible button removes the data at every screen size", async ({ page }) => {
  const calls = await stub(page, () => ({}));
  await openWorkspace(page);
  const remove = page.locator('button[aria-label="Remove data"]:visible');
  await expect(remove).toHaveCount(1);
  await remove.click();

  await expect(page.getByRole("button", { name: "Open the sample workspace" })).toBeVisible();
  expect(calls.removed).toEqual(["/api/datasets/d1"]);
});

test("one visible button switches the theme at every screen size", async ({ page }) => {
  await stub(page, () => ({}));
  await openWorkspace(page);
  const before = await page.evaluate(() => document.documentElement.dataset.theme ?? "");
  const toggle = page.locator('button[aria-label="Switch colour theme"]:visible');
  await expect(toggle).toHaveCount(1);
  await toggle.click();

  const after = await page.evaluate(() => document.documentElement.dataset.theme);
  expect(after).not.toBe(before);
  expect(["light", "dark"]).toContain(after);
});

test("every view fits the screen without sideways scrolling", async ({ page }) => {
  await stub(page, () => ({ json: answer("verified", "verified", "1234567.891") }));
  await page.goto("/static/");
  await noSidewaysScroll(page);
  await openWorkspace(page);
  await noSidewaysScroll(page);
  await ask(page, "How much?");
  await expect(page.locator(".answer-num")).toBeVisible();
  await noSidewaysScroll(page);
});
