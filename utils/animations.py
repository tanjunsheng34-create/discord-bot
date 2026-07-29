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


# ══════════════════════════════════════════════════════════════
# Internal helper — safe edit
# ══════════════════════════════════════════════════════════════

async def _safe_edit(interaction_or_msg, embed: discord.Embed):
    """Edit interaction original response or message, swallowing HTTP errors."""
    try:
        if isinstance(interaction_or_msg, discord.Interaction):
            await interaction_or_msg.edit_original_response(embed=embed)
        else:
            await interaction_or_msg.edit(embed=embed)
    except (discord.NotFound, discord.HTTPException):
        pass


# ══════════════════════════════════════════════════════════════
# Purchase Success Animation / 购买成功闪光动画
# ══════════════════════════════════════════════════════════════

async def purchase_success_animation(interaction_or_msg, item_name: str,
                                     item_emoji: str = "🛍️", price: int = 0,
                                     balance: int | None = None):
    """✨ Sparkle effect + item icon pop-out on successful purchase.

    Args:
        interaction_or_msg: discord.Interaction (deferred) or discord.Message
        item_name: Item display name (bilingual OK)
        item_emoji: Item emoji icon
        price: Price paid
        balance: Remaining balance (optional)
    """
    sparkle_frames = [
        f"## ✨ {item_emoji} ✨",
        f"## ✨💫 {item_emoji} 💫✨",
        f"# 🌟✨💫 {item_emoji} 💫✨🌟",
    ]
    for frame in sparkle_frames:
        embed = discord.Embed(description=frame, color=0xF1C40F)
        await _safe_edit(interaction_or_msg, embed)
        await asyncio.sleep(0.5)

    desc = (f"# {item_emoji} 购买成功！/ Purchase Success!\n\n"
            f"**{item_name}**\n"
            f"💰 花费 / Cost: 🪙 **{price:,}**")
    if balance is not None:
        desc += f"\n💳 余额 / Balance: 🪙 **{balance:,}**"
    embed = discord.Embed(description=desc, color=0x2ECC71)
    await _safe_edit(interaction_or_msg, embed)


# ══════════════════════════════════════════════════════════════
# Loot Drop Animation / 掉落庆祝动画
# ══════════════════════════════════════════════════════════════

async def loot_animation(interaction_or_msg, loot_name: str,
                         loot_emoji: str = "🎁", rarity: str = ""):
    """🎉 Celebration animation for boss loot / chest drops.

    Args:
        interaction_or_msg: discord.Interaction (deferred) or discord.Message
        loot_name: Loot display name (bilingual OK)
        loot_emoji: Loot emoji
        rarity: Rarity label, e.g. '🟡 传说 Legendary'
    """
    frames = [
        "## 📦 ...",
        "## 📦 ❗",
        "## 📦💥",
        f"# 🎉 {loot_emoji} 🎉",
    ]
    for frame in frames:
        embed = discord.Embed(description=frame, color=0xE67E22)
        await _safe_edit(interaction_or_msg, embed)
        await asyncio.sleep(0.55)

    desc = (f"# 🎉 获得战利品！/ Loot Acquired!\n\n"
            f"{loot_emoji} **{loot_name}**")
    if rarity:
        desc += f"\n品质 / Rarity: {rarity}"
    desc += "\n\n🎊🎊🎊"
    embed = discord.Embed(description=desc, color=0xF39C12)
    await _safe_edit(interaction_or_msg, embed)


# ══════════════════════════════════════════════════════════════
# Class Select Animation / 职业选择粒子动画
# ══════════════════════════════════════════════════════════════

async def class_select_animation(interaction_or_msg, class_name: str,
                                 class_emoji: str = "🌟"):
    """🌟 Particle effect when a class is chosen.

    Args:
        interaction_or_msg: discord.Interaction (deferred) or discord.Message
        class_name: Class display name (bilingual OK)
        class_emoji: Class emoji
    """
    frames = [
        f"## ⭐ {class_emoji}",
        f"## 🌟⭐ {class_emoji} ⭐🌟",
        f"# ✨🌟💫 {class_emoji} 💫🌟✨",
    ]
    for frame in frames:
        embed = discord.Embed(description=frame, color=0x9B59B6)
        await _safe_edit(interaction_or_msg, embed)
        await asyncio.sleep(0.55)

    embed = discord.Embed(
        description=(f"# {class_emoji} 转职成功！/ Class Selected!\n\n"
                     f"你现在是 **{class_name}**！\nYou are now a **{class_name}**!\n\n"
                     f"🌟✨💫✨🌟"),
        color=0x8E44AD,
    )
    await _safe_edit(interaction_or_msg, embed)


