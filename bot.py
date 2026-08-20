"""
Tehran Inventory Bot
بات مدیریت موجودی تهران — ثبت محصول توسط ادمین + لیست برای همه

اجرا: python bot.py
"""

import os
import logging
from typing import Optional

import httpx
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

load_dotenv()

# ── Configuration ─────────────────────────────────────────────
API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Add it to .env or the environment.")
PHOTOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photos")
os.makedirs(PHOTOS_DIR, exist_ok=True)
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
DEFAULT_SETTINGS = {
    "usd_rate": 200000,
    "shipping_per_kg": 8000000,
    "multiplier": 1.5,
}

# Admin Telegram user IDs — کاما جدا کنید
ADMIN_IDS = set(
    int(x)
    for x in os.environ.get("ADMIN_IDS", "62414083").replace(" ", "").split(",")
    if x
)

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────
(
    NAME, PRICE, SIZE, WEIGHT, CATEGORY,
    LOCATION, DESCRIPTION, PHOTO, CONFIRM,
    SET_USD_RATE, SET_SHIPPING, SET_MULTIPLIER,
    EDIT_FIELD, EDIT_VALUE, ADD_PHOTOS,
) = range(15)

# Timeout per stage (seconds)
STAGE_TIMEOUT = 300

BTN_LIST = "📦 لیست محصولات"
BTN_SEARCH = "🔍 جستجوی محصول"
BTN_ADD = "➕ افزودن محصول"
BTN_SETTINGS = "⚙️ تنظیم قیمت"
BTN_PRICE_VIEW = "💰 قیمت فعلی"
BTN_IMPORT = "📥 ورود اکسل"
BTN_MANAGE = "🛠 مدیریت محصولات"


def main_menu(user_id: int) -> ReplyKeyboardMarkup:
    rows = [[BTN_LIST, BTN_SEARCH]]
    if is_admin(user_id):
        rows.append([BTN_ADD, BTN_IMPORT])
        rows.append([BTN_SETTINGS])
        rows.append([BTN_PRICE_VIEW])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ── Helpers ───────────────────────────────────────────────────
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def load_settings() -> dict:
    import json
    if not os.path.exists(SETTINGS_FILE):
        return DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
            values = json.load(file)
        return {**DEFAULT_SETTINGS, **values}
    except (OSError, ValueError):
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict) -> None:
    import json
    with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=2)


def calculate_toman(price_usd: float, weight_grams: float | None) -> float:
    settings = load_settings()
    base = price_usd * settings["usd_rate"] * settings["multiplier"]
    shipping = ((weight_grams or 0) / 1000) * settings["shipping_per_kg"]
    return base + shipping


def toman(value: float) -> str:
    return f"{round(value):,} تومان"


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]
    )


def summary_text(d: dict) -> str:
    """Build a human-readable summary of product details."""
    parts = [f"📦 خلاصه محصول:"]
    parts.append(f"  نام: {d.get('name', '-')}")
    parts.append(f"  قیمت: ${d.get('price_usd', '-')}")
    if d.get("price_usd") is not None:
        parts.append(f"  قیمت نهایی: {toman(calculate_toman(d['price_usd'], d.get('weight_grams')))}")
    if d.get("size"):
        parts.append(f"  سایز: {d['size']}")
    weight = d.get("weight_grams")
    if weight:
        parts.append(f"  وزن: {weight} گرم ({weight / 1000:.2f} کیلو)")
    if d.get("category"):
        parts.append(f"  دسته: {d['category']}")
    if d.get("location"):
        parts.append(f"  موقعیت: {d['location']}")
    if d.get("description"):
        parts.append(f"  توضیحات: {d['description']}")
    photo_count = len(d.get("photo_paths", []))
    parts.append(f"  عکس: {photo_count} عدد" if photo_count else "  عکس: ندارد")
    return "\n".join(parts)


async def call_api(
    method: str, endpoint: str, data: Optional[dict] = None
) -> dict | list:
    async with httpx.AsyncClient() as client:
        url = f"{API_BASE_URL}{endpoint}"
        if method == "GET":
            resp = await client.get(url, timeout=15)
        elif method == "POST":
            resp = await client.post(url, json=data, timeout=15)
        elif method == "PUT":
            resp = await client.put(url, json=data, timeout=15)
        elif method == "DELETE":
            resp = await client.delete(url, timeout=15)
        else:
            raise ValueError(f"Unknown method {method}")
        resp.raise_for_status()
        return resp.json()


