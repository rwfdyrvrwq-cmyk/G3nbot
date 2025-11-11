# AQW Discord Verification Bot

A Discord bot that verifies AdventureQuest Worlds (AQW) character ownership by comparing user-provided IGN and Guild information against the character's public CharPage at `https://account.aq.com/CharPage?id=<char_id>`.

## Features

### `/verify` Command
- Opens a verification modal for users to enter their character information
- User provides:
  - **IGN (In-Game Name)**: Character name (used as character ID)
  - **Guild**: Guild name (optional - leave blank if none)
- Bot fetches character data from AQW CharPage
- Compares user input against actual CharPage data
- On successful verification:
  - Creates a private admin-only channel
  - Shows verification results in an embed
  - Provides "Finish Verification" button
- "Finish Verification" button:
  - Changes user's Discord nickname to their IGN
  - Deletes the verification channel
  - Handles permission errors gracefully

### `/deployhelper` Command (Admin Only)
- Admin-only command for deployment assistance
- Shows an empty embed with a "Help?" button
- When clicked, displays a dropdown menu with options:
  - Daily 4 Man
  - Daily 7 man
  - Daily Temple Run
  - Weekly Ultras
  - Ultraspeaker
  - Grimchallenge
  - Other
- All interactions are ephemeral (visible only to the user who clicked)

## Technical Features
- **Async HTTP** with connection pooling for fast character lookups
- **Ephemeral responses** to prevent channel spam
- **Error handling** with user-friendly messages
- **Permission checks** for nickname changes
- **Admin-only channels** for verification records

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

Or use the helper script:

```bash
chmod +x run.sh
./run.sh
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

### Deployment Helper (Admin Only)

1. Admin runs `/deployhelper`
2. Empty embed appears with "Help?" button
3. Members can click "Help?" to see deployment options
4. Select an option from the dropdown menu

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
├── bot.py              # Main bot code with commands and views
├── scraper.py          # Async CharPage scraper
├── requirements.txt    # Python dependencies
├── run.sh             # Helper script to run the bot
├── .env               # Environment variables (not committed)
├── .env.example       # Template for .env
├── .gitignore         # Git ignore file
└── README.md          # This file
```

## Requirements

- Python 3.9+
- discord.py 2.6.4+
- aiohttp 3.10.11+
- beautifulsoup4 4.14.2+
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
