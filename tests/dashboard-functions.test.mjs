import test from "node:test";
import assert from "node:assert/strict";
import auth from "../api/auth.mjs";
import proxy from "../api/proxy.mjs";
import {
  createDashboardSession,
  isDashboardSessionValid,
} from "../lib/dashboard-session.mjs";

process.env.DASHBOARD_PASSWORD = "test-dashboard-password";
process.env.DASHBOARD_SESSION_SECRET = "unit-test-session-secret-with-more-than-32-bytes";
process.env.ANALYTICS_TOKEN = "test-analytics-secret";
process.env.ADMIN_API_TOKEN = "test-admin-api-secret";
process.env.MEDIA_UPLOAD_TOKEN = "test-media-secret";
process.env.API_BASE_URL = "https://inventory.example.test";
process.env.VERCEL = "1";

test("dashboard session signatures are valid and tampering is rejected", () => {
  const token = createDashboardSession(process.env.DASHBOARD_SESSION_SECRET);
  assert.equal(isDashboardSessionValid(token, process.env.DASHBOARD_SESSION_SECRET), true);
  assert.equal(isDashboardSessionValid(token + "x", process.env.DASHBOARD_SESSION_SECRET), false);
  assert.equal(isDashboardSessionValid(token, "different-secret-with-enough-bytes"), false);
});

test("dashboard login sets an HttpOnly secure cookie and validates it", async () => {
  const response = await auth.fetch(new Request("https://panel.example.test/api/auth", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "https://panel.example.test",
    },
    body: JSON.stringify({ password: process.env.DASHBOARD_PASSWORD }),
  }));
  assert.equal(response.status, 200);
  const cookieHeader = response.headers.get("set-cookie");
  assert.match(cookieHeader, /HttpOnly/);
  assert.match(cookieHeader, /SameSite=Strict/);
  assert.match(cookieHeader, /Secure/);
  const cookie = cookieHeader.split(";", 1)[0];

  const check = await auth.fetch(new Request("https://panel.example.test/api/auth", {
    headers: { cookie },
  }));
  assert.deepEqual(await check.json(), { authenticated: true });
});

test("dashboard login rejects a wrong password", async () => {
  const response = await auth.fetch(new Request("https://panel.example.test/api/auth", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "https://panel.example.test",
    },
    body: JSON.stringify({ password: "wrong-password" }),
  }));
  assert.equal(response.status, 401);
});

test("API proxy requires a valid dashboard session and injects server-only API token", async () => {
  const cookie = "elica_dashboard_session="
    + createDashboardSession(process.env.DASHBOARD_SESSION_SECRET);
  const originalFetch = globalThis.fetch;
  let forwarded;
  globalThis.fetch = async (url, options) => {
    forwarded = { url: new URL(url), options };
    return new Response('{"deletions":[]}', {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    const noSession = await proxy.fetch(new Request(
      "https://panel.example.test/api/proxy?path=%2Fanalytics%2Fdeletions",
    ));
    assert.equal(noSession.status, 401);
    assert.equal(forwarded, undefined);

    const response = await proxy.fetch(new Request(
      "https://panel.example.test/api/proxy?path=%2Fanalytics%2Fdeletions&days=7&limit=50",
      { headers: { cookie } },
    ));
    assert.equal(response.status, 200);
    assert.equal(forwarded.url.origin, "https://inventory.example.test");
    assert.equal(forwarded.url.pathname, "/analytics/deletions");
    assert.equal(forwarded.url.searchParams.get("days"), "7");
    assert.equal(forwarded.options.headers.get("X-Analytics-Token"), "test-analytics-secret");
    assert.equal(forwarded.options.headers.has("X-Media-Token"), false);

    const invalidPath = await proxy.fetch(new Request(
      "https://panel.example.test/api/proxy?path=https%3A%2F%2Fevil.example",
      { headers: { cookie } },
    ));
    assert.equal(invalidPath.status, 400);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("product write proxy injects the separate server-only admin API token", async () => {
  const cookie = "elica_dashboard_session="
    + createDashboardSession(process.env.DASHBOARD_SESSION_SECRET);
  const originalFetch = globalThis.fetch;
  let forwardedHeaders;
  globalThis.fetch = async (_url, options) => {
    forwardedHeaders = options.headers;
    return new Response('{"id":1}', {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    const response = await proxy.fetch(new Request(
      "https://panel.example.test/api/proxy?path=%2Fproducts",
      {
        method: "POST",
        headers: {
          cookie,
          origin: "https://panel.example.test",
          "content-type": "application/json",
        },
        body: JSON.stringify({ name: "test", price_usd: 10 }),
      },
    ));
    assert.equal(response.status, 200);
    assert.equal(forwardedHeaders.get("X-Admin-API-Token"), "test-admin-api-secret");
    assert.equal(forwardedHeaders.get("X-Analytics-Token"), "test-analytics-secret");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("photo upload proxy injects media token without exposing it to the browser", async () => {
  const cookie = "elica_dashboard_session="
    + createDashboardSession(process.env.DASHBOARD_SESSION_SECRET);
  const originalFetch = globalThis.fetch;
  let forwardedHeaders;
  globalThis.fetch = async (_url, options) => {
    forwardedHeaders = options.headers;
    return new Response('{"path":"photos/test.jpg"}', {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    const response = await proxy.fetch(new Request(
      "https://panel.example.test/api/proxy?path=%2Fmedia%2Fupload",
      {
        method: "POST",
        headers: { cookie, "content-type": "multipart/form-data; boundary=test-boundary" },
        body: "--test-boundary--",
      },
    ));
    assert.equal(response.status, 200);
    assert.equal(forwardedHeaders.get("X-Media-Token"), "test-media-secret");
    assert.equal(forwardedHeaders.has("X-Analytics-Token"), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("API proxy rejects cross-origin state-changing requests", async () => {
  const cookie = "elica_dashboard_session="
    + createDashboardSession(process.env.DASHBOARD_SESSION_SECRET);
  const originalFetch = globalThis.fetch;
  let called = false;
  globalThis.fetch = async () => {
    called = true;
    return new Response("{}");
  };
  try {
    const response = await proxy.fetch(new Request(
      "https://panel.example.test/api/proxy?path=%2Fmedia%2Fupload",
      {
        method: "POST",
        headers: {
          cookie,
          origin: "https://attacker.example.test",
          "content-type": "multipart/form-data; boundary=test-boundary",
        },
        body: "--test-boundary--",
      },
    ));
    assert.equal(response.status, 403);
    assert.equal(called, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