async def download_photo(update: Update, filename: str) -> str | None:
    """Download the largest photo and save to PHOTOS_DIR. Return path or None."""
    if not update.message or not update.message.photo:
        return None
    photo = update.message.photo[-1]  # largest
    file = await photo.get_file()
    filepath = os.path.join(PHOTOS_DIR, filename)
    await file.download_to_drive(filepath)
    return filepath


# ── Command: /start ──────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    admin_status = "✅ ادمین" if is_admin(user.id) else "👥 کاربر عادی"
    text = (
        f"سلام {user.first_name}!\n\n"
        f"سطح دسترسی: {admin_status}\n\n"
        "یکی از گزینه‌های زیر را انتخاب کنید:"
    )
    await update.message.reply_text(text, reply_markup=main_menu(user.id))


# ── Command: /help ───────────────────────────────────────────
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📖 از دکمه‌های منو استفاده کنید."
    if is_admin(update.effective_user.id):
        text += "\nبرای ثبت محصول: افزودن محصول\nبرای تنظیم قیمت: تنظیم قیمت"
    await update.message.reply_text(
        text, reply_markup=main_menu(update.effective_user.id)
    )


async def settings_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ این دستور فقط برای ادمین است.")
        return ConversationHandler.END
    settings = load_settings()
    context.user_data["editing_settings"] = settings
    await update.message.reply_text(
        "⚙️ تنظیمات محاسبه قیمت\n\n"
        f"نرخ فعلی دلار: {settings['usd_rate']:,} تومان\n"
        "نرخ جدید دلار را به تومان وارد کنید:",
        reply_markup=cancel_keyboard(),
    )
    return SET_USD_RATE


async def settings_usd_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        value = float(update.message.text.replace(",", "").strip())
        if value <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ نرخ دلار باید عددی بزرگ‌تر از صفر باشد.")
        return SET_USD_RATE
    context.user_data["editing_settings"]["usd_rate"] = value
    await update.message.reply_text(
        "هزینه حمل هر کیلوگرم را به تومان وارد کنید:",
        reply_markup=cancel_keyboard(),
    )
    return SET_SHIPPING


async def settings_shipping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        value = float(update.message.text.replace(",", "").strip())
        if value < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ هزینه حمل باید عدد صفر یا بزرگ‌تر باشد.")
        return SET_SHIPPING
    context.user_data["editing_settings"]["shipping_per_kg"] = value
    await update.message.reply_text(
        "ضریب قیمت را وارد کنید (مثلاً 1.5):",
        reply_markup=cancel_keyboard(),
    )
    return SET_MULTIPLIER


async def settings_multiplier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        value = float(update.message.text.strip())
        if value <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ ضریب باید عددی بزرگ‌تر از صفر باشد.")
        return SET_MULTIPLIER
    settings = context.user_data["editing_settings"]
    settings["multiplier"] = value
    save_settings(settings)
    context.user_data.pop("editing_settings", None)
    await update.message.reply_text(
        "✅ تنظیمات ذخیره شد.\n\n"
        f"نرخ دلار: {settings['usd_rate']:,.0f} تومان\n"
        f"حمل: {settings['shipping_per_kg']:,.0f} تومان/کیلوگرم\n"
        f"ضریب: {settings['multiplier']}\n\n"
        "فرمول: (قیمت دلار × نرخ دلار × ضریب) + (وزن به کیلو × هزینه حمل)",
        reply_markup=main_menu(update.effective_user.id),
    )
    return ConversationHandler.END


async def cmd_price_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ این دستور فقط برای ادمین است.")
        return
    settings = load_settings()
    await update.message.reply_text(
        "⚙️ تنظیمات فعلی قیمت:\n"
        f"نرخ دلار: {settings['usd_rate']:,.0f} تومان\n"
        f"حمل: {settings['shipping_per_kg']:,.0f} تومان/کیلوگرم\n"
        f"ضریب: {settings['multiplier']}\n\n"
        "برای تغییر: /settings"
    )