# ══════════════════════════════════════════════════════════════
# Card Flip Animation / 翻牌动画
# ══════════════════════════════════════════════════════════════

async def card_flip_animation(interaction_or_msg, card_display: str,
                              title: str = "🎴 翻牌 / Card Flip"):
    """Flip a face-down card to reveal its value.

    Args:
        interaction_or_msg: discord.Interaction (deferred) or discord.Message
        card_display: Final card text, e.g. 'K♠'
        title: Embed title
    """
    frames = ["## 🂠", "## 🂠 ↻", "## 🂠 ↺"]
    for frame in frames:
        embed = discord.Embed(title=title, description=frame, color=0x3498DB)
        await _safe_edit(interaction_or_msg, embed)
        await asyncio.sleep(0.5)

    embed = discord.Embed(title=title, description=f"# {card_display}", color=0x2ECC71)
    await _safe_edit(interaction_or_msg, embed)


# ══════════════════════════════════════════════════════════════
# Roulette Spin Animation / 轮盘旋转动画
# ══════════════════════════════════════════════════════════════

async def roulette_spin_animation(interaction_or_msg, result_number: int,
                                  result_color: str):
    """Spin the roulette wheel then reveal the result number.

    Args:
        interaction_or_msg: discord.Interaction (deferred) or discord.Message
        result_number: Winning number (0-36)
        result_color: '🔴' or '⚫' (or '🟢' for 0)
    """
    import random as _random
    spin_frames = []
    for _ in range(4):
        fake = _random.randint(1, 36)
        fake_color = _random.choice(["🔴", "⚫"])
        spin_frames.append(f"## 🎡 旋转中... / Spinning...\n# {fake_color} {fake}")
    for frame in spin_frames:
        embed = discord.Embed(description=frame, color=0xE74C3C)
        await _safe_edit(interaction_or_msg, embed)
        await asyncio.sleep(0.6)

    embed = discord.Embed(
        description=f"## 🎡 轮盘停止！/ Wheel stopped!\n# {result_color} **{result_number}**",
        color=0xF1C40F,
    )
    await _safe_edit(interaction_or_msg, embed)


# ══════════════════════════════════════════════════════════════
# Number Reveal Animation / 数字揭示动画
# ══════════════════════════════════════════════════════════════

async def number_reveal_animation(interaction_or_msg, number: int,
                                  title: str = "🔢 数字揭示 / Number Reveal"):
    """Reveal a hidden number with a scramble effect.

    Args:
        interaction_or_msg: discord.Interaction (deferred) or discord.Message
        number: The final number to reveal
        title: Embed title
    """
    import random as _random
    for _ in range(3):
        fake = _random.randint(1, 100)
        embed = discord.Embed(title=title, description=f"# ❓ {fake} ❓", color=0x95A5A6)
        await _safe_edit(interaction_or_msg, embed)
        await asyncio.sleep(0.5)

    embed = discord.Embed(title=title, description=f"# 🎯 **{number}**", color=0x2ECC71)
    await _safe_edit(interaction_or_msg, embed)


# ══════════════════════════════════════════════════════════════
# Cosmetics animations (外观动画)
# ══════════════════════════════════════════════════════════════

# Cosmetic item emoji mapping
COSMETIC_EMOJI = {
    "cosm_king_crown": "👑",
    "cosm_ninja_mask": "🥷",
    "cosm_angel_wings": "👼",
    "cosm_demon_horns": "👿",
    "cosm_rainbow_cape": "🌈",
    "cosm_golden_armor": "🛡️",
    "cosm_shadow_cloak": "🌑",
    "cosm_fire_aura": "🔥",
}


async def cosmetic_purchase_animation(interaction_or_msg, item_emoji: str, item_name: str,
                                      title: str = "🛍️ 购买外观 / Cosmetic Purchase"):
    """3-second purchase animation: emoji spins + scales + sparkles."""
    frames = [
        f"　　{item_emoji}　　",
        f"　{item_emoji} ✨　",
        f"✨ {item_emoji} ✨",
        f"　{item_emoji} ✨　",
        f"　　{item_emoji}　　",
        f"🌟 {item_emoji} 🌟",
        f"✨🌟 {item_emoji} 🌟✨",
        f"🌟 {item_emoji} 🌟",
    ]
    for i, frame in enumerate(frames):
        scale = "🔆" * (i % 3 + 1)
        embed = discord.Embed(
            title=title,
            description=f"# {frame}\n\n**{item_name}**\n{scale}",
            color=0xF1C40F,
        )
        await _safe_edit(interaction_or_msg, embed)
        await asyncio.sleep(0.4)
    embed = discord.Embed(
        title=f"✅ {title}",
        description=f"# 🌟 {item_emoji} ✨\n\n**{item_name}**\n已购买 / Purchased!",
        color=0x2ECC71,
    )
    await _safe_edit(interaction_or_msg, embed)


