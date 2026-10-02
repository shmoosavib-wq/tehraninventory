from __future__ import annotations
import os, re, logging, json
from difflib import SequenceMatcher
from urllib.parse import quote
import httpx
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, ContextTypes, filters
from telegram.request import HTTPXRequest
load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger('customer_bot')
TOKEN = os.getenv('CUSTOMER_BOT_TOKEN')
API = os.getenv('API_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
ROUTING_TOKEN = os.getenv('ROUTING_TOKEN', '')
USD_RATE = float(os.getenv('CUSTOMER_USD_RATE', '150000'))
SHIPPING_PER_KG = float(os.getenv('CUSTOMER_SHIPPING_PER_KG', '8000000'))
MULTIPLIER = float(os.getenv('CUSTOMER_MULTIPLIER', '1.5'))
if not TOKEN: raise RuntimeError('CUSTOMER_BOT_TOKEN is not set')
BTN_SEARCH='🔍 جست‌وجوی محصولات'; BTN_CATS='📦 دسته‌بندی محصولات'; BTN_CALC='💰 محاسبه قیمت'; BTN_ABOUT='🏪 درباره ما'; BTN_FAQ='❓ سوالات متداول'; SEARCH=1; CALC_USD=2; CALC_WEIGHT=3
SUPPORT_CONTACTS = [
    ('ادمین سفارش · سارا', 'Saraaamini'),
    ('ادمین سفارش · مهتاب', 'MahtabF1234'),
    ('ادمین سفارش · فرح', 'farahnazzia'),
    ('ادمین سفارش · المیرا', 'Elmousavi'),
    ('پیگیری سفارش', 'saman_eh71'),
    ('ادمین تهران · آلبوم سفارش', 'Azami54'),
]

def menu():
    return ReplyKeyboardMarkup([[BTN_SEARCH,BTN_CATS],[BTN_CALC],[BTN_ABOUT,BTN_FAQ]], resize_keyboard=True, is_persistent=True)

def norm(v):
    v=(v or '').casefold().replace('ي','ی').replace('ى','ی').replace('ك','ک')
    v=re.sub(r'[\u064b-\u065f\u0670]','',v)
    return re.sub(r'\s+',' ',re.sub(r'[^\w\s]',' ',v,flags=re.UNICODE)).strip()

def rank(q,p):
    q=norm(q); words=norm(' '.join(str(p.get(k) or '') for k in ('name','category','description','size','location'))).split()
    if not q or not words: return 0
    vals=[]
    for token in q.split(): vals.append(1 if token in words or any(token in x for x in words) else max((SequenceMatcher(None,token,x).ratio() for x in words),default=0))
    return sum(vals)/len(vals)

async def api(method,path,**kw):
    async with httpx.AsyncClient(timeout=30) as c:
        r=await c.request(method,API+path,**kw); r.raise_for_status(); return r.json()

async def track(kind,uid,pid=None,query=None):
    try: await api('POST','/analytics/events',json={'event_type':kind,'user_id':uid,'product_id':pid,'search_text':query,'metadata':{'source':'customer_bot'}})
    except Exception: log.debug('analytics failed',exc_info=True)

def price(p, rates=None):
    rates = rates or {'usd_rate': USD_RATE, 'shipping_per_kg': SHIPPING_PER_KG, 'multiplier': MULTIPLIER}
    return float(p.get('price_usd') or 0)*float(rates['usd_rate'])*float(rates['multiplier'])+(float(p.get('weight_grams') or 0)/1000)*float(rates['shipping_per_kg'])
def toman(v): return f'{v:,.0f} تومان'
def details(p, rates=None): return ('📦 '+str(p.get('name') or 'محصول')+'\n\n'+'💵 قیمت نهایی: '+toman(price(p, rates))+'\n'+'🏷 دسته: '+str(p.get('category') or '-')+'\n'+'📏 سایز: '+str(p.get('size') or '-')+'\n'+'⚖️ وزن: '+str(p.get('weight_grams') or '-')+' گرم\n'+'📍 موقعیت: '+str(p.get('location') or '-')+'\n\n'+'📝 '+str(p.get('description') or 'توضیحی ثبت نشده است.'))

async def current_pricing():
    try: return await api('GET','/public/pricing')
    except Exception: return {'usd_rate': USD_RATE, 'shipping_per_kg': SHIPPING_PER_KG, 'multiplier': MULTIPLIER}

def contact_target(value):
    if value is None:
        return None
    value=str(value).strip()
    if value.startswith('@'):
        value=value[1:]
    elif value.lower().startswith(('https://t.me/','http://t.me/','https://telegram.me/','http://telegram.me/','t.me/','telegram.me/')):
        value=re.sub(r'^https?://','',value,flags=re.I)
        value=re.sub(r'^(?:www\.)?(?:t\.me|telegram\.me)/','',value,flags=re.I)
        value=value.split('/',1)[0].split('?',1)[0].split('#',1)[0]
    # Numeric Telegram IDs are not usernames and must never become t.me links.
    if not value.isdigit() and re.fullmatch(r'[A-Za-z0-9_]{5,32}',value):
        return 'https://t.me/'+value
    # Telegram does not allow a normal URL button to open a private user by ID.
    # Never construct tg://user?id= links; use a verified public username instead.
    return None

async def admin_contact_url(product):
    for key in ('telegram_link_1','telegram_link_2'):
        target=contact_target(product.get(key))
        if target:
            return target

    category=str(product.get('category') or '').strip()
    routing={}
    if ROUTING_TOKEN:
        try:
            routing=await api('GET','/public/routing',headers={'X-Routing-Token':ROUTING_TOKEN})
        except Exception:
            log.debug('routing lookup failed',exc_info=True)

    usernames=routing.get('admin_usernames') or {}
    def admin_url(value):
        direct=contact_target(value)
        if direct:
            return direct
        if value is not None:
            return contact_target(usernames.get(str(value).strip()))
        return None

    for key in ('created_by_admin_id','owner_admin_id'):
        target=admin_url(product.get(key))
        if target:
            return target

    categories=routing.get('categories') or {}
    category_value=categories.get(category)
    if category_value is None:
        category_value=next((v for k,v in categories.items() if str(k).casefold()==category.casefold()),None)
    target=admin_url(category_value)
    if target:
        return target

    try:
        env_categories=json.loads(os.getenv('CATEGORY_ADMIN_IDS','{}'))
    except (TypeError, ValueError):
        env_categories={}
    env_category=env_categories.get(category)
    if env_category is None:
        env_category=next((v for k,v in env_categories.items() if str(k).casefold()==category.casefold()),None)
    target=admin_url(env_category)
    if target:
        return target

    target=admin_url(routing.get('default_admin_id'))
    if target:
        return target
    target=admin_url(os.getenv('DEFAULT_CUSTOMER_ADMIN_ID'))
    if target:
        return target

    # A URL button must already contain a public Telegram username. If the
    # assigned admin has only an ID, send the customer straight to support.
    return contact_target(SUPPORT_CONTACTS[0][1])

async def start(update,context):
    context.user_data.clear(); u=update.effective_user; await track('user_started',u.id)
    await update.message.reply_text(
        'سلام '+str(u.first_name or 'دوست عزیز')+' 👋\n\n'
        'به دستیار خرید فروشگاه الیکاشاپ خوش اومدی.\n'
        'برای پیدا کردن محصولات، دیدن قیمت نهایی و آشنایی با نحوه سفارش کنارت هستم.\n\n'
        'از منوی زیر انتخاب کن تا راهنماییت کنم:',
        reply_markup=menu(),
    )

async def send_cards(message,items,title):
    if not items: await message.reply_text('محصولی پیدا نشد. عبارت کوتاه‌تر یا نام برند را امتحان کن.',reply_markup=menu()); return
    kb=[[InlineKeyboardButton('📦 '+str(p.get('name') or 'محصول')[:35]+' · '+str(p.get('price_usd',0))+' USD',callback_data='product:'+str(p['id']))] for p in items[:20]]
    await message.reply_text(title+'\n\nبرای دیدن جزئیات انتخاب کن:',reply_markup=InlineKeyboardMarkup(kb))

async def search_start(update,context):
    context.user_data.clear()
    await update.message.reply_text('🔍 نام، برند یا ویژگی محصول را بنویس:',reply_markup=menu()); return SEARCH
async def search_text(update,context):
    q=(update.message.text or '').strip()
    try:
        ps=await api('GET','/products'); result=[p for s,p in sorted(((rank(q,p),p) for p in ps),reverse=True,key=lambda x:x[0]) if s>=.42][:20]
        context.user_data['search_results']=result
        await track('search' if result else 'search_no_result',update.effective_user.id,query=q); await send_cards(update.message,result,'🔍 نتایج جست‌وجوی «'+q+'»')
    except Exception: await update.message.reply_text('در دریافت نتایج مشکلی پیش آمد.',reply_markup=menu())
    return ConversationHandler.END
async def categories(update,context):
    try:
        ps=await api('GET','/products'); context.user_data['products']=ps; counts={}
        for p in ps: counts[p.get('category') or 'سایر']=counts.get(p.get('category') or 'سایر',0)+1
        await update.message.reply_text('📦 دسته‌بندی محصولات:',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(c+' ('+str(n)+')',callback_data='cat:'+c)] for c,n in sorted(counts.items())]))
    except Exception: await update.message.reply_text('فعلاً دریافت دسته‌بندی‌ها ممکن نیست.',reply_markup=menu())
