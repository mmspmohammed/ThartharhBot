import logging
from datetime import date

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      ReplyKeyboardMarkup, KeyboardButton)
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)

from config import (BOT_TOKEN, ADMIN_IDS,
                    DEFAULT_MAX_AGE_DIFF, DEFAULT_MAX_RATING_DIFF)
import db
import utils
from i18n import t

logging.basicConfig(level=logging.INFO)

# حالات إنشاء/تعديل الملف الشخصي (بالميموري)
STATE = {}          # user_id -> الخطوة الحالية
TEMP = {}           # user_id -> بيانات مؤقتة
PENDING_RATE = {}   # user_id -> chat_id بانتظار التقييم


def get_lang(user_id):
    u = db.get_user(user_id)
    return u["lang"] if u else "ar"


def main_menu_kb(lang):
    return ReplyKeyboardMarkup([
        [KeyboardButton(t(lang, "search_female")), KeyboardButton(t(lang, "search_male"))],
        [KeyboardButton(t(lang, "my_rating")), KeyboardButton(t(lang, "settings"))],
    ], resize_keyboard=True)


async def send_menu(message, lang):
    await message.reply_text(t(lang, "menu"), reply_markup=main_menu_kb(lang))


# ============ /start ============
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    u = db.get_user(user_id)
    if u and u["name"]:
        await send_menu(update.message, u["lang"])
    else:
        kb = [[InlineKeyboardButton("العربية 🇸🇾", callback_data="lang:ar"),
               InlineKeyboardButton("English 🇬🇧", callback_data="lang:en")]]
        await update.message.reply_text(
            t("ar", "choose_lang") + "\n\n" + t("en", "choose_lang"),
            reply_markup=InlineKeyboardMarkup(kb))


# ============ Callbacks ============
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    data = q.data

    if data.startswith("lang:"):
        lang = data.split(":")[1]
        db.ensure_user(user_id, lang)
        db.set_lang(user_id, lang)
        STATE[user_id] = "name"
        TEMP[user_id] = {}
        await q.message.reply_text(t(lang, "ask_name"))

    elif data.startswith("gender:"):
        lang = get_lang(user_id)
        TEMP.setdefault(user_id, {})["gender"] = data.split(":")[1]
        STATE[user_id] = "country"
        await q.message.reply_text(t(lang, "ask_country"))

    elif data == "end_chat":
        await end_chat(user_id, context)

    elif data == "report":
        await report_user(user_id, context)

    elif data.startswith("rate:"):
        stars = int(data.split(":")[1])
        chat_id = PENDING_RATE.pop(user_id, None)
        lang = get_lang(user_id)
        if chat_id:
            chat = db.get_chat(chat_id)
            if chat:
                partner = chat["user2"] if chat["user1"] == user_id else chat["user1"]
                db.add_rating(user_id, partner, stars)
        await q.message.reply_text(t(lang, "thanks_rating"))
        await send_menu(q.message, lang)

    elif data.startswith("adm:"):
        if user_id not in ADMIN_IDS:
            return
        await admin_action(data, q)


# ============ Profile wizard ============
async def handle_profile_step(message, user_id, text, lang):
    st = STATE[user_id]
    temp = TEMP.setdefault(user_id, {})

    if st == "name":
        temp["name"] = text[:50]
        STATE[user_id] = "gender"
        kb = [[InlineKeyboardButton(t(lang, "male"), callback_data="gender:male"),
               InlineKeyboardButton(t(lang, "female"), callback_data="gender:female")]]
        await message.reply_text(t(lang, "ask_gender"), reply_markup=InlineKeyboardMarkup(kb))

    elif st == "country":
        temp["country"] = text[:50]
        STATE[user_id] = "gov"
        await message.reply_text(t(lang, "ask_gov"))

    elif st == "gov":
        temp["governorate"] = text[:50]
        STATE[user_id] = "birth"
        await message.reply_text(t(lang, "ask_birthdate"))

    elif st == "birth":
        try:
            d = date.fromisoformat(text)
        except ValueError:
            await message.reply_text(t(lang, "bad_date"))
            return
        temp["birthdate"] = text
        temp["zodiac"] = utils.zodiac_of(d, lang)
        db.save_profile(user_id, temp)
        STATE.pop(user_id, None)
        TEMP.pop(user_id, None)
        await message.reply_text(t(lang, "profile_done"))
        await send_menu(message, lang)


# ============ Matching ============
def load_criteria():
    return {
        "max_age_diff": int(db.get_setting("max_age_diff", DEFAULT_MAX_AGE_DIFF)),
        "max_rating_diff": float(db.get_setting("max_rating_diff", DEFAULT_MAX_RATING_DIFF)),
        "same_country": db.get_setting("same_country", "0") == "1",
    }


