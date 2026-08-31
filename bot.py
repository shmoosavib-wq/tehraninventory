"""
Tehran Inventory Bot
بات مدیریت موجودی تهران — ثبت محصول توسط ادمین + لیست برای همه

اجرا: python bot.py
"""

import os
import logging
import re
import base64
import json
from difflib import SequenceMatcher
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
MEDIA_UPLOAD_TOKEN = os.environ.get("MEDIA_UPLOAD_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.environ.get(
    "OPENAI_BASE_URL", "https://api.gapgpt.app/v1"
).rstrip("/")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "glm-4-flash")
AI_PROMPT_VERSION = "v2"
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Add it to .env or the environment.")
PHOTOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photos")
os.makedirs(PHOTOS_DIR, exist_ok=True)
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
ADMIN_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admins.json")
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

SUPER_ADMIN_IDS = set(int(x) for x in os.environ.get("SUPER_ADMIN_IDS", "62414083").replace(" ", "").split(",") if x)

def is_super_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMIN_IDS

def category_access(user_id: int) -> set[str]:
    if is_super_admin(user_id):
        return {"*"}
    config = load_admin_config()
    saved = config.get(str(user_id))
    if isinstance(saved, dict):
        return set(saved.get("categories") or [])
    raw = os.environ.get("ADMIN_CATEGORY_ACCESS", "")
    for entry in raw.split(";"):
        if ":" not in entry: continue
        uid, cats = entry.split(":", 1)
        if uid.strip() == str(user_id): return {c.strip() for c in cats.split("|") if c.strip()}
    return set()

def can_manage_product(user_id: int, product: dict) -> bool:
    return is_super_admin(user_id) or (product.get("category") or "سایر").strip() in category_access(user_id)

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
    EDIT_FIELD, EDIT_VALUE, ADD_PHOTOS, PHOTO_AI,
    QUICK_TEXT, QUICK_PHOTOS, QUICK_CONFIRM, QUICK_EDIT,
) = range(20)

# Timeout per stage (seconds)
STAGE_TIMEOUT = 300

BTN_LIST = "📦 لیست محصولات"
BTN_SEARCH = "🔍 جستجوی محصول"
BTN_ADD = "➕ افزودن محصول"
BTN_QUICK_ADD = "⚡ ثبت سریع محصول"
BTN_ADD_PHOTO = "🖼 افزودن با عکس"
BTN_ADD_HELP = "ℹ️ راهنمای ثبت محصول"
BTN_ADMIN_MANAGE = "👥 مدیریت ادمین‌ها"
BTN_ADMIN_REPORT = "📊 گزارش فعالیت ادمین‌ها"
ADMIN_CATEGORIES = ["کفش", "کیف", "لباس", "ورزشی", "آرایشی بهداشتی", "اکسسوری", "دارو و سلامتی", "عطر و ادکلن"]
BTN_SETTINGS = "⚙️ تنظیم قیمت"
BTN_PRICE_VIEW = "💰 قیمت فعلی"
BTN_IMPORT = "📥 ورود اکسل"
BTN_MANAGE = "🛠 مدیریت محصولات"


def main_menu(user_id: int) -> ReplyKeyboardMarkup:
    rows = [[BTN_LIST, BTN_SEARCH]]
    if is_admin(user_id):
        rows.append([BTN_ADD, BTN_ADD_PHOTO])
        rows.append([BTN_QUICK_ADD])
        rows.append([BTN_ADD_HELP])
        if is_super_admin(user_id):
            rows.append([BTN_ADMIN_MANAGE, BTN_ADMIN_REPORT])
        rows.append([BTN_IMPORT])
        rows.append([BTN_SETTINGS])
        rows.append([BTN_PRICE_VIEW])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def normalize_search_text(value: str) -> str:
    value = (value or "").lower()
    value = value.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
    value = value.replace("ۀ", "ه").replace("ة", "ه").replace("ؤ", "و")
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = re.sub(r"[\u064B-\u065F\u0670]", "", value)
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def normalize_search_text_v2(value: str) -> str:
    value = (value or "").lower()
    for source, target in (
        ("\u064a", "\u06cc"), ("\u0649", "\u06cc"), ("\u0643", "\u06a9"),
        ("\u0629", "\u0647"), ("\u0624", "\u0648"), ("\u0623", "\u0627"),
        ("\u0625", "\u0627"), ("\u0622", "\u0627"),
    ):
        value = value.replace(source, target)
    value = re.sub(r"[\u064b-\u065f\u0670]", "", value)
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    aliases = {
        "نایک": "nike", "نایکی": "nike", "nike": "nike",
        "آدیداس": "adidas", "ادیداس": "adidas", "adidas": "adidas",
        "پوما": "puma", "پیوما": "puma", "puma": "puma",
        "اسمارو": "esmaro", "esmaro": "esmaro",
        "شنل": "chanel", "چنل": "chanel", "chanel": "chanel",
        "channel": "chanel", "بلو": "bleu", "bleu": "bleu",
    }
    for source, target in aliases.items():
        value = re.sub(rf"(?<!\w){re.escape(source)}(?!\w)", target, value)
    return value


def search_token_similarity(query_token: str, searchable_tokens: list[str]) -> float:
    if query_token in searchable_tokens:
        return 1.0
    if len(query_token) < 3:
        return 0.0
    return max(
        (SequenceMatcher(None, query_token, token).ratio() for token in searchable_tokens),
        default=0.0,
    )


