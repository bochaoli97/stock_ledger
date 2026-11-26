import test from "node:test";
import assert from "node:assert/strict";
import { preferredDataDirectory } from "./data-path.mjs";

test("development shares the existing repository database", () => {
  assert.equal(
    preferredDataDirectory({
      packaged: false,
      repoRoot: "/project",
      executable: "/tmp/electron",
      environment: {},
      platform: "linux",
    }),
    "/project/data",
  );
});
test("Windows portable data belongs beside the original exe, not its temporary runtime", () => {
  assert.equal(
    preferredDataDirectory({
      packaged: true,
      repoRoot: "C:\\unused",
      executable: "C:\\Temp\\extract\\Stock Ledger.exe",
      environment: { PORTABLE_EXECUTABLE_DIR: "D:\\Investing" },
      platform: "win32",
    }),
    "D:\\Investing\\data",
  );
});
test("AppImage data belongs beside the original image, not its read-only mount", () => {
  assert.equal(
    preferredDataDirectory({
      packaged: true,
      repoRoot: "/unused",
      executable: "/tmp/.mount_ledger/stock-ledger",
      environment: { APPIMAGE: "/home/user/StockLedger.AppImage" },
      platform: "linux",
    }),
    "/home/user/data",
  );
});