def partner_card(partner, lang):
    return t(lang, "partner_info").format(
        gender=t(lang, partner["gender"]),
        age=utils.age_of(date.fromisoformat(partner["birthdate"])),
        zodiac=utils.zodiac_of(date.fromisoformat(partner["birthdate"]), lang),
        country=partner["country"],
        gov=partner["governorate"],
        duration=utils.join_duration(partner["joined_at"], lang),
    )


async def start_search(user_id, want_gender, message, context):
    lang = get_lang(user_id)
    me = db.get_user(user_id)
    crit = load_criteria()
    my_age = utils.age_of(date.fromisoformat(me["birthdate"]))

    best = None
    best_score = -1
    for c in db.get_candidates(me["gender"], want_gender):
        if c["user_id"] == user_id:
            continue
        if db.is_blocked(user_id, c["user_id"]) or db.is_blocked(c["user_id"], user_id):
            continue
        c_age = utils.age_of(date.fromisoformat(c["birthdate"]))
        age_diff = abs(my_age - c_age)
        rating_diff = abs(me["rating"] - c["rating"])
        # --- فلاتر إلزامية (المعايير اللي بتحطها أنت) ---
        if age_diff > crit["max_age_diff"]:
            continue
        if rating_diff > crit["max_rating_diff"]:
            continue
        if crit["same_country"] and me["country"].strip().lower() != c["country"].strip().lower():
            continue
        # --- نقاط التقارب: كل ما أعلى كل ما تطابق أقوى ---
        score = 0.0
        if me["country"].strip().lower() == c["country"].strip().lower():
            score += 2
        if me["governorate"].strip().lower() == c["governorate"].strip().lower():
            score += 3
        score += (crit["max_age_diff"] - age_diff)          # تقارب العمر
        score += (crit["max_rating_diff"] - rating_diff) * 2  # تقارب التقييم
        if score > best_score:
            best_score = score
            best = c

    if best:
        db.remove_waiting(best["user_id"])
        db.create_chat(user_id, best["user_id"])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(t(lang, "end_chat"), callback_data="end_chat"),
            InlineKeyboardButton(t(lang, "report"), callback_data="report"),
        ]])
        await context.bot.send_message(
            user_id, t(lang, "matched") + "\n\n" + partner_card(best, lang),
            reply_markup=kb)
        plang = best["lang"]
        kb2 = InlineKeyboardMarkup([[
            InlineKeyboardButton(t(plang, "end_chat"), callback_data="end_chat"),
            InlineKeyboardButton(t(plang, "report"), callback_data="report"),
        ]])
        await context.bot.send_message(
            best["user_id"], t(plang, "matched") + "\n\n" + partner_card(me, plang),
            reply_markup=kb2)
    else:
        db.add_waiting(user_id, want_gender)
        await message.reply_text(t(lang, "searching"))


# ============ Chat relay ============
async def relay(update: Update, chat, user_id, lang):
    partner_id = chat["user2"] if chat["user1"] == user_id else chat["user1"]
    try:
        await update.message.copy(partner_id)
    except Exception:
        await update.message.reply_text(t(lang, "relay_failed"))


async def end_chat(user_id, context):
    chat = db.get_active_chat(user_id)
    if not chat:
        return
    db.end_chat(chat["id"])
    partner_id = chat["user2"] if chat["user1"] == user_id else chat["user1"]
    for uid in (user_id, partner_id):
        PENDING_RATE[uid] = chat["id"]
        l = get_lang(uid)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"{i} ⭐", callback_data=f"rate:{i}") for i in range(1, 6)
        ]])
        try:
            await context.bot.send_message(
                uid, t(l, "chat_ended") + "\n" + t(l, "rate_partner"), reply_markup=kb)
        except Exception:
            pass


async def report_user(user_id, context):
    chat = db.get_active_chat(user_id)
    if not chat:
        return
    partner_id = chat["user2"] if chat["user1"] == user_id else chat["user1"]
    db.add_block(user_id, partner_id)
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(
                aid, f"🚩 بلاغ جديد\nالمُبلِّغ: {user_id}\nالطرف الآخر: {partner_id}\nرقم الدردشة: {chat['id']}")
        except Exception:
            pass
    lang = get_lang(user_id)
    await context.bot.send_message(user_id, t(lang, "report_sent"))


# ============ Admin panel ============
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await send_admin_panel(update.message)


