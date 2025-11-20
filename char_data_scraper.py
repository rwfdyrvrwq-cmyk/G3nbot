import asyncio
import httpx
import json
import os
import re
from urllib.parse import parse_qs, unquote

HOST = os.environ.get("CHAR_DATA_HOST", "127.0.0.1")
PORT = int(os.environ.get("CHAR_DATA_PORT", "4568"))


def _extract(parsed_vars: dict, key: str, default: str = "N/A") -> str:
    """
    Helper to safely fetch a single FlashVars value.

    FlashVars are returned as lists and sometimes include placeholders like
    "none". Treat empty strings and placeholder values as missing so the bot
    can display a consistent "N/A" marker.
    """
    values = parsed_vars.get(key)
    if not values:
        return default

    value = values[0].strip()
    if not value:
        return default

    if value.lower() in {"none", "null"}:
        return default

    return value


async def get_char_data(char_name: str):
    """Fetches character data from the AQW character page."""
    try:
        url = "http://account.aq.com/CharPage"
        params = {"id": char_name}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36'
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers, follow_redirects=True)
            response.raise_for_status()

        html_content = response.text

        # The flashvars can be in a <param> tag or an <embed> tag.
        # Let's try to find it in either, using a regex for flexibility.
        match = re.search(r'flashvars="([^"]+)"', html_content, re.IGNORECASE)
        if not match:
            # Fallback for the <param name="FlashVars" ...> format
            match = re.search(r'<param name="FlashVars" value="([^"]+)"', html_content, re.IGNORECASE)

        if not match:
            if "is wandering in the Void" in html_content:
                return {"error": "Character is inactive or does not exist."}
            return {"error": "Could not find flashvars in the page. The page structure may have changed."}

        flash_vars_str = match.group(1)
        
        # The string is HTML-encoded (&amp;) and URL-encoded.
        decoded_vars = unquote(flash_vars_str.replace("&amp;", "&"))
        
        # The decoded string is like a query string, so we can parse it
        parsed_vars = parse_qs(decoded_vars)

        # Extracting specific data points
        # The values in parsed_vars are lists, so we take the first element
        data = {
            "name": _extract(parsed_vars, "strName", char_name),
            "level": _extract(parsed_vars, "intLevel"),
            "class": _extract(parsed_vars, "strClassName"),
            "helm": _extract(parsed_vars, "strHelmName"),
            "armor": _extract(parsed_vars, "strArmorName"),
            "cape": _extract(parsed_vars, "strCapeName"),
            "weapon": _extract(parsed_vars, "strWeaponName"),
            "pet": _extract(parsed_vars, "strPetName"),
            # Cosmetic slots surfaced to the Discord bot
            "co_armor": _extract(parsed_vars, "strCustArmorName"),
            "co_helm": _extract(parsed_vars, "strCustHelmName"),
            "co_cape": _extract(parsed_vars, "strCustCapeName"),
            "co_weapon": _extract(parsed_vars, "strCustWeaponName"),
            "co_pet": _extract(parsed_vars, "strCustPetName"),
        }
        return data

    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP error occurred: {e.response.status_code}"}
    except Exception as e:
        return {"error": f"An unexpected error occurred: {str(e)}"}

async def handle_client(reader, writer):
    """Handles incoming client connections."""
    data = await reader.read(1024)
    message = data.decode().strip()
    addr = writer.get_extra_info('peername')
    print(f"Received '{message}' from {addr}")

    if not message:
        writer.close()
        await writer.wait_closed()
        return

    char_data = await get_char_data(message)
    
    response_data = json.dumps(char_data)
    
    writer.write(response_data.encode())
    await writer.drain()

    print(f"Sent data for '{message}'")
    writer.close()
    await writer.wait_closed()

async def main():
    """Starts the TCP server."""
    server = await asyncio.start_server(
        handle_client, HOST, PORT)

    addr = server.sockets[0].getsockname()
    print(f'Serving on {addr}')

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Server stopped.")
