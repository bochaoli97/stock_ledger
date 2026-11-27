const { contextBridge, ipcRenderer } = require("electron");
async function invoke(channel, ...args) {
  const response = await ipcRenderer.invoke(channel, ...args);
  if (!response.ok)
    throw Object.assign(new Error(response.error.message), response.error);
  return response.result;
}
contextBridge.exposeInMainWorld("ledger", {
  request: (method, params = {}) => invoke("ledger:request", method, params),
  backup: () => invoke("ledger:backup"),
  googleDriveStatus: () => invoke("ledger:google-drive-status"),
  googleDriveBackup: () => invoke("ledger:google-drive-backup"),
  googleDriveDisconnect: () => invoke("ledger:google-drive-disconnect"),
  exportCsv: (kind, accountId, range = {}) =>
    invoke("ledger:export", kind, accountId, range),
  openDataFolder: () => invoke("ledger:open-data"),
  runtime: () => invoke("ledger:runtime"),
});
