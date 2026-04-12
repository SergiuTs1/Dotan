# Dota 2 Carry Coach Bot

A Telegram bot that gives you a full game plan based on your draft — item build, kill order, win condition, and more.

## Setup (5 minutes)

### 1. Get your Telegram bot token
1. Open Telegram and message [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow the prompts
3. Copy the token it gives you

### 2. Get your Anthropic API key
1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an API key under **API Keys**

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Set environment variables
```bash
cp .env.example .env
# Edit .env with your keys
```

Then either:
```bash
# Option A: export manually
export TELEGRAM_TOKEN=your_token_here
export ANTHROPIC_API_KEY=your_key_here

# Option B: use python-dotenv (install it first)
pip install python-dotenv
# and add this to the top of bot.py:
# from dotenv import load_dotenv; load_dotenv()
```

### 5. Run the bot
```bash
python bot.py
```

## Usage

In Telegram, send your draft like this:

```
Anti-Mage, Crystal Maiden, Magnus, Elder Titan, PA vs Axe, Lion, Queen of Pain, Sniper, Pudge
```

- Your carry hero must be **first**
- Separate your team from enemies with **vs**
- Hero names can be partial (AM, CM, QOP, etc.)

## Commands

- `/start` — Introduction and usage
- `/help` — Quick format reminder

## Hosting (optional)

To keep the bot running 24/7, deploy to [Railway](https://railway.app) or [Fly.io](https://fly.io):

```bash
# Railway (simplest)
railway login
railway init
railway up
# Set env vars in the Railway dashboard
```

## Next features (Phase 2)
- [ ] OpenDota API integration for real meta data
- [ ] Per-role support (not just pos 1)
- [ ] Mid-game check-in command (/midgame)
- [ ] Match history tracking
