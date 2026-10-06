import { createHash, timingSafeEqual } from "node:crypto";
import {
  createDashboardSession,
  dashboardSessionSecret,
  DASHBOARD_SESSION_COOKIE,
  DASHBOARD_SESSION_TTL_SECONDS,
  readDashboardSession,
} from "../lib/dashboard-session.mjs";

function json(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      ...extraHeaders,
    },
  });
}

function configured() {
  return Boolean(process.env.DASHBOARD_PASSWORD)
    && Buffer.byteLength(process.env.DASHBOARD_SESSION_SECRET || "", "utf8") >= 32;
}

function sameOrigin(request) {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  const requestOrigin = new URL(request.url).origin;
  const forwardedHost = request.headers.get("x-forwarded-host") || request.headers.get("host");
  const forwardedProto = (request.headers.get("x-forwarded-proto") || "https").split(",")[0].trim();
  const forwardedOrigin = forwardedHost ? forwardedProto + "://" + forwardedHost : "";
  return origin === requestOrigin || origin === forwardedOrigin;
}

function secureCookie(request) {
  return process.env.VERCEL === "1"
    || (request.headers.get("x-forwarded-proto") || "").split(",")[0].trim() === "https";
}

function cookieHeader(request, value, maxAge) {
  const secure = secureCookie(request) ? "; Secure" : "";
  return DASHBOARD_SESSION_COOKIE + "=" + value
    + "; Path=/; HttpOnly; SameSite=Strict; Max-Age=" + maxAge + secure;
}

function passwordsMatch(provided, expected) {
  const suppliedDigest = createHash("sha256").update(provided, "utf8").digest();
  const expectedDigest = createHash("sha256").update(expected, "utf8").digest();
  return timingSafeEqual(suppliedDigest, expectedDigest);
}

export default {
  async fetch(request) {
    if (!configured()) {
      return json({ error: "Set DASHBOARD_PASSWORD and a 32+ byte DASHBOARD_SESSION_SECRET in Vercel." }, 503);
    }

    if (request.method === "GET") {
      return json({ authenticated: readDashboardSession(request) });
    }

    if (!["POST", "DELETE"].includes(request.method)) {
      return json({ error: "Method not allowed" }, 405, { allow: "GET, POST, DELETE" });
    }
    if (!sameOrigin(request)) return json({ error: "Cross-origin request rejected" }, 403);

    if (request.method === "DELETE") {
      return json(
        { authenticated: false },
        200,
        { "set-cookie": cookieHeader(request, "", 0) },
      );
    }

    const contentLength = Number(request.headers.get("content-length") || 0);
    if (contentLength > 2048) return json({ error: "Request too large" }, 413);
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "Expected a JSON request body" }, 400);
    }
    const password = typeof body?.password === "string" ? body.password : "";
    if (!password || password.length > 512
      || !passwordsMatch(password, process.env.DASHBOARD_PASSWORD)) {
      return json({ error: "رمز ورود صحیح نیست." }, 401);
    }

    let session;
    try {
      session = createDashboardSession(dashboardSessionSecret());
    } catch {
      return json({ error: "Dashboard session is not configured." }, 503);
    }
    return json(
      { authenticated: true },
      200,
      { "set-cookie": cookieHeader(request, session, DASHBOARD_SESSION_TTL_SECONDS) },
    );
  },
};