def normalize_query_for_search(value: str) -> str:
    value = normalize_search_text_v2(value)
    replacements = {
        "دخترانه": "بچگانه",
        "دختر": "بچگانه",
        "قرص": "دارو",
        "مسکن": "درد",
        "ضددرد": "درد",
        "ضد درد": "درد",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return re.sub(r"\s+", " ", value).strip()


def product_size(product: dict) -> str:
    explicit = str(product.get("size") or "").strip()
    if explicit:
        return explicit
    description = product.get("description") or ""
    match = re.search(
        r"(?:سایز|سایس|اندازه|size)\s*[:：\-]?\s*([0-9۰-۹]+(?:\s*[-/]\s*[0-9۰-۹]+)?)",
        description,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else "-"


def clean_product_description(product: dict) -> str:
    """Remove duplicated structured metadata from imported free-form text."""
    raw = str(product.get("description") or "").replace("\r\n", "\n")
    name = normalize_search_text_v2(str(product.get("name") or ""))
    cleaned = []
    for line in raw.splitlines():
        stripped = line.strip()
        normalized = normalize_search_text_v2(stripped)
        if not stripped:
            continue
        if name and normalized == name:
            continue
        if re.fullmatch(r"[\d۰-۹٠-٩]+(?:[.,/]\d+)?\s*\$?", stripped):
            continue
        if re.search(r"[\d۰-۹٠-٩]+\s*(?:gr|g|گرم)\b", normalized, re.I):
            continue
        if re.fullmatch(r"[\d۰-۹٠-٩]{1,2}\s*[/.-]\s*[\d۰-۹٠-٩]{1,4}", stripped):
            continue
        if "برای ثبت سفارش" in stripped or stripped.startswith("@"):
            continue
        cleaned.append(stripped)
    return "\n".join(cleaned).strip() or "توضیحی ثبت نشده است."


def display_product_name(product: dict, limit: int = 55) -> str:
    name = str(product.get("name") or "محصول بدون نام").strip()
    return name if len(name) <= limit else name[: limit - 1].rstrip() + "…"


def extract_price_max(query: str) -> float | None:
    normalized = normalize_query_for_search(query).replace(",", ".")
    match = re.search(
        r"(?:زیر|کمتر\s+از|حداکثر|تا|زیر\s+قیمت)\s*(\d+(?:\.\d+)?)\s*(?:دلار|دالر|\$)?",
        normalized,
    )
    if not match:
        match = re.search(r"<\s*(\d+(?:\.\d+)?)", normalized)
    return float(match.group(1)) if match else None

# ── Helpers ───────────────────────────────────────────────────
def load_admin_config() -> dict:
    try:
        with open(ADMIN_CONFIG_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def save_admin_config(data: dict) -> None:
    with open(ADMIN_CONFIG_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS or str(user_id) in load_admin_config() or is_super_admin(user_id)


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


async def generate_ai_description(product: dict) -> str:
    """Generate a short Persian sales description with one inexpensive API call."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    prompt = (
        "برای محصول زیر یک راهنمای خرید دقیق و جذاب به زبان فارسی بنویس. "
        "فقط بر اساس اطلاعات داده‌شده بنویس و هیچ ویژگی، امتیاز، review یا قیمت روزی را حدس نزن. "
        "اگر اطلاعاتی موجود نیست، صریحاً بنویس «اطلاعاتی ثبت نشده است». "
        "پاسخ را با این تیترها و حداکثر ۱۸۰ کلمه بنویس: معرفی، کاربردهای احتمالی، نکات مهم، جمع‌بندی.\n\n"
        f"نام: {product.get('name') or '-'}\n"
        f"دسته: {product.get('category') or '-'}\n"
        f"قیمت خرید دلاری: {product.get('price_usd') or '-'}\n"
        f"سایز: {product.get('size') or '-'}\n"
        f"وزن (گرم): {product.get('weight_grams') or '-'}\n"
        f"موقعیت: {product.get('location') or '-'}\n"
        f"توضیحات موجود: {product.get('description') or '-'}"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "تو یک نویسنده متن فروشگاهی دقیق و فارسی‌زبان هستی.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.5,
                "max_tokens": 220,
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not content or not content.strip():
            raise RuntimeError("AI returned an empty response")
        return content.strip()


async def extract_product_from_photos(photo_paths: list[str]) -> dict:
    if not OPENAI_API_KEY:
        return {}
    content = [{
        "type": "text",
        "text": (
            "از عکس‌های محصول اطلاعات قابل مشاهده را استخراج کن. فقط JSON معتبر برگردان "
            "با کلیدهای name, category, size, weight_grams, description. اگر چیزی معلوم نیست null بگذار. "
            "قیمت را استخراج نکن مگر واضح و دلاری باشد."
        ),
    }]
    for path in photo_paths[:3]:
        with open(path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("ascii")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
        })
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": OPENAI_MODEL,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.1,
                "max_tokens": 350,
            },
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.IGNORECASE).strip()
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


async def download_photo(update: Update, filename: str) -> str | None:
    """Download the largest photo and save to PHOTOS_DIR. Return path or None."""
    if not update.message or not update.message.photo:
        return None
    photo = update.message.photo[-1]  # largest
    file = await photo.get_file()
    filepath = os.path.join(PHOTOS_DIR, filename)
    await file.download_to_drive(filepath)
    if MEDIA_UPLOAD_TOKEN and not API_BASE_URL.startswith(("http://127.0.0.1", "http://localhost")):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                with open(filepath, "rb") as image:
                    response = await client.post(
                        API_BASE_URL.rstrip("/") + "/media/upload",
                        headers={"X-Media-Token": MEDIA_UPLOAD_TOKEN},
                        files={"file": (filename, image, "image/jpeg")},
                    )
                response.raise_for_status()
        except Exception:
            logger.exception("Could not mirror photo to API media storage")
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


async def restart_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allow /start to escape any active settings/product conversation."""
    context.user_data.clear()
    await cmd_start(update, context)
    return ConversationHandler.END


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
        "📥 راهنمای ورود گروهی با Excel\n\n"
        "هر ردیف Excel یک محصول است.\n"
        "نام، قیمت دلار و دسته‌بندی را وارد کنید؛ قیمت نهایی خودکار محاسبه می‌شود.\n"
        "برای عکس، فقط نام فایل را در ستون عکس ۱ تا عکس ۳ بنویسید.\n"
        "سپس فایل xlsx را همین‌جا ارسال کنید.\n\n"
        "اگر فقط چند محصول دارید، «➕ افزودن محصول» یا «🖼 افزودن با عکس» سریع‌تر است.\n\n"
        "حالا فایل Excel را ارسال کنید."
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
                    "owner_admin_id": update.effective_user.id,
        "created_by_admin_id": update.effective_user.id,
                    "created_by_admin_id": update.effective_user.id,
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
    visible = 0
    for product in products:
        if not can_manage_product(update.effective_user.id, product):
            continue
        visible += 1
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
    if visible == 0:
        await update.message.reply_text("⛔ برای دسته‌بندی‌های شما محصولی ثبت نشده است.")


async def manage_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.message.reply_text("⛔ فقط ادمین دسترسی دارد.")
        return
    action, product_id_text = query.data.split(":", 1)
    product_id = int(product_id_text)
    current_product = await call_api("GET", f"/products/{product_id}")
    if not can_manage_product(query.from_user.id, current_product):
        await query.message.reply_text("⛔ شما به این دسته‌بندی دسترسی ندارید.")
        return
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


async def admin_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super_admin(update.effective_user.id):
        await update.message.reply_text("⛔ فقط سوپرادمین دسترسی دارد.")
        return
    products = await call_api("GET", "/products")
    config = load_admin_config()
    ids = sorted(set(ADMIN_IDS) | set(SUPER_ADMIN_IDS) | {int(x) for x in config if str(x).isdigit()})
    lines = ["📊 گزارش فعالیت ادمین‌ها", ""]
    for uid in ids:
        created = sum(1 for p in products if p.get("created_by_admin_id") == uid)
        owned = sum(1 for p in products if p.get("owner_admin_id") == uid)
        lines.append(f"🆔 {uid} | ثبت محصول: {created} | مالک فعلی: {owned}")
    lines.append(f"\n📦 مجموع محصولات: {len(products)}")
    await update.message.reply_text("\n".join(lines), reply_markup=main_menu(update.effective_user.id))

async def admin_manage_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super_admin(update.effective_user.id):
        await update.message.reply_text("⛔ فقط سوپرادمین دسترسی دارد.")
        return
    config = load_admin_config()
    all_admin_ids = set(ADMIN_IDS) | set(SUPER_ADMIN_IDS) | {int(uid) for uid in config if str(uid).isdigit()}
    lines = ["👥 مدیریت ادمین‌ها", "", "ادمین‌های فعلی:"]
    if all_admin_ids:
        for uid in sorted(all_admin_ids):
            info = config.get(str(uid), {})
            cats = ", ".join(info.get("categories", [])) or "همه دسته‌ها"
            role = "سوپرادمین" if uid in SUPER_ADMIN_IDS else "ادمین"
            lines.append(f"🆔 {uid} | {role}\n   🏷️ {cats}")
    lines.append("\nبرای افزودن ادمین جدید یا تغییر دسته‌ها از دکمه‌ها استفاده کنید.")
    buttons = [[InlineKeyboardButton("✏️ تغییر دسته‌ها برای " + str(uid), callback_data=f"admin_edit:{uid}")] for uid in sorted(all_admin_ids) if uid not in SUPER_ADMIN_IDS]
    buttons.append([InlineKeyboardButton("➕ افزودن ادمین", callback_data="admin_add")])
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))

async def admin_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_super_admin(query.from_user.id):
        return
    admin_id = int(query.data.split(":", 1)[1])
    config = load_admin_config()
    context.user_data["new_admin_id"] = admin_id
    context.user_data["new_admin_categories"] = list(config.get(str(admin_id), {}).get("categories", []))
    selected = set(context.user_data["new_admin_categories"])
    buttons = [[InlineKeyboardButton(("✅ " if c in selected else "▫️ ") + c, callback_data="admin_cat:" + c)] for c in ADMIN_CATEGORIES]
    buttons.append([InlineKeyboardButton("💾 ذخیره دسترسی", callback_data="admin_cat:done")])
    await query.message.reply_text("🏷️ دسته‌های مجاز را ویرایش کنید:", reply_markup=InlineKeyboardMarkup(buttons))

async def admin_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_super_admin(query.from_user.id): return
    context.user_data["awaiting_new_admin_id"] = True
    await query.message.reply_text("🆔 آیدی عددی تلگرام ادمین جدید را ارسال کنید:", reply_markup=cancel_keyboard())

async def admin_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_super_admin(query.from_user.id): return
    selected = set(context.user_data.get("new_admin_categories", []))
    cat = query.data.split(":", 1)[1]
    if cat == "done":
        if not selected:
            await query.message.reply_text("حداقل یک دسته را انتخاب کنید.")
            return
        config = load_admin_config(); uid = str(context.user_data["new_admin_id"])
        config[uid] = {"categories": sorted(selected)}; save_admin_config(config); ADMIN_IDS.add(int(uid))
        context.user_data.pop("new_admin_id", None); context.user_data.pop("new_admin_categories", None)
        await query.message.reply_text("✅ ادمین و دسته‌های مجاز ذخیره شد.", reply_markup=main_menu(query.from_user.id)); return
    if cat in selected: selected.remove(cat)
    else: selected.add(cat)
    context.user_data["new_admin_categories"] = list(selected)
    buttons = [[InlineKeyboardButton(("✅ " if c in selected else "▫️ ")+c, callback_data="admin_cat:"+c)] for c in ADMIN_CATEGORIES]
    buttons.append([InlineKeyboardButton("💾 ذخیره دسترسی", callback_data="admin_cat:done")])
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))

