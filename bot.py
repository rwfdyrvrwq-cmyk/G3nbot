import os
import asyncio
import discord
from discord import app_commands, ui
from discord.ext import commands
from dotenv import load_dotenv
import aiohttp
from typing import Optional
from datetime import timedelta
import re
import random
from urllib.parse import quote_plus
import json
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
from discord.ext import tasks
from datetime import time, timezone, datetime
from typing import Literal

load_dotenv(override=True)

# Configure logging
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# File handler with rotation (10MB max, keep 5 backups)
file_handler = RotatingFileHandler('bot.log', maxBytes=10*1024*1024, backupCount=5)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

# Configure root logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

from scraper import get_character_info_async
from wiki_scraper import scrape_wiki_page
from shop_scraper import scrape_shop_items
from scanner_client import get_char_data

LEGEND_EMOJI = "<:legendlarge:1438729295571845201>"
AC_EMOJI = "<:aclarge:1438723955740639435>"

MAX_TIMEOUT_MINUTES = 40320  # Discord maximum timeout (28 days)

# Points file path
POINTS_FILE = Path(__file__).parent / "helper_points.json"
REQUESTER_FILE = Path(__file__).parent / "requester_stats.json"

# Verification system file paths
VERIFIED_USERS_FILE = Path(__file__).parent / "verified_users.json"
VERIFICATION_CONFIG_FILE = Path(__file__).parent / "verification_config.json"
SERVER_CONFIG_FILE = Path(__file__).parent / "server_config.json"

# Boss points mapping
BOSS_POINTS = {
    # UltraWeeklies bosses
    "UltraDarkon": 2,
    "UltraDrago": 2,
    "ChampionDrakath": 2,
    "UltraDage": 2,
    "UltraNulgath": 2,
    "UltraSpeaker": 4,
    "UltraGramiel": 5,
    # UltraDailies 4-Man bosses
    "UltraEzrajal": 2,
    "UltraWarden": 2,
    "UltraEngineer": 2,
    "UltraTyndarius": 2,
    # UltraDailies 7-Man bosses
    "AstralShrine": 2,
    "KathoolDepths": 2,
    "ApexAzalith": 2,
    "VoidFlibbi": 2,
    "VoidNightbane": 2,
    "VoidXyfrag": 2,
    "Deimos": 2,
    "Sevencircleswar": 2,
    "Frozenlair": 2,
    # TempleShrine sides (Dailies mode)
    "TempleShrine-Left": 1,
    "TempleShrine-Right": 1,
    "TempleShrine-Middle": 2,
    "TempleShrine-All": 4,  # All 3 sides = 1 + 1 + 2 = 4
    # TempleShrine spamming (per kill)
    "TempleShrine-Spamming": 1
}


