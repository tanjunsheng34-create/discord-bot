"""
GMPT Bot — 音乐播放 / KTV 点歌队列
/gmpt-play <song>    — 播放歌曲 / 加入队列
/gmpt-skip           — 跳过当前歌曲
/gmpt-stop           — 停止播放并清空队列
/gmpt-music-queue          — 查看播放队列
/gmpt-np             — 查看当前播放
/gmpt-pause          — 暂停
/gmpt-resume         — 继续播放
/gmpt-volume <0-100> — 调整音量
/gmpt-karaoke <song> — KTV模式（同 play）
"""
import asyncio
import re
import discord
from discord import app_commands
from discord.ext import commands


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.song_queue: list[dict] = []
        self.now_playing: dict | None = None
        self.voice_client: discord.VoiceClient | None = None
        self._disconnect_task: asyncio.Task | None = None
        self._volume: float = 0.5

    def _cancel_disconnect(self):
        if self._disconnect_task and not self._disconnect_task.done():
            self._disconnect_task.cancel()
            self._disconnect_task = None

    async def _start_disconnect_timer(self):
        self._cancel_disconnect()
        self._disconnect_task = asyncio.create_task(self._disconnect_after())
        # keep weak ref to avoid GC
        self._disconnect_task.add_done_callback(lambda t: None)

    async def _disconnect_after(self):
        await asyncio.sleep(180)
        if self.voice_client and not self.voice_client.is_playing():
            await self.voice_client.disconnect()
            self.voice_client = None
            self.song_queue.clear()
            self.now_playing = None

    async def _join_voice(self, interaction: discord.Interaction) -> bool:
        """Join user's voice channel. Returns True if successfully connected."""
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "请先加入语音频道 | Join a voice channel first",
                ephemeral=True,
            )
            return False

        channel = interaction.user.voice.channel

        if self.voice_client is None:
            self.voice_client = await channel.connect()
        elif self.voice_client.channel.id != channel.id:
            await self.voice_client.move_to(channel)

        return True

    async def _play_next(self, interaction: discord.Interaction = None):
        """Play the next song in queue. If queue empty, start disconnect timer."""
        if not self.song_queue:
            self.now_playing = None
            if self.voice_client and self.voice_client.is_connected():
                await self._start_disconnect_timer()
            return

        self._cancel_disconnect()

        song = self.song_queue.pop(0)
        self.now_playing = song

        try:
            audio_url = await self._extract_audio_url(song["query"])
            if audio_url is None:
                # Skip this song, try next
                await self._play_next(interaction)
                return

            ffmpeg_opts = {
                "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                "options": "-vn",
            }
            source = discord.FFmpegPCMAudio(audio_url, **ffmpeg_opts)
            source = discord.PCMVolumeTransformer(source, volume=self._volume)

            def after_play(error):
                if error:
                    print(f"[Music] Playback error: {error}")
                asyncio.run_coroutine_threadsafe(self._after_song(interaction), self.bot.loop)

            self.voice_client.play(source, after=after_play)

        except Exception as e:
            print(f"[Music] Error playing song: {e}")
            await self._play_next(interaction)

    async def _after_song(self, interaction):
        await self._play_next(interaction)

    async def _extract_audio_url(self, query: str) -> str | None:
        """Use yt-dlp to search YouTube and extract best audio URL."""
        import yt_dlp

        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "default_search": "ytsearch",
            "extract_flat": False,
        }

        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                if "entries" in info and len(info["entries"]) > 0:
                    info = info["entries"][0]
                return info.get("url")

        try:
            return await loop.run_in_executor(None, _extract)
        except Exception as e:
            print(f"[Music] yt-dlp error: {e}")
            return None

    @app_commands.command(name="gmpt-play", description="Play a song from YouTube")
    @app_commands.describe(song="歌曲名称或YouTube链接 | Song name or URL")
    async def play(self, interaction: discord.Interaction, song: str):
        await interaction.response.defer()

        if not await self._join_voice(interaction):
            return

        song_info = {
            "query": song,
            "title": song,
            "requester": interaction.user.mention,
        }

        try:
            yt_title = await self._get_title(song)
            if yt_title:
                song_info["title"] = yt_title
        except Exception:
            pass

        self.song_queue.append(song_info)

        if self.voice_client.is_playing() or self.voice_client.is_paused():
            embed = discord.Embed(
                title="已加入队列 | Added to Queue",
                description=f"**{song_info['title']}**\n请求者 | Requested by: {interaction.user.mention}",
                color=0x1DB954,
            )
            embed.set_footer(text=f"队列位置 #{len(self.song_queue)} | Queue position #{len(self.song_queue)}")
            await interaction.followup.send(embed=embed)
        else:
            embed = discord.Embed(
                title="正在播放 | Now Playing",
                description=f"**{song_info['title']}**\n请求者 | Requested by: {interaction.user.mention}",
                color=0x1DB954,
            )
            await interaction.followup.send(embed=embed)
            await self._play_next(interaction)

    async def _get_title(self, query: str) -> str | None:
        """Extract video title from query using yt-dlp."""
        import yt_dlp

        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "default_search": "ytsearch",
            "extract_flat": True,
        }

        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                if "entries" in info and len(info["entries"]) > 0:
                    return info["entries"][0].get("title")
                return info.get("title")

        try:
            return await loop.run_in_executor(None, _extract)
        except Exception:
            return None

    @app_commands.command(name="gmpt-skip", description="Skip current song")
    async def skip(self, interaction: discord.Interaction):
        if self.voice_client is None or not self.voice_client.is_connected():
            await interaction.response.send_message(
                "机器人不在语音频道中 | Bot is not in a voice channel",
                ephemeral=True,
            )
            return

        if not self.voice_client.is_playing():
            await interaction.response.send_message(
                "当前没有正在播放的歌曲 | Nothing is playing right now",
                ephemeral=True,
            )
            return

        await interaction.response.send_message("已跳过 | Skipped ⏭️")
        self.voice_client.stop()

    @app_commands.command(name="gmpt-stop", description="Stop playback and clear queue")
    async def stop(self, interaction: discord.Interaction):
        self.song_queue.clear()
        self.now_playing = None

        if self.voice_client:
            if self.voice_client.is_playing():
                self.voice_client.stop()
            await self.voice_client.disconnect()
            self.voice_client = None

        self._cancel_disconnect()

        await interaction.response.send_message("已停止播放并清空队列 | Stopped and cleared the queue")

    @app_commands.command(name="gmpt-music-queue", description="Show song queue")
    async def queue(self, interaction: discord.Interaction):
        embed = discord.Embed(title="播放队列 | Play Queue", color=0x1DB954)

        if self.now_playing:
            embed.add_field(
                name="当前播放 | Now Playing",
                value=f"**{self.now_playing['title']}** — {self.now_playing.get('requester', 'Unknown')}",
                inline=False,
            )

        if not self.song_queue:
            embed.add_field(name="队列为空 | Queue is empty", value="使用 /gmpt-play 添加歌曲", inline=False)
        else:
            desc = ""
            for i, s in enumerate(self.song_queue, 1):
                desc += f"`#{i}` **{s['title']}** — {s.get('requester', 'Unknown')}\n"
            embed.add_field(name=f"排队中 ({len(self.song_queue)} 首)", value=desc, inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="gmpt-np", description="Show now playing")
    async def now_playing_cmd(self, interaction: discord.Interaction):
        if self.now_playing is None or (self.voice_client and not self.voice_client.is_playing()):
            await interaction.response.send_message(
                "当前没有正在播放的歌曲 | Nothing is playing right now",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="正在播放 | Now Playing",
            description=f"**{self.now_playing['title']}**\n请求者 | Requested by: {self.now_playing.get('requester', 'Unknown')}",
            color=0x1DB954,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="gmpt-pause", description="Pause playback")
    async def pause(self, interaction: discord.Interaction):
        if self.voice_client is None or not self.voice_client.is_playing():
            await interaction.response.send_message(
                "当前没有正在播放的歌曲 | Nothing is playing",
                ephemeral=True,
            )
            return

        self.voice_client.pause()
        await interaction.response.send_message("已暂停 | Paused ⏸️")

    @app_commands.command(name="gmpt-resume", description="Resume playback")
    async def resume(self, interaction: discord.Interaction):
        if self.voice_client is None or not self.voice_client.is_paused():
            await interaction.response.send_message(
                "当前没有暂停中的播放 | Nothing is paused",
                ephemeral=True,
            )
            return

        self.voice_client.resume()
        await interaction.response.send_message("已继续 | Resumed ▶️")

    @app_commands.command(name="gmpt-volume", description="Set volume 0-100")
    @app_commands.describe(volume="音量 0-100 | Volume level 0-100")
    async def volume(self, interaction: discord.Interaction, volume: int):
        if volume < 0 or volume > 100:
            await interaction.response.send_message(
                "音量需在 0-100 之间 | Volume must be between 0 and 100",
                ephemeral=True,
            )
            return

        self._volume = volume / 100.0

        if self.voice_client and self.voice_client.source:
            if isinstance(self.voice_client.source, discord.PCMVolumeTransformer):
                self.voice_client.source.volume = self._volume

        await interaction.response.send_message(f"音量已设置为 {volume}% | Volume set to {volume}% 🔊")

    @app_commands.command(name="gmpt-karaoke", description="Play karaoke track from YouTube")
    @app_commands.describe(song="歌曲名称或YouTube链接 | Song name or URL")
    async def karaoke(self, interaction: discord.Interaction, song: str):
        await interaction.response.defer()

        if not await self._join_voice(interaction):
            return

        song_info = {
            "query": song,
            "title": song,
            "requester": interaction.user.mention,
        }

        try:
            yt_title = await self._get_title(song)
            if yt_title:
                song_info["title"] = yt_title
        except Exception:
            pass

        self.song_queue.append(song_info)

        if self.voice_client.is_playing() or self.voice_client.is_paused():
            embed = discord.Embed(
                title="已加入KTV队列 | Added to KTV Queue",
                description=f"**{song_info['title']}**\n点歌人 | Requested by: {interaction.user.mention}",
                color=0x1DB954,
            )
            embed.set_footer(text=f"队列位置 #{len(self.song_queue)} | Queue position #{len(self.song_queue)}")
            await interaction.followup.send(embed=embed)
        else:
            embed = discord.Embed(
                title="KTV — 正在播放 | Now Playing",
                description=f"**{song_info['title']}**\n点歌人 | Requested by: {interaction.user.mention}",
                color=0x1DB954,
            )
            await interaction.followup.send(embed=embed)
            await self._play_next(interaction)

    @app_commands.command(name="gmpt-music-panel", description="Send the music control panel")
    @app_commands.default_permissions(administrator=True)
    async def music_panel(self, interaction: discord.Interaction):
        """Send a persistent music control panel to the current channel."""
        view = MusicPanelView(self)
        embed = discord.Embed(
            title="🎵 音乐控制面板 | Music Control Panel",
            description="点击下方按钮控制音乐播放 | Click buttons below to control playback",
            color=0x1DB954,
        )
        await interaction.response.send_message(embed=embed, view=view)


