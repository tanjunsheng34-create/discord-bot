"""
GMPT Bot — 基础赚钱5大件 / Basic Income Jobs
/gmpt-work  打工赚钱 / Work
/gmpt-rob   打劫其他用户 / Rob
/gmpt-beg   乞讨 / Beg
/gmpt-fish  钓鱼 / Fish
/gmpt-hunt  狩猎 / Hunt

Bilingual (中文 / English)
"""
import asyncio
import random
import time
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db, get_db_ctx
from utils.cog_base import CogBase
from cogs.economy import get_balance, add_coins

logger = logging.getLogger(__name__)


def _format_coins(amount: int) -> str:
    return f"🪙 {amount:,}"


# ========== Module-level cooldown logic (shared by View buttons & slash commands) ==========

COOLDOWNS = {
    "work": 3600,     # 1 hour
    "rob": 7200,      # 2 hours
    "beg": 300,       # 5 min
    "fish": 180,      # 3 min
    "hunt": 300,      # 5 min
    "treasure": 600,  # 10 min
    "busk": 240,      # 4 min
    "stock": 900,     # 15 min
}

COOLDOWN_LABELS = {
    "work": "1小时 / 1h",
    "rob": "2小时 / 2h",
    "beg": "5分钟 / 5min",
    "fish": "3分钟 / 3min",
    "hunt": "5分钟 / 5min",
    "treasure": "10分钟 / 10min",
    "busk": "4分钟 / 4min",
    "stock": "15分钟 / 15min",
}


def _get_cd_remaining(user_id: str, job: str) -> int:
    """Return remaining cooldown seconds (0 = ready)."""
    cd_sec = COOLDOWNS.get(job, 0)
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT last_used FROM job_cooldowns WHERE user_id=? AND job_type=?",
            (user_id, job),
        )
        row = cur.fetchone()
    if not row:
        return 0
    elapsed = time.time() - row["last_used"]
    remaining = int(cd_sec - elapsed)
    return max(0, remaining)


def _update_cd(user_id: str, job: str):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO job_cooldowns (user_id, job_type, last_used) VALUES (?,?,?)",
            (user_id, job, time.time()),
        )
        conn.commit()


def _format_cd(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m{seconds % 60}s"
    else:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h{m}"


async def _animate_job(interaction: discord.Interaction, frames: list[str], embed: discord.Embed):
    """Show emoji job animation then edit to result embed."""
    msg = await interaction.followup.send(frames[0])
    for frame in frames[1:]:
        await asyncio.sleep(0.6)
        await msg.edit(content=frame)
    await asyncio.sleep(0.4)
    await msg.edit(content=None, embed=embed)


def _add_job_xp(uid: str) -> tuple[bool, int]:
    """Add 10-30 random job_xp after a job. Level up if job_xp >= job_level * 100.

    Returns (leveled_up, new_job_level).
    """
    gain = random.randint(10, 30)
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT job_level, job_xp FROM users WHERE discord_id=?",
            (uid,),
        )
        row = cur.fetchone()
        if not row:
            return False, 1
        job_level = row["job_level"] or 1
        job_xp = row["job_xp"] or 0
        job_xp += gain
        leveled_up = False
        while job_xp >= job_level * 100:
            job_xp -= job_level * 100
            job_level += 1
            leveled_up = True
        cur.execute(
            "UPDATE users SET job_level=?, job_xp=? WHERE discord_id=?",
            (job_level, job_xp, uid),
        )
        conn.commit()
    return leveled_up, job_level


async def _handle_job_xp(uid: str, interaction: discord.Interaction):
    """Add job XP and send level-up followup message if leveled up."""
    leveled_up, new_level = _add_job_xp(uid)
    if leveled_up:
        await interaction.followup.send(
            f"🎉 打工等级提升！你现在是 Lv.{new_level} 打工达人！"
        )


# ════ Money Effect & Helper Functions ════

def _money_effect(amount: int) -> str:
    """Return money visual effect based on amount."""
    if amount <= 0:
        return "💸 亏空了！/ Broke!"
    if amount <= 30:
        return "💰 / 💰"
    if amount <= 100:
        return "💰💰 / 💰💰"
    if amount <= 500:
        return "💰💰💰 / 💰💰💰"
    if amount <= 1500:
        return "💰💰💰💰💰 / 💰💰💰💰💰"
    return "💰💰💰💰💰💰💰💰 / 💰💰💰💰💰💰💰💰"


def _lose_effect(amount: int) -> str:
    """Return lose money visual effect."""
    if amount <= 100:
        return "💸 / 💸"
    if amount <= 500:
        return "💸💸💸 / 💸💸💸"
    return "💸💸💸💸💸 / 💸💸💸💸💸"


def _result_color(job: str, earned: int) -> int:
    """Return embed color: green for profit, red for loss, yellow for member-hit."""
    if job == "hit_person":
        return 0xF1C40F  # yellow
    if earned > 0:
        return 0x2ECC71   # green
    if earned < 0:
        return 0xE74C3C   # red
    return 0x95A5A6       # gray / neutral


def _add_rare_border(embed: discord.Embed, uname: str) -> discord.Embed:
    """Add rare event special border/decoration (5% proc)."""
    if random.random() >= 0.05:
        return embed
    stars = ["⭐✨⭐✨ 稀有事件触发！/ Rare Event! ✨⭐✨⭐",
             "🌟✨💫 天选之人！/ Chosen One! 💫✨🌟",
             "💎⚡🔥 鸿运当头！/ Jackpot! 🔥⚡💎",
             "🎪🎭🎯 奇迹降临！/ Miracle! 🎯🎭🎪"]
    border = random.choice(stars)
    embed.description = f"**{border}**\n\n{embed.description}\n\n**{border}**"
    embed.color = 0xFFD700  # gold
    return embed


# ════ Module-Level Job Handlers (shared by View buttons & slash commands) ════

