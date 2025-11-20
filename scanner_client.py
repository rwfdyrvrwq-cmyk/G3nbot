#!/usr/bin/env python3
"""
Character data client for the scraper TCP service.
"""

import os
import json
import asyncio

HOST = os.environ.get("CHAR_DATA_HOST", "127.0.0.1")
PORT = int(os.environ.get("CHAR_DATA_PORT", "4568"))


class CharDataClient:
    """Async client wrapper around the character data TCP service."""

    def __init__(self, host: str = HOST, port: int = PORT, timeout: float = 15.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    async def get_char_data(self, char_name: str):
        return await get_char_data(char_name, host=self.host, port=self.port, timeout=self.timeout)

    async def __call__(self, char_name: str):
        """Allow instances to be called directly for backwards compatibility."""
        return await self.get_char_data(char_name)


async def get_char_data(char_name: str, host: str = HOST, port: int = PORT, timeout: float = 15.0):
    """Connects to the scanner service and retrieves character data."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout
        )
    except (asyncio.TimeoutError, OSError) as e:
        # Catches: ConnectionRefusedError, ConnectionResetError, socket.gaierror (DNS failures),
        # and other network-related OSErrors
        print(f"Error connecting to scanner service: {e}")
        return {"error": "The character data service is currently unavailable. Please try again later."}

    writer.write(char_name.encode())
    await writer.drain()

    try:
        # Read the response from the server
        response_data = await asyncio.wait_for(reader.read(), timeout=timeout)
        if not response_data:
            return {"error": "Received no data from the scanner service."}

        # Decode and parse the JSON data
        char_data = json.loads(response_data.decode())

    except (asyncio.TimeoutError, json.JSONDecodeError, OSError) as e:
        # Catches timeout, JSON errors, and network errors (connection drops during read)
        print(f"Error reading/parsing data from scanner: {e}")
        return {"error": "Failed to retrieve valid character data."}
    finally:
        writer.close()
        await writer.wait_closed()

    return char_data