async def import_excel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ این گزینه فقط برای ادمین است.")
        return
    context.user_data["awaiting_excel"] = True
    await update.message.reply_text(
        "📥 فایل Excel با پسوند xlsx را ارسال کنید.\n"
        "قیمت نهایی از تنظیمات بات محاسبه می‌شود و از Excel خوانده نمی‌شود."
    )


def _excel_value(row: dict, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


async def import_excel_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("awaiting_excel", False):
        return
    document = update.message.document
    if not document or not document.file_name.lower().endswith(".xlsx"):
        await update.message.reply_text("❌ فقط فایل Excel با پسوند xlsx قابل قبول است.")
        return

    temp_path = os.path.join(PHOTOS_DIR, f"__import_{document.file_unique_id}.xlsx")
    try:
        file = await document.get_file()
        await file.download_to_drive(temp_path)
        from openpyxl import load_workbook
        workbook = load_workbook(temp_path, read_only=True, data_only=True)
        sheet = workbook["محصولات"] if "محصولات" in workbook.sheetnames else workbook.worksheets[0]
        rows = sheet.iter_rows(min_row=5, values_only=True)
        headers = [cell.value for cell in sheet[4]]
        imported = 0
        skipped = 0
        for values in rows:
            row = {str(headers[index]).strip(): value for index, value in enumerate(values) if index < len(headers)}
            name = _excel_value(row, "نام محصول", "نام")
            price = _excel_value(row, "قیمت خرید (دلار)", "قیمت دلار", "قیمت")
            if not name or price in (None, ""):
                if any(value not in (None, "") for value in values):
                    skipped += 1
                continue
            try:
                payload = {
                    "name": str(name).strip(),
                    "price_usd": float(price),
                }
                field_map = {
                    "توضیحات دستی": "description",
                    "سایز": "size",
                    "وزن (گرم)": "weight_grams",
                    "موقعیت": "location",
                    "دسته‌بندی": "category",
                    "لینک تلگرام ۱": "telegram_link_1",
                    "لینک تلگرام ۲": "telegram_link_2",
                }
                for source, target in field_map.items():
                    value = row.get(source)
                    if value not in (None, ""):
                        payload[target] = float(value) if target == "weight_grams" else str(value).strip()
                await call_api("POST", "/products", data=payload)
                imported += 1
            except (TypeError, ValueError, httpx.HTTPError):
                skipped += 1
        workbook.close()
        await update.message.reply_text(
            f"✅ ورود Excel تمام شد.\nمحصول ثبت‌شده: {imported}\nردیف ردشده: {skipped}\n\n"
            "حالا از «🛠 مدیریت محصولات» برای ویرایش یا افزودن عکس استفاده کنید.",
            reply_markup=main_menu(update.effective_user.id),
        )
    except Exception as exc:
        logger.exception("Excel import failed: %s", exc)
        await update.message.reply_text("❌ خواندن فایل Excel ناموفق بود.")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


async def manage_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ این گزینه فقط برای ادمین است.")
        return
    try:
        products = await call_api("GET", "/products")
    except Exception:
        await update.message.reply_text("❌ دریافت محصولات ناموفق بود.")
        return
    if not products:
        await update.message.reply_text("📭 محصولی وجود ندارد.")
        return
    for product in products:
        buttons = [
            [
                InlineKeyboardButton("✏️ ویرایش", callback_data=f"edit_product:{product['id']}"),
                InlineKeyboardButton("📷 افزودن عکس", callback_data=f"photo_product:{product['id']}"),
            ],
            [InlineKeyboardButton("🗑 حذف", callback_data=f"delete_product:{product['id']}")],
        ]
        await update.message.reply_text(
            f"📦 {product['name']}\nID: {product['id']} | ${product['price_usd']}",
            reply_markup=InlineKeyboardMarkup(buttons),
        )


async def manage_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.message.reply_text("⛔ فقط ادمین دسترسی دارد.")
        return
    action, product_id_text = query.data.split(":", 1)
    product_id = int(product_id_text)
    if action == "delete_product":
        await call_api("DELETE", f"/products/{product_id}")
        await query.message.reply_text("✅ محصول حذف شد.")
        return
    if action == "edit_product":
        context.user_data["editing_product_id"] = product_id
        await query.message.reply_text(
            "فیلدی که می‌خواهید تغییر کند را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("نام", callback_data="edit_field:name"),
                 InlineKeyboardButton("قیمت دلار", callback_data="edit_field:price_usd")],
                [InlineKeyboardButton("سایز", callback_data="edit_field:size"),
                 InlineKeyboardButton("وزن", callback_data="edit_field:weight_grams")],
                [InlineKeyboardButton("دسته", callback_data="edit_field:category"),
                 InlineKeyboardButton("موقعیت", callback_data="edit_field:location")],
                [InlineKeyboardButton("توضیحات", callback_data="edit_field:description")],
            ]),
        )
        return EDIT_FIELD
    elif action == "photo_product":
        context.user_data["photo_product_id"] = product_id
        context.user_data["photo_paths"] = []
        await query.message.reply_text(
            "📷 عکس‌های محصول را یکی‌یکی بفرستید، سپس «اتمام عکس‌ها» را بزنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ اتمام عکس‌ها", callback_data="finish_manage_photos")],
                [InlineKeyboardButton("❌ لغو", callback_data="cancel")],
            ]),
        )
        return ADD_PHOTOS


