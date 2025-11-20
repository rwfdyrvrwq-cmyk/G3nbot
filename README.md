# AQW Discord Verification Bot

An always-on AdventureQuest Worlds server assistant focused on secure player verification, detailed CharPage lookups, and in-server ticketing utilities. The bot orchestrates the `/verify` workflow with guild-specific admin channels, renders `/char` embeds powered by a bundled FlashVars scraper microservice, and rounds out daily operations with AQW wiki lookups, shop data, and TempleShrine/Ultra deployment helpers with advanced replacement tracking and leaderboard integration. It is designed for multi-guild deployments, uses slash commands exclusively, and ships with a lightweight TCP scraper process.

## Features

### `/verify` - Character Verification
- Verifies character ownership by comparing user input with CharPage data
- User provides IGN (In-Game Name) and optional Guild
- Creates admin-only verification channel with results
- Automatically updates Discord nickname to IGN on approval
- Handles permission errors gracefully

### `/char` - Character Lookup
- Pulls the official CharPage via the bundled FlashVars scraper service
- Shows comprehensive character information:
  - Level, class, faction, guild
  - All equipped items (weapon, armor, helm, cape, pet, misc)
  - All cosmetic items with wiki links
- Gracefully reports scraper downtime inside the embed whenever the service is offline

### `/wiki` - Item Search
- Searches AQW Wiki (aqwwiki.wikidot.com)
- Shows detailed item information with images
- Direct wiki links for more details

### `/shop` - Shop Information
- Looks up shop locations and contents
- Shows available items and acquisition methods

### `/deployticket` - Deployment Ticket System (Admin Only)
- Creates interactive tickets for boss runs with helper tracking
- Supports multiple run types:
  - **UltraWeeklies**: 3-helper weekly boss runs
  - **UltraDailies 4-Man**: 3-helper daily runs
  - **UltraDailies 7-Man**: 6-helper daily runs
  - **TempleShrine Dailies/Spamming**: Temple run coordination
- Features:
  - Server selection dropdown (Safiria first)
  - Boss selection with point values
  - Helper signup with "I'll Help" button
  - Remove Helper function for mid-run departures
  - **Advanced Replacement Tracking**:
    - Tracks all helpers who leave mid-run
    - Asks which bosses they helped with
    - Identifies who replaced them
    - Prevents duplicate replacement assignments
    - Fair point distribution based on actual participation
  - Leaderboard integration with `/leaderboard`, `/myscore`, `/resetleaderboard`
- Displays friendly nicknames/usernames throughout the UI

## Technical Architecture

### Character Data Pipeline
- **char_data_scraper.py**  
  Async HTTP fetcher that extracts FlashVars from the official CharPage and serves the parsed data over a lightweight TCP server (default `127.0.0.1:4568`).
- **scanner_client.py**  
  Async TCP client used by `/char` to talk to the scraper service. It handles connection failures gracefully and surfaces friendly error messages to Discord users.
- **bot.py**  
  Calls `get_char_data()` whenever `/char` is invoked and builds embeds from the returned equipment/cosmetic information.

### Data Scraping
- **scraper.py**: Async CharPage parser (49 FlashVars parameters)
- **wiki_scraper.py**: AQW Wiki data extraction
- **shop_scraper.py**: Shop information lookup

### Bot Features
- Async HTTP with connection pooling
- Ephemeral responses to prevent spam
- Admin-only verification channels
- Automatic nickname management
- Comprehensive error handling

## Quick Start

### 1. Create a virtual environment (recommended)

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up Discord Bot

