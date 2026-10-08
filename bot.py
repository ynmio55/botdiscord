"""Discord YouTube music bot with slash commands and persistent controls."""
import asyncio
import logging
import os
import shutil
from collections import deque
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("musicbot")
YDL = {"format": "bestaudio/best", "quiet": True, "no_warnings": True,
       "noplaylist": True, "default_search": "ytsearch1", "skip_download": True}
FFMPEG = {"before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
          "options": "-vn"}
intents = discord.Intents.default()
intents.voice_states = True
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

@dataclass
class Song:
    title: str
    url: str
    requester: str

@dataclass
class Player:
    queue: deque = field(default_factory=deque)
    current: Song | None = None
    volume: float = 0.7
    generation: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    channel: object = None
    panel: discord.Message | None = None

players: dict[int, Player] = {}

def player(guild):
    return players.setdefault(guild.id, Player())

def extract_sync(query):
    with yt_dlp.YoutubeDL(YDL) as ydl:
        result = ydl.extract_info(query, download=False)
    if result and "entries" in result:
        result = next((item for item in result["entries"] if item), None)
    if not result:
        raise ValueError("ไม่พบเพลง")
    return result

async def extract(query):
    return await asyncio.to_thread(extract_sync, query)

def same_channel(interaction):
    vc = interaction.guild.voice_client if interaction.guild else None
    user_vc = getattr(interaction.user, "voice", None)
    return bool(vc and user_vc and user_vc.channel == vc.channel)

async def authorized(interaction):
    if same_channel(interaction):
        return True
    await interaction.response.send_message("กรุณาเข้าห้องเสียงเดียวกับบอท", ephemeral=True)
    return False

async def refresh(guild):
    p = player(guild)
    if not p.channel:
        return
    if p.current:
        song = p.current
        embed = discord.Embed(title="🎶 Now Playing", description=f"**[{discord.utils.escape_markdown(song.title[:160])}]({song.url})**", color=discord.Color.blurple())
        embed.add_field(name="Requested by", value=song.requester)
        embed.add_field(name="Queue", value=str(len(p.queue)))
        embed.add_field(name="Volume", value=f"{round(p.volume * 100)}%")
    else:
        embed = discord.Embed(title="🎵 Music Bot", description="ไม่มีเพลงกำลังเล่น — ใช้ /play", color=discord.Color.dark_grey())
    try:
        if p.panel:
            await p.panel.edit(embed=embed, view=Controls())
        else:
            p.panel = await p.channel.send(embed=embed, view=Controls())
    except (discord.HTTPException, AttributeError):
        p.panel = None

async def next_song(guild, generation=None):
    p = player(guild)
    async with p.lock:
        if generation is not None and generation != p.generation:
            return
        vc = guild.voice_client
        if not vc or not vc.is_connected() or vc.is_playing() or vc.is_paused():
            return
        while p.queue:
            song = p.queue.popleft()
            try:
                data = await extract(song.url)
                stream = data.get("url")
                if not stream:
                    raise ValueError("ไม่มี audio URL")
                audio = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(stream, **FFMPEG), volume=p.volume)
                p.current = song
                p.generation += 1
                token = p.generation
                loop = asyncio.get_running_loop()
                def after(error):
                    if error:
                        log.error("Voice error: %s", error)
                    task = asyncio.run_coroutine_threadsafe(next_song(guild, token), loop)
                    def report(future):
                        try:
                            future.result()
                        except Exception:
                            log.exception("Playback continuation failed")
                    task.add_done_callback(report)
                vc.play(audio, after=after)
                await refresh(guild)
                return
            except Exception:
                p.current = None
                log.exception("Unable to play %s", song.title)
                if p.channel:
                    try:
                        await p.channel.send(f"⚠️ ไม่สามารถเล่นเพลง: {discord.utils.escape_markdown(song.title[:100])}")
                    except discord.HTTPException:
                        pass
        p.current = None
        await refresh(guild)

async def stop_player(guild):
    p = player(guild)
    p.generation += 1
    p.queue.clear()
    p.current = None
    vc = guild.voice_client
    if vc:
        vc.stop()
        await vc.disconnect(force=True)
    await refresh(guild)