async def cat_callback(update,context):
    q=update.callback_query; await q.answer(); c=q.data.split(':',1)[1]; ps=[p for p in context.user_data.get('products',[]) if (p.get('category') or 'سایر')==c]; await send_cards(q.message,ps,'📦 '+c)
async def newest(update,context):
    try: await send_cards(update.message,sorted(await api('GET','/products'),key=lambda p:p.get('id',0),reverse=True),'🆕 جدیدترین محصولات')
    except Exception: await update.message.reply_text('فعلاً دریافت محصولات ممکن نیست.',reply_markup=menu())
async def product(update,context):
    q=update.callback_query; await q.answer(); pid=int(q.data.split(':',1)[1])
    try:
        try:
            p=await api('GET','/products/'+str(pid))
        except Exception:
            p=next((x for x in context.user_data.get('search_results',[])+context.user_data.get('products',[]) if int(x.get('id',-1))==pid), None)
            if not p: raise
        rates=await current_pricing(); await track('view_product',q.from_user.id,pid); media=[]; handles=[]
        for raw in (p.get('original_photo_path') or '').split('|')[:3]:
            if not raw: continue
            local_path=os.path.join(os.path.dirname(os.path.abspath(__file__)),raw.replace('/',os.sep))
            if os.path.isfile(local_path):
                handle=open(local_path,'rb'); handles.append(handle); media.append(InputMediaPhoto(handle))
            else:
                media.append(InputMediaPhoto(API+'/media/'+quote(os.path.basename(raw),safe='')))
        if media: await q.message.reply_media_group(media=media)
        for handle in handles: handle.close()
        contact_url=await admin_contact_url(p)
        await q.message.reply_text(
            details(p, rates),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton('💬 ارتباط با ادمین فروش', url=contact_url)
            ]]),
        )
    except Exception:
        log.exception('customer product detail failed: id=%s api=%s', pid, API)
        await q.message.reply_text('نمایش این محصول موقتاً ممکن نیست. دوباره تلاش کن.',reply_markup=menu())
