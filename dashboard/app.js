const LOCAL_MODE = location.protocol === "file:"
  || location.hostname === "localhost"
  || location.hostname === "127.0.0.1";
const $ = (id) => document.getElementById(id);
const state = { api: "", analyticsToken: "", adminApiToken: "", mediaToken: "" };
const knownAdminNames = { "62414083": "shmb27" };
let catalogProducts = [];
let catalogCategory = "";
let catalogPage = 0;
let loginDialogBusy = false;

function escapeHtml(value) {
  return String(value ?? "-").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[char]);
}

function apiUrl(path) {
  const parsed = new URL(path, "https://local.invalid");
  if (LOCAL_MODE) return state.api.replace(/\/+$/, "") + parsed.pathname + parsed.search;
  const params = new URLSearchParams();
  params.set("path", parsed.pathname);
  parsed.searchParams.forEach((value, key) => params.append(key, value));
  return "/api/proxy?" + params.toString();
}

function setStatus(message, error = false) {
  const target = $("status");
  if (!target) return;
  target.textContent = message;
  target.style.color = error ? "#ff8d9b" : "";
}

function showError(error) {
  const message = error instanceof Error ? error.message : String(error);
  setStatus("خطا: " + message, true);
}

async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (LOCAL_MODE) {
    headers.set("X-Analytics-Token", state.analyticsToken);
    if (["POST", "PUT", "DELETE"].includes(options.method)
      && (path === "/products" || path.startsWith("/products/"))) {
      headers.set("X-Admin-API-Token", state.adminApiToken);
    }
    if (path === "/media/upload") headers.set("X-Media-Token", state.mediaToken);
  }
  const response = await fetch(apiUrl(path), {
    ...options,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.clone().json();
      detail = body.detail || body.error || "";
    } catch {}
    if (response.status === 401 && !LOCAL_MODE) {
      openLogin("نشست ورود منقضی شده؛ دوباره وارد شوید.");
      throw new Error("نیاز به ورود دوباره");
    }
    throw new Error(detail || ("پاسخ سرور: " + response.status));
  }
  const type = response.headers.get("content-type") || "";
  return type.includes("application/json") ? response.json() : response;
}

function row(title, subtitle, value) {
  return '<div class="row"><span>' + escapeHtml(title)
    + '<small>' + escapeHtml(subtitle) + '</small></span><strong>'
    + escapeHtml(value) + "</strong></div>";
}

function adminName(id, name) {
  if (name) return "@" + name;
  if (knownAdminNames[String(id)]) return "@" + knownAdminNames[String(id)];
  return "شناسه " + (id || "-");
}

function renderDemand(items) {
  $("demand-list").innerHTML = items.length
    ? items.slice(0, 5).map((item) => row(
      item.query,
      item.category || "بدون دسته",
      item.search_count + " جستجو",
    )).join("")
    : "داده‌ای ثبت نشده";
  $("demand-table").innerHTML = items.length
    ? "<table><thead><tr><th>عبارت</th><th>دسته</th><th>جستجو</th><th>کاربر یکتا</th></tr></thead><tbody>"
      + items.map((item) => "<tr><td>" + escapeHtml(item.query) + "</td><td>"
        + escapeHtml(item.category || "-") + "</td><td>" + Number(item.search_count || 0)
        + "</td><td>" + Number(item.unique_users || 0) + "</td></tr>").join("")
      + "</tbody></table>"
    : "داده‌ای ثبت نشده";
}

function renderDeletionLog(payload) {
  const items = payload.deletions || [];
  const target = $("deletion-table");
  $("deletion-count").textContent = items.length + " مورد";
  if (!items.length) {
    target.innerHTML = '<p class="empty-state">در این بازه حذف ثبت‌شده‌ای وجود ندارد.</p>';
    return;
  }
  target.innerHTML = '<div class="table-scroll"><table><thead><tr>'
    + "<th>زمان حذف</th><th>محصول</th><th>دسته</th><th>قیمت خرید</th>"
    + "<th>انجام‌دهنده</th><th>محل حذف</th><th>شناسه گروه</th>"
    + "</tr></thead><tbody>"
    + items.map((item) => {
      const date = item.deleted_at
        ? new Date(item.deleted_at).toLocaleString("fa-IR")
        : "-";
      const actor = item.deleted_by_admin_username
        ? "@" + String(item.deleted_by_admin_username).replace(/^@/, "")
        : item.deleted_by_admin_id
          ? "شناسه " + item.deleted_by_admin_id
          : "نامشخص";
      const source = item.source === "admin_bot" ? "بات ادمین"
        : item.source === "dashboard" ? "پنل وب" : escapeHtml(item.source || "API");
      return "<tr><td>" + escapeHtml(date) + "</td><td><b>"
        + escapeHtml(item.product_name) + "</b><small>#"
        + Number(item.product_id) + "</small></td><td>"
        + escapeHtml(item.category || "-") + "</td><td>"
        + (item.price_usd == null ? "-" : "$" + Number(item.price_usd).toLocaleString("en-US"))
        + "</td><td>" + escapeHtml(actor) + "</td><td>" + source
        + "</td><td><code>" + escapeHtml(item.batch_id || "-") + "</code></td></tr>";
    }).join("")
    + "</tbody></table></div>";
}

