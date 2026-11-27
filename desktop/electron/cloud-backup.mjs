import { randomUUID } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  readFile,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { uploadGoogleDriveBackup } from "./google-drive.mjs";
import {
  authorizeGoogle,
  parseGoogleClient,
  refreshGoogle,
} from "./google-oauth.mjs";

const CLIENT_FILE = "google-drive-client.json";
const SESSION_FILE = "google-drive-session.bin";
const MAX_CLIENT_BYTES = 64 * 1024;

export function googleDriveVault(safeStorage, platform = process.platform) {
  if (platform === "linux") {
    return {
      available: () =>
        safeStorage.isEncryptionAvailable() &&
        !["basic_text", "unknown"].includes(
          safeStorage.getSelectedStorageBackend(),
        ),
      encrypt: (value) => safeStorage.encryptString(value),
      decrypt: (value) => safeStorage.decryptString(value),
    };
  }
  return {
    available: () => safeStorage.isAsyncEncryptionAvailable(),
    encrypt: (value) => safeStorage.encryptStringAsync(value),
    decrypt: async (value) =>
      (await safeStorage.decryptStringAsync(value)).result,
  };
}

async function writePrivateFile(file, data) {
  const staging = `${file}.${randomUUID()}.tmp`;
  await mkdir(path.dirname(file), { recursive: true, mode: 0o700 });
  try {
    await writeFile(staging, data, { flag: "wx", mode: 0o600 });
    await rename(staging, file);
  } finally {
    await rm(staging, { force: true });
  }
}

export function createGoogleDriveBackup({
  profileDirectory,
  tempDirectory,
  vault,
  pickClientFile,
  openExternal,
  createSnapshot,
  authorize = authorizeGoogle,
  refresh = refreshGoogle,
  upload = uploadGoogleDriveBackup,
}) {
  const clientFile = path.join(profileDirectory, CLIENT_FILE);
  const sessionFile = path.join(profileDirectory, SESSION_FILE);
  let client, tokens, loading;
  let busy = false;
  let savedSignIn = false;

  async function load() {
    try {
      client = parseGoogleClient(await readFile(clientFile, "utf8"));
    } catch {
      return;
    }
    try {
      if (!(await vault.available())) return;
      const encrypted = await readFile(sessionFile);
      const session = JSON.parse(await vault.decrypt(encrypted));
      if (
        session.clientId === client.clientId &&
        typeof session.refreshToken === "string" &&
        session.refreshToken
      ) {
        tokens = { refreshToken: session.refreshToken, expiresAt: 0 };
        savedSignIn = true;
      }
    } catch {
      // A session from a different OS login or a locked credential store requires sign-in again.
    }
  }

  async function storeTokens(next) {
    tokens = next;
    savedSignIn = false;
    try {
      if (!(await vault.available())) return;
      const session = JSON.stringify({
        clientId: client.clientId,
        refreshToken: next.refreshToken,
      });
      await writePrivateFile(sessionFile, await vault.encrypt(session));
      savedSignIn = true;
    } catch {
      // The current session can still be used with an unavailable credential store.
    }
  }

  async function clearSession() {
    tokens = undefined;
    savedSignIn = false;
    try {
      await rm(sessionFile, { force: true });
    } catch {
      throw new Error("Could not reset Google Drive setup.");
    }
  }

  async function loadClient() {
    const selected = await pickClientFile();
    if (!selected) return null;
    let contents;
    try {
      const info = await stat(selected);
      if (!info.isFile() || info.size > MAX_CLIENT_BYTES)
        throw new Error("Invalid credential file");
      contents = await readFile(selected, "utf8");
    } catch {
      throw new Error("Could not read the Google OAuth client file.");
    }
    const parsed = parseGoogleClient(contents);
    try {
      await clearSession();
      // Desktop OAuth clients are public. Only the user refresh token requires the OS vault.
      await writePrivateFile(
        clientFile,
        JSON.stringify({
          installed: {
            client_id: parsed.clientId,
            client_secret: parsed.clientSecret,
          },
        }),
      );
    } catch {
      throw new Error("Could not save Google Drive setup.");
    }
    return parsed;
  }

  async function accessToken() {
    if (tokens && tokens.expiresAt > Date.now() + 60_000)
      return tokens.accessToken;
    if (tokens) {
      try {
        const next = await refresh({
          client,
          refreshToken: tokens.refreshToken,
        });
        if (next.refreshToken !== tokens.refreshToken || !savedSignIn)
          await storeTokens(next);
        else tokens = next;
        return next.accessToken;
      } catch (error) {
        if (error.code !== "GOOGLE_AUTH_EXPIRED") throw error;
        await clearSession();
      }
    }
    await storeTokens(await authorize({ client, openExternal }));
    return tokens.accessToken;
  }

  async function exclusive(operation) {
    if (busy)
      throw new Error("A Google Drive operation is already in progress.");
    busy = true;
    try {
      await (loading ??= load());
      return await operation();
    } finally {
      busy = false;
    }
  }

  return {
    async status() {
      await (loading ??= load());
      return {
        configured: Boolean(client),
        connected: Boolean(tokens),
        savedSignIn,
      };
    },
    backup() {
      return exclusive(async () => {
        if (!client) client = (await loadClient()) ?? undefined;
        if (!client) return null;
        const token = await accessToken();
        const stamp = new Date().toISOString().replaceAll(":", "-");
        const name = `stock_ledger_${stamp}.db`;
        let folder, snapshotPath;
        try {
          try {
            folder = await mkdtemp(
              path.join(tempDirectory, "stock-ledger-drive-"),
            );
            snapshotPath = path.join(folder, "stock_ledger.db");
            await createSnapshot(snapshotPath);
          } catch {
            throw new Error("Could not create the local database backup.");
          }
          return await upload({ accessToken: token, snapshotPath, name });
        } catch (error) {
          if (error.code === "GOOGLE_AUTH_EXPIRED") await clearSession();
          throw error;
        } finally {
          if (folder) {
            try {
              await rm(folder, { recursive: true, force: true, maxRetries: 3 });
            } catch {
              throw new Error(
                "Could not remove the temporary database backup.",
              );
            }
          }
        }
      });
    },
    disconnect() {
      return exclusive(async () => {
        try {
          await clearSession();
          await rm(clientFile, { force: true });
          client = undefined;
        } catch {
          throw new Error("Could not reset Google Drive setup.");
        }
      });
    },
  };
}