async def menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if context.user_data.pop("awaiting_new_admin_id", False):
        try: admin_id = int(text)
        except ValueError:
            await update.message.reply_text("آیدی باید عددی باشد.")
            context.user_data["awaiting_new_admin_id"] = True
            return
        context.user_data["new_admin_id"] = admin_id
        context.user_data["new_admin_categories"] = []
        buttons = [[InlineKeyboardButton("▫️ "+c, callback_data="admin_cat:"+c)] for c in ADMIN_CATEGORIES]
        buttons.append([InlineKeyboardButton("💾 ذخیره دسترسی", callback_data="admin_cat:done")])
        await update.message.reply_text("🏷️ دسته‌های مجاز را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
        return
    if text == BTN_LIST: await cmd_list(update, context)
    elif text == BTN_SEARCH:
        context.user_data["awaiting_search"] = True
        await update.message.reply_text("🔍 نام، دسته یا ویژگی محصول را بنویسید:", reply_markup=ReplyKeyboardRemove())
    elif text == BTN_IMPORT: await import_excel_start(update, context)
    elif text == BTN_PRICE_VIEW: await cmd_price_settings(update, context)
    elif text == BTN_ADD_HELP: await add_help(update, context)
    elif text == BTN_ADMIN_MANAGE: await admin_manage_start(update, context)
    elif text == BTN_ADMIN_REPORT: await admin_report(update, context)

async def receive_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("awaiting_search", False):
        return
    keyword = update.message.text.strip()
    products = await call_api("GET", "/products")
    query_normalized = normalize_query_for_search(keyword)
    query_tokens = [token for token in query_normalized.split() if len(token) > 1]
    max_price = extract_price_max(keyword)
    male_shoe_query = "مردانه" in query_normalized and "کفش" in query_normalized
    ranked = []
    for product in products:
        if max_price is not None and float(product.get("price_usd") or 0) > max_price:
            continue
        searchable = normalize_search_text_v2(" ".join(
            str(product.get(field) or "")
            for field in ("name", "description", "category", "location", "size")
        ))
        searchable_tokens = searchable.split()
        female_shoe_query = (
            any(term in query_normalized for term in ("بچگانه", "زنانه"))
            and "کفش" in query_normalized
        )
        if female_shoe_query and normalize_search_text_v2(product.get("category")) == "کفش":
            if not any(term in searchable for term in ("دخترانه", "زنانه", "بچگانه")):
                continue
        token_scores = [
            search_token_similarity(token, searchable_tokens)
            for token in query_tokens
        ]
        token_hits = sum(score >= 0.72 for score in token_scores)
        if male_shoe_query and normalize_search_text_v2(product.get("category")) == "کفش":
            if "زنانه" not in searchable and "بچگانه" not in searchable:
                token_hits += 2
        if query_normalized in searchable or (
            query_tokens and token_hits == len(query_tokens)
        ):
            ranked.append((2, sum(token_scores), product))
        elif token_hits and len(query_tokens) == 1 and token_scores[0] >= 0.78:
            ranked.append((1, sum(token_scores), product))
    results = [
        product for _, _, product in sorted(
            ranked, key=lambda item: (item[0], item[1]), reverse=True
        )
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


async def receive_search_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("awaiting_search", False):
        return
    keyword = update.message.text.strip()
    products = await call_api("GET", "/products")
    query_normalized = normalize_query_for_search(keyword)
    query_tokens = [token for token in query_normalized.split() if len(token) > 1]
    max_price = extract_price_max(keyword)
    male_shoe_query = "مردانه" in query_normalized and "کفش" in query_normalized
    ranked = []
    for product in products:
        if max_price is not None and float(product.get("price_usd") or 0) > max_price:
            continue
        searchable = normalize_search_text_v2(" ".join(
            str(product.get(field) or "")
            for field in ("name", "description", "category", "location", "size")
        ))
        searchable_tokens = searchable.split()
        female_shoe_query = (
            any(term in query_normalized for term in ("بچگانه", "زنانه"))
            and "کفش" in query_normalized
        )
        if female_shoe_query and normalize_search_text_v2(product.get("category")) == "کفش":
            if not any(term in searchable for term in ("دخترانه", "زنانه", "بچگانه")):
                continue
        token_scores = [
            search_token_similarity(token, searchable_tokens)
            for token in query_tokens
        ]
        token_hits = sum(score >= 0.72 for score in token_scores)
        if male_shoe_query and normalize_search_text_v2(product.get("category")) == "کفش":
            if "زنانه" not in searchable and "بچگانه" not in searchable:
                token_hits += 2
        if query_normalized in searchable or (
            query_tokens and token_hits == len(query_tokens)
        ):
            ranked.append((2, sum(token_scores), product))
        elif token_hits and len(query_tokens) == 1 and token_scores[0] >= 0.78:
            ranked.append((1, sum(token_scores), product))
    results = [
        product for _, _, product in sorted(
            ranked, key=lambda item: (item[0], item[1]), reverse=True
        )
    ]
    if not results:
        await update.message.reply_text(f"🔍 نتیجه‌ای برای «{keyword}» پیدا نشد.")
    else:
        await update.message.reply_text(
            f"🔍 نتایج جستجو برای «{keyword}» ({len(results)} مورد):"
        )
        for product in results[:10]:
            final_price = calculate_toman(
                product.get("price_usd", 0), product.get("weight_grams")
            )
            description = clean_product_description(product)
            description = description[:217] + "..." if len(description) > 220 else description
            caption = (
                f"📏 سایز: {product_size(product)}\n"
                f"📦 {product.get('name', '-')}\n"
                f"💵 قیمت نهایی: {toman(final_price)}\n"
                f"🏷️ دسته: {product.get('category') or '-'} | 📍 {product.get('location') or '-'}\n"
                f"📝 {description}"
            )
            photo_name = next(
                (p for p in (product.get("original_photo_path") or "").split("|") if p),
                None,
            )
            full_photo = None
            if photo_name:
                full_photo = photo_name if os.path.isabs(photo_name) else os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), photo_name
                )
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "مشاهده جزئیات و عکس‌ها",
                    callback_data=f"product_detail:{product['id']}",
                )
            ]])
            if full_photo and os.path.exists(full_photo):
                with open(full_photo, "rb") as photo:
                    await update.message.reply_photo(
                        photo=photo, caption=caption, reply_markup=markup
                    )
            else:
                await update.message.reply_text(caption, reply_markup=markup)
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


