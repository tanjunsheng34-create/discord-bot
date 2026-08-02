"""
GMPT Bot — Mini Games (Guess Number, Minesweeper, Idiom Chain, Music Quiz)
Bilingual (中文 / English)
"""
import asyncio
import random
import re
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
from cogs.economy import get_balance, add_coins
import logging

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Idiom Database (100+ commonly used Chinese idioms)
# ══════════════════════════════════════════════════════════════

IDIOMS = [
    "一心一意", "一马当先", "一鸣惊人", "一诺千金", "一见钟情",
    "一石二鸟", "一落千丈", "一言九鼎", "一目了然", "一丝不苟",
    "三心二意", "三生有幸", "三顾茅庐", "三言两语", "三番五次",
    "四面楚歌", "四海为家", "四通八达", "五光十色", "五花八门",
    "五体投地", "五湖四海", "六神无主", "七上八下", "七嘴八舌",
    "八仙过海", "九牛一毛", "九死一生", "十全十美", "十拿九稳",
    "百发百中", "百年好合", "百折不挠", "千军万马", "千变万化",
    "千方百计", "千钧一发", "千锤百炼", "万紫千红", "万众一心",
    "马到成功", "龙飞凤舞", "龙马精神", "虎头蛇尾", "虎视眈眈",
    "画龙点睛", "画蛇添足", "对牛弹琴", "守株待兔", "亡羊补牢",
    "井底之蛙", "狐假虎威", "鹤立鸡群", "鸡飞蛋打", "惊弓之鸟",
    "胸有成竹", "指鹿为马", "掩耳盗铃", "刻舟求剑", "叶公好龙",
    "纸上谈兵", "破釜沉舟", "卧薪尝胆", "完璧归赵", "负荆请罪",
    "鞠躬尽瘁", "大公无私", "大义灭亲", "大器晚成", "大智若愚",
    "天长地久", "天衣无缝", "天马行空", "天翻地覆", "天经地义",
    "地动山摇", "山清水秀", "山盟海誓", "海阔天空", "海枯石烂",
    "风雨同舟", "风花雪月", "风和日丽", "春暖花开", "秋高气爽",
    "花好月圆", "花言巧语", "心花怒放", "心想事成", "心旷神怡",
    "心安理得", "心猿意马", "走马观花", "开门见山", "人山人海",
    "人声鼎沸", "人才济济", "人云亦云", "异口同声", "异想天开",
    "爱不释手", "爱屋及乌", "安居乐业", "笨鸟先飞", "别出心裁",
    "冰天雪地", "不耻下问", "不拘一格", "不可救药", "不可思议",
    "不言而喻", "不约而同", "不翼而飞", "步步为营", "出类拔萃",
]

# Pre-index by first char for fast lookup
IDIOM_INDEX: dict[str, list[str]] = {}
for idiom in IDIOMS:
    first = idiom[0]
    if first not in IDIOM_INDEX:
        IDIOM_INDEX[first] = []
    IDIOM_INDEX[first].append(idiom)


# ══════════════════════════════════════════════════════════════
# Music Quiz song pool
# ══════════════════════════════════════════════════════════════

