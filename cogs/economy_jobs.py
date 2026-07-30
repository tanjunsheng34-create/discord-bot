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
from utils.animations import progress_bar
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
    # ── 新增 New ──
    "miner": 1800,       # 30 min
    "fisher": 1200,      # 20 min
    "hunter": 2400,      # 40 min
    "merchant": 3600,    # 60 min
    "bounty": 5400,      # 90 min
    "alchemist": 2700,   # 45 min
    "blacksmith": 3000,  # 50 min
    "enchanter": 7200,   # 120 min
    "potion_dealer": 2100,  # 35 min
    "adventurer": 10800, # 180 min
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
    "miner": "30分钟 / 30min",
    "fisher": "20分钟 / 20min",
    "hunter": "40分钟 / 40min",
    "merchant": "1小时 / 1h",
    "bounty": "1.5小时 / 1.5h",
    "alchemist": "45分钟 / 45min",
    "blacksmith": "50分钟 / 50min",
    "enchanter": "2小时 / 2h",
    "potion_dealer": "35分钟 / 35min",
    "adventurer": "3小时 / 3h",
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

def _add_global_xp(uid: str, income: int) -> int:
    """Add MMORPG EXP based on job income. Returns EXP gained.

    Success (profit): exp = max(1, income // 5)
    Failure (loss):   exp = max(1, abs(income) // 10)
    Level up every 1000 XP.
    """
    if income > 0:
        exp = max(1, income // 5)
    else:
        exp = max(1, abs(income) // 10)

    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT xp, level FROM users WHERE discord_id = ?",
            (uid,),
        )
        row = cur.fetchone()
        old_xp = row["xp"] if row else 0
        old_level = row["level"] if row else 1
        new_xp = old_xp + exp

        new_level = old_level
        while new_xp >= new_level * 1000:
            new_xp -= new_level * 1000
            new_level += 1

        cur.execute(
            "UPDATE users SET xp = ?, level = ? WHERE discord_id = ?",
            (new_xp, new_level, uid),
        )
        conn.commit()
    return exp


def _add_user_xp(uid: str, amount: int) -> tuple:
    """Add a direct XP amount to user and handle level-ups.
    Returns (xp_gained, did_level_up, old_level, new_level, level_ups_count).
    Use this for quest rewards, dungeon XP, etc. where XP is pre-calculated.
    """
    from database import get_db_ctx as _gdc
    with _gdc() as conn:
        cur = conn.cursor()
        cur.execute("SELECT xp, level FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
        old_xp = row["xp"] if row else 0
        old_level = row["level"] if row else 1

        new_xp = old_xp + amount
        new_level = old_level
        level_ups = 0
        xp_to_next = new_level * 1000

        while new_xp >= xp_to_next:
            new_xp -= xp_to_next
            new_level += 1
            level_ups += 1
            xp_to_next = new_level * 1000

        # Grant stat growth on level-up: +10 max_hp, +3 attack per level gained
        if level_ups > 0:
            hp_gain = level_ups * 10
            atk_gain = level_ups * 3
            cur.execute(
                "UPDATE users SET xp = ?, level = ?, max_hp = max_hp + ?, hp = max_hp + ?, attack = attack + ? WHERE discord_id = ?",
                (new_xp, new_level, hp_gain, hp_gain, atk_gain, uid),
            )
        else:
            cur.execute(
                "UPDATE users SET xp = ?, level = ? WHERE discord_id = ?",
                (new_xp, new_level, uid),
            )
        conn.commit()

    return (amount, level_ups > 0, old_level, new_level, level_ups)


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
        "miner":    "⛏️ 矿工 Miner",
        "fisher":   "🐟 渔夫 Fisher",
        "hunter":   "🦌 猎人 Hunter",
        "merchant": "🧳 商人 Merchant",
        "bounty":   "💀 赏金猎人 Bounty",
        "alchemist": "⚗️ 炼金术师 Alchemist",
        "blacksmith": "🔨 铁匠 Smith",
        "enchanter": "✨ 附魔师 Enchanter",
        "potion_dealer": "🧪 药水商 Potions",
        "adventurer": "🗡️ 冒险家 Adventurer",
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
        "miner":    "⛏️",
        "fisher":   "🐟",
        "hunter":   "🦌",
        "merchant": "🧳",
        "bounty":   "💀",
        "alchemist": "⚗️",
        "blacksmith": "🔨",
        "enchanter": "✨",
        "potion_dealer": "🧪",
        "adventurer": "🗡️",
    }

    def __init__(self, guild=None, dashboard_view=None, main_view=None):
        super().__init__(timeout=300)
        self.guild = guild
        self.dashboard_view = dashboard_view
        self.main_view = main_view  # MMORPG Main Panel reference
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()

        row_jobs = [
            ["work", "rob", "beg", "fish"],
            ["hunt", "treasure", "busk", "stock"],
            ["miner", "fisher", "hunter", "merchant"],
            ["bounty", "alchemist", "blacksmith", "potion_dealer"],
            ["enchanter", "adventurer"],
        ]

        for r, jobs in enumerate(row_jobs):
            for job in jobs:
                btn = discord.ui.Button(
                    label=self.JOB_LABELS[job],
                    style=discord.ButtonStyle.primary,
                    row=r,
                    custom_id=f"ejob_{job}",
                )
                btn.callback = self._make_job_callback(job)
                self.add_item(btn)

        # Work All button
        work_all_btn = discord.ui.Button(
            label="⏰ 全部打工 | Work All",
            style=discord.ButtonStyle.success,
            row=4,
            custom_id="ejob_work_all",
        )
        work_all_btn.callback = self._work_all_callback
        self.add_item(work_all_btn)

        # Back button
        back_btn = discord.ui.Button(
            label="返回主菜单 | Back to Main",
            style=discord.ButtonStyle.danger,
            row=4,
            custom_id="ejob_back",
        )
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    async def _work_all_callback(self, interaction: discord.Interaction):
        """⏰ Execute all available jobs sequentially with progress."""
        uid = str(interaction.user.id)
        uname = interaction.user.display_name

        # Build job list (all non-rob jobs)
        all_jobs = [
            "work", "beg", "fish", "hunt", "treasure", "busk", "stock",
            "miner", "fisher", "hunter", "merchant", "bounty",
            "alchemist", "blacksmith", "enchanter", "potion_dealer", "adventurer",
        ]

        # Disable all buttons during execution
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

        # Initial progress embed
        embed = discord.Embed(
            title="⏰ 全部打工中... / Working All...",
            description="正在逐项执行打工任务...\n" + progress_bar(0, len(all_jobs)),
            color=0x3498DB,
        )
        msg = await interaction.followup.send(embed=embed)

        bal_before = get_balance(uid)
        results = []  # list of {job, label, earned, skipped, cd, error}
        total_earned = 0
        exp_total = 0

        for i, job in enumerate(all_jobs):
            # Check cooldown
            remaining = _get_cd_remaining(uid, job)
            if remaining > 0:
                results.append({
                    "job": job,
                    "label": self.JOB_LABELS.get(job, job),
                    "earned": 0,
                    "skipped": True,
                    "cd": _format_cd(remaining),
                })
                continue

            pre_bal = get_balance(uid)
            try:
                # Execute job
                if job == "work":
                    base = random.randint(50, 200)
                    if random.random() < 0.10:
                        base += random.randint(100, 300)
                    add_coins(uid, base, "打工收入 / Work income (Work All)")
                    _update_cd(uid, job)
                elif job == "beg":
                    roll = random.random()
                    if roll < 0.60:
                        base = random.randint(10, 80)
                    elif roll < 0.90:
                        base = 0
                    else:
                        base = random.randint(200, 500)
                    if base > 0:
                        add_coins(uid, base, "乞讨收入 / Begging income (Work All)")
                    _update_cd(uid, job)
                elif job == "fish":
                    roll = random.random()
                    if roll < 0.05:
                        base = random.randint(500, 2000)
                    elif roll < 0.25:
                        base = random.randint(100, 200)
                    elif roll < 0.55:
                        base = random.randint(30, 60)
                    elif roll < 0.85:
                        base = random.randint(5, 20)
                    else:
                        base = 0
                    if base > 0:
                        add_coins(uid, base, "钓鱼收入 / Fishing income (Work All)")
                    _update_cd(uid, job)
                elif job == "hunt":
                    await _do_hunt(self.guild, uname, uid)
                    # _do_hunt updates cd and coins internally
                elif job == "treasure":
                    await _do_treasure(self.guild, uname, uid)
                elif job == "busk":
                    await _do_busk(self.guild, uname, uid)
                elif job == "stock":
                    await _do_stock(uname, uid)
                elif job == "miner":
                    await _do_miner(self.guild, uname, uid)
                elif job == "fisher":
                    await _do_fisher(self.guild, uname, uid)
                elif job == "hunter":
                    await _do_hunter_job(self.guild, uname, uid)
                elif job == "merchant":
                    await _do_merchant(self.guild, uname, uid)
                elif job == "bounty":
                    await _do_bounty(self.guild, uname, uid)
                elif job == "alchemist":
                    await _do_alchemist(self.guild, uname, uid)
                elif job == "blacksmith":
                    await _do_blacksmith(self.guild, uname, uid)
                elif job == "enchanter":
                    await _do_enchanter(self.guild, uname, uid)
                elif job == "potion_dealer":
                    await _do_potion_dealer(self.guild, uname, uid)
                elif job == "adventurer":
                    await _do_adventurer(self.guild, uname, uid)

                post_bal = get_balance(uid)
                earned = post_bal - pre_bal
                results.append({
                    "job": job,
                    "label": self.JOB_LABELS.get(job, job),
                    "earned": earned,
                    "skipped": False,
                })
                total_earned += earned
                exp_gain = _add_global_xp(uid, earned)
                exp_total += exp_gain
            except Exception as e:
                logger.error(f"Work All error on {job}: {e}")
                results.append({
                    "job": job,
                    "label": self.JOB_LABELS.get(job, job),
                    "earned": 0,
                    "skipped": False,
                    "error": True,
                })

            # Update progress
            done = i + 1
            total = len(all_jobs)
            desc_lines = [f"进度 / Progress: {progress_bar(done, total)} ({done}/{total})"]
            # Show last few results
            for r in results[-5:]:
                if r.get("skipped"):
                    desc_lines.append(f"{self.JOB_EMOJIS.get(r['job'], '')} **{r['label']}**: ⏳ 冷却中 ({r['cd']})")
                elif r.get("error"):
                    desc_lines.append(f"{self.JOB_EMOJIS.get(r['job'], '')} **{r['label']}**: ❌ 出错")
                elif r["earned"] > 0:
                    desc_lines.append(f"{self.JOB_EMOJIS.get(r['job'], '')} **{r['label']}**: +🪙{r['earned']:,}")
                elif r["earned"] < 0:
                    desc_lines.append(f"{self.JOB_EMOJIS.get(r['job'], '')} **{r['label']}**: 💸{abs(r['earned']):,}")
                else:
                    desc_lines.append(f"{self.JOB_EMOJIS.get(r['job'], '')} **{r['label']}**: +0")
            embed.description = "\n".join(desc_lines)
            try:
                await msg.edit(embed=embed)
            except (discord.NotFound, discord.HTTPException):
                pass
            await asyncio.sleep(0.5)

        # Build final summary embed
        bal_after = get_balance(uid)
        net_change = bal_after - bal_before

        summary_lines = [f"## 全部打工完成！ / Work All Complete!\n"]
        summary_lines.append(f"💰 总收入变动: {'+' if net_change >= 0 else ''}🪙 {net_change:,}")
        summary_lines.append(f"⭐ 获得 EXP: +{exp_total}")
        summary_lines.append(f"💼 最终余额: 🪙 {bal_after:,}\n")
        summary_lines.append("─── 明细 / Details ───")

        for r in results:
            emoji = self.JOB_EMOJIS.get(r["job"], "")
            if r.get("skipped"):
                summary_lines.append(f"{emoji} **{r['label']}**: ⏳ 冷却中")
            elif r.get("error"):
                summary_lines.append(f"{emoji} **{r['label']}**: ❌ 出错")
            elif r["earned"] > 0:
                summary_lines.append(f"{emoji} **{r['label']}**: +🪙{r['earned']:,}")
            elif r["earned"] < 0:
                summary_lines.append(f"{emoji} **{r['label']}**: 💸{abs(r['earned']):,}")
            else:
                summary_lines.append(f"{emoji} **{r['label']}**: +0")

        final_embed = discord.Embed(
            title="⏰ 全部打工 / Work All",
            description="\n".join(summary_lines),
            color=0x2ECC71 if net_change >= 0 else 0xE74C3C,
        )
        final_embed.set_footer(text=f"已完成 {len([r for r in results if not r.get('skipped')])}/{len(all_jobs)} 项打工，{len([r for r in results if r.get('skipped')])} 项冷却中")

        # Re-enable buttons
        for child in self.children:
            child.disabled = False
        await msg.edit(embed=final_embed, view=None)
        await interaction.edit_original_response(view=self)

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
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(str(interaction.user.id), interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
        elif self.dashboard_view:
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
        pre_bal = get_balance(uid)

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
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
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
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
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
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)
            if caught_member:
                await interaction.channel.send(
                    f"🐟 {caught_member.mention} 被 **{uname}** 钓鱼时钓上来了！\n"
                    f"You were fished up by **{uname}**!\n{caught_msg}"
                )

        elif job == "hunt":
            embed, hit_msg = await _do_hunt(self.guild, uname, uid)
            _update_progress(uid, "kill")
            await _animate_job(interaction, [
                f"🏹 {uname} 拉弓瞄准...",
                f"🐗 发现猎物！",
                f"💰 {uname} 放箭！",
            ], embed)
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
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
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)

        elif job == "busk":
            embed = await _do_busk(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"🎸 {uname} 在街头摆好设备...",
                f"🎶 {uname} 开始表演...",
                f"👏 路人们围了过来！",
            ], embed)
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)

        elif job == "stock":
            embed = await _do_stock(uname, uid)
            await _animate_job(interaction, [
                f"📈 {uname} 打开了股市软件...",
                f"💹 {uname} 正在分析走势...",
                f"📊 {uname} 下单买入！",
            ], embed)
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)

        elif job == "miner":
            embed = await _do_miner(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"⛏️ {uname} 戴上安全帽进入矿洞...",
                f"💎 {uname} 挥动十字镐...",
                f"🪨 矿石掉落了！",
            ], embed)
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)

        elif job == "fisher":
            embed = await _do_fisher(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"🎣 {uname} 撒下渔网...",
                f"🌊 海面泛起涟漪...",
                f"🐟 {uname} 收网！",
            ], embed)
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)

        elif job == "hunter":
            embed = await _do_hunter_job(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"🦌 {uname} 进入森林...",
                f"🏹 {uname} 拉弓瞄准...",
                f"🐗 {uname} 猎物倒下！",
            ], embed)
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)

        elif job == "merchant":
            embed = await _do_merchant(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"🧳 {uname} 打开货箱...",
                f"💬 {uname} 与商人讨价还价...",
                f"🤝 交易完成！",
            ], embed)
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)

        elif job == "bounty":
            embed = await _do_bounty(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"📜 {uname} 撕下悬赏令...",
                f"💀 {uname} 追踪目标...",
                f"⚔️ {uname} 与目标交战！",
            ], embed)
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)

        elif job == "alchemist":
            embed = await _do_alchemist(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"⚗️ {uname} 摆放烧瓶和试管...",
                f"🔮 {uname} 混合药剂...",
                f"💥 药水炼成！",
            ], embed)
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)

        elif job == "blacksmith":
            embed = await _do_blacksmith(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"🔨 {uname} 点燃熔炉...",
                f"🔥 {uname} 锻打铁锭...",
                f"⚔️ 武器出炉！",
            ], embed)
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)

        elif job == "enchanter":
            embed = await _do_enchanter(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"✨ {uname} 绘制魔法阵...",
                f"📖 {uname} 吟唱咒语...",
                f"💫 附魔完成！",
            ], embed)
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)

        elif job == "potion_dealer":
            embed = await _do_potion_dealer(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"🧪 {uname} 摆起药水摊位...",
                f"💬 {uname} 招揽顾客...",
                f"🪙 卖出药水！",
            ], embed)
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)

        elif job == "adventurer":
            embed = await _do_adventurer(self.guild, uname, uid)
            await _animate_job(interaction, [
                f"🗡️ {uname} 踏上冒险之旅...",
                f"🗺️ {uname} 探索未知领域...",
                f"💎 {uname} 发现宝藏！",
            ], embed)
            earned = get_balance(uid) - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
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


