import os
import re
import sqlite3
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta, timezone

from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["BOT_TOKEN"]
PORT = int(os.environ.get("PORT", "10000"))
DB = "afterhours_stats.db"

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"AFTERHOURS Manager OK")
    def log_message(self, *args):
        pass

threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", PORT), Health).serve_forever(),
    daemon=True
).start()

def conn():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS stats(
        chat_id INTEGER, user_id INTEGER, name TEXT, username TEXT,
        messages INTEGER DEFAULT 0, last_seen TEXT,
        PRIMARY KEY(chat_id,user_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS warns(
        chat_id INTEGER, user_id INTEGER, count INTEGER DEFAULT 0,
        PRIMARY KEY(chat_id,user_id))""")
    c.commit()
    return c

def track(m):
    if not m or not m.from_user or m.from_user.is_bot: return
    c = conn(); u = m.from_user
    c.execute("""INSERT INTO stats VALUES(?,?,?,?,1,?)
        ON CONFLICT(chat_id,user_id) DO UPDATE SET
        name=excluded.name, username=excluded.username,
        messages=messages+1, last_seen=excluded.last_seen""",
        (m.chat_id,u.id,u.full_name,u.username or "",m.date.isoformat()))
    c.commit(); c.close()

async def admin(update, uid=None):
    uid = uid or update.effective_user.id
    try:
        x = await update.effective_chat.get_member(uid)
        return x.status in ("administrator","creator")
    except: return False

async def guard(update):
    if not await admin(update):
        await update.effective_message.reply_text("⛔ فقط ادمین‌ها می‌تونن از این دستور استفاده کنن.")
        return False
    return True

def target(update):
    r = update.effective_message.reply_to_message
    return r.from_user if r else None

async def need_target(update):
    u = target(update)
    if not u:
        await update.effective_message.reply_text("👤 روی پیام شخص Reply کن و دستور رو بفرست.")
    return u

def mention(u):
    return u.mention_html()

async def ban(update, context):
    if not await guard(update): return
    u = await need_target(update)
    if not u: return
    if await admin(update,u.id):
        await update.effective_message.reply_text("⛔ نمی‌تونم ادمین یا Owner رو بن کنم."); return
    await update.effective_chat.ban_member(u.id)
    await update.effective_message.reply_text(f"🔨 {mention(u)} بن شد.",parse_mode="HTML")

async def unban(update, context):
    if not await guard(update): return
    u = await need_target(update)
    if not u: return
    await update.effective_chat.unban_member(u.id, only_if_banned=True)
    await update.effective_message.reply_text(f"🔓 بن {mention(u)} رفع شد.",parse_mode="HTML")

async def kick(update, context):
    if not await guard(update): return
    u = await need_target(update)
    if not u: return
    if await admin(update,u.id):
        await update.effective_message.reply_text("⛔ نمی‌تونم ادمین رو اخراج کنم."); return
    await update.effective_chat.ban_member(u.id)
    await update.effective_chat.unban_member(u.id)
    await update.effective_message.reply_text(f"🚪 {mention(u)} اخراج شد.",parse_mode="HTML")

ALL_PERMS = dict(can_send_messages=True,can_send_audios=True,
    can_send_documents=True,can_send_photos=True,can_send_videos=True,
    can_send_video_notes=True,can_send_voice_notes=True,can_send_polls=True,
    can_send_other_messages=True,can_add_web_page_previews=True)

async def mute(update, context):
    if not await guard(update): return
    u = await need_target(update)
    if not u: return
    if await admin(update,u.id):
        await update.effective_message.reply_text("⛔ نمی‌تونم ادمین رو ساکت کنم."); return
    await update.effective_chat.restrict_member(u.id, permissions=ChatPermissions(can_send_messages=False))
    await update.effective_message.reply_text(f"🔇 {mention(u)} ساکت شد.",parse_mode="HTML")

async def unmute(update, context):
    if not await guard(update): return
    u = await need_target(update)
    if not u: return
    await update.effective_chat.restrict_member(u.id, permissions=ChatPermissions(**ALL_PERMS))
    await update.effective_message.reply_text(f"🔊 سکوت {mention(u)} رفع شد.",parse_mode="HTML")

async def timed_mute(update, context, seconds=600):
    if not await guard(update): return
    u = await need_target(update)
    if not u: return
    if await admin(update,u.id):
        await update.effective_message.reply_text("⛔ نمی‌تونم ادمین رو ساکت کنم."); return
    await update.effective_chat.restrict_member(
        u.id, permissions=ChatPermissions(can_send_messages=False),
        until_date=datetime.now(timezone.utc)+timedelta(seconds=seconds))
    await update.effective_message.reply_text(f"🔇 {mention(u)} به مدت {seconds//60} دقیقه ساکت شد.",parse_mode="HTML")

async def warn(update, context):
    if not await guard(update): return
    u = await need_target(update)
    if not u: return
    if await admin(update,u.id):
        await update.effective_message.reply_text("⛔ نمی‌تونم به ادمین اخطار بدم."); return
    c=conn()
    row=c.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?",(update.effective_chat.id,u.id)).fetchone()
    n=(row[0] if row else 0)+1
    c.execute("""INSERT INTO warns VALUES(?,?,?) ON CONFLICT(chat_id,user_id)
        DO UPDATE SET count=excluded.count""",(update.effective_chat.id,u.id,n))
    c.commit(); c.close()
    if n>=3:
        await update.effective_chat.ban_member(u.id)
        await update.effective_message.reply_text(f"🚫 {mention(u)} اخطار سوم رو گرفت و بن شد.",parse_mode="HTML")
    else:
        await update.effective_message.reply_text(f"⚠️ {mention(u)} اخطار گرفت ({n}/3).",parse_mode="HTML")

async def unwarn(update, context):
    if not await guard(update): return
    u=await need_target(update)
    if not u:return
    c=conn(); row=c.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?",(update.effective_chat.id,u.id)).fetchone()
    n=max(0,(row[0] if row else 0)-1)
    c.execute("""INSERT INTO warns VALUES(?,?,?) ON CONFLICT(chat_id,user_id)
        DO UPDATE SET count=excluded.count""",(update.effective_chat.id,u.id,n))
    c.commit();c.close()
    await update.effective_message.reply_text(f"⚠️ اخطار {mention(u)} کم شد. ({n}/3)",parse_mode="HTML")

async def delete(update, context):
    if not await guard(update): return
    r=update.effective_message.reply_to_message
    if not r:
        await update.effective_message.reply_text("🗑️ روی پیام موردنظر Reply کن.");return
    await r.delete(); await update.effective_message.delete()

async def purge(update, context):
    if not await guard(update): return
    r=update.effective_message.reply_to_message
    if not r:
        await update.effective_message.reply_text("🧹 روی اولین پیام Reply کن و بنویس: پاک کردن چند پیام 20");return
    n=10
    parts=(update.effective_message.text or "").split()
    if len(parts)>3 and parts[-1].isdigit(): n=min(100,max(1,int(parts[-1])))
    for mid in range(r.message_id, update.effective_message.message_id+1):
        try: await update.effective_chat.delete_message(mid)
        except: pass

async def pin(update, context):
    if not await guard(update): return
    r=update.effective_message.reply_to_message
    if not r:
        await update.effective_message.reply_text("📌 روی پیام موردنظر Reply کن.");return
    await r.pin(disable_notification=True)
    await update.effective_message.delete()

async def unpin(update, context):
    if not await guard(update): return
    await update.effective_chat.unpin_message()
    await update.effective_message.reply_text("📍 پیام آن‌پین شد.")

async def tag_all(update, context):
    if not await guard(update): return
    c=conn(); rows=c.execute("SELECT user_id,name FROM stats WHERE chat_id=? ORDER BY last_seen DESC",(update.effective_chat.id,)).fetchall();c.close()
    if not rows:
        await update.effective_message.reply_text("هنوز عضوی ثبت نشده.");return
    text="📣 "
    for uid,name in rows:
        tag=f'<a href="tg://user?id={uid}">{name}</a> '
        if len(text)+len(tag)>3500:
            await update.effective_message.reply_text(text,parse_mode="HTML"); text="📣 "
        text+=tag
    if text!="📣 ": await update.effective_message.reply_text(text,parse_mode="HTML")

async def stats(update, context):
    if not await guard(update): return
    c=conn(); rows=c.execute("SELECT name,username,messages FROM stats WHERE chat_id=? ORDER BY messages DESC LIMIT 10",(update.effective_chat.id,)).fetchall();c.close()
    if not rows:
        await update.effective_message.reply_text("📊 هنوز آماری ثبت نشده.");return
    out=["🏆 فعال‌ترین اعضا"]
    for i,(name,user,n) in enumerate(rows,1): out.append(f"{i}. {('@'+user) if user else name} — {n} پیام")
    await update.effective_message.reply_text("\n".join(out))

async def my_stats(update, context):
    c=conn(); row=c.execute("SELECT messages FROM stats WHERE chat_id=? AND user_id=?",(update.effective_chat.id,update.effective_user.id)).fetchone()
    w=c.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?",(update.effective_chat.id,update.effective_user.id)).fetchone();c.close()
    await update.effective_message.reply_text(f"📊 آمار من\n\n💬 پیام: {row[0] if row else 0}\n⚠️ اخطار: {w[0] if w else 0}/3")

async def admins(update, context):
    if not await guard(update): return
    ms=await update.effective_chat.get_administrators()
    await update.effective_message.reply_text("👑 ادمین‌ها:\n" + "\n".join("• "+mention(x.user) for x in ms),parse_mode="HTML")

async def start(update, context):
    await update.effective_message.reply_text("🖤 AFTERHOURS Manager\n\nروی پیام کاربر Reply کن و بنویس:\nبن | رفع بن | اخراج | سکوت | رفع سکوت | اخطار | رفع اخطار | حذف پیام\n\n/help برای راهنما")

async def help_cmd(update, context):
    await start(update,context)

COMMANDS={
    "بن":ban,"رفع بن":unban,"اخراج":kick,"سکوت":mute,"رفع سکوت":unmute,
    "اخطار":warn,"رفع اخطار":unwarn,"حذف پیام":delete,"پاک کردن چند پیام":purge,
    "پین کردن پیام":pin,"آن‌پین کردن پیام":unpin,"تگ همه":tag_all,
    "آمار کلی":stats,"آمار من":my_stats,"لیست ادمین‌ها":admins
}

async def router(update, context):
    m=update.effective_message
    if not m:return
    track(m)
    text=(m.text or "").strip()
    if text.startswith("سکوت زمان‌دار"):
        parts=text.split()
        raw=parts[2] if len(parts)>2 else "10m"
        q=re.match(r"(\d+)(s|m|h)?$",raw.lower())
        seconds=int(q.group(1))*({"s":1,"m":60,"h":3600}[q.group(2) or "m"]) if q else 600
        await timed_mute(update,context,min(seconds,86400));return
    if text in ("قفل گروه","باز کردن گروه"):
        if await guard(update):
            if text=="قفل گروه":
                await update.effective_chat.set_permissions(ChatPermissions(can_send_messages=False))
                await m.reply_text("🔒 گروه برای اعضا قفل شد.")
            else:
                await update.effective_chat.set_permissions(ChatPermissions(**ALL_PERMS))
                await m.reply_text("🔓 گروه باز شد.")
        return
    for prefix in ("قفل ","باز کردن "):
        if text.startswith(prefix):
            item=text[len(prefix):].strip()
            types={"عکس":"photo","ویدیو":"video","فایل":"document","استیکر":"sticker","گیف":"animation"}
            if item in types:
                if await guard(update):
                    context.chat_data["lock_"+types[item]]=prefix=="قفل "
                    await m.reply_text(("🔒" if prefix=="قفل " else "🔓")+f" {item} "+("قفل شد." if prefix=="قفل " else "باز شد."))
                return
    if text in COMMANDS: await COMMANDS[text](update,context)
    else: await media_guard(update,context)

async def media_guard(update,context):
    m=update.effective_message
    if not m or not m.from_user or await admin(update,m.from_user.id): return
    checks={"photo":bool(m.photo),"video":bool(m.video),"document":bool(m.document),"sticker":bool(m.sticker),"animation":bool(m.animation)}
    for k,v in checks.items():
        if v and context.chat_data.get("lock_"+k,False):
            try: await m.delete()
            except: pass
            return

def main():
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("help",help_cmd))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND,router))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":
    main()
