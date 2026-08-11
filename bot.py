"""
Smart Client & Kheti Tracker Bot (Apps Script + PDF Support)
------------------------------------------------------------
"""

import os
import re
import logging
import threading
import asyncio
import requests
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from fpdf import FPDF
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ---------------------------------------------------------------------------
# Render Dummy Server (Port Fix)
# ---------------------------------------------------------------------------
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"Tracker Bot with Apps Script is Live!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

# ---------------------------------------------------------------------------
# Config & Setup
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PUT_YOUR_TELEGRAM_BOT_TOKEN_HERE")

# Aapka diya hua URL aur secret token
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbx-bSpCSzTf_IYbPGSzxfEGbE4uvegWNZUxwL9eKpDaSFkfKQo0GfwPJoeFT_sQuLSW8w/exec"
SECRET_TOKEN = "apna_koi_bhi_secret_yahan_daalein_123"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("smart-tracker-apps-script")

# State Management (याद रखने के लिए कि किस मुवक्किल का काम चल रहा है)
USER_STATE = {}

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------
def call_google_script(payload: dict) -> dict:
    """Google Apps Script को डेटा भेजने और मँगाने का फंक्शन"""
    payload["token"] = SECRET_TOKEN
    
    # 403 Forbidden Fix: Google को लगेगा कि यह रिक्वेस्ट Google Chrome ब्राउज़र से आ रही है
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(APPS_SCRIPT_URL, json=payload, headers=headers, allow_redirects=True, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Apps Script Error: {e}")
        return {"ok": False, "error": str(e)}

def parse_entry(args: list[str]):
    if not args:
        return None, None
    text = " ".join(args).strip()
    match = re.search(r'(\d+(?:\.\d+)?)$', text)
    if not match:
        return None, None
    amount = float(match.group(1))
    description = text[:match.start()].strip()
    return description, amount

# ---------------------------------------------------------------------------
# Telegram Bot Handlers
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "🌾 *स्मार्ट खाता एवं PDF ट्रैकर* ⚖️\n\n"
        "1️⃣ *सबसे पहले डेटाबेस चेक करें:*\n"
        "`/setup`\n\n"
        "2️⃣ *नया खाता/मुवक्किल शुरू करें:*\n"
        "`/new Ramesh`\n\n"
        "3️⃣ *खर्च या फीस दर्ज करें:*\n"
        "`/khet Tractor 1500`\n"
        "`/bainama Registry Fee 3500`\n\n"
        "4️⃣ *सबके नाम देखें और PDF निकालें:*\n"
        "`/request`"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def setup_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status_msg = await update.message.reply_text("⏳ गूगल शीट से कनेक्ट किया जा रहा है...")
    
    res = call_google_script({"action": "setup"})
    if res.get("ok"):
        sheet_url = res.get("url", "आपकी Google Sheet")
        await status_msg.edit_text(f"✅ *कनेक्शन सफल! शीट तैयार है।*\n🔗 [यहाँ देखें]({sheet_url})", parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    else:
        await status_msg.edit_text(f"❌ गड़बड़ हुई: {res.get('error')}")

async def new_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("⚠️ खाता शुरू करने के लिए नाम लिखें। जैसे: `/new Ramesh`", parse_mode=ParseMode.MARKDOWN)
        return
    
    client_name = " ".join(context.args).strip()
    user_id = update.effective_user.id
    USER_STATE[user_id] = client_name
    
    await update.message.reply_text(
        f"✅ *नया खाता एक्टिव:* `{client_name}`\n"
        f"अब आप जो भी `/khet` या `/bainama` दर्ज करेंगे, वह {client_name} के नाम पर सेव होगा।\n"
        f"*(Hinglish में ही लिखें ताकि PDF सही बने)*",
        parse_mode=ParseMode.MARKDOWN
    )

async def add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE, entry_type: str) -> None:
    user_id = update.effective_user.id
    active_name = USER_STATE.get(user_id)
    
    if not active_name:
        await update.message.reply_text("⚠️ पहले `/new <नाम>` लिखकर खाता शुरू करें!")
        return

    desc, amount = parse_entry(context.args)
    if not desc or amount is None:
        await update.message.reply_text(f"⚠️ सही फॉर्मेट में लिखें: `/{entry_type.lower()} Diesel 1200`", parse_mode=ParseMode.MARKDOWN)
        return

    status_msg = await update.message.reply_text("⏳ शीट में सेव हो रहा है...")
    
    today = datetime.now().strftime("%d-%m-%Y %I:%M %p")
    payload = {
        "action": "append",
        "date": today,
        "type": entry_type,
        "name": active_name,
        "description": desc,
        "amount": amount
    }
    
    res = call_google_script(payload)
    
    if res.get("ok"):
        await status_msg.edit_text(
            f"✅ *दर्ज हो गया!*\n"
            f"👤 खाता: `{active_name}`\n"
            f"📌 प्रकार: {entry_type}\n"
            f"📝 {desc} - 💰 Rs {amount:,.2f}",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await status_msg.edit_text(f"❌ गड़बड़ हुई: {res.get('error')}")

async def khet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_entry(update, context, "Kheti")

async def bainama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_entry(update, context, "Bainama")

# --- PDF Generation Workflow ---

async def request_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status_msg = await update.message.reply_text("🔎 शीट से नाम मँगाए जा रहे हैं...")
    
    res = call_google_script({"action": "get_names"})
    if not res.get("ok"):
        await status_msg.edit_text(f"❌ नाम लोड करने में समस्या: {res.get('error')}")
        return

    names = res.get("names", [])
    if not names:
        await status_msg.edit_text("अभी तक कोई खाता नहीं बना है।")
        return

    keyboard = []
    for name in names:
        keyboard.append([InlineKeyboardButton(name, callback_data=f"pdf_{name[:40]}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await status_msg.edit_text("📂 *किसका PDF चाहिए? नीचे नाम पर क्लिक करें:*", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    clicked_name = query.data.replace("pdf_", "")
    await query.message.edit_text(f"⏳ `{clicked_name}` का डेटा निकाला जा रहा है...", parse_mode=ParseMode.MARKDOWN)
    
    res = call_google_script({"action": "get_records", "name": clicked_name})
    if not res.get("ok"):
        await query.message.edit_text(f"❌ डेटा लाने में समस्या: {res.get('error')}")
        return

    records = res.get("records", [])
    
    try:
        # Generate PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", style="B", size=16)
        pdf.cell(190, 10, txt=f"Account Report: {clicked_name}", ln=True, align="C")
        pdf.ln(5)
        
        pdf.set_font("Helvetica", size=10)
        total_khet = 0
        total_bainama = 0
        
        for r in records:
            date, entry_type, name, desc, amt = r["date"], r["type"], r["name"], r["description"], r["amount"]
            clean_desc = str(desc).encode('ascii', 'ignore').decode('ascii') 
            pdf.cell(190, 8, txt=f"[{date}] {entry_type} | {clean_desc} | Rs {amt}", ln=True)
            
            try:
                val = float(amt)
                if entry_type == "Kheti":
                    total_khet += val
                else:
                    total_bainama += val
            except:
                pass
                
        pdf.ln(5)
        pdf.set_font("Helvetica", style="B", size=12)
        pdf.cell(190, 10, txt=f"Total Kheti Expense: Rs {total_khet}", ln=True)
        pdf.cell(190, 10, txt=f"income: Rs {total_bainama}", ln=True)
        
        # Save temp file
        filename = "temp_report.pdf"
        pdf.output(filename)
        
        # Send Document
        with open(filename, 'rb') as f:
            await query.message.reply_document(document=f, filename=f"{clicked_name}_Report.pdf")
            
        os.remove(filename)
        await query.message.reply_text("✅ PDF सफलतापूर्वक भेज दिया गया है!")

    except Exception as e:
        logger.exception("PDF Error")
        await query.message.reply_text(f"❌ PDF बनाने में समस्या: {e}")

# ---------------------------------------------------------------------------
# Main Function
# ---------------------------------------------------------------------------
def main() -> None:
    if "PUT_YOUR" in TELEGRAM_BOT_TOKEN:
        raise SystemExit("कृपया TELEGRAM_BOT_TOKEN सेट करें।")

    threading.Thread(target=run_dummy_server, daemon=True).start()

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setup", setup_sheet))
    app.add_handler(CommandHandler("new", new_client))
    app.add_handler(CommandHandler("khet", khet))
    app.add_handler(CommandHandler("bainama", bainama))
    app.add_handler(CommandHandler("request", request_data))
    
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^pdf_"))

    logger.info("Smart Tracker Bot starting with Apps Script...")
    app.run_polling()

if __name__ == "__main__":
    main()


