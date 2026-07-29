"""
GMPT Bot — MMORPG PVP 对战系统 / Player vs Player Arena
/gmpt-pvp challenge  — 发起挑战
/gmpt-pvp accept     — 接受挑战
/gmpt-pvp decline    — 拒绝挑战
"""
import asyncio
import random
import time
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
from utils.animations import progress_bar, pvp_vs_animation
from cogs.economy import get_balance, add_coins
from cogs.mmorpg_skills import SKILLS
from cogs.mmorpg_shop import POTION_CATALOG
import logging

logger = logging.getLogger(__name__)

CHALLENGE_TIMEOUT = 60   # seconds to accept/decline
TURN_TIMEOUT = 30        # seconds per turn
CHALLENGE_ID_COUNTER = 1


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _get_user_stats(uid: str) -> dict:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT hp, max_hp, mp, max_mp, attack, defense, level FROM users WHERE discord_id = ?",
            (uid,),
        )
        row = cur.fetchone()
    if row:
        return dict(row)
    return {"hp": 100, "max_hp": 100, "mp": 50, "max_mp": 50, "attack": 10, "defense": 5, "level": 1}


def _save_pvp_stats(uid: str, stats: dict):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET hp = ?, mp = ? WHERE discord_id = ?",
                     (stats["hp"], stats["mp"], uid))
        conn.commit()


def _get_equipped_skills(uid: str) -> list[dict]:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT skill_id FROM player_skills WHERE user_id = ? AND equipped = 1",
            (uid,),
        )
        rows = cur.fetchall()
    result = []
    for r in rows:
        sid = r["skill_id"]
        if sid in SKILLS:
            result.append({"skill_id": sid, **SKILLS[sid]})
    return result


def _get_pvp_potions(uid: str) -> list[dict]:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT item_name, quantity FROM user_inventory WHERE user_id = ? AND item_type = 'potion' AND quantity > 0",
            (uid,),
        )
        return [dict(r) for r in cur.fetchall()]