async def cosmetic_equip_animation(interaction_or_msg, item_emoji: str, item_name: str,
                                   title: str = "🎽 装备外观 / Equip Cosmetic"):
    """Equip animation: particle burst effect around the cosmetic emoji."""
    burst = ["·", "•", "∘", "○", "◌", "◉", "✺", "✸", "❉", "❋"]
    for i, b in enumerate(burst):
        embed = discord.Embed(
            title=title,
            description=f"# {b} {item_emoji} {b}\n\n**{item_name}**\n{'💫' * (i % 4 + 1)}",
            color=0x9B59B6,
        )
        await _safe_edit(interaction_or_msg, embed)
        await asyncio.sleep(0.3)
    embed = discord.Embed(
        title=f"✨ {title}",
        description=f"# 💥 {item_emoji} 💥\n\n**{item_name}**\n已装备 / Equipped!",
        color=0x8E44AD,
    )
    await _safe_edit(interaction_or_msg, embed)


def cosmetic_emoji_for(item_id: str) -> str:
    """Return the emoji for a cosmetic item id, fallback to 🎽."""
    return COSMETIC_EMOJI.get(item_id, "🎽")


# ══════════════════════════════════════════════════════════════
# Work Animation / 打工动画
# ══════════════════════════════════════════════════════════════

