"""
GMPT Bot — Animation Engine / 动画引擎
Provides reusable animation utilities for battle, countdown, progress bars, etc.
"""
import asyncio
import discord


# ══════════════════════════════════════════════════════════════
# Progress Bar / 进度条
# ══════════════════════════════════════════════════════════════

def progress_bar(current: int, maximum: int, length: int = 10,
                 filled: str = "█", empty: str = "░") -> str:
    """Generate an Emoji-style progress bar string.
    
    Args:
        current: Current value
        maximum: Maximum value
        length: Bar length in characters
        filled: Filled character
        empty: Empty character
    
    Returns:
        Formatted bar like [████████░░] 80/100
    """
    if maximum <= 0:
        ratio = 0
    else:
        ratio = max(0.0, min(1.0, current / maximum))
    f = max(0, min(length, int(ratio * length)))
    return f"[{filled * f}{empty * (length - f)}] {current}/{maximum}"


# ══════════════════════════════════════════════════════════════
# Battle Animation / 战斗动画
# ══════════════════════════════════════════════════════════════

async def battle_animation(interaction_or_msg, attacker_name: str, target_name: str,
                           damage: int, is_crit: bool = False, is_skill: bool = False,
                           skill_emoji: str = "", skill_name: str = ""):
    """Play a 3-frame battle animation then show damage result.
    
    Edits the interaction response or message with animated frames,
    then returns the final embed for caller to further modify.
    
    Args:
        interaction_or_msg: discord.Interaction (deferred) or discord.Message
        attacker_name: Name of the attacker
        target_name: Name of the target
        damage: Damage dealt
        is_crit: Whether this was a critical hit
        is_skill: Whether a skill was used
        skill_emoji: Skill emoji
        skill_name: Skill name in Chinese
    """
    if is_skill and skill_name:
        base_text = f"{skill_emoji} {attacker_name} {skill_name}攻击中"
    else:
        base_text = f"⚔️ {attacker_name} 攻击中"

    frames = [
        f"{base_text}...",
        f"{base_text}..",
        f"{base_text}...",
    ]

    for frame in frames:
        embed = discord.Embed(description=f"## {frame}", color=0xFF6600)
        try:
            if isinstance(interaction_or_msg, discord.Interaction):
                await interaction_or_msg.edit_original_response(embed=embed)
            else:
                await interaction_or_msg.edit(embed=embed)
        except (discord.NotFound, discord.HTTPException):
            pass
        await asyncio.sleep(0.5)

    # Build result embed
    crit_text = "💥 暴击 Critical!" if is_crit else ""
    if is_skill and skill_name:
        result_desc = f"💢 {target_name} {skill_name} — {damage} 伤害！\n{target_name} took {damage} damage!\n{crit_text}"
    else:
        result_desc = f"💢 {target_name} 受到 {damage} 点伤害！\n{target_name} took {damage} damage!\n{crit_text}"

    result_embed = discord.Embed(
        description=result_desc,
        color=0xFF0000 if is_crit else 0xFF6600,
    )
    try:
        if isinstance(interaction_or_msg, discord.Interaction):
            await interaction_or_msg.edit_original_response(embed=result_embed)
        else:
            await interaction_or_msg.edit(embed=result_embed)
    except (discord.NotFound, discord.HTTPException):
        pass


# ══════════════════════════════════════════════════════════════
# Countdown Animation / 倒计时动画
# ══════════════════════════════════════════════════════════════

async def countdown_animation(interaction_or_msg, seconds: int = 3):
    """Play a countdown animation (3→2→1).
    
    Edits the interaction response or message with countdown frames.
    After counting down, returns the final embed for caller use.
    """
    for i in range(seconds, 0, -1):
        embed = discord.Embed(
            description=f"# {i}...",
            color=0xFFA500,
        )
        try:
            if isinstance(interaction_or_msg, discord.Interaction):
                await interaction_or_msg.edit_original_response(embed=embed)
            else:
                await interaction_or_msg.edit(embed=embed)
        except (discord.NotFound, discord.HTTPException):
            pass
        await asyncio.sleep(0.8)


# ══════════════════════════════════════════════════════════════
# Boss Entrance Animation / Boss 出场动画
# ══════════════════════════════════════════════════════════════