def load_points():
    """Load points data from JSON file"""
    if POINTS_FILE.exists():
        with open(POINTS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_points(points_data):
    """Save points data to JSON file"""
    with open(POINTS_FILE, 'w') as f:
        json.dump(points_data, f, indent=2)


def load_requester_stats():
    """Load requester stats from JSON file"""
    if REQUESTER_FILE.exists():
        with open(REQUESTER_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_requester_stats(requester_data):
    """Save requester stats to JSON file"""
    with open(REQUESTER_FILE, 'w') as f:
        json.dump(requester_data, f, indent=2)


def track_ticket_created(user_id, ticket_type, guild_id):
    """Track when a user creates a ticket (per-server)"""
    all_requester_data = load_requester_stats()
    user_id_str = str(user_id)
    guild_id_str = str(guild_id)

    # Ensure guild exists in data structure
    if guild_id_str not in all_requester_data:
        all_requester_data[guild_id_str] = {"users": {}}

    requester_data = all_requester_data[guild_id_str]["users"]

    if user_id_str not in requester_data:
        requester_data[user_id_str] = {
            "tickets_created": 0,
            "ticket_types": {}
        }

    requester_data[user_id_str]["tickets_created"] += 1

    if "ticket_types" not in requester_data[user_id_str]:
        requester_data[user_id_str]["ticket_types"] = {}

    if ticket_type not in requester_data[user_id_str]["ticket_types"]:
        requester_data[user_id_str]["ticket_types"][ticket_type] = 0
    requester_data[user_id_str]["ticket_types"][ticket_type] += 1

    save_requester_stats(all_requester_data)
    return requester_data[user_id_str]["tickets_created"]


def add_points(user_id, points, bosses, guild_id):
    """Add points to a user and track boss completions (per-server)"""
    points_data = load_points()
    user_id_str = str(user_id)
    guild_id_str = str(guild_id)

    # Ensure guild exists in data structure
    if guild_id_str not in points_data:
        points_data[guild_id_str] = {"users": {}}

    guild_users = points_data[guild_id_str]["users"]

    if user_id_str not in guild_users:
        guild_users[user_id_str] = {
            "total_points": 0,
            "bosses": {},
            "tickets_completed": 0
        }

    # Handle old format (just a number)
    if isinstance(guild_users[user_id_str], (int, float)):
        guild_users[user_id_str] = {
            "total_points": guild_users[user_id_str],
            "bosses": {},
            "tickets_completed": 0
        }

    # Add points
    guild_users[user_id_str]["total_points"] += points

    # Track boss completions
    if "bosses" not in guild_users[user_id_str]:
        guild_users[user_id_str]["bosses"] = {}

    for boss in bosses:
        if boss not in guild_users[user_id_str]["bosses"]:
            guild_users[user_id_str]["bosses"][boss] = 0
        guild_users[user_id_str]["bosses"][boss] += 1

    # Increment tickets completed
    if "tickets_completed" not in guild_users[user_id_str]:
        guild_users[user_id_str]["tickets_completed"] = 0
    guild_users[user_id_str]["tickets_completed"] += 1

    save_points(points_data)
    return guild_users[user_id_str]["total_points"]


def track_ticket_join(user_id, guild_id):
    """Track when a user joins a ticket (per-server)"""
    points_data = load_points()
    user_id_str = str(user_id)
    guild_id_str = str(guild_id)

    # Ensure guild exists in data structure
    if guild_id_str not in points_data:
        points_data[guild_id_str] = {"users": {}}

    guild_users = points_data[guild_id_str]["users"]

    if user_id_str not in guild_users:
        guild_users[user_id_str] = {
            "total_points": 0,
            "bosses": {},
            "tickets_joined": 0,
            "tickets_completed": 0
        }

    # Handle old format
    if isinstance(guild_users[user_id_str], (int, float)):
        guild_users[user_id_str] = {
            "total_points": guild_users[user_id_str],
            "bosses": {},
            "tickets_joined": 0,
            "tickets_completed": 0
        }

    # Increment tickets joined
    if "tickets_joined" not in guild_users[user_id_str]:
        guild_users[user_id_str]["tickets_joined"] = 0
    guild_users[user_id_str]["tickets_joined"] += 1

    save_points(points_data)


# ==================== VERIFICATION SYSTEM HELPERS ====================

def load_verified_users():
    """Load verified users from JSON file"""
    try:
        if VERIFIED_USERS_FILE.exists():
            with open(VERIFIED_USERS_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Error loading verified users: {e}")
        return {}

def save_verified_users(data):
    """Save verified users to JSON file"""
    try:
        with open(VERIFIED_USERS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving verified users: {e}")

def add_verified_user(user_id, ign, guild, ccid=None, guild_id=None):
    """Add a verified user to storage (per-server)"""
    data = load_verified_users()
    user_id_str = str(user_id)
    guild_id_str = str(guild_id)

    # Ensure guild exists in data structure
    if guild_id_str not in data:
        data[guild_id_str] = {"users": {}}

    # Add or update user
    data[guild_id_str]["users"][user_id_str] = {
        "ign": ign,
        "guild": guild,
        "ccid": ccid,  # Character ID (unique identifier)
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "failed_checks": 0
    }

    save_verified_users(data)
    logger.info(f"Added verified user: {user_id_str} in guild {guild_id_str} (IGN: {ign}, Guild: {guild}, CCID: {ccid})")

def remove_verified_user(user_id, guild_id):
    """Remove a verified user from storage (per-server)"""
    data = load_verified_users()
    user_id_str = str(user_id)
    guild_id_str = str(guild_id)

    if guild_id_str in data and "users" in data[guild_id_str]:
        if user_id_str in data[guild_id_str]["users"]:
            del data[guild_id_str]["users"][user_id_str]
            save_verified_users(data)
            logger.info(f"Removed verified user: {user_id_str} from guild {guild_id_str}")
            return True
    return False

def get_verified_user(user_id, guild_id):
    """Get verified user data (per-server)"""
    data = load_verified_users()
    guild_id_str = str(guild_id)
    user_id_str = str(user_id)

    if guild_id_str in data and "users" in data[guild_id_str]:
        return data[guild_id_str]["users"].get(user_id_str)
    return None

def load_verification_config():
    """Load verification config from JSON file (per-server)"""
    try:
        if VERIFICATION_CONFIG_FILE.exists():
            with open(VERIFICATION_CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Error loading verification config: {e}")
        return {}

def save_verification_config(data):
    """Save verification config to JSON file (per-server)"""
    try:
        with open(VERIFICATION_CONFIG_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving verification config: {e}")

def get_guild_verification_config(guild_id):
    """Get verification config for a specific guild"""
    all_config = load_verification_config()
    guild_id_str = str(guild_id)

    if guild_id_str not in all_config:
        all_config[guild_id_str] = {
            "daily_check_enabled": True,
            "last_check_time": None,
            "total_checks_run": 0,
            "users_removed_total": 0
        }
    return all_config[guild_id_str]

def update_guild_verification_config(guild_id, updates):
    """Update verification config for a specific guild"""
    all_config = load_verification_config()
    guild_id_str = str(guild_id)

    if guild_id_str not in all_config:
        all_config[guild_id_str] = {
            "daily_check_enabled": True,
            "last_check_time": None,
            "total_checks_run": 0,
            "users_removed_total": 0
        }

    all_config[guild_id_str].update(updates)
    save_verification_config(all_config)

def is_daily_check_enabled_for_guild(guild_id):
    """Check if daily verification checks are enabled for a specific guild"""
    config = get_guild_verification_config(guild_id)
    return config.get("daily_check_enabled", True)

async def get_or_create_verification_logs_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Get or create the #verification-logs channel"""
    try:
        # Look for existing channel
        channel = discord.utils.get(guild.text_channels, name="verification-logs")
        if channel:
            return channel

        # Create the channel with admin/mod-only permissions
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        # Give admins and mods access
        for role in guild.roles:
            if role.permissions.administrator or role.permissions.manage_guild:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True)

        channel = await guild.create_text_channel(
            name="verification-logs",
            overwrites=overwrites,
            topic="Automated verification check logs - Admin/Mod only"
        )

        logger.info(f"Created verification-logs channel in {guild.name}")
        return channel
    except Exception as e:
        logger.error(f"Error creating verification-logs channel: {e}")
        return None

# ==================== SERVER CONFIG HELPERS ====================

def load_server_config():
    """Load server configuration from JSON file"""
    try:
        if SERVER_CONFIG_FILE.exists():
            with open(SERVER_CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Error loading server config: {e}")
        return {}

def save_server_config(data):
    """Save server configuration to JSON file"""
    try:
        with open(SERVER_CONFIG_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving server config: {e}")

def get_verified_role_name(guild_id: int) -> str:
    """Get the verified role name for a specific server"""
    config = load_server_config()
    guild_id_str = str(guild_id)
    return config.get(guild_id_str, {}).get("verified_role_name", "Verified")

def set_verified_role_name(guild_id: int, role_name: str):
    """Set the verified role name for a specific server"""
    config = load_server_config()
    guild_id_str = str(guild_id)
    if guild_id_str not in config:
        config[guild_id_str] = {}
    config[guild_id_str]["verified_role_name"] = role_name
    save_server_config(config)
    logger.info(f"Set verified role name for guild {guild_id} to: {role_name}")

# ==================== END SERVER CONFIG HELPERS ====================

# ==================== END VERIFICATION SYSTEM HELPERS ====================

async def run_verification_check(guild: discord.Guild) -> dict:
    """
    Run verification check on all verified users
    Returns dict with results: {checked, mismatches, errors, removed}
    """
    results = {
        "checked": 0,
        "mismatches": 0,
        "errors": 0,
        "removed": 0
    }

    # Load per-server data
    all_data = load_verified_users()
    guild_id_str = str(guild.id)

    # Get this guild's users
    guild_data = all_data.get(guild_id_str, {})
    verified_users = guild_data.get("users", {})

    # Get configured role name for this guild
    role_name = get_verified_role_name(guild.id)
    verified_role = discord.utils.get(guild.roles, name=role_name)

    if not verified_role:
        logger.warning(f"Verified role '{role_name}' not found in guild {guild.name} - skipping verification check")
        return results

    logs_channel = await get_or_create_verification_logs_channel(guild)

    # Track users to remove (can't modify dict during iteration)
    users_to_remove = []

    for user_id_str, user_data in verified_users.items():
        user_id = int(user_id_str)
        member = guild.get_member(user_id)

        # Skip if user left the server (keep data for when they return)
        if not member:
            continue

        # Skip if user doesn't have Verified role anymore (manually removed)
        if verified_role not in member.roles:
            continue

        results["checked"] += 1

        stored_ign = user_data.get("ign", "").strip().lower()
        stored_guild = user_data.get("guild")
        if stored_guild:
            stored_guild = stored_guild.strip().lower()

        failed_checks = user_data.get("failed_checks", 0)

        try:
            # Fetch current character data from AQ.com
            char_info = await get_character_info_async(stored_ign)

            if not char_info or "error" in char_info:
                # Network error - increment strike counter
                failed_checks += 1
                user_data["failed_checks"] = failed_checks
                user_data["last_checked"] = datetime.now(timezone.utc).isoformat()
                # Save updated user data
                all_data[guild_id_str]["users"][user_id_str] = user_data
                save_verified_users(all_data)
                results["errors"] += 1

                if failed_checks == 1:
                    # Strike 1: Just log it
                    if logs_channel:
                        await logs_channel.send(
                            f"⚠️ **Network Error (Strike 1/3)**\n"
                            f"User: {member.mention} ({member.name})\n"
                            f"IGN: `{user_data.get('ign')}`\n"
                            f"Error: Could not fetch character data\n"
                            f"Action: None - will retry tomorrow"
                        )
                    logger.warning(f"Network error checking {member.name} (Strike 1)")

                elif failed_checks == 2:
                    # Strike 2: Send warning DM
                    if logs_channel:
                        await logs_channel.send(
                            f"⚠️ **Network Error (Strike 2/3)**\n"
                            f"User: {member.mention} ({member.name})\n"
                            f"IGN: `{user_data.get('ign')}`\n"
                            f"Error: Could not fetch character data\n"
                            f"Action: Warning DM sent to user"
                        )
                    try:
                        await member.send(
                            f"⚠️ **Verification Check Warning**\n\n"
                            f"We've been unable to verify your character information for 2 consecutive days due to network errors.\n"
                            f"IGN: `{user_data.get('ign')}`\n\n"
                            f"If we cannot verify your information tomorrow, your 'Verified' role will be removed and you'll need to re-verify.\n\n"
                            f"This is likely a temporary issue with the AQ.com character page. No action is needed from you."
                        )
                    except:
                        pass
                    logger.warning(f"Network error checking {member.name} (Strike 2) - Warning sent")

                elif failed_checks >= 3:
                    # Strike 3: Remove role and delete from storage
                    try:
                        await member.remove_roles(verified_role)
                        users_to_remove.append(user_id_str)
                        results["removed"] += 1

                        if logs_channel:
                            await logs_channel.send(
                                f"❌ **Verification Removed (Strike 3/3)**\n"
                                f"User: {member.mention} ({member.name})\n"
                                f"IGN: `{user_data.get('ign')}`\n"
                                f"Reason: 3 consecutive network errors\n"
                                f"Action: Role removed, user must re-verify"
                            )

                        try:
                            await member.send(
                                f"❌ **Verification Removed**\n\n"
                                f"Your 'Verified' role has been removed because we were unable to verify your character information for 3 consecutive days.\n"
                                f"IGN: `{user_data.get('ign')}`\n\n"
                                f"This was likely due to temporary network issues. You can re-verify using the verification embed in the server."
                            )
                        except:
                            pass
                        logger.info(f"Removed {member.name} after 3 network errors")
                    except Exception as e:
                        logger.error(f"Error removing role from {member.name}: {e}")

                continue  # Skip to next user

            # Successfully fetched data - check for mismatches
            current_ign = char_info.get("name", "").strip().lower()
            current_guild = char_info.get("guild")
            if current_guild:
                current_guild = current_guild.strip().lower()
            current_ccid = char_info.get("ccid")

            # Reset failed checks on successful fetch
            user_data["failed_checks"] = 0
            user_data["last_checked"] = datetime.now(timezone.utc).isoformat()

            # Store ccid if we don't have it yet (graceful migration)
            stored_ccid = user_data.get("ccid")
            if current_ccid and not stored_ccid:
                user_data["ccid"] = current_ccid
                stored_ccid = current_ccid

            # Save updated user data
            all_data[guild_id_str]["users"][user_id_str] = user_data
            save_verified_users(all_data)

            # Check if IGN, Guild, or CCID changed
            ign_matches = current_ign == stored_ign
            guild_matches = (current_guild == stored_guild) if stored_guild else True
            ccid_matches = (current_ccid == stored_ccid) if (current_ccid and stored_ccid) else True

            if not ign_matches or not guild_matches or not ccid_matches:
                # Mismatch found - remove role immediately
                results["mismatches"] += 1
                results["removed"] += 1

                mismatch_details = []
                if not ign_matches:
                    mismatch_details.append(f"IGN changed: `{user_data.get('ign')}` → `{char_info.get('name')}`")
                if not guild_matches:
                    mismatch_details.append(f"Guild changed: `{user_data.get('guild')}` → `{char_info.get('guild')}`")
                if not ccid_matches:
                    mismatch_details.append(f"Character ID changed: `{stored_ccid}` → `{current_ccid}` (Account ownership may have changed)")

                try:
                    await member.remove_roles(verified_role)
                    users_to_remove.append(user_id_str)

                    if logs_channel:
                        await logs_channel.send(
                            f"❌ **Verification Mismatch Detected**\n"
                            f"User: {member.mention} ({member.name})\n"
                            + "\n".join(mismatch_details) +
                            f"\nAction: Role removed, user must re-verify"
                        )

                    try:
                        await member.send(
                            f"❌ **Verification Status Changed**\n\n"
                            f"Your 'Verified' role has been removed because your character information has changed:\n"
                            + "\n".join(mismatch_details) +
                            f"\n\nIf you'd like to verify with your new information, please use the verification embed in the server."
                        )
                    except:
                        pass
                    logger.info(f"Removed {member.name} due to data mismatch")
                except Exception as e:
                    logger.error(f"Error removing role from {member.name}: {e}")

        except Exception as e:
            logger.error(f"Error checking user {user_id_str}: {e}")
            results["errors"] += 1

    # Remove users from storage
    for user_id_str in users_to_remove:
        remove_verified_user(user_id_str, guild.id)

    # Update config for this guild
    update_guild_verification_config(guild.id, {
        "last_check_time": datetime.now(timezone.utc).isoformat(),
        "total_checks_run": get_guild_verification_config(guild.id).get("total_checks_run", 0) + 1,
        "users_removed_total": get_guild_verification_config(guild.id).get("users_removed_total", 0) + results["removed"]
    })

    return results

@tasks.loop(time=time(hour=0, minute=0, tzinfo=timezone.utc))
async def daily_verification_check():
    """Daily task that runs at 12:00 AM UTC to check all verified users"""
    try:
        logger.info("Starting daily verification check...")

        # Run checks for all guilds the bot is in
        for guild in bot.guilds:
            try:
                # Check if daily checks are enabled for this specific guild
                if not is_daily_check_enabled_for_guild(guild.id):
                    logger.info(f"Daily verification check is disabled for {guild.name} - skipping")
                    continue

                results = await run_verification_check(guild)
                logger.info(
                    f"Verification check complete for {guild.name}: "
                    f"Checked {results['checked']}, "
                    f"Mismatches {results['mismatches']}, "
                    f"Errors {results['errors']}, "
                    f"Removed {results['removed']}"
                )

                # Send summary to logs channel
                logs_channel = await get_or_create_verification_logs_channel(guild)
                if logs_channel and results['checked'] > 0:
                    await logs_channel.send(
                        f"✅ **Daily Verification Check Complete**\n"
                        f"Users Checked: {results['checked']}\n"
                        f"Mismatches Found: {results['mismatches']}\n"
                        f"Network Errors: {results['errors']}\n"
                        f"Roles Removed: {results['removed']}"
                    )
            except Exception as e:
                logger.error(f"Error running verification check for {guild.name}: {e}")

        logger.info("Daily verification check completed for all guilds")
    except Exception as e:
        logger.error(f"Error in daily verification check task: {e}")

@daily_verification_check.before_loop
async def before_daily_verification_check():
    """Wait until the bot is ready before starting the task"""
    await bot.wait_until_ready()
    logger.info("Daily verification check task initialized")


def get_user_stats(user_id, guild_id):
    """Get user statistics (per-server)"""
    points_data = load_points()
    user_id_str = str(user_id)
    guild_id_str = str(guild_id)

    # Get guild data
    guild_data = points_data.get(guild_id_str, {})
    guild_users = guild_data.get("users", {})

    if user_id_str not in guild_users:
        return {
            "total_points": 0,
            "bosses": {},
            "total_kills": 0,
            "tickets_joined": 0,
            "tickets_completed": 0,
            "completion_rate": 0.0
        }

    user_data = guild_users[user_id_str]

    # Handle old format
    if isinstance(user_data, (int, float)):
        return {
            "total_points": user_data,
            "bosses": {},
            "total_kills": 0,
            "tickets_joined": 0,
            "tickets_completed": 0,
            "completion_rate": 0.0
        }

    bosses = user_data.get("bosses", {})
    total_kills = sum(bosses.values())
    tickets_joined = user_data.get("tickets_joined", 0)
    tickets_completed = user_data.get("tickets_completed", 0)

    # Calculate completion rate
    completion_rate = (tickets_completed / tickets_joined * 100) if tickets_joined > 0 else 0.0

    return {
        "total_points": user_data.get("total_points", 0),
        "bosses": bosses,
        "total_kills": total_kills,
        "tickets_joined": tickets_joined,
        "tickets_completed": tickets_completed,
        "completion_rate": completion_rate
    }


def format_helper_display_name(client, guild, user_id):
    """Return the best available display name for a helper."""
    member = guild.get_member(user_id) if guild else None
    if member:
        nickname = member.display_name or member.name
        username = member.name
        if nickname and username and nickname != username:
            return f"{nickname} (@{username})"
        return nickname or username or f"User {user_id}"

    # Fallback to global user cache
    user = client.get_user(user_id) if client else None
    if user:
        return user.global_name or user.name or f"User {user_id}"

    return f"User {user_id}"


intents = discord.Intents.default()
intents.members = True  # Enable members intent to fetch user nicknames/usernames
BOT_STATUS = os.getenv("BOT_STATUS", "Verifying AQW heroes")
BOT_STATUS_TYPE = os.getenv("BOT_STATUS_TYPE", "listening").lower()


# Custom bot class to cleanup resources on shutdown
class VerificationBot(commands.Bot):
    async def close(self):
        global http_session
        if http_session is not None:
            await http_session.close()
            http_session = None
            logger.info("✓ Closed aiohttp session")
        await super().close()


bot = VerificationBot(command_prefix="!", intents=intents)
http_session = None


class FinishVerificationView(ui.View):
    def __init__(self, channel: discord.TextChannel, user: discord.Member, ign: str, guild: str = "", ccid: int = None, has_mismatch: bool = False, guild_id: int = None):
        super().__init__()
        self.channel = channel
        self.user = user
        self.ign = ign
        self.guild = guild
        self.ccid = ccid
        self.guild_id = guild_id

        # Always add reject button for admin discretion
        self.add_item(RejectButton(channel, user, ign))
    
    @ui.button(label="Finish Verification", style=discord.ButtonStyle.success)
    async def finish_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Only administrators can complete verification.", ephemeral=True)
                return

            # Check if configured verified role exists
            role_name = get_verified_role_name(interaction.guild.id)
            verified_role = discord.utils.get(interaction.guild.roles, name=role_name)
            if not verified_role:
                await interaction.response.send_message(
                    f"⚠️ **'{role_name}' role not found!**\n\n"
                    f"Please create a '{role_name}' role in the server for the verification system to work properly.\n"
                    f"I cannot complete this verification without it.\n\n"
                    f"You can change the configured role name using `/setverifiedrole`.",
                    ephemeral=True
                )
                return

            nickname_changed = False
            role_assigned = False

            try:
                await self.user.edit(nick=self.ign)
                nickname_changed = True
            except discord.Forbidden:
                await interaction.response.send_message(
                    f"⚠️ **Verification complete!** However, I don't have permission to change your nickname.\n\n"
                    f"**Please ask a server admin to:**\n"
                    f"1. Give my role the **Manage Nicknames** permission\n"
                    f"2. Move my role **above** your highest role in the server settings\n\n"
                    f"You can manually change your nickname to: `{self.ign}`\n"
                    f"This channel will be deleted in 5 seconds.",
                    ephemeral=True
                )
                await asyncio.sleep(5)
            except:
                pass

            # Assign Verified role
            try:
                await self.user.add_roles(verified_role)
                role_assigned = True
            except Exception as role_error:
                logger.error(f"Failed to assign Verified role: {role_error}")

            if nickname_changed or role_assigned:
                # Save user to verified_users.json with the correct guild_id
                guild_id = self.guild_id if self.guild_id else interaction.guild.id
                add_verified_user(self.user.id, self.ign, self.guild if self.guild else None, self.ccid, guild_id)

                success_msg = f"✅ Verification complete!\n"
                if nickname_changed:
                    success_msg += f"• Nickname changed to `{self.ign}`\n"
                if role_assigned:
                    success_msg += f"• Verified role assigned\n"
                success_msg += f"• User data saved for daily verification checks"

                await interaction.response.send_message(success_msg, ephemeral=True)

                # Send log to verification-logs channel
                try:
                    logs_channel = await get_or_create_verification_logs_channel(interaction.guild)
                    if logs_channel:
                        log_embed = discord.Embed(
                            title="✅ Verification Approved",
                            color=discord.Color.green(),
                            timestamp=datetime.now(timezone.utc)
                        )
                        log_embed.add_field(name="Discord Username", value=self.user.name, inline=False)
                        log_embed.add_field(name="Discord ID", value=str(self.user.id), inline=False)
                        log_embed.add_field(name="AQW IGN", value=self.ign, inline=False)
                        log_embed.add_field(name="AQW Guild", value=self.guild if self.guild else "(None)", inline=False)
                        log_embed.add_field(name="AQW ID", value=str(self.ccid) if self.ccid else "(Not available)", inline=False)
                        log_embed.set_footer(text=f"Approved by {interaction.user.name}")
                        await logs_channel.send(embed=log_embed)
                except Exception as log_error:
                    logger.error(f"Failed to send verification log: {log_error}")

                try:
                    await self.user.send(
                        f"✅ **Verification Approved!**\n\n"
                        f"Your verification has been approved by an administrator.\n"
                        f"• Your nickname has been updated to `{self.ign}`\n"
                        f"• You now have the 'Verified' role\n\n"
                        f"Your verification status will be checked daily to ensure your character information remains accurate."
                    )
                except:
                    pass

                await asyncio.sleep(1)

            await self.channel.delete()
        except Exception as e:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)
            except:
                pass


class RejectButton(ui.Button):
    def __init__(self, channel: discord.TextChannel, user: discord.Member, ign: str):
        super().__init__(label="Reject Application", style=discord.ButtonStyle.danger)
        self.channel = channel
        self.user = user
        self.ign = ign

    async def callback(self, interaction: discord.Interaction):
        try:
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Only administrators can reject applications.", ephemeral=True)
                return

            await interaction.response.send_message("✅ Application rejected. Notifying user...", ephemeral=True)

            try:
                await self.user.send(
                    "❌ **Verification Rejected**\n\n"
                    "Your application has been rejected because the details you provided do not match with the records on your CharPage.\n\n"
                    "Please ensure:\n"
                    "• Your IGN (In-Game Name) is correct\n"
                    "• Your Guild name matches exactly (or is left blank if you have none)\n\n"
                    "You may submit a new verification request with the correct information."
                )
            except:
                await interaction.followup.send("⚠️ Could not send DM to user. They may have DMs disabled.", ephemeral=True)

            await asyncio.sleep(2)
            await self.channel.delete()
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)
            except:
                pass


class VerificationModal(ui.Modal, title="Character Verification"):
    ign = ui.TextInput(label="Character IGN (In-Game Name)", placeholder="Enter your character name (used as ID)", required=True, max_length=100)
    guild = ui.TextInput(label="Guild (leave blank if none)", placeholder="Enter your guild or leave empty", required=False, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)

            user_ign = self.ign.value.strip()
            user_guild = self.guild.value.strip() if self.guild.value else ""

            char_id = user_ign

            if http_session is None:
                await interaction.followup.send("❌ Bot is still starting up. Please try again in a moment.", ephemeral=True)
                return

            info = await get_character_info_async(char_id, http_session)

            page_name = info.get("name", "").strip() if info.get("name") else ""
            page_guild = info.get("guild", "").strip() if info.get("guild") else ""

            def normalize(s: str) -> str:
                return " ".join(s.lower().split()) if s else ""

            name_match = normalize(user_ign) == normalize(page_name) if page_name else False
            guild_match = normalize(user_guild) == normalize(page_guild) if page_guild or user_guild else (not page_guild and not user_guild)

            has_mismatch = not (name_match and guild_match)
            
            embed = discord.Embed(title="Verification Result", color=discord.Color.green() if (name_match and guild_match) else discord.Color.orange())
            embed.add_field(name="Character IGN (used as ID)", value=char_id, inline=False)
            embed.add_field(name="IGN Check", value=f"{'✅ MATCH' if name_match else '❌ MISMATCH'}\nYou entered: `{user_ign}`\nPage shows: `{page_name}`", inline=False)
            embed.add_field(name="Guild Check", value=f"{'✅ MATCH' if guild_match else '❌ MISMATCH'}\nYou entered: `{user_guild if user_guild else '(empty)'}`\nPage shows: `{page_guild if page_guild else '(none)'}`", inline=False)

            # Add Character ID if available
            char_ccid = info.get("ccid") if info else None
            if char_ccid:
                embed.add_field(name="Character ID (CCID)", value=f"`{char_ccid}`", inline=False)

            if name_match and guild_match:
                embed.add_field(name="Status", value="✅ **Verification Successful!**", inline=False)
            else:
                embed.add_field(name="Status", value="⚠️ **Verification Pending** - Mismatches detected. Admin review required.", inline=False)

            embed.add_field(name="User", value=f"{interaction.user.mention} ({interaction.user.name})", inline=False)

            # Check if this is a re-verification
            existing_data = get_verified_user(interaction.user.id, interaction.guild.id)
            if existing_data:
                reverif_msg = f"User was previously verified with:\nIGN: `{existing_data.get('ign')}`\nGuild: `{existing_data.get('guild') or '(none)'}`"
                if existing_data.get('ccid'):
                    reverif_msg += f"\nCCID: `{existing_data.get('ccid')}`"
                embed.add_field(
                    name="ℹ️ Re-verification",
                    value=reverif_msg,
                    inline=False
                )

            try:
                guild = interaction.guild
                if guild:
                    admin_overwrites = {}
                    if guild.owner:
                        admin_overwrites[guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                    
                    admin_role = discord.utils.find(lambda r: r.permissions.administrator, guild.roles)
                    if admin_role:
                        admin_overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                    
                    admin_overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)

                    # Slugify username to create a valid Discord channel name
                    # Remove all non-alphanumeric characters except hyphens, lowercase, and truncate to 95 chars
                    slugified_name = re.sub(r'[^a-z0-9-]', '', interaction.user.name.lower().replace(' ', '-'))
                    # Remove consecutive hyphens and strip leading/trailing hyphens
                    slugified_name = re.sub(r'-+', '-', slugified_name).strip('-')
                    # If the result is empty or too short, fall back to user ID
                    if len(slugified_name) < 2:
                        slugified_name = str(interaction.user.id)
                    # Truncate to 95 characters (Discord limit is 100, leaving room for "verification-")
                    channel_name = f"verification-{slugified_name[:95]}"

                    channel = await guild.create_text_channel(
                        channel_name,
                        overwrites=admin_overwrites,
                        topic=f"Verification record for {interaction.user.name} (IGN: {user_ign})"
                    )
                    # Extract ccid from character info
                    user_ccid = info.get("ccid") if info else None
                    finish_view = FinishVerificationView(channel, interaction.user, user_ign, user_guild, user_ccid, has_mismatch, guild_id=interaction.guild.id)
                    await channel.send(embed=embed, view=finish_view)

                    # Send charpage link outside the embed
                    encoded_ign = quote_plus(user_ign)
                    charpage_url = f"http://account.aq.com/CharPage?id={encoded_ign}"
                    await channel.send(f"**Character Page:** {charpage_url}")
                    
                    user_confirmation = discord.Embed(
                        title="⏳ Verification Submitted",
                        description="Please wait while the admins verify and approve your request.\n\nYou will be notified once an admin has reviewed your verification.",
                        color=discord.Color.blue()
                    )
                    await interaction.followup.send(embed=user_confirmation, ephemeral=True)
            except Exception as channel_err:
                error_embed = discord.Embed(
                    title="⚠️ Verification Result",
                    description="Verification matched but could not create admin channel. Please contact an admin.",
                    color=discord.Color.orange()
                )
                error_embed.add_field(name="Error", value=str(channel_err)[:200], inline=False)
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            
        except Exception as e:
            error_msg = f"❌ Verification failed: {str(e)}"
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(error_msg[:2000], ephemeral=True)
                else:
                    await interaction.followup.send(error_msg[:2000], ephemeral=True)
            except:
                pass


class VerifyButton(ui.View):
    def __init__(self):
        super().__init__()

    @ui.button(label="Start Verification", style=discord.ButtonStyle.primary)
    async def verify_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            modal = VerificationModal()
            await interaction.response.send_modal(modal)
        except Exception as e:
            error_msg = f"❌ Failed to open verification form: {str(e)}"
            try:
                await interaction.response.send_message(error_msg, ephemeral=True)
            except:
                pass


# Wiki command helper classes
class WikiDisambiguationSelect(discord.ui.Select):
    """Dropdown select menu for disambiguation pages"""

    def __init__(self, related_items):
        options = []
        for item in related_items[:25]:  # Discord allows up to 25 options
            options.append(
                discord.SelectOption(label=item['name'][:100],
                                     description="Click to view details"[:100],
                                     value=item['name']))

        super().__init__(placeholder="Choose an item to view details...",
                         min_values=1,
                         max_values=1,
                         options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        item_name = self.values[0]
        wiki_data = await scrape_wiki_page(item_name)

        if not wiki_data:
            await interaction.followup.send(
                f"❌ Could not fetch details for {item_name}", ephemeral=True)
            return

        # Fetch merge requirements if shop is present
        shop = wiki_data.get('shop')
        if shop:
            shop_name = shop.split(' - ')[0].strip() if ' - ' in shop else shop
            shop_data = await scrape_shop_items(shop_name)
            if shop_data and shop_data.get('items'):
                # Find this specific item in the shop to get merge requirements
                for item in shop_data['items']:
                    if wiki_data['title'] in item.get('name', ''):
                        wiki_data['merge_requirements'] = item.get('price')
                        break

        embed = await create_wiki_embed(wiki_data)

        # Add interactive buttons for quest if present
        view = ItemDetailsView(wiki_data) if wiki_data.get('quest') else None

        if view:
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed)


class WikiDisambiguationView(discord.ui.View):
    """View with dropdown for disambiguation pages"""

    def __init__(self, related_items):
        super().__init__(timeout=180)
        self.add_item(WikiDisambiguationSelect(related_items))


class ItemDetailsView(discord.ui.View):
    """View with buttons for quest details"""

    def __init__(self, wiki_data):
        super().__init__(timeout=180)

        # Add quest button if quest is present
        quest = wiki_data.get('quest')
        if quest:
            # Extract quest name (remove "reward from" or similar prefixes), preserving case
            quest_name = quest
            if 'reward from' in quest.lower():
                # Find position case-insensitively, then extract with original casing
                idx = quest.lower().find('reward from')
                if idx != -1:
                    quest_name = quest[idx + len('reward from'):].strip()
            elif 'quest:' in quest.lower():
                # Find position case-insensitively, then extract with original casing
                idx = quest.lower().find('quest:')
                if idx != -1:
                    quest_name = quest[idx + len('quest:'):].strip()

            quest_button = discord.ui.Button(
                label=f"📜 {quest_name[:35]}",
                style=discord.ButtonStyle.success,
                custom_id=f"quest_{quest_name[:50]}")
            quest_button.callback = self.create_quest_callback(quest_name)
            self.add_item(quest_button)

    def create_quest_callback(self, quest_name: str):

        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()

            quest_data = await scrape_wiki_page(quest_name)

            if not quest_data:
                await interaction.followup.send(
                    f"❌ Could not fetch details for {quest_name}",
                    ephemeral=True)
                return

            embed = discord.Embed(title=f"📜 {quest_data['title']}",
                                  url=quest_data['url'],
                                  color=discord.Color.gold())

            description = quest_data.get('description')
            if description:
                if len(description) > 400:
                    description = description[:397] + "..."
                embed.description = description

            location_info = quest_data.get('location')
            if location_info:
                embed.add_field(name="📍 Location",
                                value=location_info,
                                inline=False)

            requirements = quest_data.get('requirements', [])
            if requirements:
                req_text = '\n'.join([f"• {req}" for req in requirements[:5]])
                embed.add_field(name="❗ Requirements",
                                value=req_text,
                                inline=False)

            notes = quest_data.get('notes', [])
            if notes:
                notes_text = '\n'.join([
                    f"• {note[:150]}{'...' if len(note) > 150 else ''}"
                    for note in notes[:3]
                ])
                embed.add_field(name="📝 Notes", value=notes_text, inline=False)

            embed.set_footer(text="Source: AQW Wiki")

            await interaction.followup.send(embed=embed)

        return callback


def create_wiki_link(item_name: str) -> str:
    """
    Create a wiki link for an item name

    Args:
        item_name: The item name to link

    Returns:
        Markdown formatted link to AQW wiki, or plain text if URL can't be created
    """
    # Return plain text if item name is empty or invalid
    if not item_name or not item_name.strip():
        return item_name or "Unknown"

    # AQW Wiki URL format: lowercase with hyphens
    # Example: "Cultist Knife" → "cultist-knife"
    # Example: "King's Echo" → "king-s-echo" (apostrophes become hyphens)

    # Replace apostrophes with hyphens (possessive: "King's" → "King-s")
    slug = item_name.replace("'", "-")
    # Replace spaces with hyphens
    slug = slug.replace(' ', '-')
    # Remove any other special characters except hyphens and alphanumeric
    slug = re.sub(r'[^a-zA-Z0-9-]', '', slug)
    # Convert to lowercase
    slug = slug.lower()
    # Clean up multiple consecutive hyphens
    slug = re.sub(r'-+', '-', slug)
    # Remove leading/trailing hyphens
    slug = slug.strip('-')

    # If slug is empty after cleaning, return plain text
    if not slug:
        return item_name

    wiki_url = f"http://aqwwiki.wikidot.com/{slug}"
    return f"[{item_name}]({wiki_url})"


def format_item_value(value):
    """Format an item value as clickable link or plain text"""
    if isinstance(value, dict) and 'text' in value:
        # Generate proper wiki link from the full item text instead of using HTML URL
        # (HTML URLs are often incomplete, e.g., "King" instead of "King's Echo")
        return create_wiki_link(value['text'])
    elif isinstance(value, str):
        return value
    return str(value)


def _decorate_title(title: str, member_only: bool, ac_only: bool) -> str:
    """Prefix the embed title with membership/AC indicators."""
    badges = []
    if member_only:
        badges.append(LEGEND_EMOJI)
    if ac_only:
        badges.append(AC_EMOJI)
    if badges:
        return f"{' '.join(badges)} {title}"
    return title


def _format_access_summary(member_only: bool, ac_only: bool) -> str:
    """Return a short text summary describing access requirements."""
    labels = []
    if member_only:
        labels.append(f"{LEGEND_EMOJI} Member-only")
    if ac_only:
        labels.append(f"{AC_EMOJI} AC-only")
    if not labels:
        return "Public"
    return " • ".join(labels)


async def create_wiki_embed(wiki_data):
    """Create a Discord embed from wiki data"""
    title = wiki_data.get('title', 'Unknown')
    url = wiki_data.get('url', '')
    member_only = wiki_data.get('member_only', False)
    ac_only = wiki_data.get('ac_only', False)

    decorated_title = _decorate_title(title, member_only, ac_only)

    embed = discord.Embed(title=decorated_title,
                          url=url,
                          color=discord.Color.blue())

    description = wiki_data.get('description')
    if description:
        if len(description) > 400:
            description = description[:397] + "..."
        embed.description = description

    item_type = wiki_data.get('type')
    if item_type:
        embed.add_field(name="🏷️ Type", value=item_type, inline=True)

    level = wiki_data.get('level')
    if level:
        embed.add_field(name="⭐ Level Required", value=level, inline=True)

    rarity = wiki_data.get('rarity')
    if rarity:
        embed.add_field(name="💎 Rarity", value=rarity, inline=True)

    damage = wiki_data.get('damage')
    if damage:
        embed.add_field(name="⚔️ Damage/Stats", value=damage, inline=True)

    how_to_get = []

    # Show locations list if available (for misc items)
    locations_list = wiki_data.get('locations_list', [])
    if locations_list:
        location_links = [create_wiki_link(loc) for loc in locations_list[:10]]
        locations_display = ' • '.join(location_links)
        # Ensure locations don't exceed reasonable length
        if len(locations_display) > 900:
            locations_display = locations_display[:897] + "..."
        how_to_get.append(f"📍 **Locations:** {locations_display}")

    # Show merge text if available (for misc items)
    merge_text = wiki_data.get('merge_text')
    if merge_text:
        # Truncate merge text to prevent Discord embed limit (1024 chars per field)
        # Reserve space for other content in the field
        max_merge_length = 500
        if len(merge_text) > max_merge_length:
            merge_text = merge_text[:max_merge_length - 3] + "..."
        how_to_get.append(f"\n🔨 **Merge:** {merge_text}")

    shop = wiki_data.get('shop')
    if shop:
        shop_parts = shop.split(' - ')
        if len(shop_parts) > 1:
            shop_name = shop_parts[0].strip()
            location_name = shop_parts[1].strip()
            shop_name_link = create_wiki_link(shop_name)
            location_link = create_wiki_link(location_name)
            how_to_get.append(
                f"🏪 **Shop:** {shop_name_link} - {location_link}")
        else:
            shop_link = create_wiki_link(shop)
            how_to_get.append(f"🏪 **Shop:** {shop_link}")

    location = wiki_data.get('location')
    if location and location != shop and not locations_list:
        if len(location) > 150:
            location_display = location[:147] + "..."
        else:
            location_display = location

        location_parts = location_display.split(' - ')
        if len(location_parts) > 1:
            location_name = location_parts[-1].strip()
            location_link = create_wiki_link(location_name)
            location_prefix = ' - '.join(location_parts[:-1])
            location_display = f"{location_prefix} - {location_link}"
        else:
            location_display = create_wiki_link(location_display)

        how_to_get.append(f"\n📍 **Location:** {location_display}")

    quest = wiki_data.get('quest')
    if quest:
        # Extract quest name from ORIGINAL (non-truncated) string, preserving case
        quest_name = quest
        prefix = ""

        if 'reward from' in quest.lower():
            # Find position case-insensitively, then extract with original casing
            idx = quest.lower().find('reward from')
            if idx != -1:
                quest_name = quest[idx + len('reward from'):].strip()
                prefix = "Reward from "
        elif 'quest:' in quest.lower():
            # Find position case-insensitively, then extract with original casing
            idx = quest.lower().find('quest:')
            if idx != -1:
                quest_name = quest[idx + len('quest:'):].strip()
                prefix = ""

        # Create wiki link from full quest name
        quest_link = create_wiki_link(quest_name)

        # Truncate for display only AFTER extracting the name
        if len(quest) > 150:
            quest_display = quest[:147] + "..."
        else:
            quest_display = quest

        # Build the display text
        if prefix:
            how_to_get.append(f"\n📜 **Quest/Reward:** {prefix}{quest_link}")
        else:
            how_to_get.append(f"\n📜 **Quest/Reward:** {quest_link}")

    requirements = wiki_data.get('requirements', [])
    if requirements:
        req_text = '\n'.join([f"❗ {req}" for req in requirements[:3]])
        how_to_get.append(f"\n**Requirements:**\n{req_text}")

    if how_to_get:
        embed.add_field(name="📦 How to Obtain",
                        value='\n'.join(how_to_get),
                        inline=False)

    price = wiki_data.get('price')
    sellback = wiki_data.get('sellback')
    if price or sellback:
        pricing = []
        if price:
            # Format the price to include currency if not present
            price_upper = price.upper()
            if 'AC' not in price_upper and 'GOLD' not in price_upper:
                # If it's just a number, assume it's Gold
                if price.replace(',', '').replace('.', '').isdigit():
                    price_display = f"{price} Gold 🪙"
                else:
                    price_display = price
            elif 'AC' in price_upper:
                price_display = f"{price} <:aclarge:1438723955740639435>"
            else:
                price_display = f"{price} 🪙"

            pricing.append(f"**Price:** {price_display}")

        if sellback:
            # Format the sellback to include currency if not present
            sellback_upper = sellback.upper()
            if 'AC' not in sellback_upper and 'GOLD' not in sellback_upper:
                if sellback.replace(',', '').replace('.', '').isdigit():
                    sellback_display = f"{sellback} Gold 🪙"
                else:
                    sellback_display = sellback
            elif 'AC' in sellback_upper:
                sellback_display = f"{sellback} <:aclarge:1438723955740639435>"
            else:
                sellback_display = f"{sellback} 🪙"

            pricing.append(f"**Sellback:** {sellback_display}")

        embed.add_field(name="💰 Pricing",
                        value='\n'.join(pricing),
                        inline=True)

    # Add merge requirements if available
    merge_requirements = wiki_data.get('merge_requirements')
    if merge_requirements:
        # Only show merge requirements if this is actually merge materials (not regular currency)
        # Regular currency examples: "0 AC", "50,000 Gold", "N/A"
        # Merge materials: "Roentgenium of Nulgathx15,Void Crystal Ax1,..."

        # Check if it's regular currency vs merge materials
        # Merge materials have pattern: "ItemNamexQuantity" (e.g., "Roentgenium of Nulgathx15")
        # Currency: "0 AC", "50,000 Gold", "N/A"
        merge_upper = merge_requirements.upper()

        # Check if it has merge material patterns (lowercase 'x' between item name and number)
        has_merge_pattern = False
        for part in merge_requirements.split(','):
            part = part.strip()
            if 'x' in part.lower():
                # Check if there's a number after 'x'
                x_parts = part.lower().rsplit('x', 1)
                if len(x_parts) == 2 and x_parts[1].strip().isdigit():
                    has_merge_pattern = True
                    break

        # If no merge pattern found, check if it's currency
        is_currency = (not has_merge_pattern
                       and (merge_upper in ['N/A', 'NA', 'NONE']
                            or 'AC' in merge_upper or 'GOLD' in merge_upper))

        if not is_currency:
            # Parse merge requirements (format: "Item1x5,Item2x10,Item3x1")
            items = merge_requirements.split(',')
            merge_list = []
            for item in items[:10]:  # Show up to 10 items
                item = item.strip()
                if item:
                    # Try to extract item name and quantity
                    if 'x' in item:
                        parts = item.rsplit('x', 1)
                        if len(parts) == 2:
                            item_name = parts[0].strip()
                            quantity = parts[1].strip()
                            # Verify quantity is numeric (to avoid false positives)
                            if quantity.isdigit():
                                # Create wiki link for the item
                                item_link = create_wiki_link(item_name)
                                merge_list.append(f"• {item_link} x{quantity}")
                            else:
                                merge_list.append(f"• {item}")
                        else:
                            merge_list.append(f"• {item}")
                    else:
                        merge_list.append(f"• {item}")

            if merge_list:
                embed.add_field(name="🔨 Merge Requirements",
                                value='\n'.join(merge_list),
                                inline=False)

    notes = wiki_data.get('notes', [])
    if notes:
        notes_text = '\n'.join([
            f"• {note[:120]}{'...' if len(note) > 120 else ''}"
            for note in notes[:3]
        ])
        embed.add_field(name="📝 Notes", value=notes_text, inline=False)

    embed.set_footer(text="Source: AQW Wiki • Click title to view full page")

    return embed


@bot.event
async def on_ready():
    global http_session
    try:
        if http_session is None:
            http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                connector=aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
            )

        guild_ids_env = os.getenv("GUILD_IDS")
        if guild_ids_env:
            guild_ids = [gid.strip() for gid in guild_ids_env.split(',') if gid.strip()]
        else:
            single_guild_id = os.getenv("GUILD_ID")
            guild_ids = [single_guild_id.strip()] if single_guild_id else []
        logger.info(f"Bot logged in as {bot.user.name} (ID: {bot.user.id})")
        try:
            if BOT_STATUS_TYPE == "custom":
                activity = discord.CustomActivity(name=BOT_STATUS)
            elif BOT_STATUS_TYPE == "watching":
                activity = discord.Activity(type=discord.ActivityType.watching, name=BOT_STATUS)
            elif BOT_STATUS_TYPE == "competing":
                activity = discord.Activity(type=discord.ActivityType.competing, name=BOT_STATUS)
            elif BOT_STATUS_TYPE == "playing":
                activity = discord.Activity(type=discord.ActivityType.playing, name=BOT_STATUS)
            else:
                activity = discord.Activity(type=discord.ActivityType.listening, name=BOT_STATUS)
            await bot.change_presence(status=discord.Status.online, activity=activity)
        except Exception as presence_err:
            logger.warning(f"Failed to set presence: {presence_err}")
        
        try:
            if guild_ids:
                latest_synced = []
                for gid in guild_ids:
                    try:
                        guild_obj = discord.Object(id=int(gid))
                    except ValueError:
                        logger.warning(f"⚠️ Invalid guild ID configured: {gid}")
                        continue

                    # Remove any stale guild-specific commands before copying
                    bot.tree.clear_commands(guild=guild_obj)
                    bot.tree.copy_global_to(guild=guild_obj)
                    synced = await bot.tree.sync(guild=guild_obj)
                    latest_synced = [cmd.name for cmd in synced]
                    logger.info(f"✓ Synced {len(synced)} commands to guild {gid}")

                # Also clear global commands so Discord stops showing duplicates
                bot.tree.clear_commands(guild=None)
                await bot.tree.sync()
                logger.info("✓ Cleared global commands to prevent duplicate listings")
                if latest_synced:
                    logger.info(f"Registered commands: {latest_synced}")
            else:
                # Fallback to global sync if no guild ID is provided
                synced = await bot.tree.sync()
                logger.info(f"✓ Synced {len(synced)} commands globally (may take up to 1 hour)")

                logger.info(f"Registered commands: {[cmd.name for cmd in synced]}")

        except Exception as e:
            logger.error(f"Failed to sync commands: {e}", exc_info=True)
            import traceback
            traceback.print_exc()

        # Start the daily verification check task
        if not daily_verification_check.is_running():
            daily_verification_check.start()
            logger.info("✓ Daily verification check task started")

    except Exception as e:
        logger.error(f"Error in on_ready: {e}", exc_info=True)


@bot.tree.command(name="deployverification")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(channel="The channel to send the verification embed to")
async def deployverification(interaction: discord.Interaction, channel: discord.TextChannel):
    """Deploy the verification embed to a specific channel (Admin only)"""
    embed = discord.Embed(
        title="🔐 Account Verification",
        description="Verify AQW account",
        color=discord.Color.blue()
    )
    embed.add_field(name="How to verify", value="1. Click the **Start Verification** button below\n2. Enter your IGN (In-Game Name)\n3. Enter your Guild (or leave blank if you have none)", inline=False)

    view = VerifyButton()

    # Send to the specified channel
    try:
        await channel.send(embed=embed, view=view)

        # Create verification-logs channel if it doesn't exist
        logs_channel = await get_or_create_verification_logs_channel(interaction.guild)

        # Check if configured verified role exists and warn admin if not
        role_name = get_verified_role_name(interaction.guild.id)
        verified_role = discord.utils.get(interaction.guild.roles, name=role_name)

        response_msg = f"✅ Verification embed deployed to {channel.mention}"

        if logs_channel:
            response_msg += f"\n✅ Verification logs will be sent to {logs_channel.mention}"

        if not verified_role:
            response_msg += f"\n\n⚠️ **Warning:** '{role_name}' role not found in this server.\nPlease create a '{role_name}' role for the verification system to work properly.\nYou can change the configured role name using `/setverifiedrole`."

        await interaction.response.send_message(response_msg, ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)


@bot.tree.command(name="setverifiedrole")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(role_name="The name of the role to use for verified users")
async def setverifiedrole(interaction: discord.Interaction, role_name: str):
    """Set the verified role name for this server (Admin only)"""
    try:
        # Set the role name in config
        set_verified_role_name(interaction.guild.id, role_name)

        # Check if the role exists and provide appropriate feedback
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            await interaction.response.send_message(
                f"⚠️ **Configuration saved!**\n\n"
                f"Verified role name set to: **{role_name}**\n\n"
                f"**Warning:** Role '{role_name}' not found in this server.\n"
                f"Please create the role for the verification system to work properly.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"✅ Verified role name set to: **{role_name}**\n\n"
                f"All verification operations in this server will now use this role.",
                ephemeral=True
            )
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)


@bot.tree.command(name="verificationcheck")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(action="Action to perform: enable, disable, status, or runnow")
async def verificationcheck(interaction: discord.Interaction, action: Literal["enable", "disable", "status", "runnow"]):
    """Manage daily verification checks (Admin only)"""
    guild_id = interaction.guild.id

    if action == "enable":
        update_guild_verification_config(guild_id, {"daily_check_enabled": True})
        await interaction.response.send_message(
            f"✅ Daily verification checks have been **enabled** for **{interaction.guild.name}**.",
            ephemeral=True
        )

    elif action == "disable":
        update_guild_verification_config(guild_id, {"daily_check_enabled": False})
        await interaction.response.send_message(
            f"⚠️ Daily verification checks have been **disabled** for **{interaction.guild.name}**.",
            ephemeral=True
        )

    elif action == "status":
        config = get_guild_verification_config(guild_id)
        status = "✅ Enabled" if config.get("daily_check_enabled", True) else "❌ Disabled"
        last_check = config.get("last_check_time", "Never")
        total_checks = config.get("total_checks_run", 0)
        users_removed = config.get("users_removed_total", 0)

        # Get verified user count for this specific guild
        all_data = load_verified_users()
        guild_id_str = str(guild_id)
        guild_data = all_data.get(guild_id_str, {})
        verified_users = guild_data.get("users", {})
        verified_count = len(verified_users)

        embed = discord.Embed(
            title=f"📊 Verification Check Status - {interaction.guild.name}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Daily Checks", value=status, inline=False)
        embed.add_field(name="Last Check", value=last_check, inline=False)
        embed.add_field(name="Total Checks Run", value=f"{total_checks} (this server)", inline=True)
        embed.add_field(name="Users Removed", value=f"{users_removed} (this server)", inline=True)
        embed.add_field(name="Currently Verified", value=f"{verified_count} users", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    elif action == "runnow":
        await interaction.response.defer(ephemeral=True)
        try:
            # Import the run_verification_check function that we'll create next
            results = await run_verification_check(interaction.guild)

            embed = discord.Embed(
                title="✅ Verification Check Complete",
                color=discord.Color.green()
            )
            embed.add_field(name="Users Checked", value=str(results["checked"]), inline=True)
            embed.add_field(name="Mismatches Found", value=str(results["mismatches"]), inline=True)
            embed.add_field(name="Network Errors", value=str(results["errors"]), inline=True)
            embed.add_field(name="Roles Removed", value=str(results["removed"]), inline=True)

            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error running verification check: {str(e)}", ephemeral=True)
            logger.error(f"Error in manual verification check: {e}")


@bot.tree.command(name="serverinfo")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def serverinfo_command(interaction: discord.Interaction):
    """Shows server information including the Guild ID"""
    embed = discord.Embed(
        title="📊 Server Information",
        color=discord.Color.blue()
    )
    embed.add_field(name="Server Name", value=interaction.guild.name, inline=False)
    embed.add_field(name="Guild ID", value=f"`{interaction.guild.id}`", inline=False)
    embed.add_field(name="Member Count", value=interaction.guild.member_count, inline=False)
    embed.set_footer(text="Copy the Guild ID and add it to your .env file")
    await interaction.response.send_message(embed=embed, ephemeral=True)


def parse_timeout_duration(duration_raw: str) -> Optional[int]:
    """Parse timeout durations like 30m, 2h, 3d, 1w into minutes."""
    match = re.fullmatch(r"\s*(\d+)\s*([mdhwMDHW])\s*", duration_raw or "")
    if not match:
        return None

    amount, unit = match.groups()
    amount_int = int(amount)
    unit = unit.lower()
    multiplier = {"m": 1, "h": 60, "d": 1440, "w": 10080}
    return amount_int * multiplier[unit]


def _parse_hex_color(color_str: Optional[str]) -> Optional[discord.Color]:
    """Parse a hex color string like #ffcc00 into a Discord Color."""
    if not color_str:
        return None

    sanitized = color_str.strip().lower()
    if sanitized.startswith("#"):
        sanitized = sanitized[1:]

    if not re.fullmatch(r"[0-9a-f]{6}", sanitized):
        return None

    return discord.Color(int(sanitized, 16))


def apply_custom_emojis(text: str, guild: Optional[discord.Guild]) -> str:
    """Replace :emoji_name: tokens with actual custom emojis from the guild."""
    if not text or not guild:
        return text

    emoji_map = {emoji.name: str(emoji) for emoji in guild.emojis}

    def replacer(match: re.Match) -> str:
        name = match.group(1)
        return emoji_map.get(name, match.group(0))

    return re.sub(r":([A-Za-z0-9_~]+):", replacer, text)


class AnnouncementModal(ui.Modal, title="Send Announcement"):
    def __init__(self, dest_channel: discord.abc.Messageable, author: discord.Member, tag_role: Optional[discord.Role] = None):
        super().__init__(timeout=300)
        self.dest_channel = dest_channel
        self.author = author
        self.tag_role = tag_role

        self.title_input = ui.TextInput(
            label="Title",
            placeholder="Announcement title",
            max_length=256,
            required=True,
        )
        self.message_input = ui.TextInput(
            label="Message",
            style=discord.TextStyle.long,
            placeholder="Full announcement body",
            max_length=1900,
            required=True,
        )
        self.color_input = ui.TextInput(
            label="Color (hex, optional)",
            placeholder="#5b8def",
            max_length=7,
            required=False,
        )
        self.thumbnail_input = ui.TextInput(
            label="Thumbnail URL (right side, optional)",
            placeholder="https://example.com/thumb.png",
            required=False,
        )
        self.image_input = ui.TextInput(
            label="Image URL (bottom, optional)",
            placeholder="https://example.com/image.png",
            required=False,
        )

        for item in (
            self.title_input,
            self.message_input,
            self.color_input,
            self.thumbnail_input,
            self.image_input,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        color = _parse_hex_color(self.color_input.value) or discord.Color.blurple()
        guild = getattr(self.dest_channel, "guild", None) or getattr(interaction.user, "guild", None)
        title_text = apply_custom_emojis(self.title_input.value, guild)
        message_text = apply_custom_emojis(self.message_input.value, guild)

        embed = discord.Embed(
            title=title_text,
            description=message_text,
            color=color,
        )
        embed.set_footer(text=f"Posted by {self.author.display_name}")
        embed.timestamp = discord.utils.utcnow()

        if self.thumbnail_input.value:
            embed.set_thumbnail(url=self.thumbnail_input.value)
        if self.image_input.value:
            embed.set_image(url=self.image_input.value)

        content = self.tag_role.mention if self.tag_role else None
        allowed = discord.AllowedMentions(roles=True, users=False, everyone=False)
        try:
            await self.dest_channel.send(content=content, embed=embed, allowed_mentions=allowed)
            await interaction.followup.send(
                f"Announcement posted in {self.dest_channel.mention}",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to post in that channel.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"Failed to send announcement: {e}",
                ephemeral=True,
            )


class GiveawayView(ui.View):
    def __init__(self, host: discord.Member, winner_count: int, end_time):
        super().__init__(timeout=None)
        self.host = host
        self.winner_count = winner_count
        self.end_time = end_time
        self.entries = set()
        self.ended = False
        self.message: Optional[discord.Message] = None

    @ui.button(label="Join Giveaway", style=discord.ButtonStyle.primary, custom_id="giveaway_enter")
    async def enter_giveaway(self, interaction: discord.Interaction, button: ui.Button):
        if self.ended:
            await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
            return

        if interaction.user.bot:
            await interaction.response.send_message("Bots can't enter giveaways.", ephemeral=True)
            return

        if interaction.user.id in self.entries:
            self.entries.remove(interaction.user.id)
            await interaction.response.send_message("You left the giveaway. ❌", ephemeral=True)
            await self._update_entry_count()
            return

        self.entries.add(interaction.user.id)
        await interaction.response.send_message("You're in! 🎉", ephemeral=True)

        await self._update_entry_count()

    async def _update_entry_count(self):
        """Keep the entries count live on the giveaway embed."""
        if not self.message or not self.message.embeds:
            return

        embed = discord.Embed.from_dict(self.message.embeds[0].to_dict())
        entry_text = str(len(self.entries))

        updated = False
        for idx, field in enumerate(embed.fields):
            if field.name == "Entries":
                embed.set_field_at(idx, name="Entries", value=entry_text, inline=True)
                updated = True
                break

        if not updated:
            embed.add_field(name="Entries", value=entry_text, inline=True)

        try:
            await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass


class GiveawayModal(ui.Modal, title="Create Giveaway"):
    def __init__(self, dest_channel: discord.abc.Messageable, author: discord.Member, tag_role: Optional[discord.Role] = None):
        super().__init__(timeout=300)
        self.dest_channel = dest_channel
        self.author = author
        self.tag_role = tag_role

        self.title_input = ui.TextInput(
            label="Title",
            placeholder="Giveaway title",
            max_length=256,
            required=True,
        )
        self.description_input = ui.TextInput(
            label="Message",
            style=discord.TextStyle.long,
            placeholder="Details about the prize and how to enter",
            max_length=1900,
            required=True,
        )
        self.duration_input = ui.TextInput(
            label="Duration (e.g. 30m, 2h, 1d)",
            placeholder="Use m/h/d/w units",
            max_length=10,
            required=True,
        )
        self.winners_input = ui.TextInput(
            label="Number of winners",
            placeholder="1",
            max_length=3,
            required=True,
        )
        self.thumbnail_input = ui.TextInput(
            label="Thumbnail URL (image on the right, optional)",
            placeholder="https://example.com/image.png",
            required=False,
        )

        for item in (
            self.title_input,
            self.description_input,
            self.duration_input,
            self.winners_input,
            self.thumbnail_input,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = getattr(self.dest_channel, "guild", None) or getattr(interaction.user, "guild", None)
        title_text = apply_custom_emojis(self.title_input.value, guild)
        description_text = apply_custom_emojis(self.description_input.value, guild)

        parsed_minutes = parse_timeout_duration(self.duration_input.value)
        if parsed_minutes is None:
            await interaction.followup.send(
                "Invalid duration. Use m=minutes, h=hours, d=days, w=weeks (examples: 30m, 2h, 3d, 1w).",
                ephemeral=True,
            )
            return

        if parsed_minutes < 1 or parsed_minutes > MAX_TIMEOUT_MINUTES:
            await interaction.followup.send(
                "Duration must be between 1m and 28d. Examples: 30m, 2h, 7d, 1w.",
                ephemeral=True,
            )
            return

        try:
            winner_count = int(self.winners_input.value)
        except ValueError:
            await interaction.followup.send("Winner count must be a number.", ephemeral=True)
            return

        if winner_count < 1:
            await interaction.followup.send("Winner count must be at least 1.", ephemeral=True)
            return

        end_time = discord.utils.utcnow() + timedelta(minutes=parsed_minutes)
        view = GiveawayView(host=self.author, winner_count=winner_count, end_time=end_time)

        ts = int(end_time.timestamp())
        embed = discord.Embed(
            title=title_text,
            description=description_text,
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Winners", value=str(winner_count), inline=True)
        embed.add_field(name="Entries", value="0", inline=True)
        embed.add_field(name="Ends", value=f"<t:{ts}:R> (<t:{ts}:f>)", inline=False)
        if self.thumbnail_input.value:
            embed.set_thumbnail(url=self.thumbnail_input.value)
        embed.set_footer(text="Join below to enter!")
        embed.timestamp = discord.utils.utcnow()

        content = self.tag_role.mention if self.tag_role else None
        allowed = discord.AllowedMentions(roles=True, users=False, everyone=False)

        message = await self.dest_channel.send(content=content, embed=embed, view=view, allowed_mentions=allowed)
        view.message = message

        await interaction.followup.send(
            f"Giveaway started in {self.dest_channel.mention}. Ends <t:{ts}:R>.",
            ephemeral=True,
        )

        async def conclude_giveaway():
            try:
                sleep_seconds = max(0, (end_time - discord.utils.utcnow()).total_seconds())
                await asyncio.sleep(sleep_seconds)

                view.ended = True
                entries = list(view.entries)
                if entries:
                    winner_ids = random.sample(entries, k=min(winner_count, len(entries)))
                    winners_text = ", ".join(f"<@{uid}>" for uid in winner_ids)
                    result_text = f"🎉 Winners: {winners_text}"
                    result_color = discord.Color.green()
                else:
                    winner_ids = []
                    result_text = "No valid entries."
                    result_color = discord.Color.red()

                for child in view.children:
                    child.disabled = True

                end_embed = discord.Embed(
                    title=f"{self.title_input.value} (Ended)",
                    description=result_text,
                    color=result_color,
                )
                end_embed.add_field(name="Winners", value=str(winner_count), inline=True)
                end_embed.add_field(name="Entries", value=str(len(entries)), inline=True)
                end_embed.add_field(name="Ended", value=f"<t:{ts}:f>", inline=False)
                end_embed.timestamp = discord.utils.utcnow()
                end_embed.set_footer(text="Giveaway concluded")

                try:
                    await message.edit(embed=end_embed, view=view)
                except discord.HTTPException:
                    pass

                allowed_mentions = discord.AllowedMentions(roles=True, users=False, everyone=False)
                tag_prefix = f"{self.tag_role.mention} " if self.tag_role else ""

                if winner_ids:
                    winners_embed = discord.Embed(
                        title="🎉 Giveaway Winners",
                        description=f"{', '.join(f'<@{uid}>' for uid in winner_ids)}\n\nThank you everyone for participating!",
                        color=discord.Color.green(),
                    )
                    winners_embed.add_field(name="Prize", value=self.title_input.value, inline=True)
                    winners_embed.add_field(name="Entries", value=str(len(entries)), inline=True)
                    winners_embed.timestamp = discord.utils.utcnow()
                    await message.channel.send(
                        content=tag_prefix or None,
                        embed=winners_embed,
                        allowed_mentions=allowed_mentions,
                    )
                else:
                    no_entry_embed = discord.Embed(
                        title="Giveaway Ended",
                        description="No valid entries.\n\nThank you everyone for participating!",
                        color=discord.Color.red(),
                    )
                    no_entry_embed.add_field(name="Prize", value=self.title_input.value, inline=True)
                    no_entry_embed.timestamp = discord.utils.utcnow()
                    await message.channel.send(
                        content=tag_prefix or None,
                        embed=no_entry_embed,
                        allowed_mentions=allowed_mentions,
                    )

                view.stop()
            except Exception as e:
                try:
                    await message.channel.send(f"⚠️ Giveaway error: {e}")
                except Exception:
                    pass

        asyncio.create_task(conclude_giveaway())


@bot.tree.command(name="announce")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@app_commands.describe(
    channel="Channel to post in (defaults to this channel)",
    tag="Role to mention in the announcement (optional)"
)
async def announce_command(
    interaction: discord.Interaction,
    channel: Optional[discord.TextChannel] = None,
    tag: Optional[discord.Role] = None,
):
    """Open a modal to craft and post an announcement embed."""
    dest_channel = channel or interaction.channel
    if not isinstance(dest_channel, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message(
            "Please choose a text channel to post the announcement.",
            ephemeral=True,
        )
        return

    await interaction.response.send_modal(
        AnnouncementModal(dest_channel=dest_channel, author=interaction.user, tag_role=tag)
    )


def _rps_outcome(a: str, b: str) -> int:
    beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
    if a == b:
        return 0
    return 1 if beats[a] == b else 2


class RPSChallenge:
    def __init__(self, challenger: discord.Member, opponent: discord.Member, channel: discord.abc.Messageable, command_interaction: discord.Interaction):
        self.challenger = challenger
        self.opponent = opponent
        self.channel = channel
        self.command_interaction = command_interaction
        self.message: Optional[discord.Message] = None
        self.choices: dict[int, str] = {}
        self.completed = False
        self.challenge_view: Optional[ui.View] = None

    def record_choice(self, user_id: int, choice: str) -> bool:
        if self.completed:
            return False
        self.choices[user_id] = choice
        return len(self.choices) >= 2

    async def finish(self):
        if self.completed or len(self.choices) < 2:
            return
        self.completed = True

        challenger_choice = self.choices.get(self.challenger.id)
        opponent_choice = self.choices.get(self.opponent.id)
        result = _rps_outcome(challenger_choice, opponent_choice)

        if result == 0:
            winner_text = "It's a draw!"
            color = discord.Color.greyple()
        elif result == 1:
            winner_text = f"Winner: {self.challenger.mention}"
            color = discord.Color.green()
        else:
            winner_text = f"Winner: {self.opponent.mention}"
            color = discord.Color.green()

        result_embed = discord.Embed(
            title="Rock Paper Scissors Result",
            description=winner_text,
            color=color,
        )
        result_embed.add_field(name=self.challenger.display_name, value=challenger_choice.title(), inline=True)
        result_embed.add_field(name=self.opponent.display_name, value=opponent_choice.title(), inline=True)
        result_embed.timestamp = discord.utils.utcnow()

        if self.challenge_view and self.message:
            for child in self.challenge_view.children:
                child.disabled = True
            try:
                await self.message.edit(view=self.challenge_view)
            except discord.HTTPException:
                pass

        try:
            await self.channel.send(embed=result_embed)
        except discord.HTTPException:
            pass


class RPSMoveView(ui.View):
    def __init__(self, session: RPSChallenge, allowed_user: discord.Member):
        super().__init__(timeout=60)
        self.session = session
        self.allowed_user = allowed_user

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.allowed_user.id:
            await interaction.response.send_message("You're not part of this match.", ephemeral=True)
            return False
        return True

    async def _handle_choice(self, interaction: discord.Interaction, choice: str):
        self.session.record_choice(interaction.user.id, choice)
        for child in self.children:
            child.disabled = True

        try:
            await interaction.response.edit_message(content=f"You chose **{choice.title()}**.", view=self)
        except discord.HTTPException:
            pass

        await self.session.finish()

    @ui.button(label="Rock", style=discord.ButtonStyle.secondary)
    async def choose_rock(self, interaction: discord.Interaction, button: ui.Button):
        await self._handle_choice(interaction, "rock")

    @ui.button(label="Paper", style=discord.ButtonStyle.secondary)
    async def choose_paper(self, interaction: discord.Interaction, button: ui.Button):
        await self._handle_choice(interaction, "paper")

    @ui.button(label="Scissors", style=discord.ButtonStyle.secondary)
    async def choose_scissors(self, interaction: discord.Interaction, button: ui.Button):
        await self._handle_choice(interaction, "scissors")


class RPSChallengeView(ui.View):
    def __init__(self, session: RPSChallenge):
        super().__init__(timeout=120)
        self.session = session
        self.session.challenge_view = self

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.session.completed:
            await interaction.response.send_message("This challenge is already finished.", ephemeral=True)
            return False
        return True

    @ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.session.opponent.id:
            await interaction.response.send_message("Only the challenged user can respond.", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content=f"{self.session.challenger.mention} vs {self.session.opponent.mention} — choosing moves...",
            view=self,
        )

        try:
            await interaction.followup.send(
                "Pick your move:",
                view=RPSMoveView(self.session, self.session.opponent),
                ephemeral=True,
            )
        except discord.HTTPException:
            pass

        try:
            await self.session.command_interaction.followup.send(
                "Pick your move:",
                view=RPSMoveView(self.session, self.session.challenger),
                ephemeral=True,
            )
        except discord.HTTPException:
            pass

    @ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.session.opponent.id:
            await interaction.response.send_message("Only the challenged user can respond.", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content=f"{self.session.opponent.mention} has rejected the challenge. What a coward.",
            view=self,
        )
        self.session.completed = True

    async def on_timeout(self):
        if self.session.completed or not self.session.message:
            return
        for child in self.children:
            child.disabled = True
        try:
            await self.session.message.edit(content="Rock Paper Scissors challenge expired.", view=self)
        except discord.HTTPException:
            pass


@bot.tree.command(name="giveaway")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@app_commands.describe(
    channel="Channel to post in (defaults to this channel)",
    tag="Role to mention when the giveaway starts and ends (optional)"
)
async def giveaway_command(
    interaction: discord.Interaction,
    channel: Optional[discord.TextChannel] = None,
    tag: Optional[discord.Role] = None,
):
    """Open a modal to create a giveaway embed with a join button."""
    dest_channel = channel or interaction.channel
    if not isinstance(dest_channel, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message(
            "Please choose a text channel to post the giveaway.",
            ephemeral=True,
        )
        return

    await interaction.response.send_modal(
        GiveawayModal(dest_channel=dest_channel, author=interaction.user, tag_role=tag)
    )


@bot.tree.command(name="rps")
@app_commands.guild_only()
@app_commands.describe(
    opponent="Who you want to challenge"
)
async def rps_command(interaction: discord.Interaction, opponent: discord.Member):
    """Challenge another user to Rock Paper Scissors."""
    if opponent.id == interaction.user.id:
        await interaction.response.send_message("You can't challenge yourself.", ephemeral=True)
        return
    if opponent.bot:
        await interaction.response.send_message("You can't challenge bots.", ephemeral=True)
        return

    session = RPSChallenge(interaction.user, opponent, interaction.channel, interaction)
    view = RPSChallengeView(session)
    challenge_message = f"{interaction.user.mention} challenges {opponent.mention} to Rock Paper Scissors! Accept?"
    await interaction.response.send_message(challenge_message, view=view)
    try:
        session.message = await interaction.original_response()
    except Exception:
        session.message = None


@bot.tree.command(name="mute")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@app_commands.describe(
    member="Member to mute (timeout)",
    duration="Timeout duration using m/h/d/w (e.g. 30m, 2h, 3d, or 1w; max 28 days)",
    reason="Why they are being muted"
)
async def mute_command(
    interaction: discord.Interaction,
    member: discord.Member,
    duration: str,
    reason: Optional[str] = None
):
    """Apply a communication timeout to a member."""
    await interaction.response.defer(ephemeral=True)

    if member.id == interaction.user.id:
        await interaction.followup.send("You cannot mute yourself.", ephemeral=True)
        return

    if interaction.guild and member == interaction.guild.owner:
        await interaction.followup.send("You cannot mute the server owner.", ephemeral=True)
        return

    parsed_minutes = parse_timeout_duration(duration)
    if parsed_minutes is None:
        await interaction.followup.send("Invalid duration. Use m=minutes, h=hours, d=days, w=weeks (examples: 30m, 2h, 3d, 1w).", ephemeral=True)
        return

    if parsed_minutes < 1 or parsed_minutes > MAX_TIMEOUT_MINUTES:
        await interaction.followup.send("Duration must be between 1m and 28d. Examples: 30m, 2h, 7d, 1w.", ephemeral=True)
        return

    # Ensure role hierarchy is respected
    me = interaction.guild.me if interaction.guild else None
    if me and member.top_role >= me.top_role:
        await interaction.followup.send("I can't mute that member because their top role is higher or equal to mine.", ephemeral=True)
        return
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.followup.send("You can’t mute someone with an equal or higher role.", ephemeral=True)
        return

    until = discord.utils.utcnow() + timedelta(minutes=parsed_minutes)
    try:
        await member.timeout(until, reason=reason or "Muted via /mute command")
        ts = int(until.timestamp())
        await interaction.followup.send(
            f"✅ {member.mention} muted until <t:{ts}:R> (<t:{ts}:f>).",
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to mute that member.", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"Failed to mute: {e}", ephemeral=True)


@bot.tree.command(name="unmute")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@app_commands.describe(
    member="Member to remove timeout from",
    reason="Why they are being unmuted"
)
async def unmute_command(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: Optional[str] = None
):
    """Remove communication timeout from a member."""
    await interaction.response.defer(ephemeral=True)

    if interaction.guild and member == interaction.guild.owner:
        await interaction.followup.send("You cannot unmute the server owner (they cannot be muted).", ephemeral=True)
        return

    me = interaction.guild.me if interaction.guild else None
    if me and member.top_role >= me.top_role:
        await interaction.followup.send("I can't unmute that member because their top role is higher or equal to mine.", ephemeral=True)
        return
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.followup.send("You can’t unmute someone with an equal or higher role.", ephemeral=True)
        return

    try:
        await member.timeout(None, reason=reason or "Unmuted via /unmute command")
        await interaction.followup.send(f"✅ {member.mention} has been unmuted.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to unmute that member.", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"Failed to unmute: {e}", ephemeral=True)


@bot.tree.command(
    name='char',
    description='Fetch character details from their AQ.com page.')
@app_commands.describe(username='Character username to look up')
async def char(interaction: discord.Interaction, username: str):
    await interaction.response.defer()

    try:
        # Get character data from the new scraper service
        char_data = await get_char_data(username)

        # Handle errors from the service
        if not char_data or 'error' in char_data:
            error_message = char_data.get('error', 'An unknown error occurred.')
            await interaction.followup.send(
                f'❌ **Could not fetch character data for `{username}`.**\n\n'
                f'**Reason:** {error_message}\n'
                f'Please check the character name or try again later.'
            )
            return

        # Create embed with character information
        char_name = char_data.get('name', username)
        level = char_data.get('level', 'N/A')

        # Properly encode the username for the URL to handle spaces and special characters
        encoded_username = quote_plus(username)

        embed = discord.Embed(
            title=f"Character Info: {char_name}",
            description=f"**Level {level}**",
            url=f"http://account.aq.com/CharPage?id={encoded_username}",
            color=discord.Color.blue()
        )

        # Build the equipment list
        equipment_text = []
        item_slots = ["Class", "Armor", "Helm", "Cape", "Weapon", "Pet"]
        for slot in item_slots:
            item_name = char_data.get(slot.lower())
            if item_name and item_name != "N/A":
                item_link = create_wiki_link(item_name)
                equipment_text.append(f"**{slot}:** {item_link}")
            else:
                equipment_text.append(f"**{slot}:** *None*")

        if equipment_text:
            embed.add_field(
                name="Equipped Items",
                value='\n'.join(equipment_text),
                inline=True
            )

        # Build the cosmetic items list
        cosmetic_text = []
        cosmetic_slots = [
            ("co_armor", "Armor"),
            ("co_helm", "Helm"),
            ("co_cape", "Cape"),
            ("co_weapon", "Weapon"),
            ("co_pet", "Pet")
        ]
        has_cosmetics = False
        for key, display_name in cosmetic_slots:
            item_name = char_data.get(key)
            if item_name and item_name != "N/A":
                has_cosmetics = True
                item_link = create_wiki_link(item_name)
                cosmetic_text.append(f"**{display_name}:** {item_link}")

        if has_cosmetics:
            embed.add_field(
                name="Cosmetic Items",
                value='\n'.join(cosmetic_text),
                inline=True
            )
        
        embed.set_footer(text="Click the item names to see details on the AQW Wiki.")
        embed.set_thumbnail(url="https://www.aq.com/images/avatars/1/default_avatar.png") # Generic thumbnail

        await interaction.followup.send(embed=embed)

    except Exception as e:
        logger.error(f'Error in /char command: {e}', exc_info=True)
        import traceback
        traceback.print_exc()
        await interaction.followup.send(
            f'An unexpected error occurred while processing the `/char` command: {str(e)}')



class ReplacementBossesView(ui.View):
    """View to ask which bosses each replacement covered"""

    def __init__(self, helper_view, message, button, replacements_with_ids, interaction=None):
        super().__init__(timeout=120)
        self.helper_view = helper_view
        self.message = message
        self.button = button
        self.replacements_with_ids = replacements_with_ids  # Only filled replacements
        self.current_index = 0
        # Store interaction for display name formatting
        self.initial_interaction = interaction

        if len(self.replacements_with_ids) > 0:
            self._add_current_replacement_select()

    def _add_current_replacement_select(self, interaction=None):
        """Add dropdown for current helper who left"""
        self.clear_items()

        replacement = self.replacements_with_ids[self.current_index]

        # Get display name of person who left (use formatted name instead of mention)
        left_id = replacement['left_id']
        # Use passed interaction, or fall back to initial interaction
        active_interaction = interaction or self.initial_interaction

        if active_interaction and active_interaction.guild:
            left_name = format_helper_display_name(active_interaction.client, active_interaction.guild, left_id)
        else:
            left_name = replacement['left_mention']

        # Create dropdown with all selected bosses
        options = []
        for boss in self.helper_view.selected_bosses:
            points = BOSS_POINTS.get(boss, 0)
            options.append(discord.SelectOption(
                label=boss,
                value=boss,
                description=f"{points} points"
            ))

        select = ui.Select(
            placeholder=f"Which bosses did {left_name} help with?",
            options=options,
            min_values=0,  # Can select none if they didn't help any
            max_values=len(options)
        )
        select.callback = self._bosses_selected
        self.add_item(select)

    async def _bosses_selected(self, interaction: discord.Interaction):
        """Handle boss selection for person who left"""
        selected_bosses = list(interaction.data['values'])

        # Store the bosses the person who LEFT helped with
        self.replacements_with_ids[self.current_index]['bosses_covered_by_left'] = selected_bosses

        # Now ask who replaced them
        self._add_replacement_helper_select(interaction)
        await interaction.response.edit_message(
            content=f"Helper who left {self.current_index + 1} of {len(self.replacements_with_ids)}: Who replaced them?",
            view=self
        )

    def _add_replacement_helper_select(self, interaction):
        """Add dropdown to select who replaced this person"""
        self.clear_items()

        replacement = self.replacements_with_ids[self.current_index]
        left_id = replacement['left_id']

        # Get friendly display name
        left_name = format_helper_display_name(interaction.client, interaction.guild, left_id)

        # Collect helpers who have already been assigned as replacements
        already_assigned = set()
        for i in range(self.current_index):
            prev_replacement = self.replacements_with_ids[i]
            if prev_replacement.get('replacement_id') is not None:
                already_assigned.add(prev_replacement['replacement_id'])

        # Create dropdown with current helpers (excluding those already assigned as replacements)
        options = []
        for helper_id, helper_mention in self.helper_view.helpers:
            # Skip helpers who are already assigned as replacements
            if helper_id in already_assigned:
                continue

            helper_display = format_helper_display_name(interaction.client, interaction.guild, helper_id)
            options.append(discord.SelectOption(
                label=helper_display,
                value=str(helper_id),
                description=f"Replaced {left_name}"
            ))

        # Add option for "No one replaced" in case the slot wasn't filled
        options.append(discord.SelectOption(
            label="No one replaced them",
            value="none",
            description="Slot never filled, filled by non-member, or public player"
        ))

        select = ui.Select(
            placeholder=f"Who replaced {left_name}?",
            options=options,
            min_values=1,
            max_values=1
        )
        select.callback = self._replacement_helper_selected
        self.add_item(select)

    async def _replacement_helper_selected(self, interaction: discord.Interaction):
        """Handle selection of who replaced the person who left"""
        selected_value = interaction.data['values'][0]

        if selected_value == "none":
            # No one replaced them
            self.replacements_with_ids[self.current_index]['replacement_id'] = None
            self.replacements_with_ids[self.current_index]['replacement_mention'] = "No one"
        else:
            # Find the selected helper
            selected_id = int(selected_value)
            for helper_id, helper_mention in self.helper_view.helpers:
                if helper_id == selected_id:
                    self.replacements_with_ids[self.current_index]['replacement_id'] = helper_id
                    self.replacements_with_ids[self.current_index]['replacement_mention'] = helper_mention
                    break

        # Move to next person who left
        self.current_index += 1

        if self.current_index < len(self.replacements_with_ids):
            # Show next person who left
            self._add_current_replacement_select()
            await interaction.response.edit_message(
                content=f"Helper who left {self.current_index + 1} of {len(self.replacements_with_ids)}",
                view=self
            )
        else:
            # All people who left have been processed, proceed with completion
            await interaction.response.edit_message(
                content="Processing ticket completion...",
                view=None
            )
            await self._complete_ticket_with_replacements(interaction)

    async def _complete_ticket_with_replacements(self, interaction: discord.Interaction):
        """Complete ticket with replacement tracking - Award points based on who covered what"""
        all_bosses = set(self.helper_view.selected_bosses)
        people_who_left = {}  # {left_id: {mention, bosses_covered, points}}
        replacement_rewards = {}  # {replacement_id: {points, bosses}}
        helpers_with_replacements = set()  # Track which helpers are replacements

        # Step 1: Process each person who left
        for replacement in self.replacements_with_ids:
            left_id = replacement['left_id']
            left_mention = replacement['left_mention']
            bosses_covered_by_left = set(replacement.get('bosses_covered_by_left', []))
            replacement_id = replacement.get('replacement_id')

            # Award points to person who left for the bosses they helped with
            left_points = sum(BOSS_POINTS.get(boss, 0) for boss in bosses_covered_by_left)

            if left_points > 0 or len(bosses_covered_by_left) > 0:
                new_total = add_points(left_id, left_points, list(bosses_covered_by_left), interaction.guild.id)
                people_who_left[left_id] = {
                    'mention': left_mention,
                    'bosses_covered': list(bosses_covered_by_left),
                    'points': left_points,
                    'new_total': new_total
                }

            # Award remaining bosses to the REPLACEMENT (if there is one)
            if replacement_id is not None:
                helpers_with_replacements.add(replacement_id)
                remaining_bosses_for_this_slot = all_bosses - bosses_covered_by_left
                remaining_points_for_this_slot = sum(BOSS_POINTS.get(boss, 0) for boss in remaining_bosses_for_this_slot)

                if replacement_id not in replacement_rewards:
                    replacement_rewards[replacement_id] = {'points': 0, 'bosses': set()}

                replacement_rewards[replacement_id]['points'] += remaining_points_for_this_slot
                replacement_rewards[replacement_id]['bosses'].update(remaining_bosses_for_this_slot)

        # Step 2: Award points to helpers
        helper_rewards = []
        for helper_id, helper_mention in self.helper_view.helpers:
            if helper_id in replacement_rewards:
                # This helper replaced someone - award only the remaining bosses they covered
                reward_info = replacement_rewards[helper_id]
                points = reward_info['points']
                bosses = list(reward_info['bosses'])
                new_total = add_points(helper_id, points, bosses, interaction.guild.id)
                helper_rewards.append(f"{helper_mention}: +{points} points (Total: {new_total})")
            else:
                # This helper was NOT a replacement - award ALL bosses
                total_points = sum(BOSS_POINTS.get(boss, 0) for boss in all_bosses)
                new_total = add_points(helper_id, total_points, list(all_bosses), interaction.guild.id)
                helper_rewards.append(f"{helper_mention}: +{total_points} points (Total: {new_total})")

        # Add people who left to helper rewards
        for left_id, left_info in people_who_left.items():
            helper_rewards.append(f"{left_info['mention']}: +{left_info['points']} points (Total: {left_info['new_total']}) [Left mid-run]")

        # Build detailed breakdown
        boss_points_breakdown = []
        for boss in self.helper_view.selected_bosses:
            points = BOSS_POINTS.get(boss, 0)
            boss_points_breakdown.append(f"**{boss}:** {points} points")

        completion_summary = "\n".join(boss_points_breakdown)

        # Add info about people who left and their replacements
        if self.replacements_with_ids:
            completion_summary += "\n\n**Replacements:**"
            for repl in self.replacements_with_ids:
                left_id = repl['left_id']
                left_name = repl['left_mention']
                repl_name = repl['replacement_mention']
                bosses_covered_by_left = repl.get('bosses_covered_by_left', [])

                if bosses_covered_by_left:
                    bosses_str = ", ".join(bosses_covered_by_left)
                    left_points = sum(BOSS_POINTS.get(b, 0) for b in bosses_covered_by_left)
                    completion_summary += f"\n• {repl_name} replaced {left_name}"
                    completion_summary += f"\n  ↳ {left_name} helped with: {bosses_str} ({left_points}pts)"
                else:
                    completion_summary += f"\n• {repl_name} replaced {left_name}"
                    completion_summary += f"\n  ↳ {left_name} left before helping (0pts)"

        # Mark ticket as completed
        self.helper_view.ticket_completed = True
        self.button.disabled = True
        await self.message.edit(view=self.helper_view)

        # Create completion embed
        completion_embed = discord.Embed(
            title="✅ Ticket Completed!",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )

        completion_embed.add_field(
            name="Requester",
            value=f"<@{self.helper_view.requester_id}>",
            inline=False
        )

        completion_embed.add_field(
            name="Completion Summary",
            value=completion_summary,
            inline=False
        )

        completion_embed.add_field(
            name="Helper Rewards",
            value="\n".join(helper_rewards) if helper_rewards else "No helpers received points",
            inline=False
        )

        # Send to ticket-logs
        guild = interaction.guild
        ticket_logs_channel = discord.utils.get(guild.text_channels, name="ticket-logs")

        if ticket_logs_channel:
            await ticket_logs_channel.send(embed=completion_embed)
            await interaction.followup.send("Ticket completed! Summary sent to ticket-logs. Channel will be deleted in 10 seconds.", ephemeral=True)
            await asyncio.sleep(10)
            try:
                await interaction.channel.delete(reason="Ticket completed")
            except Exception as e:
                logger.error(f"Error deleting channel: {e}")
        else:
            await interaction.followup.send(embed=completion_embed, ephemeral=False)


class HelperView(ui.View):
    """View with I'll Help button for helpers"""

    def __init__(self, requester_id, selected_bosses):
        super().__init__(timeout=None)
        self.helpers = []
        self.max_helpers = 3
        self.requester_id = requester_id
        self.selected_bosses = selected_bosses
        self.ticket_completed = False
        self.replacements = []  # Track replacements: [{'left_id': int, 'left_mention': str, 'replacement_id': int, 'replacement_mention': str, 'bosses_covered': []}]

        # Update button label to show initial count
        for item in self.children:
            if isinstance(item, ui.Button) and item.custom_id == "helper_button":
                item.label = f"I'll Help (0/{self.max_helpers})"
                break

    @ui.button(label="I'll Help (0/3)", style=discord.ButtonStyle.success, custom_id="helper_button")
    async def help_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id
            user_mention = interaction.user.mention

            # Check if user is the requester
            if user_id == self.requester_id:
                await interaction.response.send_message("You cannot join as a helper for your own request!", ephemeral=True)
                return

            # Check if user already volunteered
            if user_id in [h[0] for h in self.helpers]:
                await interaction.response.send_message("You've already volunteered to help!", ephemeral=True)
                return

            # Check if max helpers reached
            if len(self.helpers) >= self.max_helpers:
                await interaction.response.send_message("Only 3 helpers allowed", ephemeral=True)
                return

            # Check if this is a replacement (someone left before and slot not filled)
            unfilled_replacement = None
            for replacement in self.replacements:
                if replacement['replacement_id'] is None:
                    unfilled_replacement = replacement
                    break

            # Add helper
            self.helpers.append((user_id, user_mention))

            # If this is a replacement, track it
            if unfilled_replacement:
                unfilled_replacement['replacement_id'] = user_id
                unfilled_replacement['replacement_mention'] = user_mention

            # Track ticket join
            track_ticket_join(user_id, interaction.guild.id)

            # Update the button label to show count
            for item in self.children:
                if isinstance(item, ui.Button) and item.custom_id in ["helper_button", "dailies_helper_button", "7man_helper_button"]:
                    item.label = f"I'll Help ({len(self.helpers)}/{self.max_helpers})"
                    break

            await interaction.response.edit_message(view=self)
            await interaction.followup.send(f"{user_mention} has joined as a helper! ({len(self.helpers)}/{self.max_helpers})")

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="Remove Helper", style=discord.ButtonStyle.danger, custom_id="remove_helper_button")
    async def remove_helper_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id

            # Check if user is requester or admin
            is_requester = user_id == self.requester_id
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_requester or is_admin):
                await interaction.response.send_message("Only the requester or admins can remove helpers!", ephemeral=True)
                return

            # Check if there are any helpers to remove
            if not self.helpers:
                await interaction.response.send_message("There are no helpers to remove!", ephemeral=True)
                return

            # Create a dropdown to select which helper to remove
            options = []
            for helper_id, _ in self.helpers:
                display_name = format_helper_display_name(interaction.client, interaction.guild, helper_id)
                options.append(discord.SelectOption(
                    label=display_name,
                    value=str(helper_id),
                    description=f"Remove {display_name}"
                ))

            select = ui.Select(
                placeholder="Select a helper to remove...",
                options=options,
                custom_id="select_helper_to_remove"
            )

            async def select_callback(select_interaction: discord.Interaction):
                try:
                    selected_helper_id = int(select.values[0])

                    # Find and remove the helper
                    removed_helper = None
                    for i, (helper_id, helper_mention) in enumerate(self.helpers):
                        if helper_id == selected_helper_id:
                            removed_helper = self.helpers.pop(i)
                            break

                    # Track this as a replacement (will be filled when someone joins)
                    if removed_helper:
                        self.replacements.append({
                            'left_id': removed_helper[0],
                            'left_mention': removed_helper[1],
                            'replacement_id': None,
                            'replacement_mention': None,
                            'bosses_covered': []
                        })

                    # Update the button label to show count
                    for item in self.children:
                        if isinstance(item, ui.Button) and item.custom_id in ["helper_button", "dailies_helper_button", "7man_helper_button"]:
                            item.label = f"I'll Help ({len(self.helpers)}/{self.max_helpers})" if self.helpers else "I'll Help"
                            break

                    await interaction.message.edit(view=self)

                    # Get removed helper's display name
                    removed_display_name = format_helper_display_name(select_interaction.client, interaction.guild, selected_helper_id)

                    # Tag @Helper role to notify helpers
                    helper_role = discord.utils.get(interaction.guild.roles, name="Helper")
                    role_mention = helper_role.mention if helper_role else "@here"
                    await interaction.channel.send(f"{role_mention} **{removed_display_name}** left! Requesting helpers please!")

                    await select_interaction.response.send_message("Helper removed successfully!", ephemeral=True)

                except Exception as e:
                    try:
                        await select_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
                    except:
                        pass

            select.callback = select_callback

            view = ui.View(timeout=60)
            view.add_item(select)

            await interaction.response.send_message("Select a helper to remove:", view=view, ephemeral=True)

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="Complete Ticket", style=discord.ButtonStyle.blurple, custom_id="complete_ticket_button")
    async def complete_ticket_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id

            # Check if user is requester or admin
            is_requester = user_id == self.requester_id
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_requester or is_admin):
                await interaction.response.send_message("Only the requester or admins can complete the ticket!", ephemeral=True)
                return

            # Check if ticket was already completed
            if self.ticket_completed:
                await interaction.response.send_message("This ticket has already been completed!", ephemeral=True)
                return

            # Check if there are any helpers
            if not self.helpers:
                await interaction.response.send_message("Cannot complete ticket - no helpers have joined!", ephemeral=True)
                return

            # Check if there are ANY replacements (people who left, regardless of whether they were replaced)
            if self.replacements:
                # Ask which bosses each PERSON WHO LEFT helped with (all of them, not just filled ones)
                view = ReplacementBossesView(self, interaction.message, button, self.replacements, interaction)
                await interaction.response.send_message(
                    f"There were {len(self.replacements)} helper(s) who left. Please specify which bosses each person who left helped with (select none if they didn't help any).",
                    view=view,
                    ephemeral=True
                )
                return

        # Calculate total points based on selected bosses
            total_points = sum(BOSS_POINTS.get(boss, 0) for boss in self.selected_bosses)

            # Award points to all helpers
            helper_rewards = []
            for helper_id, helper_mention in self.helpers:
                new_total = add_points(helper_id, total_points, self.selected_bosses, interaction.guild.id)
                helper_rewards.append(f"{helper_mention}: +{total_points} points (Total: {new_total})")

            # Mark ticket as completed
            self.ticket_completed = True

            # Disable the Complete Ticket button
            button.disabled = True
            await interaction.message.edit(view=self)

            # Create detailed completion summary
            boss_points_breakdown = []
            for boss in self.selected_bosses:
                points = BOSS_POINTS.get(boss, 0)
                boss_points_breakdown.append(f"**{boss}:** {points} points")

            completion_summary = "\n".join(boss_points_breakdown)
            completion_summary += f"\n\n**Total Points:** {total_points} per helper"

            # Create completion embed
            completion_embed = discord.Embed(
                title="✅ Ticket Completed!",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )

            completion_embed.add_field(
                name="Requester",
                value=f"<@{self.requester_id}>",
                inline=False
            )

            completion_embed.add_field(
                name="Completion Summary",
                value=completion_summary,
                inline=False
            )

            completion_embed.add_field(
                name="Helper Rewards",
                value="\n".join(helper_rewards),
                inline=False
            )

            # Find the ticket-logs channel
            guild = interaction.guild
            ticket_logs_channel = discord.utils.get(guild.text_channels, name="ticket-logs")

            if ticket_logs_channel:
                # Send to ticket-logs channel
                await ticket_logs_channel.send(embed=completion_embed)
                await interaction.response.send_message("Ticket completed! Summary sent to ticket-logs. Channel will be deleted in 10 seconds.", ephemeral=True)

                # Wait 10 seconds then delete the channel
                await asyncio.sleep(10)
                try:
                    await interaction.channel.delete(reason="UltraWeeklies ticket completed")
                except Exception as e:
                    logger.error(f"Error deleting channel: {e}")
            else:
                # Fallback: send in current channel if ticket-logs doesn't exist
                await interaction.response.send_message(embed=completion_embed, ephemeral=False)

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="Cancel Ticket", style=discord.ButtonStyle.danger, custom_id="cancel_ticket_button")
    async def cancel_ticket_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id

            # Check if user is requester or admin
            is_requester = user_id == self.requester_id
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_requester or is_admin):
                await interaction.response.send_message("Only the requester or admins can cancel the ticket!", ephemeral=True)
                return

            # Send cancellation message
            await interaction.response.send_message("Ticket cancelled. Channel will be deleted in 5 seconds.", ephemeral=True)

            # Wait 5 seconds then delete the channel
            await asyncio.sleep(5)
            try:
                await interaction.channel.delete(reason="UltraWeeklies ticket cancelled")
            except Exception as e:
                logger.error(f"Error deleting channel: {e}")

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class UltraWeekliesModal(ui.Modal, title="UltraWeeklies Request"):
    """Modal for collecting user information for UltraWeeklies"""

    ign = ui.TextInput(
        label="IGN (In-Game Name)",
        placeholder="Enter your character name",
        required=True,
        max_length=100
    )

    room_number = ui.TextInput(
        label="Room Number",
        placeholder="Enter 4-digit room number (e.g., 1234)",
        required=True,
        min_length=4,
        max_length=4
    )

    concerns = ui.TextInput(
        label="Any Concerns",
        placeholder="Enter any special requests or concerns (optional)",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    def __init__(self, selected_bosses, server):
        super().__init__()
        self.selected_bosses = selected_bosses
        self.server = server

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_ign = self.ign.value.strip()
            user_server = self.server  # Server now comes from dropdown selection
            user_room = self.room_number.value.strip()
            user_concerns = self.concerns.value.strip() if self.concerns.value else "None"

            # Validate room number is 4 digits
            if not user_room.isdigit() or len(user_room) != 4:
                await interaction.response.send_message("Room number must be exactly 4 digits!", ephemeral=True)
                return

            # Format join commands for each boss
            join_commands = []
            for boss in self.selected_bosses:
                join_commands.append(f"/join {boss}-{user_room}")

            # Create a private channel name based on username
            channel_name = f"ultra-{interaction.user.name}-{user_room}".lower()
            channel_name = re.sub(r'[^a-z0-9-]', '', channel_name)

            # Get the guild
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Error: Could not find guild.", ephemeral=True)
                return

            # Create a text channel visible to everyone
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            # Defer the response first since channel creation takes time
            await interaction.response.defer(ephemeral=True)

            # Create the channel
            new_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites
            )

            # Create embed with all information
            embed = discord.Embed(
                title="UltraWeeklies Request",
                color=discord.Color.blue()
            )
            embed.add_field(name="IGN", value=user_ign, inline=False)
            embed.add_field(name="Server", value=user_server, inline=False)
            embed.add_field(name="Join Commands", value="\n".join(join_commands), inline=False)
            embed.add_field(name="Concerns", value=user_concerns, inline=False)
            embed.add_field(name="Requested by", value=interaction.user.mention, inline=False)
            embed.timestamp = discord.utils.utcnow()

            # Create helper view with requester ID and selected bosses
            helper_view = HelperView(requester_id=interaction.user.id, selected_bosses=self.selected_bosses)

            # Track ticket creation
            track_ticket_created(interaction.user.id, "UltraWeeklies", interaction.guild.id)

            # Send embed to the new channel with helper button
            await new_channel.send(embed=embed, view=helper_view)

            # Tag @Helper role to notify helpers
            helper_role = discord.utils.get(guild.roles, name="Helper")
            if helper_role:
                await new_channel.send(f"{helper_role.mention} New UltraWeeklies ticket created!")
                print(f"Tagged @Helper role (ID: {helper_role.id}) in channel {new_channel.name}")
            else:
                # If Helper role doesn't exist, send a general notification
                await new_channel.send("@here New UltraWeeklies ticket created!")
                print(f"WARNING: 'Helper' role not found in guild {guild.name}. Available roles: {[role.name for role in guild.roles]}")

            # Notify the user
            await interaction.followup.send(
                f"Channel created: {new_channel.mention}",
                ephemeral=True
            )

        except Exception as e:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class ServerSelectView(ui.View):
    """View for selecting AQW server"""

    def __init__(self, selected_bosses, original_user, ticket_type="UltraWeeklies"):
        super().__init__(timeout=60)
        self.selected_bosses = selected_bosses
        self.original_user = original_user
        self.add_item(ServerSelect(selected_bosses, original_user, ticket_type))


class ServerSelect(ui.Select):
    """Dropdown for AQW server selection"""

    def __init__(self, selected_bosses, original_user, ticket_type="UltraWeeklies"):
        self.selected_bosses = selected_bosses
        self.original_user = original_user
        self.ticket_type = ticket_type

        options = [
            discord.SelectOption(label="Safiria", value="Safiria"),
            discord.SelectOption(label="Artix", value="Artix"),
            discord.SelectOption(label="Gravelyn", value="Gravelyn"),
            discord.SelectOption(label="Galanoth", value="Galanoth"),
            discord.SelectOption(label="Yorumi", value="Yorumi"),
            discord.SelectOption(label="Espada", value="Espada"),
            discord.SelectOption(label="Sepulchure", value="Sepulchure"),
            discord.SelectOption(label="Swordhaven (EU)", value="Swordhaven"),
            discord.SelectOption(label="Alteon", value="Alteon"),
            discord.SelectOption(label="Yokai (SEA)", value="Yokai"),
        ]

        super().__init__(
            placeholder="Choose AQW Server...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="server_select"
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            # Only allow original user to select
            if interaction.user.id != self.original_user.id:
                await interaction.response.send_message("Only the requester can select the server.", ephemeral=True)
                return

            selected_server = self.values[0]

            # Show appropriate modal based on ticket type
            if self.ticket_type == "UltraWeeklies":
                modal = UltraWeekliesModal(self.selected_bosses, selected_server)
            elif self.ticket_type == "UltraDailies4Man":
                modal = UltraDailiesModal(self.selected_bosses, selected_server)
            elif self.ticket_type == "UltraDailies7Man":
                modal = Ultra7ManModal(self.selected_bosses, selected_server)
            elif self.ticket_type == "TempleShrineDailies":
                modal = TempleShrineDailiesModal(self.selected_bosses, selected_server)
            elif self.ticket_type == "TempleShrineSpamming":
                modal = TempleShrineSpammingModal(self.selected_bosses, selected_server)
            else:
                modal = UltraWeekliesModal(self.selected_bosses, selected_server)

            await interaction.response.send_modal(modal)

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class BossConfirmView(ui.View):
    """Confirmation view for boss selection"""

    def __init__(self, selected_bosses, original_user):
        super().__init__(timeout=60)
        self.selected_bosses = selected_bosses
        self.original_user = original_user

    @ui.button(label="Confirm", style=discord.ButtonStyle.green, custom_id="confirm_bosses")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        # Only allow the original user to confirm
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message("Only the requester can confirm this.", ephemeral=True)
            return

        # Show server selection view
        server_view = ServerSelectView(self.selected_bosses, self.original_user)
        await interaction.response.send_message(
            "**Select AQW Server:**",
            view=server_view,
            ephemeral=True
        )

    @ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel_bosses")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        # Only allow the original user to cancel
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message("Only the requester can cancel this.", ephemeral=True)
            return

        await interaction.response.send_message("Selection cancelled.", ephemeral=True)

        # Disable the buttons
        self.confirm_button.disabled = True
        self.cancel_button.disabled = True
        await interaction.message.edit(view=self)


class UltraWeekliesSelect(ui.Select):
    """Dropdown select menu for UltraWeeklies bosses"""

    def __init__(self):
        options = [
            discord.SelectOption(label="UltraDage"),
            discord.SelectOption(label="UltraNulgath"),
            discord.SelectOption(label="UltraDarkon"),
            discord.SelectOption(label="UltraDrago"),
            discord.SelectOption(label="ChampionDrakath"),
            discord.SelectOption(label="UltraSpeaker"),
            discord.SelectOption(label="UltraGramiel"),
        ]
        super().__init__(
            placeholder="Choose UltraWeekly bosses...",
            min_values=1,
            max_values=7,
            options=options,
            custom_id="ultra_weeklies_select"
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            selected_bosses = self.values

            # Create confirmation embed for boss selection
            bosses_list = "\n".join(selected_bosses)

            confirm_embed = discord.Embed(
                title="Confirm Boss Selection",
                description="You selected the following bosses:",
                color=discord.Color.orange()
            )
            confirm_embed.add_field(name="Selected Bosses", value=bosses_list, inline=False)
            confirm_embed.set_footer(text="Click Confirm to continue or Cancel to select again")

            # Create confirmation view
            confirm_view = BossConfirmView(
                selected_bosses=selected_bosses,
                original_user=interaction.user
            )

            # Send confirmation message
            await interaction.response.send_message(
                embed=confirm_embed,
                view=confirm_view,
                ephemeral=True
            )

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class UltraWeekliesSelectView(ui.View):
    """View containing the UltraWeeklies dropdown selector"""

    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(UltraWeekliesSelect())


class UltraDailiesSelect(ui.Select):
    """Dropdown select menu for UltraDailies 4-Man bosses"""

    def __init__(self):
        options = [
            discord.SelectOption(label="UltraEzrajal"),
            discord.SelectOption(label="UltraWarden"),
            discord.SelectOption(label="UltraEngineer"),
            discord.SelectOption(label="UltraTyndarius"),
        ]
        super().__init__(
            placeholder="Choose UltraDaily 4-Man bosses...",
            min_values=1,
            max_values=4,
            options=options,
            custom_id="ultra_dailies_select"
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            selected_bosses = self.values

            # Create confirmation embed for boss selection
            bosses_list = "\n".join(selected_bosses)

            confirm_embed = discord.Embed(
                title="Confirm Boss Selection",
                description="You selected the following bosses:",
                color=discord.Color.orange()
            )
            confirm_embed.add_field(name="Selected Bosses", value=bosses_list, inline=False)
            confirm_embed.set_footer(text="Click Confirm to continue or Cancel to select again")

            # Create confirmation view
            confirm_view = DailiesBossConfirmView(
                selected_bosses=selected_bosses,
                original_user=interaction.user
            )

            # Send confirmation message
            await interaction.response.send_message(
                embed=confirm_embed,
                view=confirm_view,
                ephemeral=True
            )

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class DailiesBossConfirmView(ui.View):
    """Confirmation view for UltraDailies boss selection"""

    def __init__(self, selected_bosses, original_user):
        super().__init__(timeout=60)
        self.selected_bosses = selected_bosses
        self.original_user = original_user

    @ui.button(label="Confirm", style=discord.ButtonStyle.green, custom_id="confirm_dailies_bosses")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        # Only allow the original user to confirm
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message("Only the requester can confirm this.", ephemeral=True)
            return

        # Show server selection view
        server_view = ServerSelectView(self.selected_bosses, self.original_user, "UltraDailies4Man")
        await interaction.response.send_message(
            "**Select AQW Server:**",
            view=server_view,
            ephemeral=True
        )

    @ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel_dailies_bosses")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        # Only allow the original user to cancel
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message("Only the requester can cancel this.", ephemeral=True)
            return

        await interaction.response.send_message("Selection cancelled.", ephemeral=True)

        # Disable the buttons
        self.confirm_button.disabled = True
        self.cancel_button.disabled = True
        await interaction.message.edit(view=self)


class UltraDailiesModal(ui.Modal, title="UltraDailies 4-Man Request"):
    """Modal for collecting user information for UltraDailies"""

    ign = ui.TextInput(
        label="IGN (In-Game Name)",
        placeholder="Enter your character name",
        required=True,
        max_length=100
    )

    room_number = ui.TextInput(
        label="Room Number",
        placeholder="Enter 4-digit room number (e.g., 1234)",
        required=True,
        min_length=4,
        max_length=4
    )

    concerns = ui.TextInput(
        label="Any Concerns",
        placeholder="Enter any special requests or concerns (optional)",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    def __init__(self, selected_bosses, server):
        super().__init__()
        self.selected_bosses = selected_bosses
        self.server = server

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_ign = self.ign.value.strip()
            user_server = self.server  # Server now comes from dropdown selection
            user_room = self.room_number.value.strip()
            user_concerns = self.concerns.value.strip() if self.concerns.value else "None"

            # Validate room number is 4 digits
            if not user_room.isdigit() or len(user_room) != 4:
                await interaction.response.send_message("Room number must be exactly 4 digits!", ephemeral=True)
                return

            # Format join commands for each boss
            join_commands = []
            for boss in self.selected_bosses:
                join_commands.append(f"/join {boss}-{user_room}")

            # Create a private channel name based on username
            channel_name = f"daily-{interaction.user.name}-{user_room}".lower()
            channel_name = re.sub(r'[^a-z0-9-]', '', channel_name)

            # Get the guild
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Error: Could not find guild.", ephemeral=True)
                return

            # Create a text channel visible to everyone
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            # Defer the response first since channel creation takes time
            await interaction.response.defer(ephemeral=True)

            # Create the channel
            new_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites
            )

            # Create embed with all information
            embed = discord.Embed(
                title="UltraDailies 4-Man Request",
                color=discord.Color.blue()
            )
            embed.add_field(name="IGN", value=user_ign, inline=False)
            embed.add_field(name="Server", value=user_server, inline=False)
            embed.add_field(name="Join Commands", value="\n".join(join_commands), inline=False)
            embed.add_field(name="Concerns", value=user_concerns, inline=False)
            embed.add_field(name="Requested by", value=interaction.user.mention, inline=False)
            embed.timestamp = discord.utils.utcnow()

            # Create helper view with requester ID and selected bosses (max 3 helpers for 4-man)
            helper_view = DailiesHelperView(requester_id=interaction.user.id, selected_bosses=self.selected_bosses)

            # Track ticket creation
            track_ticket_created(interaction.user.id, "UltraDailies4Man", interaction.guild.id)

            # Send embed to the new channel with helper button
            await new_channel.send(embed=embed, view=helper_view)

            # Tag @Helper role to notify helpers
            helper_role = discord.utils.get(guild.roles, name="Helper")
            if helper_role:
                await new_channel.send(f"{helper_role.mention} New UltraDailies 4-Man ticket created!")
                print(f"Tagged @Helper role (ID: {helper_role.id}) in channel {new_channel.name}")
            else:
                # If Helper role doesn't exist, send a general notification
                await new_channel.send("@here New UltraDailies 4-Man ticket created!")
                print(f"WARNING: 'Helper' role not found in guild {guild.name}. Available roles: {[role.name for role in guild.roles]}")

            # Notify the user
            await interaction.followup.send(
                f"Channel created: {new_channel.mention}",
                ephemeral=True
            )

        except Exception as e:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class DailiesHelperView(ui.View):
    """View with I'll Help button for UltraDailies helpers"""

    def __init__(self, requester_id, selected_bosses):
        super().__init__(timeout=None)
        self.helpers = []
        self.max_helpers = 3  # 4-man content, so 3 helpers + requester
        self.requester_id = requester_id
        self.selected_bosses = selected_bosses
        self.ticket_completed = False
        self.replacements = []  # Track replacements: [{'left_id': int, 'left_mention': str, 'replacement_id': int, 'replacement_mention': str, 'bosses_covered': []}]

        # Update button label to show initial count
        for item in self.children:
            if isinstance(item, ui.Button) and item.custom_id == "dailies_helper_button":
                item.label = f"I'll Help (0/{self.max_helpers})"
                break

    @ui.button(label="I'll Help (0/3)", style=discord.ButtonStyle.success, custom_id="dailies_helper_button")
    async def help_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id
            user_mention = interaction.user.mention

            # Check if user is the requester
            if user_id == self.requester_id:
                await interaction.response.send_message("You cannot join as a helper for your own request!", ephemeral=True)
                return

            # Check if user already volunteered
            if user_id in [h[0] for h in self.helpers]:
                await interaction.response.send_message("You've already volunteered to help!", ephemeral=True)
                return

            # Check if max helpers reached
            if len(self.helpers) >= self.max_helpers:
                await interaction.response.send_message("Only 3 helpers allowed for 4-man content", ephemeral=True)
                return

            # Check if this is a replacement (someone left before and slot not filled)
            unfilled_replacement = None
            for replacement in self.replacements:
                if replacement['replacement_id'] is None:
                    unfilled_replacement = replacement
                    break

            # Add helper
            self.helpers.append((user_id, user_mention))

            # If this is a replacement, track it
            if unfilled_replacement:
                unfilled_replacement['replacement_id'] = user_id
                unfilled_replacement['replacement_mention'] = user_mention

            # Track ticket join
            track_ticket_join(user_id, interaction.guild.id)

            # Update the button label to show count
            for item in self.children:
                if isinstance(item, ui.Button) and item.custom_id in ["helper_button", "dailies_helper_button", "7man_helper_button"]:
                    item.label = f"I'll Help ({len(self.helpers)}/{self.max_helpers})"
                    break

            await interaction.response.edit_message(view=self)
            await interaction.followup.send(f"{user_mention} has joined as a helper! ({len(self.helpers)}/{self.max_helpers})")

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="Remove Helper", style=discord.ButtonStyle.danger, custom_id="remove_dailies_helper_button")
    async def remove_helper_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id

            # Check if user is requester or admin
            is_requester = user_id == self.requester_id
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_requester or is_admin):
                await interaction.response.send_message("Only the requester or admins can remove helpers!", ephemeral=True)
                return

            # Check if there are any helpers to remove
            if not self.helpers:
                await interaction.response.send_message("There are no helpers to remove!", ephemeral=True)
                return

            # Create a dropdown to select which helper to remove
            options = []
            for helper_id, _ in self.helpers:
                display_name = format_helper_display_name(interaction.client, interaction.guild, helper_id)
                options.append(discord.SelectOption(
                    label=display_name,
                    value=str(helper_id),
                    description=f"Remove {display_name}"
                ))

            select = ui.Select(
                placeholder="Select a helper to remove...",
                options=options,
                custom_id="select_dailies_helper_to_remove"
            )

            async def select_callback(select_interaction: discord.Interaction):
                try:
                    selected_helper_id = int(select.values[0])

                    # Find and remove the helper
                    removed_helper = None
                    for i, (helper_id, helper_mention) in enumerate(self.helpers):
                        if helper_id == selected_helper_id:
                            removed_helper = self.helpers.pop(i)
                            break

                    # Track this as a replacement (will be filled when someone joins)
                    if removed_helper:
                        self.replacements.append({
                            'left_id': removed_helper[0],
                            'left_mention': removed_helper[1],
                            'replacement_id': None,
                            'replacement_mention': None,
                            'bosses_covered': []
                        })

                    # Update the button label to show count
                    for item in self.children:
                        if isinstance(item, ui.Button) and item.custom_id in ["helper_button", "dailies_helper_button", "7man_helper_button"]:
                            item.label = f"I'll Help ({len(self.helpers)}/{self.max_helpers})" if self.helpers else "I'll Help"
                            break

                    await interaction.message.edit(view=self)

                    # Get removed helper's display name
                    removed_display_name = format_helper_display_name(select_interaction.client, interaction.guild, selected_helper_id)

                    # Tag @Helper role to notify helpers
                    helper_role = discord.utils.get(interaction.guild.roles, name="Helper")
                    role_mention = helper_role.mention if helper_role else "@here"
                    await interaction.channel.send(f"{role_mention} **{removed_display_name}** left! Requesting helpers please!")

                    await select_interaction.response.send_message("Helper removed successfully!", ephemeral=True)

                except Exception as e:
                    try:
                        await select_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
                    except:
                        pass

            select.callback = select_callback

            view = ui.View(timeout=60)
            view.add_item(select)

            await interaction.response.send_message("Select a helper to remove:", view=view, ephemeral=True)

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="Complete Ticket", style=discord.ButtonStyle.blurple, custom_id="complete_dailies_ticket_button")
    async def complete_ticket_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id

            # Check if user is requester or admin
            is_requester = user_id == self.requester_id
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_requester or is_admin):
                await interaction.response.send_message("Only the requester or admins can complete the ticket!", ephemeral=True)
                return

            # Check if ticket was already completed
            if self.ticket_completed:
                await interaction.response.send_message("This ticket has already been completed!", ephemeral=True)
                return

            # Check if there are any helpers
            if not self.helpers:
                await interaction.response.send_message("Cannot complete ticket - no helpers have joined!", ephemeral=True)
                return

            # Check if there are ANY replacements (people who left, regardless of whether they were replaced)
            if self.replacements:
                # Ask which bosses each PERSON WHO LEFT helped with (all of them, not just filled ones)
                view = ReplacementBossesView(self, interaction.message, button, self.replacements, interaction)
                await interaction.response.send_message(
                    f"There were {len(self.replacements)} helper(s) who left. Please specify which bosses each person who left helped with (select none if they didn't help any).",
                    view=view,
                    ephemeral=True
                )
                return

        # Calculate total points based on selected bosses
            total_points = sum(BOSS_POINTS.get(boss, 0) for boss in self.selected_bosses)

            # Award points to all helpers
            helper_rewards = []
            for helper_id, helper_mention in self.helpers:
                new_total = add_points(helper_id, total_points, self.selected_bosses, interaction.guild.id)
                helper_rewards.append(f"{helper_mention}: +{total_points} points (Total: {new_total})")

            # Mark ticket as completed
            self.ticket_completed = True

            # Disable the Complete Ticket button
            button.disabled = True
            await interaction.message.edit(view=self)

            # Create boss points breakdown
            # Create detailed completion summary
            boss_points_breakdown = []
            for boss in self.selected_bosses:
                points = BOSS_POINTS.get(boss, 0)
                boss_points_breakdown.append(f"**{boss}:** {points} points")

            completion_summary = "\n".join(boss_points_breakdown)
            completion_summary += f"\n\n**Total Points:** {total_points} per helper"

            # Create completion embed
            completion_embed = discord.Embed(
                title="✅ UltraDailies 4-Man Ticket Completed!",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )

            completion_embed.add_field(
                name="Requester",
                value=f"<@{self.requester_id}>",
                inline=False
            )

            completion_embed.add_field(
                name="Completion Summary",
                value=completion_summary,
                inline=False
            )

            completion_embed.add_field(
                name="Helper Rewards",
                value="\n".join(helper_rewards),
                inline=False
            )

            # Find the ticket-logs channel
            guild = interaction.guild
            ticket_logs_channel = discord.utils.get(guild.text_channels, name="ticket-logs")

            if ticket_logs_channel:
                # Send to ticket-logs channel
                await ticket_logs_channel.send(embed=completion_embed)
                await interaction.response.send_message("Ticket completed! Summary sent to ticket-logs. Channel will be deleted in 10 seconds.", ephemeral=True)

                # Wait 10 seconds then delete the channel
                await asyncio.sleep(10)
                try:
                    await interaction.channel.delete(reason="UltraDailies 4-Man ticket completed")
                except Exception as e:
                    logger.error(f"Error deleting channel: {e}")
            else:
                # Fallback: send in current channel if ticket-logs doesn't exist
                await interaction.response.send_message(embed=completion_embed, ephemeral=False)

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="Cancel Ticket", style=discord.ButtonStyle.danger, custom_id="cancel_dailies_ticket_button")
    async def cancel_ticket_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id

            # Check if user is requester or admin
            is_requester = user_id == self.requester_id
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_requester or is_admin):
                await interaction.response.send_message("Only the requester or admins can cancel the ticket!", ephemeral=True)
                return

            # Send cancellation message
            await interaction.response.send_message("Ticket cancelled. Channel will be deleted in 5 seconds.", ephemeral=True)

            # Wait 5 seconds then delete the channel
            await asyncio.sleep(5)
            try:
                await interaction.channel.delete(reason="UltraDailies 4-Man ticket cancelled")
            except Exception as e:
                logger.error(f"Error deleting channel: {e}")

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class UltraDailiesSelectView(ui.View):
    """View containing the UltraDailies dropdown selector"""

    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(UltraDailiesSelect())


class Ultra7ManSelect(ui.Select):
    """Dropdown select menu for UltraDailies 7-Man bosses"""

    def __init__(self):
        options = [
            discord.SelectOption(label="AstralShrine"),
            discord.SelectOption(label="KathoolDepths"),
            discord.SelectOption(label="ApexAzalith"),
            discord.SelectOption(label="VoidFlibbi"),
            discord.SelectOption(label="VoidNightbane"),
            discord.SelectOption(label="VoidXyfrag"),
            discord.SelectOption(label="Deimos"),
            discord.SelectOption(label="Sevencircleswar"),
            discord.SelectOption(label="Frozenlair"),
        ]
        super().__init__(
            placeholder="Choose UltraDaily 7-Man bosses...",
            min_values=1,
            max_values=9,
            options=options,
            custom_id="ultra_7man_select"
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            selected_bosses = self.values

            # Create confirmation embed for boss selection
            bosses_list = "\n".join(selected_bosses)

            confirm_embed = discord.Embed(
                title="Confirm Boss Selection",
                description="You selected the following bosses:",
                color=discord.Color.orange()
            )
            confirm_embed.add_field(name="Selected Bosses", value=bosses_list, inline=False)
            confirm_embed.set_footer(text="Click Confirm to continue or Cancel to select again")

            # Create confirmation view
            confirm_view = SevenManBossConfirmView(
                selected_bosses=selected_bosses,
                original_user=interaction.user
            )

            # Send confirmation message
            await interaction.response.send_message(
                embed=confirm_embed,
                view=confirm_view,
                ephemeral=True
            )

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class SevenManBossConfirmView(ui.View):
    """Confirmation view for UltraDailies 7-Man boss selection"""

    def __init__(self, selected_bosses, original_user):
        super().__init__(timeout=60)
        self.selected_bosses = selected_bosses
        self.original_user = original_user

    @ui.button(label="Confirm", style=discord.ButtonStyle.green, custom_id="confirm_7man_bosses")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        # Only allow the original user to confirm
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message("Only the requester can confirm this.", ephemeral=True)
            return

        # Show server selection view
        server_view = ServerSelectView(self.selected_bosses, self.original_user, "UltraDailies7Man")
        await interaction.response.send_message(
            "**Select AQW Server:**",
            view=server_view,
            ephemeral=True
        )

    @ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel_7man_bosses")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        # Only allow the original user to cancel
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message("Only the requester can cancel this.", ephemeral=True)
            return

        await interaction.response.send_message("Selection cancelled.", ephemeral=True)

        # Disable the buttons
        self.confirm_button.disabled = True
        self.cancel_button.disabled = True
        await interaction.message.edit(view=self)


class Ultra7ManModal(ui.Modal, title="UltraDailies 7-Man Request"):
    """Modal for collecting user information for UltraDailies 7-Man"""

    ign = ui.TextInput(
        label="IGN (In-Game Name)",
        placeholder="Enter your character name",
        required=True,
        max_length=100
    )

    room_number = ui.TextInput(
        label="Room Number",
        placeholder="Enter 4-digit room number (e.g., 1234)",
        required=True,
        min_length=4,
        max_length=4
    )

    concerns = ui.TextInput(
        label="Any Concerns",
        placeholder="Enter any special requests or concerns (optional)",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    def __init__(self, selected_bosses, server):
        super().__init__()
        self.selected_bosses = selected_bosses
        self.server = server

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_ign = self.ign.value.strip()
            user_server = self.server  # Server now comes from dropdown selection
            user_room = self.room_number.value.strip()
            user_concerns = self.concerns.value.strip() if self.concerns.value else "None"

            # Validate room number is 4 digits
            if not user_room.isdigit() or len(user_room) != 4:
                await interaction.response.send_message("Room number must be exactly 4 digits!", ephemeral=True)
                return

            # Format join commands for each boss
            join_commands = []
            for boss in self.selected_bosses:
                join_commands.append(f"/join {boss}-{user_room}")

            # Create a private channel name based on username
            channel_name = f"7man-{interaction.user.name}-{user_room}".lower()
            channel_name = re.sub(r'[^a-z0-9-]', '', channel_name)

            # Get the guild
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Error: Could not find guild.", ephemeral=True)
                return

            # Create a text channel visible to everyone
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            # Defer the response first since channel creation takes time
            await interaction.response.defer(ephemeral=True)

            # Create the channel
            new_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites
            )

            # Create embed with all information
            embed = discord.Embed(
                title="UltraDailies 7-Man Request",
                color=discord.Color.blue()
            )
            embed.add_field(name="IGN", value=user_ign, inline=False)
            embed.add_field(name="Server", value=user_server, inline=False)
            embed.add_field(name="Join Commands", value="\n".join(join_commands), inline=False)
            embed.add_field(name="Concerns", value=user_concerns, inline=False)
            embed.add_field(name="Requested by", value=interaction.user.mention, inline=False)
            embed.timestamp = discord.utils.utcnow()

            # Create helper view with requester ID and selected bosses (max 6 helpers for 7-man)
            helper_view = SevenManHelperView(requester_id=interaction.user.id, selected_bosses=self.selected_bosses)

            # Track ticket creation
            track_ticket_created(interaction.user.id, "UltraDailies7Man", interaction.guild.id)

            # Send embed to the new channel with helper button
            await new_channel.send(embed=embed, view=helper_view)

            # Tag @Helper role to notify helpers
            helper_role = discord.utils.get(guild.roles, name="Helper")
            if helper_role:
                await new_channel.send(f"{helper_role.mention} New UltraDailies 7-Man ticket created!")
                print(f"Tagged @Helper role (ID: {helper_role.id}) in channel {new_channel.name}")
            else:
                # If Helper role doesn't exist, send a general notification
                await new_channel.send("@here New UltraDailies 7-Man ticket created!")
                print(f"WARNING: 'Helper' role not found in guild {guild.name}. Available roles: {[role.name for role in guild.roles]}")

            # Notify the user
            await interaction.followup.send(
                f"Channel created: {new_channel.mention}",
                ephemeral=True
            )

        except Exception as e:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class SevenManHelperView(ui.View):
    """View with I'll Help button for UltraDailies 7-Man helpers"""

    def __init__(self, requester_id, selected_bosses):
        super().__init__(timeout=None)
        self.helpers = []
        self.max_helpers = 6  # 7-man content, so 6 helpers + requester
        self.requester_id = requester_id
        self.selected_bosses = selected_bosses
        self.ticket_completed = False
        self.replacements = []  # Track replacements: [{'left_id': int, 'left_mention': str, 'replacement_id': int, 'replacement_mention': str, 'bosses_covered': []}]

        # Update button label to show initial count
        for item in self.children:
            if isinstance(item, ui.Button) and item.custom_id == "7man_helper_button":
                item.label = f"I'll Help (0/{self.max_helpers})"
                break

    @ui.button(label="I'll Help (0/6)", style=discord.ButtonStyle.success, custom_id="7man_helper_button")
    async def help_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id
            user_mention = interaction.user.mention

            # Check if user is the requester
            if user_id == self.requester_id:
                await interaction.response.send_message("You cannot join as a helper for your own request!", ephemeral=True)
                return

            # Check if user already volunteered
            if user_id in [h[0] for h in self.helpers]:
                await interaction.response.send_message("You've already volunteered to help!", ephemeral=True)
                return

            # Check if max helpers reached
            if len(self.helpers) >= self.max_helpers:
                await interaction.response.send_message("Only 6 helpers allowed for 7-man content", ephemeral=True)
                return

            # Check if this is a replacement (someone left before and slot not filled)
            unfilled_replacement = None
            for replacement in self.replacements:
                if replacement['replacement_id'] is None:
                    unfilled_replacement = replacement
                    break

            # Add helper
            self.helpers.append((user_id, user_mention))

            # If this is a replacement, track it
            if unfilled_replacement:
                unfilled_replacement['replacement_id'] = user_id
                unfilled_replacement['replacement_mention'] = user_mention

            # Track ticket join
            track_ticket_join(user_id, interaction.guild.id)

            # Update the button label to show count
            for item in self.children:
                if isinstance(item, ui.Button) and item.custom_id in ["helper_button", "dailies_helper_button", "7man_helper_button"]:
                    item.label = f"I'll Help ({len(self.helpers)}/{self.max_helpers})"
                    break

            await interaction.response.edit_message(view=self)
            await interaction.followup.send(f"{user_mention} has joined as a helper! ({len(self.helpers)}/{self.max_helpers})")

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="Remove Helper", style=discord.ButtonStyle.danger, custom_id="remove_7man_helper_button")
    async def remove_helper_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id

            # Check if user is requester or admin
            is_requester = user_id == self.requester_id
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_requester or is_admin):
                await interaction.response.send_message("Only the requester or admins can remove helpers!", ephemeral=True)
                return

            # Check if there are any helpers to remove
            if not self.helpers:
                await interaction.response.send_message("There are no helpers to remove!", ephemeral=True)
                return

            # Create a dropdown to select which helper to remove
            options = []
            for helper_id, _ in self.helpers:
                display_name = format_helper_display_name(interaction.client, interaction.guild, helper_id)
                options.append(discord.SelectOption(
                    label=display_name,
                    value=str(helper_id),
                    description=f"Remove {display_name}"
                ))

            select = ui.Select(
                placeholder="Select a helper to remove...",
                options=options,
                custom_id="select_7man_helper_to_remove"
            )

            async def select_callback(select_interaction: discord.Interaction):
                try:
                    selected_helper_id = int(select.values[0])

                    # Find and remove the helper
                    removed_helper = None
                    for i, (helper_id, helper_mention) in enumerate(self.helpers):
                        if helper_id == selected_helper_id:
                            removed_helper = self.helpers.pop(i)
                            break

                    # Track this as a replacement (will be filled when someone joins)
                    if removed_helper:
                        self.replacements.append({
                            'left_id': removed_helper[0],
                            'left_mention': removed_helper[1],
                            'replacement_id': None,
                            'replacement_mention': None,
                            'bosses_covered': []
                        })

                    # Update the button label to show count
                    for item in self.children:
                        if isinstance(item, ui.Button) and item.custom_id in ["helper_button", "dailies_helper_button", "7man_helper_button"]:
                            item.label = f"I'll Help ({len(self.helpers)}/{self.max_helpers})" if self.helpers else "I'll Help"
                            break

                    await interaction.message.edit(view=self)

                    # Get removed helper's display name
                    removed_display_name = format_helper_display_name(select_interaction.client, interaction.guild, selected_helper_id)

                    # Tag @Helper role to notify helpers
                    helper_role = discord.utils.get(interaction.guild.roles, name="Helper")
                    role_mention = helper_role.mention if helper_role else "@here"
                    await interaction.channel.send(f"{role_mention} **{removed_display_name}** left! Requesting helpers please!")

                    await select_interaction.response.send_message("Helper removed successfully!", ephemeral=True)

                except Exception as e:
                    try:
                        await select_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
                    except:
                        pass

            select.callback = select_callback

            view = ui.View(timeout=60)
            view.add_item(select)

            await interaction.response.send_message("Select a helper to remove:", view=view, ephemeral=True)

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="Complete Ticket", style=discord.ButtonStyle.blurple, custom_id="complete_7man_ticket_button")
    async def complete_ticket_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id

            # Check if user is requester or admin
            is_requester = user_id == self.requester_id
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_requester or is_admin):
                await interaction.response.send_message("Only the requester or admins can complete the ticket!", ephemeral=True)
                return

            # Check if ticket was already completed
            if self.ticket_completed:
                await interaction.response.send_message("This ticket has already been completed!", ephemeral=True)
                return

            # Check if there are any helpers
            if not self.helpers:
                await interaction.response.send_message("Cannot complete ticket - no helpers have joined!", ephemeral=True)
                return

            # Check if there are ANY replacements (people who left, regardless of whether they were replaced)
            if self.replacements:
                # Ask which bosses each PERSON WHO LEFT helped with (all of them, not just filled ones)
                view = ReplacementBossesView(self, interaction.message, button, self.replacements, interaction)
                await interaction.response.send_message(
                    f"There were {len(self.replacements)} helper(s) who left. Please specify which bosses each person who left helped with (select none if they didn't help any).",
                    view=view,
                    ephemeral=True
                )
                return

        # Calculate total points based on selected bosses
            total_points = sum(BOSS_POINTS.get(boss, 0) for boss in self.selected_bosses)

            # Award points to all helpers
            helper_rewards = []
            for helper_id, helper_mention in self.helpers:
                new_total = add_points(helper_id, total_points, self.selected_bosses, interaction.guild.id)
                helper_rewards.append(f"{helper_mention}: +{total_points} points (Total: {new_total})")

            # Mark ticket as completed
            self.ticket_completed = True

            # Disable the Complete Ticket button
            button.disabled = True
            await interaction.message.edit(view=self)

            # Create boss points breakdown
            # Create detailed completion summary
            boss_points_breakdown = []
            for boss in self.selected_bosses:
                points = BOSS_POINTS.get(boss, 0)
                boss_points_breakdown.append(f"**{boss}:** {points} points")

            completion_summary = "\n".join(boss_points_breakdown)
            completion_summary += f"\n\n**Total Points:** {total_points} per helper"

            # Create completion embed
            completion_embed = discord.Embed(
                title="✅ UltraDailies 7-Man Ticket Completed!",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )

            completion_embed.add_field(
                name="Requester",
                value=f"<@{self.requester_id}>",
                inline=False
            )

            completion_embed.add_field(
                name="Completion Summary",
                value=completion_summary,
                inline=False
            )

            completion_embed.add_field(
                name="Helper Rewards",
                value="\n".join(helper_rewards),
                inline=False
            )

            # Find the ticket-logs channel
            guild = interaction.guild
            ticket_logs_channel = discord.utils.get(guild.text_channels, name="ticket-logs")

            if ticket_logs_channel:
                # Send to ticket-logs channel
                await ticket_logs_channel.send(embed=completion_embed)
                await interaction.response.send_message("Ticket completed! Summary sent to ticket-logs. Channel will be deleted in 10 seconds.", ephemeral=True)

                # Wait 10 seconds then delete the channel
                await asyncio.sleep(10)
                try:
                    await interaction.channel.delete(reason="UltraDailies 7-Man ticket completed")
                except Exception as e:
                    logger.error(f"Error deleting channel: {e}")
            else:
                # Fallback: send in current channel if ticket-logs doesn't exist
                await interaction.response.send_message(embed=completion_embed, ephemeral=False)

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="Cancel Ticket", style=discord.ButtonStyle.danger, custom_id="cancel_7man_ticket_button")
    async def cancel_ticket_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id

            # Check if user is requester or admin
            is_requester = user_id == self.requester_id
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_requester or is_admin):
                await interaction.response.send_message("Only the requester or admins can cancel the ticket!", ephemeral=True)
                return

            # Send cancellation message
            await interaction.response.send_message("Ticket cancelled. Channel will be deleted in 5 seconds.", ephemeral=True)

            # Wait 5 seconds then delete the channel
            await asyncio.sleep(5)
            try:
                await interaction.channel.delete(reason="UltraDailies 7-Man ticket cancelled")
            except Exception as e:
                logger.error(f"Error deleting channel: {e}")

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class Ultra7ManSelectView(ui.View):
    """View containing the UltraDailies 7-Man dropdown selector"""

    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(Ultra7ManSelect())