async def edit_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.split(":", 1)[1]
    context.user_data["editing_field"] = field
    labels = {
        "name": "نام جدید",
        "price_usd": "قیمت جدید به دلار",
        "size": "سایز جدید",
        "weight_grams": "وزن جدید به گرم",
        "category": "دسته‌بندی جدید",
        "location": "موقعیت جدید",
        "description": "توضیحات جدید",
    }
    await query.message.reply_text(f"{labels[field]} را ارسال کنید:")
    return EDIT_VALUE


async def edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    product_id = context.user_data.get("editing_product_id")
    field = context.user_data.get("editing_field")
    value = update.message.text.strip()
    try:
        if field in ("price_usd", "weight_grams"):
            value = float(value.replace(",", ""))
        await call_api("PUT", f"/products/{product_id}", data={field: value})
        await update.message.reply_text(
            "✅ محصول به‌روزرسانی شد.", reply_markup=main_menu(update.effective_user.id)
        )
    except (ValueError, httpx.HTTPError):
        await update.message.reply_text("❌ مقدار واردشده معتبر نیست.")
        return EDIT_VALUE
    context.user_data.pop("editing_product_id", None)
    context.user_data.pop("editing_field", None)
    return ConversationHandler.END


async def manage_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    product_id = context.user_data.get("photo_product_id")
    if not product_id:
        return
    product = await call_api("GET", f"/products/{product_id}")
    existing = [p for p in (product.get("original_photo_path") or "").split("|") if p]
    paths = context.user_data.setdefault("photo_paths", [])
    filename = f"product_{product_id}_{int(__import__('time').time() * 1000)}_{len(existing) + len(paths) + 1}.jpg"
    saved = await download_photo(update, filename)
    if saved:
        paths.append(f"photos/{filename}")
    await update.message.reply_text(f"✅ عکس {len(paths)} دریافت شد.")
    return ADD_PHOTOS


async def finish_manage_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = context.user_data.get("photo_product_id")
    new_paths = context.user_data.get("photo_paths", [])
    if product_id and new_paths:
        product = await call_api("GET", f"/products/{product_id}")
        existing = [p for p in (product.get("original_photo_path") or "").split("|") if p]
        await call_api(
            "PUT",
            f"/products/{product_id}",
            data={"original_photo_path": "|".join(existing + new_paths)},
        )
    context.user_data.pop("photo_product_id", None)
    context.user_data.pop("photo_paths", None)
    await query.message.reply_text("✅ عکس‌ها به محصول اضافه شدند.")
    return ConversationHandler.END


async def menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text == BTN_LIST:
        await cmd_list(update, context)
    elif text == BTN_SEARCH:
        context.user_data["awaiting_search"] = True
        await update.message.reply_text(
            "🔍 نام، دسته یا ویژگی محصول را بنویسید:",
            reply_markup=ReplyKeyboardRemove(),
        )
    elif text == BTN_IMPORT:
        await import_excel_start(update, context)
    elif text == BTN_PRICE_VIEW:
        await cmd_price_settings(update, context)


