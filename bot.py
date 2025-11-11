import os
import asyncio
import discord
from discord import app_commands, ui
from discord.ext import commands
from dotenv import load_dotenv
import aiohttp
from functools import lru_cache

load_dotenv()

from scraper import get_character_info_async


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
http_session = None


class FinishVerificationView(ui.View):
    def __init__(self, channel: discord.TextChannel, user: discord.Member, ign: str):
        super().__init__()
        self.channel = channel
        self.user = user
        self.ign = ign
    
    @ui.button(label="Finish Verification", style=discord.ButtonStyle.success)
    async def finish_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            print(f"[finish_button] Clicked by {interaction.user} to close channel {self.channel.name}")
            
            nickname_changed = False
            try:
                print(f"[finish_button] Changing nickname for {self.user.name} to {self.ign}")
                await self.user.edit(nick=self.ign)
                print(f"[finish_button] Successfully changed nickname to {self.ign}")
                nickname_changed = True
            except discord.Forbidden:
                print(f"[finish_button] Missing permissions to change nickname")
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
            except Exception as nick_err:
                print(f"[finish_button] Unexpected error changing nickname: {nick_err}")
            
            if nickname_changed:
                await interaction.response.send_message(f"✅ Nickname changed to `{self.ign}` and verification complete!", ephemeral=True)
                await asyncio.sleep(1)
            
            await self.channel.delete()
            print(f"[finish_button] Successfully deleted channel {self.channel.name}")
        except Exception as e:
            print(f"[finish_button] Error: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)
            except:
                pass


class VerificationModal(ui.Modal, title="Character Verification"):
    ign = ui.TextInput(label="Character IGN (In-Game Name)", placeholder="Enter your character name (used as ID)", required=True, max_length=100)
    guild = ui.TextInput(label="Guild (leave blank if none)", placeholder="Enter your guild or leave empty", required=False, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        import traceback
        
        try:
            print(f"[on_submit] Starting verification for user {interaction.user}")
            await interaction.response.defer(ephemeral=True)
            print(f"[on_submit] Deferred interaction")

            user_ign = self.ign.value.strip()
            user_guild = self.guild.value.strip() if self.guild.value else ""
            print(f"[on_submit] User input: ign='{user_ign}', guild='{user_guild}'")

            char_id = user_ign

            if http_session is None:
                await interaction.followup.send("❌ Bot is still starting up. Please try again in a moment.", ephemeral=True)
                return

            print(f"[on_submit] Fetching character info for char_id='{char_id}'")
            info = await get_character_info_async(char_id, http_session)
            print(f"[on_submit] Got info: {info}")

            page_name = info.get("name", "").strip() if info.get("name") else ""
            page_guild = info.get("guild", "").strip() if info.get("guild") else ""
            print(f"[on_submit] Page values: name='{page_name}', guild='{page_guild}'")

            def normalize(s: str) -> str:
                return " ".join(s.lower().split()) if s else ""

            name_match = normalize(user_ign) == normalize(page_name) if page_name else False
            guild_match = normalize(user_guild) == normalize(page_guild) if page_guild or user_guild else (not page_guild and not user_guild)
            print(f"[on_submit] Comparison: name_match={name_match}, guild_match={guild_match}")

            embed = discord.Embed(title="Verification Result", color=discord.Color.green() if (name_match and guild_match) else discord.Color.red())
            embed.add_field(name="Character IGN (used as ID)", value=char_id, inline=False)
            embed.add_field(name="IGN Check", value=f"{'✅ MATCH' if name_match else '❌ MISMATCH'}\nYou entered: `{user_ign}`\nPage shows: `{page_name}`", inline=False)
            embed.add_field(name="Guild Check", value=f"{'✅ MATCH' if guild_match else '❌ MISMATCH'}\nYou entered: `{user_guild if user_guild else '(empty)'}`\nPage shows: `{page_guild if page_guild else '(none)'}`", inline=False)

            if name_match and guild_match:
                embed.add_field(name="Status", value="✅ **Verification Successful!**", inline=False)
                print(f"[on_submit] Creating private admin channel for {interaction.user.name}...")
                try:
                    guild = interaction.guild
                    if guild:
                        admin_overwrites = {}
                        if guild.owner:
                            admin_overwrites[guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                        
                        admin_role = discord.utils.find(lambda r: r.permissions.administrator, guild.roles)
                        if admin_role:
                            admin_overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                        
                        admin_overwrites[interaction.user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                        admin_overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
                        channel_name = f"verification-{interaction.user.name.lower().replace(' ', '-')}"
                        channel = await guild.create_text_channel(
                            channel_name,
                            overwrites=admin_overwrites,
                            topic=f"Verification record for {interaction.user.name} (IGN: {user_ign})"
                        )
                        print(f"[on_submit] Created channel: {channel.mention}")
                        finish_view = FinishVerificationView(channel, interaction.user, user_ign)
                        await channel.send(embed=embed, view=finish_view)
                        confirmation = discord.Embed(
                            title="✅ Verification Processed",
                            description=f"Your verification has been recorded in {channel.mention}. An admin can close the channel when ready.",
                            color=discord.Color.green()
                        )
                        await interaction.followup.send(embed=confirmation, ephemeral=True)
                except Exception as channel_err:
                    print(f"[on_submit] Error creating admin channel: {channel_err}")
                    error_embed = discord.Embed(
                        title="⚠️ Verification Result",
                        description="Verification matched but could not create admin channel. Please contact an admin.",
                        color=discord.Color.orange()
                    )
                    error_embed.add_field(name="Error", value=str(channel_err)[:200], inline=False)
                    await interaction.followup.send(embed=error_embed, ephemeral=True)
            else:
                embed.add_field(name="Status", value="❌ **Verification Failed** - Details do not match the character page.", inline=False)
                print(f"[on_submit] Sending result embed to user...")
                await interaction.followup.send(embed=embed, ephemeral=True)
            
            print(f"[on_submit] Result sent successfully")
            
        except Exception as e:
            error_msg = f"❌ Verification failed: {str(e)}"
            print(f"[on_submit] ERROR: {error_msg}\n{traceback.format_exc()}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(error_msg[:2000], ephemeral=True)
                else:
                    await interaction.followup.send(error_msg[:2000], ephemeral=True)
            except Exception as send_err:
                print(f"[on_submit] Could not send error message: {send_err}")


class VerifyButton(ui.View):
    def __init__(self):
        super().__init__()

    @ui.button(label="Start Verification", style=discord.ButtonStyle.primary)
    async def verify_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            print(f"[verify_button] Button clicked by {interaction.user}")
            modal = VerificationModal()
            print(f"[verify_button] Modal created, sending to user...")
            await interaction.response.send_modal(modal)
            print(f"[verify_button] Modal sent successfully")
        except Exception as e:
            import traceback
            error_msg = f"❌ Failed to open verification form: {str(e)}"
            print(f"[verify_button] ERROR: {error_msg}\n{traceback.format_exc()}")
            try:
                await interaction.response.send_message(error_msg, ephemeral=True)
            except:
                print(f"[verify_button] Could not send error message")
@bot.event
async def on_ready():
    global http_session
    import traceback
    try:
        if http_session is None:
            http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                connector=aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
            )
            print("✅ HTTP session pool initialized")
        
        print(f"Bot ready. Logged in as {bot.user} (id: {bot.user.id})")
        guild_id = os.getenv("GUILD_ID")
        try:
            if guild_id:
                print(f"Syncing to guild {guild_id}...")
                guild_obj = discord.Object(id=int(guild_id))
                synced = await bot.tree.sync(guild=guild_obj)
                print(f"✅ Synced {len(synced)} application commands to guild {guild_id}")
            else:
                print("Syncing to global (all guilds)...")
                synced = await bot.tree.sync()
                print(f"✅ Synced {len(synced)} global application commands")
        except Exception as sync_err:
            print(f"⚠️ Failed to sync application commands: {sync_err}")
            print(traceback.format_exc())
    except Exception as e:
        print(f"❌ FATAL ERROR in on_ready: {e}")
        print(traceback.format_exc())


@bot.tree.command(name="verify")
async def verify(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔐 Account Verification",
    description="Verify AQW account",
        color=discord.Color.blue()
    )
    embed.add_field(name="How to verify", value="1. Click the **Start Verification** button below\n2. Enter your IGN (In-Game Name)\n3. Enter your Guild (or leave blank if you have none)", inline=False)

    view = VerifyButton()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="sync")
async def sync_commands(interaction: discord.Interaction):
    try:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permission to run /sync.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            guild_obj = discord.Object(id=int(guild_id))
            synced = await bot.tree.sync(guild=guild_obj)
            await interaction.followup.send(f"✅ Resynced {len(synced)} commands to guild {guild_id}.")
        else:
            synced = await bot.tree.sync()
            await interaction.followup.send(f"✅ Resynced {len(synced)} global commands.")
    except Exception as e:
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ Sync failed: {e}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Sync failed: {e}", ephemeral=True)


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("Please set DISCORD_TOKEN environment variable and rerun.")
        return
    bot.run(token)


if __name__ == "__main__":
    main()
