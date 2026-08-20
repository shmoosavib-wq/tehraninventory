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
) = range(12)

# Timeout per stage (seconds)
STAGE_TIMEOUT = 300

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
        "دستورات:\n"
        "/list — مشاهده محصولات\n"
        "/search <کلمه> — جستجوی محصول\n"
    )
    if is_admin(user.id):
        text += "/add — افزودن محصول جدید\n"
        text += "/delete <id> — حذف محصول\n"
    await update.message.reply_text(text)


# ── Command: /help ───────────────────────────────────────────
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 راهنما:\n\n"
        "/list — مشاهده لیست محصولات\n"
        "/search <کلمه> — جستجوی محصول\n"
    )
    if is_admin(update.effective_user.id):
        text += (
            "/add — افزودن محصول جدید\n"
            "/delete <id> — حذف محصول\n\n"
            "/settings — تنظیم نرخ دلار، حمل و ضریب قیمت\n"
            "/price_settings — نمایش تنظیمات قیمت\n\n"
            "مراحل افزودن:\n"
            "نام → قیمت → سایز → وزن → دسته → موقعیت → توضیح → عکس → تأیید\n"
        )
    await update.message.reply_text(text)


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
        "فرمول: (قیمت دلار × نرخ دلار × ضریب) + (وزن به کیلو × هزینه حمل)"
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
        text = (
            f"📦 **{p['name']}**\n"
            f"💰 ${p['price_usd']}  |  📏 {p.get('size', '-')}  |  🏷️ {p.get('category', '-')}\n"
            f"📍 {p.get('location', '-')}  |  ID: {p['id']}"
        )
        # Try to send photo
        raw_paths = p.get("original_photo_path") or ""
        photo_paths = [path for path in raw_paths.split("|") if path]
        sent_photo = False
        for photo_path in photo_paths:
            if os.path.isabs(photo_path):
                full = photo_path
            else:
                full = os.path.join(os.path.dirname(os.path.abspath(__file__)), photo_path)
            if not os.path.exists(full):
                continue
            try:
                with open(full, "rb") as photo_file:
                    await update.effective_message.reply_photo(
                        photo=photo_file, caption=text if not sent_photo else None,
                        parse_mode="Markdown" if not sent_photo else None,
                    )
                sent_photo = True
            except Exception as exc:
                logger.warning("Could not send photo %s: %s", full, exc)

        if not sent_photo:
            await update.effective_message.reply_text(text, parse_mode="Markdown")

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
        entry_points=[CommandHandler("settings", settings_start)],
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

    # Conversation handler for /add
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
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
        CallbackQueryHandler(list_callback, pattern="^list_(next|prev)$")
    )

    print("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