async def receive_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("awaiting_search", False):
        return
    keyword = update.message.text.strip()
    products = await call_api("GET", "/products")
    kw = keyword.lower()
    results = [
        p for p in products
        if kw in p.get("name", "").lower()
        or kw in p.get("description", "").lower()
        or kw in p.get("category", "").lower()
    ]
    if not results:
        await update.message.reply_text(f"🔍 نتیجه‌ای برای «{keyword}» پیدا نشد.")
    else:
        text = f"🔍 نتایج جستجو برای «{keyword}» ({len(results)} مورد):\n\n"
        for index, product in enumerate(results[:10], 1):
            text += (
                f"{index}. {product['name']}\n"
                f"   💰 ${product['price_usd']} | 🏷️ {product.get('category', '-')}"
                f" | 📍 {product.get('location', '-')} | ID: {product['id']}\n\n"
            )
        await update.message.reply_text(text)
    await update.message.reply_text(
        "از منوی زیر انتخاب کنید:", reply_markup=main_menu(update.effective_user.id)
    )


# ── Conversation: /add ───────────────────────────────────────
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ این دستور فقط برای ادمین است.")
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["product"] = {}
    await update.message.reply_text(
        "➕ افزودن محصول جدید\n\n"
        "مرحله ۱: نام محصول را بفرستید.",
        reply_markup=cancel_keyboard(),
    )
    return NAME


async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["product"]["name"] = update.message.text.strip()
    await update.message.reply_text(
        "مرحله ۲: قیمت به دلار؟ (فقط عدد)",
        reply_markup=cancel_keyboard(),
    )
    return PRICE


async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "❌ قیمت باید عدد باشد. دوباره بفرستید.",
            reply_markup=cancel_keyboard(),
        )
        return PRICE
    context.user_data["product"]["price_usd"] = price
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("بدون سایز", callback_data="skip_size")],
            [InlineKeyboardButton("❌ لغو", callback_data="cancel")],
        ]
    )
    await update.message.reply_text(
        "مرحله ۳: سایز؟", reply_markup=kb
    )
    return SIZE


async def add_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["product"]["size"] = update.message.text.strip()
    return await _goto_weight(update)


async def add_size_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _goto_weight(update)


async def _goto_weight(update: Update):
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("نمی‌دانم", callback_data="skip_weight")],
            [InlineKeyboardButton("❌ لغو", callback_data="cancel")],
        ]
    )
    if update.callback_query:
        try:
            await update.callback_query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await update.effective_message.reply_text(
        "مرحله ۴: وزن به گرم؟ (فقط عدد)",
        reply_markup=kb,
    )
    return WEIGHT


async def add_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        w = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "❌ وزن باید عدد باشد. دوباره بفرستید.",
            reply_markup=cancel_keyboard(),
        )
        return WEIGHT
    context.user_data["product"]["weight_grams"] = w
    return await _goto_category(update)


async def add_weight_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _goto_category(update)


async def _goto_category(update: Update):
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("کیف", callback_data="cat_کیف"),
                InlineKeyboardButton("کفش", callback_data="cat_کفش"),
                InlineKeyboardButton("ورزشی", callback_data="cat_ورزشی"),
            ],
            [
                InlineKeyboardButton("آرایشی بهداشتی", callback_data="cat_آرایشی بهداشتی"),
                InlineKeyboardButton("اکسسوری", callback_data="cat_اکسسوری"),
            ],
            [
                InlineKeyboardButton("دارو و سلامتی", callback_data="cat_دارو و سلامتی"),
                InlineKeyboardButton("سایر", callback_data="cat_سایر"),
            ],
            [InlineKeyboardButton("❌ لغو", callback_data="cancel")],
        ]
    )
    await update.effective_message.reply_text(
        "مرحله ۵: دسته‌بندی؟", reply_markup=kb
    )
    return CATEGORY


async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data.replace("cat_", "", 1)
    context.user_data["product"]["category"] = cat
    return await _goto_location(update, query)


async def _goto_location(update: Update, query=None):
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("تهران", callback_data="loc_تهران"),
                InlineKeyboardButton("کانادا", callback_data="loc_کانادا"),
            ],
            [InlineKeyboardButton("❌ لغو", callback_data="cancel")],
        ]
    )
    msg_target = query.message if query else update.effective_message
    await msg_target.reply_text("مرحله ۶: موقعیت؟", reply_markup=kb)
    return LOCATION