# TempleShrine System Classes
class TempleShrineModeSel(ui.View):
    """View to select between Dailies and Spamming modes"""

    def __init__(self):
        super().__init__(timeout=180)

    @ui.button(label="Dailies", style=discord.ButtonStyle.primary, custom_id="temple_dailies_button")
    async def dailies_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            await interaction.response.send_message(
                "**Select Temple Shrine Side(s):**",
                view=TempleShrineSideSelectView(),
                ephemeral=True
            )
        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="Spamming", style=discord.ButtonStyle.success, custom_id="temple_spamming_button")
    async def spamming_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            await interaction.response.send_message(
                "**Select Temple Shrine Side(s) for Spamming:**",
                view=TempleShrineSpammingSideSelectView(),
                ephemeral=True
            )
        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class TempleShrineSideSelect(ui.Select):
    """Dropdown for selecting TempleShrine sides (for Dailies)"""

    def __init__(self):
        options = [
            discord.SelectOption(label="Left Side"),
            discord.SelectOption(label="Right Side"),
            discord.SelectOption(label="Middle Side"),
        ]
        super().__init__(
            placeholder="Choose side(s)...",
            min_values=1,
            max_values=3,
            options=options,
            custom_id="temple_side_select"
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            selected_sides = self.values

            # Create confirmation embed
            sides_list = "\n".join(selected_sides)

            confirm_embed = discord.Embed(
                title="Confirm Side Selection",
                description="You selected the following side(s):",
                color=discord.Color.orange()
            )
            confirm_embed.add_field(name="Selected Sides", value=sides_list, inline=False)
            confirm_embed.set_footer(text="Click Confirm to continue or Cancel to select again")

            # Create confirmation view
            confirm_view = TempleShrineSideConfirmView(
                selected_sides=selected_sides,
                original_user=interaction.user
            )

            await interaction.response.send_message(
                embed=confirm_embed,
                view=confirm_view,
                ephemeral=True
            )

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class TempleShrineSpammingSideSelect(ui.Select):
    """Dropdown for selecting TempleShrine sides (for Spamming)"""

    def __init__(self):
        options = [
            discord.SelectOption(label="Left Side"),
            discord.SelectOption(label="Right Side"),
            discord.SelectOption(label="Middle Side"),
        ]
        super().__init__(
            placeholder="Choose side(s) for spamming...",
            min_values=1,
            max_values=3,
            options=options,
            custom_id="temple_spam_side_select"
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            selected_sides = self.values

            # Create confirmation embed
            sides_list = "\n".join(selected_sides)

            confirm_embed = discord.Embed(
                title="Confirm Side Selection",
                description="You selected the following side(s) for spamming:",
                color=discord.Color.purple()
            )
            confirm_embed.add_field(name="Selected Sides", value=sides_list, inline=False)
            confirm_embed.set_footer(text="Click Confirm to continue or Cancel to select again")

            # Create confirmation view
            confirm_view = TempleShrineSpammingSideConfirmView(
                selected_sides=selected_sides,
                original_user=interaction.user
            )

            await interaction.response.send_message(
                embed=confirm_embed,
                view=confirm_view,
                ephemeral=True
            )

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class TempleShrineSideSelectView(ui.View):
    """View containing the side selector for Dailies"""

    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(TempleShrineSideSelect())


class TempleShrineSpammingSideSelectView(ui.View):
    """View containing the side selector for Spamming"""

    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(TempleShrineSpammingSideSelect())


class TempleShrineSideConfirmView(ui.View):
    """Confirmation view for side selection (Dailies)"""

    def __init__(self, selected_sides, original_user):
        super().__init__(timeout=60)
        self.selected_sides = selected_sides
        self.original_user = original_user

    @ui.button(label="Confirm", style=discord.ButtonStyle.green, custom_id="confirm_temple_sides")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message("Only the requester can confirm this.", ephemeral=True)
            return

        # Show server selection view
        server_view = ServerSelectView(self.selected_sides, self.original_user, "TempleShrineDailies")
        await interaction.response.send_message(
            "**Select AQW Server:**",
            view=server_view,
            ephemeral=True
        )

    @ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel_temple_sides")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message("Only the requester can cancel this.", ephemeral=True)
            return

        await interaction.response.send_message("Selection cancelled.", ephemeral=True)
        self.confirm_button.disabled = True
        self.cancel_button.disabled = True
        await interaction.message.edit(view=self)


class TempleShrineSpammingSideConfirmView(ui.View):
    """Confirmation view for side selection (Spamming)"""

    def __init__(self, selected_sides, original_user):
        super().__init__(timeout=60)
        self.selected_sides = selected_sides
        self.original_user = original_user

    @ui.button(label="Confirm", style=discord.ButtonStyle.green, custom_id="confirm_temple_spam_sides")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message("Only the requester can confirm this.", ephemeral=True)
            return

        # Show server selection view
        server_view = ServerSelectView(self.selected_sides, self.original_user, "TempleShrineSpamming")
        await interaction.response.send_message(
            "**Select AQW Server:**",
            view=server_view,
            ephemeral=True
        )

    @ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel_temple_spam_sides")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message("Only the requester can cancel this.", ephemeral=True)
            return

        await interaction.response.send_message("Selection cancelled.", ephemeral=True)
        self.confirm_button.disabled = True
        self.cancel_button.disabled = True
        await interaction.message.edit(view=self)


class TempleShrineDailiesModal(ui.Modal, title="TempleShrine Dailies Request"):
    """Modal for Dailies mode"""

    ign = ui.TextInput(
        label="IGN (In-Game Name)",
        placeholder="Enter your character name",
        required=True,
        max_length=100
    )

    room_number = ui.TextInput(
        label="Room Number",
        placeholder="Enter 4-digit room number (e.g., 1234)",
        required=True,
        min_length=4,
        max_length=4
    )

    concerns = ui.TextInput(
        label="Any Concerns",
        placeholder="Enter any special requests or concerns (optional)",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    def __init__(self, selected_sides, server):
        super().__init__()
        self.selected_sides = selected_sides
        self.server = server

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_ign = self.ign.value.strip()
            user_server = self.server  # Server now comes from dropdown selection
            user_room = self.room_number.value.strip()
            user_concerns = self.concerns.value.strip() if self.concerns.value else "None"

            if not user_room.isdigit() or len(user_room) != 4:
                await interaction.response.send_message("Room number must be exactly 4 digits!", ephemeral=True)
                return

            # Determine boss key for points
            if len(self.selected_sides) == 3:
                boss_key = "TempleShrine-All"
            else:
                boss_key = [f"TempleShrine-{side.replace(' Side', '')}" for side in self.selected_sides]

            channel_name = f"temple-{interaction.user.name}-{user_room}".lower()
            channel_name = re.sub(r'[^a-z0-9-]', '', channel_name)

            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Error: Could not find guild.", ephemeral=True)
                return

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            await interaction.response.defer(ephemeral=True)

            new_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites
            )

            # Create embed
            embed = discord.Embed(
                title="TempleShrine Dailies Request",
                color=discord.Color.blue()
            )
            embed.add_field(name="IGN", value=user_ign, inline=False)
            embed.add_field(name="Server", value=user_server, inline=False)
            embed.add_field(name="Room", value=f"/join templeshrine-{user_room}", inline=False)

            # Add selected sides
            if len(self.selected_sides) == 3:
                sides_text = "All Sides (Left, Right, Middle)"
            else:
                sides_text = ", ".join(self.selected_sides)
            embed.add_field(name="Selected Sides", value=sides_text, inline=False)

            embed.add_field(name="Concerns", value=user_concerns, inline=False)
            embed.add_field(name="Requested by", value=interaction.user.mention, inline=False)
            embed.timestamp = discord.utils.utcnow()

            # Create helper view
            helper_view = TempleShrineHelperView(
                requester_id=interaction.user.id,
                selected_sides=self.selected_sides,
                boss_key=boss_key,
                mode="dailies"
            )

            # Track ticket creation
            track_ticket_created(interaction.user.id, "TempleShrineDailies", interaction.guild.id)

            await new_channel.send(embed=embed, view=helper_view)

            helper_role = discord.utils.get(guild.roles, name="Helper")
            if helper_role:
                await new_channel.send(f"{helper_role.mention} New TempleShrine Dailies ticket created!")
            else:
                await new_channel.send("@here New TempleShrine Dailies ticket created!")

            await interaction.followup.send(f"Channel created: {new_channel.mention}", ephemeral=True)

        except Exception as e:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class TempleShrineSpammingModal(ui.Modal, title="TempleShrine Spamming Request"):
    """Modal for Spamming mode"""

    ign = ui.TextInput(
        label="IGN (In-Game Name)",
        placeholder="Enter your character name",
        required=True,
        max_length=100
    )

    room_number = ui.TextInput(
        label="Room Number",
        placeholder="Enter 4-digit room number (e.g., 1234)",
        required=True,
        min_length=4,
        max_length=4
    )

    kill_count = ui.TextInput(
        label="Expected Kill Count",
        placeholder="How many kills are you planning? (e.g., 10)",
        required=True,
        max_length=4
    )

    concerns = ui.TextInput(
        label="Any Concerns",
        placeholder="Enter any special requests or concerns (optional)",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    def __init__(self, selected_sides, server):
        super().__init__()
        self.selected_sides = selected_sides
        self.server = server

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_ign = self.ign.value.strip()
            user_server = self.server  # Server now comes from dropdown selection
            user_room = self.room_number.value.strip()
            user_kill_count = self.kill_count.value.strip()
            user_concerns = self.concerns.value.strip() if self.concerns.value else "None"

            if not user_room.isdigit() or len(user_room) != 4:
                await interaction.response.send_message("Room number must be exactly 4 digits!", ephemeral=True)
                return

            if not user_kill_count.isdigit():
                await interaction.response.send_message("Kill count must be a number!", ephemeral=True)
                return

            channel_name = f"temple-spam-{interaction.user.name}-{user_room}".lower()
            channel_name = re.sub(r'[^a-z0-9-]', '', channel_name)

            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Error: Could not find guild.", ephemeral=True)
                return

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            await interaction.response.defer(ephemeral=True)

            new_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites
            )

            embed = discord.Embed(
                title="TempleShrine Spamming Request",
                color=discord.Color.purple()
            )
            embed.add_field(name="IGN", value=user_ign, inline=False)
            embed.add_field(name="Server", value=user_server, inline=False)
            embed.add_field(name="Room", value=f"/join templeshrine-{user_room}", inline=False)

            # Add selected sides
            if len(self.selected_sides) == 3:
                sides_text = "All Sides (Left, Right, Middle)"
            else:
                sides_text = ", ".join(self.selected_sides)
            embed.add_field(name="Selected Sides", value=sides_text, inline=False)

            embed.add_field(name="Expected Kills", value=user_kill_count, inline=False)
            embed.add_field(name="Concerns", value=user_concerns, inline=False)
            embed.add_field(name="Requested by", value=interaction.user.mention, inline=False)
            embed.timestamp = discord.utils.utcnow()

            helper_view = TempleShrineHelperView(
                requester_id=interaction.user.id,
                selected_sides=self.selected_sides,
                boss_key="spamming",
                mode="spamming"
            )

            # Track ticket creation
            track_ticket_created(interaction.user.id, "TempleShrineSpamming", interaction.guild.id)

            await new_channel.send(embed=embed, view=helper_view)

            helper_role = discord.utils.get(guild.roles, name="Helper")
            if helper_role:
                await new_channel.send(f"{helper_role.mention} New TempleShrine Spamming ticket created!")
            else:
                await new_channel.send("@here New TempleShrine Spamming ticket created!")

            await interaction.followup.send(f"Channel created: {new_channel.mention}", ephemeral=True)

        except Exception as e:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class TempleShrineHelperView(ui.View):
    """Helper view for TempleShrine tickets"""

    def __init__(self, requester_id, selected_sides, boss_key, mode="dailies"):
        super().__init__(timeout=None)
        self.helpers = []
        self.max_helpers = 3
        self.requester_id = requester_id
        self.selected_sides = selected_sides
        self.boss_key = boss_key
        self.mode = mode
        self.ticket_completed = False
        self.replacements = []  # Track replacements: [{'left_id': int, 'left_mention': str, 'replacement_id': int, 'replacement_mention': str, 'sides_covered': []}]

        # Update button label to show initial count
        for item in self.children:
            if isinstance(item, ui.Button) and item.custom_id == "temple_helper_button":
                item.label = f"I'll Help (0/{self.max_helpers})"
                break

    @ui.button(label="I'll Help (0/3)", style=discord.ButtonStyle.success, custom_id="temple_helper_button")
    async def help_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id
            user_mention = interaction.user.mention

            if user_id == self.requester_id:
                await interaction.response.send_message("You cannot join as a helper for your own request!", ephemeral=True)
                return

            if user_id in [h[0] for h in self.helpers]:
                await interaction.response.send_message("You've already volunteered to help!", ephemeral=True)
                return

            if len(self.helpers) >= self.max_helpers:
                await interaction.response.send_message("Maximum helpers reached!", ephemeral=True)
                return

            # Check if this is a replacement (someone left before and slot not filled)
            unfilled_replacement = None
            for replacement in self.replacements:
                if replacement['replacement_id'] is None:
                    unfilled_replacement = replacement
                    break

            self.helpers.append((user_id, user_mention))

            # If this is a replacement, track it
            if unfilled_replacement:
                unfilled_replacement['replacement_id'] = user_id
                unfilled_replacement['replacement_mention'] = user_mention

            track_ticket_join(user_id, interaction.guild.id)

            # Update the button label to show count
            for item in self.children:
                if isinstance(item, ui.Button) and item.custom_id == "temple_helper_button":
                    item.label = f"I'll Help ({len(self.helpers)}/{self.max_helpers})"
                    break

            await interaction.response.edit_message(view=self)
            await interaction.followup.send(f"{user_mention} has joined as a helper! ({len(self.helpers)}/{self.max_helpers})")

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="Remove Helper", style=discord.ButtonStyle.danger, custom_id="remove_temple_helper_button")
    async def remove_helper_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id
            is_requester = user_id == self.requester_id
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_requester or is_admin):
                await interaction.response.send_message("Only the requester or admins can remove helpers!", ephemeral=True)
                return

            if not self.helpers:
                await interaction.response.send_message("There are no helpers to remove!", ephemeral=True)
                return

            # Create dropdown to select which helper to remove
            options = []
            for helper_id, _ in self.helpers:
                display_name = format_helper_display_name(interaction.client, interaction.guild, helper_id)
                options.append(discord.SelectOption(
                    label=display_name,
                    value=str(helper_id),
                    description=f"Remove {display_name}"
                ))

            select = ui.Select(
                placeholder="Select a helper to remove...",
                options=options,
                custom_id="select_temple_helper_to_remove"
            )

            async def select_callback(select_interaction: discord.Interaction):
                try:
                    selected_helper_id = int(select.values[0])

                    # For spamming mode, show kill count modal per side
                    if self.mode == "spamming":
                        modal = RemoveHelperSpammingModal(self, interaction.message, selected_helper_id, self.selected_sides)
                        await select_interaction.response.send_modal(modal)
                    else:
                        # For dailies mode, show sides selection view
                        dailies_view = RemoveHelperDailiesView(
                            self,
                            interaction.message,
                            selected_helper_id,
                            self.selected_sides
                        )
                        await select_interaction.response.send_message(
                            "Select which sides were completed:",
                            view=dailies_view,
                            ephemeral=True
                        )

                except Exception as e:
                    try:
                        await select_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
                    except:
                        pass

            select.callback = select_callback

            view = ui.View(timeout=60)
            view.add_item(select)

            await interaction.response.send_message("Select a helper to remove:", view=view, ephemeral=True)

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="Complete Ticket", style=discord.ButtonStyle.blurple, custom_id="complete_temple_ticket_button")
    async def complete_ticket_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id
            is_requester = user_id == self.requester_id
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_requester or is_admin):
                await interaction.response.send_message("Only the requester or admins can complete the ticket!", ephemeral=True)
                return

            if self.ticket_completed:
                await interaction.response.send_message("This ticket has already been completed!", ephemeral=True)
                return

            if not self.helpers:
                await interaction.response.send_message("Cannot complete ticket - no helpers have joined!", ephemeral=True)
                return

            if self.mode == "spamming":
                # For spamming mode - check if there are replacements
                if self.replacements:
                    # Ask for kill counts for each person who left
                    view = ReplacementKillCountView(self, interaction.message, button, self.replacements, self.selected_sides, interaction)
                    await interaction.response.send_message(
                        f"There were {len(self.replacements)} helper(s) who left. Please specify kill counts for each person who left.",
                        view=view,
                        ephemeral=True
                    )
                    return

                # No replacements - ask for total kill counts
                modal = CompleteSpammingModal(self, interaction.message, button, self.selected_sides)
                await interaction.response.send_modal(modal)
            else:
                # For dailies mode - check if there are replacements
                if self.replacements:
                    # Ask which sides each person who left helped with
                    view = ReplacementSidesView(self, interaction.message, button, self.replacements, interaction)
                    await interaction.response.send_message(
                        f"There were {len(self.replacements)} helper(s) who left. Please specify which sides each person who left helped with (select none if they didn't help any).",
                        view=view,
                        ephemeral=True
                    )
                    return

                # No replacements - simple completion
                if isinstance(self.boss_key, list):
                    # Partial sides
                    total_points = sum(BOSS_POINTS.get(key, 0) for key in self.boss_key)
                    boss_names = self.boss_key
                else:
                    # All sides
                    total_points = BOSS_POINTS.get(self.boss_key, 0)
                    boss_names = [self.boss_key]

                helper_rewards = []
                for helper_id, helper_mention in self.helpers:
                    new_total = add_points(helper_id, total_points, boss_names, interaction.guild.id)
                    helper_rewards.append(f"{helper_mention}: +{total_points} points (Total: {new_total})")

                self.ticket_completed = True
                button.disabled = True
                await interaction.message.edit(view=self)

                # Create detailed completion summary
                if isinstance(self.boss_key, list):
                    sides_breakdown = "\n".join([f"**{key}:** {BOSS_POINTS.get(key, 0)} points" for key in self.boss_key])
                else:
                    sides_breakdown = f"**All Sides:** {total_points} points"

                completion_summary = sides_breakdown + f"\n\n**Total Points:** {total_points} per helper"

                completion_embed = discord.Embed(
                    title="✅ TempleShrine Dailies Ticket Completed!",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )

                completion_embed.add_field(name="Requester", value=f"<@{self.requester_id}>", inline=False)
                completion_embed.add_field(name="Completion Summary", value=completion_summary, inline=False)
                completion_embed.add_field(name="Helper Rewards", value="\n".join(helper_rewards), inline=False)

                guild = interaction.guild
                ticket_logs_channel = discord.utils.get(guild.text_channels, name="ticket-logs")

                if ticket_logs_channel:
                    await ticket_logs_channel.send(embed=completion_embed)
                    await interaction.response.send_message("Ticket completed! Summary sent to ticket-logs. Channel will be deleted in 10 seconds.", ephemeral=True)
                    await asyncio.sleep(10)
                    try:
                        await interaction.channel.delete(reason="TempleShrine ticket completed")
                    except Exception as e:
                        logger.error(f"Error deleting channel: {e}")
                else:
                    await interaction.response.send_message(embed=completion_embed, ephemeral=False)

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="Cancel Ticket", style=discord.ButtonStyle.danger, custom_id="cancel_temple_ticket_button")
    async def cancel_ticket_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user_id = interaction.user.id
            is_requester = user_id == self.requester_id
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_requester or is_admin):
                await interaction.response.send_message("Only the requester or admins can cancel the ticket!", ephemeral=True)
                return

            await interaction.response.send_message("Ticket cancelled. Channel will be deleted in 5 seconds.", ephemeral=True)
            await asyncio.sleep(5)
            try:
                await interaction.channel.delete(reason="TempleShrine ticket cancelled")
            except Exception as e:
                logger.error(f"Error deleting channel: {e}")

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class RemoveHelperSpammingModal(ui.Modal, title="Remove Helper - Spamming"):
    """Modal to input kills per side for Spamming mode removal"""

    def __init__(self, helper_view, message, selected_helper_id, available_sides):
        super().__init__()
        self.helper_view = helper_view
        self.message = message
        self.selected_helper_id = selected_helper_id
        self.available_sides = available_sides

        # Create text inputs for each side
        for side in available_sides:
            side_name = side.replace(" Side", "")
            text_input = ui.TextInput(
                label=f"{side_name} Side Kills",
                placeholder=f"How many {side_name} kills? (0 if none)",
                required=True,
                max_length=4,
                default="0"
            )
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Parse kill counts from text inputs
            side_kills = {}
            total_kills = 0

            for i, side in enumerate(self.available_sides):
                side_name = side.replace(" Side", "")
                kill_value = self.children[i].value.strip()

                if not kill_value.isdigit():
                    await interaction.response.send_message(f"{side_name} kill count must be a number!", ephemeral=True)
                    return

                kills = int(kill_value)
                side_kills[side_name] = kills
                total_kills += kills

            # Find helper by selected ID
            helper_to_remove = None
            for helper_id, helper_mention in self.helper_view.helpers:
                if helper_id == self.selected_helper_id:
                    helper_to_remove = (helper_id, helper_mention)
                    break

            if not helper_to_remove:
                await interaction.response.send_message(f"Could not find the selected helper!", ephemeral=True)
                return

            # Award points based on kills per side (Left/Right = 1pt, Middle = 2pts)
            total_points = 0
            boss_names = []

            if total_kills > 0:
                for side_name, kills in side_kills.items():
                    if kills > 0:
                        boss_key = f"TempleShrine-{side_name}"
                        points_per_kill = BOSS_POINTS.get(boss_key, 1)
                        side_points = kills * points_per_kill
                        total_points += side_points
                        # Add boss names for tracking
                        boss_names.extend([boss_key] * kills)

                add_points(helper_to_remove[0], total_points, boss_names, interaction.guild.id)

            # Remove helper from list
            self.helper_view.helpers.remove(helper_to_remove)

            # Track this as a replacement (will be filled when someone joins)
            self.helper_view.replacements.append({
                'left_id': helper_to_remove[0],
                'left_mention': helper_to_remove[1],
                'replacement_id': None,
                'replacement_mention': None,
                'sides_covered': side_kills,  # Track kill counts per side for spamming mode
                'kills_by_left': side_kills   # Also store as kills_by_left for completion compatibility
            })

            # Update the button label to show count
            for item in self.helper_view.children:
                if isinstance(item, ui.Button) and item.custom_id == "temple_helper_button":
                    item.label = f"I'll Help ({len(self.helper_view.helpers)}/{self.helper_view.max_helpers})" if self.helper_view.helpers else "I'll Help"
                    break

            await self.message.edit(view=self.helper_view)

            removed_display_name = format_helper_display_name(interaction.client, interaction.guild, helper_to_remove[0])

            if total_kills > 0:
                # Build breakdown message
                breakdown = ", ".join([f"{side_name}: {kills}" for side_name, kills in side_kills.items() if kills > 0])

                await interaction.response.send_message(
                    f"Helper removed! **{removed_display_name}** completed {total_kills} kill(s) ({breakdown}) and earned {total_points} points.",
                    ephemeral=False
                )
                # Tag @Helper role to notify helpers
                helper_role = discord.utils.get(interaction.guild.roles, name="Helper")
                role_mention = helper_role.mention if helper_role else "@here"
                await interaction.channel.send(f"{role_mention} **{removed_display_name}** left! Requesting helpers please!")
            else:
                await interaction.response.send_message("Helper removed successfully!", ephemeral=True)
                # Tag @Helper role to notify helpers
                helper_role = discord.utils.get(interaction.guild.roles, name="Helper")
                role_mention = helper_role.mention if helper_role else "@here"
                await interaction.channel.send(f"{role_mention} **{removed_display_name}** left! Requesting helpers please!")

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class RemoveHelperDailiesView(ui.View):
    """View to select which sides were completed for Dailies mode"""

    def __init__(self, helper_view, message, selected_helper_id, available_sides):
        super().__init__(timeout=60)
        self.helper_view = helper_view
        self.message = message
        self.selected_helper_id = selected_helper_id
        self.available_sides = available_sides

        # Create dropdown with available sides
        options = []
        for side in available_sides:
            side_name = side.replace(" Side", "")
            boss_key = f"TempleShrine-{side_name}"
            points = BOSS_POINTS.get(boss_key, 1)
            options.append(discord.SelectOption(
                label=side,
                value=side,
                description=f"{points} point(s)"
            ))

        select = ui.Select(
            placeholder="Select which sides were completed...",
            options=options,
            min_values=0,  # Allow selecting none (if they completed 0)
            max_values=len(options)  # Allow selecting all available sides
        )
        select.callback = self.sides_selected
        self.add_item(select)

    async def sides_selected(self, interaction: discord.Interaction):
        """Handle side selection and award points"""
        try:
            selected_sides = interaction.data['values']

            # Find helper by selected ID
            helper_to_remove = None
            for helper_id, helper_mention in self.helper_view.helpers:
                if helper_id == self.selected_helper_id:
                    helper_to_remove = (helper_id, helper_mention)
                    break

            if not helper_to_remove:
                await interaction.response.send_message(f"Could not find the selected helper!", ephemeral=True)
                return

            # Award points based on completed sides
            points = 0
            boss_names = []

            if len(selected_sides) > 0:
                for side in selected_sides:
                    side_name = side.replace(" Side", "")
                    boss_key = f"TempleShrine-{side_name}"
                    side_points = BOSS_POINTS.get(boss_key, 0)
                    points += side_points
                    boss_names.append(boss_key)

                if boss_names:
                    add_points(helper_to_remove[0], points, boss_names, interaction.guild.id)

            # Remove helper from list
            self.helper_view.helpers.remove(helper_to_remove)

            # Track this as a replacement (will be filled when someone joins)
            self.helper_view.replacements.append({
                'left_id': helper_to_remove[0],
                'left_mention': helper_to_remove[1],
                'replacement_id': None,
                'replacement_mention': None,
                'sides_covered': list(selected_sides)  # Track which sides the person who left completed
            })

            # Update the button label to show count
            for item in self.helper_view.children:
                if isinstance(item, ui.Button) and item.custom_id == "temple_helper_button":
                    item.label = f"I'll Help ({len(self.helper_view.helpers)}/{self.helper_view.max_helpers})" if self.helper_view.helpers else "I'll Help"
                    break

            await self.message.edit(view=self.helper_view)

            removed_display_name = format_helper_display_name(interaction.client, interaction.guild, helper_to_remove[0])

            if len(selected_sides) > 0:
                sides_list = ", ".join(selected_sides)
                await interaction.response.send_message(
                    f"Helper removed! **{removed_display_name}** completed {sides_list} and earned {points} point(s).",
                    ephemeral=False
                )
            else:
                await interaction.response.send_message(
                    f"Helper removed! **{removed_display_name}** completed 0 sides.",
                    ephemeral=True
                )

            # Tag @Helper role to notify helpers
            helper_role = discord.utils.get(interaction.guild.roles, name="Helper")
            role_mention = helper_role.mention if helper_role else "@here"
            await interaction.channel.send(f"{role_mention} **{removed_display_name}** left! Requesting helpers please!")

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class CompleteSpammingModal(ui.Modal, title="Complete Spamming Ticket"):
    """Modal to input kill count per side for spamming completion"""

    def __init__(self, helper_view, message, button, available_sides):
        super().__init__()
        self.helper_view = helper_view
        self.message = message
        self.button = button
        self.available_sides = available_sides

        # Create text inputs for each side
        for side in available_sides:
            side_name = side.replace(" Side", "")
            text_input = ui.TextInput(
                label=f"{side_name} Side Kills",
                placeholder=f"How many {side_name} kills completed?",
                required=True,
                max_length=4,
                default="0"
            )
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Parse kill counts from text inputs
            side_kills = {}
            total_kills = 0

            for i, side in enumerate(self.available_sides):
                side_name = side.replace(" Side", "")
                kill_value = self.children[i].value.strip()

                if not kill_value.isdigit():
                    await interaction.response.send_message(f"{side_name} kill count must be a number!", ephemeral=True)
                    return

                kills = int(kill_value)
                side_kills[side_name] = kills
                total_kills += kills

            # Calculate points based on side (Left/Right = 1pt, Middle = 2pts)
            total_points = 0
            boss_names = []

            for side_name, kills in side_kills.items():
                if kills > 0:
                    boss_key = f"TempleShrine-{side_name}"
                    points_per_kill = BOSS_POINTS.get(boss_key, 1)
                    side_points = kills * points_per_kill
                    total_points += side_points
                    # Add boss names for tracking
                    boss_names.extend([boss_key] * kills)

            helper_rewards = []
            for helper_id, helper_mention in self.helper_view.helpers:
                new_total = add_points(helper_id, total_points, boss_names, interaction.guild.id)
                helper_rewards.append(f"{helper_mention}: +{total_points} points (Total: {new_total})")

            self.helper_view.ticket_completed = True
            self.button.disabled = True
            await self.message.edit(view=self.helper_view)

            # Build detailed completion summary with kill and point breakdown
            completion_summary_lines = []
            for side_name, kills in side_kills.items():
                if kills > 0:
                    boss_key = f"TempleShrine-{side_name}"
                    points_per_kill = BOSS_POINTS.get(boss_key, 1)
                    side_points = kills * points_per_kill
                    completion_summary_lines.append(f"**{side_name} Side:** {kills} kills × {points_per_kill}pt = {side_points} points")

            completion_summary = "\n".join(completion_summary_lines)
            completion_summary += f"\n\n**Total:** {total_kills} kills = {total_points} points per helper"

            completion_embed = discord.Embed(
                title="✅ TempleShrine Spamming Ticket Completed!",
                color=discord.Color.purple(),
                timestamp=discord.utils.utcnow()
            )

            completion_embed.add_field(name="Requester", value=f"<@{self.helper_view.requester_id}>", inline=False)
            completion_embed.add_field(name="Completion Summary", value=completion_summary, inline=False)
            completion_embed.add_field(name="Helper Rewards", value="\n".join(helper_rewards), inline=False)

            guild = interaction.guild
            ticket_logs_channel = discord.utils.get(guild.text_channels, name="ticket-logs")

            if ticket_logs_channel:
                await ticket_logs_channel.send(embed=completion_embed)
                await interaction.response.send_message("Ticket completed! Summary sent to ticket-logs. Channel will be deleted in 10 seconds.", ephemeral=True)
                await asyncio.sleep(10)
                try:
                    await interaction.channel.delete(reason="TempleShrine Spamming ticket completed")
                except Exception as e:
                    logger.error(f"Error deleting channel: {e}")
            else:
                await interaction.response.send_message(embed=completion_embed, ephemeral=False)

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class ReplacementSidesView(ui.View):
    """View to ask which sides each replacement covered for TempleShrine Dailies"""

    def __init__(self, helper_view, message, button, replacements_with_ids, interaction=None):
        super().__init__(timeout=120)
        self.helper_view = helper_view
        self.message = message
        self.button = button
        self.replacements_with_ids = replacements_with_ids
        self.current_index = 0
        self.initial_interaction = interaction

        # Get available sides from helper_view
        if isinstance(helper_view.boss_key, list):
            self.available_sides = helper_view.boss_key
        else:
            # Convert TempleShrine-All to individual sides
            if helper_view.boss_key == "TempleShrine-All":
                self.available_sides = ["TempleShrine-Left", "TempleShrine-Right", "TempleShrine-Middle"]
            else:
                self.available_sides = [helper_view.boss_key]

        if len(self.replacements_with_ids) > 0:
            self._add_current_replacement_select()

    def _add_current_replacement_select(self, interaction=None):
        """Add dropdown for current helper who left"""
        self.clear_items()

        replacement = self.replacements_with_ids[self.current_index]
        left_id = replacement['left_id']
        active_interaction = interaction or self.initial_interaction

        if active_interaction and active_interaction.guild:
            left_name = format_helper_display_name(active_interaction.client, active_interaction.guild, left_id)
        else:
            left_name = replacement['left_mention']

        # Create dropdown with all available sides
        options = []
        for side_key in self.available_sides:
            side_display = side_key.replace("TempleShrine-", "") + " Side"
            points = BOSS_POINTS.get(side_key, 0)
            options.append(discord.SelectOption(
                label=side_display,
                value=side_key,
                description=f"{points} points"
            ))

        select = ui.Select(
            placeholder=f"Which sides did {left_name} help with?",
            options=options,
            min_values=0,
            max_values=len(options)
        )
        select.callback = self._sides_selected
        self.add_item(select)

    async def _sides_selected(self, interaction: discord.Interaction):
        """Handle side selection for person who left"""
        selected_sides = list(interaction.data['values'])
        self.replacements_with_ids[self.current_index]['sides_covered_by_left'] = selected_sides

        # Now ask who replaced them
        self._add_replacement_helper_select(interaction)
        await interaction.response.edit_message(
            content=f"Helper who left {self.current_index + 1} of {len(self.replacements_with_ids)}: Who replaced them?",
            view=self
        )

    def _add_replacement_helper_select(self, interaction):
        """Add dropdown to select who replaced this person"""
        self.clear_items()

        replacement = self.replacements_with_ids[self.current_index]
        left_id = replacement['left_id']
        left_name = format_helper_display_name(interaction.client, interaction.guild, left_id)

        # Collect helpers who have already been assigned as replacements
        already_assigned = set()
        for i in range(self.current_index):
            prev_replacement = self.replacements_with_ids[i]
            if prev_replacement.get('replacement_id') is not None:
                already_assigned.add(prev_replacement['replacement_id'])

        # Create dropdown with current helpers
        options = []
        for helper_id, helper_mention in self.helper_view.helpers:
            if helper_id in already_assigned:
                continue

            helper_display = format_helper_display_name(interaction.client, interaction.guild, helper_id)
            options.append(discord.SelectOption(
                label=helper_display,
                value=str(helper_id),
                description=f"Replaced {left_name}"
            ))

        options.append(discord.SelectOption(
            label="No one replaced them",
            value="none",
            description="Slot never filled, filled by non-member, or public player"
        ))

        select = ui.Select(
            placeholder=f"Who replaced {left_name}?",
            options=options,
            min_values=1,
            max_values=1
        )
        select.callback = self._replacement_helper_selected
        self.add_item(select)

    async def _replacement_helper_selected(self, interaction: discord.Interaction):
        """Handle selection of who replaced the person who left"""
        selected_value = interaction.data['values'][0]

        if selected_value == "none":
            self.replacements_with_ids[self.current_index]['replacement_id'] = None
            self.replacements_with_ids[self.current_index]['replacement_mention'] = "No one"
        else:
            selected_id = int(selected_value)
            for helper_id, helper_mention in self.helper_view.helpers:
                if helper_id == selected_id:
                    self.replacements_with_ids[self.current_index]['replacement_id'] = helper_id
                    self.replacements_with_ids[self.current_index]['replacement_mention'] = helper_mention
                    break

        # Move to next person who left
        self.current_index += 1

        if self.current_index < len(self.replacements_with_ids):
            self._add_current_replacement_select()
            await interaction.response.edit_message(
                content=f"Helper who left {self.current_index + 1} of {len(self.replacements_with_ids)}",
                view=self
            )
        else:
            await interaction.response.edit_message(
                content="Processing ticket completion...",
                view=None
            )
            await self._complete_ticket_with_replacements(interaction)

    async def _complete_ticket_with_replacements(self, interaction: discord.Interaction):
        """Complete ticket with replacement tracking - Award points based on who covered what"""
        all_sides = set(self.available_sides)
        people_who_left = {}
        replacement_rewards = {}
        helpers_with_replacements = set()

        # Step 1: Process each person who left
        for replacement in self.replacements_with_ids:
            left_id = replacement['left_id']
            left_mention = replacement['left_mention']
            sides_covered_by_left = set(replacement.get('sides_covered_by_left', []))
            replacement_id = replacement.get('replacement_id')

            # Award points to person who left
            left_points = sum(BOSS_POINTS.get(side, 0) for side in sides_covered_by_left)

            if left_points > 0 or len(sides_covered_by_left) > 0:
                new_total = add_points(left_id, left_points, list(sides_covered_by_left), interaction.guild.id)
                people_who_left[left_id] = {
                    'mention': left_mention,
                    'sides_covered': list(sides_covered_by_left),
                    'points': left_points,
                    'new_total': new_total
                }

            # Award remaining sides to the REPLACEMENT
            if replacement_id is not None:
                helpers_with_replacements.add(replacement_id)
                remaining_sides_for_this_slot = all_sides - sides_covered_by_left
                remaining_points_for_this_slot = sum(BOSS_POINTS.get(side, 0) for side in remaining_sides_for_this_slot)

                if replacement_id not in replacement_rewards:
                    replacement_rewards[replacement_id] = {'points': 0, 'sides': set()}

                replacement_rewards[replacement_id]['points'] += remaining_points_for_this_slot
                replacement_rewards[replacement_id]['sides'].update(remaining_sides_for_this_slot)

        # Step 2: Award points to helpers
        helper_rewards = []
        for helper_id, helper_mention in self.helper_view.helpers:
            if helper_id in replacement_rewards:
                reward_info = replacement_rewards[helper_id]
                points = reward_info['points']
                sides = list(reward_info['sides'])
                new_total = add_points(helper_id, points, sides, interaction.guild.id)
                helper_rewards.append(f"{helper_mention}: +{points} points (Total: {new_total})")
            else:
                # This helper was NOT a replacement - award ALL sides
                total_points = sum(BOSS_POINTS.get(side, 0) for side in all_sides)
                new_total = add_points(helper_id, total_points, list(all_sides), interaction.guild.id)
                helper_rewards.append(f"{helper_mention}: +{total_points} points (Total: {new_total})")

        # Add people who left to helper rewards
        for left_id, left_info in people_who_left.items():
            helper_rewards.append(f"{left_info['mention']}: +{left_info['points']} points (Total: {left_info['new_total']}) [Left mid-run]")

        # Build detailed breakdown
        sides_points_breakdown = []
        for side in self.available_sides:
            side_display = side.replace("TempleShrine-", "") + " Side"
            points = BOSS_POINTS.get(side, 0)
            sides_points_breakdown.append(f"**{side_display}:** {points} points")

        completion_summary = "\n".join(sides_points_breakdown)

        # Add info about people who left and their replacements
        if self.replacements_with_ids:
            completion_summary += "\n\n**Replacements:**"
            for repl in self.replacements_with_ids:
                left_id = repl['left_id']
                left_name = repl['left_mention']
                repl_name = repl['replacement_mention']
                sides_covered_by_left = repl.get('sides_covered_by_left', [])

                if sides_covered_by_left:
                    sides_str = ", ".join([s.replace("TempleShrine-", "") + " Side" for s in sides_covered_by_left])
                    left_points = sum(BOSS_POINTS.get(s, 0) for s in sides_covered_by_left)
                    completion_summary += f"\n• {repl_name} replaced {left_name}"
                    completion_summary += f"\n  ↳ {left_name} helped with: {sides_str} ({left_points}pts)"
                else:
                    completion_summary += f"\n• {repl_name} replaced {left_name}"
                    completion_summary += f"\n  ↳ {left_name} left before helping (0pts)"

        # Mark ticket as completed
        self.helper_view.ticket_completed = True
        self.button.disabled = True
        await self.message.edit(view=self.helper_view)

        # Create completion embed
        completion_embed = discord.Embed(
            title="✅ TempleShrine Dailies Ticket Completed!",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )

        completion_embed.add_field(name="Requester", value=f"<@{self.helper_view.requester_id}>", inline=False)
        completion_embed.add_field(name="Completion Summary", value=completion_summary, inline=False)
        completion_embed.add_field(name="Helper Rewards", value="\n".join(helper_rewards), inline=False)

        guild = interaction.guild
        ticket_logs_channel = discord.utils.get(guild.text_channels, name="ticket-logs")

        if ticket_logs_channel:
            await ticket_logs_channel.send(embed=completion_embed)
            await interaction.followup.send("Ticket completed! Summary sent to ticket-logs. Channel will be deleted in 10 seconds.", ephemeral=True)
            await asyncio.sleep(10)
            try:
                await interaction.channel.delete(reason="TempleShrine Dailies ticket completed")
            except Exception as e:
                logger.error(f"Error deleting channel: {e}")
        else:
            await interaction.followup.send(embed=completion_embed, ephemeral=False)


