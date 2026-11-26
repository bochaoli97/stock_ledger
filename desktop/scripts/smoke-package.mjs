import { _electron as electron } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";

const defaults = {
  linux: "release/linux-unpacked/stock-ledger-desktop",
  win32: "release/win-unpacked/Stock Ledger.exe",
  darwin: "release/mac/Stock Ledger.app/Contents/MacOS/Stock Ledger",
};
const executable = path.resolve(process.argv[2] ?? defaults[process.platform]);
const temporary = await mkdtemp(
  path.join(os.tmpdir(), "stock-ledger-package-"),
);
const environment = {
  ...process.env,
  STOCK_LEDGER_DB: path.join(temporary, "test.db"),
  STOCK_LEDGER_TEST_USER_DATA: path.join(temporary, "profile"),
  STOCK_LEDGER_PYTHON: "/not-an-installed-python",
  ELECTRON_RENDERER_URL: "",
};
delete environment.ELECTRON_RUN_AS_NODE;
let application;
try {
  application = await electron.launch({
    executablePath: executable,
    args: process.platform === "linux" ? ["--no-sandbox"] : [],
    env: environment,
  });
  const page = await application.firstWindow();
  await page.waitForFunction(() => !!window.ledger);
  assert.equal(await application.evaluate(({ app }) => app.isPackaged), true);
  const state = await page.evaluate(() =>
    window.ledger.request("account.save", { name: "打包验证", cash: "42.34" }),
  );
  assert.equal(state.summary.total, "$42.34");
  await page.reload();
  await page.locator('.hero .number-ticker[aria-label="$42.34"]').waitFor();
  const runtime = await page.evaluate(() => window.ledger.runtime());
  const graphics = await application.evaluate(({ app }) =>
    app.getGPUInfo(process.platform === "win32" ? "complete" : "basic"),
  );
  const hardwareAcceleration = await application.evaluate(({ app }) =>
    app.isHardwareAccelerationEnabled(),
  );
  await mkdir("test-results", { recursive: true });
  await writeFile(
    "test-results/packaged-gpu.json",
    JSON.stringify({ runtime, graphics, hardwareAcceleration }, null, 2),
  );
  if (process.env.STOCK_LEDGER_REQUIRE_GPU === "1") {
    assert.match(runtime.gpu.gpu_compositing, /^enabled/);
    assert.equal(hardwareAcceleration, true);
    assert.doesNotMatch(
      graphics.auxAttributes?.glRenderer ?? "",
      /SwiftShader|llvmpipe|software/i,
    );
  }
  console.log(
    "Packaged application passed: bundled Python, UTF-8, SQLite, renderer, $42.34.",
  );
  console.log(
    JSON.stringify(
      {
        hardwareAcceleration,
        compositing: runtime.gpu.gpu_compositing,
        renderer: graphics.auxAttributes?.glRenderer,
        devices: graphics.gpuDevice?.filter((device) => device.active),
      },
      null,
      2,
    ),
  );
} finally {
  await application?.close();
  await rm(temporary, { recursive: true, force: true });
}