# ══════════════════════════════════════════════════════════════
# 新增打工函数 / New Job Shared Functions
# ══════════════════════════════════════════════════════════════

async def _do_miner(guild, uname: str, uid: str):
    """⛏️ 矿工 Miner — Lv.1, 50-150g, 30min CD, 10% fail"""
    roll = random.random()
    if roll < 0.10:
        base = random.randint(10, 30)
        add_coins(uid, base, "矿工收入 / Miner income (collapse)")
        desc = (f"{uname} 在矿洞深处挖掘时遭遇塌方... 只捡到可怜的 🪙 **{base:,}** 金币！\n"
                f"The mine collapsed on {uname}... Only salvaged 🪙 **{base:,}** coins!")
        color = 0x7F8C8D
    elif roll < 0.30:
        base = random.randint(50, 100)
        add_coins(uid, base, "矿工收入 / Miner income")
        desc = (f"{uname} 挖到了几块铁矿石，卖得 🪙 **{base:,}** 金币！\n"
                f"{uname} dug up some iron ore, sold for 🪙 **{base:,}** coins!")
        color = 0x95A5A6
    elif roll < 0.80:
        base = random.randint(80, 150)
        add_coins(uid, base, "矿工收入 / Miner income")
        desc = (f"{uname} 在矿洞深处挖到了金矿！卖得 🪙 **{base:,}** 金币！\n"
                f"{uname} struck gold in the mines! Sold for 🪙 **{base:,}** coins!")
        color = 0xF1C40F
    else:
        base = random.randint(200, 500)
        add_coins(uid, base, "矿工收入 / Miner income (diamond)")
        desc = (f"💎 {uname} 挖到了一颗闪亮的钻石！！卖得 🪙 **{base:,}** 金币！！\n"
                f"💎 {uname} found a glittering diamond!! Sold for 🪙 **{base:,}** coins!!")
        color = 0x3498DB
    if random.random() < 0.08:
        penalty = int(base * 0.5)
        add_coins(uid, -penalty, "矿洞瓦斯罚款 / Mine gas penalty")
        desc += f"\n\n💨 瓦斯泄漏！收入减半，损失 🪙 {penalty:,} / Gas leak! Income halved, lost 🪙 {penalty:,}"
    _update_cd(uid, "miner")
    bal = get_balance(uid)
    embed = discord.Embed(title=f"⛏️ {uname} 矿工 / Miner", description=desc, color=color)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.set_footer(text="矿工冷却 30 分钟 / Miner cooldown: 30 min")
    return embed