class Controls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Pause", emoji="⏸️", style=discord.ButtonStyle.secondary, custom_id="music:pause")
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await authorized(interaction): return
        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Paused", ephemeral=True)
        else:
            await interaction.response.send_message("ไม่มีเพลงกำลังเล่น", ephemeral=True)

    @discord.ui.button(label="Resume", emoji="▶️", style=discord.ButtonStyle.secondary, custom_id="music:resume")
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await authorized(interaction): return
        vc = interaction.guild.voice_client
        if vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Resumed", ephemeral=True)
        else:
            await interaction.response.send_message("ไม่มีเพลงที่หยุดไว้", ephemeral=True)

    @discord.ui.button(label="Skip", emoji="⏭️", style=discord.ButtonStyle.primary, custom_id="music:skip")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await authorized(interaction): return
        vc = interaction.guild.voice_client
        if vc.is_playing() or vc.is_paused():
            vc.stop()
            await interaction.response.send_message("⏭️ Skipped", ephemeral=True)
        else:
            await interaction.response.send_message("ไม่มีเพลงให้ข้าม", ephemeral=True)

    @discord.ui.button(label="Stop", emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music:stop")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await authorized(interaction): return
        await interaction.response.defer(ephemeral=True)
        await stop_player(interaction.guild)
        await interaction.followup.send("⏹️ Stopped and disconnected", ephemeral=True)

async def _handle_play(interaction: discord.Interaction, query: str):
    if not interaction.guild:
        await interaction.response.send_message("ใช้ใน Server เท่านั้น", ephemeral=True)
        return
    user_voice = getattr(interaction.user, "voice", None)
    if not user_voice or not user_voice.channel:
        await interaction.response.send_message("เข้าห้อง Voice ก่อนครับ", ephemeral=True)
        return
    vc = interaction.guild.voice_client
    if vc and vc.channel != user_voice.channel:
        await interaction.response.send_message("บอทกำลังอยู่ในห้องอื่น", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    if not vc:
        try:
            vc = await user_voice.channel.connect(timeout=30)
        except Exception as error:
            await interaction.followup.send(f"เข้าห้อง Voice ไม่สำเร็จ: {str(error)[:160]}")
            return
    try:
        data = await extract(query)
        url = data.get("webpage_url") or data.get("original_url")
        if not url or not url.startswith(("https://", "http://")):
            raise ValueError("ไม่ได้รับ URL เพลง")
        song = Song(str(data.get("title") or "Unknown")[:180], url, interaction.user.mention)
    except Exception as error:
        await interaction.followup.send(f"ค้นหาเพลงไม่สำเร็จ: {str(error)[:180]}")
        return
    p = player(interaction.guild)
    p.channel = interaction.channel
    p.queue.append(song)
    await interaction.followup.send(f"✅ เพิ่มเพลง: **{discord.utils.escape_markdown(song.title)}**")
    await next_song(interaction.guild)

@bot.tree.command(name="play", description="ค้นหาและเล่นเพลง YouTube")
@app_commands.describe(query="ชื่อเพลงหรือลิงก์ YouTube")
async def play(interaction: discord.Interaction, query: str):
    await _handle_play(interaction, query)

@bot.tree.command(name="ohm", description="ค้นหาและเล่นเพลง YouTube")
@app_commands.describe(query="ชื่อเพลงหรือลิงก์ YouTube")
async def ohm(interaction: discord.Interaction, query: str):
    await _handle_play(interaction, query)

@bot.tree.command(name="queue", description="แสดงคิวเพลง")
async def queue(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("ใช้ใน Server เท่านั้น", ephemeral=True)
        return
    p = player(interaction.guild)
    lines = [f"▶️ {p.current.title}" if p.current else "ไม่มีเพลงกำลังเล่น"]
    lines.extend(f"{i}. {s.title[:90]}" for i, s in enumerate(list(p.queue)[:15], 1))
    await interaction.response.send_message("\n".join(lines)[:1900])

@bot.tree.command(name="volume", description="ระดับเสียง 0-100")
@app_commands.describe(percent="ระดับเสียง 0-100")
async def volume(interaction: discord.Interaction, percent: app_commands.Range[int, 0, 100]):
    if not await authorized(interaction): return
    p = player(interaction.guild)
    p.volume = percent / 100
    vc = interaction.guild.voice_client
    if isinstance(vc.source, discord.PCMVolumeTransformer):
        vc.source.volume = p.volume
    await interaction.response.send_message(f"🔊 Volume {percent}%", ephemeral=True)
    await refresh(interaction.guild)

@bot.tree.command(name="leave", description="หยุดและออกจากห้องเสียง")
async def leave(interaction: discord.Interaction):
    if not await authorized(interaction): return
    await interaction.response.defer(ephemeral=True)
    await stop_player(interaction.guild)
    await interaction.followup.send("ออกจากห้องแล้ว", ephemeral=True)

async def setup_hook():
    bot.add_view(Controls())
    guild_id = os.getenv("GUILD_ID", "").strip()
    if guild_id:
        guild = discord.Object(id=int(guild_id))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        log.info("Commands synced for guild %s", guild_id)
    else:
        await bot.tree.sync()
        log.info("Global commands synced")

bot.setup_hook = setup_hook

async def main():
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "put_your_discord_bot_token_here":
        raise SystemExit("Set DISCORD_TOKEN in .env")
    if not shutil.which("ffmpeg"):
        raise SystemExit("FFmpeg not installed")
    @bot.event
    async def on_ready():
        log.info("Bot online: %s", bot.user)
        for guild in bot.guilds:
            try:
                bot.tree.copy_global_to(guild=guild)
                await bot.tree.sync(guild=guild)
                log.info("Synced commands to guild: %s (%s)", guild.name, guild.id)
            except Exception as e:
                log.warning("Could not sync to guild %s: %s", guild.id, e)
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
