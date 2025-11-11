# AQ Account Verification Discord Bot

This repository contains a small Discord bot that can verify an AdventureQuest character's IGN and guild by fetching the character page at `https://account.aq.com/CharPage?id=<char_id>` and parsing the returned HTML.

Features
- Slash command group: `/verify start` and `/verify confirm`
  - `/verify start <char_id>`: generates a short verification code and instructs the user to place it on their public character page (for example in their bio/profile).
  - `/verify confirm <char_id>`: fetches the character page and checks for the presence of the previously-generated code. If found, the bot links the Discord user to the character and stores basic info (char id, parsed name, guild).
  - The bot still provides parsing debug info when needed (via the scraping functionality).

Quick start

1. Create and activate a virtual environment (recommended):

```bash
python3 -m venv venv
source venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a bot application on the Discord Developer Portal and copy the bot token.


4. Set the token in your environment and run the bot. The bot registers application commands on startup.

If you're testing and want instant command availability, set `GUILD_ID` to a test guild (server) id so the commands are registered to that guild and appear immediately:

```bash
export DISCORD_TOKEN="your_token_here"
export GUILD_ID="123456789012345678"
python bot.py
```

```bash
export DISCORD_TOKEN="your_token_here"
python bot.py
```

Usage examples

- Verify with only char id (no expected values):

```text
/verify 12345
```

- Verify with expected IGN and guild:

```text
/verify 12345 SomePlayer "Cool Guild"
```

Assumptions and notes
- The bot fetches the public character page at `https://account.aq.com/CharPage?id=<char_id>` and uses HTML parsing heuristics. The website HTML structure may change; parsing may need adjustments.
- This repository does not include the bot token or any privileged credentials. Keep your token secret.
- For real verification (proving ownership), a secure challenge-response should be used (for example asking the user to set a short verification code in their in-game profile or bio). This bot only compares the public page content to provided expectations.

Next steps (optional)
- Add automatic role assignment on successful verification (assign a Discord role to verified users).
- Add tests that mock the HTTP responses to validate parsing logic.

Contact
If you want changes to behavior or integrations (role assignment, logging, persistent storage), tell me what you need and I can add it.
