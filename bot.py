import os
import re
import json
from google import genai
from telegram.constants import ParseMode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from google.genai.errors import APIError

# Import our custom Dota API integration
from dota_api import dota_api

# Load environment variables from .env file
load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MINI_APP_URL = os.environ.get("MINI_APP_URL", "https://sergiuts1.github.io/Dotan/")

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """You are an elite Dota 2 coach specializing in pos 1 carry players in the Herald-Archon bracket (below 3k MMR).

Your job: give a clear, structured game plan before each match based on the draft.
Keep advice practical and direct - no complex micro, no jargon overload. Every tip must be actionable.

[STRATEGIC PRIORITIZATION LOGIC]

SCALING ANALYSIS: Compare the late-game potential of both carries.

IF the enemy carry scales significantly better (Hard Carry), prioritize "Tempo/Aggressive" items to win mid-game.

IF the user outscales the enemy, prioritize "Safe/Farming" items to ensure a late-game victory.

COUNTER-ITEMIZATION: Identify the enemy's primary defensive mechanic (High Armor, Evasion, Ghost Scepter, Force Staff, or high HP regen). Ensure the 4th/5th item slot explicitly counters this mechanic (e.g., MKB for evasion, Nullifier for saves).

DEBUFF MITIGATION: Check if the enemy team has "Root", "Silence", or "Heavy Slows". If yes, a Dispel item (Manta, BKB, Lotus) is mandatory in the core build.

THREAT IDENTIFICATION: Before generating, identify the "Game-Ending Threat" (the one skill or hero that prevents the user from doing their job). Build the '⚠️ TOP 3 MISTAKES' and 'Kill Order' specifically to neutralize this threat.

Respond with EXACTLY this structure:

🎯 DRAFT IDENTITY
One sentence describing your team win condition archetype.

⚔️ LANING PHASE
- Safe lane tip: can you trade/kill or should you farm passively?
- Biggest lane threat and how to play around them
- Starting items recommendation

🎒 YOUR ITEM BUILD
List 6 core items in order:
1. Item - why
2. Item - why
(cover early/mid/late)

📈 POWERSPIKE TIMING
At what minute / item does your team peak? What to do then?

💀 KILL ORDER AND WHY
First target, second target, third target - explain why each based on your draft.

🏆 WIN CONDITION
One sentence. The single thing your team must execute.

⚠️ TOP 3 MISTAKES TO AVOID
Specific to this matchup. Number them."""


def convert_gemini_markdown_to_html(text: str) -> str:
    """
    Converts a subset of Gemini's Markdown to Telegram's supported HTML format.
    - **bold** -> <b>bold</b>
    - Headers (#, ##, etc.) -> <b>Header</b>
    - Escapes essential HTML characters.
    """
    # Escape base HTML characters to prevent injection or formatting errors
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Convert Markdown Headers (e.g., #, ##) to bold
    text = re.sub(r"^\s*#+\s*(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Convert **bold** to <b>bold</b>
    # This is the most common format from Gemini.
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # Gemini sometimes uses * for lists. Telegram HTML doesn't have <ul>/<li>.
    # We can leave them as is, they look fine as plain text bullet points.

    return text


async def analyze_draft(update: Update, my_hero: str, allies: list, enemies: list):
    ally_str = ", ".join(allies) if allies else "unknown"
    enemy_str = ", ".join(enemies)
    
    thinking_msg = await update.message.reply_text(
        f"Analyzing draft... playing {my_hero} vs {len(enemies)} enemies.\nFetching live meta..."
    )
    
    # Fetch live meta items
    meta_items_str = await dota_api.get_meta_items(my_hero)
    
    # Construct user message
    user_message = (
        f"My hero (pos 1 carry): {my_hero}\n"
        f"My team: {ally_str}\n"
        f"Enemy team: {enemy_str}\n\n"
    )
    
    if meta_items_str:
        user_message += (
            f"[LIVE META DATA]\n"
            f"Current popular items for {my_hero} this patch: {meta_items_str}\n\n"
            f"Give me the full game plan. Prioritize the live meta items in your build if they make sense against this specific enemy draft."
        )
    else:
        user_message += "Give me the full game plan."

    try:
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=user_message,
            config=genai.types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
            )
        )
        
        advice = response.text
        
        try:
            # Convert Markdown to a safe subset of HTML for Telegram
            html_advice = convert_gemini_markdown_to_html(advice)
            
            # Send the message with HTML parsing
            await thinking_msg.edit_text(
                html_advice,
                parse_mode=ParseMode.HTML
            )
        except Exception as formatting_err:
            # If HTML formatting fails for any reason, fall back to plain text
            print(f"HTML formatting failed: {formatting_err}, sending as plain text.")
            await thinking_msg.edit_text(advice)

    except APIError as api_err:
        # Check if this is specifically a 429 Too Many Requests/Quota error
        if api_err.code == 429:
             try:
                 await thinking_msg.edit_text(
                     "⏳ I'm currently analyzing too many drafts! I've hit a temporary rate limit from Google.\n\n"
                     "Please wait about 1 minute and try your request again."
                 )
             except Exception:
                 pass
        else:
             # Handle other specific API errors gracefully
             try:
                 await thinking_msg.edit_text(f"API Error: {api_err.message}\n\nPlease try again later.")
             except Exception:
                 pass
    except Exception as e:
        try:
            await thinking_msg.edit_text(f"Something went wrong: {e}\n\nPlease try again.")
        except Exception:
            pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Changed from InlineKeyboardButton to KeyboardButton
    keyboard = [[KeyboardButton("Pick heroes", web_app=WebAppInfo(url=MINI_APP_URL))]]
    await update.message.reply_text(
        "Dota 2 Carry Coach\n\n"
        "Tap the button below to pick heroes visually, or type manually:\n"
        "Anti-Mage, CM, Magnus, ET, PA vs Axe, Lion, QOP, Sniper, Pudge\n\n"
        "Your hero must be first in the list.",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


async def pick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("Open hero picker", web_app=WebAppInfo(url=MINI_APP_URL))]]
    await update.message.reply_text("Tap below to open the hero picker:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))


async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = json.loads(update.message.web_app_data.data)
        await analyze_draft(update, data["my_hero"], data["allies"], data["enemies"])
    except Exception as e:
        await update.message.reply_text(f"Could not read draft data: {e}")


def parse_draft(text: str):
    parts = re.split(r"\s+vs\.?\s+", text.strip(), flags=re.IGNORECASE)
    if len(parts) != 2:
        return None, None
    allies = [h.strip() for h in parts[0].split(",") if h.strip()]
    enemies = [h.strip() for h in parts[1].split(",") if h.strip()]
    return (allies, enemies) if allies and enemies else (None, None)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allies, enemies = parse_draft(update.message.text.strip())
    if allies is None:
        keyboard = [[KeyboardButton("Pick heroes instead", web_app=WebAppInfo(url=MINI_APP_URL))]]
        await update.message.reply_text(
            "Could not parse that. Use format:\nAnti-Mage, CM, Magnus, ET, PA vs Axe, Lion, QOP, Sniper, Pudge\n\nOr use the hero picker:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        )
        return
    await analyze_draft(update, allies[0], allies[1:], enemies)


def main():
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN environment variable is missing.")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pick", pick_command))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Dota 2 Coach Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