async function loadAnalytics() {
  const days = Number($("days").value || 30);
  setStatus("در حال دریافت آمار…");
  const results = await Promise.all([
    apiRequest("/analytics/summary?days=" + days),
    apiRequest("/analytics/demand?days=" + days + "&limit=50"),
    apiRequest("/analytics/products?days=" + days),
    apiRequest("/analytics/admins?days=" + days),
    apiRequest("/analytics/deletions?days=" + days + "&limit=200"),
  ]);
  const [summary, demand, products, admins, deletions] = results;
  $("users").textContent = summary.unique_users ?? 0;
  $("searches").textContent = summary.searches ?? 0;
  $("views").textContent = summary.product_views ?? 0;
  $("conversion").textContent = (summary.conversion_rate ?? 0) + "%";
  $("f-search").textContent = summary.searches ?? 0;
  $("f-view").textContent = summary.product_views ?? 0;
  $("f-click").textContent = summary.order_clicks ?? 0;
  $("f-order").textContent = summary.completed_orders ?? 0;
  renderDemand(Array.isArray(demand) ? demand : []);
  $("product-list").innerHTML = products.products?.length
    ? products.products.slice(0, 8).map((item) => row(
      item.name,
      (item.category || "-") + " · " + item.views + " مشاهده",
      item.order_clicks + " سفارش",
    )).join("")
    : "داده‌ای ثبت نشده";
  $("admin-list").innerHTML = admins.admins?.length
    ? admins.admins.map((item) => row(
      adminName(item.admin_id, item.username),
      item.products_created + " محصول · " + item.referrals + " ارجاع",
      item.completed_orders + " فروش",
    )).join("")
    : "داده‌ای ثبت نشده";
  renderDeletionLog(deletions);
  setStatus("آخرین بروزرسانی: همین حالا");
}

function renderCategoryButtons() {
  const counts = new Map();
  catalogProducts.forEach((product) => {
    const category = product.category || "سایر";
    counts.set(category, (counts.get(category) || 0) + 1);
  });
  let markup = '<button type="button" class="category-chip'
    + (!catalogCategory ? " active" : "") + '" data-category="">همه (' + catalogProducts.length + ")</button>";
  [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0], "fa")).forEach(([category, count]) => {
    markup += '<button type="button" class="category-chip'
      + (catalogCategory === category ? " active" : "")
      + '" data-category="' + escapeHtml(category) + '">'
      + escapeHtml(category) + " (" + count + ")</button>";
  });
  $("category-list").innerHTML = markup;
  $("category-list").querySelectorAll("[data-category]").forEach((button) => {
    button.addEventListener("click", () => {
      catalogCategory = button.dataset.category || "";
      catalogPage = 0;
      renderCategoryButtons();
      renderCatalog();
    });
  });
}