async def add_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    loc = query.data.replace("loc_", "", 1)
    context.user_data["product"]["location"] = loc
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("بدون توضیح", callback_data="skip_desc")],
            [InlineKeyboardButton("❌ لغو", callback_data="cancel")],
        ]
    )
    await query.message.reply_text(
        "مرحله ۷: توضیحات؟", reply_markup=kb
    )
    return DESCRIPTION


async def add_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["product"]["description"] = update.message.text.strip()
    return await _goto_photo(update)


async def add_description_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _goto_photo(update)


async def _goto_photo(update: Update):
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("بدون عکس", callback_data="skip_photo")],
            [InlineKeyboardButton("❌ لغو", callback_data="cancel")],
        ]
    )
    await update.effective_message.reply_text(
        "مرحله ۸: عکس محصول را بفرستید.\n"
        "می‌توانید چند عکس پشت‌سرهم ارسال کنید؛ بعد دکمه «اتمام عکس‌ها» را بزنید.",
        reply_markup=kb,
    )
    return PHOTO


async def add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    product = context.user_data["product"]
    photo_paths = product.setdefault("photo_paths", [])
    name_slug = "".join(c if c.isalnum() else "_" for c in product.get("name", "product"))
    import time
    filename = f"{name_slug}_{int(time.time() * 1000)}_{len(photo_paths) + 1}.jpg"
    filepath = await download_photo(update, filename)
    if filepath:
        relative_path = f"photos/{filename}"
        photo_paths.append(relative_path)
        product["original_photo_path"] = "|".join(photo_paths)
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ اتمام عکس‌ها", callback_data="finish_photos")],
            [InlineKeyboardButton("❌ لغو", callback_data="cancel")],
        ]
    )
    await update.message.reply_text(
        f"✅ عکس {len(photo_paths)} ذخیره شد. عکس بعدی را بفرستید یا اتمام عکس‌ها را بزنید.",
        reply_markup=kb,
    )
    return PHOTO


async def add_photo_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await _goto_confirm(update, context)


async def add_photo_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await _goto_confirm(update, context, query)


async def _goto_confirm(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query=None,
):
    product = context.user_data["product"]
    text = summary_text(product) + "\n\nثبت نهایی؟"
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ تأیید و ثبت", callback_data="confirm_save"),
                InlineKeyboardButton("✏️ از اول", callback_data="confirm_redo"),
            ],
            [InlineKeyboardButton("❌ لغو", callback_data="cancel")],
        ]
    )
    msg_target = query.message if query else update.effective_message
    await msg_target.reply_text(text, reply_markup=kb)
    return CONFIRM


async def add_confirm_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product = context.user_data["product"]

    # Build API payload
    payload = {
        "name": product["name"],
        "price_usd": product["price_usd"],
    }
    for field in ("size", "weight_grams", "location", "category", "description",
                  "original_photo_path"):
        if product.get(field):
            payload[field] = product[field]

    try:
        result = await call_api("POST", "/products", data=payload)
        text = (
            f"✅ محصول با موفقیت ثبت شد!\n\n"
            f"ID: {result['id']}\n"
            f"نام: {result['name']}\n"
            f"قیمت: ${result['price_usd']}\n"
            f"\nمشاهده: /list"
        )
        await query.message.reply_text(text)
    except Exception as exc:
        logger.error("Error saving product: %s", exc)
        await query.message.reply_text("❌ خطا در ثبت محصول. دوباره تلاش کنید.")

    context.user_data.clear()
    return ConversationHandler.END


async def add_confirm_redo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["product"] = {}
    await query.message.reply_text(
        "شروع از اول...\n\nمرحله ۱: نام محصول را بفرستید.",
        reply_markup=cancel_keyboard(),
    )
    return NAME


# ── Cancel handler (shared) ──────────────────────────────────
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    context.user_data.clear()
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            "❌ عملیات لغو شد.", reply_markup=ReplyKeyboardRemove()
        )
    return ConversationHandler.END


# ── Timeout handler ───────────────────────────────────────────
async def stage_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.effective_message:
        await update.effective_message.reply_text(
            "⏰ زمان انتظار تمام شد. عملیات لغو شد.\n"
            "برای شروع دوباره: /add"
        )
    return ConversationHandler.END


