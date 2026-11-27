import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createGoogleDriveBackup, googleDriveVault } from "./cloud-backup.mjs";

const clientId = "test-client.apps.googleusercontent.com";
const disconnected = {
  configured: false,
  connected: false,
  savedSignIn: false,
};

async function fixture(t) {
  const directory = await mkdtemp(path.join(os.tmpdir(), "ledger-cloud-test-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const selectedFile = path.join(directory, "downloaded-client.json");
  const profileDirectory = path.join(directory, "profile");
  await writeFile(
    selectedFile,
    JSON.stringify({
      installed: { client_id: clientId, client_secret: "test-client-secret" },
    }),
  );
  const tokenResponse = (accessToken) => ({
    accessToken,
    refreshToken: "mock-refresh",
    expiresAt: Date.now() + 3_600_000,
  });
  const options = {
    profileDirectory,
    tempDirectory: directory,
    vault: {
      available: () => true,
      encrypt: (value) => Buffer.from(value).toString("base64"),
      decrypt: (value) => Buffer.from(value.toString(), "base64").toString(),
    },
    pickClientFile: async () => selectedFile,
    authorize: async ({ client }) => {
      assert.equal(client.clientId, clientId);
      return tokenResponse("authorized-access");
    },
    refresh: async ({ refreshToken }) => {
      assert.equal(refreshToken, "mock-refresh");
      return tokenResponse("refreshed-access");
    },
    createSnapshot: (destination) =>
      writeFile(destination, "mock SQLite snapshot"),
    upload: async ({ accessToken, snapshotPath, name }) => {
      assert.match(accessToken, /^(authorized|refreshed)-access$/);
      assert.equal(
        await readFile(snapshotPath, "utf8"),
        "mock SQLite snapshot",
      );
      return { name, folderName: "Stock Ledger Backups" };
    },
  };
  return { directory, profileDirectory, options };
}

test("first backup authorizes, one-click backups reuse authorization, and restart refreshes it", async (t) => {
  const { directory, profileDirectory, options } = await fixture(t);
  let opened = 0;
  let selected = 0;
  const first = createGoogleDriveBackup({
    ...options,
    authorize: (...args) => {
      opened++;
      return options.authorize(...args);
    },
    pickClientFile: () => {
      selected++;
      return options.pickClientFile();
    },
  });
  assert.deepEqual(await first.status(), disconnected);
  for (let count = 0; count < 2; count++) {
    const file = await first.backup();
    assert.match(file.name, /^stock_ledger_\d{4}-\d{2}-\d{2}T.*Z\.db$/);
    assert.equal(file.folderName, "Stock Ledger Backups");
  }
  assert.equal(opened, 1);
  assert.equal(selected, 1);
  assert.deepEqual(await first.status(), {
    ...disconnected,
    configured: true,
    connected: true,
    savedSignIn: true,
  });
  assert.deepEqual((await readdir(directory)).sort(), [
    "downloaded-client.json",
    "profile",
  ]);
  const session = await readFile(
    path.join(profileDirectory, "google-drive-session.bin"),
    "utf8",
  );
  assert.doesNotMatch(session, /mock-refresh|authorized-access/);
  const restarted = createGoogleDriveBackup({
    ...options,
    authorize: () => assert.fail("Authorization should be refreshed"),
  });
  assert.equal((await restarted.status()).savedSignIn, true);
  assert.match((await restarted.backup()).name, /\.db$/);
  await restarted.disconnect();
  assert.deepEqual(await restarted.status(), disconnected);
  assert.deepEqual(await readdir(profileDirectory), []);
});

test("cancel does no work, network failure cleans the snapshot, and credentials stay in memory without a vault", async (t) => {
  const { directory, profileDirectory, options } = await fixture(t);
  const canceled = createGoogleDriveBackup({
    ...options,
    pickClientFile: () => null,
    authorize: () => assert.fail("Canceled file selection"),
  });
  assert.equal(await canceled.backup(), null);
  const backup = createGoogleDriveBackup({
    ...options,
    vault: googleDriveVault(
      {
        isEncryptionAvailable: () => true,
        getSelectedStorageBackend: () => "basic_text",
        encryptString: () => assert.fail("Insecure vault must not be used"),
      },
      "linux",
    ),
    upload: () => {
      throw new Error("Mock network failure");
    },
  });
  await assert.rejects(backup.backup(), /Mock network failure/);
  assert.deepEqual(await backup.status(), {
    ...disconnected,
    configured: true,
    connected: true,
  });
  assert.deepEqual(await readdir(profileDirectory), [
    "google-drive-client.json",
  ]);
  assert.deepEqual((await readdir(directory)).sort(), [
    "downloaded-client.json",
    "profile",
  ]);
});

test("expired refresh authorization is replaced before another backup", async (t) => {
  const { options } = await fixture(t);
  await createGoogleDriveBackup(options).backup();
  let reconnected = false;
  const backup = createGoogleDriveBackup({
    ...options,
    refresh: () => {
      throw Object.assign(new Error("Mock expired consent"), {
        code: "GOOGLE_AUTH_EXPIRED",
      });
    },
    authorize: (...args) => {
      reconnected = true;
      return options.authorize(...args);
    },
    upload: (...args) => {
      assert.equal(reconnected, true);
      return options.upload(...args);
    },
  });
  assert.equal((await backup.backup()).folderName, "Stock Ledger Backups");
});
