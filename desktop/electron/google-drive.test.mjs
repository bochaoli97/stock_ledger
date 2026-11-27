import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { uploadGoogleDriveBackup } from "./google-drive.mjs";

const session =
  "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=upload-test";
const name = "stock_ledger_backup_2026-11-26.db";
const accessToken = "test-only-access-token";

async function backupFixture(t, bytes) {
  const directory = await mkdtemp(
    path.join(os.tmpdir(), "stock-ledger-drive-"),
  );
  t.after(() => rm(directory, { recursive: true, force: true }));
  const snapshotPath = path.join(directory, "snapshot.db");
  await writeFile(snapshotPath, bytes);
  return { accessToken, name, snapshotPath };
}

async function readBytes(stream) {
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  return Buffer.concat(chunks);
}

test("creates a backup folder and streams a database larger than 5 MB", async (t) => {
  const bytes = Buffer.alloc(6 * 1024 * 1024, 0xc4);
  bytes.write("SQLite format 3\0");
  const backup = await backupFixture(t, bytes);
  const fetchSteps = [
    (url) => {
      assert.equal(url.pathname, "/drive/v3/files");
      const q = url.searchParams.get("q");
      assert.match(q, /'me' in owners/);
      assert.match(q, /trashed = false/);
      assert.match(
        q,
        /appProperties has \{ key='stockLedgerBackupFolder' and value='1' \}/,
      );
      return Response.json({
        files: [{ id: "shared", name: "Shared backup", shared: true }],
        nextPageToken: "more",
      });
    },
    (url) => {
      assert.equal(url.searchParams.get("pageToken"), "more");
      return Response.json({ files: [] });
    },
    (url, request) => {
      assert.equal(url.pathname, "/drive/v3/files");
      assert.equal(url.searchParams.get("ignoreDefaultVisibility"), "true");
      assert.equal(request.method, "POST");
      assert.deepEqual(JSON.parse(request.body), {
        name: "Stock Ledger Backups",
        mimeType: "application/vnd.google-apps.folder",
        appProperties: { stockLedgerBackupFolder: "1" },
      });
      return Response.json({
        id: "backup-dir",
        name: "Stock Ledger Backups",
        shared: false,
      });
    },
    (url, request) => {
      assert.equal(url.pathname, "/upload/drive/v3/files");
      assert.equal(url.searchParams.get("uploadType"), "resumable");
      assert.equal(url.searchParams.get("ignoreDefaultVisibility"), "true");
      assert.equal(request.method, "POST");
      assert.equal(
        request.headers["X-Upload-Content-Length"],
        String(bytes.length),
      );
      assert.deepEqual(JSON.parse(request.body), {
        name,
        mimeType: "application/vnd.sqlite3",
        parents: ["backup-dir"],
      });
      return new Response(null, { headers: { Location: session } });
    },
    async (url, request) => {
      assert.equal(url.toString(), session);
      assert.equal(request.method, "PUT");
      assert.equal(request.duplex, "half");
      assert.equal(request.headers["Content-Length"], String(bytes.length));
      assert.deepEqual(await readBytes(request.body), bytes);
      return Response.json({ id: "backup-file", name }, { status: 201 });
    },
  ];
  let call = 0;
  const result = await uploadGoogleDriveBackup({
    ...backup,
    fetchImpl: (input, request) => {
      assert.equal(request.headers.Authorization, `Bearer ${accessToken}`);
      assert.equal(request.redirect, "manual");
      assert.ok(request.signal instanceof AbortSignal);
      return fetchSteps[call++](new URL(input), request);
    },
  });
  assert.equal(call, fetchSteps.length);
  assert.deepEqual(result, {
    name,
    folderName: "Stock Ledger Backups",
    url: "https://drive.google.com/open?id=backup-file",
  });
});

test("reuses a renamed folder and recovers from an interrupted upload", async (t) => {
  const bytes = Buffer.from("SQLite snapshot");
  const backup = await backupFixture(t, bytes);
  const initialLength = 6;
  let call = 0;
  const result = await uploadGoogleDriveBackup({
    ...backup,
    async fetchImpl(input, request) {
      switch (++call) {
        case 1:
          return Response.json({
            files: [{ id: "existing", name: "My Backups", shared: false }],
          });
        case 2:
          assert.deepEqual(JSON.parse(request.body).parents, ["existing"]);
          return new Response(null, { headers: { Location: session } });
        case 3:
          assert.deepEqual(await readBytes(request.body), bytes);
          return new Response(null, { status: 503 });
        case 4:
          assert.equal(request.headers["Content-Length"], "0");
          assert.equal(
            request.headers["Content-Range"],
            `bytes */${bytes.length}`,
          );
          return new Response(null, {
            status: 308,
            headers: { Range: `bytes=0-${initialLength - 1}` },
          });
        case 5:
          assert.equal(
            request.headers["Content-Range"],
            `bytes ${initialLength}-${bytes.length - 1}/${bytes.length}`,
          );
          assert.deepEqual(
            await readBytes(request.body),
            bytes.subarray(initialLength),
          );
          return Response.json({ id: "backup-file", name });
        default:
          throw new Error("Unexpected request");
      }
    },
  });
  assert.equal(call, 5);
  assert.equal(result.folderName, "My Backups");
});

test("rejects unsafe session URLs before transmitting a database", async (t) => {
  const backup = await backupFixture(t, "test contents");
  for (const location of [
    "",
    "http://www.googleapis.com/upload/drive/v3/files?upload_id=x",
    "https://www.googleapis.com.example.com/upload/drive/v3/files?upload_id=x",
    "https://www.googleapis.com:8080/upload/drive/v3/files?upload_id=x",
    "https://user@www.googleapis.com/upload/drive/v3/files?upload_id=x",
    "https://www.googleapis.com/unrelated?upload_id=x",
    "https://www.googleapis.com/upload/drive/v3/files",
  ]) {
    let call = 0;
    await assert.rejects(
      uploadGoogleDriveBackup({
        ...backup,
        fetchImpl: () =>
          ++call === 1
            ? Response.json({
                files: [{ id: "existing", name: "My Backups", shared: false }],
              })
            : new Response(null, { headers: { Location: location } }),
      }),
      { message: "Google Drive backup failed. Try again." },
    );
    assert.equal(call, 2);
  }
});

test("distinguishes expired authorization and hides raw provider errors", async (t) => {
  const backup = await backupFixture(t, "test contents");
  await assert.rejects(
    uploadGoogleDriveBackup({
      ...backup,
      fetchImpl: () => new Response("private data", { status: 401 }),
    }),
    {
      code: "GOOGLE_AUTH_EXPIRED",
      message: "Google authorization expired. Connect again.",
    },
  );
  await assert.rejects(
    uploadGoogleDriveBackup({
      ...backup,
      fetchImpl: () => {
        throw new Error("provider request details");
      },
    }),
    { message: "Could not reach Google Drive. Try again." },
  );
  await assert.rejects(
    uploadGoogleDriveBackup({
      ...backup,
      snapshotPath: path.join(backup.snapshotPath, "missing"),
    }),
    { message: "Could not read the local database backup." },
  );
});
