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

async def admin_target(product):
    direct=product.get('telegram_link_1') or product.get('telegram_link_2')
    if direct: return direct
    for key in ('created_by_admin_id','owner_admin_id'):
        value=product.get(key)
        if value: return 'tg://user?id='+str(value)
    if ROUTING_TOKEN:
        try:
            routing=await api('GET','/public/routing',headers={'X-Routing-Token':ROUTING_TOKEN})
            mapping=routing.get('categories',{})
            category=str(product.get('category') or '').strip()
            category_id=mapping.get(category) or mapping.get(category.casefold())
            if category_id: return 'tg://user?id='+str(category_id)
            default_id=routing.get('default_admin_id')
            if default_id: return 'tg://user?id='+str(default_id)
        except Exception:
            log.debug('routing lookup failed',exc_info=True)
    try:
        mapping=json.loads(os.getenv('CATEGORY_ADMIN_IDS','{}'))
    except (TypeError, ValueError):
        mapping={}
    category=str(product.get('category') or '').strip()
    category_id=mapping.get(category) or mapping.get(category.casefold())
    if category_id: return 'tg://user?id='+str(category_id)
    default_id=os.getenv('DEFAULT_CUSTOMER_ADMIN_ID','').strip()
    return 'tg://user?id='+default_id if default_id.isdigit() else None

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
        await q.message.reply_text(details(p, rates)); buttons=[]; owner=await admin_target(p)
        if owner: buttons.append([InlineKeyboardButton('💬 ارتباط با ادمین فروش',url=owner)])
        else: buttons.append([InlineKeyboardButton('💬 ارتباط با پشتیبانی',callback_data='support_info')])
        await q.message.reply_text('برای سفارش یا دریافت راهنمایی، با ادمین فروش در ارتباط باش:',reply_markup=InlineKeyboardMarkup(buttons))
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

async def about(update,context):
    await update.message.reply_text('🏪 الیکاشاپ\n\nما محصولات منتخب را از بازارهای مختلف پیدا می‌کنیم و برای خرید و ارسال آن‌ها راهنمایی‌ات می‌کنیم. برای هر محصول می‌توانی جزئیات، قیمت نهایی و راه ارتباط با ادمین را ببینی.', reply_markup=menu())

async def faq(update,context):
    await update.message.reply_text('❓ سوالات متداول\n\n۱) چطور محصول پیدا کنم؟\nاز «جست‌وجوی محصولات» نام، برند یا ویژگی محصول را بنویس.\n\n۲) قیمت نهایی چطور محاسبه می‌شود؟\nقیمت دلاری، نرخ روز و هزینه حمل در محاسبه لحاظ می‌شود.\n\n۳) چطور سفارش بدهم؟\nمحصول را باز کن و روی «گفتگو و ثبت درخواست» بزن تا با ادمین مربوط به همان محصول صحبت کنی.\n\n۴) اگر محصولی پیدا نشد؟\nعبارت کوتاه‌تر یا نام برند را امتحان کن و در صورت نیاز با پشتیبانی در تماس باش.', reply_markup=menu())

async def help_cmd(update,context):
    await update.message.reply_text('از «جست‌وجوی محصولات» شروع کن؛ برای هر محصول دکمه گفتگو و ثبت درخواست وجود دارد.', reply_markup=menu())

async def flow_categories(update,context):
    context.user_data.clear(); await categories(update,context); return ConversationHandler.END

async def flow_about(update,context):
    context.user_data.clear(); await about(update,context); return ConversationHandler.END

async def flow_faq(update,context):
    context.user_data.clear(); await faq(update,context); return ConversationHandler.END

async def support_info(update,context):
    q=update.callback_query; await q.answer('ادمین فروش هنوز برای این محصول تنظیم نشده است.')
    await q.message.reply_text('برای این محصول هنوز ادمین فروش مشخص نشده است. لطفاً بعداً دوباره تلاش کن.',reply_markup=menu())

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