async def _do_fisher(guild, uname: str, uid: str):
    """🐟 渔夫 Fisher — Lv.1, 40-120g, 20min CD, 8% fail"""
    roll = random.random()
    if roll < 0.08:
        base = 0
        desc = (f"{uname} 出海捕鱼遭遇暴风雨... 空手而归！\n"
                f"A storm caught {uname} at sea... Returned empty-handed!")
        color = 0x7F8C8D
    elif roll < 0.30:
        base = random.randint(40, 70)
        desc = (f"{uname} 捕到了一些沙丁鱼，卖得 🪙 **{base:,}** 金币！\n"
                f"{uname} caught some sardines, sold for 🪙 **{base:,}** coins!")
        color = 0x3498DB
    elif roll < 0.80:
        base = random.randint(70, 120)
        desc = (f"🐟 {uname} 捕到了一网肥美的鲑鱼！卖得 🪙 **{base:,}** 金币！\n"
                f"🐟 {uname} netted a haul of salmon! Sold for 🪙 **{base:,}** coins!")
        color = 0xE67E22
    else:
        base = random.randint(150, 400)
        desc = (f"🐋 {uname} 捕到了一条巨大的金枪鱼！！卖得 🪙 **{base:,}** 金币！！\n"
                f"🐋 {uname} caught a giant tuna!! Sold for 🪙 **{base:,}** coins!!")
        color = 0xF1C40F
    if base > 0:
        add_coins(uid, base, "渔夫收入 / Fisher income")
    _update_cd(uid, "fisher")
    bal = get_balance(uid)
    embed = discord.Embed(title=f"🐟 {uname} 渔夫 / Fisher", description=desc, color=color)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.set_footer(text="渔夫冷却 20 分钟 / Fisher cooldown: 20 min")
    return embed


