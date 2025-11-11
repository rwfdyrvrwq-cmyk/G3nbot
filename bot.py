import os
import asyncio
import discord
from discord import app_commands, ui
from discord.ext import commands
from dotenv import load_dotenv
import aiohttp

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
            nickname_changed = False
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
            
            if nickname_changed:
                await interaction.response.send_message(f"✅ Nickname changed to `{self.ign}` and verification complete!", ephemeral=True)
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

            embed = discord.Embed(title="Verification Result", color=discord.Color.green() if (name_match and guild_match) else discord.Color.red())
            embed.add_field(name="Character IGN (used as ID)", value=char_id, inline=False)
            embed.add_field(name="IGN Check", value=f"{'✅ MATCH' if name_match else '❌ MISMATCH'}\nYou entered: `{user_ign}`\nPage shows: `{page_name}`", inline=False)
            embed.add_field(name="Guild Check", value=f"{'✅ MATCH' if guild_match else '❌ MISMATCH'}\nYou entered: `{user_guild if user_guild else '(empty)'}`\nPage shows: `{page_guild if page_guild else '(none)'}`", inline=False)

            if name_match and guild_match:
                embed.add_field(name="Status", value="✅ **Verification Successful!**", inline=False)
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
                        finish_view = FinishVerificationView(channel, interaction.user, user_ign)
                        await channel.send(embed=embed, view=finish_view)
                        confirmation = discord.Embed(
                            title="✅ Verification Processed",
                            description=f"Your verification has been recorded in {channel.mention}. An admin can close the channel when ready.",
                            color=discord.Color.green()
                        )
                        await interaction.followup.send(embed=confirmation, ephemeral=True)
                except Exception as channel_err:
                    error_embed = discord.Embed(
                        title="⚠️ Verification Result",
                        description="Verification matched but could not create admin channel. Please contact an admin.",
                        color=discord.Color.orange()
                    )
                    error_embed.add_field(name="Error", value=str(channel_err)[:200], inline=False)
                    await interaction.followup.send(embed=error_embed, ephemeral=True)
            else:
                embed.add_field(name="Status", value="❌ **Verification Failed** - Details do not match the character page.", inline=False)
                await interaction.followup.send(embed=embed, ephemeral=True)
            
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


class HelpOptionsView(ui.View):
    def __init__(self):
        super().__init__()

    @ui.button(label="Help?", style=discord.ButtonStyle.primary)
    async def help_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            dropdown_view = HelpDropdownView()
            await interaction.response.send_message("Select an option from the dropdown below:", view=dropdown_view, ephemeral=True)
        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass


class HelpDropdownView(ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(HelpSelect())


class HelpSelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Daily 4 Man", description="Daily 4 Man content"),
            discord.SelectOption(label="Daily 7 man", description="Daily 7 man content"),
            discord.SelectOption(label="Daily Temple Run", description="Daily Temple Run content"),
            discord.SelectOption(label="Weekly Ultras", description="Weekly Ultras content"),
            discord.SelectOption(label="Ultraspeaker", description="Ultraspeaker content"),
            discord.SelectOption(label="Grimchallenge", description="Grimchallenge content"),
            discord.SelectOption(label="Other", description="Other content"),
        ]
        super().__init__(placeholder="Choose an option...", options=options)

    async def callback(self, interaction: discord.Interaction):
        try:
            selected = self.values[0]
            await interaction.response.send_message(f"You selected: **{selected}**", ephemeral=True)
        except Exception as e:
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass
@bot.event
async def on_ready():
    global http_session
    try:
        if http_session is None:
            http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                connector=aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
            )
        
        guild_id = os.getenv("GUILD_ID")
        try:
            if guild_id:
                guild_obj = discord.Object(id=int(guild_id))
                await bot.tree.sync(guild=guild_obj)
            else:
                await bot.tree.sync()
        except:
            pass
    except:
        pass


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


@bot.tree.command(name="deployhelper")
@app_commands.default_permissions(administrator=True)
async def deployhelper_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=False)
        embed = discord.Embed(
            description="​",
            color=discord.Color.blue()
        )
        
        view = HelpOptionsView()
        await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
        except:
            pass


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        return
    bot.run(token)


if __name__ == "__main__":
    main()