async def add_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ این راهنما فقط برای ادمین‌هاست.")
        return
    await update.message.reply_text(
        "ℹ️ راهنمای ثبت محصول\n\n"
        "➕ افزودن محصول: ثبت دستی مرحله‌به‌مرحله\n"
        "🖼 افزودن با عکس: ارسال یک تا سه عکس؛ بات اطلاعات قابل تشخیص را استخراج می‌کند و شما موارد ناقص را تکمیل می‌کنید.\n"
        "📥 ورود اکسل: ثبت تعداد زیادی محصول با یک فایل Excel.\n\n"
        "ثبت دستی:\n"
        "۱. نام محصول\n۲. قیمت خرید به دلار\n۳. سایز (اختیاری)\n"
        "۴. وزن به گرم (اختیاری)\n۵. دسته‌بندی\n۶. موقعیت\n"
        "۷. توضیحات\n۸. عکس‌های محصول\n\n"
        "قیمت نهایی از نرخ دلار، ضریب، وزن و هزینه حمل محاسبه می‌شود.\n"
        "برای خروج از هر مرحله، دکمه «لغو» را بزنید.\n\n"
        "نمونه قیمت: 59.99\n"
        "نمونه نام: کفش آدیداس سامبا"
    )


async def add_photo_ai_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ فقط ادمین می‌تواند محصول اضافه کند.")
        return ConversationHandler.END
    context.user_data.clear()
    context.user_data["product"] = {"photo_paths": []}
    await update.message.reply_text(
        "🖼 راهنمای ثبت محصول با عکس\n\n"
        "۱) یک تا سه عکس واضح از یک محصول بفرستید.\n"
        "۲) بعد از هر عکس، «✅ اتمام عکس‌ها» را بزنید یا عکس بعدی را ارسال کنید.\n"
        "۳) بات نام و اطلاعات قابل تشخیص را استخراج می‌کند.\n"
        "۴) اگر چیزی پیدا نشود، خودتان اصلاح یا تکمیل می‌کنید.\n"
        "۵) قیمت و سایر اطلاعات ناقص را وارد کنید.\n\n"
        "نکته: عکس‌ها باید مربوط به یک محصول باشند.\n"
        "برای خروج، «لغو» را بزنید.\n\n"
        "لطفاً عکس اول را ارسال کنید.",
        reply_markup=cancel_keyboard(),
    )
    return PHOTO_AI