async def _do_hunt(guild, uname: str, uid: str) -> tuple[discord.Embed, str | None]:
    """Enhanced hunt: normal prey + chance to hit a member."""
    roll = random.random()
    injured = random.random() < 0.15

    # ---- Normal prey ----
    if roll < 0.03:
        prey_name = "传说猎物 / Legendary Prey"
        prey_emoji = "🐉"
        earned = random.randint(1000, 3000)
    elif roll < 0.20:
        prey_name = "野猪 / Wild Boar"
        prey_emoji = "🐗"
        earned = random.randint(200, 400)
    elif roll < 0.50:
        prey_name = "鹿 / Deer"
        prey_emoji = "🦌"
        earned = random.randint(80, 150)
    elif roll < 0.80:
        prey_name = "兔子 / Rabbit"
        prey_emoji = "🐇"
        earned = random.randint(20, 50)
    else:
        prey_name = "空手而归 / Empty-handed"
        prey_emoji = "🌿"
        earned = 0

    # ---- Hit a person event (12% independent) ----
    hit_desc = None
    if guild and random.random() < 0.12:
        members = [m for m in guild.members if not m.bot and m.display_name != uname]
        if members:
            victim = random.choice(members)
            hit_flavors = [
                f"箭射偏了，射中了路过的 **{victim.display_name}** 的屁股！🍑",
                f"追野猪追太猛，一头撞上了 **{victim.display_name}**！💥",
                f"回旋镖没接住，砸到了 **{victim.display_name}** 的脑袋！🤕",
                f"弓箭脱手飞出去，正中 **{victim.display_name}** 的膝盖！🦵",
                f"被野猪追着跑，把 **{victim.display_name}** 撞进了泥坑！💦",
                f"甩出的捕兽夹夹住了 **{victim.display_name}** 的脚！🪤",
                f"猎枪走火，子弹擦过 **{victim.display_name}** 的帽檐！🎩",
            ]
            hit_desc = random.choice(hit_flavors)
            penalty = random.randint(100, 300)
            earned = max(0, earned - penalty)
            # Compensate victim
            add_coins(str(victim.id), penalty, f"被 {uname} 误伤赔偿 / Hit by {uname} compensation")

    if earned > 0:
        add_coins(uid, earned, f"狩猎: {prey_name} / Hunting: {prey_name}")
    _update_cd(uid, "hunt")
    bal = get_balance(uid)

    # Build embed
    parts = []
    if earned > 0:
        parts.append(f"{uname} 猎到了 {prey_emoji} **{prey_name}**！卖得 🪙 **{earned:,}** 金币！")
        parts.append(f"Hunted {prey_emoji} **{prey_name}**! Sold for 🪙 **{earned:,}** coins!")
    else:
        parts.append(f"{uname} 在森林里转了一圈，什么都没找到...")
        parts.append("Wandered the forest, found nothing...")

    money_fx = _money_effect(earned) if earned > 0 else ""
    if hit_desc:
        parts.append(f"\n💥 **误伤事件！** {hit_desc}")
        parts.append(f"赔偿 🪙 {penalty:,} / Paid 🪙 {penalty:,} compensation")
        color = _result_color("hit_person", 0)
    elif injured:
        parts.append("\n\n🤕 **受伤了！** 狩猎冷却延长 10 分钟。\n**Injured!** Hunt cooldown extended by 10 min.")
        color = 0xE74C3C
    elif earned > 0:
        color = _result_color("hunt", earned)
    else:
        color = _result_color("hunt", 0)

    desc = "\n".join(parts)
    embed = discord.Embed(title=f"🏹 {uname} 狩猎 / Hunting", description=desc, color=color)
    if money_fx:
        embed.add_field(name="🪙 金钱特效", value=money_fx, inline=False)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.set_footer(text="狩猎冷却 5 分钟 / Hunt cooldown: 5 min")

    if hit_desc:
        embed.set_thumbnail(url=victim.avatar.url) if victim.avatar else None
    _add_rare_border(embed, uname)

    hit_msg = None
    if hit_desc:
        hit_msg = f"💥 {victim.mention} 被 **{uname}** 误伤！获得赔偿 🪙 {penalty:,} / You were hit by **{uname}**! Compensation: 🪙 {penalty:,}"
    return embed, hit_msg