async def calc_start(update,context):
    context.user_data.clear()
    await update.message.reply_text('💰 قیمت دلاری محصول را وارد کن. مثال: 60', reply_markup=menu())
    return CALC_USD

async def calc_usd(update,context):
    try:
        value=float((update.message.text or '').replace(',', '.').strip())
        if value <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text('لطفاً قیمت دلاری را به‌صورت عدد مثبت وارد کن.')
        return CALC_USD
    context.user_data['calc_usd']=value
    await update.message.reply_text('⚖️ وزن محصول را به گرم وارد کن. اگر وزن را نمی‌دانی، 0 بفرست.', reply_markup=menu())
    return CALC_WEIGHT

async def calc_weight(update,context):
    try:
        weight=float((update.message.text or '').replace(',', '.').strip())
        if weight < 0: raise ValueError
    except ValueError:
        await update.message.reply_text('لطفاً وزن را به‌صورت عددی وارد کن؛ مثلاً 500 یا 0.')
        return CALC_WEIGHT
    usd=context.user_data.pop('calc_usd',0)
    rates=await current_pricing()
    total=usd*float(rates['usd_rate'])*float(rates['multiplier'])+(weight/1000)*float(rates['shipping_per_kg'])
    await update.message.reply_text('✅ برآورد قیمت نهایی:\n\n💵 قیمت خرید: '+str(usd)+' دلار\n⚖️ وزن: '+str(weight)+' گرم\n💰 قیمت نهایی: '+toman(total)+'\n\nاین مبلغ برآوردی است و قیمت نهایی هنگام ثبت سفارش تأیید می‌شود.', reply_markup=menu())
    return ConversationHandler.END