async def add_photo_ai_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    product = context.user_data["product"]
    if len(product["photo_paths"]) >= 3:
        await update.message.reply_text("حداکثر سه عکس مجاز است.")
        return PHOTO_AI
    filename = f"ai_product_{update.effective_user.id}_{len(product['photo_paths']) + 1}.jpg"
    filepath = await download_photo(update, filename)
    if filepath:
        product["photo_paths"].append(filepath)
        product["original_photo_path"] = "|".join(
            f"photos/{os.path.basename(path)}" for path in product["photo_paths"]
        )
    await update.message.reply_text(
        f"✅ عکس {len(product['photo_paths'])} دریافت شد. عکس بعدی را بفرستید یا اتمام عکس‌ها را بزنید.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ اتمام عکس‌ها", callback_data="ai_finish_photos"),
            InlineKeyboardButton("❌ لغو", callback_data="cancel"),
        ]]),
    )
    return PHOTO_AI


async def add_photo_ai_finish_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allow finishing photo collection by typing the button label."""
    product = context.user_data.get("product", {})
    if not product.get("photo_paths"):
        await update.message.reply_text("حداقل یک عکس بفرستید.")
        return PHOTO_AI
    await update.message.reply_text("🔎 در حال بررسی عکس‌ها…")
    try:
        extracted = await extract_product_from_photos(product["photo_paths"])
        product.update({k: v for k, v in extracted.items() if v not in (None, "")})
    except Exception as exc:
        logger.warning("Photo extraction failed: %s", exc)
    if not product.get("name"):
        await update.message.reply_text("نام محصول از عکس مشخص نشد. لطفاً نام محصول را وارد کنید:")
        return NAME
    await update.message.reply_text("اطلاعات اولیه آماده شد. حالا قیمت دلار را وارد کنید:")
    return PRICE


async def add_photo_ai_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product = context.user_data["product"]
    if not product.get("photo_paths"):
        await query.message.reply_text("حداقل یک عکس بفرستید.")
        return PHOTO_AI
    await query.message.reply_text("🔎 در حال بررسی عکس‌ها…")
    try:
        extracted = await extract_product_from_photos(product["photo_paths"])
        product.update({k: v for k, v in extracted.items() if v not in (None, "")})
    except Exception as exc:
        logger.warning("Photo extraction failed: %s", exc)
    if not product.get("name"):
        await query.message.reply_text(
            "نام محصول از عکس مشخص نشد. لطفاً نام محصول را وارد کنید:"
        )
        return NAME
    await query.message.reply_text("اطلاعات اولیه آماده شد. حالا قیمت دلار را وارد کنید:")
    return PRICE


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
                InlineKeyboardButton("عطر و ادکلن", callback_data="cat_عطر و ادکلن"),
            ],
            [
                InlineKeyboardButton("لباس", callback_data="cat_لباس"),
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
    if not is_super_admin(query.from_user.id) and cat not in category_access(query.from_user.id):
        await query.message.reply_text("⛔ شما به این دسته‌بندی دسترسی ندارید.")
        return ConversationHandler.END
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
    if context.user_data["product"].get("photo_paths"):
        return await _goto_confirm(update, context)
    return await _goto_photo(update)


async def add_description_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data["product"].get("photo_paths"):
        return await _goto_confirm(update, context)
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
        "owner_admin_id": update.effective_user.id,
        "created_by_admin_id": update.effective_user.id,
                    "created_by_admin_id": update.effective_user.id,
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
LIST_PAGE_SIZE = 15


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

    context.user_data["all_products"] = products
    await _send_category_page(update, context)
    return
    context.user_data["list_page"] = 0
    context.user_data["list_title"] = "📦 فهرست محصولات"
    await _send_product_page(update, context, 0)


async def _send_product_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    products = context.user_data.get("list_products", [])
    total = len(products)
    start = page * LIST_PAGE_SIZE
    end = start + LIST_PAGE_SIZE
    page_items = products[start:end]

    buttons = []
    for p in page_items:
        photo_mark = "🖼" if p.get("original_photo_path") else "▫️"
        label = f"{photo_mark} {display_product_name(p, 35)} — ${p['price_usd']}"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"product_detail:{p['id']}")
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data="list_prev"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️ بعدی", callback_data="list_next"))
    if nav:
        buttons.append(nav)
    buttons.append([
        InlineKeyboardButton("📂 دسته‌بندی‌ها", callback_data="list_categories")
    ])
    title = context.user_data.get("list_title", "📦 فهرست محصولات")
    await update.effective_message.reply_text(
        f"{title}\nمحصولات {start + 1}-{min(end, total)} از {total}\n"
        "برای مشاهده جزئیات، یک محصول را انتخاب کنید.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _send_category_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = context.user_data.get("all_products", [])
    counts = {}
    for product in products:
        category = (product.get("category") or "سایر").strip()
        counts[category] = counts.get(category, 0) + 1
    buttons = [
        [InlineKeyboardButton(f"🏷️ {category} ({count})", callback_data=f"category:{category}")]
        for category, count in sorted(counts.items())
    ]
    await update.effective_message.reply_text(
        "📂 دسته‌بندی محصولات\nیک دسته را برای مشاهده محصولات انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = context.user_data.get("list_page", 0)
    if query.data == "list_next":
        page += 1
    elif query.data == "list_prev":
        page = max(0, page - 1)
    elif query.data == "list_categories":
        await _send_category_page(update, context)
        return
    context.user_data["list_page"] = page
    await _send_product_page(update, context, page)


async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split(":", 1)[1]
    products = [
        product for product in context.user_data.get("all_products", [])
        if (product.get("category") or "سایر").strip() == category
    ]
    context.user_data["list_products"] = products
    context.user_data["list_page"] = 0
    context.user_data["list_title"] = f"📂 {category}"
    await _send_product_page(update, context, 0)


async def product_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = int(query.data.split(":", 1)[1])
    product = await call_api("GET", f"/products/{product_id}")
    final_price = calculate_toman(product.get("price_usd", 0), product.get("weight_grams"))
    text = (
        f"📦 {product['name']}\n"
        f"💰 قیمت خرید: ${product['price_usd']}\n"
        f"💵 قیمت نهایی: {toman(final_price)}\n"
        f"📏 سایز: {product.get('size') or '-'}\n"
        f"⚖️ وزن: {product.get('weight_grams') or '-'} گرم\n"
        f"🏷️ دسته: {product.get('category') or '-'}\n"
        f"📍 موقعیت: {product.get('location') or '-'}\n"
        f"📝 توضیحات:\n{clean_product_description(product)}"
    )
    raw_paths = product.get("original_photo_path") or ""
    existing_paths = []
    for photo_path in raw_paths.split("|"):
        if not photo_path:
            continue
        full = photo_path if os.path.isabs(photo_path) else os.path.join(
            os.path.dirname(os.path.abspath(__file__)), photo_path
        )
        if os.path.exists(full):
            existing_paths.append(full)
    if existing_paths:
        handles = []
        try:
            handles = [open(path, "rb") for path in existing_paths]
            media = [
                InputMediaPhoto(
                    media=handle,
                    caption=text if index == 0 else None,
                    parse_mode="Markdown" if index == 0 else None,
                )
                for index, handle in enumerate(handles)
            ]
            await query.message.reply_media_group(media=media)
        finally:
            for handle in handles:
                handle.close()
    else:
        await query.message.reply_text(text)
    await query.message.reply_text(
        "گزینه‌های محصول:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "✨ اطلاعات بیشتر", callback_data=f"ai_info:{product_id}"
            )
        ]]),
    )
    if is_admin(query.from_user.id):
        await query.message.reply_text(
            "عملیات محصول:",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✏️ ویرایش", callback_data=f"edit_product:{product_id}"),
                    InlineKeyboardButton("📷 افزودن عکس", callback_data=f"photo_product:{product_id}"),
                ],
                [InlineKeyboardButton("🗑 حذف", callback_data=f"delete_product:{product_id}")],
            ]),
        )


# ── Command: /delete <id> ────────────────────────────────────
async def product_ai_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("این قابلیت فعلاً غیرفعال است.")
    await query.message.reply_text(
        "ℹ️ توضیحات هوشمند فعلاً غیرفعال شده تا اتصال جستجوی واقعی وب اضافه شود."
    )
    return
    product_id = int(query.data.split(":", 1)[1])
    try:
        product = await call_api("GET", f"/products/{product_id}")
        cached = (product.get("ai_description") or "").strip()
        if cached.startswith(f"{AI_PROMPT_VERSION}:"):
            description = cached.split(":", 1)[1].strip()
            source_note = " (ذخیره‌شده)"
        else:
            description = await generate_ai_description(product)
            await call_api(
                "PUT",
                f"/products/{product_id}",
                {"ai_description": f"{AI_PROMPT_VERSION}: {description}"},
            )
            source_note = ""
        await query.message.reply_text(
            f"✨ اطلاعات بیشتر درباره «{product.get('name', '-')}»{source_note}:\n\n"
            f"{description}"
        )
    except Exception as exc:
        logger.error("Error generating AI product info: %s", exc)
        await query.message.reply_text(
            "⚠️ فعلاً امکان دریافت اطلاعات بیشتر وجود ندارد. لطفاً کمی بعد دوباره تلاش کنید."
        )


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

    context.user_data["list_products"] = results
    context.user_data["list_page"] = 0
    context.user_data["list_title"] = f"🔍 نتایج «{keyword}»"
    await _send_product_page(update, context, 0)


# ── Experimental quick product entry ─────────────────────────
def parse_quick_product(text: str) -> dict:
    """Parse labelled multi-line or free-form one-line product text."""
    raw = text.strip()
    normalized = raw.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    lines = [x.strip() for x in normalized.splitlines() if x.strip()]
    def find(pattern):
        m = re.search(pattern, normalized, re.I | re.M)
        return (m.group(1) or "").strip(" \t:：-،,؛") if m else None
    price = find(r"(?:قیمت(?: خرید)?|price)\s*[:：-]?\s*([0-9]+(?:[.,][0-9]+)?)")
    if not price:
        m = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*(?:دلار|دالر|usd|\$)", normalized, re.I); price = m.group(1) if m else None
    weight = find(r"(?:وزن|weight)\s*[:：-]?\s*([0-9]+(?:[.,][0-9]+)?)")
    if not weight:
        m = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*(?:گرم|g)\b", normalized, re.I); weight = m.group(1) if m else None
    size = find(r"(?:سایز|سایس|اندازه|size)\s*[:：-]?\s*((?:(?:US|EU|UK)\s*)?[0-9]+(?:[.,][0-9]+)?)")
    location = find(r"(?:موقعیت|لوکیشن|location)\s*[:：-]?\s*([^\n,؛]+)")
    if not location:
        m = re.search(r"\b(تهران|کانادا|ایران|آمریکا|ترکیه|دبی|canada|iran|usa|turkey|dubai)\b", normalized, re.I)
        location = m.group(1) if m else "تهران"
    category = find(r"(?:دسته|دسته‌بندی|category)\s*[:：-]?\s*([^\n,؛]+)")
    description = find(r"(?:توضیحات|توضیح|شرح|description)\s*[:：-]?\s*(.+)$")
    name = find(r"(?:نام|محصول|name)\s*[:：-]?\s*(.+?)(?=\s+(?:قیمت|وزن|سایز|دسته|موقعیت|توضیحات)\s*[:：-]|\s+[0-9]+\s*(?:دلار|\$)|$)")
    if not name:
        name = lines[0] if lines else ""
        name = re.split(r"\s+(?=(?:سایز|سایس|اندازه|قیمت|وزن|موقعیت|دسته|توضیحات)\b|[0-9]+(?:[.,][0-9]+)?\s*(?:دلار|دالر|usd|\$|گرم|g)\b)", name, maxsplit=1, flags=re.I)[0].strip(" -،,؛:")
    haystack = f"{name} {description or ''} {normalized}".lower()
    if not category:
        rules = [("عطر و ادکلن", ("عطر","ادکلن","perfume","cologne","fragrance","رایحه")), ("دارو و سلامتی", ("قرص","دارو","ویتامین","مکمل","مسکن","tablet","vitamin")), ("کفش", ("کفش","کتونی","بوت","صندل","sneaker","shoe")), ("کیف", ("کیف","کوله","bag","backpack")), ("لباس", ("لباس","پیراهن","شلوار","کاپشن","مانتو","dress","shirt","jacket")), ("اکسسوری", ("اکسسوری","ساعت","انگشتر","گردنبند","دستبند","watch")), ("ورزشی", ("ورزشی","فوتبال","بدنسازی","gym","sport")), ("آرایشی بهداشتی", ("آرایشی","بهداشتی","کرم","شامپو","cosmetic"))]
        category = next((label for label, words in rules if any(w in haystack for w in words)), "سایر")
    if not description:
        cleaned = normalized
        if name: cleaned = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", " ", cleaned, flags=re.I)
        cleaned = re.sub(r"(?:سایز|سایس|اندازه)\s*[0-9]+(?:[.,][0-9]+)?", " ", cleaned, flags=re.I)
        cleaned = re.sub(r"[0-9]+(?:[.,][0-9]+)?\s*(?:دلار|دالر|usd|\$|گرم|g)\b", " ", cleaned, flags=re.I)
        cleaned = re.sub(r"\b(?:قیمت|خرید|وزن|دسته|دسته‌بندی|موقعیت|لوکیشن|توضیحات|سایز|سایس|اندازه|size)\s*[:：-]?", " ", cleaned, flags=re.I)
        for value in (size, category, location):
            if value: cleaned = re.sub(r"(?<!\w)" + re.escape(value) + r"(?!\w)", " ", cleaned, flags=re.I)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -،,؛:")
        description = cleaned or ""
    return {"name": name, "price_usd": float(price.replace(",", ".")) if price else None, "weight_grams": float(weight.replace(",", ".")) if weight else None, "size": size, "category": category, "location": location, "description": description}
async def quick_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return ConversationHandler.END
    context.user_data.clear(); context.user_data["product"] = {"photo_paths": []}
    await update.message.reply_text("⚡ ثبت سریع محصول\nلطفاً اطلاعات را به همین ترتیب و ترجیحاً هر مورد در یک خط بفرستید:\nنام محصول\nقیمت به دلار\nوزن به گرم\nسایز (اختیاری)\nموقعیت (اختیاری؛ پیش‌فرض تهران)\nتوضیحات\nدسته‌بندی (اختیاری)\n\nمتن پیوسته هم پشتیبانی می‌شود، اما برای تشخیص دقیق‌تر Enter بزنید.", reply_markup=cancel_keyboard())
    return QUICK_TEXT

async def quick_add_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text or ""
    price_count = len(re.findall(r"[0-9۰-۹]+(?:[.,][0-9۰-۹]+)?\s*(?:دلار|دالر|usd|\$)", raw_text, re.I))
    if price_count > 1:
        await update.message.reply_text("⚠️ به نظر می‌رسد اطلاعات چند محصول در یک پیام است. لطفاً هر محصول را جداگانه ارسال کنید.", reply_markup=cancel_keyboard())
        return QUICK_TEXT
    product = context.user_data["product"]; product.update({k:v for k,v in parse_quick_product(update.message.text).items() if v not in (None, "")})
    if not product.get("price_usd"):
        await update.message.reply_text("قیمت دلار پیدا نشد؛ دوباره متن را همراه قیمت بفرستید.", reply_markup=cancel_keyboard()); return QUICK_TEXT
    await update.message.reply_text("✅ اطلاعات خوانده شد. حالا یک تا سه عکس بفرستید؛ اگر عکس ندارید دکمه اتمام را بزنید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ اتمام عکس‌ها", callback_data="quick_finish")],[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]))
    return QUICK_PHOTOS

async def quick_add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    paths=context.user_data["product"].setdefault("photo_paths",[])
    if len(paths)>=3: return QUICK_PHOTOS
    filename=f"quick_product_{update.effective_user.id}_{len(paths)+1}.jpg"; saved=await download_photo(update,filename)
    if saved: paths.append(saved); context.user_data["product"]["original_photo_path"]="|".join("photos/"+os.path.basename(p) for p in paths)
    await update.message.reply_text(f"✅ عکس {len(paths)} دریافت شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ اتمام عکس‌ها", callback_data="quick_finish")],[InlineKeyboardButton("❌ لغو", callback_data="cancel")]])); return QUICK_PHOTOS

async def quick_add_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); p=context.user_data["product"]; missing=[]
    if not p.get("name"): missing.append("نام")
    if not p.get("price_usd"): missing.append("قیمت")
    if missing: await q.message.reply_text("موارد ناقص: "+"، ".join(missing)); return QUICK_TEXT
    preview=(f"📦 عنوان: {p['name']}\n💰 قیمت خرید: ${p['price_usd']}\n💵 قیمت نهایی: {toman(calculate_toman(p['price_usd'], p.get('weight_grams')))}\n⚖️ وزن: {p.get('weight_grams') or '-'} گرم\n📏 سایز: {p.get('size') or '-'}\n🏷️ دسته تشخیص‌داده‌شده: {p.get('category') or 'سایر'}\n📍 موقعیت: {p.get('location') or '-'}\n📝 توضیحات: {p.get('description') or '-'}")
    context.user_data["quick_preview"] = p
    await q.message.reply_text(preview, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ ثبت محصول", callback_data="quick_save"), InlineKeyboardButton("✏️ ویرایش", callback_data="quick_edit")],[InlineKeyboardButton("❌ لغو", callback_data="cancel")]])); return QUICK_CONFIRM

async def quick_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    fields = [("name", "عنوان"), ("price_usd", "قیمت دلار"), ("weight_grams", "وزن"), ("size", "سایز"), ("category", "دسته‌بندی"), ("location", "موقعیت"), ("description", "توضیحات")]
    keyboard = [[InlineKeyboardButton(label, callback_data=f"quick_edit_field:{field}")] for field, label in fields]
    keyboard.append([InlineKeyboardButton("↩️ بازگشت", callback_data="quick_back")])
    await q.message.reply_text("کدام بخش ویرایش شود؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return QUICK_EDIT

async def quick_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    field = q.data.split(":", 1)[1]
    context.user_data["quick_edit_field"] = field
    await q.message.reply_text("مقدار جدید را بفرستید:", reply_markup=cancel_keyboard())
    return QUICK_EDIT

async def quick_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.pop("quick_edit_field", None)
    if not field:
        return QUICK_EDIT
    value = update.message.text.strip()
    if field in ("price_usd", "weight_grams"):
        try:
            value = float(value.replace(",", ".").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
        except ValueError:
            await update.message.reply_text("لطفاً عدد معتبر بفرستید.")
            context.user_data["quick_edit_field"] = field
            return QUICK_EDIT
    context.user_data["product"][field] = value
    await update.message.reply_text("✅ ویرایش شد. برای ویرایش بخش دیگر دکمه ویرایش را بزنید یا ثبت کنید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ ثبت محصول", callback_data="quick_save")],[InlineKeyboardButton("✏️ ویرایش بخش دیگر", callback_data="quick_edit")],[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]))
    return QUICK_CONFIRM
async def quick_add_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); p=context.user_data.pop("quick_preview", context.user_data.get("product",{})); payload={k:v for k,v in p.items() if k not in ("photo_paths",) and v not in (None, "")}; payload["owner_admin_id"]=q.from_user.id; payload["created_by_admin_id"]=q.from_user.id
    try: result=await call_api("POST","/products",data=payload); await q.message.reply_text(f"✅ محصول ثبت شد. ID: {result['id']}",reply_markup=main_menu(q.from_user.id))
    except Exception: await q.message.reply_text("❌ ثبت محصول ناموفق بود.",reply_markup=main_menu(q.from_user.id))
    context.user_data.clear(); return ConversationHandler.END
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
                CommandHandler("start", restart_conversation),
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_usd_rate),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            SET_SHIPPING: [
                CommandHandler("start", restart_conversation),
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_shipping),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            SET_MULTIPLIER: [
                CommandHandler("start", restart_conversation),
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
            MessageHandler(filters.Regex(f"^{BTN_QUICK_ADD}$"), quick_add_start),
            MessageHandler(filters.Regex(f"^{BTN_ADD_PHOTO}$"), add_photo_ai_start),
        ],
        states={
            QUICK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, quick_add_text), CallbackQueryHandler(cancel, pattern="^cancel$")],
            QUICK_PHOTOS: [MessageHandler(filters.PHOTO, quick_add_photo), CallbackQueryHandler(quick_add_finish, pattern="^quick_finish$"), CallbackQueryHandler(cancel, pattern="^cancel$")],
            QUICK_CONFIRM: [CallbackQueryHandler(quick_add_save, pattern="^quick_save$"), CallbackQueryHandler(quick_edit_start, pattern="^quick_edit$"), CallbackQueryHandler(cancel, pattern="^cancel$")],
            QUICK_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, quick_edit_value), CallbackQueryHandler(quick_edit_field, pattern="^quick_edit_field:"), CallbackQueryHandler(quick_edit_start, pattern="^quick_edit$"), CallbackQueryHandler(quick_add_finish, pattern="^quick_back$"), CallbackQueryHandler(cancel, pattern="^cancel$")],
            PHOTO_AI: [
                MessageHandler(filters.PHOTO, add_photo_ai_receive),
                MessageHandler(
                    filters.Regex(r"^(✅\s*)?اتمام عکس‌ها$"),
                    add_photo_ai_finish_text,
                ),
                CallbackQueryHandler(add_photo_ai_finish, pattern="^ai_finish_photos$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
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

    # Priority handlers: these must work even when another conversation is active.
    application.add_handler(CallbackQueryHandler(cancel, pattern=r"^cancel$"), group=-1)
    application.add_handler(
        MessageHandler(filters.Regex(f"^(?:{BTN_ADMIN_MANAGE}|{BTN_ADMIN_REPORT})$"), menu_button),
        group=-1,
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
    application.add_handler(CallbackQueryHandler(admin_edit_callback, pattern=r"^admin_edit:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_add_callback, pattern=r"^admin_add$"))
    application.add_handler(CallbackQueryHandler(admin_category_callback, pattern=r"^admin_cat:"))
    application.add_handler(
        CallbackQueryHandler(product_detail_callback, pattern=r"^product_detail:\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(product_ai_info_callback, pattern=r"^ai_info:\d+$")
    )
    application.add_handler(
            MessageHandler(
            filters.Regex(
                f"^(?:{BTN_LIST}|{BTN_SEARCH}|{BTN_IMPORT}|{BTN_PRICE_VIEW}|{BTN_ADD_HELP})$"
            ),
            menu_button,
        )
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, receive_search_cards)
    )
    application.add_handler(
        CallbackQueryHandler(list_callback, pattern="^list_(next|prev|categories)$")
    )
    application.add_handler(
        CallbackQueryHandler(category_callback, pattern=r"^category:")
    )

    print("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
