# Quick Reference Card

## 🚀 Starting the Stack

```bash
# Activate virtual environment
source venv/bin/activate

# One-off run
python bot.py

# Or supervise scraper + bot together
./start_all.sh
```

`start_all.sh` stops any lingering processes, launches `char_data_scraper.py`, then starts `bot.py`. Logs are written to `scraper.log` and `bot.log` (override with `LOG_DIR=/path ./start_all.sh`).

## 📁 Core Files

| File | Purpose |
|------|---------|
| `bot.py` | Discord application with slash commands |
| `char_data_scraper.py` | FlashVars scraper + TCP service (port 4568) |
| `scanner_client.py` | Async TCP client used by `/char` |
| `scraper.py` | Additional CharPage parsing helpers |
| `wiki_scraper.py` | AQW wiki queries |
| `shop_scraper.py` | Shop lookup utilities |
| `get_guild_id.py` | Guild ID helper |
| `start_all.sh` | Supervisor for scraper + bot |

## 🎮 Slash Commands

| Command | Description | Scope |
|---------|-------------|-------|
| `/verify` | User submits IGN/Guild and kicks off verification flow | Everyone |
| `/char <username>` | Look up level + equipped/cosmetic gear via CharPage | Everyone |
| `/wiki <query>` | Fetch detailed wiki info with embeds and buttons | Everyone |
| `/deployhelper` | Dropdown with deployment info | Admins |
| `/serverinfo` | Shows guild metadata/ID | Admins |

## 🔌 Character Data Service

- Default endpoint: `127.0.0.1:4568`
- Start manually: `CHAR_DATA_PORT=4568 venv/bin/python char_data_scraper.py`
- Health check: `python - <<'PY' ... from scanner_client import get_char_data ... PY`
- Change port/host for both scraper and bot by exporting `CHAR_DATA_HOST/PORT`

## 🔧 Common Ops

```bash
# Check if bot is running
ps aux | grep "python.*bot.py" | grep -v grep

# Tail logs
tail -f bot.log   # or scraper.log

# Kill runaway processes
pkill -f "python.*bot.py"
pkill -f "python.*char_data_scraper.py"
```

## ✅ Health Checks

- Syntax: `PYTHONPYCACHEPREFIX=/tmp/pycache python -m compileall bot.py char_data_scraper.py scanner_client.py`
- Command sync: watch `bot.log` for “Synced N commands”
- Scraper: `lsof -iTCP:4568` should show the Python server while running

## 📦 Dependencies

```txt
discord.py==2.6.4
requests==2.32.5
beautifulsoup4==4.14.2
python-dotenv==1.2.1
aiohttp==3.10.11
httpx==0.27.2
```

## 🧠 Tips

1. Keep the scraper service running for instant `/char` responses.
2. Watch `scraper.log` when AQW CharPage layout changes—parsers log helpful errors.
3. For faster slash command updates during testing, set `GUILD_ID` in `.env`.
4. Always grant the bot “Manage Nicknames” and position its role above members it needs to rename.
