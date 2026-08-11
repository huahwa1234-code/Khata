"""
Smart Client & Kheti Tracker Bot (PDF Support)
----------------------------------------------
"""

import os
import re
import json
import logging
import threading
import asyncio
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import gspread
from google.oauth2.service_account import Credentials
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
        self.wfile.write(b"Tracker Bot with PDF is Live!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

# ---------------------------------------------------------------------------
# Config & Setup
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PUT_YOUR_TELEGRAM_BOT_TOKEN_HERE")
SHEET_NAME = "Smart_Tracker_DB"

# Render env variable jisme service account ka poora JSON content paste kiya gaya hai.
# Naam bilkul "service_account.json" hi rakha gaya hai (Render dashboard mein jo daala hai).
CREDENTIALS_ENV_VAR = "service_account.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("smart-tracker")

# State Management (ये याद रखेगा कि आप किस मुवक्किल का काम कर रहे हैं)
USER_STATE = {}

def get_sheets_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    raw_creds = os.environ.get(CREDENTIALS_ENV_VAR)
    if not raw_creds:
        raise RuntimeError(
            f"Environment variable '{CREDENTIALS_ENV_VAR}' नहीं मिला। "
            "Render dashboard → Environment में यह variable चेक करें।"
        )

    try:
        creds_info = json.loads(raw_creds)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"'{CREDENTIALS_ENV_VAR}' में valid JSON नहीं है। "
            "Render में पूरी service_account.json फाइल का content copy-paste किया गया है या नहीं, चेक करें. "
            f"Detail: {e}"
        )

    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(creds)

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
        "1️⃣ *सबसे पहले डेटाबेस बनाएं (सिर्फ एक बार):*\n"
        "`/setup apni.email@gmail.com`\n\n"
        "2️⃣ *नया खाता/मुवक्किल शुरू करें:*\n"
        "`/new Ramesh`\n\n"
        "3️⃣ *खर्च या फीस दर्ज करें (यह रमेश के खाते में जाएगा):*\n"
        "`/khet Tractor 1500`\n"
        "`/bainama Registry Fee 3500`\n\n"
        "4️⃣ *सबके नाम देखें और PDF निकालें:*\n"
        "`/request`"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def setup_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("⚠️ अपनी ईमेल ID लिखें: `/setup ankur@gmail.com`", parse_mode=ParseMode.MARKDOWN)
        return
    
    user_email = context.args[0]
    status_msg = await update.message.reply_text("⏳ डेटाबेस बनाया जा रहा है...")
    
    try:
        client = get_sheets_client()
        spreadsheet = client.create(SHEET_NAME)
        spreadsheet.share(user_email, perm_type='user', role='writer')
        
        # We use a single tab for all data to easily filter by name
        sheet1 = spreadsheet.sheet1
        sheet1.update_title("All_Data")
        sheet1.append_row(["Date", "Type", "Name", "Description", "Amount"])
        
        await status_msg.edit_text(f"✅ *डेटाबेस तैयार है!*\n🔗 [यहाँ देखें]({spreadsheet.url})", parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    except Exception as e:
        await status_msg.edit_text(f"❌ गड़बड़ हुई: {e}")

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
        f"*(कृपया नाम और काम Hinglish में लिखें ताकि PDF सही बने)*",
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

    status_msg = await update.message.reply_text("⏳ सेव हो रहा है...")
    try:
        client = get_sheets_client()
        sheet = client.open(SHEET_NAME).worksheet("All_Data")
        today = datetime.now().strftime("%d-%m-%Y %I:%M %p")
        
        sheet.append_row([today, entry_type, active_name, desc, amount])
        
        await status_msg.edit_text(
            f"✅ *दर्ज हो गया!*\n"
            f"👤 खाता: `{active_name}`\n"
            f"📌 प्रकार: {entry_type}\n"
            f"📝 {desc} - 💰 Rs {amount:,.2f}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ गड़बड़ हुई: {e}")

async def khet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_entry(update, context, "Kheti")

async def bainama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_entry(update, context, "Bainama")

# --- PDF Generation Workflow ---

async def request_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status_msg = await update.message.reply_text("🔎 नाम ढूँढे जा रहे हैं...")
    
    try:
        client = get_sheets_client()
        sheet = client.open(SHEET_NAME).worksheet("All_Data")
        records = sheet.get_all_values()[1:]
        
        # Extract unique names
        names = list(set([r[2] for r in records if len(r) > 2]))
        
        if not names:
            await status_msg.edit_text("अभी तक कोई खाता नहीं बना है।")
            return

        keyboard = []
        for name in names:
            # Callback data limit is 64 bytes
            keyboard.append([InlineKeyboardButton(name, callback_data=f"pdf_{name[:40]}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_msg.edit_text("📂 *किसका PDF चाहिए? नीचे नाम पर क्लिक करें:*", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        await status_msg.edit_text(f"❌ डेटा लोड करने में समस्या: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    clicked_name = query.data.replace("pdf_", "")
    await query.message.edit_text(f"⏳ `{clicked_name}` का PDF तैयार किया जा रहा है...", parse_mode=ParseMode.MARKDOWN)
    
    try:
        client = get_sheets_client()
        sheet = client.open(SHEET_NAME).worksheet("All_Data")
        records = sheet.get_all_values()[1:]
        
        # Filter records for this name (checking prefix because we sliced to 40 chars)
        user_records = [r for r in records if len(r) > 4 and r[2].startswith(clicked_name)]
        
        # Generate PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", style="B", size=16)
        pdf.cell(190, 10, txt=f"Account Report: {clicked_name}", ln=True, align="C")
        pdf.ln(5)
        
        pdf.set_font("Helvetica", size=10)
        total_khet = 0
        total_bainama = 0
        
        for r in user_records:
            date, entry_type, name, desc, amt = r[0], r[1], r[2], r[3], r[4]
            # Replace unsupported characters with standard ones (basic sanitization for FPDF)
            clean_desc = desc.encode('ascii', 'ignore').decode('ascii') 
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
        pdf.cell(190, 10, txt=f"Total Bainama Income: Rs {total_bainama}", ln=True)
        
        # Save temp file
        filename = "temp_report.pdf"
        pdf.output(filename)
        
        # Send Document
        with open(filename, 'rb') as f:
            await query.message.reply_document(document=f, filename=f"{clicked_name}_Report.pdf")
            
        os.remove(filename) # Clean up
        await query.message.reply_text("✅ PDF सफलता पूर्वक भेज दिया गया है!")

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
    
    # Callback handler for inline buttons
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^pdf_"))

    logger.info("Smart Tracker Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