# ── Command: /list (paginated, with photos) ──────────────────
LIST_PAGE_SIZE = 5


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        products = await call_api("GET", "/products")
    except Exception as exc:
        logger.error("Error listing products: %s", exc)
        await update.message.reply_text("❌ خطا در دریافت لیست محصولات.")
        return

    if not products:
        await update.message.reply_text("📭 محصولی موجود نیست.")
        return

    context.user_data["list_products"] = products
    context.user_data["list_page"] = 0
    await _send_product_page(update, context, 0)


async def _send_product_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    products = context.user_data.get("list_products", [])
    total = len(products)
    start = page * LIST_PAGE_SIZE
    end = start + LIST_PAGE_SIZE
    page_items = products[start:end]

    for idx, p in enumerate(page_items, start=start):
        final_price = calculate_toman(
            p.get("price_usd", 0),
            p.get("weight_grams"),
        )
        text = (
            f"📦 **{p['name']}**\n"
            f"💰 ${p['price_usd']}  |  📏 {p.get('size', '-')}  |  🏷️ {p.get('category', '-')}\n"
            f"📍 {p.get('location', '-')}  |  ID: {p['id']}\n"
            f"💵 قیمت نهایی: {toman(final_price)}"
        )
        # Try to send photo
        raw_paths = p.get("original_photo_path") or ""
        photo_paths = [path for path in raw_paths.split("|") if path]
        existing_paths = []
        for photo_path in photo_paths:
            if os.path.isabs(photo_path):
                full = photo_path
            else:
                full = os.path.join(os.path.dirname(os.path.abspath(__file__)), photo_path)
            if not os.path.exists(full):
                continue
            existing_paths.append(full)

        sent_photo = False
        controls = None
        if is_admin(update.effective_user.id):
            controls = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✏️ ویرایش", callback_data=f"edit_product:{p['id']}"),
                    InlineKeyboardButton("📷 افزودن عکس", callback_data=f"photo_product:{p['id']}"),
                ],
                [InlineKeyboardButton("🗑 حذف", callback_data=f"delete_product:{p['id']}")],
            ])
        if existing_paths:
            handles = []
            try:
                for full in existing_paths:
                    handles.append(open(full, "rb"))
                media = [
                    InputMediaPhoto(
                        media=handle,
                        caption=text if index == 0 else None,
                        parse_mode="Markdown" if index == 0 else None,
                    )
                    for index, handle in enumerate(handles)
                ]
                await update.effective_message.reply_media_group(media=media)
                sent_photo = True
                if controls:
                    await update.effective_message.reply_text(
                        "عملیات محصول را انتخاب کنید:",
                        reply_markup=controls,
                    )
            except Exception as exc:
                logger.warning("Could not send product album: %s", exc)
            finally:
                for handle in handles:
                    handle.close()

        if not sent_photo:
            await update.effective_message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=controls,
            )

    # Navigation buttons
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"list_prev"))
    if end < total:
        buttons.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"list_next"))
    if buttons:
        kb = InlineKeyboardMarkup([buttons])
        await update.effective_message.reply_text(
            f"صفحه {page + 1} — محصول {start + 1}-{min(end, total)} از {total}",
            reply_markup=kb,
        )
    else:
        await update.effective_message.reply_text(
            f"صفحه {page + 1} — محصول {start + 1}-{min(end, total)} از {total}"
        )


async def list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = context.user_data.get("list_page", 0)
    if query.data == "list_next":
        page += 1
    elif query.data == "list_prev":
        page = max(0, page - 1)
    context.user_data["list_page"] = page
    await _send_product_page(update, context, page)


# ── Command: /delete <id> ────────────────────────────────────
async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ این دستور فقط برای ادمین است.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("طریقه استفاده:\n/delete <id>")
        return

    try:
        pid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ ID باید عدد باشد.")
        return

    try:
        await call_api("DELETE", f"/products/{pid}")
        await update.message.reply_text(f"✅ محصول {pid} حذف شد.")
    except Exception as exc:
        logger.error("Error deleting product: %s", exc)
        await update.message.reply_text("❌ خطا در حذف محصول.")