class ReplacementKillCountView(ui.View):
    """View to ask for kill counts for each person who left in TempleShrine Spamming"""

    def __init__(self, helper_view, message, button, replacements_with_ids, selected_sides, interaction=None):
        super().__init__(timeout=120)
        self.helper_view = helper_view
        self.message = message
        self.button = button
        self.replacements_with_ids = replacements_with_ids
        self.selected_sides = selected_sides
        self.current_index = 0
        self.initial_interaction = interaction

        if len(self.replacements_with_ids) > 0:
            self._add_start_button()

    def _add_start_button(self):
        """Add button to start entering kill counts for person who left, or skip if already entered"""
        self.clear_items()

        replacement = self.replacements_with_ids[self.current_index]
        left_id = replacement['left_id']

        if self.initial_interaction and self.initial_interaction.guild:
            left_name = format_helper_display_name(self.initial_interaction.client, self.initial_interaction.guild, left_id)
        else:
            left_name = replacement['left_mention']

        # Check if kill counts already exist (entered during removal)
        if 'kills_by_left' in replacement and replacement['kills_by_left']:
            # Skip kill count entry, go straight to asking who replaced them
            button = ui.Button(
                label=f"Select replacement for {left_name}",
                style=discord.ButtonStyle.success
            )
            button.callback = self._skip_to_replacement_select
        else:
            # Need to enter kill counts
            button = ui.Button(
                label=f"Enter kills for {left_name}",
                style=discord.ButtonStyle.primary
            )
            button.callback = self._show_kill_count_modal

        self.add_item(button)

    async def _skip_to_replacement_select(self, interaction: discord.Interaction):
        """Skip kill count entry and go straight to replacement selection"""
        await self._show_replacement_helper_select(interaction)
        await interaction.response.edit_message(
            content=f"Helper who left {self.current_index + 1} of {len(self.replacements_with_ids)}: Who replaced them?",
            view=self
        )

    async def _show_kill_count_modal(self, interaction: discord.Interaction):
        """Show modal to enter kill counts for person who left"""
        replacement = self.replacements_with_ids[self.current_index]
        left_id = replacement['left_id']
        left_name = format_helper_display_name(interaction.client, interaction.guild, left_id)

        modal = ReplacementKillCountModal(self, replacement, left_name, self.selected_sides, interaction)
        await interaction.response.send_modal(modal)

    async def _show_replacement_helper_select(self, interaction):
        """Add dropdown to select who replaced this person"""
        self.clear_items()

        replacement = self.replacements_with_ids[self.current_index]
        left_id = replacement['left_id']
        left_name = format_helper_display_name(interaction.client, interaction.guild, left_id)

        # Collect helpers who have already been assigned as replacements
        already_assigned = set()
        for i in range(self.current_index):
            prev_replacement = self.replacements_with_ids[i]
            if prev_replacement.get('replacement_id') is not None:
                already_assigned.add(prev_replacement['replacement_id'])

        # Create dropdown with current helpers
        options = []
        for helper_id, helper_mention in self.helper_view.helpers:
            if helper_id in already_assigned:
                continue

            helper_display = format_helper_display_name(interaction.client, interaction.guild, helper_id)
            options.append(discord.SelectOption(
                label=helper_display,
                value=str(helper_id),
                description=f"Replaced {left_name}"
            ))

        options.append(discord.SelectOption(
            label="No one replaced them",
            value="none",
            description="Slot never filled, filled by non-member, or public player"
        ))

        select = ui.Select(
            placeholder=f"Who replaced {left_name}?",
            options=options,
            min_values=1,
            max_values=1
        )
        select.callback = self._replacement_helper_selected
        self.add_item(select)

    async def _replacement_helper_selected(self, interaction: discord.Interaction):
        """Handle selection of who replaced the person who left"""
        selected_value = interaction.data['values'][0]

        if selected_value == "none":
            self.replacements_with_ids[self.current_index]['replacement_id'] = None
            self.replacements_with_ids[self.current_index]['replacement_mention'] = "No one"
        else:
            selected_id = int(selected_value)
            for helper_id, helper_mention in self.helper_view.helpers:
                if helper_id == selected_id:
                    self.replacements_with_ids[self.current_index]['replacement_id'] = helper_id
                    self.replacements_with_ids[self.current_index]['replacement_mention'] = helper_mention
                    break

        # Move to next person who left
        self.current_index += 1

        if self.current_index < len(self.replacements_with_ids):
            self._add_start_button()
            await interaction.response.edit_message(
                content=f"Helper who left {self.current_index + 1} of {len(self.replacements_with_ids)}",
                view=self
            )
        else:
            # All people who left processed, now ask for final total kill counts
            await interaction.response.edit_message(
                content="Now enter the TOTAL kill counts for the entire run:",
                view=None
            )
            # Show modal for total kill counts
            modal = CompleteTotalKillCountModal(self, self.selected_sides)
            await interaction.followup.send("Enter total kill counts:", ephemeral=True)
            # We need to trigger this differently - let me use a button instead
            view = ui.View(timeout=60)
            button = ui.Button(label="Enter Total Kill Counts", style=discord.ButtonStyle.success)

            async def show_total_modal(btn_interaction):
                total_modal = CompleteTotalKillCountModal(self, self.selected_sides)
                await btn_interaction.response.send_modal(total_modal)

            button.callback = show_total_modal
            view.add_item(button)
            await interaction.followup.send("Click to enter total kill counts:", view=view, ephemeral=True)