function renderCatalog() {
  const query = ($("catalog-search").value || "").trim().toLocaleLowerCase("fa");
  const filtered = catalogProducts.filter((product) => {
    const category = product.category || "سایر";
    const text = [product.name, product.category, product.location, product.description]
      .join(" ").toLocaleLowerCase("fa");
    return (!catalogCategory || category === catalogCategory) && (!query || text.includes(query));
  });
  const pageCount = Math.max(1, Math.ceil(filtered.length / 20));
  catalogPage = Math.min(catalogPage, pageCount - 1);
  const visible = filtered.slice(catalogPage * 20, catalogPage * 20 + 20);
  if (!visible.length) {
    $("catalog-table").innerHTML = '<p class="empty-state">محصولی در این دسته پیدا نشد.</p>';
    return;
  }
  $("catalog-table").innerHTML = '<table><thead><tr><th>نام محصول</th><th>دسته</th>'
    + "<th>قیمت خرید</th><th>موقعیت</th><th>عملیات</th></tr></thead><tbody>"
    + visible.map((product) => "<tr><td>" + escapeHtml(product.name) + "</td><td>"
      + escapeHtml(product.category || "-") + "</td><td>$"
      + Number(product.price_usd || 0).toLocaleString("en-US") + "</td><td>"
      + escapeHtml(product.location || "-") + '</td><td><button type="button" class="edit-btn" data-view-product="'
      + Number(product.id) + '">جزئیات و ویرایش</button></td></tr>').join("")
    + '</tbody></table><div class="pagination"><button type="button" data-page="prev"'
    + (catalogPage === 0 ? " disabled" : "") + ">قبلی</button><span>صفحه "
    + (catalogPage + 1) + " از " + pageCount + " · " + filtered.length
    + " محصول</span><button type=\"button\" data-page=\"next\""
    + (catalogPage >= pageCount - 1 ? " disabled" : "") + ">بعدی</button></div>";
  $("catalog-table").querySelectorAll("[data-view-product]").forEach((button) => {
    button.addEventListener("click", () => viewProduct(Number(button.dataset.viewProduct)));
  });
  $("catalog-table").querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => {
      catalogPage += button.dataset.page === "next" ? 1 : -1;
      renderCatalog();
    });
  });
}

async function loadCatalog() {
  const result = await apiRequest("/products");
  catalogProducts = Array.isArray(result) ? result : [];
  renderCategoryButtons();
  renderCatalog();
}

function imageUrl(path) {
  const filename = String(path || "").split(/[\\/]/).pop();
  if (/^https?:\/\//i.test(path || "")) return path;
  if (LOCAL_MODE && location.origin !== "null") {
    return location.origin + "/photos/" + encodeURIComponent(filename);
  }
  return apiUrl("/media/" + encodeURIComponent(filename));
}

function fillProductForm(product) {
  $("form-id").value = product?.id || "";
  $("form-title").textContent = product ? "ویرایش محصول" : "افزودن محصول";
  $("form-name").value = product?.name || "";
  $("form-price").value = product?.price_usd ?? "";
  $("form-weight").value = product?.weight_grams ?? "";
  $("form-size").value = product?.size || "";
  $("form-category").value = product?.category || "سایر";
  $("form-location").value = product?.location || "تهران";
  $("form-description").value = product?.description || "";
  if (!$("product-form-dialog").open) $("product-form-dialog").showModal();
}

function showProduct(product) {
  const photos = (product.original_photo_path || "").split("|").filter(Boolean);
  const photoMarkup = photos.length
    ? photos.map((path, index) => '<span class="photo-item"><img src="'
      + escapeHtml(imageUrl(path)) + '" alt="' + escapeHtml(product.name)
      + '"><button type="button" data-remove-photo="' + index + '" aria-label="حذف عکس">×</button></span>').join("")
    : "<p>عکسی ثبت نشده است.</p>";
  $("product-detail").innerHTML = '<button class="modal-close" type="button" aria-label="بستن">×</button>'
    + '<h2 class="detail-title">' + escapeHtml(product.name) + "</h2>"
    + '<div class="detail-photos">' + photoMarkup + "</div>"
    + '<label class="photo-upload">افزودن عکس محصول<input id="photo-upload-input" type="file" accept="image/*" multiple></label>'
    + '<div class="detail-grid"><span>قیمت خرید</span><b>$' + escapeHtml(product.price_usd)
    + "</b><span>دسته</span><b>" + escapeHtml(product.category || "-")
    + "</b><span>وزن</span><b>" + escapeHtml(product.weight_grams ?? "-")
    + " گرم</b><span>سایز</span><b>" + escapeHtml(product.size || "-")
    + "</b><span>موقعیت</span><b>" + escapeHtml(product.location || "-")
    + "</b><span>ثبت‌کننده</span><b>" + escapeHtml(adminName(
      product.created_by_admin_id, product.created_by_admin_username,
    )) + " (" + escapeHtml(product.created_by_admin_id || "-") + ")</b></div>"
    + "<p>" + escapeHtml(product.description || "توضیحی ثبت نشده است.")
    + '</p><div class="detail-actions"><button type="button" class="edit-btn" id="detail-edit">ویرایش محصول</button>'
    + '<button type="button" class="secondary" id="detail-close">بستن</button></div>';
  if (!$("product-dialog").open) $("product-dialog").showModal();
  $("product-detail").querySelector(".modal-close").onclick = () => $("product-dialog").close();
  $("detail-close").onclick = () => $("product-dialog").close();
  $("detail-edit").onclick = () => {
    $("product-dialog").close();
    fillProductForm(product);
  };
  $("product-detail").querySelectorAll("[data-remove-photo]").forEach((button) => {
    button.addEventListener("click", () => removeProductPhoto(
      product, Number(button.dataset.removePhoto),
    ));
  });
  $("photo-upload-input").addEventListener("change", (event) => {
    uploadProductPhotos(product, [...(event.target.files || [])]);
  });
}

async function viewProduct(id) {
  const product = catalogProducts.find((item) => item.id === id)
    || await apiRequest("/products/" + id);
  showProduct(product);
}

async function saveProduct(event) {
  event.preventDefault();
  const id = $("form-id").value;
  const product = {
    name: $("form-name").value.trim(),
    price_usd: Number($("form-price").value),
    weight_grams: $("form-weight").value ? Number($("form-weight").value) : null,
    size: $("form-size").value || null,
    category: $("form-category").value || null,
    location: $("form-location").value || "تهران",
    description: $("form-description").value || null,
  };
  try {
    await apiRequest("/products" + (id ? "/" + id : ""), {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(product),
    });
    $("product-form-dialog").close();
    await loadCatalog();
    setStatus("محصول ذخیره شد.");
  } catch (error) {
    showError(error);
  }
}

async function compressImage(file) {
  const maxBytes = 3_500_000;
  if (file.size <= maxBytes) return file;
  if (!file.type.startsWith("image/")) throw new Error("فقط فایل تصویری قابل آپلود است.");
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error("این تصویر قابل فشرده‌سازی نیست؛ نسخه کوچک‌تری انتخاب کنید.");
  }
  let width = bitmap.width;
  let height = bitmap.height;
  const initialScale = Math.min(1, 1800 / Math.max(width, height));
  width = Math.max(1, Math.round(width * initialScale));
  height = Math.max(1, Math.round(height * initialScale));
  let blob = null;
  while (Math.max(width, height) >= 320) {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { alpha: false });
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, width, height);
    context.drawImage(bitmap, 0, 0, width, height);
    blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.82));
    if (blob && blob.size <= maxBytes) break;
    width = Math.round(width * 0.8);
    height = Math.round(height * 0.8);
  }
  bitmap.close?.();
  if (!blob || blob.size > maxBytes) {
    throw new Error("حجم تصویر زیاد است؛ لطفاً تصویر کوچک‌تری انتخاب کنید.");
  }
  const base = file.name.replace(/\.[^.]+$/, "") || "product-photo";
  return new File([blob], base + ".jpg", { type: "image/jpeg", lastModified: Date.now() });
}

