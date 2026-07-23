"""
GMPT Bot — Social / Mini Games (Roll, Guess Number, Truth or Dare, Whisper, Roulette)
Bilingual (中文 / English)
"""
import asyncio
import random
import re
import time
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
from utils.cog_base import CogBase
from cogs.economy import get_balance, add_coins
from config import WHISPER_CHANNEL_ID
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ── 辅助函数 ──
def _format_coins(amount: int) -> str:
    return f"🪙 {amount:,}"

def _get_user_or_create(uid: str, uname: str):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (discord_id, username) VALUES (?,?) ON CONFLICT(discord_id) DO NOTHING",
        (uid, uname),
    )
    cur.execute("SELECT score, id FROM users WHERE discord_id=?", (uid,))
    row = cur.fetchone()
    conn.close()
    return row

# ── Whisper counter (SQLite) ──
def _init_whisper_table():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS whispers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit(); conn.close()

_init_whisper_table()


# ══════════════════════════════════════════════════════════════
# Truth or Dare question pool
# ══════════════════════════════════════════════════════════════

TRUTH_QUESTIONS = [
    # 30% English
    {"zh": "你最近一次说谎是什么时候？说了什么？", "en": "When was the last time you lied? What did you lie about?"},
    {"zh": "你在游戏里做过最坑队友的事是什么？", "en": "What's the worst thing you've done to a teammate in a game?"},
    {"zh": "你最尴尬的一次语音聊天经历是什么？", "en": "What's your most embarrassing voice chat experience?"},
    {"zh": "你有没有偷偷喜欢过服务器里的某个人？", "en": "Have you ever secretly liked someone in this server?"},
    {"zh": "你最长一次连续打游戏是多少小时？", "en": "What's the longest gaming session you've ever had?"},
    {"zh": "你用过最奇葩的借口逃避开黑是什么？", "en": "What's the weirdest excuse you've used to dodge a game session?"},
    {"zh": "If you could swap lives with anyone in this server for a day, who would it be?", "en": "If you could swap lives with anyone in this server for a day, who would it be?"},
    {"zh": "What's the most embarrassing song on your playlist?", "en": "What's the most embarrassing song on your playlist?"},
    {"zh": "你觉得自己LOL里最菜的是哪个位置？", "en": "Which role are you worst at in League?"},
    {"zh": "你有没有为了游戏氪金而后悔的经历？花了多少？", "en": "Have you ever regretted spending money on a game? How much?"},
    {"zh": "你在Discord里偷偷静音过谁？为什么？", "en": "Have you ever secretly muted someone on Discord? Why?"},
    {"zh": "Have you ever rage-quit a game and blamed your teammates?", "en": "Have you ever rage-quit a game and blamed your teammates?"},
    {"zh": "你最近一次哭是因为什么？", "en": "When was the last time you cried and why?"},
    {"zh": "What's one thing you wish people in this server knew about you?", "en": "What's one thing you wish people in this server knew about you?"},
    {"zh": "你上次对别人说'我爱你'是什么时候？对谁？", "en": "When was the last time you said 'I love you' and to whom?"},
    {"zh": "你有没有假装在线但其实在打其他游戏？", "en": "Have you ever pretended to be online but were actually playing a different game?"},
    {"zh": "你吃过最奇怪的食物是什么？", "en": "What's the strangest food you've ever eaten?"},
    {"zh": "If you had to delete one game forever, which would it be?", "en": "If you had to delete one game forever, which would it be?"},
]

