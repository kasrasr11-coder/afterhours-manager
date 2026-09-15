import os
import logging
from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["BOT_TOKEN"]

async def is_admin(update, user_id):
    m = await update.effective_chat.get_member(user_id)
    return m.status in ("administrator", "creator")

async def guard(update):
    if not await is_admin(update, update.effective_user.id):
        await update.effective_message.reply_text("⛔ فقط ادمین‌ها می‌تونن از این دستور استفاده کنن.")
        return False
    return True

def target(update):
    r = update.effective_message.reply_to_message
    return r.from_user if r else None

async def ban(update, context):
    if not await guard(update): return
    u = target(update)
    if not u:
        return await update.effective_message.reply_text("👤 روی پیام شخص Reply کن و «بن» بفرست.")
    if await is_admin(update, u.id):
        return await update.effective_message.reply_text("⛔ نمی‌تونم یک ادمین رو بن کنم.")
    await update.effective_chat.ban_member(u.id)
    await update.effective_message.reply_text(f"🔨 {u.mention_html()} بن شد.", parse_mode="HTML")

async def unban(update, context):
    if not await guard(update): return
    u = target(update)
    if not u:
        return await update.effective_message.reply_text("👤 روی پیام شخص Reply کن و «رفع بن» بفرست.")
    await update.effective_chat.unban_member(u.id, only_if_banned=True)
    await update.effective_message.reply_text(f"🔓 {u.mention_html()} رفع بن شد.", parse_mode="HTML")

async def kick(update, context):
    if not await guard(update): return
    u = target(update)
    if not u:
        return await update.effective_message.reply_text("👤 روی پیام شخص Reply کن و «اخراج» بفرست.")
    if await is_admin(update, u.id):
        return await update.effective_message.reply_text("⛔ نمی‌تونم یک ادمین رو اخراج کنم.")
    await update.effective_chat.ban_member(u.id)
    await update.effective_chat.unban_member(u.id)
    await update.effective_message.reply_text(f"🚪 {u.mention_html()} اخراج شد.", parse_mode="HTML")

async def mute(update, context):
    if not await guard(update): return
    u = target(update)
    if not u:
        return await update.effective_message.reply_text("👤 روی پیام شخص Reply کن و «سکوت» بفرست.")
    if await is_admin(update, u.id):
        return await update.effective_message.reply_text("⛔ نمی‌تونم یک ادمین رو ساکت کنم.")
    await update.effective_chat.restrict_member(u.id, permissions=ChatPermissions(can_send_messages=False))
    await update.effective_message.reply_text(f"🔇 {u.mention_html()} ساکت شد.", parse_mode="HTML")

async def unmute(update, context):
    if not await guard(update): return
    u = target(update)
    if not u:
        return await update.effective_message.reply_text("👤 روی پیام شخص Reply کن و «رفع سکوت» بفرست.")
    p = ChatPermissions(
        can_send_messages=True, can_send_audios=True, can_send_documents=True,
        can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
        can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
        can_add_web_page_previews=True
    )
    await update.effective_chat.restrict_member(u.id, permissions=p)
    await update.effective_message.reply_text(f"🔊 {u.mention_html()} رفع سکوت شد.", parse_mode="HTML")

async def warn(update, context):
    if not await guard(update): return
    u = target(update)
    if not u:
        return await update.effective_message.reply_text("👤 روی پیام شخص Reply کن و «اخطار» بفرست.")
    if await is_admin(update, u.id):
        return await update.effective_message.reply_text("⛔ نمی‌تونم به یک ادمین اخطار بدم.")
    ws = context.application.bot_data.setdefault("warnings", {})
    k = (update.effective_chat.id, u.id)
    ws[k] = ws.get(k, 0) + 1
    if ws[k] >= 3:
        await update.effective_chat.ban_member(u.id)
        text = f"🚫 {u.mention_html()} اخطار سوم را گرفت و بن شد."
    else:
        text = f"⚠️ {u.mention_html()} اخطار گرفت. ({ws[k]}/3)"
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def delete(update, context):
    if not await guard(update): return
    r = update.effective_message.reply_to_message
    if not r:
        return await update.effective_message.reply_text("🗑️ روی پیام موردنظر Reply کن و «حذف پیام» بفرست.")
    await r.delete()
    await update.effective_message.delete()

async def start(update, context):
    await update.effective_message.reply_text(
        "🖤 AFTERHOURS Manager\n\n"
        "روی پیام یک کاربر Reply کن و بنویس:\n"
        "بن | رفع بن | اخراج | سکوت | رفع سکوت | اخطار | حذف پیام"
    )

COMMANDS = {
    "بن": ban, "رفع بن": unban, "اخراج": kick, "سکوت": mute,
    "رفع سکوت": unmute, "اخطار": warn, "حذف پیام": delete
}

async def router(update, context):
    f = COMMANDS.get((update.effective_message.text or "").strip())
    if f:
        await f(update, context)

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router))
app.run_polling(allowed_updates=Update.ALL_TYPES)
