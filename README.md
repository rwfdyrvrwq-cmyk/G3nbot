# AQW Discord Verification Bot

An always-on AdventureQuest Worlds server assistant focused on secure player verification with daily automated checks, detailed CharPage lookups, and in-server ticketing utilities. The bot orchestrates verification workflows with guild-specific admin channels, renders `/char` embeds powered by a bundled FlashVars scraper microservice, and rounds out daily operations with AQW wiki lookups, shop data, and TempleShrine/Ultra deployment helpers with advanced replacement tracking and leaderboard integration. It is designed for multi-guild deployments, uses slash commands exclusively, and ships with a lightweight TCP scraper process.

## Features

### Character Verification System
- **Automated Daily Verification**: Checks all verified users' IGN and Guild daily at 12:00 AM UTC
- **Role-Based Access**: Assigns "Verified" role upon approval
- **Smart Error Handling**: 3-strike system for network errors with progressive warnings
- **Re-verification Support**: Users can re-verify if their character information changes
- **Admin Controls**: `/verificationcheck` command to enable/disable/monitor checks
- **Audit Logging**: All verification events logged to #verification-logs channel

**Verification Flow:**
1. Admin deploys verification embed using `/deployverification`
2. User clicks "Start Verification" button
3. User enters IGN and Guild in modal
4. Bot compares input against CharPage data
5. Admin-only verification channel created with results
6. Admin clicks "Finish Verification" to approve
7. User receives "Verified" role and nickname updated to IGN
8. User data saved for daily automated checks

**Daily Verification Checks:**
- Fetches current character data from AQ.com CharPage
- Compares stored IGN and Guild (case-insensitive)
- Removes "Verified" role if data doesn't match
- Sends DM notifications to affected users
- Network error handling with 3-strike system:
  - Strike 1: Log to #verification-logs
  - Strike 2: Warning DM sent to user
  - Strike 3: Role removed, user must re-verify

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

### `/verificationcheck` - Verification System Management (Admin Only)
- **enable**: Enable daily verification checks
- **disable**: Disable daily verification checks
- **status**: View statistics (checks run, users removed, verified count)
- **runnow**: Manually trigger verification check immediately

## Technical Architecture

### Character Data Pipeline
- **char_data_scraper.py**
  Async HTTP fetcher that extracts FlashVars from the official CharPage and serves the parsed data over a lightweight TCP server (default `127.0.0.1:4568`).
- **scanner_client.py**
  Async TCP client used by `/char` to talk to the scraper service. It handles connection failures gracefully and surfaces friendly error messages to Discord users.
- **bot.py**
  Calls `get_char_data()` whenever `/char` is invoked and builds embeds from the returned equipment/cosmetic information.

### Verification Data Storage
- **verified_users.json**: Stores verified user data (IGN, Guild, timestamps, failed check count)
- **verification_config.json**: System configuration and statistics

### Data Scraping
- **scraper.py**: Async CharPage parser (49 FlashVars parameters)
- **wiki_scraper.py**: AQW Wiki data extraction
- **shop_scraper.py**: Shop information lookup

### Bot Features
- Async HTTP with connection pooling
- Ephemeral responses to prevent spam
- Admin-only verification channels
- Automatic nickname management
- Daily automated verification checks
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
   - **Manage Roles** (required for "Verified" role assignment)
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

### 5. Create "Verified" Role

Before deploying verification:
1. Go to Server Settings → Roles
2. Create a new role called "Verified" (exact name)
3. Position it appropriately in your role hierarchy
4. Assign desired permissions

### 6. Run the bot

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

### Setting Up Verification

1. Create "Verified" role in your Discord server
2. Admin runs `/deployverification #channel-name`
3. Verification embed posted to specified channel
4. If "Verified" role doesn't exist, admin receives a warning

### User Verification Flow

1. User clicks "Start Verification" button on embed
2. Enters IGN and Guild in modal
3. Bot compares against CharPage data
4. Admin-only verification channel created
5. Admin reviews and clicks "Finish Verification"
6. User gets "Verified" role and nickname updated
7. User data saved for daily automated checks

### Daily Verification Checks

The bot automatically checks all verified users daily at 12:00 AM UTC:
- Fetches current character data from AQ.com
- Compares stored IGN and Guild
- Removes role if data doesn't match
- Logs all events to #verification-logs channel
- Sends DM notifications to affected users

Admins can manage checks with `/verificationcheck`:
```
/verificationcheck enable   # Enable daily checks
/verificationcheck disable  # Disable daily checks
/verificationcheck status   # View statistics
/verificationcheck runnow   # Run check immediately
```

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
├── verified_users.json     # Verified user data (auto-generated)
├── verification_config.json # Verification system config (auto-generated)
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
- requests 2.32.5+ (HTTP requests)

## Security Notes

- ✅ `.env` file is protected by `.gitignore`
- ✅ Bot token is never committed to the repository
- ✅ Only environment variables are used for sensitive data
- ✅ Verification data stored locally in JSON files
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

### "Verified" role not assigned
1. Ensure "Verified" role exists in server
2. Check bot has "Manage Roles" permission
3. Ensure bot's role is **above** "Verified" role in server settings

### Commands not showing
- Commands sync automatically on bot startup
- Wait 1-2 minutes for Discord to update
- Try restarting the bot

### Daily verification checks not running
- Check bot logs for "Daily verification check task started"
- Use `/verificationcheck status` to verify checks are enabled
- Checks run at 12:00 AM UTC daily

## Health Checks

- **Syntax validation**: `PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m compileall bot.py scraper.py char_data_scraper.py ...`
  (use `/tmp/pycache` so no cache files are written into the repo).
- **Process status**: Inspect `/tmp/*.pid` files written by `start_all.sh` and `tail -f bot.log` / `scraper.log`.
- **Scraper availability**: `lsof -iTCP:4568` (or your custom port) should show the character data server while running.
- **Cleanup**: The `.gitignore` excludes logs, PID files, and other runtime artifacts so the working tree stays clean after tests.

## License

This project is provided as-is for AdventureQuest Worlds community use.

## Contact

For issues, suggestions, or contributions, please open an issue on GitHub.