class ReplacementKillCountModal(ui.Modal, title="Kill Counts"):
    """Modal to input kill counts for person who left"""

    def __init__(self, parent_view, replacement, left_name, available_sides, interaction):
        super().__init__()
        self.title = f"Kills for {left_name}"
        self.parent_view = parent_view
        self.replacement = replacement
        self.left_name = left_name
        self.available_sides = available_sides
        self.interaction = interaction

        # Create text inputs for each side
        for side in available_sides:
            side_name = side.replace(" Side", "")
            text_input = ui.TextInput(
                label=f"{side_name} Side Kills",
                placeholder=f"How many {side_name} kills? (0 if none)",
                required=True,
                max_length=4,
                default="0"
            )
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Parse kill counts
            side_kills = {}
            for i, side in enumerate(self.available_sides):
                side_name = side.replace(" Side", "")
                kill_value = self.children[i].value.strip()

                if not kill_value.isdigit():
                    await interaction.response.send_message(f"{side_name} kill count must be a number!", ephemeral=True)
                    return

                kills = int(kill_value)
                side_kills[side_name] = kills

            # Store kill counts for this person who left
            self.replacement['kills_by_left'] = side_kills

            # Now show dropdown to select who replaced them
            await self.parent_view._show_replacement_helper_select(self.interaction)
            await interaction.response.edit_message(
                content=f"Helper who left {self.parent_view.current_index + 1} of {len(self.parent_view.replacements_with_ids)}: Who replaced them?",
                view=self.parent_view
            )

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class CompleteTotalKillCountModal(ui.Modal, title="Total Kill Counts"):
    """Modal to input TOTAL kill counts for the entire spamming run"""

    def __init__(self, parent_view, available_sides):
        super().__init__()
        self.parent_view = parent_view
        self.available_sides = available_sides

        # Create text inputs for each side
        for side in available_sides:
            side_name = side.replace(" Side", "")
            text_input = ui.TextInput(
                label=f"{side_name} Side Total Kills",
                placeholder=f"Total {side_name} kills completed?",
                required=True,
                max_length=4,
                default="0"
            )
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Parse total kill counts
            total_side_kills = {}
            for i, side in enumerate(self.available_sides):
                side_name = side.replace(" Side", "")
                kill_value = self.children[i].value.strip()

                if not kill_value.isdigit():
                    await interaction.response.send_message(f"{side_name} kill count must be a number!", ephemeral=True)
                    return

                kills = int(kill_value)
                total_side_kills[side_name] = kills

            # Now complete the ticket with replacement tracking
            await interaction.response.send_message("Processing ticket completion...", ephemeral=True)
            await self._complete_ticket_with_replacements(interaction, total_side_kills)

        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    async def _complete_ticket_with_replacements(self, interaction: discord.Interaction, total_side_kills):
        """Complete ticket with replacement tracking for spamming mode"""
        people_who_left = {}
        replacement_rewards = {}
        helpers_with_replacements = set()

        # Step 1: Process each person who left
        for replacement in self.parent_view.replacements_with_ids:
            left_id = replacement['left_id']
            left_mention = replacement['left_mention']
            kills_by_left = replacement.get('kills_by_left', {})
            replacement_id = replacement.get('replacement_id')

            # Award points to person who left based on their kills
            left_points = 0
            boss_names = []
            for side_name, kills in kills_by_left.items():
                if kills > 0:
                    boss_key = f"TempleShrine-{side_name}"
                    points_per_kill = BOSS_POINTS.get(boss_key, 1)
                    side_points = kills * points_per_kill
                    left_points += side_points
                    boss_names.extend([boss_key] * kills)

            if left_points > 0:
                new_total = add_points(left_id, left_points, boss_names, interaction.guild.id)
                people_who_left[left_id] = {
                    'mention': left_mention,
                    'kills': kills_by_left,
                    'points': left_points,
                    'new_total': new_total
                }

            # Calculate remaining kills for the replacement
            if replacement_id is not None:
                helpers_with_replacements.add(replacement_id)
                remaining_kills = {}
                remaining_points = 0
                remaining_boss_names = []

                for side_name, total_kills in total_side_kills.items():
                    left_kills = kills_by_left.get(side_name, 0)
                    remaining = total_kills - left_kills
                    if remaining > 0:
                        remaining_kills[side_name] = remaining
                        boss_key = f"TempleShrine-{side_name}"
                        points_per_kill = BOSS_POINTS.get(boss_key, 1)
                        side_points = remaining * points_per_kill
                        remaining_points += side_points
                        remaining_boss_names.extend([boss_key] * remaining)

                if replacement_id not in replacement_rewards:
                    replacement_rewards[replacement_id] = {'points': 0, 'boss_names': []}

                replacement_rewards[replacement_id]['points'] += remaining_points
                replacement_rewards[replacement_id]['boss_names'].extend(remaining_boss_names)

        # Step 2: Award points to helpers
        helper_rewards = []
        for helper_id, helper_mention in self.parent_view.helper_view.helpers:
            if helper_id in replacement_rewards:
                # This helper replaced someone - award only remaining kills
                reward_info = replacement_rewards[helper_id]
                points = reward_info['points']
                boss_names = reward_info['boss_names']
                new_total = add_points(helper_id, points, boss_names, interaction.guild.id)
                helper_rewards.append(f"{helper_mention}: +{points} points (Total: {new_total})")
            else:
                # This helper was NOT a replacement - award ALL kills
                total_points = 0
                all_boss_names = []
                for side_name, kills in total_side_kills.items():
                    if kills > 0:
                        boss_key = f"TempleShrine-{side_name}"
                        points_per_kill = BOSS_POINTS.get(boss_key, 1)
                        side_points = kills * points_per_kill
                        total_points += side_points
                        all_boss_names.extend([boss_key] * kills)

                new_total = add_points(helper_id, total_points, all_boss_names, interaction.guild.id)
                helper_rewards.append(f"{helper_mention}: +{total_points} points (Total: {new_total})")

        # Add people who left to helper rewards
        for left_id, left_info in people_who_left.items():
            helper_rewards.append(f"{left_info['mention']}: +{left_info['points']} points (Total: {left_info['new_total']}) [Left mid-run]")

        # Build completion summary
        total_kills = sum(total_side_kills.values())
        total_points = 0
        completion_summary_lines = []

        for side_name, kills in total_side_kills.items():
            if kills > 0:
                boss_key = f"TempleShrine-{side_name}"
                points_per_kill = BOSS_POINTS.get(boss_key, 1)
                side_points = kills * points_per_kill
                total_points += side_points
                completion_summary_lines.append(f"**{side_name} Side:** {kills} kills × {points_per_kill}pt = {side_points} points")

        completion_summary = "\n".join(completion_summary_lines)
        completion_summary += f"\n\n**Total:** {total_kills} kills"

        # Add replacement info
        if self.parent_view.replacements_with_ids:
            completion_summary += "\n\n**Replacements:**"
            for repl in self.parent_view.replacements_with_ids:
                left_name = repl['left_mention']
                repl_name = repl['replacement_mention']
                kills_by_left = repl.get('kills_by_left', {})

                if any(k > 0 for k in kills_by_left.values()):
                    kills_str = ", ".join([f"{side}: {kills}" for side, kills in kills_by_left.items() if kills > 0])
                    left_points = sum(BOSS_POINTS.get(f"TempleShrine-{s}", 1) * k for s, k in kills_by_left.items())
                    completion_summary += f"\n• {repl_name} replaced {left_name}"
                    completion_summary += f"\n  ↳ {left_name} completed: {kills_str} ({left_points}pts)"
                else:
                    completion_summary += f"\n• {repl_name} replaced {left_name}"
                    completion_summary += f"\n  ↳ {left_name} left before helping (0pts)"

        # Mark ticket as completed
        self.parent_view.helper_view.ticket_completed = True
        self.parent_view.button.disabled = True
        await self.parent_view.message.edit(view=self.parent_view.helper_view)

        # Create completion embed
        completion_embed = discord.Embed(
            title="✅ TempleShrine Spamming Ticket Completed!",
            color=discord.Color.purple(),
            timestamp=discord.utils.utcnow()
        )

        completion_embed.add_field(name="Requester", value=f"<@{self.parent_view.helper_view.requester_id}>", inline=False)
        completion_embed.add_field(name="Completion Summary", value=completion_summary, inline=False)
        completion_embed.add_field(name="Helper Rewards", value="\n".join(helper_rewards), inline=False)

        guild = interaction.guild
        ticket_logs_channel = discord.utils.get(guild.text_channels, name="ticket-logs")

        if ticket_logs_channel:
            await ticket_logs_channel.send(embed=completion_embed)
            await interaction.followup.send("Ticket completed! Summary sent to ticket-logs. Channel will be deleted in 10 seconds.", ephemeral=True)
            await asyncio.sleep(10)
            try:
                await interaction.channel.delete(reason="TempleShrine Spamming ticket completed")
            except Exception as e:
                logger.error(f"Error deleting channel: {e}")
        else:
            await interaction.followup.send(embed=completion_embed, ephemeral=False)