async def _do_hunter_job(guild, uname: str, uid: str):
    """🦌 猎人 Hunter — Lv.3, 80-200g, 40min CD, 15% fail"""
    roll = random.random()
    if roll < 0.15:
        base = 0
        desc = (f"{uname} 追踪了半天的猎物逃进了灌木丛... 一无所获！\n"
                f"{uname} tracked prey for hours but it escaped... Nothing!")
        color = 0x7F8C8D
    elif roll < 0.50:
        base = random.randint(80, 130)
        desc = (f"🐇 {uname} 猎到了几只野兔，卖得 🪙 **{base:,}** 金币！\n"
                f"🐇 {uname} hunted some rabbits, sold for 🪙 **{base:,}** coins!")
        color = 0x8E44AD
    elif roll < 0.85:
        base = random.randint(130, 200)
        desc = (f"🦌 {uname} 猎到了一头雄鹿！卖得 🪙 **{base:,}** 金币！\n"
                f"🦌 {uname} hunted a stag! Sold for 🪙 **{base:,}** coins!")
        color = 0xE74C3C
    else:
        base = random.randint(250, 600)
        desc = (f"🐻 {uname} 猎到了一头巨熊！！卖得 🪙 **{base:,}** 金币！！\n"
                f"🐻 {uname} brought down a massive bear!! Sold for 🪙 **{base:,}** coins!!")
        color = 0xF1C40F
    if base > 0:
        add_coins(uid, base, "猎人收入 / Hunter income")
    _update_cd(uid, "hunter")
    bal = get_balance(uid)
    embed = discord.Embed(title=f"🦌 {uname} 猎人 / Hunter", description=desc, color=color)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.set_footer(text="猎人冷却 40 分钟 / Hunter cooldown: 40 min")
    return embed


async def _do_merchant(guild, uname: str, uid: str):
    """🧳 商人 Merchant — Lv.5, 100-300g, 60min CD, 20% fail"""
    roll = random.random()
    if roll < 0.20:
        base = random.randint(30, 80)
        add_coins(uid, base, "商人收入 / Merchant income (loss)")
        desc = (f"{uname} 进货时被奸商骗了... 只勉强卖得 🪙 **{base:,}** 金币！\n"
                f"{uname} was scammed by a shady supplier... Barely made 🪙 **{base:,}** coins!")
        color = 0x7F8C8D
    elif roll < 0.70:
        base = random.randint(100, 200)
        add_coins(uid, base, "商人收入 / Merchant income")
        desc = (f"{uname} 在一个繁忙的市场卖出了货物，赚得 🪙 **{base:,}** 金币！\n"
                f"{uname} sold goods at a bustling market, earned 🪙 **{base:,}** coins!")
        color = 0x2ECC71
    elif roll < 0.95:
        base = random.randint(200, 300)
        add_coins(uid, base, "商人收入 / Merchant income")
        desc = (f"{uname} 谈成了一笔大生意！赚得 🪙 **{base:,}** 金币！\n"
                f"{uname} closed a big deal! Earned 🪙 **{base:,}** coins!")
        color = 0xF39C12
    else:
        base = random.randint(400, 800)
        add_coins(uid, base, "商人收入 / Merchant income (jackpot)")
        desc = (f"💰 {uname} 发现了一条利润丰厚的贸易路线！！赚得 🪙 **{base:,}** 金币！！\n"
                f"💰 {uname} discovered a lucrative trade route!! Earned 🪙 **{base:,}** coins!!")
        color = 0xF1C40F
    if random.random() < 0.10:
        penalty = int(base * 0.4)
        add_coins(uid, -penalty, "商人被劫 / Merchant robbed")
        desc += f"\n\n🔫 途中遭遇劫匪！损失 🪙 {penalty:,} / Robbed on the road! Lost 🪙 {penalty:,}"
    _update_cd(uid, "merchant")
    bal = get_balance(uid)
    embed = discord.Embed(title=f"🧳 {uname} 商人 / Merchant", description=desc, color=color)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.set_footer(text="商人冷却 1 小时 / Merchant cooldown: 1 hour")
    return embed


async def _do_bounty(guild, uname: str, uid: str):
    """💀 赏金猎人 Bounty Hunter — Lv.8, 200-500g, 90min CD, 30% fail"""
    roll = random.random()
    if roll < 0.30:
        base = random.randint(50, 150)
        add_coins(uid, base, "赏金收入 / Bounty income (failed)")
        desc = (f"{uname} 追踪目标失败，目标已经逃往其他城市... 只拿到 🪙 **{base:,}** 路费！\n"
                f"{uname} lost the target who fled... Only got 🪙 **{base:,}** travel pay!")
        color = 0x7F8C8D
    elif roll < 0.75:
        base = random.randint(200, 350)
        add_coins(uid, base, "赏金收入 / Bounty income")
        desc = (f"💀 {uname} 成功制服了通缉犯！领取赏金 🪙 **{base:,}** 金币！\n"
                f"💀 {uname} captured the wanted criminal! Bounty: 🪙 **{base:,}** coins!")
        color = 0xE74C3C
    else:
        base = random.randint(400, 800)
        add_coins(uid, base, "赏金收入 / Bounty income (boss)")
        desc = (f"💀 {uname} 击杀了一个危险的头号通缉犯！！赏金 🪙 **{base:,}** 金币！！\n"
                f"💀 {uname} took down a top wanted criminal!! Bounty: 🪙 **{base:,}** coins!!")
        color = 0xF1C40F
    if random.random() < 0.12:
        penalty = random.randint(50, 150)
        add_coins(uid, -penalty, "被通缉犯反杀罚款 / Bounty counter-attack")
        desc += f"\n\n🗡️ 通缉犯设下埋伏反扑！重伤损失 🪙 {penalty:,} / Ambushed! Lost 🪙 {penalty:,}"
    _update_cd(uid, "bounty")
    bal = get_balance(uid)
    embed = discord.Embed(title=f"💀 {uname} 赏金猎人 / Bounty Hunter", description=desc, color=color)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.set_footer(text="赏金猎人冷却 1.5 小时 / Bounty cooldown: 1.5 hours")
    return embed


