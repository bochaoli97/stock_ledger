import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  authorizeGoogle,
  parseGoogleClient,
  refreshGoogle,
} from "./google-oauth.mjs";

const driveScope = "https://www.googleapis.com/auth/drive.file";
const installed = {
  client_id: "1234-test.apps.googleusercontent.com",
  client_secret: "test-secret",
};
const client = parseGoogleClient(JSON.stringify({ installed }));

test("reads only Google Desktop app credentials and ignores supplied URLs", () => {
  assert.deepEqual(
    parseGoogleClient(
      "\uFEFF" +
        JSON.stringify({
          installed: { ...installed, token_uri: "https://example.invalid" },
        }),
    ),
    { clientId: installed.client_id, clientSecret: installed.client_secret },
  );
  for (const json of [
    "",
    "null",
    JSON.stringify({ web: installed }),
    JSON.stringify({ installed: { ...installed, client_id: "unrelated" } }),
    JSON.stringify({ installed: { client_id: installed.client_id } }),
  ]) {
    assert.throws(() => parseGoogleClient(json), {
      message: "Select a Google OAuth Desktop app JSON file.",
    });
  }
});

test("Google sign-in checks loopback path, method and state before exchanging the code with PKCE", async () => {
  let authUrl;
  let callback;
  let browser;
  let tokenRequest;
  const tokens = await authorizeGoogle({
    client,
    openExternal: (url) => {
      authUrl = new URL(url);
      callback = new URL(authUrl.searchParams.get("redirect_uri"));
      browser = (async () => {
        const state = authUrl.searchParams.get("state");
        const approved = new URL(`?state=${state}&code=test-code`, callback);
        const requests = [
          fetch(new URL("?state=wrong&code=unexpected", callback)),
          fetch(new URL(`/other?state=${state}&code=unexpected`, callback)),
          fetch(approved, { method: "POST" }),
          fetch(
            new URL(`?state=${state}&state=another&code=unexpected`, callback),
          ),
        ];
        assert.deepEqual(
          await Promise.all(
            requests.map(async (response) => (await response).status),
          ),
          [400, 400, 400, 400],
        );
        const response = await fetch(approved);
        assert.equal(response.status, 200);
        assert.equal(response.headers.get("cache-control"), "no-store");
        assert.match(await response.text(), /Return to Stock Ledger/);
      })();
      return browser;
    },
    fetchImpl: async (url, options) => {
      tokenRequest = { url, ...options };
      return Response.json({
        access_token: "access",
        refresh_token: "refresh",
        expires_in: 3_600,
        scope: driveScope,
      });
    },
    timeoutMs: 5_000,
  });
  await browser;
  assert.equal(authUrl.origin, "https://accounts.google.com");
  assert.equal(authUrl.searchParams.get("scope"), driveScope);
  assert.equal(authUrl.searchParams.get("access_type"), "offline");
  assert.equal(authUrl.searchParams.get("code_challenge_method"), "S256");
  assert.equal(authUrl.searchParams.has("client_secret"), false);
  assert.equal(callback.hostname, "127.0.0.1");
  assert.ok(Number(callback.port) > 0);
  assert.equal(tokenRequest.url, "https://oauth2.googleapis.com/token");
  assert.equal(tokenRequest.redirect, "error");
  assert.equal(tokenRequest.body.get("code"), "test-code");
  assert.equal(tokenRequest.body.get("grant_type"), "authorization_code");
  assert.equal(tokenRequest.body.get("client_secret"), "test-secret");
  assert.equal(
    tokenRequest.body.get("redirect_uri"),
    authUrl.searchParams.get("redirect_uri"),
  );
  assert.equal(
    createHash("sha256")
      .update(tokenRequest.body.get("code_verifier"))
      .digest("base64url"),
    authUrl.searchParams.get("code_challenge"),
  );
  assert.equal(tokens.accessToken, "access");
  assert.equal(tokens.refreshToken, "refresh");
  assert.ok(tokens.expiresAt > Date.now());
  await assert.rejects(fetch(callback));
});

test("Google sign-in closes the loopback listener after denial and timeout", async () => {
  let deniedCallback;
  let browser;
  const unexpectedExchange = async () =>
    assert.fail("Unexpected token request");
  await assert.rejects(
    authorizeGoogle({
      client,
      openExternal: (url) => {
        const request = new URL(url);
        deniedCallback = new URL(request.searchParams.get("redirect_uri"));
        deniedCallback.searchParams.set(
          "state",
          request.searchParams.get("state"),
        );
        deniedCallback.searchParams.set("error", "access_denied");
        browser = fetch(deniedCallback);
        return browser;
      },
      fetchImpl: unexpectedExchange,
      timeoutMs: 5_000,
    }),
    { message: "Google Drive access was not granted." },
  );
  assert.equal((await browser).status, 200);
  await assert.rejects(fetch(deniedCallback));

  let timedOutCallback;
  await assert.rejects(
    authorizeGoogle({
      client,
      openExternal: (url) => {
        timedOutCallback = new URL(url).searchParams.get("redirect_uri");
      },
      fetchImpl: unexpectedExchange,
      timeoutMs: 50,
    }),
    { message: "Google sign-in timed out. Try again." },
  );
  assert.ok(timedOutCallback);
  await assert.rejects(fetch(timedOutCallback));
});

test("Google refresh preserves existing token, adopts rotation and identifies expired consent", async () => {
  async function refresh(data, status = 200) {
    return refreshGoogle({
      client,
      refreshToken: "previous-refresh-token",
      fetchImpl: async (url, { body }) => {
        assert.equal(url, "https://oauth2.googleapis.com/token");
        assert.equal(body.get("grant_type"), "refresh_token");
        assert.equal(body.get("refresh_token"), "previous-refresh-token");
        return Response.json(data, { status });
      },
    });
  }
  const refreshed = { access_token: "new-access", expires_in: 3_600 };
  assert.equal(
    (await refresh(refreshed)).refreshToken,
    "previous-refresh-token",
  );
  assert.equal(
    (await refresh({ ...refreshed, refresh_token: "rotated" })).refreshToken,
    "rotated",
  );
  await assert.rejects(refresh({ error: "invalid_grant" }, 400), {
    code: "GOOGLE_AUTH_EXPIRED",
    message: "Google authorization expired. Connect again.",
  });
  await assert.rejects(refresh({ ...refreshed, scope: "email" }), {
    message: "Google Drive access was not granted.",
  });
});