class UltraWeekliesView(ui.View):
    """View with UltraWeeklies and UltraDailies buttons for ticket reminders"""

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="UltraWeeklies", style=discord.ButtonStyle.primary, custom_id="ultra_weeklies_button")
    async def ultra_weeklies_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            # Send a message with the dropdown selector
            await interaction.response.send_message(
                "**Select an UltraWeekly Boss:**",
                view=UltraWeekliesSelectView(),
                ephemeral=True
            )
        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="UltraDailies 4-Man", style=discord.ButtonStyle.primary, custom_id="ultra_dailies_button")
    async def ultra_dailies_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            # Send a message with the dropdown selector
            await interaction.response.send_message(
                "**Select an UltraDaily 4-Man Boss:**",
                view=UltraDailiesSelectView(),
                ephemeral=True
            )
        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="UltraDailies 7-Man", style=discord.ButtonStyle.primary, custom_id="ultra_7man_button")
    async def ultra_7man_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            # Send a message with the dropdown selector
            await interaction.response.send_message(
                "**Select an UltraDaily 7-Man Boss:**",
                view=Ultra7ManSelectView(),
                ephemeral=True
            )
        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass

    @ui.button(label="TempleShrine", style=discord.ButtonStyle.primary, custom_id="temple_shrine_button")
    async def temple_shrine_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            # Send mode selection view
            await interaction.response.send_message(
                "**Select TempleShrine Mode:**",
                view=TempleShrineModeSel(),
                ephemeral=True
            )
        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