async function uploadProductPhotos(product, files) {
  if (!files.length) return;
  setStatus("در حال آماده‌سازی و بارگذاری عکس‌ها…");
  try {
    const paths = (product.original_photo_path || "").split("|").filter(Boolean);
    for (const originalFile of files) {
      const file = LOCAL_MODE ? originalFile : await compressImage(originalFile);
      const form = new FormData();
      form.append("file", file, file.name);
      const result = await apiRequest("/media/upload", { method: "POST", body: form });
      paths.push(result.path || "photos/" + file.name);
    }
    await apiRequest("/products/" + product.id, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ original_photo_path: paths.join("|") }),
    });
    await loadCatalog();
    await viewProduct(product.id);
    setStatus("عکس‌های محصول ذخیره شد.");
  } catch (error) {
    showError(error);
  }
}

async function removeProductPhoto(product, index) {
  if (!confirm("این عکس از محصول حذف شود؟")) return;
  const paths = (product.original_photo_path || "").split("|").filter(Boolean);
  paths.splice(index, 1);
  try {
    await apiRequest("/products/" + product.id, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ original_photo_path: paths.join("|") || null }),
    });
    await loadCatalog();
    await viewProduct(product.id);
    setStatus("عکس از محصول حذف شد.");
  } catch (error) {
    showError(error);
  }
}

function addDeletionNavigation() {
  const nav = document.querySelector(".side nav");
  if (nav && !document.getElementById("nav-deletions")) {
    const link = document.createElement("a");
    link.id = "nav-deletions";
    link.href = "#deletions";
    link.textContent = "سوابق حذف";
    nav.append(link);
  }
  const catalog = $("catalog");
  if (catalog && !$("deletions")) {
    catalog.insertAdjacentHTML("afterend",
      '<section id="deletions" class="panel deletion-panel"><div class="panel-head">'
      + "<div><h2>سوابق حذف محصولات</h2><p>حذف‌های انجام‌شده از بات ادمین و پنل وب، همراه با نام ادمین و شناسه گروهی</p></div>"
      + '<span id="deletion-count" class="deletion-count">—</span></div><div id="deletion-table">'
      + '<p class="empty-state">در حال دریافت سوابق…</p></div></section>');
  }
}