async def calc(update,context):
    return await calc_start(update,context)

def support_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, url='https://t.me/'+username)]
        for label, username in SUPPORT_CONTACTS
    ])

async def show_support_contacts(message, product_id=None):
    ref = ('\nکد محصول: '+str(product_id)) if product_id is not None else ''
    await message.reply_text(
        'لینک مستقیم مسئول این محصول در تلگرام در دسترس نبود. برای سفارش یا راهنمایی، از یکی از راه‌های تماس زیر پیام بده و نام/کد محصول را هم بفرست.'+ref,
        reply_markup=support_keyboard(),
    )

async def about(update,context):
    await update.message.reply_text(
        '🏪 دربارهٔ الیکاشاپ\n\n'
        'سلام و خوش‌آمدی 🌷\n'
        'الیکاشاپ با بیش از ۱۲ سال تجربهٔ خرید از فروشگاه‌ها و سایت‌های کانادا، برای تهیهٔ محصولات منتخب همراه شماست. 🇨🇦\n\n'
        '👟 پوشاک، کیف و کفش از برندهایی مثل آدیداس، ریباک، نایکی، زارا، کارترز، H&M، کلارکس، مایکل کورس، جیوکس و اکو؛\n'
        '🧴 محصولات آرایشی و مراقبت پوست از برندهایی مثل الیزابت گرانت، شیسیدو، استی لادر، لانکوم، کلینیک و توفیسد.\n\n'
        '🛍 دو روش سفارش داریم:\n'
        '• خرید از فروشگاه‌های کانادا: عکس محصول، سایز، رنگ، قیمت و اولویت‌هایت را برای ادمین سفارش بفرست.\n'
        '• خرید از سایت‌های معتبر کانادایی: لینک محصول، عکس و مشخصات موردنظرت را ارسال کن.\n\n'
        '💵 نرخ دلار روزانه اعلام می‌شود و فقط برای پرداخت همان روز معتبر است. مالیات ۱۳٪ انتاریو در قیمت دلاری لحاظ می‌شود. هزینهٔ حمل پس از رسیدن کالا به تهران و مشخص‌شدن وزن اعلام خواهد شد.\n'
        '📦 زمان معمول رسیدن کالا حدود ۵ تا ۷ هفته پس از خرید است و با توجه به شرایط ممکن است تغییر کند.\n\n'
        'پس از ثبت درخواست، حداکثر تا یک روز بعد برای پیگیری خریدشدن سفارش پیام بده و منتظر دریافت فاکتور بمان. لطفاً توضیحات را به‌صورت ویس نفرست. هزینه‌های احتمالی داخلی سایت نیز پیش از نهایی‌شدن سفارش اعلام می‌شود.\n\n'
        'برای تماس، یکی از ادمین‌های زیر را انتخاب کن:',
        reply_markup=support_keyboard(),
    )

async def faq(update,context):
    await update.message.reply_text(
        '❓ سوالات متداول\n\n'
        '۱) چطور برای محصولی که در بات می‌بینم سفارش ثبت کنم؟\n'
        'محصول را باز کن و «ارتباط با ادمین فروش» را بزن؛ چت ادمین مسئول همان محصول یا پشتیبانی مستقیم باز می‌شود.\n\n'
        '۲) برای خرید از فروشگاه‌های کانادا چه اطلاعاتی بفرستم؟\n'
        'عکس محصول، سایز، رنگ، قیمت و اگر گزینه‌ای اولویت دارد ترتیب اولویت‌ها را برای ادمین سفارش بفرست.\n\n'
        '۳) برای خرید از سایت چه چیزی لازم است؟\n'
        'لینک صفحهٔ محصول، عکس، سایز/رنگ و سایر مشخصات دلخواه را ارسال کن.\n\n'
        '۴) قیمت نهایی چطور محاسبه می‌شود؟\n'
        'مبلغ بر اساس قیمت محصول، نرخ دلار اعلام‌شده در همان روز، ضریب قیمت‌گذاری و هزینهٔ حمل محاسبه می‌شود. هزینهٔ حمل پس از رسیدن کالا و مشخص‌شدن وزن اعلام می‌شود.\n\n'
        '۵) مالیات انتاریو جداگانه اضافه می‌شود؟\n'
        'مالیات ۱۳٪ انتاریو در محاسبهٔ قیمت دلاری لحاظ می‌شود و جداگانه به مبلغ اعلامی اضافه نمی‌شود.\n\n'
        '۶) سفارش چه زمانی به تهران می‌رسد؟\n'
        'زمان معمول حدود ۵ تا ۷ هفته پس از خرید است؛ ممکن است بسته به شرایط کمتر یا بیشتر شود.\n\n'
        '۷) بعد از فرستادن سفارش چه کار کنم؟\n'
        'حداکثر تا یک روز بعد برای پیگیری خریدشدن سفارش پیام بده و منتظر فاکتور پرداخت بمان. لطفاً توضیحات را به‌صورت ویس نفرست.\n\n'
        '۸) هزینهٔ جانبی هم ممکن است داشته باشد؟\n'
        'اگر هزینهٔ داخلی سایت یا هزینهٔ دیگری وجود داشته باشد، پیش از نهایی‌شدن سفارش به تو اطلاع می‌دهیم.',
        reply_markup=menu(),
    )