@bot.tree.command(name="deployticket")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(channel="The channel to send the ticket reminders embed to")
async def deployticket_command(interaction: discord.Interaction, channel: discord.TextChannel):
    """Deploy ticket reminders embed to a specific channel (Admin only)"""
    try:
        embed = discord.Embed(
            title="📌 Reminders",
            description=(
                "I-mention o i-screenshot mo ang mga tumulong sa ticket mo once na tapos na, "
                "at panatilihing updated ang ticket status.\n\n"
                "**SAFIRIA** ang best na Server. Huwag sa **ARTIX**.\n\n"
                "If gusto mong mag-practice o matuto, mag-create ka ng **SPAMMING** ticket at "
                "i-indicate mo na lang kung anong type of tulong ang kailangan mo sa description.\n\n"
                "Lahat ng ticket ay dapat sa **PRIVATE room lang**. Except ang SPAM/Others ticket "
                "na puwede sa pub, lalo na kapag walang masyadong helper.\n\n"
                "**4-man** and **7-man** dailies/weekly ay **SEPARATE TICKETS**.\n\n"
                "Kapag hindi sumunod sa mga rules, mabibigyan ng **WARN**. "
                "**3 WARNS** will temporarily remove your ticket privileges.\n\n"
                "May tanong? Mag-**ASK**.\n"
                "**NO PREMADE PARTIES ALLOWED.**"
            ),
            color=discord.Color.gold()
        )

        view = UltraWeekliesView()

        # Send to the specified channel
        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ Ticket reminders embed deployed to {channel.mention}", ephemeral=True)
    except Exception as e:
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
        except:
            pass