DARE_QUESTIONS = [
    # 30% English
    {"zh": "在语音频道里唱一段歌（至少30秒）", "en": "Sing a song in voice chat (at least 30 seconds)."},
    {"zh": "把你的Discord状态改成'我是最菜的'并保持10分钟", "en": "Change your Discord status to 'I am the worst' for 10 minutes."},
    {"zh": "发一张你最丑的自拍到聊天频道", "en": "Post your ugliest selfie in the chat channel."},
    {"zh": "用全大写英文在频道里打10条消息", "en": "Type 10 messages in ALL CAPS in the chat channel."},
    {"zh": "给服务器里随机一个人发DM说你暗恋TA", "en": "DM a random person in the server saying you have a crush on them."},
    {"zh": "在语音里用机器人语调说话直到下一局游戏结束", "en": "Speak in a robot voice in voice chat until the next game ends."},
    {"zh": "把头像换成皮卡丘并保持24小时", "en": "Change your profile picture to Pikachu for 24 hours."},
    {"zh": "在频道里发一句'我是小可爱'", "en": "Post 'I am a cutie' in the chat channel."},
    {"zh": "Do 10 push-ups on camera (if comfortable) or just say you did", "en": "Do 10 push-ups on camera (if comfortable) or just say you did."},
    {"zh": "模仿你最讨厌的英雄说一句话", "en": "Imitate your most hated champion with one line."},
    {"zh": "在聊天频道只用emoji交流接下来的5分钟", "en": "Only communicate using emojis in chat for the next 5 minutes."},
    {"zh": "把你的游戏内名称改成'求带飞'并打一局", "en": "Change your in-game name to 'CarryMePlz' and play one game."},
    {"zh": "Pretend to be a news reporter and announce the last match result dramatically in voice chat", "en": "Pretend to be a news reporter and announce the last match result dramatically in voice chat."},
    {"zh": "给服务器Owner发一条夸TA的消息", "en": "Send a compliment message to the server owner."},
    {"zh": "在语音里用方言说一段自我介绍", "en": "Introduce yourself in your local dialect/accent in voice chat."},
    {"zh": "把你的Discord昵称改成'XX的小跟班'（XX是随机队友名）保持1小时", "en": "Change your Discord nickname to '[random player]'s Sidekick' for 1 hour."},
    {"zh": "Rap your favorite champion's ability names in voice chat", "en": "Rap your favorite champion's ability names in voice chat."},
    {"zh": "发一张你桌面的截图到聊天频道", "en": "Post a screenshot of your desktop in the chat channel."},
]


