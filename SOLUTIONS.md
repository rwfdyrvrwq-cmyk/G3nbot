# Character Data Service Guide

This guide explains how the CharPage FlashVars microservice (`char_data_scraper.py`) works, how the Discord bot consumes it, and how to troubleshoot the most common `/char` issues.

## Architecture Overview

1. **char_data_scraper.py**
   - Fetches `https://www.aq.com/character.asp?id=<IGN>` with `httpx`
   - Extracts FlashVars via regex, normalises missing values, and exposes the results over a TCP socket (default `127.0.0.1:4568`)
2. **scanner_client.py**
   - Async helper used by `/char`
   - Connects to the scraper service, reads JSON, and hands it back to the bot
3. **bot.py**
   - Calls `get_char_data()` whenever `/char` is invoked
   - Builds embeds that include both equipped and cosmetic items

## Running the Scraper Service

```bash
# Optional: override defaults
export CHAR_DATA_HOST=127.0.0.1
export CHAR_DATA_PORT=4568

venv/bin/python char_data_scraper.py
```

Logs show when the server starts (“Serving on …”) and each IGN request.

### Supervisor Mode

`./start_all.sh` launches the scraper in the background and stores the PID in `/tmp/scraper.pid`. Use `tail -f scraper.log` for live output.

## Common Issues & Fixes

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `OSError: [Errno 48] ... address already in use` | Another scraper instance is listening on the same port | Stop the old process (`pkill -f char_data_scraper.py`) or set `CHAR_DATA_PORT` to a free port for both scraper and bot |
| `/char` says “service unavailable” | Bot can’t connect to the TCP service | Ensure the scraper is running and the host/port match the bot’s environment variables |
| Cosmetics always show `*None*` | Old scraper build without `strCust*` fields | Redeploy the current scraper that exposes `co_armor`, `co_helm`, `co_cape`, `co_weapon`, `co_pet` |
| Random blanks like `"none"` | FlashVars sometimes return placeholder strings | `_extract()` already normalises `none/null` to `N/A`; keep the helper up to date if new placeholders appear |

## Testing the Pipeline

1. **Direct call (no TCP)**
   ```bash
   venv/bin/python - <<'PY'
   import asyncio
   from char_data_scraper import get_char_data
   async def main():
       data = await get_char_data('Artix')
       print({k: data.get(k) for k in ('name','class','weapon','co_weapon')})
   asyncio.run(main())
   PY
   ```

2. **End-to-end via TCP**
   ```bash
   # Terminal 1
   CHAR_DATA_PORT=4658 venv/bin/python char_data_scraper.py

   # Terminal 2
   CHAR_DATA_PORT=4658 venv/bin/python - <<'PY'
   import asyncio, os
   from scanner_client import get_char_data
   async def main():
       data = await get_char_data('Artix', port=int(os.environ['CHAR_DATA_PORT']))
       print(data)
   asyncio.run(main())
   PY
   ```

## Extending the Data

- To expose more FlashVars, add them to `_extract()` in `char_data_scraper.py` and update the embed logic in `bot.py`.
- If AQW introduces new cosmetic slots, follow the existing naming convention (`strCustFooName` → `co_foo`).

## Deployment Tips

- Run the scraper and bot together via `start_all.sh` so restarts clean up both processes.
- When deploying to a remote host, keep the scraper bound to loopback and run the bot on the same machine to avoid opening extra firewall ports.
- For containers or PaaS deployments, run the scraper inside the same container image and expose it over localhost.

By keeping the focus on FlashVars data, the bot can reliably show both equipped and cosmetic items without relying on any rendering services.
