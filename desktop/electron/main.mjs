import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import { accessSync, constants, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { PythonBridge } from "./bridge.mjs";
import { preferredDataDirectory } from "./data-path.mjs";
import { runtimeDiagnostics } from "./graphics.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const methods = new Set([
  "snapshot",
  "account.select",
  "account.save",
  "account.delete",
  "transaction.save",
  "transaction.preview",
  "transaction.delete",
  "prices.save",
  "settings.save",
  "quotes.refresh",
  "chart",
  "symbols.search",
  "finance.snapshot",
  "finance.month.save",
  "finance.month.delete",
  "finance.categories.save",
]);
let window, bridge, database;
// Keep Chromium's hardware acceleration and vsync enabled. Do not force GPU
// blocklist overrides: the actual feature status is exposed in Settings.
if (process.env.STOCK_LEDGER_DISABLE_GPU === "1")
  app.disableHardwareAcceleration();
if (process.env.STOCK_LEDGER_TEST_USER_DATA)
  app.setPath("userData", process.env.STOCK_LEDGER_TEST_USER_DATA);

function databasePath() {
  if (process.env.STOCK_LEDGER_DB)
    return path.resolve(process.env.STOCK_LEDGER_DB);
  let folder = preferredDataDirectory({
    packaged: app.isPackaged,
    repoRoot: root,
    executable: process.execPath,
  });
  try {
    mkdirSync(folder, { recursive: true });
    accessSync(folder, constants.W_OK);
  } catch {
    folder = app.getPath("userData");
    mkdirSync(folder, { recursive: true });
  }
  return path.join(folder, "stock_ledger.db");
}
function startService() {
  database = databasePath();
  if (app.isPackaged) {
    const executable = path.join(
      process.resourcesPath,
      "python",
      `stock-ledger-service${process.platform === "win32" ? ".exe" : ""}`,
    );
    if (!existsSync(executable))
      throw new Error(
        "Packaged Python service is missing. Run npm run package on the target platform.",
      );
    bridge = new PythonBridge(executable, ["--db", database]);
  } else {
    const python =
      process.env.STOCK_LEDGER_PYTHON ||
      (process.platform === "win32" ? "python" : "python3");
    bridge = new PythonBridge(
      python,
      ["-u", path.join(root, "desktop_backend.py"), "--db", database],
      {
        cwd: root,
        env: {
          ...process.env,
          PYTHONIOENCODING: "utf-8",
          PYTHONUNBUFFERED: "1",
        },
      },
    );
  }
}
function verify(event) {
  if (
    !window ||
    event.sender !== window.webContents ||
    event.senderFrame !== window.webContents.mainFrame
  )
    throw new Error("Untrusted IPC sender");
}
async function envelope(fn) {
  try {
    return { ok: true, result: await fn() };
  } catch (error) {
    return {
      ok: false,
      error: {
        message: error.message,
        code: error.code,
        details: error.details,
      },
    };
  }
}
function handle(channel, callback) {
  ipcMain.handle(channel, (event, ...args) =>
    envelope(() => {
      verify(event);
      return callback(...args);
    }),
  );
}
function registerIPC() {
  handle("ledger:request", (method, params) => {
    if (
      !methods.has(method) ||
      !params ||
      typeof params !== "object" ||
      Array.isArray(params)
    )
      throw new Error("Invalid request");
    return bridge.request(method, params);
  });
  handle("ledger:backup", async () => {
    const { canceled, filePath } = await dialog.showSaveDialog(window, {
      title: "Back up database / 备份数据库",
      defaultPath: `stock_ledger_backup_${new Date().toISOString().slice(0, 10)}.db`,
      filters: [{ name: "SQLite database", extensions: ["db"] }],
    });
    return canceled || !filePath
      ? null
      : bridge.request("backup", { path: filePath });
  });
  handle("ledger:export", async (kind, accountId) => {
    if (!["stock", "finance"].includes(kind))
      throw new Error("Invalid export type");
    const { canceled, filePaths } = await dialog.showOpenDialog(window, {
      title: "Export CSV / 导出 CSV",
      properties: ["openDirectory", "createDirectory"],
    });
    return canceled || !filePaths[0]
      ? null
      : bridge.request("export", {
          kind,
          account_id: accountId,
          folder: filePaths[0],
        });
  });
  handle("ledger:open-data", async () => {
    const error = await shell.openPath(path.dirname(database));
    if (error) throw new Error(error);
  });
  handle("ledger:runtime", () => runtimeDiagnostics(app, database));
}

app.whenReady().then(async () => {
  try {
    startService();
    registerIPC();
    window = new BrowserWindow({
      width: 1440,
      height: 960,
      minWidth: 900,
      minHeight: 640,
      backgroundColor: "#000000",
      show: false,
      autoHideMenuBar: true,
      title: "Stock Ledger",
      icon: app.isPackaged ? undefined : path.join(root, "icon.ico"),
      webPreferences: {
        preload: path.join(here, "preload.cjs"),
        contextIsolation: true,
        sandbox: true,
        nodeIntegration: false,
        webSecurity: true,
      },
    });
    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    window.webContents.on("will-navigate", (event) => event.preventDefault());
    window.webContents.session.setPermissionRequestHandler(
      (_contents, _permission, callback) => callback(false),
    );
    window.once("ready-to-show", () => window.show());
    const devURL = process.env.ELECTRON_RENDERER_URL;
    if (!app.isPackaged && devURL) {
      const url = new URL(devURL);
      if (url.origin !== "http://127.0.0.1:5173")
        throw new Error("Invalid development server URL");
      await window.loadURL(devURL);
    } else await window.loadFile(path.join(here, "../out/index.html"));
  } catch (error) {
    dialog.showErrorBox("Stock Ledger", error.message);
    app.quit();
  }
});
app.on("window-all-closed", () => app.quit());
app.on("before-quit", () => bridge?.close());
