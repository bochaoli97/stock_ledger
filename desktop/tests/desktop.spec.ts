import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from "@playwright/test";
import {
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import { execFileSync } from "node:child_process";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";

const directory = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
let app: ElectronApplication, page: Page, temporary: string;
const errors: string[] = [];

test.beforeEach(async () => {
  errors.length = 0;
  temporary = await mkdtemp(path.join(os.tmpdir(), "stock-ledger-ui-"));
  const db = path.join(temporary, "test.db");
  const python =
    process.env.STOCK_LEDGER_TEST_PYTHON ||
    (process.platform === "win32" ? "python" : "python3");
  execFileSync(
    python,
    [
      "-c",
      `
from pathlib import Path
from desktop_backend import LedgerService
s=LedgerService(Path(${JSON.stringify(db)}),backup=False)
s.dispatch('settings.save',dict(live=False,language='en',text_size='Standard',finance=True))
a=s.dispatch('account.save',dict(name='Brokerage',broker='Fidelity',cash='25000',date='2026-01-01',positions=[dict(symbol='AAPL',quantity='20',price='150'),dict(symbol='MSFT',quantity='10',price='350')]))
s.dispatch('prices.save',dict(prices=dict(AAPL='185.25',MSFT='420.50')))
s.dispatch('account.save',dict(name='Roth IRA',cash='10000',date='2026-01-01'))
s.dispatch('account.select',dict(account_id=a['account_id']))
s.close()
`,
    ],
    { cwd: path.dirname(directory) },
  );
  // A temporary Python startup hook supplies offline network data on every OS.
  // The production entry point and interpreter remain exactly the same.
  await writeFile(
    path.join(temporary, "sitecustomize.py"),
    `import runpy, sys\nsys.path.insert(0, ${JSON.stringify(path.dirname(directory))})\nimport quotes\nfixture = runpy.run_path(${JSON.stringify(path.join(directory, "tests/fixture-service.py"))})\nquotes.fetch_quotes = fixture["fetch"]\nquotes.fetch_full_history = lambda symbol: fixture["fetch"]([symbol], "max", "1d")\nquotes._fetch_chart = lambda *args, **kwargs: {}\nquotes.search_symbols = fixture["search"]\n`,
    "utf8",
  );
  const environment: Record<string, string> = {
    ...(process.env as Record<string, string>),
    ELECTRON_RENDERER_URL: "",
    STOCK_LEDGER_DB: db,
    STOCK_LEDGER_PYTHON: python,
    PYTHONPATH: [temporary, process.env.PYTHONPATH]
      .filter(Boolean)
      .join(path.delimiter),
    STOCK_LEDGER_TEST_USER_DATA: path.join(temporary, "chromium-profile"),
  };
  delete environment.ELECTRON_RUN_AS_NODE;
  app = await electron.launch({
    args: [
      directory,
      ...(process.platform === "linux" ? ["--no-sandbox"] : []),
    ],
    env: environment,
    timeout: 30000,
  });
  page = await app.firstWindow();
  page.on("pageerror", (e) => errors.push(e.message));
  await expect(
    page.getByRole("button", { name: "Settings", exact: true }),
  ).toBeVisible();
});
test.afterEach(async ({}, info) => {
  if (page && info.status !== info.expectedStatus)
    await page
      .screenshot({ path: info.outputPath("failure.png"), fullPage: true })
      .catch(() => {});
  await app?.close();
  await rm(temporary, { recursive: true, force: true });
  expect(errors).toEqual([]);
});

test("real ledger: transaction validation, edit, delete and sidebar navigation", async () => {
  await expect(page.locator(".hero .number-ticker")).toHaveAttribute(
    "aria-label",
    "$32,910.00",
  );
  await page
    .getByRole("button", { name: "New transaction", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Type", { exact: true }).selectOption("DEPOSIT");
  await dialog.getByLabel("Amount", { exact: true }).fill("1234.56");
  await dialog
    .getByLabel("Note", { exact: true })
    .fill("UI integration deposit");
  await dialog.getByRole("button", { name: "Save transaction" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.locator(".hero .number-ticker")).toHaveAttribute(
    "aria-label",
    "$34,144.56",
  );
  await page.getByRole("button", { name: "Activity", exact: true }).click();
  const row = page
    .getByRole("row")
    .filter({ hasText: "UI integration deposit" });
  await row.getByRole("button", { name: "Edit transaction" }).click();
  await page
    .getByRole("dialog")
    .getByLabel("Amount", { exact: true })
    .fill("1235.56");
  await page.getByRole("button", { name: "Save transaction" }).click();
  await expect(row).toContainText("1,235.56");
  await row.getByRole("button", { name: "Delete transaction" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Delete", exact: true })
    .click();
  await expect(row).toBeHidden();
  await page.locator(".stock-row").filter({ hasText: "AAPL" }).click();
  await expect(page.locator(".hero-title")).toHaveText("AAPL");
  await expect(page.locator(".hero .number-ticker")).toHaveAttribute(
    "aria-label",
    "$185.25",
  );
  await page.getByRole("button", { name: "Back to portfolio" }).click();
  await expect(page.locator(".hero .number-ticker")).toHaveAttribute(
    "aria-label",
    "$32,910.00",
  );
});

test("real chart hover, restore and range requests stay in the renderer", async () => {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("Live prices", { exact: false }).check();
  await page.getByRole("button", { name: "Investing", exact: true }).click();
  await expect(page.locator(".price-chart")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  const chart = page.locator(".price-chart");
  await expect
    .poll(() =>
      page.evaluate(() =>
        window
          .ledger!.request<any>("chart", { range: "1D" })
          .then((d) => d.points.length),
      ),
    )
    .toBeGreaterThan(2);
  await page.getByRole("button", { name: "1W", exact: true }).click();
  await expect(chart).toHaveAttribute("aria-busy", "false");
  const rect = (await chart.boundingBox())!;
  const current = await page
    .locator(".hero .number-ticker")
    .getAttribute("aria-label");
  await page.mouse.move(rect.x + rect.width * 0.3, rect.y + rect.height * 0.5);
  await expect(page.locator(".chart-cursor")).toBeVisible();
  await expect(page.locator(".hero .number-ticker")).not.toHaveAttribute(
    "aria-label",
    current!,
  );
  const before = await page.evaluate(
    () => performance.getEntriesByType("resource").length,
  );
  for (let i = 0; i < 25; i++)
    await page.mouse.move(
      rect.x + (i / 26) * rect.width,
      rect.y + rect.height / 2,
    );
  expect(
    await page.evaluate(() => performance.getEntriesByType("resource").length),
  ).toBe(before);
  await page.mouse.move(rect.x, rect.y - 20);
  await expect(page.locator(".hero .number-ticker")).toHaveAttribute(
    "aria-label",
    current!,
  );
  await expect(page.locator(".chart-cursor")).toBeHidden();
  await page.waitForTimeout(700);
  await page.screenshot({
    path: test.info().outputPath("portfolio-dark.png"),
    fullPage: true,
  });
});

test("individual stocks show long market history before the first purchase", async () => {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("Live prices").check();
  await page.getByLabel("Language", { exact: true }).selectOption("zh");
  await page.getByRole("button", { name: "投资", exact: true }).click();
  const tabs = page.getByRole("group", { name: "投资表现" });
  await expect(tabs.getByRole("button", { name: "5年" })).toHaveCount(0);
  await page.locator(".stock-row").filter({ hasText: "AAPL" }).click();
  const chart = page.locator(".price-chart");
  for (const [name, caption, years] of [
    ["5年", "过去五年", 5],
    ["全部", "全部时间", 40],
    ["10年", "过去十年", 10],
  ] as const) {
    const tab = tabs.getByRole("button", { name, exact: true });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".hero-change")).toContainText(caption);
    await expect(chart).toHaveAttribute("aria-busy", "false");
    await chart.hover({ position: { x: 3, y: 50 } });
    const start = new Date(Date.now() - years * 365 * 86400 * 1000);
    await expect(chart.locator(".chart-cursor > span")).toContainText(
      String(start.getUTCFullYear()),
    );
  }
  await page.keyboard.press("Escape");
  await expect(tabs.getByRole("button", { name: "1天" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(tabs.getByRole("button", { name: "10年" })).toHaveCount(0);
});

test("a stock with one historical price shows a point that can be inspected", async () => {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("Live prices").check();
  await page.getByRole("button", { name: "Investing", exact: true }).click();
  await page.locator(".stock-row").filter({ hasText: "MSFT" }).click();
  await page.getByRole("button", { name: "1Y", exact: true }).click();

  const chart = page.getByRole("group", { name: "Price history / 价格走势" });
  const ticker = page.locator(".hero .number-ticker");
  await expect(chart).toContainText("Only one price point is available");
  await expect(ticker).toHaveAttribute("aria-label", "$420.50");
  await chart.press("ArrowLeft");
  await expect(chart.locator(".chart-cursor")).toBeVisible();
  await expect(ticker).toHaveAttribute("aria-label", "$419.50");

  await page.getByRole("button", { name: "1Y", exact: true }).focus();
  await expect(chart.locator(".chart-cursor")).toBeHidden();
  await chart.hover();
  await expect(chart.locator(".chart-cursor")).toBeVisible();
  await expect(ticker).toHaveAttribute("aria-label", "$419.50");
});

test("Google Drive backup authorizes in the browser and uploads a consistent SQLite file", async () => {
  await app.evaluate(({ dialog }) => {
    dialog.showOpenDialog = async () => ({ canceled: true, filePaths: [] });
  });
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const drive = page.getByRole("region", { name: "Google Drive", exact: true });
  const backup = drive.getByRole("button", { name: "Back up to Google Drive" });
  await backup.click();
  await expect(backup).toBeEnabled();
  await expect(drive).toContainText(
    "Choose a Google Cloud Desktop app OAuth JSON file",
  );

  const credentials = path.join(temporary, "client.json");
  const uploaded = path.join(temporary, "uploaded.db");
  await writeFile(
    credentials,
    JSON.stringify({
      installed: {
        client_id: "fixture.apps.googleusercontent.com",
        client_secret: "fixture-client-credential",
      },
    }),
  );
  await app.evaluate(
    ({ dialog, shell }, { credentials, uploaded }) => {
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [credentials],
      });
      const localFetch = globalThis.fetch;
      shell.openExternal = async (url) => {
        const auth = new URL(url);
        if (auth.origin !== "https://accounts.google.com")
          throw new Error("Unexpected sign-in origin");
        const callback = new URL(auth.searchParams.get("redirect_uri")!);
        callback.searchParams.set("state", auth.searchParams.get("state")!);
        callback.searchParams.set("code", "test-code");
        const response = await localFetch(callback);
        if (!response.ok) throw new Error("Loopback validation failed");
        await response.text();
      };
      let name: string;
      globalThis.fetch = async (input, options) => {
        const url = new URL(String(input));
        if (url.href === "https://oauth2.googleapis.com/token") {
          const grant = options?.body as URLSearchParams;
          if (grant.get("code") !== "test-code" || !grant.get("code_verifier"))
            throw new Error("Expected OAuth code exchange with PKCE");
          return Response.json({
            access_token: "fixture-access",
            refresh_token: "fixture-refresh",
            expires_in: 3600,
            scope: "https://www.googleapis.com/auth/drive.file",
          });
        }
        const headers = new Headers(options?.headers);
        if (
          url.origin !== "https://www.googleapis.com" ||
          headers.get("Authorization") !== "Bearer fixture-access"
        )
          throw new Error("Unexpected Google API request");
        if (url.pathname === "/drive/v3/files" && !options?.method)
          return Response.json({
            files: [
              { id: "folder", name: "Stock Ledger Backups", shared: false },
            ],
          });
        if (
          url.pathname === "/upload/drive/v3/files" &&
          options?.method === "POST"
        ) {
          const file = JSON.parse(String(options.body));
          if (file.parents?.[0] !== "folder")
            throw new Error("Unexpected Drive folder");
          name = file.name;
          return new Response(null, {
            headers: {
              Location: `${url.origin}${url.pathname}?upload_id=session`,
            },
          });
        }
        if (
          url.searchParams.get("upload_id") === "session" &&
          options?.method === "PUT"
        ) {
          const chunks = [];
          for await (const chunk of options.body as unknown as AsyncIterable<Uint8Array>)
            chunks.push(chunk);
          const fs = process.getBuiltinModule("node:fs/promises")!;
          await fs.writeFile(uploaded, Buffer.concat(chunks));
          return Response.json({ id: "backup", name }, { status: 201 });
        }
        throw new Error("Unexpected Drive request");
      };
    },
    { credentials, uploaded },
  );
  await backup.click();
  await expect(page.locator(".notice-banner")).toHaveText(
    /Google Drive backup complete · Stock Ledger Backups \/ stock_ledger_.*\.db/,
  );
  const python =
    process.env.STOCK_LEDGER_TEST_PYTHON ||
    (process.platform === "win32" ? "python" : "python3");
  const result = execFileSync(
    python,
    [
      "-c",
      "import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); print(db.execute('PRAGMA integrity_check').fetchone()[0]); print(db.execute('SELECT name FROM accounts ORDER BY id LIMIT 1').fetchone()[0])",
      uploaded,
    ],
    { encoding: "utf8" },
  );
  expect(result.replaceAll("\r\n", "\n")).toBe("ok\nBrokerage\n");
  await drive.getByRole("button", { name: "Disconnect Google Drive" }).click();
  await expect(drive).toContainText(
    "Choose a Google Cloud Desktop app OAuth JSON file",
  );
});

test("animation compositor, fractional retargeting, clipping and frame timing", async () => {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page
    .getByRole("button", { name: "Animation studio", exact: true })
    .click();
  const input = page.getByRole("textbox", { name: "Value", exact: true });
  expect(
    (await page.locator(".studio-stage .number-ticker").boundingBox())!.width,
  ).toBeGreaterThan(160);
  await input.fill("$12.34");
  await page.waitForTimeout(700);
  await input.fill("$12.39");
  await page.waitForTimeout(90);
  const continuity = await page.evaluate(() => {
    const reel = document.querySelector<HTMLElement>(
      '[data-slot="dec_2"] .ticker-reel',
    )!;
    const before = new DOMMatrix(getComputedStyle(reel).transform).m42;
    const old = document.querySelector('[data-slot="int_0"]');
    const input = document.querySelector<HTMLInputElement>(
      'input[aria-label="Value"]',
    )!;
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "$12.31");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    const after = new DOMMatrix(getComputedStyle(reel).transform).m42;
    return {
      difference: Math.abs(after - before),
      sameSlot: old === document.querySelector('[data-slot="int_0"]'),
      accelerated: reel.getAnimations().length,
    };
  });
  expect(continuity.difference).toBeLessThan(1.5);
  expect(continuity.sameSlot).toBe(true);
  expect(continuity.accelerated).toBe(1);
  await input.fill("$999.99");
  await page.waitForTimeout(700);
  await input.fill("$1,000.00");
  await page.waitForTimeout(90);
  const clipping = await page.evaluate(() => {
    const slot = document.querySelector<HTMLElement>('[data-slot="int_3"]')!;
    const unscale = slot.querySelector<HTMLElement>(".ticker-unscale")!;
    return {
      scale: new DOMMatrix(getComputedStyle(slot).transform).m11,
      inverse: new DOMMatrix(getComputedStyle(unscale).transform).m11,
    };
  });
  expect(clipping.scale).toBeGreaterThan(0);
  expect(clipping.scale).toBeLessThan(1);
  expect(clipping.scale * clipping.inverse).toBeCloseTo(1, 4);
  await page
    .getByRole("combobox", { name: "Animation preview" })
    .selectOption("Rapid retargeting");
  await page.getByRole("slider", { name: "Update interval" }).focus();
  await page.keyboard.press("Home");
  await page.getByRole("button", { name: "Run sequence" }).click();
  const frames = await page.evaluate(async () => {
    const times: number[] = [],
      start = performance.now();
    let previous = start;
    await new Promise<void>((resolve) => {
      const tick = (now: number) => {
        times.push(now - previous);
        previous = now;
        if (now - start < 1800) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });
    const samples = times.slice(1).sort((a, b) => a - b);
    return {
      samples: samples.length,
      median: samples[Math.floor(samples.length * 0.5)],
      p95: samples[Math.floor(samples.length * 0.95)],
      max: samples.at(-1),
    };
  });
  await test.info().attach("frame-timing.json", {
    body: JSON.stringify(frames, null, 2),
    contentType: "application/json",
  });
  expect(frames.samples).toBeGreaterThan(20);
  const runtime = await page.evaluate(() => window.ledger!.runtime());
  const graphics = await app.evaluate(({ app }) =>
    app.getGPUInfo(process.platform === "win32" ? "complete" : "basic"),
  );
  await writeFile(
    test.info().outputPath("frame-timing.json"),
    JSON.stringify(
      {
        ...frames,
        updateIntervalMs: 50,
        runtime,
        graphics,
      },
      null,
      2,
    ),
  );
  if (process.env.STOCK_LEDGER_REQUIRE_GPU === "1") {
    expect(
      runtime.gpu.gpu_compositing,
      "Hardware GPU compositing is required for this run",
    ).toMatch(/^enabled/);
  }
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await page.waitForTimeout(700);
  await page.screenshot({
    path: test.info().outputPath("animation-studio.png"),
  });
});

test("finance formulas, theme, language, account creation and combined view", async () => {
  await page.getByRole("button", { name: "Finance", exact: true }).click();
  await page.getByRole("button", { name: "Add month", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Month", { exact: true }).fill("2026-01");
  await dialog.getByLabel("Opening balance", { exact: true }).fill("100");
  await dialog.getByLabel("Salary", { exact: true }).fill("1250.50+1250.50");
  const comment = dialog.getByLabel("Comment", { exact: true }).first();
  await comment.fill("First line");
  await comment.press("Enter");
  await comment.pressSequentially("Second line");
  await expect(dialog).toBeVisible();
  await expect(comment).toHaveValue("First line\nSecond line");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.locator(".finance-table")).toContainText("$2,601.00");
  await page.getByRole("button", { name: "Edit month", exact: true }).click();
  await expect(
    page.getByRole("dialog").getByLabel("Comment", { exact: true }).first(),
  ).toHaveValue("First line\nSecond line");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("Dark mode", { exact: true }).uncheck();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByLabel("Language", { exact: true }).selectOption("zh");
  await expect(
    page.getByRole("heading", { name: "设置", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "新建账户", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByLabel("名称", { exact: true })
    .fill("Savings");
  await page
    .getByRole("dialog")
    .getByLabel("期初现金", { exact: true })
    .fill("500");
  await page.getByRole("button", { name: "保存账户", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await page.getByRole("combobox", { name: "账户", exact: true }).click();
  await page.getByRole("option", { name: "全部账户", exact: true }).click();
  await expect(page.locator(".hero .number-ticker")).toHaveAttribute(
    "aria-label",
    "$43,410.00",
  );
  await page.screenshot({
    path: test.info().outputPath("portfolio-light.png"),
    fullPage: true,
  });
});

test("animated amounts can be highlighted without selecting hidden reel digits", async () => {
  const amount = page.locator(".hero .number-ticker");
  await page.waitForTimeout(700);
  const box = (await amount.boundingBox())!;
  await page.mouse.move(box.x + 1, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width - 2, box.y + box.height / 2, {
    steps: 12,
  });
  await page.mouse.up();
  expect(
    await page.evaluate(() => window.getSelection()?.toString().trim()),
  ).toBe("$32,910.00");
  expect(
    await amount
      .locator(".ticker-selection")
      .evaluate((node) => getComputedStyle(node).userSelect),
  ).toBe("text");
  await page.screenshot({
    path: test.info().outputPath("amount-highlighted.png"),
  });
  await page.evaluate(() => window.getSelection()?.removeAllRanges());
});

test("account popup remains readable in both themes and supports keyboard selection", async () => {
  const account = page.getByRole("combobox", { name: "Account", exact: true });
  const checkContrast = async () => {
    await account.click();
    const option = page.getByRole("option", { name: "Brokerage", exact: true });
    await expect(option).toBeVisible();
    const contrast = await option.evaluate((node) => {
      const style = getComputedStyle(node);
      const luminance = (color: string) => {
        const rgb = color
          .match(/[\d.]+/g)!
          .slice(0, 3)
          .map(Number)
          .map((value) => {
            const n = value / 255;
            return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
          });
        return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
      };
      const fg = luminance(style.color),
        bg = luminance(style.backgroundColor);
      return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
    });
    expect(contrast).toBeGreaterThan(4.5);
  };
  await checkContrast();
  await page.screenshot({ path: test.info().outputPath("accounts-dark.png") });
  await page.getByRole("option", { name: "Roth IRA", exact: true }).click();
  await expect(page.locator(".hero .number-ticker")).toHaveAttribute(
    "aria-label",
    "$10,000.00",
  );
  await account.press("ArrowUp");
  await account.press("Enter");
  await expect(page.locator(".hero .number-ticker")).toHaveAttribute(
    "aria-label",
    "$32,910.00",
  );
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("Dark mode", { exact: true }).uncheck();
  await checkContrast();
  await page.screenshot({ path: test.info().outputPath("accounts-light.png") });
  await account.press("Escape");
  await expect(
    page.getByRole("listbox", { name: "Account", exact: true }),
  ).toBeHidden();
});

test("settings shows actual GPU mode, adapter and rendering backend", async () => {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const runtime = await page.evaluate(() => window.ledger!.runtime());
  const card = page.locator(".gpu-status-card");
  await expect(card).toHaveAttribute("data-mode", runtime.graphics.mode);
  await expect(card).toContainText(
    runtime.graphics.mode === "hardware"
      ? "Hardware acceleration enabled"
      : "Software rendering",
  );
  if (runtime.graphics.renderer)
    await expect(card).toContainText(runtime.graphics.renderer);
  for (const device of runtime.graphics.devices)
    await expect(card).toContainText(device.name);
  if (process.env.STOCK_LEDGER_REQUIRE_GPU === "1")
    await expect(card).toHaveAttribute("data-mode", "hardware");
  await page.screenshot({
    path: test.info().outputPath("graphics-status.png"),
  });
});

test("account CSV uses activity dates, validates bounds and exports through the native dialog", async () => {
  await page.evaluate(async () => {
    const state = await window.ledger!.request<{ account_id: number }>(
      "snapshot",
    );
    for (const [date, note] of [
      ["2026-02-01", "February export"],
      ["2026-03-01", "March excluded"],
    ])
      await window.ledger!.request("transaction.save", {
        account_id: state.account_id,
        date,
        type: "DEPOSIT",
        amount: "100",
        note,
      });
  });
  await page.reload();
  await page
    .getByRole("button", { name: "Export account CSV", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Time range", { exact: true })).toHaveValue(
    "ALL",
  );
  await dialog.getByLabel("Time range", { exact: true }).selectOption("CUSTOM");
  await dialog.getByLabel("From", { exact: true }).fill("2026-03-01");
  await dialog.getByLabel("To", { exact: true }).fill("2026-02-01");
  await expect(dialog.getByRole("alert")).toHaveText("Start must precede end");
  await expect(
    dialog.getByRole("button", { name: "Choose folder and export" }),
  ).toBeDisabled();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Activity", exact: true }).click();
  await page.getByLabel("All time", { exact: true }).selectOption("CUSTOM");
  await page.getByLabel("From", { exact: true }).fill("2026-02-01");
  await page.getByLabel("To", { exact: true }).fill("2026-02-28");
  await page
    .getByRole("button", { name: "Export account CSV", exact: true })
    .click();
  await expect(dialog.getByLabel("From", { exact: true })).toHaveValue(
    "2026-02-01",
  );
  await expect(dialog.getByLabel("To", { exact: true })).toHaveValue(
    "2026-02-28",
  );
  await app.evaluate(({ dialog }) => {
    dialog.showOpenDialog = async () => ({ canceled: true, filePaths: [] });
  });
  await dialog
    .getByRole("button", { name: "Choose folder and export" })
    .click();
  await expect(dialog).toBeVisible();
  const folder = path.join(temporary, "account-exports");
  await mkdir(folder);
  await app.evaluate(({ dialog }, folder) => {
    dialog.showOpenDialog = async () => ({
      canceled: false,
      filePaths: [folder],
    });
  }, folder);
  await dialog
    .getByRole("button", { name: "Choose folder and export" })
    .click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("status")).toContainText("CSV exported");
  const names = await readdir(folder);
  expect(names).toHaveLength(3);
  expect(names.every((name) => name.includes("2026-02-01_to_2026-02-28"))).toBe(
    true,
  );
  const transactions = await readFile(
    path.join(
      folder,
      names.find((name) => name.includes("_transactions_"))!,
    ),
    "utf8",
  );
  expect(transactions).toContain("February export");
  expect(transactions).not.toContain("March excluded");
  expect(transactions).not.toContain("2026-01-01");
});

test("finance CSV inherits month filters and preserves the carried opening balance", async () => {
  await page.evaluate(async () => {
    const data = await window.ledger!.request<{
      categories: { id: number; kind: string }[];
    }>("finance.snapshot");
    const category = data.categories.find(
      (category) => category.kind === "income",
    )!.id;
    await window.ledger!.request("finance.month.save", {
      month: "2026-01",
      opening: "100",
      entries: { [category]: { raw: "1000" } },
    });
    await window.ledger!.request("finance.month.save", {
      month: "2026-02",
      entries: {
        [category]: { raw: "500", comment: "Filtered finance entry" },
      },
    });
  });
  await page.getByRole("button", { name: "Finance", exact: true }).click();
  await expect(
    page.getByRole("row").filter({ hasText: "2026-02" }),
  ).toBeVisible();
  await page.getByLabel("All time", { exact: true }).selectOption("CUSTOM");
  await page.getByLabel("From", { exact: true }).fill("2026-02");
  await page.getByLabel("To", { exact: true }).fill("2026-02");
  await page
    .getByRole("button", { name: "Export finance CSV", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("From", { exact: true })).toHaveValue(
    "2026-02",
  );
  await expect(dialog.getByLabel("To", { exact: true })).toHaveAttribute(
    "type",
    "month",
  );
  const folder = path.join(temporary, "finance-exports");
  await mkdir(folder);
  await app.evaluate(({ dialog }, folder) => {
    dialog.showOpenDialog = async () => ({
      canceled: false,
      filePaths: [folder],
    });
  }, folder);
  await dialog
    .getByRole("button", { name: "Choose folder and export" })
    .click();
  await expect(dialog).toBeHidden();
  const names = await readdir(folder);
  expect(names).toHaveLength(3);
  const monthly = await readFile(
    path.join(
      folder,
      names.find((name) => name.includes("_monthly_"))!,
    ),
    "utf8",
  );
  expect(monthly).toContain("2026-02,1100.00,500.00");
  expect(monthly).not.toContain("2026-01");
});

test("settings cards support both themes and return to the originating page", async () => {
  await page.getByRole("button", { name: "Finance", exact: true }).click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.locator(".settings-card")).toHaveCount(5);
  await expect(
    page.getByRole("button", { name: "Export account CSV", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Export finance CSV", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: test.info().outputPath("settings-dark.png"),
    fullPage: true,
  });
  await page.getByLabel("Dark mode", { exact: true }).uncheck();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.screenshot({
    path: test.info().outputPath("settings-light.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Animation studio", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Back to settings", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Animation studio", exact: true })
    .click();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Back to previous page", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Finance", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("heading", { name: "Finance", exact: true }),
  ).toBeVisible();
});