1. Create a bot application on the [Discord Developer Portal](https://discord.com/developers/applications)
2. Enable these bot permissions:
   - **Manage Nicknames** (required for nickname changes)
   - **Manage Channels** (required for creating verification channels)
   - **Send Messages**
   - **Use Slash Commands**
3. Copy your bot token

### 4. Configure environment variables

Create a `.env` file:

```bash
cp .env.example .env
```

Edit `.env` and add your token:

```bash
DISCORD_TOKEN="your_bot_token_here"
# Optional: for faster testing, register commands to a single guild
# GUILD_ID=123456789012345678
```

### 5. Run the bot

```bash
python bot.py
```

Or use the process manager helper:

```bash
chmod +x start_all.sh
./start_all.sh
```

`start_all.sh` stops any lingering processes, launches the scraper microservice, and then starts the bot. Override paths without editing the file:

```bash
LOG_DIR="$HOME/verificationbot/logs" ./start_all.sh
```

## Usage

### Verifying a Character

1. User runs `/verify`
2. Clicks "Start Verification" button
3. Enters their IGN and Guild in the modal
4. Bot compares against CharPage data
5. If successful, admin channel is created
6. Admin (or user) clicks "Finish Verification"
7. User's nickname changes to their IGN
8. Verification channel is deleted

### Creating Deployment Tickets (Admin Only)

1. Admin runs `/deployticket`
2. Select ticket type from dropdown (UltraWeeklies, UltraDailies, TempleShrine)
3. Select bosses and server
4. Ticket is created with "I'll Help" button
5. Helpers click to join, requester clicks "Finish Verification" when done
6. If helpers left mid-run, system asks about replacements and distributes points fairly

## Deployment

### Free Hosting Options

**Recommended: [Render.com](https://render.com)**
- Free tier with 750 hours/month
- Easy GitHub integration
- Auto-restarts on crashes
- Sleeps after 15 minutes of inactivity (wakes instantly on command)

**Other Options:**
- **Railway.app**: $5 free credit monthly (~20 days uptime)
- **Fly.io**: Free tier with 3 shared VMs, always-on
- **PythonAnywhere**: Always-on free tier for Python bots

### Deploy to Render

1. Push your code to GitHub
2. Sign up at [render.com](https://render.com)
3. Create new "Web Service"
4. Connect your GitHub repository
5. Configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
6. Add environment variable:
   - **Key**: `DISCORD_TOKEN`
   - **Value**: Your bot token
7. Deploy!

## Project Structure

```
verificationbot/
├── bot.py                   # Main bot with all commands
├── scraper.py              # Additional CharPage parsing helpers
├── char_data_scraper.py    # FlashVars scraper + TCP microservice
├── scanner_client.py       # Async TCP client used by /char
├── wiki_scraper.py         # Wiki search functionality
├── shop_scraper.py         # Shop information lookup
├── get_guild_id.py         # Guild lookup utility
├── requirements.txt        # Python dependencies
├── start_all.sh            # Supervisor for scraper + bot
├── .env / .env.example     # Environment variables (gitignored template)
├── QUICK_REFERENCE.md      # Ops quick reference
├── SOLUTIONS.md            # Character data service guide
└── README.md               # This file
```

## Requirements

- Python 3.9+
- discord.py 2.6.4+
- httpx 0.27.2+ (async HTTP client)
- aiohttp 3.10.11+ (HTTP sessions)
- beautifulsoup4 4.14.2+ (HTML parsing)
- python-dotenv 1.2.1+

## Security Notes

- ✅ `.env` file is protected by `.gitignore`
- ✅ Bot token is never committed to the repository
- ✅ Only environment variables are used for sensitive data
- ⚠️ Ensure your bot role is positioned correctly in Discord server for nickname changes
- ⚠️ Keep your bot token secret - regenerate if exposed

## Troubleshooting

### "Application did not respond"
- Bot may not be running or has crashed
- Check logs for errors
- Restart the bot

### Nickname change fails
1. Check bot has "Manage Nicknames" permission
2. Ensure bot's role is **above** the user's highest role in server settings
3. Bot cannot change server owner's nickname

### Commands not showing
- Commands sync automatically on bot startup
- Wait 1-2 minutes for Discord to update
- Try restarting the bot

## Health Checks

- **Syntax validation**: `PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m compileall bot.py scraper.py char_data_scraper.py ...`
  (use `/tmp/pycache` so no cache files are written into the repo).
- **Process status**: Inspect `/tmp/*.pid` files written by `start_all.sh` and `tail -f bot.log` / `scraper.log`.
- **Scraper availability**: `lsof -iTCP:4568` (or your custom port) should show the character data server while running.
- **Cleanup**: The `.gitignore` excludes logs, PID files, and other runtime artifacts so the working tree stays clean after tests.

## Future Enhancements

Potential features to add:
- Automatic role assignment on verification
- Persistent storage of verified users
- Verification logs and analytics
- Custom deployment helper content per option
- Re-verification system
- Verification expiry

## License

This project is provided as-is for AdventureQuest Worlds community use.

## Contact

For issues, suggestions, or contributions, please open an issue on GitHub.