async def work_animation(
    interaction_or_msg,
    job_emoji: str,
    uname: str,
    earned: int,
    frames: list[str] = None,
):
    """Play a 3-frame work animation then show the result.
    
    Args:
        interaction_or_msg: discord.Interaction (deferred) or discord.Message
        job_emoji: Emoji representing the job (e.g., ⛏️)
        uname: Display name of the user
        earned: Amount earned (positive = gain, negative = loss, 0 = neutral)
        frames: Optional custom frame texts; defaults to job-specific ones
    
    Duration: ~2.2s total (3 frames × 0.6s + 0.4s hold), within 3s budget.
    """
    if frames is None:
        frames = [
            f"{job_emoji} {uname} 开始工作...",
            f"{job_emoji} {uname} 努力工作中...",
            f"{job_emoji} {uname} 即将完成...",
        ]

    # Format result
    if earned > 0:
        coins_emojis = "💰" * min(8, max(1, earned // 50))
        result = f"{job_emoji} **{uname}** 获得 {coins_emojis} +🪙{earned:,}!"
    elif earned < 0:
        loss_emojis = "💸" * min(5, max(1, abs(earned) // 100))
        result = f"{job_emoji} **{uname}** 亏损 {loss_emojis} -🪙{abs(earned):,}!"
    else:
        result = f"{job_emoji} **{uname}** 毫无收获..."
    
    frames.append(result)

    # Determine if we have an interaction or a message
    is_interaction = hasattr(interaction_or_msg, 'response')
    
    if is_interaction:
        msg = await interaction_or_msg.followup.send(frames[0])
    else:
        msg = interaction_or_msg
        await msg.edit(content=frames[0])
    
    for frame in frames[1:]:
        await asyncio.sleep(0.6)
        await msg.edit(content=frame)
    
    await asyncio.sleep(0.4)
    return msg


# ══════════════════════════════════════════════════════════════
# Mini-Game Animations (Task C)
# ══════════════════════════════════════════════════════════════

SCRATCH_REVEAL_FRAMES = [
    "💳 刮开中... 🟫🟫🟫",
    "💳 刮开中... 🟫✨🟫",
    "💳 刮开中... ✨🟫✨",
]


async def scratch_reveal_animation(interaction: discord.Interaction, result_emojis: str):
    """Scratch card reveal animation: 3 frames → show result.
    
    Duration: ~2.0s (3 × 0.5s + 0.5s hold).
    """
    msg = await interaction.followup.send(SCRATCH_REVEAL_FRAMES[0])
    for frame in SCRATCH_REVEAL_FRAMES[1:]:
        await asyncio.sleep(0.5)
        await msg.edit(content=frame)
    await asyncio.sleep(0.5)
    await msg.edit(content=f"💳 揭晓！{result_emojis}")


RUSSIAN_ROULETTE_FRAMES = [
    "🔫 转动转轮... 💨",
    "🔫 转轮旋转中... 🌀",
    "🔫 对准太阳穴... 😰",
]


async def russian_roulette_spin_animation(interaction: discord.Interaction, survived: bool):
    """Russian roulette chamber spin animation.
    
    Duration: ~2.0s. Returns the followup message for further edits.
    """
    msg = await interaction.followup.send(RUSSIAN_ROULETTE_FRAMES[0])
    for frame in RUSSIAN_ROULETTE_FRAMES[1:]:
        await asyncio.sleep(0.5)
        await msg.edit(content=frame)
    await asyncio.sleep(0.5)
    if survived:
        await msg.edit(content="🔫 **啪！空弹！** 💨 你活下来了！")
    else:
        await msg.edit(content="🔫 **砰！！！** 💥 你死了...")
    return msg


SLOT_EMOJIS = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣", "⭐"]


async def slot_spin_animation(interaction: discord.Interaction, cols: list[str]):
    """Slot machine spin animation: reels stop one by one.
    
    Duration: ~3.0s (3 × 0.8s + 0.6s).
    Returns the followup message for further edits.
    """
    c1, c2, c3 = cols
    msg = await interaction.followup.send(
        f"🎰 旋转中...\n| 🔄 | 🔄 | 🔄 |"
    )
    await asyncio.sleep(0.8)
    await msg.edit(content=f"🎰 第1列停！\n| {c1} | 🔄 | 🔄 |")
    await asyncio.sleep(0.8)
    await msg.edit(content=f"🎰 第2列停！\n| {c1} | {c2} | 🔄 |")
    await asyncio.sleep(0.8)
    await msg.edit(content=f"🎰 全部停止！\n| {c1} | {c2} | {c3} |")
    await asyncio.sleep(0.6)
    return msg


DICE_FRAMES = [
    ("🎲", "🎲"),
    ("⚀", "⚃"),
    ("⚁", "⚄"),
    ("⚂", "⚅"),
]


DICE_FACE = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}


async def dice_roll_animation(interaction: discord.Interaction, d1: int, d2: int):
    """Two dice roll animation: shake → reveal.
    
    Duration: ~2.0s.
    Returns the followup message for further edits.
    """
    msg = await interaction.followup.send("🎲 掷骰子中... | ⚀ | ⚁ |")
    await asyncio.sleep(0.5)
    await msg.edit(content="🎲 骰子旋转... | ⚂ | ⚃ |")
    await asyncio.sleep(0.5)
    await msg.edit(content="🎲 即将揭晓... | ⚄ | ⚅ |")
    await asyncio.sleep(0.5)
    d1_face = DICE_FACE.get(d1, str(d1))
    d2_face = DICE_FACE.get(d2, str(d2))
    total = d1 + d2
    await msg.edit(content=f"🎲 结果出来了！| {d1_face} | {d2_face} | = **{total}**")
    await asyncio.sleep(0.5)
    return msg


COIN_FLIP_FRAMES = [
    "🪙 硬币旋转中... 🌑",
    "🪙 硬币翻转中... 🌓",
    "🪙 即将落地... 🌕",
]


async def coin_flip_animation(interaction: discord.Interaction, result: str):
    """Coin flip animation: spin → reveal heads/tails.
    
    Duration: ~2.0s.
    Returns the followup message for further edits.
    """
    msg = await interaction.followup.send(COIN_FLIP_FRAMES[0])
    for frame in COIN_FLIP_FRAMES[1:]:
        await asyncio.sleep(0.5)
        await msg.edit(content=frame)
    await asyncio.sleep(0.5)
    emoji = "🪙✨" if result == "heads" else "🪙💫"
    label = "正面 Heads!" if result == "heads" else "反面 Tails!"
    await msg.edit(content=f"{emoji} 硬币落地！**{label}**")
    return msg


# ══════════════════════════════════════════════════════════════
# System Animations
# ══════════════════════════════════════════════════════════════

BOSS_DEFEAT_FRAMES = [
    "👹 Boss 摇摇欲坠...",
    "👹 Boss 发出最后的咆哮！",
    "💥 Boss 爆炸了！",
]


async def boss_defeat_animation(interaction: discord.Interaction, boss_name: str, boss_emoji: str):
    """Boss defeat animation: shake → roar → explode → loot.
    
    Duration: ~3.0s.
    """
    msg = await interaction.followup.send(f"{boss_emoji} **{boss_name}** 摇摇欲坠...")
    await asyncio.sleep(0.7)
    await msg.edit(content=f"{boss_emoji} **{boss_name}** 发出最后的咆哮！")
    await asyncio.sleep(0.7)
    await msg.edit(content=f"💥 **{boss_name}** 爆炸了！")
    await asyncio.sleep(0.7)
    await msg.edit(content=f"🎉 **{boss_name}** 被击败了！战利品掉落中...")
    await asyncio.sleep(0.5)
    return msg


async def quest_complete_animation(interaction: discord.Interaction, quest_name: str):
    """Daily quest completion animation.
    
    Duration: ~1.5s.
    """
    await interaction.followup.send(f"📋 任务完成！**{quest_name}**")
    await asyncio.sleep(0.5)


async def reward_claim_animation(interaction: discord.Interaction, coins: int, exp: int):
    """Reward claim animation with particle effects.
    
    Duration: ~2.0s.
    """
    msg = await interaction.followup.send("🎁 领取奖励中...")
    await asyncio.sleep(0.6)
    await msg.edit(content=f"🎁 获得 🪙 **{coins:,}** 金币！✨")
    await asyncio.sleep(0.6)
    await msg.edit(content=f"🎁 获得 🪙 **{coins:,}** 金币 + ⚡ **{exp}** 经验值！")
    await asyncio.sleep(0.6)
    return msg


async def equip_animation(interaction: discord.Interaction, item_name: str):
    """Equipment equip animation.
    
    Duration: ~1.5s.
    """
    msg = await interaction.followup.send(f"⚔️ 装备中...")
    await asyncio.sleep(0.5)
    await msg.edit(content=f"⚔️ **{item_name}** 已装备！🛡️")
    await asyncio.sleep(0.5)
    return msg


async def unequip_animation(interaction: discord.Interaction, item_name: str):
    """Equipment unequip animation.
    
    Duration: ~1.5s.
    """
    msg = await interaction.followup.send(f"📦 卸下中...")
    await asyncio.sleep(0.5)
    await msg.edit(content=f"📦 **{item_name}** 已卸下！")
    await asyncio.sleep(0.5)
    return msg


async def unlock_achievement_animation(interaction: discord.Interaction, ach_name: str, reward: int):
    """Achievement unlock animation with celebration.
    
    Duration: ~2.5s.
    """
    msg = await interaction.followup.send("🌟 成就解锁中...")
    await asyncio.sleep(0.6)
    await msg.edit(content=f"🌟🌟 成就解锁中...")
    await asyncio.sleep(0.6)
    await msg.edit(content=f"🏆 **成就解锁！** {ach_name}")
    await asyncio.sleep(0.6)
    await msg.edit(content=f"🏆 **成就解锁！** {ach_name}\n🪙 +{reward:,} 奖励！")
    await asyncio.sleep(0.5)
    return msg


async def insufficient_balance_animation(interaction: discord.Interaction, needed: int, have: int):
    """Insufficient balance animation with shake effect.
    
    Duration: ~1.0s.
    """
    await interaction.followup.send(
        f"💸 余额不足！需要 🪙 **{needed:,}**，你只有 🪙 **{have:,}**\n"
        f"Insufficient balance! Need 🪙 **{needed:,}**, you have 🪙 **{have:,}**"
    )


async def dungeon_enter_animation(interaction: discord.Interaction, floor_name: str):
    """Dungeon floor entrance animation.
    
    Duration: ~1.5s.
    """
    msg = await interaction.followup.send(f"🚪 进入 **{floor_name}**...")
    await asyncio.sleep(0.5)
    await msg.edit(content=f"🚪🚪 深入 **{floor_name}**...")
    await asyncio.sleep(0.5)
    await msg.edit(content=f"⚔️ 已到达 **{floor_name}**！准备战斗！")
    await asyncio.sleep(0.5)
    return msg


async def chest_reward_animation(interaction: discord.Interaction, coins: int):
    """Treasure chest reward animation.
    
    Duration: ~2.0s.
    """
    msg = await interaction.followup.send("📦 宝箱出现！")
    await asyncio.sleep(0.5)
    await msg.edit(content="📦✨ 打开宝箱中...")
    await asyncio.sleep(0.5)
    await msg.edit(content=f"🎁 宝箱打开！获得 🪙 **{coins:,}** 金币！")
    await asyncio.sleep(0.5)
    return msg