async def send_admin_panel(message):
    crit = load_criteria()
    txt = (f"⚙️ لوحة تحكم الأدمن\n\n"
           f"• أقصى فرق بالعمر: {crit['max_age_diff']} سنة\n"
           f"• أقصى فرق بالتقييم: {crit['max_rating_diff']}\n"
           f"• نفس الدولة إجبارية: {'نعم ✅' if crit['same_country'] else 'لا ❌'}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("عمر +", callback_data="adm:age+"),
         InlineKeyboardButton("عمر −", callback_data="adm:age-")],
        [InlineKeyboardButton("تقييم +", callback_data="adm:rate+"),
         InlineKeyboardButton("تقييم −", callback_data="adm:rate-")],
        [InlineKeyboardButton("تبديل شرط الدولة", callback_data="adm:country")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="adm:stats")],
    ])
    await message.reply_text(txt, reply_markup=kb)


async def admin_action(data, q):
    if data == "adm:age+":
        v = int(db.get_setting("max_age_diff", DEFAULT_MAX_AGE_DIFF)) + 1
        db.set_setting("max_age_diff", str(v))
    elif data == "adm:age-":
        v = max(1, int(db.get_setting("max_age_diff", DEFAULT_MAX_AGE_DIFF)) - 1)
        db.set_setting("max_age_diff", str(v))
    elif data == "adm:rate+":
        v = float(db.get_setting("max_rating_diff", DEFAULT_MAX_RATING_DIFF)) + 0.5
        db.set_setting("max_rating_diff", str(v))
    elif data == "adm:rate-":
        v = max(0.5, float(db.get_setting("max_rating_diff", DEFAULT_MAX_RATING_DIFF)) - 0.5)
        db.set_setting("max_rating_diff", str(v))
    elif data == "adm:country":
        cur = db.get_setting("same_country", "0")
        db.set_setting("same_country", "0" if cur == "1" else "1")
    elif data == "adm:stats":
        s = db.stats()
        await q.message.reply_text(
            f"📊 الإحصائيات\n• المستخدمون: {s['users']}\n"
            f"• دردشات نشطة الآن: {s['active_chats']}\n• بانتظار التطابق: {s['waiting']}")
        return
    await send_admin_panel(q.message)


# ============ Message router ============
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    user_id = update.effective_user.id
    text = (msg.text or "").strip()
    lang = get_lang(user_id)

    # 1) داخل معالج إنشاء/تعديل الملف الشخصي
    if user_id in STATE:
        if not text:
            await msg.reply_text(t(lang, "bad_date") if STATE[user_id] == "birth" else "✍️")
            return
        await handle_profile_step(msg, user_id, text, lang)
        return

    # 2) داخل دردشة نشطة: مرّر الرسالة للطرف الآخر
    chat = db.get_active_chat(user_id)
    if chat:
        await relay(update, chat, user_id, lang)
        return

    if not text:
        return

    # 3) أزرار القائمة
    if text == t(lang, "search_female"):
        await start_search(user_id, "female", msg, context)
    elif text == t(lang, "search_male"):
        await start_search(user_id, "male", msg, context)
    elif text == t(lang, "cancel_search"):
        db.remove_waiting(user_id)
        await msg.reply_text(t(lang, "cancelled"))
    elif text == t(lang, "my_rating"):
        u = db.get_user(user_id)
        await msg.reply_text(t(lang, "your_rating").format(
            rating=round(u["rating"], 2), count=u["ratings_count"]))
    elif text == t(lang, "settings"):
        kb = ReplyKeyboardMarkup([
            [KeyboardButton(t(lang, "edit_profile")), KeyboardButton(t(lang, "change_lang"))],
            [KeyboardButton(t(lang, "back"))],
        ], resize_keyboard=True)
        await msg.reply_text(t(lang, "settings_menu"), reply_markup=kb)
    elif text == t(lang, "edit_profile"):
        STATE[user_id] = "name"
        TEMP[user_id] = {}
        await msg.reply_text(t(lang, "ask_name"))
    elif text == t(lang, "change_lang"):
        kb = [[InlineKeyboardButton("العربية 🇸🇾", callback_data="lang:ar"),
               InlineKeyboardButton("English 🇬🇧", callback_data="lang:en")]]
        await msg.reply_text(t(lang, "choose_lang"), reply_markup=InlineKeyboardMarkup(kb))
    elif text == t(lang, "back"):
        await send_menu(msg, lang)
    else:
        await send_menu(msg, lang)


# ============ Main ============
def main():
    if "ضع_التوكن_هنا" in BOT_TOKEN:
        raise SystemExit("⚠️ ضع التوكن في config.py أولاً!")
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, on_message))
    app.run_polling()


if __name__ == "__main__":
    main()
