import { readDashboardSession } from "../lib/dashboard-session.mjs";

const DEFAULT_API_BASE_URL = "https://tehraninventory-production.up.railway.app";
const MAX_UPLOAD_BYTES = 4 * 1024 * 1024;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store, max-age=0",
    },
  });
}

function allowedPath(path, method) {
  if (["/analytics/summary", "/analytics/demand", "/analytics/products",
    "/analytics/admins", "/analytics/deletions"].includes(path)) {
    return method === "GET";
  }
  if (path === "/products") return method === "GET" || method === "POST";
  if (/^\/products\/[1-9]\d*$/.test(path)) {
    return ["GET", "PUT", "DELETE"].includes(method);
  }
  if (path === "/media/upload") return method === "POST";
  if (/^\/media\/[^/]+$/u.test(path)) {
    const filename = path.slice("/media/".length);
    return method === "GET" && filename !== "." && filename !== "..";
  }
  return false;
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

function buildUpstreamUrl(requestUrl, path) {
  const base = new URL(process.env.API_BASE_URL || DEFAULT_API_BASE_URL);
  if (process.env.VERCEL === "1" && base.protocol !== "https:") {
    throw new Error("API_BASE_URL must use HTTPS in production.");
  }
  base.pathname = base.pathname.replace(/\/+$/, "") + path;
  base.search = "";
  const query = new URL(requestUrl).searchParams;
  for (const key of ["days", "limit"]) {
    const value = query.get(key);
    if (value !== null && /^\d{1,4}$/.test(value)) base.searchParams.set(key, value);
  }
  return base;
}

export default {
  async fetch(request) {
    if (!readDashboardSession(request)) return json({ error: "Dashboard login required." }, 401);
    if (request.method !== "GET" && !sameOrigin(request)) {
      return json({ error: "Cross-origin request rejected." }, 403);
    }

    const requestUrl = new URL(request.url);
    const encodedPath = requestUrl.searchParams.get("path") || "";
    let path;
    try {
      path = decodeURIComponent(encodedPath);
    } catch {
      return json({ error: "Invalid API path." }, 400);
    }
    if (!path.startsWith("/") || path.startsWith("//")
      || path.includes("\\") || path.includes("\0")
      || path.split("/").some((part) => part === "." || part === "..")) {
      return json({ error: "Invalid API path." }, 400);
    }
    if (!allowedPath(path, request.method)) {
      return json({ error: "API path or method is not allowed." }, 403);
    }

    const isUpload = path === "/media/upload";
    const isMediaRead = path.startsWith("/media/") && !isUpload;
    const isProductWrite = (path === "/products" && request.method === "POST")
      || (/^\/products\/[1-9]\d*$/.test(path) && ["PUT", "DELETE"].includes(request.method));
    const analyticsToken = process.env.ANALYTICS_TOKEN || "";
    const adminApiToken = process.env.ADMIN_API_TOKEN || "";
    const mediaToken = process.env.MEDIA_UPLOAD_TOKEN || "";
    const missingSecret = isUpload
      ? (mediaToken ? "" : "MEDIA_UPLOAD_TOKEN")
      : isProductWrite
        ? (adminApiToken ? "" : "ADMIN_API_TOKEN")
        : (!isMediaRead && !analyticsToken) ? "ANALYTICS_TOKEN" : "";
    if (missingSecret) {
      return json({ error: missingSecret + " is not configured in Vercel." }, 503);
    }

    let body;
    if (request.method !== "GET" && request.method !== "HEAD") {
      const length = Number(request.headers.get("content-length") || 0);
      if (isUpload && length > MAX_UPLOAD_BYTES) {
        return json({ error: "تصویر بعد از فشرده‌سازی باید کمتر از ۴ مگابایت باشد." }, 413);
      }
      body = await request.arrayBuffer();
      if (isUpload && body.byteLength > MAX_UPLOAD_BYTES) {
        return json({ error: "تصویر بعد از فشرده‌سازی باید کمتر از ۴ مگابایت باشد." }, 413);
      }
    }

    const headers = new Headers();
    const accept = request.headers.get("accept");
    if (accept) headers.set("accept", accept);
    const contentType = request.headers.get("content-type");
    if (contentType && body) headers.set("content-type", contentType);
    if (isUpload) {
      headers.set("X-Media-Token", mediaToken);
    } else if (isProductWrite) {
      headers.set("X-Admin-API-Token", adminApiToken);
      if (analyticsToken) headers.set("X-Analytics-Token", analyticsToken);
    } else if (!isMediaRead) {
      headers.set("X-Analytics-Token", analyticsToken);
    }
    if (request.method === "DELETE") {
      headers.set("X-Deletion-Source", "dashboard");
      if (process.env.DASHBOARD_ADMIN_LABEL) {
        headers.set("X-Admin-Username", process.env.DASHBOARD_ADMIN_LABEL.replace(/^@/, ""));
      }
    }

    let upstream;
    try {
      upstream = await fetch(buildUpstreamUrl(requestUrl, path), {
        method: request.method,
        headers,
        body: body ? Buffer.from(body) : undefined,
        redirect: "manual",
        signal: AbortSignal.timeout(25_000),
      });
    } catch {
      return json({ error: "Could not reach the inventory API." }, 502);
    }

    const responseHeaders = new Headers({ "cache-control": "private, no-store, max-age=0" });
    for (const name of ["content-type", "last-modified", "etag"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  },
};