async def boss_entrance_animation(interaction_or_msg, boss_name: str, boss_emoji: str,
                                  difficulty: str, player_count: int):
    """Animate boss name appearing letter-by-letter.
    
    Shows the boss name building up character by character with
    decorative emoji and effects.
    
    Args:
        interaction_or_msg: discord.Interaction (deferred) or discord.Message
        boss_name: Boss name in Chinese (e.g., "金龙")
        boss_emoji: Boss emoji (e.g., "🐉")
        difficulty: Difficulty string (e.g., "困难")
        player_count: Number of players in the dungeon
    """
    name_chars = list(boss_name)
    fire_emojis = ["🔥", "💀", "👹", "⚡", "💥", "🌟"]

    for i, char in enumerate(name_chars):
        partial = "".join(name_chars[:i + 1])
        fire_idx = i % len(fire_emojis)
        desc = (f"## {fire_emojis[fire_idx]} {boss_emoji} {partial}...\n\n"
                f"Difficulty / 难度: **{difficulty}**\n"
                f"Players / 玩家: **{player_count}**")
        embed = discord.Embed(description=desc, color=0xFF4500)
        try:
            if isinstance(interaction_or_msg, discord.Interaction):
                await interaction_or_msg.edit_original_response(embed=embed)
            else:
                await interaction_or_msg.edit(embed=embed)
        except (discord.NotFound, discord.HTTPException):
            pass
        await asyncio.sleep(0.6)

    # Final frame — boss roaring
    desc = (f"# {boss_emoji} {boss_name} 登场！/ {boss_name} Appears!\n\n"
            f"Difficulty / 难度: **{difficulty}**\n"
            f"Players / 玩家: **{player_count}**")
    embed = discord.Embed(description=desc, color=0xFF0000)
    try:
        if isinstance(interaction_or_msg, discord.Interaction):
            await interaction_or_msg.edit_original_response(embed=embed)
        else:
            await interaction_or_msg.edit(embed=embed)
    except (discord.NotFound, discord.HTTPException):
        pass


# ══════════════════════════════════════════════════════════════
# Purchase Confirmation Animation / 购买确认动画
# ══════════════════════════════════════════════════════════════

async def purchase_animation(interaction_or_msg, item_name_cn: str, item_name_en: str,
                             item_emoji: str, quantity: int, total_price: int):
    """Play a purchase confirmation with countdown → success.
    
    Args:
        interaction_or_msg: discord.Interaction (deferred) or discord.Message
        item_name_cn: Item Chinese name
        item_name_en: Item English name
        item_emoji: Item emoji
        quantity: Quantity purchased
        total_price: Total price paid
    """
    # Countdown: 3 → 2 → 1 → Purchase!
    for i in range(3, 0, -1):
        embed = discord.Embed(
            description=f"## {item_emoji} 购买确认中... {i}\nPurchasing {item_name_en}... {i}",
            color=0xFFA500,
        )
        try:
            if isinstance(interaction_or_msg, discord.Interaction):
                await interaction_or_msg.edit_original_response(embed=embed)
            else:
                await interaction_or_msg.edit(embed=embed)
        except (discord.NotFound, discord.HTTPException):
            pass
        await asyncio.sleep(0.6)

    # Success frame
    embed = discord.Embed(
        title=f"{item_emoji} Purchase Successful! / 购买成功！",
        description=(f"**{item_name_cn}** / **{item_name_en}**\n"
                     f"Quantity / 数量: **x{quantity}**\n"
                     f"Total / 总计: **🪙 {total_price}**"),
        color=0x2ECC71,
    )
    try:
        if isinstance(interaction_or_msg, discord.Interaction):
            await interaction_or_msg.edit_original_response(embed=embed)
        else:
            await interaction_or_msg.edit(embed=embed)
    except (discord.NotFound, discord.HTTPException):
        pass


# ══════════════════════════════════════════════════════════════
# PVP VS Animation / PVP 对决动画
# ══════════════════════════════════════════════════════════════

async def pvp_vs_animation(interaction_or_msg, p1_name: str, p2_name: str, bet: int):
    """Play PVP battle start animation: VS screen + countdown.
    
    Args:
        interaction_or_msg: discord.Interaction (deferred) or discord.Message
        p1_name: Player 1 name
        p2_name: Player 2 name
        bet: Bet amount
    """
    # VS frame
    embed = discord.Embed(
        title=f"⚔️ {p1_name}  VS  {p2_name} ⚔️",
        description=f"Bet / 赌注: **{bet}₲**\n\n准备战斗...\nPrepare for battle...",
        color=0xE74C3C,
    )
    try:
        if isinstance(interaction_or_msg, discord.Interaction):
            await interaction_or_msg.edit_original_response(embed=embed)
        else:
            await interaction_or_msg.edit(embed=embed)
    except (discord.NotFound, discord.HTTPException):
        pass
    await asyncio.sleep(1.5)

    # Countdown
    for i in range(3, 0, -1):
        embed = discord.Embed(
            title=f"⚔️ {p1_name}  VS  {p2_name} ⚔️",
            description=f"# {i}...",
            color=0xE74C3C,
        )
        try:
            if isinstance(interaction_or_msg, discord.Interaction):
                await interaction_or_msg.edit_original_response(embed=embed)
            else:
                await interaction_or_msg.edit(embed=embed)
        except (discord.NotFound, discord.HTTPException):
            pass
        await asyncio.sleep(0.8)

    # FIGHT! frame
    embed = discord.Embed(
        title=f"⚔️ {p1_name}  VS  {p2_name} ⚔️",
        description="# FIGHT! / 开战！🔥",
        color=0xFF0000,
    )
    try:
        if isinstance(interaction_or_msg, discord.Interaction):
            await interaction_or_msg.edit_original_response(embed=embed)
        else:
            await interaction_or_msg.edit(embed=embed)
    except (discord.NotFound, discord.HTTPException):
        pass