MUSIC_QUIZ_SONGS = [
    {"title": "月亮代表我的心", "artist": "邓丽君", "lyric_hint": "你问我爱你有多深", "emoji_hint": "🌙💖"},
    {"title": "童话", "artist": "光良", "lyric_hint": "忘了有多久再没听到你", "emoji_hint": "📖🏰"},
    {"title": "青花瓷", "artist": "周杰伦", "lyric_hint": "素胚勾勒出青花笔锋浓转淡", "emoji_hint": "🔵🏺"},
    {"title": "稻香", "artist": "周杰伦", "lyric_hint": "对这个世界如果你有太多的抱怨", "emoji_hint": "🌾🎵"},
    {"title": "十年", "artist": "陈奕迅", "lyric_hint": "如果那两个字没有颤抖", "emoji_hint": "🔟📅"},
    {"title": "小幸运", "artist": "田馥甄", "lyric_hint": "我听见雨滴落在青青草地", "emoji_hint": "🍀💕"},
    {"title": "告白气球", "artist": "周杰伦", "lyric_hint": "塞纳河畔左岸的咖啡", "emoji_hint": "🎈❤️"},
    {"title": "演员", "artist": "薛之谦", "lyric_hint": "简单点说话的方式简单点", "emoji_hint": "🎭🎬"},
    {"title": "体面", "artist": "于文文", "lyric_hint": "别堆砌怀念让剧情变得狗血", "emoji_hint": "👔👋"},
    {"title": "起风了", "artist": "买辣椒也用券", "lyric_hint": "这一路上走走停停", "emoji_hint": "🍃🏃"},
    {"title": "光年之外", "artist": "邓紫棋", "lyric_hint": "感受停在我发端的指尖", "emoji_hint": "✨🚀"},
    {"title": "后来", "artist": "刘若英", "lyric_hint": "后来我总算学会了如何去爱", "emoji_hint": "⏭️💔"},
    {"title": "晴天", "artist": "周杰伦", "lyric_hint": "故事的小黄花从出生那年就飘着", "emoji_hint": "☀️🌸"},
    {"title": "暖暖", "artist": "梁静茹", "lyric_hint": "都可以随便的你说的我都愿意去", "emoji_hint": "🔥💗"},
    {"title": "夜曲", "artist": "周杰伦", "lyric_hint": "一群嗜血的蚂蚁被腐肉所吸引", "emoji_hint": "🌙🎹"},
    {"title": "遇见", "artist": "孙燕姿", "lyric_hint": "听见冬天的离开", "emoji_hint": "👀🍂"},
    {"title": "平凡之路", "artist": "朴树", "lyric_hint": "徘徊着的在路上的", "emoji_hint": "🛣️🚶"},
    {"title": "海阔天空", "artist": "Beyond", "lyric_hint": "今天我寒夜里看雪飘过", "emoji_hint": "🌊🦅"},
    {"title": "同桌的你", "artist": "老狼", "lyric_hint": "明天你是否会想起", "emoji_hint": "📚👫"},
    {"title": "倔强", "artist": "五月天", "lyric_hint": "当我和世界不一样", "emoji_hint": "💪😤"},
    {"title": "江南", "artist": "林俊杰", "lyric_hint": "风到这里就是粘", "emoji_hint": "🌧️🏯"},
    {"title": "七里香", "artist": "周杰伦", "lyric_hint": "窗外的麻雀在电线杆上多嘴", "emoji_hint": "🌿🌸"},
    {"title": "那些年", "artist": "胡夏", "lyric_hint": "又回到最初的起点", "emoji_hint": "📖💭"},
    {"title": "匆匆那年", "artist": "王菲", "lyric_hint": "匆匆那年我们究竟说了几遍", "emoji_hint": "⏰📅"},
    {"title": "可惜不是你", "artist": "梁静茹", "lyric_hint": "这一刻突然觉得好熟悉", "emoji_hint": "😢❌"},
]


# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════