async def _do_treasure(guild, uname: str, uid: str) -> discord.Embed:
    """Treasure hunt: high variance, big wins or empty."""
    roll = random.random()

    if roll < 0.03:
        treasure = "远古神器 / Ancient Artifact"
        emoji = "👑"
        earned = random.randint(5000, 15000)
    elif roll < 0.10:
        treasure = "海盗宝藏 / Pirate Treasure"
        emoji = "🏴‍☠️"
        earned = random.randint(2000, 5000)
    elif roll < 0.30:
        treasure = "金矿脉 / Gold Vein"
        emoji = "💎"
        earned = random.randint(500, 2000)
    elif roll < 0.60:
        treasure = "古代银币 / Ancient Coins"
        emoji = "🪙"
        earned = random.randint(100, 500)
    elif roll < 0.80:
        treasure = "生锈铁钉 / Rusty Nails"
        emoji = "🔩"
        earned = random.randint(1, 30)
    elif roll < 0.90:
        treasure = "什么都没有 / Nothing"
        emoji = "🕳️"
        earned = 0
    else:
        treasure = "陷阱！/ Trap!"
        emoji = "💣"
        earned = -random.randint(200, 1000)

    if earned > 0:
        add_coins(uid, earned, f"寻宝: {treasure} / Treasure: {treasure}")
    elif earned < 0:
        my_bal = get_balance(uid)
        penalty = min(abs(earned), my_bal // 2)
        penalty = max(penalty, 1)
        add_coins(uid, -penalty, "寻宝触雷 / Treasure trap triggered")
        earned = -penalty

    _update_cd(uid, "treasure")
    bal = get_balance(uid)

    if earned > 0:
        desc = (f"{uname} 🗺️ 挖到了 {emoji} **{treasure}**！\n"
                f"价值 🪙 **{earned:,}** 金币！\n\n"
                f"Found {emoji} **{treasure}**! Worth 🪙 **{earned:,}** coins!")
        money_fx = _money_effect(earned)
    elif earned < 0:
        desc = (f"{uname} 🗺️ 触发了 {emoji} **陷阱**！\n"
                f"损失 🪙 **{abs(earned):,}** 金币！\n\n"
                f"Triggered {emoji} **Trap**! Lost 🪙 **{abs(earned):,}** coins!")
        money_fx = _lose_effect(abs(earned))
    else:
        desc = (f"{uname} 🗺️ 挖了半天，{emoji} 什么都没找到...\n"
                f"Dug for hours, {emoji} found nothing...")
        money_fx = ""

    color = _result_color("treasure", earned)
    embed = discord.Embed(title=f"🗺️ {uname} 寻宝 / Treasure Hunt", description=desc, color=color)
    if money_fx:
        embed.add_field(name="🪙 特效", value=money_fx, inline=False)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.set_footer(text="寻宝冷却 10 分钟 / Treasure cooldown: 10 min")
    _add_rare_border(embed, uname)
    return embed


async def _do_busk(guild, uname: str, uid: str) -> discord.Embed:
    """Busking: income depends on online member count."""
    if guild:
        online = len([m for m in guild.members if not m.bot and m.status != discord.Status.offline])
    else:
        online = 0

    roll = random.random()
    base_per_person = random.randint(5, 30)
    earned = online * base_per_person
    earned = max(earned, 5)

    acts = ["弹吉他 / Guitar 🎸", "唱歌 / Singing 🎤", "街舞 / Street Dance 💃",
            "魔术 / Magic 🎩", "杂耍 / Juggling 🤹", "拉小提琴 / Violin 🎻",
            "Beatbox 🎧", "默剧 / Mime 🤡"]

    if roll < 0.05:
        act = random.choice(acts)
        earned = int(earned * 3)
        desc = (f"{uname} {act} 表演太精彩了！观众如痴如醉！\n"
                f"围观 **{online}** 人，大获成功！\n"
                f"收入 🪙 **{earned:,}** 金币！\n\n"
                f"Amazing {act} performance! Crowd of **{online}** went wild!\n"
                f"Earned 🪙 **{earned:,}** coins!")
    elif roll < 0.30:
        act = random.choice(acts)
        desc = (f"{uname} {act} 表演不错，路人纷纷投币。\n"
                f"围观 **{online}** 人，\n"
                f"收入 🪙 **{earned:,}** 金币！\n\n"
                f"Decent {act}, passers-by tossed coins.\n"
                f"Earned 🪙 **{earned:,}** coins!")
    elif roll < 0.70:
        act = random.choice(acts)
        desc = (f"{uname} {act} 表演平平，只有几个人丢了零钱。\n"
                f"围观 **{online}** 人，\n"
                f"收入 🪙 **{earned:,}** 金币！\n\n"
                f"Mediocre {act}, only a few donated.\n"
                f"Earned 🪙 **{earned:,}** coins!")
    elif roll < 0.90:
        earned = 0
        desc = (f"{uname} 表演太烂了... 人群散了。\n"
                f"围观 **{online}** 人全部跑光！\n"
                f"收入 🪙 **0** 金币。\n\n"
                f"Terrible performance... crowd dispersed.\n"
                f"Earned 🪙 **0** coins.")
    else:
        penalty = random.randint(100, 300)
        earned = -penalty
        desc = (f"{uname} 表演砸了，被城管罚款！👮\n"
                f"围观 **{online}** 人看着你被拖走...\n"
                f"罚款 🪙 **{penalty:,}** 金币！\n\n"
                f"Got fined by authorities! 👮\n"
                f"Penalty: 🪙 **{penalty:,}** coins!")

    if earned > 0:
        add_coins(uid, earned, f"街头卖艺 / Busking")
    elif earned < 0:
        my_bal = get_balance(uid)
        penalty = min(abs(earned), my_bal // 2)
        penalty = max(penalty, 1)
        add_coins(uid, -penalty, "卖艺罚款 / Busking fine")
        earned = -penalty

    _update_cd(uid, "busk")
    bal = get_balance(uid)

    color = _result_color("busk", earned)
    embed = discord.Embed(title=f"🎸 {uname} 街头卖艺 / Busking", description=desc, color=color)
    money_fx = _money_effect(earned) if earned > 0 else (_lose_effect(abs(earned)) if earned < 0 else "")
    if money_fx:
        embed.add_field(name="🪙 特效", value=money_fx, inline=False)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.add_field(name="👥 围观人数 / Crowd", value=f"{online} 人", inline=True)
    embed.set_footer(text="卖艺冷却 4 分钟 / Busking cooldown: 4 min")
    _add_rare_border(embed, uname)
    return embed


async def _do_stock(uname: str, uid: str) -> discord.Embed:
    """Stock trading: high risk, high reward."""
    invest = random.randint(100, 500)
    my_bal = get_balance(uid)
    invest = min(invest, my_bal // 3)
    invest = max(invest, 50)

    roll = random.random()
    stocks_trending = ["🚀 月球科技 / MoonTech", "🤖 AI概念股 / AI Corp",
                       "💊 生物制药 / BioPharma", "⚡ 新能源 / NeoEnergy",
                       "🎮 元宇宙 / MetaVerse", "🔋 电池龙头 / Battery King"]

    if roll < 0.05:
        mult = random.uniform(5.0, 15.0)
        earned = int(invest * mult)
        stock = random.choice(stocks_trending)
        desc = (f"{uname} 买了 📈 **{stock}**！股价暴涨 {mult:.1f}x！\n"
                f"投入 {_format_coins(invest)} → 回报 {_format_coins(earned)}！\n\n"
                f"Bought 📈 **{stock}**! Rocketed {mult:.1f}x!\n"
                f"Invested {_format_coins(invest)} → Return {_format_coins(earned)}!")
        color = 0x2ECC71
    elif roll < 0.30:
        mult = random.uniform(1.2, 3.0)
        earned = int(invest * mult)
        stock = random.choice(stocks_trending)
        desc = (f"{uname} 买了 📈 **{stock}**！涨了 {mult:.1f}x！\n"
                f"投入 {_format_coins(invest)} → 回报 {_format_coins(earned)}！\n\n"
                f"Bought 📈 **{stock}**! Up {mult:.1f}x!\n"
                f"Invested {_format_coins(invest)} → Return {_format_coins(earned)}!")
        color = 0x2ECC71
    elif roll < 0.60:
        mult = random.uniform(0.5, 1.2)
        earned = int(invest * mult)
        stock = random.choice(stocks_trending)
        if earned >= invest:
            desc = (f"{uname} 买了 📊 **{stock}**，小赚一点。\n"
                    f"投入 {_format_coins(invest)} → 回报 {_format_coins(earned)}！\n\n"
                    f"Bought 📊 **{stock}**, small profit.\n"
                    f"Invested {_format_coins(invest)} → Return {_format_coins(earned)}!")
            color = 0x3498DB
        else:
            desc = (f"{uname} 买了 📉 **{stock}**，小亏一点。\n"
                    f"投入 {_format_coins(invest)} → 回收 {_format_coins(earned)}！\n\n"
                    f"Bought 📉 **{stock}**, small loss.\n"
                    f"Invested {_format_coins(invest)} → Return {_format_coins(earned)}!")
            color = 0xE67E22
    elif roll < 0.85:
        stock = random.choice(stocks_trending)
        earned = 0
        desc = (f"{uname} 买了 📉 **{stock}**，停牌了！💀\n"
                f"投入 {_format_coins(invest)} → 血本无归！\n\n"
                f"Bought 📉 **{stock}**, delisted! 💀\n"
                f"Invested {_format_coins(invest)} → Total loss!")
        color = 0xE74C3C
    else:
        stock = random.choice(stocks_trending)
        mult = random.uniform(0.01, 0.2)
        earned = int(invest * mult)
        desc = (f"{uname} 买了 📉 **{stock}**，公司跑路了！🏃💨\n"
                f"投入 {_format_coins(invest)} → 只剩 {_format_coins(earned)}！\n\n"
                f"Bought 📉 **{stock}**, CEO ran away! 🏃💨\n"
                f"Invested {_format_coins(invest)} → Only {_format_coins(earned)} left!")
        color = 0xE74C3C

    if earned > 0:
        net = earned - invest
        add_coins(uid, earned, f"炒股: {stock} / Stock: {stock}")
    else:
        net = -invest
        add_coins(uid, -invest, f"炒股亏损: {stock} / Stock loss: {stock}")

    _update_cd(uid, "stock")
    bal = get_balance(uid)

    embed = discord.Embed(title=f"📈 {uname} 炒股 / Stock Trading", description=desc, color=color)
    if net > 0:
        money_fx = _money_effect(net)
        embed.add_field(name="📈 净赚 / Net Profit", value=f"{_format_coins(net)} {money_fx}", inline=False)
    else:
        money_fx = _lose_effect(abs(net))
        embed.add_field(name="📉 净亏 / Net Loss", value=f"{_format_coins(abs(net))} {money_fx}", inline=False)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.set_footer(text="炒股冷却 15 分钟 / Stock cooldown: 15 min")
    _add_rare_border(embed, uname)
    return embed


# ══════════════════════════════════════════════════════════════
# EconomyJobsView — 打工按钮面板 / Job Button Panel
# ══════════════════════════════════════════════════════════════

class EconomyJobsView(discord.ui.View):
    """打工赚钱按钮面板 — 点击按钮即可打工，无需打指令。"""

    JOB_LABELS = {
        "work":     "🏭 打工 Work",
        "rob":      "🥷 打劫 Rob",
        "beg":      "🥺 乞讨 Beg",
        "fish":     "🎣 钓鱼 Fish",
        "hunt":     "🏹 狩猎 Hunt",
        "treasure": "🗺️ 寻宝 Treasure",
        "busk":     "🎸 卖艺 Busk",
        "stock":    "📈 炒股 Stock",
    }

    JOB_EMOJIS = {
        "work":     "🏭",
        "rob":      "🥷",
        "beg":      "🥺",
        "fish":     "🎣",
        "hunt":     "🏹",
        "treasure": "🗺️",
        "busk":     "🎸",
        "stock":    "📈",
    }

    def __init__(self, guild=None, dashboard_view=None):
        super().__init__(timeout=300)
        self.guild = guild
        self.dashboard_view = dashboard_view  # optional ref for back-to-dashboard
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()

        row0_jobs = ["work", "rob", "beg", "fish"]
        row1_jobs = ["hunt", "treasure", "busk", "stock"]

        for job in row0_jobs:
            btn = discord.ui.Button(
                label=self.JOB_LABELS[job],
                style=discord.ButtonStyle.primary,
                row=0,
                custom_id=f"ejob_{job}",
            )
            btn.callback = self._make_job_callback(job)
            self.add_item(btn)

        for job in row1_jobs:
            btn = discord.ui.Button(
                label=self.JOB_LABELS[job],
                style=discord.ButtonStyle.primary,
                row=1,
                custom_id=f"ejob_{job}",
            )
            btn.callback = self._make_job_callback(job)
            self.add_item(btn)

        # Back button
        back_btn = discord.ui.Button(
            label="返回主菜单 | Back to Main",
            style=discord.ButtonStyle.danger,
            row=2,
            custom_id="ejob_back",
        )
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    def _make_job_callback(self, job: str):
        async def cb(interaction: discord.Interaction):
            uid = str(interaction.user.id)
            remaining = _get_cd_remaining(uid, job)
            if remaining > 0:
                cd_label = COOLDOWN_LABELS.get(job, "?")
                return await interaction.response.send_message(
                    f"⏳ **{self.JOB_LABELS[job]}** 冷却中！\n"
                    f"剩余 / Remaining: **{_format_cd(remaining)}**\n"
                    f"冷却时间 / Cooldown: {cd_label}",
                    ephemeral=True,
                )

            await interaction.response.defer()

            if job == "rob":
                # Rob needs target - show target selection
                await self._handle_rob(interaction, uid)
            else:
                await self._handle_job(interaction, uid, job)

        return cb

    async def _back_callback(self, interaction: discord.Interaction):
        if self.dashboard_view:
            self.dashboard_view.category = 0
            self.dashboard_view.build_page_buttons()
            embed = self.dashboard_view._build_page_embed()
            try:
                await interaction.response.edit_message(embed=embed, view=self.dashboard_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.dashboard_view)
        else:
            try:
                await interaction.response.edit_message(
                    content="使用 `/gmpt-dashboard` 返回主菜单 / Use `/gmpt-dashboard` to go back.",
                    embed=None,
                    view=None,
                )
            except discord.InteractionResponded:
                await interaction.edit_original_response(
                    content="使用 `/gmpt-dashboard` 返回主菜单 / Use `/gmpt-dashboard` to go back.",
                    embed=None,
                    view=None,
                )

    # ═══════════════════ Job Handlers ═══════════════════

    async def _handle_job(self, interaction: discord.Interaction, uid: str, job: str):
        uname = interaction.user.display_name

        if job == "work":
            base = random.randint(50, 200)
            bonus = 0
            bonus_msg = ""
            if random.random() < 0.10:
                bonus = random.randint(100, 300)
                base += bonus
                bonus_msg = f"\n🔥 **加班事件 / Overtime Bonus!** +{bonus:,}"
            add_coins(uid, base, "打工收入 / Work income")
            _update_cd(uid, job)
            bal = get_balance(uid)
            embed = discord.Embed(
                title="🏭 打工 / Work",
                description=f"辛苦搬砖，赚了 🪙 **{base:,}** 金币！{bonus_msg}\n\nHard work paid off! Earned 🪙 **{base:,}** coins!",
                color=0x3498DB,
            )
            embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            embed.set_footer(text="每小时可打工一次 / Work once per hour")
            await _animate_job(interaction, [
                f"💼 {uname} 正在打工...",
                f"💪 {uname} 搬砖中...",
                f"💰 {uname} 收到工资！",
            ], embed)
            await _handle_job_xp(uid, interaction)

        elif job == "beg":
            roll = random.random()
            if roll < 0.60:
                earned = random.randint(10, 80)
                add_coins(uid, earned, "乞讨收入 / Begging income")
                bal = get_balance(uid)
                embed = discord.Embed(
                    title="🥺 乞讨 / Begging",
                    description=f"好心人给了 {uname} 🪙 **{earned:,}** 金币！\nA kind stranger gave you 🪙 **{earned:,}** coins!",
                    color=0x2ECC71,
                )
                embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            elif roll < 0.90:
                bal = get_balance(uid)
                embed = discord.Embed(
                    title="🥺 乞讨 / Begging",
                    description=f"没人理 {uname}... 被无视了。\nNobody noticed... Ignored.",
                    color=0x95A5A6,
                )
                embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            else:
                earned = random.randint(200, 500)
                add_coins(uid, earned, "好心人打赏 / Generous donation")
                bal = get_balance(uid)
                embed = discord.Embed(
                    title="🥺 乞讨 / Begging",
                    description=f"🎉 超级好心人给了 {uname} 🪙 **{earned:,}** 金币！！\nA generous soul gave you 🪙 **{earned:,}** coins!!",
                    color=0xF1C40F,
                )
                embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            embed.set_footer(text="乞讨冷却 5 分钟 / Beg cooldown: 5 min")
            _update_cd(uid, job)
            await _animate_job(interaction, [
                f"🥺 {uname} 可怜巴巴地看着路人...",
                f"🙏 {uname} 双手合十乞求...",
                f"💰 {'有人施舍了！' if roll < 0.60 or roll >= 0.90 else '没人回应...'}",
            ], embed)
            await _handle_job_xp(uid, interaction)

        elif job == "fish":
            roll = random.random()
            if roll < 0.05:
                fish_name = "传说鱼 / Legendary Fish"
                fish_emoji = "🐋"
                earned = random.randint(500, 2000)
                color = 0xF1C40F
            elif roll < 0.25:
                fish_name = "金鱼 / Goldfish"
                fish_emoji = "🐠"
                earned = random.randint(100, 200)
                color = 0xE67E22
            elif roll < 0.55:
                fish_name = "鲈鱼 / Bass"
                fish_emoji = "🐟"
                earned = random.randint(30, 60)
                color = 0x3498DB
            elif roll < 0.85:
                fish_name = "鲱鱼 / Herring"
                fish_emoji = "🐡"
                earned = random.randint(5, 20)
                color = 0x95A5A6
            else:
                fish_name = "垃圾 / Trash"
                fish_emoji = "👢"
                earned = 0
                color = 0x7F8C8D

            # Rare event: catch a server member (25% independent)
            caught_member = None
            member_bonus = 0
            if random.random() < 0.25 and self.guild:
                members = [m for m in self.guild.members if not m.bot and str(m.id) != uid]
                if members:
                    caught_member = random.choice(members)
                    # Fisher: 50% gets 100-500 coins, 50% gives 100-500 coins to caught member
                    if random.random() < 0.50:
                        member_bonus = random.randint(100, 500)
                        earned += member_bonus
                        fisher_dir = "got"
                    else:
                        member_bonus = random.randint(100, 500)
                        fisher_dir = "gave"
                    # Caught: 50% gets 50 compensation, 50% gives 50 coins to fisher
                    if random.random() < 0.50:
                        caught_comp = 50
                        caught_dir = "got"
                    else:
                        caught_comp = -50
                        caught_dir = "gave"
                        earned += 50
                    if caught_comp > 0:
                        add_coins(str(caught_member.id), caught_comp, "被钓鱼补偿 / Caught by fishing compensation")
                    else:
                        add_coins(str(caught_member.id), caught_comp, "被钓鱼反给 / Caught, gave coins back")
                    color = 0xE91E63

            if earned > 0:
                add_coins(uid, earned, f"钓鱼: {fish_name} / Fishing: {fish_name}")
            bal = get_balance(uid)
            if caught_member:
                if fisher_dir == "got":
                    coin_desc = f"顺便获得 🪙 **{member_bonus:,}** 金币！"
                    coin_desc_en = f"Bonus 🪙 **{member_bonus:,}** coins!"
                else:
                    coin_desc = f"反倒给了 🪙 **{member_bonus:,}** 金币..."
                    coin_desc_en = f"Gave 🪙 **{member_bonus:,}** coins instead..."
                if caught_dir == "got":
                    caught_msg = f"获得补偿 🪙 **50** 金币 / Compensation: 🪙 50 coins"
                else:
                    caught_msg = f"反给了 {uname} 🪙 **50** 金币 / Gave 🪙 50 coins to {uname}"
                desc = (
                    f"{uname} 🎣 用力一拉...\n"
                    f"居然钓上来了 **{caught_member.display_name}**！！\n"
                    f"{coin_desc} ({fish_emoji} {fish_name} +{earned - member_bonus:,})\n\n"
                    f"OMG! {uname} fished up **{caught_member.display_name}**!!\n"
                    f"{coin_desc_en} ({fish_emoji} {fish_name} +{earned - member_bonus:,})"
                )
                embed = discord.Embed(title=f"🎣 {uname} 钓鱼 / Fishing", description=desc, color=color)
                if caught_member.avatar:
                    embed.set_thumbnail(url=caught_member.avatar.url)
            elif earned > 0:
                desc = f"{uname} 钓到了 {fish_emoji} **{fish_name}**！卖得 🪙 **{earned:,}** 金币！\nCaught {fish_emoji} **{fish_name}**! Sold for 🪙 **{earned:,}** coins!"
            else:
                desc = f"{uname} 钓到了 {fish_emoji} **垃圾**... 一文不值。\nCaught {fish_emoji} **trash**... Worthless."
            if not caught_member:
                embed = discord.Embed(title=f"🎣 {uname} 钓鱼 / Fishing", description=desc, color=color)
            embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            embed.set_footer(text="钓鱼冷却 3 分钟 / Fish cooldown: 3 min")
            _update_cd(uid, job)
            await _animate_job(interaction, [
                f"🎣 {uname} 甩出了鱼竿...",
                f"🌊 水面泛起涟漪...",
                f"🐟 有东西上钩了！",
                f"💦 激烈搏斗中...",
                f"🐠 快出水了！",
                f"💰 {uname} 收竿！",
            ], embed)
            await _handle_job_xp(uid, interaction)
            if caught_member:
                await interaction.channel.send(
                    f"🐟 {caught_member.mention} 被 **{uname}** 钓鱼时钓上来了！\n"
                    f"You were fished up by **{uname}**!\n{caught_msg}"
                )

        elif job == "hunt":
            embed, hit_msg = await _do_hunt(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"🏹 {uname} 拉弓瞄准...",
                f"🐗 发现猎物！",
                f"💰 {uname} 放箭！",
            ], embed)
            await _handle_job_xp(uid, interaction)
            if hit_msg:
                await interaction.channel.send(hit_msg)

        elif job == "treasure":
            embed = await _do_treasure(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"🗺️ {uname} 打开了藏宝图...",
                f"⛏️ {uname} 正在挖掘...",
                f"💎 {uname} 发现了什么！",
            ], embed)
            await _handle_job_xp(uid, interaction)

        elif job == "busk":
            embed = await _do_busk(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"🎸 {uname} 在街头摆好设备...",
                f"🎶 {uname} 开始表演...",
                f"👏 路人们围了过来！",
            ], embed)
            await _handle_job_xp(uid, interaction)

        elif job == "stock":
            embed = await _do_stock(uname, uid)
            await _animate_job(interaction, [
                f"📈 {uname} 打开了股市软件...",
                f"💹 {uname} 正在分析走势...",
                f"📊 {uname} 下单买入！",
            ], embed)
            await _handle_job_xp(uid, interaction)

    async def _handle_rob(self, interaction: discord.Interaction, uid: str):
        """Rob requires a target — show a select dropdown with eligible targets."""
        if not self.guild:
            return await interaction.followup.send(
                "无法获取服务器信息 / Cannot get guild info.", ephemeral=True
            )

        members = [m for m in self.guild.members if not m.bot and str(m.id) != uid][:25]
        if not members:
            return await interaction.followup.send(
                "没有可打劫的玩家 / No players to rob.", ephemeral=True
            )

        options = []
        for m in members:
            try:
                bal = get_balance(str(m.id))
            except Exception:
                bal = 0
            label = f"{m.display_name[:50]} — 🪙{bal}"
            if bal < 100:
                label += " (余额不足)"
            options.append(discord.SelectOption(
                label=label[:100],
                value=str(m.id),
                description=f"ID: {m.id}",
            ))

        select = discord.ui.Select(
            placeholder="选择打劫目标 / Select a target...",
            options=options[:25],
        )

        async def rob_select_callback(sel_int: discord.Interaction):
            await sel_int.response.defer()
            tid = sel_int.data["values"][0]
            target = self.guild.get_member(int(tid))
            if not target:
                return await sel_int.followup.send("目标不在服务器 / Target not found.", ephemeral=True)

            tname = target.display_name
            uname = interaction.user.display_name
            target_bal = get_balance(tid)

            if target_bal < 100:
                return await sel_int.followup.send(
                    f"{tname} 余额不足 100 金币，无法打劫 / Balance < 100.", ephemeral=True
                )

            success = random.random() < 0.60
            if success:
                pct = random.uniform(0.10, 0.30)
                stolen = min(int(target_bal * pct), 5000)
                stolen = max(stolen, 1)
                add_coins(tid, -stolen, f"被 {uname} 打劫 / Robbed by {uname}")
                add_coins(uid, stolen, f"打劫 {tname} / Robbed {tname}")
                robber_bal = get_balance(uid)
                embed = discord.Embed(
                    title="🥷 打劫成功！/ Robbery Success!",
                    description=f"{uname} 成功打劫了 {tname}！",
                    color=0xE74C3C,
                )
                embed.add_field(name="💰 抢走 / Stolen", value=_format_coins(stolen), inline=True)
                embed.add_field(name="💰 你的余额 / Your Balance", value=_format_coins(robber_bal), inline=True)
            else:
                penalty_pct = 0.20
                my_bal = get_balance(uid)
                penalty = max(int(my_bal * penalty_pct), 1)
                add_coins(uid, -penalty, "打劫失败罚款 / Failed robbery penalty")
                add_coins(tid, penalty, f"{uname} 打劫失败赔偿 / Compensation from failed robbery")
                robber_bal = get_balance(uid)
                embed = discord.Embed(
                    title="🚔 打劫失败！/ Robbery Failed!",
                    description=f"{uname} 打劫 {tname} 被抓，罚款赔偿！\nCaught! Penalty paid to victim.",
                    color=0xF1C40F,
                )
                embed.add_field(name="💸 罚款 / Penalty", value=_format_coins(penalty), inline=True)
                embed.add_field(name="💰 你的余额 / Your Balance", value=_format_coins(robber_bal), inline=True)

            embed.set_footer(text="打劫冷却 2 小时 / Rob cooldown: 2 hours")
            _update_cd(uid, "rob")
            await _animate_job(sel_int, [
                f"😈 {uname} 盯上了 {tname}...",
                f"🏃 {uname} 冲了过去！",
                f"💰 {'得手了！' if success else '被抓了！'}",
            ], embed)

        select.callback = rob_select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send("🥷 选择打劫目标 / Select a target:", view=view, ephemeral=True)