class Games(CogBase):
    """社交娱乐小游戏 / Social Mini Games"""

    def __init__(self, bot):
        self.bot = bot
        self._whispers: dict[str, float] = {}  # cooldown: user_id -> timestamp

    # ══════════════════════════════════════════════════════════
    # /gmpt-roll
    # ══════════════════════════════════════════════════════════
    @app_commands.command(
        name="gmpt-roll",
        description="掷骰子 | Roll dice (e.g. 2d6, 1d20)",
    )
    @app_commands.describe(dice="骰子表达式 / Dice expression (NdM format, N≤20, M≤100)")
    async def roll(self, interaction: discord.Interaction, dice: str):
        m = re.fullmatch(r"(\d+)[dD](\d+)", dice.strip())
        if not m:
            return await interaction.response.send_message(
                "请使用 NdM 格式（如 1d6, 2d20）/ Use NdM format (e.g. 1d6, 2d20)",
                ephemeral=True,
            )

        n, faces = int(m.group(1)), int(m.group(2))
        if n < 1 or n > 20:
            return await interaction.response.send_message(
                "骰子数量限制 1-20 / Dice count limited to 1-20",
                ephemeral=True,
            )
        if faces < 2 or faces > 100:
            return await interaction.response.send_message(
                "骰子面数限制 2-100 / Face count limited to 2-100",
                ephemeral=True,
            )

        results = [random.randint(1, faces) for _ in range(n)]
        total = sum(results)

        embed = discord.Embed(
            title="🎲 骰子结果 / Dice Roll",
            color=0x3498DB,
        )
        embed.add_field(name="表达式 / Expression", value=f"`{n}d{faces}`", inline=True)
        embed.add_field(name="单骰 / Dice", value=str(results), inline=True)
        embed.add_field(name="总和 / Total", value=_format_coins(total).replace("🪙 ", ""), inline=True)
        embed.set_footer(text=f"Rolled by {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # /gmpt-guess-number
    # ══════════════════════════════════════════════════════════
    @app_commands.command(
        name="gmpt-guess-number",
        description="猜数字游戏 | Number guessing game (default 1-100)",
    )
    @app_commands.describe(max_num="最大数字 / Max number (default: 100)")
    async def guess_number(self, interaction: discord.Interaction, max_num: int = 100):
        if max_num < 10 or max_num > 10000:
            return await interaction.response.send_message(
                "范围限制 10-10000 / Range must be 10-10000",
                ephemeral=True,
            )

        answer = random.randint(1, max_num)
        uid = str(interaction.user.id)

        embed = discord.Embed(
            title="🔢 猜数字 / Number Guessing",
            description=f"1 - {max_num} 之间的数字\nGuess a number between 1 and {max_num}.",
            color=0x2ECC71,
        )
        embed.add_field(name="范围 / Range", value=f"`1 - {max_num}`", inline=True)
        embed.add_field(name="状态 / Status", value="🤔 等待猜测 / Waiting for guess", inline=True)
        embed.add_field(name="剩余次数 / Attempts Left", value=f"**10/10**", inline=True)
        embed.set_footer(text=f"Player: {interaction.user.display_name}")

        view = GuessNumberView(answer, max_num, uid, interaction.user.display_name)
        await interaction.response.send_message(embed=embed, view=view)

    # ══════════════════════════════════════════════════════════
    # /gmpt-truth-dare
    # ══════════════════════════════════════════════════════════
    @app_commands.command(
        name="gmpt-truth-dare",
        description="真心话大冒险 | Truth or Dare",
    )
    @app_commands.describe(mode="模式: truth / dare / random（留空=随机）")
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.user.id)
    async def truth_dare(self, interaction: discord.Interaction, mode: str = "random"):
        mode = mode.strip().lower()
        if mode not in ("truth", "dare", "random"):
            return await interaction.response.send_message(
                "模式: truth / dare / random / Mode: truth, dare, or random",
                ephemeral=True,
            )

        if mode == "random":
            mode = random.choice(["truth", "dare"])

        if mode == "truth":
            q = random.choice(TRUTH_QUESTIONS)
            title = "📝 真心话 / Truth"
            question_text = f"**{q['zh']}**\n\n*{q['en']}*"
            color = 0x9B59B6
        else:
            q = random.choice(DARE_QUESTIONS)
            title = "🎯 大冒险 / Dare"
            question_text = f"**{q['zh']}**\n\n*{q['en']}*"
            color = 0xE74C3C

        embed = discord.Embed(title=title, color=color)
        embed.add_field(name="题目 / Question", value=question_text, inline=False)
        embed.set_footer(text=f"Requested by {interaction.user.display_name} | Mode: {mode}")

        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # /gmpt-whisper
    # ══════════════════════════════════════════════════════════
    @app_commands.command(
        name="gmpt-whisper",
        description="匿名投树洞 | Anonymous confession",
    )
    @app_commands.describe(message="你想说的话 / Your message (max 500 chars)")
    async def whisper(self, interaction: discord.Interaction, message: str):
        # 检查频道是否配置
        if not WHISPER_CHANNEL_ID:
            return await interaction.response.send_message(
                "树洞频道未配置，请联系管理员 / Whisper channel not configured, contact admin.",
                ephemeral=True,
            )

        if len(message) > 500:
            return await interaction.response.send_message(
                "最多 500 字 / Max 500 characters",
                ephemeral=True,
            )

        uid = str(interaction.user.id)

        # 写入数据库
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO whispers (author_id, message) VALUES (?, ?)",
            (uid, message),
        )
        wid = cur.lastrowid
        conn.commit(); conn.close()

        # 发送到树洞频道
        channel = self.bot.get_channel(int(WHISPER_CHANNEL_ID))
        if not channel:
            return await interaction.response.send_message(
                "树洞频道未找到，请联系管理员 / Whisper channel not found, contact admin.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title="🕊️ 树洞 / Confession",
            description=message,
            color=0x95A5A6,
        )
        embed.set_footer(text=f"第 #{wid} 号匿名 | Anonymous Whisper #{wid}")

        await channel.send(embed=embed)
        await interaction.response.send_message(
            f"你的树洞已投递！编号 #{wid} / Your whisper has been posted! ID #{wid}",
            ephemeral=True,
        )

    # ══════════════════════════════════════════════════════════
    # /gmpt-roulette
    # ══════════════════════════════════════════════════════════
    @app_commands.command(
        name="gmpt-roulette",
        description="轮盘赌 | Roulette (Red/Black/Green)",
    )
    @app_commands.describe(bet="下注金额 / Bet amount")
    async def roulette(self, interaction: discord.Interaction, bet: int):
        uid = str(interaction.user.id)
        bal = get_balance(uid)

        if bet < 10:
            return await interaction.response.send_message(
                "最低下注 10 金币 / Minimum bet is 10 coins.",
                ephemeral=True,
            )
        if bet > bal:
            return await interaction.response.send_message(
                f"余额不足！你有 {_format_coins(bal)} / Insufficient balance! You have {_format_coins(bal)}.",
                ephemeral=True,
            )

        view = RouletteColorView(uid, bet, interaction.user.display_name)
        embed = discord.Embed(
            title="🎡 轮盘 / Roulette",
            description=f"选择颜色 / Choose a color:\n\n"
                        f"🔴 **Red** — 1:1 (红)\n"
                        f"⚫ **Black** — 1:1 (黑)\n"
                        f"🟢 **Green** — 14:1 (绿)\n\n"
                        f"赌注 / Bet: {_format_coins(bet)} | 余额 / Balance: {_format_coins(bal)}",
            color=0xF1C40F,
        )
        embed.set_footer(text=f"Player: {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed, view=view)


# ══════════════════════════════════════════════════════════════
# Guess Number View (buttons for guessing)
# ══════════════════════════════════════════════════════════════

class GuessNumberView(discord.ui.View):
    def __init__(self, answer: int, max_num: int, player_id: str, player_name: str):
        super().__init__(timeout=120)
        self.answer = answer
        self.max_num = max_num
        self.player_id = player_id
        self.player_name = player_name
        self.attempts = 0
        self.max_attempts = 10
        self.low = 1
        self.high = max_num
        self.finished = False
        self._update_buttons()

    def _update_buttons(self):
        self.clear_items()
        mid = (self.low + self.high) // 2

        # 根据当前范围生成 5 个猜测按钮
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

        # Reset button
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
                return await interaction.response.send_message(
                    "这不是你的游戏！/ This is not your game!",
                    ephemeral=True,
                )
            if self.finished:
                return await interaction.response.send_message(
                    "游戏已结束 / Game already ended.",
                    ephemeral=True,
                )

            self.attempts += 1
            uid = self.player_id

            if guess == self.answer:
                self.finished = True
                reward = 100 * (self.max_attempts - self.attempts + 1)
                add_coins(uid, reward, f"猜数字获胜 / Guess Number win")
                embed = self._build_result_embed(
                    "🎉 正确！/ Correct!", reward, None,
                )
                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(embed=embed, view=self)
            elif self.attempts >= self.max_attempts:
                self.finished = True
                embed = self._build_result_embed(
                    f"😢 失败！答案是 {self.answer} / Game Over! Answer was {self.answer}",
                    0, self.answer,
                )
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
                embed = self._build_embed(status)
                await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def _reset_callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.player_id:
            return await interaction.response.send_message("这不是你的游戏！", ephemeral=True)
        self.answer = random.randint(1, self.max_num)
        self.attempts = 0
        self.low = 1
        self.high = self.max_num
        self.finished = False
        self._update_buttons()
        embed = self._build_embed("🤔 等待猜测 / Waiting for guess")
        await interaction.response.edit_message(embed=embed, view=self)

    def _build_embed(self, status: str) -> discord.Embed:
        embed = discord.Embed(
            title="🔢 猜数字 / Number Guessing",
            description=f"{self.low} - {self.high}",
            color=0x2ECC71,
        )
        embed.add_field(name="范围 / Range", value=f"`1 - {self.max_num}`", inline=True)
        embed.add_field(name="状态 / Status", value=status, inline=True)
        remaining = self.max_attempts - self.attempts
        embed.add_field(name="剩余次数 / Attempts Left", value=f"**{remaining}/{self.max_attempts}**", inline=True)
        embed.set_footer(text=f"Player: {self.player_name}")
        return embed

    def _build_result_embed(self, status: str, reward: int, answer: int | None) -> discord.Embed:
        embed = discord.Embed(
            title="🔢 猜数字 / Number Guessing",
            color=0xF1C40F if reward > 0 else 0xE74C3C,
        )
        embed.add_field(name="范围 / Range", value=f"`1 - {self.max_num}`", inline=True)
        embed.add_field(name="状态 / Status", value=status, inline=True)
        embed.add_field(name="剩余次数 / Attempts Left", value=f"**{self.max_attempts - self.attempts}/{self.max_attempts}**", inline=True)
        if reward > 0:
            embed.add_field(name="奖励 / Reward", value=_format_coins(reward), inline=True)
        if answer is not None:
            embed.add_field(name="答案 / Answer", value=str(answer), inline=True)
        embed.set_footer(text=f"Player: {self.player_name}")
        return embed

    async def on_timeout(self):
        if not self.finished:
            for child in self.children:
                child.disabled = True
            embed = self._build_embed("⏰ 超时 / Timeout")
            if self.message:
                await self.message.edit(embed=embed, view=self)


# ══════════════════════════════════════════════════════════════
# Roulette Color Select View
# ══════════════════════════════════════════════════════════════

class RouletteColorView(discord.ui.View):
    def __init__(self, player_id: str, bet: int, player_name: str):
        super().__init__(timeout=60)
        self.player_id = player_id
        self.bet = bet
        self.player_name = player_name
        self.finished = False

    @discord.ui.button(label="🔴 Red / 红", style=discord.ButtonStyle.red)
    async def red_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, "red")

    @discord.ui.button(label="⚫ Black / 黑", style=discord.ButtonStyle.secondary)
    async def black_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, "black")

    @discord.ui.button(label="🟢 Green / 绿", style=discord.ButtonStyle.green, row=1)
    async def green_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, "green")

    async def _resolve(self, interaction: discord.Interaction, choice: str):
        if str(interaction.user.id) != self.player_id:
            return await interaction.response.send_message("这不是你的赌局！/ Not your bet!", ephemeral=True)
        if self.finished:
            return await interaction.response.send_message("赌局已结束 / Bet already resolved.", ephemeral=True)

        self.finished = True
        uid = self.player_id

        # Roulette spin 0-36
        # 0 = green
        # 1-10: odd=red, even=black
        # 11-18: odd=black, even=red
        # 19-28: odd=red, even=black
        # 29-36: odd=black, even=red
        number = random.randint(0, 36)

        if number == 0:
            result_color = "green"
        elif (1 <= number <= 10) or (19 <= number <= 28):
            result_color = "red" if number % 2 == 1 else "black"
        else:
            result_color = "red" if number % 2 == 0 else "black"

        color_emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}

        win = (choice == result_color)
        if win:
            if result_color == "green":
                multiplier = 15  # net: +14*bet (15x total)
                profit = self.bet * 14
            else:
                multiplier = 2  # net: +bet (2x total)
                profit = self.bet
            add_coins(uid, profit, f"轮盘赌获胜 / Roulette win ({choice})")
            pnl_text = f"🪙 +{profit:,}"
        else:
            profit = -self.bet
            add_coins(uid, profit, f"轮盘赌输 / Roulette loss ({choice}, {result_color})")
            pnl_text = f"🪙 {profit:,}"

        bal = get_balance(uid)

        embed = discord.Embed(
            title="🎡 轮盘 / Roulette",
            color=0xF1C40F if win else 0xE74C3C,
        )
        embed.add_field(
            name="结果 / Result",
            value=f"🎯 **{number}** {color_emoji.get(result_color, '')}",
            inline=True,
        )
        embed.add_field(name="你的选择 / Your Choice", value=f"{color_emoji.get(choice, '')} {choice}", inline=True)
        embed.add_field(name="赌注 / Bet", value=_format_coins(self.bet), inline=True)
        embed.add_field(name="盈亏 / P/L", value=pnl_text, inline=True)
        embed.add_field(name="余额 / Balance", value=_format_coins(bal), inline=True)
        embed.set_footer(text=f"Player: {self.player_name}")

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if not self.finished:
            for child in self.children:
                child.disabled = True
            if self.message:
                embed = discord.Embed(
                    title="🎡 轮盘 / Roulette",
                    description="⏰ 超时 / Timed out",
                    color=0x95A5A6,
                )
                await self.message.edit(embed=embed, view=self)


# ══════════════════════════════════════════════════════════════
# Cog setup
# ══════════════════════════════════════════════════════════════

async def setup(bot):
    await bot.add_cog(Games(bot))
