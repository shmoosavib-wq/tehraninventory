import { createHmac, timingSafeEqual } from "node:crypto";

export const DASHBOARD_SESSION_COOKIE = "elica_dashboard_session";
export const DASHBOARD_SESSION_TTL_SECONDS = 14 * 24 * 60 * 60;

export function dashboardSessionSecret() {
  const secret = process.env.DASHBOARD_SESSION_SECRET || "";
  if (Buffer.byteLength(secret, "utf8") < 32) {
    throw new Error("DASHBOARD_SESSION_SECRET must be at least 32 bytes");
  }
  return secret;
}

export function createDashboardSession(secret, now = Date.now()) {
  const payload = Buffer.from(JSON.stringify({
    issuedAt: Math.floor(now / 1000),
    expiresAt: Math.floor(now / 1000) + DASHBOARD_SESSION_TTL_SECONDS,
  })).toString("base64url");
  const signature = createHmac("sha256", secret).update(payload).digest("base64url");
  return payload + "." + signature;
}

export function isDashboardSessionValid(token, secret, now = Date.now()) {
  if (typeof token !== "string" || token.length > 1024) return false;
  const parts = token.split(".");
  if (parts.length !== 2) return false;
  const [payload, signature] = parts;
  const expected = createHmac("sha256", secret).update(payload).digest();
  let supplied;
  try {
    supplied = Buffer.from(signature, "base64url");
  } catch {
    return false;
  }
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) return false;
  try {
    const data = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
    const nowSeconds = Math.floor(now / 1000);
    return Number.isInteger(data.issuedAt)
      && Number.isInteger(data.expiresAt)
      && data.issuedAt <= nowSeconds
      && data.expiresAt > nowSeconds
      && data.expiresAt - data.issuedAt <= DASHBOARD_SESSION_TTL_SECONDS;
  } catch {
    return false;
  }
}

export function readDashboardSession(request) {
  let secret;
  try {
    secret = dashboardSessionSecret();
  } catch {
    return false;
  }
  const cookieHeader = request.headers.get("cookie") || "";
  const cookie = cookieHeader.split(";").map((item) => item.trim())
    .find((item) => item.startsWith(DASHBOARD_SESSION_COOKIE + "="));
  if (!cookie) return false;
  return isDashboardSessionValid(
    cookie.slice(DASHBOARD_SESSION_COOKIE.length + 1),
    secret,
  );
}