class MusicPanelView(discord.ui.View):
    """Persistent music control panel with buttons."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def _check_voice(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.voice:
            await interaction.response.send_message(
                "请先加入语音频道 | Join a voice channel first",
                ephemeral=True,
            )
            return False
        if not self.cog.voice_client or not self.cog.voice_client.is_connected():
            await interaction.response.send_message(
                "Bot 不在语音频道，请先使用 /gmpt-play | Bot not connected, use /gmpt-play first",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="music_prev", row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Replay the current song from the beginning."""
        if not await self._check_voice(interaction):
            return
        if self.cog.now_playing:
            self.cog.song_queue.insert(0, dict(self.cog.now_playing))
        if self.cog.voice_client and self.cog.voice_client.is_playing():
            self.cog.voice_client.stop()
        await interaction.response.send_message("⏮️ 正在重播 | Replaying...", ephemeral=False)

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, custom_id="music_toggle", row=0)
    async def toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle pause / resume."""
        if not await self._check_voice(interaction):
            return
        vc = self.cog.voice_client
        if vc.is_playing():
            vc.pause()
            button.emoji = "▶️"
            msg = "已暂停 | Paused ⏸️"
        elif vc.is_paused():
            vc.resume()
            button.emoji = "⏯️"
            msg = "已继续 | Resumed ▶️"
        else:
            return await interaction.response.send_message(
                "当前没有正在播放的歌曲 | Nothing is playing", ephemeral=True
            )
        await interaction.response.send_message(msg, ephemeral=False)
        await interaction.message.edit(view=self)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="music_skip", row=0)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Skip the current song."""
        if not await self._check_voice(interaction):
            return
        if not self.cog.voice_client.is_playing() and not self.cog.voice_client.is_paused():
            return await interaction.response.send_message(
                "当前没有正在播放的歌曲 | Nothing is playing", ephemeral=True
            )
        self.cog.voice_client.stop()
        await interaction.response.send_message("已跳过 | Skipped ⏭️", ephemeral=False)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music_stop", row=0)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Stop playback, clear queue and disconnect."""
        if not await self._check_voice(interaction):
            return
        self.cog.song_queue.clear()
        self.cog.now_playing = None
        if self.cog.voice_client.is_playing():
            self.cog.voice_client.stop()
        await self.cog.voice_client.disconnect()
        self.cog.voice_client = None
        self.cog._cancel_disconnect()
        await interaction.response.send_message("已停止播放并清空队列 | Stopped and cleared queue", ephemeral=False)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, custom_id="music_voldown", row=1)
    async def voldown_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Decrease volume by 10."""
        if not await self._check_voice(interaction):
            return
        new_vol = max(0, int(self.cog._volume * 100) - 10)
        self.cog._volume = new_vol / 100.0
        if self.cog.voice_client and self.cog.voice_client.source:
            if isinstance(self.cog.voice_client.source, discord.PCMVolumeTransformer):
                self.cog.voice_client.source.volume = self.cog._volume
        await interaction.response.send_message(f"音量 {new_vol}% | Volume: {new_vol}%", ephemeral=False)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="music_volup", row=1)
    async def volup_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Increase volume by 10."""
        if not await self._check_voice(interaction):
            return
        new_vol = min(100, int(self.cog._volume * 100) + 10)
        self.cog._volume = new_vol / 100.0
        if self.cog.voice_client and self.cog.voice_client.source:
            if isinstance(self.cog.voice_client.source, discord.PCMVolumeTransformer):
                self.cog.voice_client.source.volume = self.cog._volume
        await interaction.response.send_message(f"音量 {new_vol}% | Volume: {new_vol}%", ephemeral=False)

    @discord.ui.button(emoji="📋", style=discord.ButtonStyle.secondary, custom_id="music_queue", row=1)
    async def queue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show the current song queue (ephemeral)."""
        embed = discord.Embed(title="播放队列 | Play Queue", color=0x1DB954)
        if self.cog.now_playing:
            embed.add_field(
                name="当前播放 | Now Playing",
                value=f"**{self.cog.now_playing['title']}** — {self.cog.now_playing.get('requester', 'Unknown')}",
                inline=False,
            )
        if not self.cog.song_queue:
            embed.add_field(name="队列为空 | Queue is empty", value="使用 /gmpt-play 添加歌曲", inline=False)
        else:
            desc = ""
            for i, s in enumerate(self.cog.song_queue, 1):
                desc += f"`#{i}` **{s['title']}** — {s.get('requester', 'Unknown')}\n"
            embed.add_field(name=f"排队中 ({len(self.cog.song_queue)} 首)", value=desc, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(emoji="🎤", style=discord.ButtonStyle.secondary, custom_id="music_ktv", row=1)
    async def ktv_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show KTV mode tip."""
        await interaction.response.send_message(
            "🎤 KTV模式 — 使用 `/gmpt-karaoke <歌曲名>` 点歌 | Use `/gmpt-karaoke <song>` for KTV mode",
            ephemeral=True,
        )




async def setup(bot):
    await bot.add_cog(Music(bot))
