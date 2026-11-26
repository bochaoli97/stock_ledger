import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { PythonBridge } from "./bridge.mjs";

test("bridge transports concurrent requests and structured validation errors", async () => {
  const directory = await mkdtemp(
    path.join(os.tmpdir(), "stock-ledger-bridge-"),
  );
  const backend = fileURLToPath(
    new URL("../../desktop_backend.py", import.meta.url),
  );
  const bridge = new PythonBridge(
    process.env.STOCK_LEDGER_PYTHON ||
      (process.platform === "win32" ? "python" : "python3"),
    ["-u", backend, "--db", path.join(directory, "test.db")],
  );
  try {
    const [state, bad] = await Promise.all([
      bridge.request("snapshot"),
      bridge.request("unknown").catch((e) => e),
    ]);
    assert.deepEqual(state.accounts, []);
    assert.equal(bad.code, "METHOD_NOT_FOUND");
    const account = await bridge.request("account.save", {
      name: "IPC Test",
      cash: "12.34",
    });
    assert.equal(account.summary.total, "$12.34");
    const next = await bridge.request("snapshot", {
      account_id: account.account_id,
    });
    assert.equal(next.accounts[0].name, "IPC Test");
  } finally {
    bridge.close();
    await new Promise((resolve) => bridge.child.once("exit", resolve));
    await rm(directory, { recursive: true, force: true });
  }
});
test("startup failures reject requests instead of hanging", async () => {
  const bridge = new PythonBridge("/missing/stock-ledger-python", []);
  await assert.rejects(
    bridge.request("snapshot"),
    /Cannot start Python service/,
  );
  bridge.close();
});
test("timeouts release pending requests and shutdown rejects new work", async () => {
  const bridge = new PythonBridge(process.execPath, [
    "-e",
    "process.stdin.resume()",
  ]);
  await assert.rejects(bridge.request("never-respond", {}, 25), /timed out/);
  bridge.close();
  await assert.rejects(bridge.request("snapshot"), /closed/);
  await new Promise((resolve) => bridge.child.once("exit", resolve));
});