function addLogoutButton() {
  if (LOCAL_MODE || $("logout")) return;
  const actions = document.querySelector("header .actions");
  if (!actions) return;
  const button = document.createElement("button");
  button.id = "logout";
  button.type = "button";
  button.textContent = "خروج";
  button.className = "secondary";
  button.onclick = async () => {
    await fetch("/api/auth", { method: "DELETE", credentials: "same-origin" });
    openLogin("برای ادامه دوباره وارد شوید.");
  };
  actions.append(button);
}

function configureSetupDialog() {
  const dialog = $("setup");
  dialog.addEventListener("cancel", (event) => {
    if (loginDialogBusy || !LOCAL_MODE) event.preventDefault();
  });
  if (LOCAL_MODE) {
    dialog.innerHTML = '<form id="local-setup-form"><h2>اتصال داشبورد محلی</h2>'
      + "<p>این تنظیم فقط در همین تب مرورگر ذخیره می‌شود.</p>"
      + '<label>آدرس API<input id="local-api" value="http://127.0.0.1:8000" required></label>'
      + '<label>توکن آنالیتیکس<input id="local-analytics-token" type="password" required></label>'
      + '<label>توکن مدیریت API<input id="local-admin-token" type="password" required></label>'
      + '<label>توکن آپلود عکس<input id="local-media-token" type="password"></label>'
      + '<button type="submit">اتصال</button></form>';
    $("local-setup-form").addEventListener("submit", (event) => {
      event.preventDefault();
      state.api = $("local-api").value.trim().replace(/\/+$/, "");
      state.analyticsToken = $("local-analytics-token").value;
      state.adminApiToken = $("local-admin-token").value;
      state.mediaToken = $("local-media-token").value;
      dialog.close();
      loadAll();
    });
    return;
  }
  dialog.innerHTML = '<form id="login-form"><h2>ورود به پنل مدیریت</h2>'
    + "<p>برای مشاهده اطلاعات فروشگاه رمز داشبورد را وارد کنید.</p>"
    + '<label>رمز داشبورد<input id="dashboard-password" type="password" autocomplete="current-password" required></label>'
    + '<p id="login-error" class="login-error" role="alert"></p>'
    + '<button id="login-submit" type="submit">ورود امن</button></form>';
  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("login-submit");
    const error = $("login-error");
    button.disabled = true;
    error.textContent = "";
    try {
      const response = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify({ password: $("dashboard-password").value }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "ورود ناموفق بود.");
      }
      dialog.close();
      addLogoutButton();
      await loadAll();
    } catch (reason) {
      error.textContent = reason.message || "ورود ناموفق بود.";
    } finally {
      button.disabled = false;
    }
  });
}

function openLogin(message = "") {
  const dialog = $("setup");
  if (LOCAL_MODE) return;
  const error = $("login-error");
  if (error && message) error.textContent = message;
  loginDialogBusy = true;
  if (!dialog.open) dialog.showModal();
  loginDialogBusy = false;
  $("dashboard-password")?.focus();
}

async function loadAll() {
  try {
    await Promise.all([loadAnalytics(), loadCatalog()]);
  } catch (error) {
    showError(error);
  }
}

async function initialize() {
  addDeletionNavigation();
  configureSetupDialog();
  $("refresh").addEventListener("click", loadAll);
  $("days").addEventListener("change", loadAll);
  $("catalog-search").addEventListener("input", () => {
    catalogPage = 0;
    renderCatalog();
  });
  $("add-product").addEventListener("click", () => fillProductForm(null));
  $("product-form").addEventListener("submit", saveProduct);
  if (LOCAL_MODE) {
    $("setup").showModal();
    return;
  }
  try {
    const response = await fetch("/api/auth", { credentials: "same-origin", cache: "no-store" });
    const result = await response.json();
    if (!response.ok || !result.authenticated) {
      openLogin();
      return;
    }
    addLogoutButton();
    await loadAll();
  } catch (error) {
    showError(error);
    openLogin("اتصال ورود پنل برقرار نشد؛ لاگ Function در Vercel را بررسی کنید.");
  }
}

initialize();
