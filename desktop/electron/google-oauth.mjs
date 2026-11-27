import { createHash, randomBytes } from "node:crypto";
import { createServer } from "node:http";

const AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth";
const TOKEN_URL = "https://oauth2.googleapis.com/token";
const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file";
const LOOPBACK = "127.0.0.1";
const INVALID_CLIENT_FILE = "Select a Google OAuth Desktop app JSON file.";
const UNAVAILABLE = "Google sign-in is unavailable. Try again.";
const ACCESS_DENIED = "Google Drive access was not granted.";

export function parseGoogleClient(jsonText) {
  let config;
  try {
    config = JSON.parse(jsonText.replace(/^\uFEFF/, ""));
  } catch {
    throw new Error(INVALID_CLIENT_FILE);
  }
  const { client_id: clientId, client_secret: clientSecret } =
    config?.installed ?? {};
  if (
    typeof clientId !== "string" ||
    !/^[a-zA-Z\d_-]+\.apps\.googleusercontent\.com$/.test(clientId) ||
    typeof clientSecret !== "string" ||
    !/^[a-zA-Z\d_-]+$/.test(clientSecret)
  ) {
    throw new Error(INVALID_CLIENT_FILE);
  }
  return { clientId, clientSecret };
}

function browserReply(response, status, message, afterSend) {
  response.writeHead(status, {
    "Cache-Control": "no-store",
    Connection: "close",
    "Content-Security-Policy": "default-src 'none'",
    "Content-Type": "text/html; charset=utf-8",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(
    `<!doctype html><meta charset="utf-8"><title>Stock Ledger</title><p>${message}</p>`,
    afterSend,
  );
}

function getAuthorizationCode({ state, openBrowser, timeoutMs }) {
  return new Promise((resolve, reject) => {
    let redirectUri;
    let completing = false;
    let settled = false;
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      server.close();
      server.closeAllConnections();
      if (error) reject(error);
      else resolve(result);
    };

    const server = createServer(
      { headersTimeout: 10_000, requestTimeout: 15_000 },
      (request, response) => {
        const origin = new URL(redirectUri);
        const target = URL.parse(request.url, origin);
        const states = target?.searchParams.getAll("state");
        const codes = target?.searchParams.getAll("code");
        const errors = target?.searchParams.getAll("error");
        if (
          completing ||
          request.method !== "GET" ||
          request.headers.host !== origin.host ||
          !request.url.startsWith("/") ||
          target?.origin !== origin.origin ||
          target.pathname !== "/" ||
          states.length !== 1 ||
          states[0] !== state ||
          codes.length + errors.length !== 1 ||
          !(codes[0] || errors[0])
        ) {
          browserReply(response, 400, "Invalid Google sign-in response.");
          return;
        }
        completing = true;
        if (errors[0]) {
          browserReply(
            response,
            200,
            "Google Drive access was not granted. Return to Stock Ledger. / 未授予 Google 云端硬盘访问权限，请返回股票账本。",
            () => finish(new Error(ACCESS_DENIED)),
          );
          return;
        }
        browserReply(
          response,
          200,
          "Return to Stock Ledger to finish connecting Google Drive. / 请返回股票账本完成连接。",
          () => finish(null, { code: codes[0], redirectUri }),
        );
      },
    );

    const timer = setTimeout(
      () => finish(new Error("Google sign-in timed out. Try again.")),
      timeoutMs,
    );
    server.once("error", () =>
      finish(new Error("Could not open Google sign-in.")),
    );
    server.listen(0, LOOPBACK, () => {
      if (settled) return;
      redirectUri = `http://${LOOPBACK}:${server.address().port}`;
      Promise.resolve()
        .then(() => openBrowser(redirectUri))
        .catch(() => {
          if (!completing) finish(new Error("Could not open Google sign-in."));
        });
    });
  });
}

async function requestTokens(client, grant, fetchImpl) {
  let response;
  let tokens;
  try {
    response = await fetchImpl(TOKEN_URL, {
      method: "POST",
      redirect: "error",
      body: new URLSearchParams({
        client_id: client.clientId,
        client_secret: client.clientSecret,
        ...grant,
      }),
      signal: AbortSignal.timeout(30_000),
    });
    tokens = await response.json();
  } catch {
    throw new Error(UNAVAILABLE);
  }
  if (!response.ok || tokens?.error) {
    if (tokens?.error === "invalid_grant") {
      const error = new Error("Google authorization expired. Connect again.");
      error.code = "GOOGLE_AUTH_EXPIRED";
      throw error;
    }
    if (
      ["invalid_client", "unauthorized_client", "deleted_client"].includes(
        tokens?.error,
      )
    ) {
      throw new Error(
        "Google rejected this OAuth client. Import a valid Desktop app credential.",
      );
    }
    throw new Error(UNAVAILABLE);
  }
  const expiresIn = tokens?.expires_in;
  if (
    typeof tokens?.access_token !== "string" ||
    !tokens.access_token ||
    !Number.isSafeInteger(expiresIn) ||
    expiresIn <= 0
  ) {
    throw new Error(UNAVAILABLE);
  }
  if (
    typeof tokens.scope === "string" &&
    !tokens.scope.split(/\s+/).includes(DRIVE_SCOPE)
  ) {
    throw new Error(ACCESS_DENIED);
  }
  const refreshToken = tokens.refresh_token ?? grant.refresh_token;
  if (typeof refreshToken !== "string" || !refreshToken) {
    throw new Error("Google did not return offline access. Connect again.");
  }
  return {
    accessToken: tokens.access_token,
    refreshToken,
    expiresAt: Date.now() + expiresIn * 1000,
  };
}

export async function authorizeGoogle({
  client,
  openExternal,
  fetchImpl = globalThis.fetch,
  timeoutMs = 180_000,
}) {
  const state = randomBytes(32).toString("base64url");
  const codeVerifier = randomBytes(32).toString("base64url");
  const codeChallenge = createHash("sha256")
    .update(codeVerifier)
    .digest("base64url");
  const { code, redirectUri } = await getAuthorizationCode({
    state,
    timeoutMs,
    openBrowser: (callback) => {
      const url = new URL(AUTHORIZE_URL);
      url.search = new URLSearchParams({
        client_id: client.clientId,
        redirect_uri: callback,
        scope: DRIVE_SCOPE,
        response_type: "code",
        access_type: "offline",
        prompt: "consent select_account",
        state,
        code_challenge: codeChallenge,
        code_challenge_method: "S256",
      });
      return openExternal(url.href);
    },
  });
  return requestTokens(
    client,
    {
      grant_type: "authorization_code",
      code,
      code_verifier: codeVerifier,
      redirect_uri: redirectUri,
    },
    fetchImpl,
  );
}

export function refreshGoogle({
  client,
  refreshToken,
  fetchImpl = globalThis.fetch,
}) {
  return requestTokens(
    client,
    { grant_type: "refresh_token", refresh_token: refreshToken },
    fetchImpl,
  );
}
