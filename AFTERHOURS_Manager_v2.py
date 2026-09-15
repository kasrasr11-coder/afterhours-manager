import os
import re
import sqlite3
import threading
import logging
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.environ["BOT_TOKEN"]
PORT = int(os.environ.get("PORT", "10000"))
DB = os.environ.get("DB_PATH", "afterhours.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

lock = threading.Lock()
db = sqlite3.connect(DB, check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS users(
 chat_id INTEGER, user_id INTEGER, username TEXT, first_name TEXT,
 messages INTEGER DEFAULT 0, warnings INTEGER DEFAULT 0, mutes INTEGER DEFAULT 0,
 bans INTEGER DEFAULT 0, kicks INTEGER DEFAULT 0, last_seen TEXT,
 PRIMARY KEY(chat_id,user_id))""")
db.execute("""CREATE TABLE IF NOT EXISTS events(
 chat_id INTEGER, user_id INTEGER, kind TEXT, created_at TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS settings(
 chat_id INTEGER PRIMARY KEY, rules TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS locks(
 chat_id INTEGER, kind TEXT, PRIMARY KEY(chat_id,kind))""")
db.commit()


def utcnow():
    return datetime.now(timezone.utc)


def track(chat_id, user):
    if user.is_bot:
        return
    t = utcnow().isoformat()
    with lock:
        db.execute("""INSERT INTO users(chat_id,user_id,username,first_name,messages,last_seen)
        VALUES(?,?,?,?,1,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET
        username=excluded.username, first_name=excluded.first_name,
        messages=users.messages+1,last_seen=excluded.last_seen""",
        (chat_id,user.id,user.username or "",user.first_name or "",t))
        db.execute("INSERT INTO events VALUES(?,?,?,?)",(chat_id,user.id,"message",t))
        db.commit()


def remember(chat_id, user):
    with lock:
        db.execute("""INSERT INTO users(chat_id,user_id,username,first_name,last_seen)
        VALUES(?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET
        username=excluded.username,first_name=excluded.first_name,last_seen=excluded.last_seen""",
        (chat_id,user.id,user.username or "",user.first_name or "",utcnow().isoformat()))
        db.commit()


def target(update):
    m = update.effective_message
    return m.reply_to_message.from_user if m and m.reply_to_message else None


async def admin(update, uid=None):
    try:
        uid = uid or update.effective_user.id
        m = await update.effective_chat.get_member(uid)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


async def need_admin(update):
    if not await admin(update):
        await update.effective_message.reply_text("⛔️ فقط ادمین می‌تواند این دستور را اجرا کند.")
        return False
    return True


def tag(u):
    name = (u.first_name or "کاربر").replace("<","").replace(">","")
    return f'<a href="tg://user?id={u.id}">{name}</a>'


def bump(chat_id, uid, field, kind):
    with lock:
        db.execute(f"UPDATE users SET {field}={field}+1 WHERE chat_id=? AND user_id=?",(chat_id,uid))
        db.execute("INSERT INTO events VALUES(?,?,?,?)",(chat_id,uid,kind,utcnow().isoformat()))
        db.commit()


async def start(update, context):
    await update.effective_message.reply_text(
        "🖤 AFTERHOURS Manager\n\n"
        "آمار: آمار | آمار امروز | آمار هفته | آمار ماه | آمار من | فعال‌ترین‌ها\n"
        "مدیریت: بن | رفع بن | اخراج | سکوت | رفع سکوت | سکوت زمان‌دار 10 | اخطار\n"
        "پیام: حذف پیام | پاک کردن چند پیام 20 | پین کردن پیام | آن‌پین کردن پیام\n"
        "قفل: قفل عکس | قفل ویدیو | قفل فایل | قفل استیکر | قفل گیف | قفل رسانه | باز کردن گروه\n"
        "سایر: قوانین | تعیین قوانین گروه ... | تگ اعضا"
    )


async def ban(update, context):
    if not await need_admin(update): return
    u=target(update)
    if not u: return await update.effective_message.reply_text("روی پیام شخص Reply کن و «بن» بفرست.")
    if await admin(update,u.id): return await update.effective_message.reply_text("⛔️ ادمین را نمی‌شود بن کرد.")
    try:
        await update.effective_chat.ban_member(u.id)
        remember(update.effective_chat.id,u); bump(update.effective_chat.id,u.id,"bans","ban")
        await update.effective_message.reply_text(f"🚫 {tag(u)} بن شد.",parse_mode="HTML")
    except Exception as e: await update.effective_message.reply_text(f"❌ بن انجام نشد: {e}")


async def unban(update, context):
    if not await need_admin(update): return
    u=target(update)
    if not u: return await update.effective_message.reply_text("روی پیام شخص Reply کن و «رفع بن» بفرست.")
    try:
        await update.effective_chat.unban_member(u.id)
        await update.effective_message.reply_text(f"✅ بن {tag(u)} برداشته شد.",parse_mode="HTML")
    except Exception as e: await update.effective_message.reply_text(f"❌ رفع بن انجام نشد: {e}")


async def kick(update, context):
    if not await need_admin(update): return
    u=target(update)
    if not u: return await update.effective_message.reply_text("روی پیام شخص Reply کن و «اخراج» بفرست.")
    if await admin(update,u.id): return await update.effective_message.reply_text("⛔️ ادمین را نمی‌شود اخراج کرد.")
    try:
        await update.effective_chat.ban_member(u.id); await update.effective_chat.unban_member(u.id)
        remember(update.effective_chat.id,u); bump(update.effective_chat.id,u.id,"kicks","kick")
        await update.effective_message.reply_text(f"👢 {tag(u)} اخراج شد.",parse_mode="HTML")
    except Exception as e: await update.effective_message.reply_text(f"❌ اخراج انجام نشد: {e}")


async def mute(update, context, minutes=None):
    if not await need_admin(update): return
    u=target(update)
    if not u: return await update.effective_message.reply_text("روی پیام شخص Reply کن و «سکوت» بفرست.")
    if await admin(update,u.id): return await update.effective_message.reply_text("⛔️ ادمین را نمی‌شود ساکت کرد.")
    try:
        until = utcnow()+timedelta(minutes=minutes) if minutes else None
        await update.effective_chat.restrict_member(u.id,ChatPermissions(can_send_messages=False),until_date=until)
        remember(update.effective_chat.id,u); bump(update.effective_chat.id,u.id,"mutes","mute")
        suffix=f" ({minutes} دقیقه)" if minutes else ""
        await update.effective_message.reply_text(f"🔇 {tag(u)} ساکت شد{suffix}.",parse_mode="HTML")
    except Exception as e: await update.effective_message.reply_text(f"❌ سکوت انجام نشد: {e}")


async def unmute(update, context):
    if not await need_admin(update): return
    u=target(update)
    if not u: return await update.effective_message.reply_text("روی پیام شخص Reply کن و «رفع سکوت» بفرست.")
    try:
        p=ChatPermissions(can_send_messages=True,can_send_audios=True,can_send_documents=True,
          can_send_photos=True,can_send_videos=True,can_send_video_notes=True,
          can_send_voice_notes=True,can_send_polls=True,can_send_other_messages=True,
          can_add_web_page_previews=True)
        await update.effective_chat.restrict_member(u.id,p)
        await update.effective_message.reply_text(f"🔊 سکوت {tag(u)} برداشته شد.",parse_mode="HTML")
    except Exception as e: await update.effective_message.reply_text(f"❌ رفع سکوت انجام نشد: {e}")


async def timed_mute(update, context):
    m=re.search(r"(\d+)",update.effective_message.text or "")
    if not m: return await update.effective_message.reply_text("مثال: سکوت زمان‌دار 10")
    n=int(m.group(1))
    if not 1<=n<=10080: return await update.effective_message.reply_text("زمان بین ۱ دقیقه تا ۷ روز باشد.")
    await mute(update,context,n)


async def warn(update, context):
    if not await need_admin(update): return
    u=target(update)
    if not u: return await update.effective_message.reply_text("روی پیام شخص Reply کن و «اخطار» بفرست.")
    if await admin(update,u.id): return await update.effective_message.reply_text("⛔️ به ادمین اخطار نمی‌دهم.")
    cid=update.effective_chat.id; remember(cid,u)
    with lock:
        db.execute("UPDATE users SET warnings=warnings+1 WHERE chat_id=? AND user_id=?",(cid,u.id))
        db.execute("INSERT INTO events VALUES(?,?,?,?)",(cid,u.id,"warning",utcnow().isoformat())); db.commit()
        n=db.execute("SELECT warnings FROM users WHERE chat_id=? AND user_id=?",(cid,u.id)).fetchone()[0]
    if n>=3:
        try:
            await update.effective_chat.ban_member(u.id); bump(cid,u.id,"bans","ban_after_3_warnings")
            text=f"⚠️ اخطار {tag(u)}: {n}/3\n🚫 به‌دلیل رسیدن به ۳ اخطار، بن شد."
        except Exception: text=f"⚠️ اخطار {tag(u)}: {n}/3\n❌ بن خودکار انجام نشد."
    else: text=f"⚠️ اخطار {tag(u)}: {n}/3"
    await update.effective_message.reply_text(text,parse_mode="HTML")


async def delete_msg(update, context):
    if not await need_admin(update): return
    try:
        if update.effective_message.reply_to_message: await update.effective_message.reply_to_message.delete()
        await update.effective_message.delete()
    except Exception: pass


async def purge(update, context):
    if not await need_admin(update): return
    m=re.search(r"(\d+)",update.effective_message.text or ""); n=int(m.group(1)) if m else 10
    n=max(1,min(n,100)); last=update.effective_message.message_id
    for mid in range(last-n+1,last+1):
        try: await update.effective_chat.delete_message(mid)
        except Exception: pass


async def pin(update, context):
    if not await need_admin(update): return
    msg=update.effective_message.reply_to_message
    if not msg: return await update.effective_message.reply_text("روی پیام Reply کن و «پین کردن پیام» بفرست.")
    try: await msg.pin(); await update.effective_message.reply_text("📌 پیام پین شد.")
    except Exception as e: await update.effective_message.reply_text(f"❌ پین نشد: {e}")


async def unpin(update, context):
    if not await need_admin(update): return
    try: await update.effective_chat.unpin_all_messages(); await update.effective_message.reply_text("📍 همه پین‌ها برداشته شدند.")
    except Exception as e: await update.effective_message.reply_text(f"❌ آن‌پین نشد: {e}")


async def rules(update, context):
    cid=update.effective_chat.id
    with lock: row=db.execute("SELECT rules FROM settings WHERE chat_id=?",(cid,)).fetchone()
    await update.effective_message.reply_text("📜 قوانین AFTERHOURS\n\n"+(row[0] if row else "هنوز قوانینی ثبت نشده است."))


async def set_rules(update, context):
    if not await need_admin(update): return
    text=re.sub(r"^تعیین قوانین گروه\s*","",update.effective_message.text or "").strip()
    if not text: return await update.effective_message.reply_text("بعد از دستور، متن قوانین را بنویس.")
    with lock:
        db.execute("INSERT INTO settings(chat_id,rules) VALUES(?,?) ON CONFLICT(chat_id) DO UPDATE SET rules=excluded.rules",(update.effective_chat.id,text)); db.commit()
    await update.effective_message.reply_text("✅ قوانین ذخیره شد.")


LOCKS={"قفل عکس":"photo","قفل ویدیو":"video","قفل فایل":"document","قفل استیکر":"sticker","قفل گیف":"animation","قفل رسانه":"media"}

async def set_lock(update, context):
    if not await need_admin(update): return
    text=(update.effective_message.text or "").strip(); kind=next((v for k,v in LOCKS.items() if text.startswith(k)),None)
    if not kind: return
    with lock: db.execute("INSERT OR IGNORE INTO locks VALUES(?,?)",(update.effective_chat.id,kind)); db.commit()
    await update.effective_message.reply_text(f"🔒 {text} فعال شد.")


async def unlock(update, context):
    if not await need_admin(update): return
    with lock: db.execute("DELETE FROM locks WHERE chat_id=?",(update.effective_chat.id,)); db.commit()
    await update.effective_message.reply_text("🔓 قفل‌های رسانه‌ای باز شد.")


async def enforce_lock(update, context):
    msg=update.effective_message
    if not msg or not update.effective_user or await admin(update): return
    kind="photo" if msg.photo else "video" if msg.video else "document" if msg.document else "sticker" if msg.sticker else "animation" if msg.animation else None
    if not kind: return
    with lock: ls={r[0] for r in db.execute("SELECT kind FROM locks WHERE chat_id=?",(update.effective_chat.id,)).fetchall()}
    if kind in ls or "media" in ls:
        try: await msg.delete()
        except Exception: pass


async def stats(update, context, period="all"):
    cid=update.effective_chat.id; start=None
    if period=="today": start=utcnow().replace(hour=0,minute=0,second=0,microsecond=0)
    elif period=="week": start=utcnow()-timedelta(days=7)
    elif period=="month": start=utcnow()-timedelta(days=30)
    with lock:
        if start:
            total=db.execute("SELECT COUNT(*) FROM events WHERE chat_id=? AND kind='message' AND created_at>=?",(cid,start.isoformat())).fetchone()[0]
            rows=db.execute("""SELECT u.user_id,u.username,u.first_name,COUNT(e.rowid) n FROM users u
              LEFT JOIN events e ON e.chat_id=u.chat_id AND e.user_id=u.user_id AND e.kind='message' AND e.created_at>=?
              WHERE u.chat_id=? GROUP BY u.user_id ORDER BY n DESC LIMIT 10""",(start.isoformat(),cid)).fetchall()
        else:
            total=db.execute("SELECT COALESCE(SUM(messages),0) FROM users WHERE chat_id=?",(cid,)).fetchone()[0]
            rows=db.execute("SELECT user_id,username,first_name,messages n FROM users WHERE chat_id=? ORDER BY messages DESC LIMIT 10",(cid,)).fetchall()
        active=db.execute("SELECT COUNT(DISTINCT user_id) FROM events WHERE chat_id=? AND kind='message'"+(" AND created_at>=?" if start else ""),(cid,start.isoformat()) if start else (cid,)).fetchone()[0]
    label={"all":"کل دوره","today":"امروز","week":"۷ روز اخیر","month":"۳۰ روز اخیر"}[period]
    out=["📊 آمار AFTERHOURS",f"📅 {label}",f"👥 اعضای فعال: {active}",f"💬 پیام‌ها: {total}","","🏆 رتبه‌بندی:"]
    for i,r in enumerate(rows,1):
        uid,un,fn,n=r; name="@"+un if un else (fn or str(uid)); medal=["🥇","🥈","🥉"][i-1] if i<=3 else f"{i}."; out.append(f"{medal} {name} — {n} پیام")
    if not rows: out.append("هنوز آماری ثبت نشده.")
    await update.effective_message.reply_text("\n".join(out))


async def my_stats(update, context):
    cid=update.effective_chat.id; u=update.effective_user; remember(cid,u)
    with lock: r=db.execute("SELECT messages,warnings,mutes,bans,kicks FROM users WHERE chat_id=? AND user_id=?",(cid,u.id)).fetchone()
    m,w,mu,b,k=r or (0,0,0,0,0)
    await update.effective_message.reply_text(f"👤 آمار {u.first_name}\n\n💬 پیام: {m}\n⚠️ اخطار: {w}\n🔇 سکوت: {mu}\n🚫 بن: {b}\n👢 اخراج: {k}")


async def tag_members(update, context):
    if not await need_admin(update): return
    cid=update.effective_chat.id
    with lock: rows=db.execute("SELECT user_id,username,first_name FROM users WHERE chat_id=? ORDER BY last_seen DESC",(cid,)).fetchall()
    if not rows: return await update.effective_message.reply_text("👥 هنوز کاربری برای تگ کردن شناخته نشده؛ اعضا باید حداقل یک پیام بفرستند.")
    names=[f'<a href="tg://user?id={uid}">{(un if un else (fn or "کاربر"))}</a>' for uid,un,fn in rows]
    await update.effective_message.reply_text("👥 اعضای شناخته‌شده:\n\n"+" ".join(names),parse_mode="HTML",disable_web_page_preview=True)


async def router(update, context):
    msg=update.effective_message
    if not msg or not update.effective_chat or not update.effective_user or update.effective_chat.type not in ("group","supergroup"): return
    if update.effective_user.is_bot: return
    track(update.effective_chat.id,update.effective_user)
    text=(msg.text or msg.caption or "").strip()
    if text.startswith("سکوت زمان‌دار") or text.startswith("سکوت زمان دار"): return await timed_mute(update,context)
    if text.startswith("تعیین قوانین گروه"): return await set_rules(update,context)
    if text.startswith("پاک کردن چند پیام"): return await purge(update,context)
    if text in LOCKS: return await set_lock(update,context)
    commands={
      "بن":ban,"رفع بن":unban,"اخراج":kick,"سکوت":lambda u,c:mute(u,c),"رفع سکوت":unmute,
      "اخطار":warn,"حذف پیام":delete_msg,"پین کردن پیام":pin,"آن‌پین کردن پیام":unpin,"آن-پین کردن پیام":unpin,
      "آمار":lambda u,c:stats(u,c,"all"),"آمار امروز":lambda u,c:stats(u,c,"today"),"آمار هفته":lambda u,c:stats(u,c,"week"),
      "آمار ماه":lambda u,c:stats(u,c,"month"),"آمار من":my_stats,"فعال‌ترین‌ها":lambda u,c:stats(u,c,"week"),
      "فعال ترین ها":lambda u,c:stats(u,c,"week"),"تگ اعضا":tag_members,"قوانین":rules,"باز کردن گروه":unlock}
    if text in commands: return await commands[text](update,context)
    await enforce_lock(update,context)


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type","text/plain"); self.end_headers(); self.wfile.write(b"AFTERHOURS Manager is running")
    def log_message(self,*args): pass


def health_server():
    HTTPServer(("0.0.0.0",PORT),Health).serve_forever()


def main():
    threading.Thread(target=health_server,daemon=True).start()
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND,router))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__=="__main__": main()