async def _do_alchemist(guild, uname: str, uid: str):
    """⚗️ 炼金术师 Alchemist — Lv.10, 150-400g, 45min CD, 25% fail"""
    roll = random.random()
    if roll < 0.25:
        base = random.randint(30, 100)
        add_coins(uid, base, "炼金收入 / Alchemist income (fail)")
        desc = (f"{uname} 的药剂配方出了差错，烧瓶爆炸了！只卖得 🪙 **{base:,}** 金币！\n"
                f"{uname}'s potion formula went wrong, beaker exploded! Only 🪙 **{base:,}** coins!")
        color = 0xE74C3C
    elif roll < 0.75:
        base = random.randint(150, 300)
        add_coins(uid, base, "炼金收入 / Alchemist income")
        desc = (f"⚗️ {uname} 成功炼制出了治疗药水，卖得 🪙 **{base:,}** 金币！\n"
                f"⚗️ {uname} brewed healing potions, sold for 🪙 **{base:,}** coins!")
        color = 0x9B59B6
    else:
        base = random.randint(350, 700)
        add_coins(uid, base, "炼金收入 / Alchemist income (rare)")
        desc = (f"🔮 {uname} 炼出了传说中的贤者之石！！卖得 🪙 **{base:,}** 金币！！\n"
                f"🔮 {uname} created the legendary Philosopher's Stone!! Sold for 🪙 **{base:,}** coins!!")
        color = 0xF1C40F
    _update_cd(uid, "alchemist")
    bal = get_balance(uid)
    embed = discord.Embed(title=f"⚗️ {uname} 炼金术师 / Alchemist", description=desc, color=color)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.set_footer(text="炼金术师冷却 45 分钟 / Alchemist cooldown: 45 min")
    return embed


async def _do_blacksmith(guild, uname: str, uid: str):
    """🔨 铁匠 Blacksmith — Lv.7, 120-350g, 50min CD, 18% fail"""
    roll = random.random()
    if roll < 0.18:
        base = random.randint(40, 100)
        add_coins(uid, base, "铁匠收入 / Blacksmith income (fail)")
        desc = (f"{uname} 锻造时铁砧裂了，武器报废... 只卖得 🪙 **{base:,}** 废铁价！\n"
                f"{uname}'s anvil cracked while forging... Scrap sold for 🪙 **{base:,}**!")
        color = 0x7F8C8D
    elif roll < 0.70:
        base = random.randint(120, 250)
        add_coins(uid, base, "铁匠收入 / Blacksmith income")
        desc = (f"🔨 {uname} 打造了一把精良长剑，卖得 🪙 **{base:,}** 金币！\n"
                f"🔨 {uname} forged a fine longsword, sold for 🪙 **{base:,}** coins!")
        color = 0xE67E22
    else:
        base = random.randint(280, 500)
        add_coins(uid, base, "铁匠收入 / Blacksmith income (masterwork)")
        desc = (f"⚔️ {uname} 打造了一把大师级武器！！卖得 🪙 **{base:,}** 金币！！\n"
                f"⚔️ {uname} crafted a masterwork weapon!! Sold for 🪙 **{base:,}** coins!!")
        color = 0xF1C40F
    if random.random() < 0.08:
        penalty = random.randint(30, 80)
        add_coins(uid, -penalty, "锻造烧伤赔款 / Forge burn compensation")
        desc += f"\n\n🔥 熔炉过热烫伤了顾客！赔偿 🪙 {penalty:,} / Forge overheated! Paid 🪙 {penalty:,}"
    _update_cd(uid, "blacksmith")
    bal = get_balance(uid)
    embed = discord.Embed(title=f"🔨 {uname} 铁匠 / Blacksmith", description=desc, color=color)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.set_footer(text="铁匠冷却 50 分钟 / Blacksmith cooldown: 50 min")
    return embed


async def _do_enchanter(guild, uname: str, uid: str):
    """✨ 附魔师 Enchanter — Lv.12, 300-600g, 120min CD, 35% fail"""
    roll = random.random()
    if roll < 0.35:
        base = random.randint(80, 200)
        add_coins(uid, base, "附魔收入 / Enchanter income (fail)")
        desc = (f"{uname} 念错了咒语，附魔失败了！魔法反噬，只得到 🪙 **{base:,}** 金币！\n"
                f"{uname} mispronounced the incantation! Magical backlash, only 🪙 **{base:,}** coins!")
        color = 0x7F8C8D
    elif roll < 0.80:
        base = random.randint(300, 450)
        add_coins(uid, base, "附魔收入 / Enchanter income")
        desc = (f"✨ {uname} 成功为武器附上了火焰附魔！赚得 🪙 **{base:,}** 金币！\n"
                f"✨ {uname} enchanted a weapon with fire! Earned 🪙 **{base:,}** coins!")
        color = 0x9B59B6
    else:
        base = random.randint(500, 900)
        add_coins(uid, base, "附魔收入 / Enchanter income (legendary)")
        desc = (f"💫 {uname} 施展了传说级附魔！！赚得 🪙 **{base:,}** 金币！！\n"
                f"💫 {uname} cast a legendary enchantment!! Earned 🪙 **{base:,}** coins!!")
        color = 0xF1C40F
    _update_cd(uid, "enchanter")
    bal = get_balance(uid)
    embed = discord.Embed(title=f"✨ {uname} 附魔师 / Enchanter", description=desc, color=color)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.set_footer(text="附魔师冷却 2 小时 / Enchanter cooldown: 2 hours")
    return embed


async def _do_potion_dealer(guild, uname: str, uid: str):
    """🧪 药水商 Potion Dealer — Lv.6, 100-250g, 35min CD, 12% fail"""
    roll = random.random()
    if roll < 0.12:
        base = random.randint(30, 70)
        add_coins(uid, base, "药水商收入 / Potion dealer income (fail)")
        desc = (f"{uname} 的药水被查出是假货，被罚款后只剩 🪙 **{base:,}** 金币...\n"
                f"{uname}'s potions were exposed as counterfeit! Fined, only 🪙 **{base:,}** left...")
        color = 0x7F8C8D
    elif roll < 0.70:
        base = random.randint(100, 180)
        add_coins(uid, base, "药水商收入 / Potion dealer income")
        desc = (f"🧪 {uname} 在集市上卖出了几瓶药水，赚得 🪙 **{base:,}** 金币！\n"
                f"🧪 {uname} sold some potions at the market, earned 🪙 **{base:,}** coins!")
        color = 0x2ECC71
    else:
        base = random.randint(200, 400)
        add_coins(uid, base, "药水商收入 / Potion dealer income (hot)")
        desc = (f"💊 {uname} 的自制特效药水大受欢迎！！赚得 🪙 **{base:,}** 金币！！\n"
                f"💊 {uname}'s special brew was a hit!! Earned 🪙 **{base:,}** coins!!")
        color = 0xF39C12
    _update_cd(uid, "potion_dealer")
    bal = get_balance(uid)
    embed = discord.Embed(title=f"🧪 {uname} 药水商 / Potion Dealer", description=desc, color=color)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.set_footer(text="药水商冷却 35 分钟 / Potion Dealer cooldown: 35 min")
    return embed


