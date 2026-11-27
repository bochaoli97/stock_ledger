import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";

const driveOrigin = "https://www.googleapis.com";
const filesUrl = `${driveOrigin}/drive/v3/files`;
const uploadPath = "/upload/drive/v3/files";
const folderName = "Stock Ledger Backups";
const folderType = "application/vnd.google-apps.folder";
const backupType = "application/vnd.sqlite3";
const markerKey = "stockLedgerBackupFolder";
const markerValue = "1";
const failedMessage = "Google Drive backup failed. Try again.";
const readMessage = "Could not read the local database backup.";

async function discard(response) {
  await response.body?.cancel().catch(() => {});
}

async function check(response) {
  if (response.ok) return response;
  await discard(response);
  if (response.status === 401) {
    throw Object.assign(
      new Error("Google authorization expired. Connect again."),
      {
        code: "GOOGLE_AUTH_EXPIRED",
      },
    );
  }
  throw new Error(failedMessage);
}

async function readJson(response) {
  await check(response);
  try {
    const value = await response.json();
    if (value && typeof value === "object" && !Array.isArray(value))
      return value;
  } catch {
    // Google error bodies can contain private details.
  }
  throw new Error(failedMessage);
}

function sessionUrl(location) {
  try {
    const url = new URL(location);
    if (
      [driveOrigin, "https://drive.googleapis.com"].includes(url.origin) &&
      !url.username &&
      !url.password &&
      !url.hash &&
      url.pathname === uploadPath &&
      url.searchParams.get("upload_id")
    )
      return url;
  } catch {
    // The session must be an absolute Google Drive upload URL.
  }
  throw new Error(failedMessage);
}

function hasFileMetadata(file) {
  return (
    typeof file?.id === "string" &&
    file.id.length > 0 &&
    typeof file.name === "string" &&
    file.name.length > 0
  );
}

async function getBackupFolder(send) {
  const list = new URL(filesUrl);
  list.search = new URLSearchParams({
    q: `'me' in owners and trashed = false and mimeType = '${folderType}' and appProperties has { key='${markerKey}' and value='${markerValue}' }`,
    spaces: "drive",
    fields: "nextPageToken,files(id,name,shared)",
    orderBy: "createdTime",
  });
  const seen = new Set();
  for (;;) {
    const page = await readJson(await send(list));
    const folder = Array.isArray(page.files)
      ? page.files.find(
          (item) => hasFileMetadata(item) && item.shared === false,
        )
      : null;
    if (folder) return folder;
    if (!page.nextPageToken) break;
    if (typeof page.nextPageToken !== "string" || seen.has(page.nextPageToken))
      throw new Error(failedMessage);
    seen.add(page.nextPageToken);
    list.searchParams.set("pageToken", page.nextPageToken);
  }

  const create = new URL(filesUrl);
  create.search = new URLSearchParams({
    fields: "id,name,shared",
    ignoreDefaultVisibility: "true",
  });
  const folder = await readJson(
    await send(create, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=UTF-8" },
      body: JSON.stringify({
        name: folderName,
        mimeType: folderType,
        appProperties: { [markerKey]: markerValue },
      }),
    }),
  );
  if (!hasFileMetadata(folder) || folder.shared !== false)
    throw new Error(failedMessage);
  return folder;
}

async function sendBackupBytes(send, url, snapshotPath, size, start = 0) {
  const body = createReadStream(snapshotPath, { start });
  const closed = new Promise((resolve) => body.once("close", resolve));
  const headers = {
    "Content-Type": backupType,
    "Content-Length": String(size - start),
  };
  if (start) headers["Content-Range"] = `bytes ${start}-${size - 1}/${size}`;
  try {
    return await send(
      url,
      { method: "PUT", headers, body, duplex: "half" },
      300_000,
    );
  } catch (error) {
    if (body.errored && "path" in body.errored) throw new Error(readMessage);
    throw error;
  } finally {
    body.destroy();
    await closed;
  }
}

async function completeUpload(send, url, snapshotPath, size) {
  let response;
  try {
    response = await sendBackupBytes(send, url, snapshotPath, size);
  } catch (error) {
    if (error.code !== "GOOGLE_DRIVE_UNREACHABLE") throw error;
  }
  if (response && response.status !== 308 && response.status < 500)
    return response;
  if (response) await discard(response);

  // The server may already have received some or all of the data.
  const status = await send(url, {
    method: "PUT",
    headers: { "Content-Length": "0", "Content-Range": `bytes */${size}` },
  });
  if (status.status !== 308) return status;
  const received = status.headers.get("Range");
  await discard(status);
  const match = received?.match(/^bytes=0-(\d+)$/);
  const start = received ? Number(match?.[1]) + 1 : 0;
  if (!Number.isSafeInteger(start) || start >= size)
    throw new Error(failedMessage);
  return sendBackupBytes(send, url, snapshotPath, size, start);
}

export async function uploadGoogleDriveBackup({
  accessToken,
  snapshotPath,
  name,
  fetchImpl = globalThis.fetch,
}) {
  const snapshot = await stat(snapshotPath).catch(() => null);
  if (!snapshot?.isFile() || snapshot.size === 0) throw new Error(readMessage);

  async function send(url, { headers, ...options } = {}, timeout = 30_000) {
    try {
      return await fetchImpl(url, {
        ...options,
        headers: { ...headers, Authorization: `Bearer ${accessToken}` },
        redirect: "manual",
        signal: AbortSignal.timeout(timeout),
      });
    } catch {
      throw Object.assign(
        new Error("Could not reach Google Drive. Try again."),
        {
          code: "GOOGLE_DRIVE_UNREACHABLE",
        },
      );
    }
  }

  const folder = await getBackupFolder(send);
  const url = new URL(uploadPath, driveOrigin);
  url.search = new URLSearchParams({
    uploadType: "resumable",
    fields: "id,name",
    ignoreDefaultVisibility: "true",
  });
  const initial = await check(
    await send(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": backupType,
        "X-Upload-Content-Length": String(snapshot.size),
      },
      body: JSON.stringify({
        name,
        mimeType: backupType,
        parents: [folder.id],
      }),
    }),
  );
  const location = initial.headers.get("Location");
  await discard(initial);
  const session = sessionUrl(location);
  const file = await readJson(
    await completeUpload(send, session, snapshotPath, snapshot.size),
  );
  if (!hasFileMetadata(file)) throw new Error(failedMessage);
  return {
    name: file.name,
    folderName: folder.name,
    url: `https://drive.google.com/open?id=${encodeURIComponent(file.id)}`,
  };
}