async def help_cmd(update,context):
    await update.message.reply_text('از «جست‌وجوی محصولات» شروع کن؛ برای هر محصول دکمه گفتگو و ثبت درخواست وجود دارد.', reply_markup=menu())

async def flow_categories(update,context):
    context.user_data.clear(); await categories(update,context); return ConversationHandler.END

async def flow_about(update,context):
    context.user_data.clear(); await about(update,context); return ConversationHandler.END

async def flow_faq(update,context):
    context.user_data.clear(); await faq(update,context); return ConversationHandler.END

async def support_info(update,context):
    q=update.callback_query; await q.answer()
    await show_support_contacts(q.message)

async def cancel(update,context):
    context.user_data.clear(); m=update.effective_message; await m.reply_text('عملیات لغو شد.',reply_markup=menu()); return ConversationHandler.END

async def start_flow(update,context):
    await start(update,context)
    return ConversationHandler.END

def build_customer_flow():
    menu_routes=[
        MessageHandler(filters.Regex('^'+re.escape(BTN_CATS)+'$'),flow_categories),
        MessageHandler(filters.Regex('^'+re.escape(BTN_ABOUT)+'$'),flow_about),
        MessageHandler(filters.Regex('^'+re.escape(BTN_FAQ)+'$'),flow_faq),
    ]
    return ConversationHandler(
        entry_points=[
            CommandHandler('start',start_flow),
            MessageHandler(filters.Regex('^'+re.escape(BTN_SEARCH)+'$'),search_start),
            MessageHandler(filters.Regex('^'+re.escape(BTN_CALC)+'$'),calc_start),
        ],
        states={
            SEARCH:menu_routes+[MessageHandler(filters.TEXT & ~filters.COMMAND,search_text)],
            CALC_USD:menu_routes+[MessageHandler(filters.TEXT & ~filters.COMMAND,calc_usd)],
            CALC_WEIGHT:menu_routes+[MessageHandler(filters.TEXT & ~filters.COMMAND,calc_weight)],
        },
        fallbacks=[CommandHandler('cancel',cancel)],
        allow_reentry=True,
    )

def main():
    telegram_request=HTTPXRequest(connect_timeout=30, read_timeout=60, write_timeout=60, pool_timeout=30)
    updates_request=HTTPXRequest(connect_timeout=30, read_timeout=90, write_timeout=60, pool_timeout=30)
    app=Application.builder().token(TOKEN).request(telegram_request).get_updates_request(updates_request).build()
    app.add_handler(build_customer_flow())
    app.add_handler(CommandHandler('cancel',cancel))
    app.add_handler(CallbackQueryHandler(product,pattern=r'^product:\d+$'))
    app.add_handler(CallbackQueryHandler(cat_callback,pattern=r'^cat:'))
    app.add_handler(CallbackQueryHandler(support_info,pattern=r'^support_info$'))
    app.add_handler(MessageHandler(filters.Regex('^'+re.escape(BTN_CATS)+'$'),categories))
    app.add_handler(MessageHandler(filters.Regex('^'+re.escape(BTN_ABOUT)+'$'),about))
    app.add_handler(MessageHandler(filters.Regex('^'+re.escape(BTN_FAQ)+'$'),faq))
    app.run_polling(allowed_updates=Update.ALL_TYPES)
if __name__=='__main__': main()