async def _do_adventurer(guild, uname: str, uid: str):
    """🗡️ 冒险家 Adventurer — Lv.15, 500-1000g, 180min CD, 40% fail"""
    roll = random.random()
    if roll < 0.40:
        base = random.randint(100, 300)
        add_coins(uid, base, "冒险收入 / Adventurer income (fail)")
        scenarios = [
            "遭遇了龙卷风，装备全毁",
            "掉进了陷阱，差点没命",
            "迷路了三天三夜",
            "被山贼洗劫一空",
        ]
        scenario = random.choice(scenarios)
        desc = (f"{uname} 踏上冒险，但{scenario}... 只带回 🪙 **{base:,}** 金币！\n"
                f"{uname} went on an adventure, but disaster struck... Only 🪙 **{base:,}** coins!")
        color = 0x7F8C8D
    elif roll < 0.80:
        base = random.randint(500, 800)
        add_coins(uid, base, "冒险收入 / Adventurer income")
        desc = (f"🗡️ {uname} 探索了一座古老遗迹，发现 🪙 **{base:,}** 金币！\n"
                f"🗡️ {uname} explored ancient ruins, found 🪙 **{base:,}** coins!")
        color = 0xE67E22
    else:
        base = random.randint(900, 1500)
        add_coins(uid, base, "冒险收入 / Adventurer income (legend)")
        desc = (f"👑 {uname} 发现了一座失落的黄金之城！！带回 🪙 **{base:,}** 金币！！\n"
                f"👑 {uname} discovered a lost city of gold!! Brought back 🪙 **{base:,}** coins!!")
        color = 0xF1C40F
    if random.random() < 0.15:
        penalty = int(base * 0.4)
        add_coins(uid, -penalty, "冒险队友背叛 / Party member betrayal")
        desc += f"\n\n😈 队友背叛偷走了宝藏！损失 🪙 {penalty:,} / Betrayed! Lost 🪙 {penalty:,}"
    _update_cd(uid, "adventurer")
    bal = get_balance(uid)
    embed = discord.Embed(title=f"🗡️ {uname} 冒险家 / Adventurer", description=desc, color=color)
    embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
    embed.set_footer(text="冒险家冷却 3 小时 / Adventurer cooldown: 3 hours")
    return embed



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
            pre_bal = get_balance(uid)

            base = random.randint(50, 200)
            bonus = 0
            bonus_msg = ""

            if random.random() < 0.10:
                bonus = random.randint(100, 300)
                base += bonus
                bonus_msg = f"\n🔥 **加班事件 / Overtime Bonus!** 🪙 +{bonus:,}"

            add_coins(uid, base, "打工收入 / Work income")
            _update_progress(uid, "work")
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
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
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
            pre_bal = get_balance(uid)
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
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
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
            pre_bal = get_balance(uid)

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
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
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
            pre_bal = get_balance(uid)

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
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
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
            pre_bal = get_balance(uid)

            embed, hit_msg = await _do_hunt(interaction.guild, uname, uid)
            await interaction.response.defer()
            frames = [
                f"🏹 {uname} 进入猎场...",
                f"🐗 {uname} 搜寻猎物中...",
                f"🐾 {uname} 发现猎物！",
            ]
            await _animate_job(interaction, frames, embed)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
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
            pre_bal = get_balance(uid)
            embed = await _do_treasure(interaction.guild, uname, uid)
            await interaction.response.defer()
            frames = [
                f"🗺️ {uname} 展开藏宝图...",
                f"⛏️ {uname} 挖掘中...",
                f"📦 {uname} 找到了什么！",
            ]
            await _animate_job(interaction, frames, embed)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
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
            pre_bal = get_balance(uid)
            embed = await _do_busk(interaction.guild, uname, uid)
            await interaction.response.defer()
            frames = [
                f"🎸 {uname} 摆好摊位...",
                f"🎶 {uname} 卖力演奏中...",
                f"🎩 {uname} 收取打赏！",
            ]
            await _animate_job(interaction, frames, embed)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
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
            pre_bal = get_balance(uid)
            embed = await _do_stock(uname, uid)
            await interaction.response.defer()
            frames = [
                f"📈 {uname} 盯盘中...",
                f"💹 {uname} 果断出手...",
                f"📊 {uname} 交易完成！",
            ]
            await _animate_job(interaction, frames, embed)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            post_bal = get_balance(uid)
            earned = post_bal - pre_bal
            if earned != 0:
                _add_global_xp(uid, earned)
            await _handle_job_xp(uid, interaction)
        except Exception as e:
            logger.error(f"[stock_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 炒股命令出错，请重试 / Stock error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 炒股命令出错，请重试 / Stock error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-job miner — 矿工
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="miner", description="⛏️ 矿工 / Mining — dig for ore and gems! (30 min cooldown)")
    @app_commands.checks.cooldown(1, 1800, key=lambda i: (i.guild_id, i.user.id))
    async def miner_cmd(self, interaction: discord.Interaction):
        """矿工."""
        uid = str(interaction.user.id)
        remaining = _get_cd_remaining(uid, "miner")
        if remaining > 0:
            return await interaction.response.send_message(
                f"⏳ 矿工冷却中！剩余 **{_format_cd(remaining)}** / Miner cooldown! Remaining: **{_format_cd(remaining)}**",
                ephemeral=True,
            )
        uname = interaction.user.display_name
        pre_bal = get_balance(uid)
        embed = await _do_miner(interaction.guild, uname, uid)
        await interaction.response.defer()
        frames = [
            f"⛏️ {uname} 戴上安全帽进入矿洞...",
            f"💎 {uname} 挥动十字镐挖掘中...",
            f"🪨 {uname} 收获矿石！",
        ]
        await _animate_job(interaction, frames, embed)
        post_bal = get_balance(uid)
        earned = post_bal - pre_bal
        if earned != 0:
            _add_global_xp(uid, earned)
        await _handle_job_xp(uid, interaction)

    # ══════════════════════════════════════════════════════════
    # /gmpt-job fisher — 渔夫
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="fisherman", description="🐟 渔夫 / Fishing — cast nets at sea! (20 min cooldown)")
    @app_commands.checks.cooldown(1, 1200, key=lambda i: (i.guild_id, i.user.id))
    async def fisherman_cmd(self, interaction: discord.Interaction):
        """渔夫."""
        uid = str(interaction.user.id)
        remaining = _get_cd_remaining(uid, "fisher")
        if remaining > 0:
            return await interaction.response.send_message(
                f"⏳ 渔夫冷却中！剩余 **{_format_cd(remaining)}** / Fisher cooldown! Remaining: **{_format_cd(remaining)}**",
                ephemeral=True,
            )
        uname = interaction.user.display_name
        pre_bal = get_balance(uid)
        embed = await _do_fisher(interaction.guild, uname, uid)
        await interaction.response.defer()
        frames = [
            f"🎣 {uname} 撒下渔网...",
            f"🌊 {uname} 等待鱼群...",
            f"🐟 {uname} 收网！",
        ]
        await _animate_job(interaction, frames, embed)
        post_bal = get_balance(uid)
        earned = post_bal - pre_bal
        if earned != 0:
            _add_global_xp(uid, earned)
        await _handle_job_xp(uid, interaction)

    # ══════════════════════════════════════════════════════════
    # /gmpt-job hunter — 猎人
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="hunterjob", description="🦌 猎人 / Hunting — track and hunt prey! (40 min cooldown)")
    @app_commands.checks.cooldown(1, 2400, key=lambda i: (i.guild_id, i.user.id))
    async def hunter_job_cmd(self, interaction: discord.Interaction):
        """猎人."""
        uid = str(interaction.user.id)
        remaining = _get_cd_remaining(uid, "hunter")
        if remaining > 0:
            return await interaction.response.send_message(
                f"⏳ 猎人冷却中！剩余 **{_format_cd(remaining)}** / Hunter cooldown! Remaining: **{_format_cd(remaining)}**",
                ephemeral=True,
            )
        uname = interaction.user.display_name
        pre_bal = get_balance(uid)
        embed = await _do_hunter_job(interaction.guild, uname, uid)
        await interaction.response.defer()
        frames = [
            f"🦌 {uname} 进入森林...",
            f"🏹 {uname} 追踪猎物足迹...",
            f"🐗 {uname} 发射！",
        ]
        await _animate_job(interaction, frames, embed)
        post_bal = get_balance(uid)
        earned = post_bal - pre_bal
        if earned != 0:
            _add_global_xp(uid, earned)
        await _handle_job_xp(uid, interaction)

    # ══════════════════════════════════════════════════════════
    # /gmpt-job merchant — 商人
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="merchant", description="🧳 商人 / Trading — buy low sell high! (60 min cooldown)")
    @app_commands.checks.cooldown(1, 3600, key=lambda i: (i.guild_id, i.user.id))
    async def merchant_cmd(self, interaction: discord.Interaction):
        """商人."""
        uid = str(interaction.user.id)
        remaining = _get_cd_remaining(uid, "merchant")
        if remaining > 0:
            return await interaction.response.send_message(
                f"⏳ 商人冷却中！剩余 **{_format_cd(remaining)}** / Merchant cooldown! Remaining: **{_format_cd(remaining)}**",
                ephemeral=True,
            )
        uname = interaction.user.display_name
        pre_bal = get_balance(uid)
        embed = await _do_merchant(interaction.guild, uname, uid)
        await interaction.response.defer()
        frames = [
            f"🧳 {uname} 整理货物...",
            f"💬 {uname} 讨价还价中...",
            f"🤝 {uname} 成交！",
        ]
        await _animate_job(interaction, frames, embed)
        post_bal = get_balance(uid)
        earned = post_bal - pre_bal
        if earned != 0:
            _add_global_xp(uid, earned)
        await _handle_job_xp(uid, interaction)

    # ══════════════════════════════════════════════════════════
    # /gmpt-job bounty — 赏金猎人
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="bounty", description="💀 赏金猎人 / Bounty hunting — capture wanted criminals! (90 min cooldown)")
    @app_commands.checks.cooldown(1, 5400, key=lambda i: (i.guild_id, i.user.id))
    async def bounty_cmd(self, interaction: discord.Interaction):
        """赏金猎人."""
        uid = str(interaction.user.id)
        remaining = _get_cd_remaining(uid, "bounty")
        if remaining > 0:
            return await interaction.response.send_message(
                f"⏳ 赏金猎人冷却中！剩余 **{_format_cd(remaining)}** / Bounty cooldown! Remaining: **{_format_cd(remaining)}**",
                ephemeral=True,
            )
        uname = interaction.user.display_name
        pre_bal = get_balance(uid)
        embed = await _do_bounty(interaction.guild, uname, uid)
        await interaction.response.defer()
        frames = [
            f"📜 {uname} 撕下悬赏令...",
            f"💀 {uname} 追踪目标...",
            f"⚔️ {uname} 与目标交战！",
        ]
        await _animate_job(interaction, frames, embed)
        post_bal = get_balance(uid)
        earned = post_bal - pre_bal
        if earned != 0:
            _add_global_xp(uid, earned)
        await _handle_job_xp(uid, interaction)

    # ══════════════════════════════════════════════════════════
    # /gmpt-job alchemist — 炼金术师
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="alchemist", description="⚗️ 炼金术师 / Alchemy — brew potions and elixirs! (45 min cooldown)")
    @app_commands.checks.cooldown(1, 2700, key=lambda i: (i.guild_id, i.user.id))
    async def alchemist_cmd(self, interaction: discord.Interaction):
        """炼金术师."""
        uid = str(interaction.user.id)
        remaining = _get_cd_remaining(uid, "alchemist")
        if remaining > 0:
            return await interaction.response.send_message(
                f"⏳ 炼金术师冷却中！剩余 **{_format_cd(remaining)}** / Alchemist cooldown! Remaining: **{_format_cd(remaining)}**",
                ephemeral=True,
            )
        uname = interaction.user.display_name
        pre_bal = get_balance(uid)
        embed = await _do_alchemist(interaction.guild, uname, uid)
        await interaction.response.defer()
        frames = [
            f"⚗️ {uname} 摆放烧瓶...",
            f"🔮 {uname} 混合药剂...",
            f"💥 {uname} 炼成药水！",
        ]
        await _animate_job(interaction, frames, embed)
        post_bal = get_balance(uid)
        earned = post_bal - pre_bal
        if earned != 0:
            _add_global_xp(uid, earned)
        await _handle_job_xp(uid, interaction)

    # ══════════════════════════════════════════════════════════
    # /gmpt-job blacksmith — 铁匠
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="blacksmith", description="🔨 铁匠 / Blacksmith — forge weapons and armor! (50 min cooldown)")
    @app_commands.checks.cooldown(1, 3000, key=lambda i: (i.guild_id, i.user.id))
    async def blacksmith_cmd(self, interaction: discord.Interaction):
        """铁匠."""
        uid = str(interaction.user.id)
        remaining = _get_cd_remaining(uid, "blacksmith")
        if remaining > 0:
            return await interaction.response.send_message(
                f"⏳ 铁匠冷却中！剩余 **{_format_cd(remaining)}** / Blacksmith cooldown! Remaining: **{_format_cd(remaining)}**",
                ephemeral=True,
            )
        uname = interaction.user.display_name
        pre_bal = get_balance(uid)
        embed = await _do_blacksmith(interaction.guild, uname, uid)
        await interaction.response.defer()
        frames = [
            f"🔨 {uname} 点燃熔炉...",
            f"🔥 {uname} 锻打铁锭...",
            f"⚔️ {uname} 武器出炉！",
        ]
        await _animate_job(interaction, frames, embed)
        post_bal = get_balance(uid)
        earned = post_bal - pre_bal
        if earned != 0:
            _add_global_xp(uid, earned)
        await _handle_job_xp(uid, interaction)

    # ══════════════════════════════════════════════════════════
    # /gmpt-job enchanter — 附魔师
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="enchanter", description="✨ 附魔师 / Enchanting — imbue items with magic! (120 min cooldown)")
    @app_commands.checks.cooldown(1, 7200, key=lambda i: (i.guild_id, i.user.id))
    async def enchanter_cmd(self, interaction: discord.Interaction):
        """附魔师."""
        uid = str(interaction.user.id)
        remaining = _get_cd_remaining(uid, "enchanter")
        if remaining > 0:
            return await interaction.response.send_message(
                f"⏳ 附魔师冷却中！剩余 **{_format_cd(remaining)}** / Enchanter cooldown! Remaining: **{_format_cd(remaining)}**",
                ephemeral=True,
            )
        uname = interaction.user.display_name
        pre_bal = get_balance(uid)
        embed = await _do_enchanter(interaction.guild, uname, uid)
        await interaction.response.defer()
        frames = [
            f"✨ {uname} 绘制魔法阵...",
            f"📖 {uname} 吟唱咒语...",
            f"💫 {uname} 附魔完成！",
        ]
        await _animate_job(interaction, frames, embed)
        post_bal = get_balance(uid)
        earned = post_bal - pre_bal
        if earned != 0:
            _add_global_xp(uid, earned)
        await _handle_job_xp(uid, interaction)

    # ══════════════════════════════════════════════════════════
    # /gmpt-job potiondealer — 药水商
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="potiondealer", description="🧪 药水商 / Potion dealing — sell potions at the market! (35 min cooldown)")
    @app_commands.checks.cooldown(1, 2100, key=lambda i: (i.guild_id, i.user.id))
    async def potiondealer_cmd(self, interaction: discord.Interaction):
        """药水商."""
        uid = str(interaction.user.id)
        remaining = _get_cd_remaining(uid, "potion_dealer")
        if remaining > 0:
            return await interaction.response.send_message(
                f"⏳ 药水商冷却中！剩余 **{_format_cd(remaining)}** / Potion Dealer cooldown! Remaining: **{_format_cd(remaining)}**",
                ephemeral=True,
            )
        uname = interaction.user.display_name
        pre_bal = get_balance(uid)
        pre_bal = get_balance(uid)
        embed = await _do_potion_dealer(interaction.guild, uname, uid)
        await interaction.response.defer()
        frames = [
            f"🧪 {uname} 摆起摊位...",
            f"💬 {uname} 招揽顾客...",
            f"🪙 {uname} 卖出药水！",
        ]
        await _animate_job(interaction, frames, embed)
        post_bal = get_balance(uid)
        earned = post_bal - pre_bal
        if earned != 0:
            _add_global_xp(uid, earned)
        await _handle_job_xp(uid, interaction)

    # ══════════════════════════════════════════════════════════
    # /gmpt-job adventurer — 冒险家
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="adventurer", description="🗡️ 冒险家 / Adventuring — explore unknown lands! (3h cooldown)")
    @app_commands.checks.cooldown(1, 10800, key=lambda i: (i.guild_id, i.user.id))
    async def adventurer_cmd(self, interaction: discord.Interaction):
        """冒险家."""
        uid = str(interaction.user.id)
        remaining = _get_cd_remaining(uid, "adventurer")
        if remaining > 0:
            return await interaction.response.send_message(
                f"⏳ 冒险家冷却中！剩余 **{_format_cd(remaining)}** / Adventurer cooldown! Remaining: **{_format_cd(remaining)}**",
                ephemeral=True,
            )
        uname = interaction.user.display_name
        embed = await _do_adventurer(interaction.guild, uname, uid)
        await interaction.response.defer()
        frames = [
            f"🗡️ {uname} 背上行囊出发...",
            f"🗺️ {uname} 探索未知领域...",
            f"💎 {uname} 发现宝藏！",
        ]
        await _animate_job(interaction, frames, embed)
        post_bal = get_balance(uid)
        earned = post_bal - pre_bal
        if earned != 0:
            _add_global_xp(uid, earned)
        await _handle_job_xp(uid, interaction)

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
            name="基础 / Basic",
            value=(
                "🏭 **打工 Work** — 1h CD\n"
                "🥺 **乞讨 Beg** — 5min CD\n"
                "🎣 **钓鱼 Fish** — 3min CD"
            ),
            inline=True,
        )
        embed.add_field(
            name="采集 / Gathering",
            value=(
                "⛏️ **矿工 Miner** — 30min CD\n"
                "🐟 **渔夫 Fisher** — 20min CD\n"
                "🦌 **猎人 Hunter** — 40min CD\n"
                "🏹 **狩猎 Hunt** — 5min CD"
            ),
            inline=True,
        )
        embed.add_field(
            name="工匠 / Crafting",
            value=(
                "🔨 **铁匠 Smith** — 50min CD\n"
                "⚗️ **炼金术师 Alchemist** — 45min CD\n"
                "✨ **附魔师 Enchanter** — 2h CD"
            ),
            inline=True,
        )
        embed.add_field(
            name="商业 / Commerce",
            value=(
                "🧳 **商人 Merchant** — 1h CD\n"
                "🧪 **药水商 Potions** — 35min CD\n"
                "🎸 **卖艺 Busk** — 4min CD\n"
                "📈 **炒股 Stock** — 15min CD"
            ),
            inline=True,
        )
        embed.add_field(
            name="冒险 / Adventure",
            value=(
                "🗺️ **寻宝 Treasure** — 10min CD\n"
                "💀 **赏金猎人 Bounty** — 1.5h CD\n"
                "🗡️ **冒险家 Adventurer** — 3h CD"
            ),
            inline=True,
        )
        embed.add_field(
            name="危险 / Danger",
            value=(
                "🥷 **打劫 Rob** — 2h CD"
            ),
            inline=True,
        )
        embed.set_footer(text="每种工作有独立的冷却时间 | Each job has its own cooldown")
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(EconomyJobs(bot))