class MiniGames(CogBase):
    """小游戏合集 / Mini Games Collection"""

    gmpt_mini_group = app_commands.Group(
        name="gmpt-mini",
        description="Mini games / 小游戏合集"
    )

    def __init__(self, bot):
        self.bot = bot
        self._idiom_sessions: dict[str, dict] = {}   # channel_id -> session
        self._musicquiz_sessions: dict[str, dict] = {}  # channel_id -> session

    # ══════════════════════════════════════════════════════════
    # /gmpt-mini guess — 猜数字 (standalone)
    # ══════════════════════════════════════════════════════════

    @gmpt_mini_group.command(
        name="guess",
        description="猜数字游戏 / Number guessing game (1-100, 10 tries)"
    )
    async def guess_cmd(self, interaction: discord.Interaction):
        answer = random.randint(1, 100)
        uid = str(interaction.user.id)
        uname = interaction.user.display_name

        embed = discord.Embed(
            title="🔢 猜数字 / Number Guessing",
            description=f"1 - 100 之间的数字，你只有 **10** 次机会！\nGuess a number between 1 and 100, only **10** tries!",
            color=0x2ECC71,
        )
        embed.add_field(name="范围 / Range", value="`1 - 100`", inline=True)
        embed.add_field(name="剩余次数 / Attempts Left", value="**10/10**", inline=True)
        embed.set_footer(text=f"Player: {uname}")

        view = MiniGuessView(answer, uid, uname)
        await interaction.response.send_message(embed=embed, view=view)

    # ══════════════════════════════════════════════════════════
    # /gmpt-mini minesweeper — 扫雷
    # ══════════════════════════════════════════════════════════

    @gmpt_mini_group.command(
        name="minesweeper",
        description="扫雷 / Minesweeper — 5x5 grid with 3 mines"
    )
    async def minesweeper_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        uname = interaction.user.display_name

        # Generate board: 5x5, 3 mines
        positions = list(range(25))
        mine_pos = set(random.sample(positions, 3))
        safe_count = 22  # total safe cells

        # Build embed with spoiler tags
        rows_display = []
        for r in range(5):
            row_cells = []
            for c in range(5):
                pos = r * 5 + c
                if pos in mine_pos:
                    row_cells.append("||💣||")
                else:
                    row_cells.append("||🟩||")
            rows_display.append(" ".join(row_cells))

        grid_text = "\n".join(rows_display)

        embed = discord.Embed(
            title="💣 扫雷 / Minesweeper",
            description=f"5×5 雷区，共 **3** 颗雷。输入坐标翻格子（如 `A3`）\n"
                        f"5×5 grid, **3** mines. Enter coordinate to flip (e.g. `A3`)\n\n"
                        f"**列/Column:** A B C D E  |  **行/Row:** 1 2 3 4 5\n\n" + grid_text,
            color=0xE74C3C,
        )
        embed.set_footer(text=f"Player: {uname} | 点击 spoiler 标签翻格子 / Click spoiler tags to flip")

        view = MineSweeperView(mine_pos, safe_count, uid, uname)
        await interaction.response.send_message(embed=embed, view=view)

    # ══════════════════════════════════════════════════════════
    # /gmpt-mini idiom — 成语接龙
    # ══════════════════════════════════════════════════════════

    @gmpt_mini_group.command(
        name="idiom",
        description="成语接龙 / Idiom Chain — 接最后一个字开头的成语"
    )
    async def idiom_cmd(self, interaction: discord.Interaction):
        chid = str(interaction.channel_id)

        if chid in self._idiom_sessions and self._idiom_sessions[chid].get("active"):
            return await interaction.response.send_message(
                "本频道已有进行中的成语接龙，先 `/gmpt-mini idiom-stop` 结束！\n"
                "An idiom chain is already active in this channel!",
                ephemeral=True,
            )

        starter = random.choice(IDIOMS)
        last_char = starter[-1]

        self._idiom_sessions[chid] = {
            "active": True,
            "current": starter,
            "last_char": last_char,
            "chain": [starter],
            "used": {starter},
            "streak": 0,
            "current_player": None,
        }

        embed = discord.Embed(
            title="🈶 成语接龙 / Idiom Chain",
            description=(
                f"Bot 出的成语: **{starter}**\n"
                f"请接以 **「{last_char}」** 开头的成语！\n"
                f"Reply with an idiom starting with **「{last_char}」**!\n\n"
                f"说出成语即可（无需指令前缀）/ Just type the idiom (no command)"
            ),
            color=0xE67E22,
        )
        embed.add_field(name="连击 / Streak", value="0", inline=True)
        embed.add_field(name="接龙长度 / Chain Length", value="1", inline=True)
        embed.set_footer(text=f"接不上? 用 /gmpt-mini idiom-pass 跳过 | Use /gmpt-mini idiom-pass to skip")

        await interaction.response.send_message(embed=embed)

    @gmpt_mini_group.command(
        name="idiom-stop",
        description="结束当前频道的成语接龙 / Stop the idiom chain"
    )
    async def idiom_stop_cmd(self, interaction: discord.Interaction):
        chid = str(interaction.channel_id)
        if chid in self._idiom_sessions:
            session = self._idiom_sessions.pop(chid)
            embed = discord.Embed(
                title="🈶 成语接龙结束 / Idiom Chain Ended",
                description=f"接龙长度: **{len(session['chain'])}** 个成语\n"
                            f"最长连击: **{session['streak']}**\n"
                            f"接龙: {' → '.join(session['chain'])}",
                color=0xE67E22,
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("本频道没有进行中的成语接龙 / No active idiom chain.", ephemeral=True)

    @gmpt_mini_group.command(
        name="idiom-pass",
        description="跳过当前回合（扣金币）/ Skip current turn (costs coins)"
    )
    async def idiom_pass_cmd(self, interaction: discord.Interaction):
        chid = str(interaction.channel_id)
        uid = str(interaction.user.id)
        uname = interaction.user.display_name

        if chid not in self._idiom_sessions or not self._idiom_sessions[chid].get("active"):
            return await interaction.response.send_message("本频道没有进行中的成语接龙 / No active idiom chain.", ephemeral=True)

        session = self._idiom_sessions[chid]
        session["streak"] = max(0, session["streak"] - 1)

        # Penalty
        penalty = 30
        bal = get_balance(uid)
        if bal >= penalty:
            add_coins(uid, -penalty, f"成语接龙跳过 / Idiom chain pass")

        # Give new idiom
        new_idiom = random.choice(IDIOMS)
        last_char = new_idiom[-1]
        session["current"] = new_idiom
        session["last_char"] = last_char
        session["chain"].append(new_idiom)
        session["used"].add(new_idiom)
        session["current_player"] = None

        embed = discord.Embed(
            title="🈶 成语接龙 / Idiom Chain",
            description=(
                f"{uname} 跳过了！扣除 🪙 **{penalty}** (如有余额)\n"
                f"新成语: **{new_idiom}**\n"
                f"请接以 **「{last_char}」** 开头的成语！"
            ),
            color=0xE67E22,
        )
        embed.add_field(name="连击 / Streak", value=str(session["streak"]), inline=True)
        embed.add_field(name="接龙长度 / Chain Length", value=str(len(session["chain"])), inline=True)

        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # /gmpt-mini musicquiz — 音乐猜歌
    # ══════════════════════════════════════════════════════════

    @gmpt_mini_group.command(
        name="musicquiz",
        description="音乐猜歌 / Music Quiz — 5 rounds, guess the song!"
    )
    async def musicquiz_cmd(self, interaction: discord.Interaction):
        chid = str(interaction.channel_id)

        if chid in self._musicquiz_sessions and self._musicquiz_sessions[chid].get("active"):
            return await interaction.response.send_message(
                "本频道已有进行中的猜歌游戏 / Music quiz already active!",
                ephemeral=True,
            )

        songs = random.sample(MUSIC_QUIZ_SONGS, min(5, len(MUSIC_QUIZ_SONGS)))
        self._musicquiz_sessions[chid] = {
            "active": True,
            "songs": songs,
            "round": 0,
            "scores": {},
            "current_song": songs[0],
        }

        song = songs[0]
        scrambled = "".join(random.sample(song["title"], len(song["title"])))
        if scrambled == song["title"]:
            scrambled = song["title"][::-1]

        embed = discord.Embed(
            title="🎵 音乐猜歌 / Music Quiz",
            description=(
                f"**第 1/5 轮 / Round 1/5**\n\n"
                f"**打乱标题 / Scrambled:** `{scrambled}`\n"
                f"**Emoji 提示 / Emoji Hint:** {song['emoji_hint']}\n"
                f"**歌词片段 / Lyric:** _{song['lyric_hint']}_\n\n"
                f"直接回复歌名即可！/ Just reply with the song title!"
            ),
            color=0x9B59B6,
        )
        embed.set_footer(text="30 秒计时 / 30s timer | 抢答最快者得分")

        await interaction.response.send_message(embed=embed)

        # Start 30s timer
        self.bot.loop.create_task(self._musicquiz_timer(interaction, chid))

    async def _musicquiz_timer(self, interaction: discord.Interaction, chid: str):
        await asyncio.sleep(30)
        session = self._musicquiz_sessions.get(chid)
        if not session or not session.get("active"):
            return

        session["round"] += 1
        if session["round"] >= 5:
            return await self._musicquiz_end(interaction, chid)

        song = session["songs"][session["round"]]
        session["current_song"] = song
        scrambled = "".join(random.sample(song["title"], len(song["title"])))
        if scrambled == song["title"]:
            scrambled = song["title"][::-1]

        embed = discord.Embed(
            title="🎵 音乐猜歌 / Music Quiz",
            description=(
                f"⏰ 上轮超时！/ Previous round timeout!\n\n"
                f"**第 {session['round']+1}/5 轮 / Round {session['round']+1}/5**\n\n"
                f"**打乱标题 / Scrambled:** `{scrambled}`\n"
                f"**Emoji 提示 / Emoji Hint:** {song['emoji_hint']}\n"
                f"**歌词片段 / Lyric:** _{song['lyric_hint']}_\n\n"
                f"直接回复歌名即可！/ Just reply with the song title!"
            ),
            color=0x9B59B6,
        )
        embed.set_footer(text="30 秒计时 / 30s timer")

        await interaction.channel.send(embed=embed)
        self.bot.loop.create_task(self._musicquiz_timer(interaction, chid))

    async def _musicquiz_end(self, interaction: discord.Interaction, chid: str):
        session = self._musicquiz_sessions.pop(chid, None)
        if not session:
            return

        # Sort scores
        sorted_scores = sorted(session["scores"].items(), key=lambda x: x[1], reverse=True)
        score_text = "\n".join(
            f"**{i+1}.** <@{uid}> — {pts} 分" for i, (uid, pts) in enumerate(sorted_scores[:10])
        ) if sorted_scores else "无人得分 / No one scored"

        # Top player gets bonus
        if sorted_scores:
            top_uid, top_pts = sorted_scores[0]
            bonus = top_pts * 50
            add_coins(top_uid, bonus, f"音乐猜歌冠军 / Music Quiz winner")
            bonus_text = f"\n🏆 冠军 <@{top_uid}> 额外获得 🪙 **{bonus}** 金币！"
        else:
            bonus_text = ""

        embed = discord.Embed(
            title="🎵 音乐猜歌结束 / Music Quiz Over",
            description=f"**最终排名 / Final Rankings:**\n{score_text}{bonus_text}",
            color=0xF1C40F,
        )
        if interaction:
            await interaction.channel.send(embed=embed)
        else:
            channel = self.bot.get_channel(int(chid)) or await self.bot.fetch_channel(int(chid))
            await channel.send(embed=embed)

    # ══════════════════════════════════════════════════════════
    # Message listener for idiom chain and music quiz answers
    # ══════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if getattr(self.bot, "bot_role", "full") != "full":
            return
        if message.author.bot:
            return

        chid = str(message.channel.id)
        content = message.content.strip()

        # ── Idiom chain answer ──
        session = self._idiom_sessions.get(chid)
        if session and session.get("active"):
            if len(content) == 4 and content in IDIOMS:
                if content in session["used"]:
                    await message.add_reaction("⚠️")
                    await message.reply(f"❌ **{content}** 已经用过了！/ Already used!", delete_after=5)
                    return

                if content[0] != session["last_char"]:
                    await message.add_reaction("❌")
                    await message.reply(
                        f"❌ 必须以 **「{session['last_char']}」** 开头！/ Must start with **「{session['last_char']}」**!",
                        delete_after=5,
                    )
                    return

                # Valid answer
                session["streak"] += 1
                session["used"].add(content)
                session["chain"].append(content)
                session["current"] = content
                session["last_char"] = content[-1]
                session["current_player"] = str(message.author.id)

                # Check if ending char has next idioms
                available_next = IDIOM_INDEX.get(content[-1], [])
                available_next = [i for i in available_next if i not in session["used"]]

                uid = str(message.author.id)
                reward = 20 + session["streak"] * 10
                add_coins(uid, reward, f"成语接龙 / Idiom chain (streak {session['streak']})")

                await message.add_reaction("✅")

                if not available_next:
                    # No available idioms — round bonus
                    streak_bonus = session["streak"] * 30
                    add_coins(uid, streak_bonus, f"成语接龙终结奖励 / Idiom chain finisher")
                    embed = discord.Embed(
                        title="🈶 成语接龙 / Idiom Chain",
                        description=(
                            f"**{message.author.display_name}** 答: **{content}** ✅\n"
                            f"🪙 +{reward} (+{streak_bonus} 终结奖励!)\n\n"
                            f"没有以 **「{content[-1]}」** 开头的可用成语了！\n"
                            f"开始新一轮...\n\n"
                            f"No available idioms starting with **「{content[-1]}」**! New round..."
                        ),
                        color=0xF1C40F,
                    )
                    # Start new round
                    new_idiom = random.choice(IDIOMS)
                    session["current"] = new_idiom
                    session["last_char"] = new_idiom[-1]
                    session["chain"] = [new_idiom]
                    session["used"] = {new_idiom}
                    session["streak"] = 0
                    session["current_player"] = None

                    embed.add_field(name="新成语 / New", value=f"**{new_idiom}** → 请接「{new_idiom[-1]}」", inline=False)
                else:
                    embed = discord.Embed(
                        title="🈶 成语接龙 / Idiom Chain",
                        description=(
                            f"**{message.author.display_name}** 答: **{content}** ✅ 🪙 +{reward}\n"
                            f"下一个请接 **「{content[-1]}」** 开头！\n"
                            f"Next: start with **「{content[-1]}」**!"
                        ),
                        color=0xE67E22,
                    )
                    embed.add_field(name="连击 / Streak", value=str(session["streak"]), inline=True)
                    embed.add_field(name="链长 / Chain", value=str(len(session["chain"])), inline=True)

                await message.reply(embed=embed)
                return

        # ── Music quiz answer ──
        quiz = self._musicquiz_sessions.get(chid)
        if quiz and quiz.get("active"):
            song = quiz["current_song"]
            if content == song["title"]:
                uid = str(message.author.id)
                round_num = quiz["round"] + 1
                reward = 100 + (5 - round_num) * 20  # faster = more
                quiz["scores"][uid] = quiz["scores"].get(uid, 0) + 1
                add_coins(uid, reward, f"音乐猜歌答对 / Music Quiz correct")

                await message.add_reaction("🎉")

                quiz["round"] += 1
                if quiz["round"] >= 5:
                    await self._musicquiz_end(None, chid)
                    quiz["active"] = False
                else:
                    quiz["current_song"] = quiz["songs"][quiz["round"]]
                    next_song = quiz["current_song"]
                    scrambled = "".join(random.sample(next_song["title"], len(next_song["title"])))
                    if scrambled == next_song["title"]:
                        scrambled = next_song["title"][::-1]

                    embed = discord.Embed(
                        title="🎵 音乐猜歌 / Music Quiz",
                        description=(
                            f"**{message.author.display_name}** 答对了！✅ 🪙 +{reward}\n\n"
                            f"**第 {quiz['round']+1}/5 轮 / Round {quiz['round']+1}/5**\n\n"
                            f"**打乱标题 / Scrambled:** `{scrambled}`\n"
                            f"**Emoji 提示 / Emoji Hint:** {next_song['emoji_hint']}\n"
                            f"**歌词片段 / Lyric:** _{next_song['lyric_hint']}_"
                        ),
                        color=0x9B59B6,
                    )
                    embed.set_footer(text="30 秒计时 / 30s timer")

                    await message.reply(embed=embed)

                return

        await self.bot.process_commands(message)


# ══════════════════════════════════════════════════════════════
# Mini Guess Number View
# ══════════════════════════════════════════════════════════════

class MiniGuessView(discord.ui.View):
    def __init__(self, answer: int, player_id: str, player_name: str):
        super().__init__(timeout=120)
        self.answer = answer
        self.player_id = player_id
        self.player_name = player_name
        self.attempts = 0
        self.max_attempts = 10
        self.low = 1
        self.high = 100
        self.finished = False
        self._update_buttons()

    def _update_buttons(self):
        self.clear_items()
        mid = (self.low + self.high) // 2
        candidates = set()
        candidates.add(self.low)
        candidates.add(self.high)
        candidates.add(mid)
        candidates.add(self.low + max(1, (self.high - self.low) // 4))
        candidates.add(self.high - max(1, (self.high - self.low) // 4))
        unique = sorted([c for c in candidates if self.low <= c <= self.high])[:5]
        row = 0
        for val in unique:
            btn = discord.ui.Button(
                label=str(val),
                style=discord.ButtonStyle.secondary,
                row=row,
            )
            btn.callback = self._make_guess_callback(val)
            self.add_item(btn)
            row += 1
        if row > 4:
            row = 4
        reset_btn = discord.ui.Button(
            label="🔄 新游戏 / New Game",
            style=discord.ButtonStyle.danger,
            row=row,
        )
        reset_btn.callback = self._reset_callback
        self.add_item(reset_btn)

    def _make_guess_callback(self, guess: int):
        async def callback(interaction: discord.Interaction):
            if str(interaction.user.id) != self.player_id:
                return await interaction.response.send_message("这不是你的游戏！/ Not your game!", ephemeral=True)
            if self.finished:
                return await interaction.response.send_message("游戏已结束 / Game ended.", ephemeral=True)

            self.attempts += 1
            uid = self.player_id

            if guess == self.answer:
                self.finished = True
                reward = 100 * (self.max_attempts - self.attempts + 1)
                add_coins(uid, reward, f"猜数字获胜 / Guess Number win")
                embed = discord.Embed(
                    title="🔢 猜数字 / Number Guessing",
                    description=f"🎉 正确！答案是 **{self.answer}** / Correct! Answer was **{self.answer}**",
                    color=0xF1C40F,
                )
                embed.add_field(name="范围 / Range", value="`1 - 100`", inline=True)
                embed.add_field(name="次数 / Attempts", value=f"{self.attempts}/{self.max_attempts}", inline=True)
                embed.add_field(name="奖励 / Reward", value=f"🪙 {reward:,}", inline=True)
                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(embed=embed, view=self)
            elif self.attempts >= self.max_attempts:
                self.finished = True
                penalty = 30
                bal = get_balance(uid)
                if bal >= penalty:
                    add_coins(uid, -penalty, f"猜数字失败 / Guess Number loss")
                embed = discord.Embed(
                    title="🔢 猜数字 / Number Guessing",
                    description=f"😢 失败！答案是 **{self.answer}** / Game Over! Answer was **{self.answer}**",
                    color=0xE74C3C,
                )
                embed.add_field(name="范围 / Range", value="`1 - 100`", inline=True)
                embed.add_field(name="次数 / Attempts", value=f"{self.attempts}/{self.max_attempts}", inline=True)
                embed.add_field(name="惩罚 / Penalty", value=f"🪙 -{penalty}", inline=True)
                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                if guess < self.answer:
                    self.low = max(self.low, guess + 1)
                    status = "⬆️ 太小 / Too low"
                else:
                    self.high = min(self.high, guess - 1)
                    status = "⬇️ 太大 / Too high"
                self._update_buttons()
                embed = discord.Embed(
                    title="🔢 猜数字 / Number Guessing",
                    description=f"{self.low} - {self.high}",
                    color=0x2ECC71,
                )
                embed.add_field(name="范围 / Range", value="`1 - 100`", inline=True)
                embed.add_field(name="状态 / Status", value=status, inline=True)
                embed.add_field(name="剩余次数 / Left", value=f"**{self.max_attempts - self.attempts}/{self.max_attempts}**", inline=True)
                embed.set_footer(text=f"Player: {self.player_name}")
                await interaction.response.edit_message(embed=embed, view=self)
        return callback

    async def _reset_callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.player_id:
            return await interaction.response.send_message("这不是你的游戏！", ephemeral=True)
        self.answer = random.randint(1, 100)
        self.attempts = 0
        self.low = 1
        self.high = 100
        self.finished = False
        self._update_buttons()
        embed = discord.Embed(
            title="🔢 猜数字 / Number Guessing",
            description="1 - 100 之间的数字，10 次机会！/ Guess 1-100, 10 tries!",
            color=0x2ECC71,
        )
        embed.add_field(name="范围 / Range", value="`1 - 100`", inline=True)
        embed.add_field(name="剩余次数 / Left", value="**10/10**", inline=True)
        embed.set_footer(text=f"Player: {self.player_name}")
        await interaction.response.edit_message(embed=embed, view=self)


    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass

# ══════════════════════════════════════════════════════════════
# MineSweeper View
# ══════════════════════════════════════════════════════════════

COL_LABELS = ["A", "B", "C", "D", "E"]

class MineSweeperView(discord.ui.View):
    def __init__(self, mine_pos: set, safe_count: int, player_id: str, player_name: str):
        super().__init__(timeout=300)
        self.mine_pos = mine_pos
        self.safe_count = safe_count
        self.player_id = player_id
        self.player_name = player_name
        self.revealed: set = set()
        self.finished = False
        self._build_board_buttons()

    def _build_board_buttons(self):
        self.clear_items()
        for r in range(5):
            for c in range(5):
                pos = r * 5 + c
                label = f"{COL_LABELS[c]}{r+1}"
                if pos in self.revealed:
                    if pos in self.mine_pos:
                        label = f"{COL_LABELS[c]}{r+1} 💣"
                    else:
                        label = f"{COL_LABELS[c]}{r+1} 🟩"
                    btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=r, disabled=True)
                else:
                    btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=r)
                    btn.callback = self._make_flip_callback(pos, r, c)
                self.add_item(btn)

    def _make_flip_callback(self, pos: int, row: int, col: int):
        async def callback(interaction: discord.Interaction):
            if str(interaction.user.id) != self.player_id:
                return await interaction.response.send_message("这不是你的游戏！/ Not your game!", ephemeral=True)
            if self.finished:
                return await interaction.response.send_message("游戏已结束 / Game ended.", ephemeral=True)
            if pos in self.revealed:
                return await interaction.response.send_message("已翻开 / Already flipped.", ephemeral=True)

            uid = self.player_id
            self.revealed.add(pos)

            if pos in self.mine_pos:
                self.finished = True
                penalty = 100
                bal = get_balance(uid)
                if bal >= penalty:
                    add_coins(uid, -penalty, "扫雷踩雷 / Minesweeper mine hit")
                self._build_board_buttons()
                for child in self.children:
                    child.disabled = True

                # Reveal all mines
                rows = []
                for r2 in range(5):
                    cells = []
                    for c2 in range(5):
                        p = r2 * 5 + c2
                        if p in self.mine_pos:
                            cells.append("💣")
                        elif p in self.revealed:
                            cells.append("🟩")
                        else:
                            cells.append("⬜")
                    rows.append(" ".join(cells))
                grid_text = "\n".join(rows)

                embed = discord.Embed(
                    title="💣 扫雷 / Minesweeper",
                    description=f"**踩雷了！** {COL_LABELS[col]}{row+1} 是 💣\n"
                                f"扣 🪙 **{penalty}** 金币！\n\n{grid_text}",
                    color=0xE74C3C,
                )
                embed.set_footer(text=f"Player: {self.player_name} | Game Over")
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                self.safe_count -= 1
                if self.safe_count <= 0:
                    self.finished = True
                    reward = 500
                    add_coins(uid, reward, "扫雷通关 / Minesweeper cleared")
                    self._build_board_buttons()
                    for child in self.children:
                        child.disabled = True

                    rows = []
                    for r2 in range(5):
                        cells = []
                        for c2 in range(5):
                            p = r2 * 5 + c2
                            if p in self.mine_pos:
                                cells.append("💣")
                            else:
                                cells.append("🟩")
                        rows.append(" ".join(cells))
                    grid_text = "\n".join(rows)

                    embed = discord.Embed(
                        title="💣 扫雷 / Minesweeper",
                        description=f"🎉 **通关！** 翻完了所有安全格子！\n"
                                    f"奖励 🪙 **{reward}** 金币！\n\n{grid_text}",
                        color=0xF1C40F,
                    )
                    embed.set_footer(text=f"Player: {self.player_name} | Cleared!")
                    await interaction.response.edit_message(embed=embed, view=self)
                else:
                    self._build_board_buttons()
                    embed = discord.Embed(
                        title="💣 扫雷 / Minesweeper",
                        description=f"翻开 {COL_LABELS[col]}{row+1}: 🟩 安全！\n"
                                    f"剩余安全格: **{self.safe_count}**\n"
                                    f"Safe! Remaining safe: **{self.safe_count}**",
                        color=0x2ECC71,
                    )
                    embed.set_footer(text=f"Player: {self.player_name}")
                    await interaction.response.edit_message(embed=embed, view=self)
        return callback


    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass

# ══════════════════════════════════════════════════════════════
# Cog setup
# ══════════════════════════════════════════════════════════════

async def setup(bot):
    await bot.add_cog(MiniGames(bot))