class EconomyJobs(CogBase):
    """基础赚钱命令 / Basic income commands."""

    def __init__(self, bot):
        self.bot = bot

    gmpt_job_group = app_commands.Group(
        name="gmpt-job",
        description="Economy jobs to earn coins / 打工赚钱"
    )

    async def cog_load(self):
        cmds = [cmd.qualified_name for cmd in self.get_app_commands()]
        logger.info(f"[EconomyJobs] cog_load — 已注册 {len(cmds)} 个命令: {', '.join(cmds)}")

    # ══════════════════════════════════════════════════════════
    # /gmpt-work — 打工赚钱
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="work", description="💼 打工赚钱 / Work to earn coins (1h cooldown)")
    @app_commands.checks.cooldown(1, 3600, key=lambda i: (i.guild_id, i.user.id))
    async def work_cmd(self, interaction: discord.Interaction):
        """打工赚钱，每小时一次."""
        try:
            uid = str(interaction.user.id)
            remaining = _get_cd_remaining(uid, "work")
            if remaining > 0:
                return await interaction.response.send_message(
                    f"⏳ 打工冷却中！剩余 **{_format_cd(remaining)}** / Work cooldown! Remaining: **{_format_cd(remaining)}**",
                    ephemeral=True,
                )
            uname = interaction.user.display_name

            base = random.randint(50, 200)
            bonus = 0
            bonus_msg = ""

            if random.random() < 0.10:
                bonus = random.randint(100, 300)
                base += bonus
                bonus_msg = f"\n🔥 **加班事件 / Overtime Bonus!** 🪙 +{bonus:,}"

            add_coins(uid, base, "打工收入 / Work income")
            _update_cd(uid, "work")
            bal = get_balance(uid)

            embed = discord.Embed(
                title=f"💼 {uname} 打工 / Work",
                description=f"辛苦搬砖，赚了 🪙 **{base:,}** 金币！{bonus_msg}\n\nHard work paid off! Earned 🪙 **{base:,}** coins!",
                color=0x3498DB,
            )
            embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            embed.set_footer(text="每小时可打工一次 / Work once per hour")

            await interaction.response.defer()
            frames = [
                f"💼 {uname} 正在打工...",
                f"💪 {uname} 搬砖中...",
                f"💰 {uname} 收到工资！",
            ]
            await _animate_job(interaction, frames, embed)
            await _handle_job_xp(uid, interaction)
        except Exception as e:
            logger.error(f"[work_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 打工命令出错，请重试 / Work error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 打工命令出错，请重试 / Work error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-rob — 打劫其他用户
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="rob", description="🥷 打劫其他用户 / Rob another user (2h cooldown)")
    @app_commands.describe(target="打劫目标 / Target user")
    @app_commands.checks.cooldown(1, 7200, key=lambda i: (i.guild_id, i.user.id))
    async def rob_cmd(self, interaction: discord.Interaction, target: discord.Member):
        """打劫目标用户."""
        try:
            uid = str(interaction.user.id)
            remaining = _get_cd_remaining(uid, "rob")
            if remaining > 0:
                return await interaction.response.send_message(
                    f"⏳ 打劫冷却中！剩余 **{_format_cd(remaining)}** / Rob cooldown! Remaining: **{_format_cd(remaining)}**",
                    ephemeral=True,
                )
            tid = str(target.id)
            uname = interaction.user.display_name
            tname = target.display_name

            if target.id == interaction.user.id:
                return await interaction.response.send_message(
                    "不能打劫自己 / Cannot rob yourself!", ephemeral=True)
            if target.bot:
                return await interaction.response.send_message(
                    "不能打劫机器人 / Cannot rob bots!", ephemeral=True)

            target_bal = get_balance(tid)
            if target_bal < 100:
                return await interaction.response.send_message(
                    f"{tname} 余额不足 100 金币，无法打劫 / Balance < 100, cannot rob.",
                    ephemeral=True,
                )

            success = random.random() < 0.60

            if success:
                pct = random.uniform(0.10, 0.30)
                stolen = min(int(target_bal * pct), 5000)
                stolen = max(stolen, 1)

                add_coins(tid, -stolen, f"被 {uname} 打劫 / Robbed by {uname}")
                add_coins(uid, stolen, f"打劫 {tname} / Robbed {tname}")
                robber_bal = get_balance(uid)

                embed = discord.Embed(
                    title="🥷 打劫成功！/ Robbery Success!",
                    description=f"{uname} 成功打劫了 {tname}！\n{{Robbed successfully!}}",
                    color=0xE74C3C,
                )
                embed.add_field(name="💰 抢走 / Stolen", value=_format_coins(stolen), inline=True)
                embed.add_field(name="💰 你的余额 / Your Balance", value=_format_coins(robber_bal), inline=True)
            else:
                penalty_pct = 0.20
                my_bal = get_balance(uid)
                penalty = max(int(my_bal * penalty_pct), 1)

                add_coins(uid, -penalty, f"打劫失败罚款 / Failed robbery penalty")
                add_coins(tid, penalty, f"{uname} 打劫失败赔偿 / Compensation from failed robbery")
                robber_bal = get_balance(uid)

                embed = discord.Embed(
                    title="🚔 打劫失败！/ Robbery Failed!",
                    description=f"{uname} 打劫 {tname} 被抓，罚款赔偿！\nCaught! Penalty paid to victim.",
                    color=0xF1C40F,
                )
                embed.add_field(name="💸 罚款 / Penalty", value=_format_coins(penalty), inline=True)
                embed.add_field(name="💰 你的余额 / Your Balance", value=_format_coins(robber_bal), inline=True)

            embed.set_footer(text="打劫冷却 2 小时 / Rob cooldown: 2 hours")
            _update_cd(uid, "rob")
            await interaction.response.defer()
            result_text = f"成功从 {tname} 抢走 {_format_coins(stolen)}！" if success else f"失败，被罚款 {_format_coins(penalty)}！"
            frames = [
                f"🥷 {uname} 正在踩点...",
                f"👀 {uname} 锁定目标 {tname}...",
                f"💸 {uname} {result_text}",
            ]
            await _animate_job(interaction, frames, embed)
            await _handle_job_xp(uid, interaction)
        except Exception as e:
            logger.error(f"[rob_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 打劫命令出错，请重试 / Rob error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 打劫命令出错，请重试 / Rob error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-beg — 乞讨
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="beg", description="🙏 乞讨 / Beg for coins (5 min cooldown)")
    @app_commands.checks.cooldown(1, 300, key=lambda i: (i.guild_id, i.user.id))
    async def beg_cmd(self, interaction: discord.Interaction):
        """乞讨."""
        try:
            uid = str(interaction.user.id)
            remaining = _get_cd_remaining(uid, "beg")
            if remaining > 0:
                return await interaction.response.send_message(
                    f"⏳ 乞讨冷却中！剩余 **{_format_cd(remaining)}** / Beg cooldown! Remaining: **{_format_cd(remaining)}**",
                    ephemeral=True,
                )
            uname = interaction.user.display_name

            roll = random.random()

            if roll < 0.60:
                earned = random.randint(10, 80)
                add_coins(uid, earned, "乞讨收入 / Begging income")
                bal = get_balance(uid)
                embed = discord.Embed(
                    title="🙏 乞讨 / Begging",
                    description=f"好心人给了 {uname} 🪙 **{earned:,}** 金币！\nA kind stranger gave you 🪙 **{earned:,}** coins!",
                    color=0x2ECC71,
                )
                embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            elif roll < 0.90:
                bal = get_balance(uid)
                embed = discord.Embed(
                    title="🙏 乞讨 / Begging",
                    description=f"没人理 {uname}... 被无视了。\nNobody noticed... Ignored.",
                    color=0x95A5A6,
                )
                embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            else:
                earned = random.randint(200, 500)
                add_coins(uid, earned, "好心人打赏 / Generous donation")
                bal = get_balance(uid)
                embed = discord.Embed(
                    title="🙏 乞讨 / Begging",
                    description=f"🎉 超级好心人给了 {uname} 🪙 **{earned:,}** 金币！！\nA generous soul gave you 🪙 **{earned:,}** coins!!",
                    color=0xF1C40F,
                )
                embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)

            embed.set_footer(text="乞讨冷却 5 分钟 / Beg cooldown: 5 min")
            _update_cd(uid, "beg")
            await interaction.response.defer()
            frames = [
                f"🥺 {uname} 跪地乞讨...",
                f"🙏 {uname} 正在等待好心人...",
                f"💰 {'有人施舍了！' if roll < 0.60 or roll >= 0.90 else '没人回应...'}",
            ]
            await _animate_job(interaction, frames, embed)
            await _handle_job_xp(uid, interaction)
        except Exception as e:
            logger.error(f"[beg_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 乞讨命令出错，请重试 / Beg error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 乞讨命令出错，请重试 / Beg error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-fish — 钓鱼
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="fish", description="🎣 钓鱼 / Go fishing (3 min cooldown)")
    @app_commands.checks.cooldown(1, 180, key=lambda i: (i.guild_id, i.user.id))
    async def fish_cmd(self, interaction: discord.Interaction):
        """钓鱼."""
        try:
            uid = str(interaction.user.id)
            remaining = _get_cd_remaining(uid, "fish")
            if remaining > 0:
                return await interaction.response.send_message(
                    f"⏳ 钓鱼冷却中！剩余 **{_format_cd(remaining)}** / Fish cooldown! Remaining: **{_format_cd(remaining)}**",
                    ephemeral=True,
                )
            uname = interaction.user.display_name

            roll = random.random()

            if roll < 0.05:
                fish_name = "传说鱼 / Legendary Fish"
                fish_emoji = "🐋"
                earned = random.randint(500, 2000)
                color = 0xF1C40F
            elif roll < 0.25:
                fish_name = "金鱼 / Goldfish"
                fish_emoji = "🐠"
                earned = random.randint(100, 200)
                color = 0xE67E22
            elif roll < 0.55:
                fish_name = "鲈鱼 / Bass"
                fish_emoji = "🐟"
                earned = random.randint(30, 60)
                color = 0x3498DB
            elif roll < 0.85:
                fish_name = "鲱鱼 / Herring"
                fish_emoji = "🐡"
                earned = random.randint(5, 20)
                color = 0x95A5A6
            else:
                fish_name = "垃圾 / Trash"
                fish_emoji = "👢"
                earned = 0
                color = 0x7F8C8D

            # Rare event: catch a server member (25% independent)
            caught_member = None
            member_bonus = 0
            if random.random() < 0.25 and interaction.guild:
                members = [m for m in interaction.guild.members if not m.bot and m.id != interaction.user.id]
                if members:
                    caught_member = random.choice(members)
                    # Fisher: 50% gets 100-500 coins, 50% gives 100-500 coins to caught member
                    if random.random() < 0.50:
                        member_bonus = random.randint(100, 500)
                        earned += member_bonus
                        fisher_dir = "got"
                    else:
                        member_bonus = random.randint(100, 500)
                        fisher_dir = "gave"
                    # Caught: 50% gets 50 compensation, 50% gives 50 coins to fisher
                    if random.random() < 0.50:
                        caught_comp = 50
                        caught_dir = "got"
                    else:
                        caught_comp = -50
                        caught_dir = "gave"
                        earned += 50
                    if caught_comp > 0:
                        add_coins(str(caught_member.id), caught_comp, "被钓鱼补偿 / Caught by fishing compensation")
                    else:
                        add_coins(str(caught_member.id), caught_comp, "被钓鱼反给 / Caught, gave coins back")
                    color = 0xE91E63

            if earned > 0:
                add_coins(uid, earned, f"钓鱼: {fish_name} / Fishing: {fish_name}")

            bal = get_balance(uid)

            if caught_member:
                if fisher_dir == "got":
                    coin_desc = f"顺便获得 🪙 **{member_bonus:,}** 金币！"
                    coin_desc_en = f"Bonus 🪙 **{member_bonus:,}** coins!"
                else:
                    coin_desc = f"反倒给了 🪙 **{member_bonus:,}** 金币..."
                    coin_desc_en = f"Gave 🪙 **{member_bonus:,}** coins instead..."
                if caught_dir == "got":
                    caught_msg = f"获得补偿 🪙 **50** 金币 / Compensation: 🪙 50 coins"
                else:
                    caught_msg = f"反给了 {uname} 🪙 **50** 金币 / Gave 🪙 50 coins to {uname}"
                desc = (
                    f"{uname} 🎣 用力一拉...\n"
                    f"居然钓上来了 **{caught_member.display_name}**！！\n"
                    f"{coin_desc} ({fish_emoji} {fish_name} +{earned - member_bonus:,})\n\n"
                    f"OMG! {uname} fished up **{caught_member.display_name}**!!\n"
                    f"{coin_desc_en} ({fish_emoji} {fish_name} +{earned - member_bonus:,})"
                )
                embed = discord.Embed(title=f"🎣 {uname} 钓鱼 / Fishing", description=desc, color=color)
                if caught_member.avatar:
                    embed.set_thumbnail(url=caught_member.avatar.url)
            elif earned > 0:
                desc = f"{uname} 钓到了 {fish_emoji} **{fish_name}**！卖得 🪙 **{earned:,}** 金币！\nCaught {fish_emoji} **{fish_name}**! Sold for 🪙 **{earned:,}** coins!"
            else:
                desc = f"{uname} 钓到了 {fish_emoji} **垃圾**... 一文不值。\nCaught {fish_emoji} **trash**... Worthless."

            if not caught_member:
                embed = discord.Embed(title=f"🎣 {uname} 钓鱼 / Fishing", description=desc, color=color)

            embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            embed.set_footer(text="钓鱼冷却 3 分钟 / Fish cooldown: 3 min")
            _update_cd(uid, "fish")
            await interaction.response.defer()
            frames = [
                f"🎣 {uname} 抛出鱼线...",
                f"🐟 {uname} 等待鱼儿上钩...",
                f"🐠 {uname} 拉杆！",
            ]
            await _animate_job(interaction, frames, embed)
            await _handle_job_xp(uid, interaction)
            if caught_member:
                await interaction.channel.send(
                    f"🐟 {caught_member.mention} 被 **{uname}** 钓鱼时钓上来了！\n"
                    f"You were fished up by **{uname}**!\n{caught_msg}"
                )
        except Exception as e:
            logger.error(f"[fish_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 钓鱼命令出错，请重试 / Fish error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 钓鱼命令出错，请重试 / Fish error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-hunt — 狩猎
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="hunt", description="🏹 狩猎 / Go hunting (5 min cooldown)")
    @app_commands.checks.cooldown(1, 300, key=lambda i: (i.guild_id, i.user.id))
    async def hunt_cmd(self, interaction: discord.Interaction):
        """狩猎."""
        try:
            uid = str(interaction.user.id)
            remaining = _get_cd_remaining(uid, "hunt")
            if remaining > 0:
                return await interaction.response.send_message(
                    f"⏳ 狩猎冷却中！剩余 **{_format_cd(remaining)}** / Hunt cooldown! Remaining: **{_format_cd(remaining)}**",
                    ephemeral=True,
                )
            uname = interaction.user.display_name

            embed, hit_msg = await _do_hunt(interaction.guild, uname, uid)
            await interaction.response.defer()
            frames = [
                f"🏹 {uname} 进入猎场...",
                f"🐗 {uname} 搜寻猎物中...",
                f"🐾 {uname} 发现猎物！",
            ]
            await _animate_job(interaction, frames, embed)
            await _handle_job_xp(uid, interaction)
            if hit_msg:
                await interaction.channel.send(hit_msg)
        except Exception as e:
            logger.error(f"[hunt_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 狩猎命令出错，请重试 / Hunt error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 狩猎命令出错，请重试 / Hunt error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-job treasure — 寻宝
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="treasure", description="🗺️ 寻宝 / Treasure hunt — big wins or traps! (10 min cooldown)")
    @app_commands.checks.cooldown(1, 600, key=lambda i: (i.guild_id, i.user.id))
    async def treasure_cmd(self, interaction: discord.Interaction):
        """寻宝."""
        try:
            uid = str(interaction.user.id)
            remaining = _get_cd_remaining(uid, "treasure")
            if remaining > 0:
                return await interaction.response.send_message(
                    f"⏳ 寻宝冷却中！剩余 **{_format_cd(remaining)}** / Treasure cooldown! Remaining: **{_format_cd(remaining)}**",
                    ephemeral=True,
                )
            uname = interaction.user.display_name
            embed = await _do_treasure(interaction.guild, uname, uid)
            await interaction.response.defer()
            frames = [
                f"🗺️ {uname} 展开藏宝图...",
                f"⛏️ {uname} 挖掘中...",
                f"📦 {uname} 找到了什么！",
            ]
            await _animate_job(interaction, frames, embed)
            await _handle_job_xp(uid, interaction)
        except Exception as e:
            logger.error(f"[treasure_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 寻宝命令出错，请重试 / Treasure error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 寻宝命令出错，请重试 / Treasure error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-job busk — 街头卖艺
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="busk", description="🎸 街头卖艺 / Busking — income depends on crowd size! (4 min cooldown)")
    @app_commands.checks.cooldown(1, 240, key=lambda i: (i.guild_id, i.user.id))
    async def busk_cmd(self, interaction: discord.Interaction):
        """街头卖艺."""
        try:
            uid = str(interaction.user.id)
            remaining = _get_cd_remaining(uid, "busk")
            if remaining > 0:
                return await interaction.response.send_message(
                    f"⏳ 卖艺冷却中！剩余 **{_format_cd(remaining)}** / Busking cooldown! Remaining: **{_format_cd(remaining)}**",
                    ephemeral=True,
                )
            uname = interaction.user.display_name
            embed = await _do_busk(interaction.guild, uname, uid)
            await interaction.response.defer()
            frames = [
                f"🎸 {uname} 摆好摊位...",
                f"🎶 {uname} 卖力演奏中...",
                f"🎩 {uname} 收取打赏！",
            ]
            await _animate_job(interaction, frames, embed)
            await _handle_job_xp(uid, interaction)
        except Exception as e:
            logger.error(f"[busk_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 卖艺命令出错，请重试 / Busk error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 卖艺命令出错，请重试 / Busk error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-job stock — 炒股
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="stock", description="📈 炒股 / Stock trading — high risk high reward! (15 min cooldown)")
    @app_commands.checks.cooldown(1, 900, key=lambda i: (i.guild_id, i.user.id))
    async def stock_cmd(self, interaction: discord.Interaction):
        """炒股."""
        try:
            uid = str(interaction.user.id)
            remaining = _get_cd_remaining(uid, "stock")
            if remaining > 0:
                return await interaction.response.send_message(
                    f"⏳ 炒股冷却中！剩余 **{_format_cd(remaining)}** / Stock cooldown! Remaining: **{_format_cd(remaining)}**",
                    ephemeral=True,
                )
            uname = interaction.user.display_name
            embed = await _do_stock(uname, uid)
            await interaction.response.defer()
            frames = [
                f"📈 {uname} 盯盘中...",
                f"💹 {uname} 果断出手...",
                f"📊 {uname} 交易完成！",
            ]
            await _animate_job(interaction, frames, embed)
            await _handle_job_xp(uid, interaction)
        except Exception as e:
            logger.error(f"[stock_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 炒股命令出错，请重试 / Stock error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 炒股命令出错，请重试 / Stock error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-jobs — 打工按钮面板 / Job Button Panel
    # ══════════════════════════════════════════════════════════
    @app_commands.command(name="gmpt-jobs", description="💼 打工赚钱面板 / Economy jobs button panel")
    async def jobs_panel(self, interaction: discord.Interaction):
        """显示打工按钮面板."""
        view = EconomyJobsView(guild=interaction.guild)
        embed = discord.Embed(
            title="💼 打工赚钱 | Economy Jobs",
            description="点击下方按钮即可打工赚钱，无需打指令！\nClick a button below to earn coins — no commands needed!",
            color=0xF39C12,
        )
        embed.add_field(
            name="可用工作 / Available Jobs",
            value=(
                "🏭 **打工** — 1小时 CD / 1h cooldown\n"
                "🥷 **打劫** — 2小时 CD / 2h cooldown\n"
                "🥺 **乞讨** — 5分钟 CD / 5min cooldown\n"
                "🎣 **钓鱼** — 3分钟 CD / 3min cooldown\n"
                "🏹 **狩猎** — 5分钟 CD / 5min cooldown\n"
                "🗺️ **寻宝** — 10分钟 CD / 10min cooldown\n"
                "🎸 **卖艺** — 4分钟 CD / 4min cooldown\n"
                "📈 **炒股** — 15分钟 CD / 15min cooldown"
            ),
            inline=False,
        )
        embed.set_footer(text="每种工作有独立的冷却时间 | Each job has its own cooldown")
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(EconomyJobs(bot))
