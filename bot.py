import os
import re
import json
from google import genai
from telegram.constants import ParseMode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

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


def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram's MarkdownV2 format, except for characters used for actual formatting (like * or _)"""
    # These are all the characters that need to be escaped in MarkdownV2
    escape_chars = r'_~`>#+-=|{}.!'
    # Escape them
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    # Also escape brackets/parentheses carefully (since they might be used in links, though unlikely here)
    text = text.replace('[', r'\[').replace(']', r'\]').replace('(', r'\(').replace(')', r'\)')
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
            model='gemini-2.5-flash',
            contents=user_message,
            config=genai.types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                # Enable Google Search to retrieve latest item abilities
                tools=[{'google_search': {}}],
            )
        )
        
        advice = response.text
        
        # Telegram Markdown V1 is deprecated and very strict. 
        # Using MARKDOWN can cause issues if Gemini returns symbols like `-`, `.`, etc in unexpected ways.
        # However, MarkdownV2 is very strict too, requiring escaping. 
        # Alternatively, we can use ParseMode.HTML or try to escape it properly, 
        # or simply don't pass parse_mode (plain text) if it fails.
        
        try:
            # We try using Markdown
            # In V1, asterisks are used for bold.
            advice_md = advice.replace('**', '*')
            await thinking_msg.edit_text(advice_md, parse_mode=ParseMode.MARKDOWN)
        except Exception as md_err:
            print(f"Markdown parsing failed: {md_err}, sending as plain text.")
            # If markdown parsing fails, fallback to sending the exact text without parse_mode
            await thinking_msg.edit_text(advice)

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