# ── Command: /search <keyword> ───────────────────────────────
async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "طریقه استفاده:\n/search <کلمه کلیدی>"
        )
        return

    keyword = " ".join(context.args).strip()
    try:
        products = await call_api("GET", "/products")
    except Exception as exc:
        logger.error("Error searching products: %s", exc)
        await update.message.reply_text("❌ خطا در جستجو.")
        return

    kw = keyword.lower()
    results = [
        p for p in products
        if kw in p.get("name", "").lower()
        or kw in p.get("description", "").lower()
        or kw in p.get("category", "").lower()
    ]

    if not results:
        await update.message.reply_text(f"🔍 نتیجه‌ای برای «{keyword}» پیدا نشد.")
        return

    text = f"🔍 نتایج جستجو برای «{keyword}» ({len(results)} مورد):\n\n"
    for i, p in enumerate(results[:10], 1):
        text += (
            f"{i}. {p['name']}\n"
            f"   💰 ${p['price_usd']} | 🏷️ {p.get('category', '-')} | "
            f"📍 {p.get('location', '-')} | ID: {p['id']}\n\n"
        )
    await update.message.reply_text(text)


# ── Main ─────────────────────────────────────────────────────
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    settings_handler = ConversationHandler(
        entry_points=[
            CommandHandler("settings", settings_start),
            MessageHandler(filters.Regex(f"^{BTN_SETTINGS}$"), settings_start),
        ],
        states={
            SET_USD_RATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_usd_rate),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            SET_SHIPPING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_shipping),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            SET_MULTIPLIER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_multiplier),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
        ],
        conversation_timeout=STAGE_TIMEOUT,
    )
    application.add_handler(settings_handler)

    product_management_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                manage_product_callback,
                pattern=r"^(edit_product|photo_product):\d+$",
            )
        ],
        states={
            EDIT_FIELD: [
                CallbackQueryHandler(edit_field_callback, pattern="^edit_field:")
            ],
            EDIT_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            ADD_PHOTOS: [
                MessageHandler(filters.PHOTO, manage_photo_message),
                CallbackQueryHandler(
                    finish_manage_photos, pattern="^finish_manage_photos$"
                ),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
        ],
        conversation_timeout=STAGE_TIMEOUT,
        allow_reentry=True,
    )
    application.add_handler(product_management_handler)

    # Conversation handler for /add
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("add", add_start),
            MessageHandler(filters.Regex(f"^{BTN_ADD}$"), add_start),
        ],
        states={
            NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_name),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_price),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            SIZE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_size),
                CallbackQueryHandler(add_size_skip, pattern="^skip_size$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            WEIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_weight),
                CallbackQueryHandler(add_weight_skip, pattern="^skip_weight$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            CATEGORY: [
                CallbackQueryHandler(add_category, pattern="^cat_"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            LOCATION: [
                CallbackQueryHandler(add_location, pattern="^loc_"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_description),
                CallbackQueryHandler(add_description_skip, pattern="^skip_desc$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            PHOTO: [
                MessageHandler(filters.PHOTO, add_photo),
                CallbackQueryHandler(add_photo_skip, pattern="^skip_photo$"),
                CallbackQueryHandler(add_photo_finish, pattern="^finish_photos$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            CONFIRM: [
                CallbackQueryHandler(add_confirm_save, pattern="^confirm_save$"),
                CallbackQueryHandler(add_confirm_redo, pattern="^confirm_redo$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
        ],
        conversation_timeout=STAGE_TIMEOUT,
    )
    application.add_handler(conv_handler)

    # Regular commands
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("list", cmd_list))
    application.add_handler(CommandHandler("delete", cmd_delete))
    application.add_handler(CommandHandler("search", cmd_search))
    application.add_handler(CommandHandler("price_settings", cmd_price_settings))
    application.add_handler(
        MessageHandler(filters.Document.FileExtension("xlsx"), import_excel_document)
    )
    application.add_handler(
        CallbackQueryHandler(
            manage_product_callback, pattern=r"^delete_product:\d+$"
        )
    )
    application.add_handler(
            MessageHandler(
            filters.Regex(
                f"^(?:{BTN_LIST}|{BTN_SEARCH}|{BTN_IMPORT}|{BTN_PRICE_VIEW})$"
            ),
            menu_button,
        )
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, receive_search_text)
    )
    application.add_handler(
        CallbackQueryHandler(list_callback, pattern="^list_(next|prev)$")
    )

    print("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