@bot.tree.command(
    name='wiki',
    description='Get detailed information about an item from the AQW Wiki')
@app_commands.describe(
    query='Item name, class, or page (e.g., "Void Highlord", "Malgor\'s Blade")'
)
async def wiki(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    try:
        # Scrape wiki page for details
        wiki_data = await scrape_wiki_page(query)

        if not wiki_data:
            # Page not found, provide simple link
            wiki_link = create_wiki_link(query)
            url_match = re.search(r'\(([^)]+)\)', wiki_link)
            wiki_url = url_match.group(
                1) if url_match else f"http://aqwwiki.wikidot.com"

            embed = discord.Embed(
                title=f"❌ Page Not Found: {query}",
                description=
                f"Could not find a wiki page for '{query}'.\n\nTry searching manually: {wiki_link}",
                color=discord.Color.orange())
            await interaction.followup.send(embed=embed)
            return

        # Check if this is a disambiguation page with related items
        related_items = wiki_data.get('related_items', [])
        if related_items:
            # Create disambiguation embed
            title = wiki_data.get('title', query)
            url = wiki_data.get('url', '')
            member_only = wiki_data.get('member_only', False)
            ac_only = wiki_data.get('ac_only', False)

            decorated_title = _decorate_title(title, member_only, ac_only)

            embed = discord.Embed(title=decorated_title,
                                  url=url,
                                  color=discord.Color.blue())


            description = wiki_data.get('description')
            if description:
                if len(description) > 200:
                    description = description[:197] + "..."
                embed.description = description

            # Show related items list in the embed
            related_list = []
            for item in related_items[:10]:
                related_list.append(f"• {item['name']}")

            embed.add_field(name="📋 Multiple items found:",
                            value='\n'.join(related_list),
                            inline=False)

            embed.set_footer(
                text="Use the dropdown menu below to view item details")

            view = WikiDisambiguationView(related_items)
            await interaction.followup.send(embed=embed, view=view)
            return

        # Fetch merge requirements if shop is present
        shop = wiki_data.get('shop')
        if shop:
            shop_name = shop.split(' - ')[0].strip() if ' - ' in shop else shop
            shop_data = await scrape_shop_items(shop_name)
            if shop_data and shop_data.get('items'):
                # Find this specific item in the shop to get merge requirements
                for item in shop_data['items']:
                    if wiki_data['title'] in item.get('name', ''):
                        wiki_data['merge_requirements'] = item.get('price')
                        break

        # Create embed
        embed = await create_wiki_embed(wiki_data)

        # Add interactive buttons for quest if present
        view = ItemDetailsView(wiki_data) if wiki_data.get('quest') else None

        if view:
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f'Error fetching wiki data: {e}')
        import traceback
        traceback.print_exc()

        await interaction.followup.send(
            f'An error occurred while fetching wiki data: {str(e)}')


@bot.tree.command(name="leaderboard")
async def leaderboard_command(interaction: discord.Interaction):
    """View the top helpers leaderboard for this server"""
    try:
        all_points_data = load_points()

        # Get this guild's data
        guild_id_str = str(interaction.guild.id)
        guild_data = all_points_data.get(guild_id_str, {})
        points_data = guild_data.get("users", {})

        if not points_data:
            await interaction.response.send_message("No helper data yet! Be the first to help with tickets.", ephemeral=True)
            return

        # Build list of (user_id, total_points, tickets_completed)
        leaderboard_data = []
        for user_id_str, data in points_data.items():
            if isinstance(data, dict):
                total_points = data.get("total_points", 0)
                tickets_completed = data.get("tickets_completed", 0)
            else:
                # Old format (just a number)
                total_points = data
                tickets_completed = 0

            if total_points > 0:
                leaderboard_data.append((user_id_str, total_points, tickets_completed))

        if not leaderboard_data:
            await interaction.response.send_message("No one has earned points yet! Be the first to help with tickets.", ephemeral=True)
            return

        # Sort by total points descending
        leaderboard_data.sort(key=lambda x: x[1], reverse=True)

        # Take top 10
        top_10 = leaderboard_data[:10]

        # Build embed
        embed = discord.Embed(
            title=f"Helper Leaderboard - {interaction.guild.name}",
            description="Top helpers ranked by total points in this server",
            color=discord.Color.gold()
        )

        # Build leaderboard text
        leaderboard_text = []
        medals = ["🥇", "🥈", "🥉"]

        for i, (user_id_str, points, tickets) in enumerate(top_10):
            rank = i + 1
            if rank <= 3:
                rank_display = medals[rank - 1]
            else:
                rank_display = f"**{rank}.**"

            leaderboard_text.append(f"{rank_display} <@{user_id_str}> - **{points}** pts ({tickets} tickets)")

        embed.add_field(
            name="Top Helpers",
            value="\n".join(leaderboard_text),
            inline=False
        )

        # Find user's rank if not in top 10
        user_id_str = str(interaction.user.id)
        user_rank = None
        user_points = 0
        for i, (uid, points, _) in enumerate(leaderboard_data):
            if uid == user_id_str:
                user_rank = i + 1
                user_points = points
                break

        if user_rank and user_rank > 10:
            embed.add_field(
                name="Your Helper Rank",
                value=f"**#{user_rank}** with **{user_points}** points",
                inline=False
            )
        elif not user_rank:
            embed.add_field(
                name="Your Helper Rank",
                value="You haven't earned any points yet!",
                inline=False
            )

        # Add Top Requesters section (per-server)
        all_requester_data = load_requester_stats()
        guild_id_str = str(interaction.guild.id)
        guild_requester_data = all_requester_data.get(guild_id_str, {})
        requester_data = guild_requester_data.get("users", {})

        if requester_data:
            # Build list of (user_id, tickets_created)
            requester_list = []
            for user_id_str_req, data in requester_data.items():
                tickets_created = data.get("tickets_created", 0)
                if tickets_created > 0:
                    requester_list.append((user_id_str_req, tickets_created))

            if requester_list:
                # Sort by tickets created descending
                requester_list.sort(key=lambda x: x[1], reverse=True)

                # Take top 5
                top_5_requesters = requester_list[:5]

                # Build requester text
                requester_text = []
                for i, (user_id_str_req, tickets) in enumerate(top_5_requesters):
                    rank = i + 1
                    if rank <= 3:
                        rank_display = medals[rank - 1]
                    else:
                        rank_display = f"**{rank}.**"
                    requester_text.append(f"{rank_display} <@{user_id_str_req}> - **{tickets}** tickets")

                embed.add_field(
                    name="Top Requesters",
                    value="\n".join(requester_text),
                    inline=False
                )

        embed.set_footer(text="Use /myscore to see your detailed stats")
        embed.timestamp = discord.utils.utcnow()

        await interaction.response.send_message(embed=embed)

    except Exception as e:
        print(f"/leaderboard failed: {e}")
        if interaction.response.is_done():
            await interaction.followup.send(f"Something went wrong: {e}")
        else:
            await interaction.response.send_message(f"Something went wrong: {e}")


@bot.tree.command(name="resetleaderboard")
async def resetleaderboard_command(interaction: discord.Interaction):
    """Reset all leaderboard data (Admin only)"""
    try:
        # Check if user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need Administrator permissions to use this command.", ephemeral=True)
            return

        # Create confirmation view
        class ConfirmResetView(ui.View):
            def __init__(self):
                super().__init__(timeout=30)
                self.confirmed = False

            @ui.button(label="Confirm Reset", style=discord.ButtonStyle.danger)
            async def confirm_button(self, button_interaction: discord.Interaction, button: ui.Button):
                if button_interaction.user.id != interaction.user.id:
                    await button_interaction.response.send_message("Only the command user can confirm.", ephemeral=True)
                    return

                # Reset helper points for THIS server only
                all_points_data = load_points()
                guild_id_str = str(interaction.guild.id)
                if guild_id_str in all_points_data:
                    all_points_data[guild_id_str] = {"users": {}}
                    save_points(all_points_data)

                # Reset requester stats for THIS server only
                all_requester_data = load_requester_stats()
                if guild_id_str in all_requester_data:
                    all_requester_data[guild_id_str] = {"users": {}}
                    save_requester_stats(all_requester_data)

                self.confirmed = True
                self.stop()

                await button_interaction.response.edit_message(
                    content=f"✅ Leaderboard has been reset for **{interaction.guild.name}**!\n\nAll helper points and requester stats for this server have been cleared.\n\n*(Other servers' data remains unchanged)*",
                    view=None
                )

            @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel_button(self, button_interaction: discord.Interaction, button: ui.Button):
                if button_interaction.user.id != interaction.user.id:
                    await button_interaction.response.send_message("Only the command user can cancel.", ephemeral=True)
                    return

                self.stop()
                await button_interaction.response.edit_message(
                    content="Reset cancelled.",
                    view=None
                )

        view = ConfirmResetView()
        await interaction.response.send_message(
            f"**Are you sure you want to reset the leaderboard for {interaction.guild.name}?**\n\nThis will:\n- Clear all helper points for this server\n- Clear all requester stats for this server\n- Other servers' data will NOT be affected\n\n⚠️ **This action cannot be undone!**",
            view=view,
            ephemeral=True
        )

    except Exception as e:
        print(f"/resetleaderboard failed: {e}")
        if interaction.response.is_done():
            await interaction.followup.send(f"Something went wrong: {e}")
        else:
            await interaction.response.send_message(f"Something went wrong: {e}")


@bot.tree.command(name="myscore")
async def myscore_command(interaction: discord.Interaction):
    """View your helper score and statistics for this server"""
    try:
        user_id = interaction.user.id
        stats = get_user_stats(user_id, interaction.guild.id)

        total_points = stats["total_points"]
        bosses = stats["bosses"]
        total_kills = stats["total_kills"]
        tickets_joined = stats["tickets_joined"]
        tickets_completed = stats["tickets_completed"]
        completion_rate = stats["completion_rate"]

        # Create embed
        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Helper Score",
            color=discord.Color.gold()
        )

        # Create boss summary for Total Boss Kills field
        if bosses:
            boss_summary = ", ".join([f"{boss}" for boss in sorted(bosses.keys())])
        else:
            boss_summary = "None"

        # Add total points and stats
        embed.add_field(name="Total Points", value=f"{total_points}", inline=True)
        embed.add_field(name="Total Boss Kills", value=f"{total_kills}\n({boss_summary})", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # Spacer

        # Add ticket statistics
        embed.add_field(name="Tickets Joined", value=f"{tickets_joined}", inline=True)
        embed.add_field(name="Tickets Completed", value=f"{tickets_completed}", inline=True)
        embed.add_field(name="Completion Rate", value=f"{completion_rate:.1f}%", inline=True)

        # Add boss statistics if any
        if bosses:
            boss_stats = []
            for boss_name in sorted(bosses.keys()):
                count = bosses[boss_name]
                points_earned = count * BOSS_POINTS.get(boss_name, 2)
                percentage = (count / total_kills * 100) if total_kills > 0 else 0
                boss_stats.append(
                    f"**{boss_name}**\n"
                    f"  Kills: {count} ({percentage:.1f}%)\n"
                    f"  Points Earned: {points_earned}"
                )

            embed.add_field(
                name="Boss Statistics",
                value="\n\n".join(boss_stats),
                inline=False
            )
        else:
            embed.add_field(
                name="Boss Statistics",
                value="No boss kills yet! Help with UltraWeeklies to earn points.",
                inline=False
            )

        # Add footer
        embed.set_footer(text="Keep helping to earn more points!")
        embed.timestamp = discord.utils.utcnow()

        # Send public response directly (no defer needed for fast operations)
        await interaction.response.send_message(embed=embed)

    except Exception as e:
        print(f"/myscore failed: {e}")
        # If we already responded, use followup, otherwise use response
        if interaction.response.is_done():
            await interaction.followup.send(f"Something went wrong: {e}")
        else:
            await interaction.response.send_message(f"Something went wrong: {e}")


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        return
    bot.run(token)


if __name__ == "__main__":
    main()