def _consume_potion(uid: str, potion_name: str) -> dict | None:
    """Remove 1 potion from inventory, return POTION_CATALOG dict or None."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, quantity FROM user_inventory WHERE user_id = ? AND item_name = ? AND item_type = 'potion'",
            (uid, potion_name),
        )
        inv_row = cur.fetchone()
    if not inv_row or inv_row["quantity"] <= 0:
        return None
    if inv_row["quantity"] > 1:
        with get_db_ctx() as conn:
            conn.cursor().execute("UPDATE user_inventory SET quantity = quantity - 1 WHERE id = ?", (inv_row["id"],))
            conn.commit()
    else:
        with get_db_ctx() as conn:
            conn.cursor().execute("DELETE FROM user_inventory WHERE id = ?", (inv_row["id"],))
            conn.commit()
    return POTION_CATALOG.get(potion_name)


def _format_bar(current: int, maximum: int, length: int = 10, filled: str = "█", empty: str = "░") -> str:
    ratio = max(0, min(1, current / max(1, maximum)))
    f = int(ratio * length)
    return filled * f + empty * (length - f) + f" {current}/{maximum}"


# ══════════════════════════════════════════════════════════════
# PVP Battle View (Select-based)
# ══════════════════════════════════════════════════════════════

class PVPBattleView(discord.ui.View):
    """A View with one Select containing all actions: attack, skills, potions, surrender."""

    def __init__(self, room: dict, player_id: str, event: asyncio.Event, options: list[discord.SelectOption]):
        super().__init__(timeout=TURN_TIMEOUT)
        self.room = room
        self.player_id = player_id
        self.event = event
        self.result: dict | None = None

        select = discord.ui.Select(
            placeholder="选择你的行动 / Choose action...",
            options=options[:25],
            row=0,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.player_id:
            await interaction.response.send_message("现在不是你的回合！/ Not your turn!", ephemeral=True)
            return
        value = interaction.data["values"][0]
        if value == "attack":
            self.result = {"action": "attack"}
        elif value == "surrender":
            self.result = {"action": "surrender"}
        elif value.startswith("skill:"):
            self.result = {"action": "skill", "skill_id": value.split(":", 1)[1]}
        elif value.startswith("potion:"):
            self.result = {"action": "potion", "potion_name": value.split(":", 1)[1]}
        self.event.set()
        await interaction.response.defer()
        self.stop()

    async def on_timeout(self):
        self.result = {"action": "attack"}
        self.event.set()


# ══════════════════════════════════════════════════════════════
# PVP Cog
# ══════════════════════════════════════════════════════════════

class PVPCog(CogBase):
    """MMORPG 玩家对战系统 / Player vs Player Arena"""

    gmpt_pvp_group = app_commands.Group(
        name="gmpt-pvp",
        description="PVP对战 / Player vs Player — 回合制决斗"
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        # challenge_id → {challenger_id, defender_id, bet, status, created_at}
        self.pvp_challenges: dict[int, dict] = {}
        # room_id → full room state (see G2)
        self.pvp_rooms: dict[int, dict] = {}
        self._challenge_counter = CHALLENGE_ID_COUNTER

    # ══════════════════════════════════════════════════════════
    # /gmpt-pvp challenge
    # ══════════════════════════════════════════════════════════

    @gmpt_pvp_group.command(
        name="challenge",
        description="向其他玩家发起PVP挑战 / Challenge another player"
    )
    @app_commands.describe(
        opponent="挑战对象 / Opponent",
        bet="赌注金额 (0-10000₲) / Bet amount",
    )
    async def pvp_challenge(
        self,
        interaction: discord.Interaction,
        opponent: discord.Member,
        bet: int = 100,
    ):
        challenger_id = str(interaction.user.id)
        defender_id = str(opponent.id)

        if challenger_id == defender_id:
            return await interaction.response.send_message("不能挑战自己！/ Can't challenge yourself!", ephemeral=True)

        if opponent.bot:
            return await interaction.response.send_message("不能挑战机器人！/ Can't challenge bots!", ephemeral=True)

        if bet < 0 or bet > 10000:
            return await interaction.response.send_message("Bet range: 0-10000₲ / 赌注范围: 0-10000₲！", ephemeral=True)

        # Check challenger balance
        chal_bal = get_balance(challenger_id)
        if chal_bal < bet:
            return await interaction.response.send_message(
                f"Insufficient balance! Need {bet}₲, have {chal_bal}₲ / 余额不足！需要 {bet}₲，当前 {chal_bal}₲", ephemeral=True)

        # Check defender balance
        def_bal = get_balance(defender_id)
        if def_bal < bet:
            return await interaction.response.send_message(
                f"{opponent.display_name} doesn't have {bet}₲! / {opponent.display_name} 余额不足 {bet}₲！", ephemeral=True)

        # Check if either player is already in an active challenge
        for cid, ch in self.pvp_challenges.items():
            if ch["status"] == "waiting" and (
                challenger_id in (ch["challenger_id"], ch["defender_id"]) or
                defender_id in (ch["challenger_id"], ch["defender_id"])
            ):
                return await interaction.response.send_message(
                    "你或对手已有进行中的挑战！/ You or your opponent already has a pending challenge!",
                    ephemeral=True,
                )

        # Create challenge
        cid = self._challenge_counter
        self._challenge_counter += 1
        self.pvp_challenges[cid] = {
            "challenger_id": challenger_id,
            "challenger_name": interaction.user.display_name,
            "defender_id": defender_id,
            "defender_name": opponent.display_name,
            "bet": bet,
            "status": "waiting",
            "created_at": time.time(),
        }

        embed = discord.Embed(
            title="PVP Challenge! / PVP 挑战！",
            description=(
                f"**{interaction.user.mention}** challenged **{opponent.mention}**!\n"
                f"**{interaction.user.mention}** 向 **{opponent.mention}** 发起了挑战！\n\n"
                f"💰 Bet / 赌注: **{bet}₲**\n"
                f"⏰ Reply within / {CHALLENGE_TIMEOUT}秒内回复\n\n"
                f"Use / Type `/gmpt-pvp accept {cid}` to accept / 接受\n"
                f"or / 或 `/gmpt-pvp decline {cid}` to decline / 拒绝"
            ),
            color=0xE74C3C,
        )
        embed.set_footer(text=f"Challenge ID / 挑战ID: {cid}")
        await interaction.response.send_message(embed=embed)

        # Auto-cancel after timeout
        self.bot.loop.create_task(self._challenge_timeout(cid, interaction.channel))

    async def _challenge_timeout(self, cid: int, channel):
        await asyncio.sleep(CHALLENGE_TIMEOUT)
        ch = self.pvp_challenges.get(cid)
        if ch and ch["status"] == "waiting":
            ch["status"] = "expired"
            await channel.send(f"⏰ Challenge #{cid} expired / 挑战 #{cid} 已过期")

    # ══════════════════════════════════════════════════════════
    # /gmpt-pvp accept
    # ══════════════════════════════════════════════════════════

    @gmpt_pvp_group.command(
        name="accept",
        description="接受PVP挑战 / Accept a PVP challenge"
    )
    @app_commands.describe(challenge_id="挑战ID / Challenge ID")
    async def pvp_accept(self, interaction: discord.Interaction, challenge_id: int):
        uid = str(interaction.user.id)

        ch = self.pvp_challenges.get(challenge_id)
        if not ch:
            return await interaction.response.send_message("Invalid challenge ID / 挑战ID无效！", ephemeral=True)
        if ch["status"] != "waiting":
            return await interaction.response.send_message("Challenge expired or cancelled / 挑战已过期或被取消", ephemeral=True)
        if uid != ch["defender_id"]:
            return await interaction.response.send_message("You are not the defender! / 你不是被挑战者！", ephemeral=True)

        # Check balance again
        def_bal = get_balance(uid)
        if def_bal < ch["bet"]:
            return await interaction.response.send_message(
                f"Insufficient balance! Need {ch['bet']}₲, have {def_bal}₲ / 余额不足！", ephemeral=True)

        chal_bal = get_balance(ch["challenger_id"])
        if chal_bal < ch["bet"]:
            ch["status"] = "expired"
            return await interaction.response.send_message("Challenger has insufficient funds, challenge cancelled / 挑战者余额不足", ephemeral=True)

        ch["status"] = "accepted"

        # Create room
        room_id = challenge_id
        chal_stats = _get_user_stats(ch["challenger_id"])
        def_stats = _get_user_stats(uid)

        room = {
            "room_id": room_id,
            "challenger_id": ch["challenger_id"],
            "challenger_name": ch["challenger_name"],
            "defender_id": uid,
            "defender_name": ch["defender_name"],
            "players": {
                ch["challenger_id"]: {
                    "hp": chal_stats["hp"],
                    "mp": chal_stats["mp"],
                    "max_hp": chal_stats["max_hp"],
                    "max_mp": chal_stats["max_mp"],
                    "atk": chal_stats["attack"],
                    "def": chal_stats["defense"],
                    "buff_atk": 0,
                    "buff_def": 0,
                    "buff_atk_turns": 0,
                    "buff_def_turns": 0,
                    "dot_dmg": 0,
                    "dot_turns": 0,
                    "frozen": False,
                    "username": ch["challenger_name"],
                },
                uid: {
                    "hp": def_stats["hp"],
                    "mp": def_stats["mp"],
                    "max_hp": def_stats["max_hp"],
                    "max_mp": def_stats["max_mp"],
                    "atk": def_stats["attack"],
                    "def": def_stats["defense"],
                    "buff_atk": 0,
                    "buff_def": 0,
                    "buff_atk_turns": 0,
                    "buff_def_turns": 0,
                    "dot_dmg": 0,
                    "dot_turns": 0,
                    "frozen": False,
                    "username": ch["defender_name"],
                },
            },
            "bet": ch["bet"],
            "current_turn": "challenger_id",  # challenger goes first
            "status": "fighting",
            "msg": None,
            "stats": {
                ch["challenger_id"]: {"total_dmg": 0, "skills_used": 0, "healed": 0},
                uid: {"total_dmg": 0, "skills_used": 0, "healed": 0},
            },
        }
        self.pvp_rooms[room_id] = room

        # 🎬 PVP VS + Countdown animation
        await interaction.response.defer()
        await pvp_vs_animation(interaction, ch["challenger_name"], ch["defender_name"], ch["bet"])
        await asyncio.sleep(0.5)

        # Edit to show "battle begins" with the first turn embed
        embed = self._build_pvp_embed(room, "challenger_id", 0)
        await interaction.edit_original_response(
            content=f"⚔️ **{ch['defender_name']}** accepted! / **{ch['challenger_name']}** VS **{ch['defender_name']}** — Fight!",
            embed=embed,
        )

        # Start battle loop
        self.bot.loop.create_task(self._pvp_battle_loop(room_id, interaction.channel))

    # ══════════════════════════════════════════════════════════
    # /gmpt-pvp decline
    # ══════════════════════════════════════════════════════════

    @gmpt_pvp_group.command(
        name="decline",
        description="拒绝PVP挑战 / Decline a PVP challenge"
    )
    @app_commands.describe(challenge_id="挑战ID / Challenge ID")
    async def pvp_decline(self, interaction: discord.Interaction, challenge_id: int):
        uid = str(interaction.user.id)

        ch = self.pvp_challenges.get(challenge_id)
        if not ch:
            return await interaction.response.send_message("Invalid challenge ID / 挑战ID无效！", ephemeral=True)
        if ch["status"] != "waiting":
            return await interaction.response.send_message("Challenge expired or cancelled / 挑战已过期或被取消", ephemeral=True)
        if uid != ch["defender_id"]:
            return await interaction.response.send_message("You are not the defender! / 你不是被挑战者！", ephemeral=True)

        ch["status"] = "declined"
        await interaction.response.send_message(
            f"🏳️ **{ch['defender_name']}** declined the challenge! / 拒绝了挑战！"
        )

    # ══════════════════════════════════════════════════════════
    # Battle Loop
    # ══════════════════════════════════════════════════════════

    async def _pvp_battle_loop(self, room_id: int, channel):
        room = self.pvp_rooms.get(room_id)
        if not room:
            return

        turn_count = 0

        while room["status"] == "fighting":
            turn_count += 1

            # Determine current/opponent player IDs
            current_key = room["current_turn"]  # "challenger_id" or "defender_id"
            opponent_key = "defender_id" if current_key == "challenger_id" else "challenger_id"

            current_id = room[current_key]
            opponent_id = room[opponent_key]

            p_data = room["players"][current_id]
            o_data = room["players"][opponent_id]

            if p_data["hp"] <= 0:
                break

            # Tick dot on opponent before current player acts
            dot_log = ""
            if o_data["dot_dmg"] > 0 and o_data["dot_turns"] > 0:
                dot_log = f"☠️ {o_data['username']} poisoned, {o_data['dot_dmg']} damage! / 受到 {o_data['dot_dmg']} 毒伤！"
                o_data["hp"] = max(0, o_data["hp"] - o_data["dot_dmg"])
                o_data["dot_turns"] -= 1
                if o_data["dot_turns"] <= 0:
                    o_data["dot_dmg"] = 0

            # Check if opponent died from dot
            if o_data["hp"] <= 0:
                break

            # Check frozen on current player
            if p_data["frozen"]:
                p_data["frozen"] = False
                await channel.send(f"❄️ **{p_data['username']}** 被冻结，跳过本回合！/ Frozen! Turn skipped.")
                room["current_turn"] = opponent_key
                continue

            # Build Select options
            options = [
                discord.SelectOption(
                    label="Attack / 普通攻击",
                    value="attack",
                    description="Basic attack / 基础攻击",
                )
            ]

            # Skills
            skills = _get_equipped_skills(current_id)
            for sk in skills:
                disabled = p_data["mp"] < sk["mp_cost"]
                options.append(discord.SelectOption(
                    label=f"{sk['emoji']} {sk['name']} (MP:{sk['mp_cost']})",
                    value=f"skill:{sk['skill_id']}",
                    description=sk.get("description", ""),
                ))

            # Potions
            potions = _get_pvp_potions(current_id)
            for pot in potions:
                options.append(discord.SelectOption(
                    label=f"{pot['item_name']}",
                    value=f"potion:{pot['item_name']}",
                    description=f"x{pot['quantity']} left / 剩余{pot['quantity']}个",
                ))

            options.append(discord.SelectOption(
                label="Surrender / 投降",
                value="surrender",
                description="Forfeit / 认输",
            ))

            # Build embed
            embed = self._build_pvp_embed(room, current_key, turn_count)
            if dot_log:
                embed.description = dot_log

            event = asyncio.Event()
            view = PVPBattleView(room, current_id, event, options)

            if room["msg"]:
                try:
                    await room["msg"].edit(content=None, embed=embed, view=view)
                except (discord.NotFound, discord.HTTPException):
                    room["msg"] = await channel.send(embed=embed, view=view)
            else:
                room["msg"] = await channel.send(embed=embed, view=view)

            # Wait for player action (or timeout)
            try:
                await asyncio.wait_for(event.wait(), timeout=TURN_TIMEOUT)
            except asyncio.TimeoutError:
                result = {"action": "attack"}
                await channel.send(f"⏰ {p_data['username']} timed out, auto attack! / 超时，自动普攻")
            else:
                result = view.result or {"action": "attack"}

            # Disable view on message
            try:
                await room["msg"].edit(view=None)
            except (discord.NotFound, discord.HTTPException):
                pass

            # Process the action
            action = result.get("action", "attack")
            result_msg = self._process_pvp_action(room, current_id, opponent_id, action, result)

            # ⚡ Quick attack animation on the room message
            if action in ("attack", "skill"):
                p_data = room["players"][current_id]
                anim_frames = [
                    f"⚔️ {p_data['username']} attacking...",
                    f"⚔️ {p_data['username']} attacking..",
                    f"⚔️ {p_data['username']} attacking...",
                ]
                if room["msg"]:
                    for frame in anim_frames:
                        anim_embed = discord.Embed(description=f"## {frame}", color=0xFF6600)
                        try:
                            await room["msg"].edit(embed=anim_embed)
                        except (discord.NotFound, discord.HTTPException):
                            pass
                        await asyncio.sleep(0.3)

            await channel.send(result_msg)

            # Check win condition
            if o_data["hp"] <= 0 or action == "surrender":
                room["status"] = "finished"
                break

            # Decrement current player's buff turns
            self._tick_buffs(p_data)

            # Switch turn
            room["current_turn"] = opponent_key

        # Battle ended
        await self._end_pvp_battle(room, channel)

    def _process_pvp_action(
        self, room: dict, current_id: str, opponent_id: str,
        action: str, result: dict,
    ) -> str:
        """Process the selected action and return a result string."""
        p_data = room["players"][current_id]
        o_data = room["players"][opponent_id]
        stats = room["stats"].get(current_id, {"total_dmg": 0, "skills_used": 0, "healed": 0})

        if action == "surrender":
            return f"🏳️ **{p_data['username']}** surrendered! / 投降了！"

        elif action == "attack":
            base_atk = p_data["atk"] + p_data["buff_atk"]
            dmg = base_atk + random.randint(1, 10)
            if random.random() < 0.1:
                dmg = int(dmg * 2)
                crit = "💥 CRIT! / 暴击！"
            else:
                crit = ""
            o_data["hp"] = max(0, o_data["hp"] - dmg)
            stats["total_dmg"] += dmg
            return (
                f"⚔️ **{p_data['username']}** attack / 攻击 {crit}— "
                f"**{dmg}** DMG → {o_data['username']} ({o_data['hp']}/{o_data['max_hp']} HP)"
            )

        elif action == "skill":
            skill_id = result.get("skill_id")
            if not skill_id or skill_id not in SKILLS:
                return "⚠️ Invalid skill, auto basic attack / 技能无效，自动普通攻击"
            skill_def = SKILLS[skill_id]

            # Check MP
            if p_data["mp"] < skill_def["mp_cost"]:
                # Fallback to normal attack
                dmg = p_data["atk"] + random.randint(1, 10)
                o_data["hp"] = max(0, o_data["hp"] - dmg)
                stats["total_dmg"] += dmg
                return f"⚡ Not enough MP! Auto attack — **{dmg}** DMG / MP 不足，自动普攻"

            p_data["mp"] -= skill_def["mp_cost"]
            stats["skills_used"] += 1

            if skill_id == "fireball":
                dmg = 35
                o_data["hp"] = max(0, o_data["hp"] - dmg)
                stats["total_dmg"] += dmg
                return f"🔥 Fireball / 火球术！— {dmg} DMG → {o_data['username']} ({o_data['hp']}/{o_data['max_hp']} HP)"

            elif skill_id == "ice_shard":
                dmg = 25
                o_data["hp"] = max(0, o_data["hp"] - dmg)
                stats["total_dmg"] += dmg
                msg = f"❄️ Ice Shard / 冰锥术！— {dmg} DMG → {o_data['username']} ({o_data['hp']}/{o_data['max_hp']} HP)"
                if random.random() < 0.3:
                    o_data["frozen"] = True
                    msg += " | 🧊 Frozen! Skip next turn / 冻结！跳过下回合"
                return msg

            elif skill_id == "thunder":
                dmg = 50
                o_data["hp"] = max(0, o_data["hp"] - dmg)
                stats["total_dmg"] += dmg
                msg = f"⚡ Thunder Strike / 雷霆一击！— {dmg} DMG → {o_data['username']} ({o_data['hp']}/{o_data['max_hp']} HP)"
                if random.random() < 0.1:
                    self_dmg = int(dmg * 0.3)
                    p_data["hp"] = max(0, p_data["hp"] - self_dmg)
                    msg += f" | ⚡ Backlash! {self_dmg} self-damage / 反噬！自伤 {self_dmg}"
                return msg

            elif skill_id == "heal":
                heal_val = skill_def.get("heal", 40)
                healed = min(heal_val, p_data["max_hp"] - p_data["hp"])
                p_data["hp"] += healed
                stats["healed"] += healed
                return f"💚 Heal / 治愈术！Restored {healed} HP → ({p_data['hp']}/{p_data['max_hp']} HP)"

            elif skill_id == "berserk":
                p_data["buff_atk"] += 20
                p_data["buff_atk_turns"] = 3
                return f"😡 Berserk / 狂暴！ATK +20 for 3 turns / 攻击力+20，持续3回合"

            elif skill_id == "shield":
                p_data["buff_def"] += 15
                p_data["buff_def_turns"] = 3
                return f"🛡️ Shield / 圣盾术！DEF +15 for 3 turns / 防御力+15，持续3回合"

            elif skill_id == "poison":
                o_data["dot_dmg"] = skill_def.get("dot", 10)
                o_data["dot_turns"] = skill_def.get("dot_duration", 3)
                return (
                    f"☠️ Poison / 毒雾！{o_data['username']} poisoned, "
                    f"-{o_data['dot_dmg']} HP/turn for {o_data['dot_turns']} turns / "
                    f"中毒，每回合扣{o_data['dot_dmg']}HP，持续{o_data['dot_turns']}回合"
                )

            elif skill_id == "steal":
                stolen = int(get_balance(opponent_id) * 0.1)
                if stolen > 0:
                    add_coins(opponent_id, -stolen, f"PVP: 被 {p_data['username']} 偷窃")
                    add_coins(current_id, stolen, f"PVP: 偷窃 {o_data['username']}")
                    return f"💰 Steal / 偷窃！Stole {stolen}₲ from {o_data['username']}！/ 从 {o_data['username']} 偷了 {stolen}₲！"
                return f"💰 Steal / 偷窃！{o_data['username']} has empty wallet... / 钱包空空"

            else:
                dmg = skill_def.get("damage", 20)
                o_data["hp"] = max(0, o_data["hp"] - dmg)
                stats["total_dmg"] += dmg
                return f"{skill_def['emoji']} **{skill_def['name']}** — {dmg} DMG / 伤害"

        elif action == "potion":
            potion_name = result.get("potion_name")
            if not potion_name:
                return "⚠️ Invalid potion / 无效药水"

            potion = _consume_potion(current_id, potion_name)
            if not potion:
                return f"背包中没有 **{potion_name}**！/ Not in your bag!"

            effect_type = potion["effect_type"]
            effect_value = potion["effect_value"]
            duration = potion.get("duration", 3)

            if effect_type == "heal_hp":
                healed = min(effect_value, p_data["max_hp"] - p_data["hp"])
                p_data["hp"] += healed
                stats["healed"] += healed
                return f"🧪 {p_data['username']} used **{potion['name_cn']} / {potion['name_en']}** — Restored {healed} HP / 恢复了 {healed} HP"
            elif effect_type == "heal_mp":
                healed = min(effect_value, p_data["max_mp"] - p_data["mp"])
                p_data["mp"] += healed
                return f"🧪 {p_data['username']} used **{potion['name_cn']} / {potion['name_en']}** — Restored {healed} MP / 恢复了 {healed} MP"
            elif effect_type == "buff_atk":
                p_data["buff_atk"] += effect_value
                p_data["buff_atk_turns"] = max(p_data["buff_atk_turns"], duration)
                return f"🧪 {p_data['username']} used **{potion['name_cn']} / {potion['name_en']}** — ATK +{effect_value} for {duration} turns / 攻击力 +{effect_value}，持续 {duration} 回合"
            elif effect_type == "buff_def":
                p_data["buff_def"] += effect_value
                p_data["buff_def_turns"] = max(p_data["buff_def_turns"], duration)
                return f"🧪 {p_data['username']} used **{potion['name_cn']} / {potion['name_en']}** — DEF +{effect_value} for {duration} turns / 防御力 +{effect_value}，持续 {duration} 回合"
            elif effect_type == "buff_spd":
                return f"🧪 {p_data['username']} used **{potion['name_cn']} / {potion['name_en']}** — SPD +{effect_value}% for {duration} turns / 速度 +{effect_value}%，持续 {duration} 回合"
            elif effect_type == "buff_crit":
                return f"🧪 {p_data['username']} used **{potion['name_cn']} / {potion['name_en']}** — Crit +{effect_value}% for {duration} turns / 暴击率 +{effect_value}%，持续 {duration} 回合"
            elif effect_type == "purify":
                return f"🧪 {p_data['username']} used **{potion['name_cn']} / {potion['name_en']}** — All debuffs removed / 所有负面状态已移除"
            elif effect_type == "revive":
                if p_data["hp"] > 0:
                    return f"🧪 {p_data['username']} still alive! Revival ineffective / 还活着，复活药水无效！"
                restore_pct = max(1, int(p_data["max_hp"] * effect_value / 100))
                p_data["hp"] = restore_pct
                p_data["mp"] = p_data["max_mp"]
                return f"✨ {p_data['username']} used **{potion['name_cn']} / {potion['name_en']}** — Revived! HP {p_data['hp']}, MP full / 复活！HP恢复到 {p_data['hp']}，MP全满"

        return "⚠️ Unknown action / 未知操作"

    def _tick_buffs(self, p_data: dict):
        if p_data["buff_atk_turns"] > 0:
            p_data["buff_atk_turns"] -= 1
            if p_data["buff_atk_turns"] <= 0:
                p_data["buff_atk"] = 0
        if p_data["buff_def_turns"] > 0:
            p_data["buff_def_turns"] -= 1
            if p_data["buff_def_turns"] <= 0:
                p_data["buff_def"] = 0

    async def _end_pvp_battle(self, room: dict, channel):
        """Determine winner, distribute rewards, show results."""
        chal_id = room["challenger_id"]
        def_id = room["defender_id"]
        chal_data = room["players"][chal_id]
        def_data = room["players"][def_id]
        bet = room["bet"]

        # Determine winner
        if chal_data["hp"] <= 0 and def_data["hp"] <= 0:
            winner_id = None
            loser_id = None
            result_text = "Draw! / 平局！"
        elif chal_data["hp"] <= 0:
            winner_id = def_id
            loser_id = chal_id
            result_text = f"**{def_data['username']}** wins! / 获胜！"
        else:
            winner_id = chal_id
            loser_id = def_id
            result_text = f"**{chal_data['username']}** wins! / 获胜！"

        # Transfer bet
        if winner_id and loser_id and bet > 0:
            add_coins(winner_id, bet, f"PVP获胜: vs {room['players'][loser_id]['username']}")
            add_coins(loser_id, -bet, f"PVP战败: vs {room['players'][winner_id]['username']}")

        # Build result embed
        embed = discord.Embed(
            title="PVP Battle Over! / PVP 战斗结束！",
            description=result_text,
            color=0xF1C40F if winner_id else 0x95A5A6,
        )

        # Winner prize
        if winner_id and bet > 0:
            embed.add_field(
                name="Prize / 奖金",
                value=f"**{room['players'][winner_id]['username']}** won / 赢得了 **{bet}₲**！",
                inline=False,
            )

        # Battle stats
        stats_text = ""
        for pid, pdata in room["players"].items():
            s = room["stats"].get(pid, {"total_dmg": 0, "skills_used": 0, "healed": 0})
            hp_bar = progress_bar(pdata["hp"], pdata["max_hp"], 10)
            stats_text += (
                f"**{pdata['username']}**\n"
                f"❤️ HP: {hp_bar}\n"
                f"🗡️ DMG: {s['total_dmg']} | ⚡ Skills: {s['skills_used']} | 💚 Heal: {s['healed']}\n\n"
            )
        embed.add_field(name="Battle Stats / 战斗统计", value=stats_text, inline=False)
        embed.set_footer(text=f"Bet / 赌注: {bet}₲ | PVP Arena / PVP 竞技场")

        try:
            await room["msg"].edit(embed=embed, view=None)
        except (discord.NotFound, discord.HTTPException):
            await channel.send(embed=embed)

        # Save HP/MP
        for pid, pdata in room["players"].items():
            _save_pvp_stats(pid, pdata)

    # ══════════════════════════════════════════════════════════
    # Embed Builder
    # ══════════════════════════════════════════════════════════

    def _build_pvp_embed(self, room: dict, current_key: str, turn_count: int) -> discord.Embed:
        chal_id = room["challenger_id"]
        def_id = room["defender_id"]
        chal_data = room["players"][chal_id]
        def_data = room["players"][def_id]

        embed = discord.Embed(
            title="PVP Arena / PVP 竞技场",
            color=0xE74C3C,
        )

        # Who's turn
        current_id = room[current_key]
        current_name = room["players"][current_id]["username"]
        embed.description = f"⏳ {current_name} 的回合 / Turn #{turn_count} | 💰 Bet / 赌注 {room['bet']}₲"

        for pid, pdata in [(chal_id, chal_data), (def_id, def_data)]:
            hp_bar = progress_bar(pdata["hp"], pdata["max_hp"])
            mp_bar = progress_bar(pdata["mp"], pdata["max_mp"], 6)

            buffs = []
            if pdata["buff_atk"] > 0:
                buffs.append(f"ATK+{pdata['buff_atk']}")
            if pdata["buff_def"] > 0:
                buffs.append(f"DEF+{pdata['buff_def']}")
            if pdata["frozen"]:
                buffs.append("Frozen/冻结")
            if pdata["dot_dmg"] > 0:
                buffs.append(f"Poison/毒({pdata['dot_turns']}T)")
            buff_str = f" [{', '.join(buffs)}]" if buffs else ""

            value = (
                f"❤️ HP: {hp_bar}\n"
                f"💙 MP: {mp_bar}\n"
                f"🗡️ ATK: {pdata['atk']} | 🛡️ DEF: {pdata['def']}{buff_str}"
            )

            turn_marker = "⚡ " if pid == current_id else ""
            embed.add_field(
                name=f"{turn_marker}{pdata['username']}",
                value=value,
                inline=True,
            )

        return embed


# ══════════════════════════════════════════════════════════════
# PVP Lobby View — Interactive PVP hub
# ══════════════════════════════════════════════════════════════
class PVPLobbyView(discord.ui.View):
    """PVP大厅面板 / PVP lobby panel."""

    def __init__(self, user_id: str, main_view=None):
        super().__init__(timeout=300)
        self.uid = user_id
        self.main_view = main_view
        self._build()

    def build_main_embed(self):
        bal = get_balance(self.uid)
        embed = discord.Embed(
            title="🏆 PVP Arena / PVP 对战",
            description=(
                "挑战其他玩家，赢取荣誉与金币！\n"
                "Challenge other players, earn glory and coins!\n\n"
                f"🪙 你的余额 / Your balance: **{bal:,}**"
            ),
            color=0xE74C3C,
        )
        embed.add_field(
            name="⚔️ 挑战玩家 / Challenge",
            value="在聊天中使用 `/gmpt-pvp challenge @玩家 <赌注>` 发起挑战\nUse `/gmpt-pvp challenge @player <bet>` in chat",
            inline=False,
        )
        embed.add_field(
            name="📋 活跃挑战 / Active Challenges",
            value="查看是否有等待接受的挑战 / Check for pending challenges",
            inline=False,
        )
        embed.set_footer(text="PVP 消耗技能和药水，请做好准备！")
        return embed

    def _build(self):
        self.clear_items()
        challenge_btn = discord.ui.Button(
            label="⚔️ Challenge / 挑战", style=discord.ButtonStyle.primary,
            row=0, custom_id="pvp_challenge",
        )
        challenge_btn.callback = self._challenge_info_callback
        self.add_item(challenge_btn)

        if self.main_view:
            back_btn = discord.ui.Button(
                label="Back to MMORPG / 返回", style=discord.ButtonStyle.danger,
                row=1, emoji="🏠", custom_id="pvp_back",
            )
            back_btn.callback = self._back_callback
            self.add_item(back_btn)

    async def _challenge_info_callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "⚔️ **发起挑战 / Challenge:**\n"
            "在聊天中 `@` 你要挑战的玩家：`/gmpt-pvp challenge @player <赌注>`\n"
            "对方会用按钮接受或拒绝 / Opponent accepts/declines via buttons",
            ephemeral=True,
        )

    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            from cogs.mmorpg_shop import _get_user_stats
            uid = str(self.uid)
            stats = _get_user_stats(uid)
            bal = get_balance(uid)
            embed = discord.Embed(
                title="MMORPG Main Panel / MMORPG 主面板",
                description=(
                    f"❤️ HP: **{stats['hp']}/{stats['max_hp']}**  "
                    f"🔮 MP: **{stats['mp']}/{stats['max_mp']}**\n"
                    f"⚔️ ATK: **{stats['attack']}**  🛡️ DEF: **{stats['defense']}**  "
                    f"⭐ Lv.**{stats['level']}**  🪙 **{bal:,}**\n\n"
                    f"Click a button below / 点击下方按钮："
                ),
                color=0x9B59B6,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)


async def setup(bot):
    await bot.add_cog(PVPCog(bot))
