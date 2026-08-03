"""
GMPT Bot — MMORPG Boss 多人团战系统 / Multiplayer Boss Raid (Button-Driven)
/gmpt-boss lobby — 打开Boss大厅面板 / Open Boss lobby panel
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
from utils.animations import progress_bar, battle_animation, boss_entrance_animation
from cogs.economy import get_balance, add_coins
from cogs.mmorpg_skills import SKILLS
from cogs.mmorpg_shop import POTION_CATALOG
from config import (
    ELEMENTS, ELEMENT_STRONG, ELEMENT_ADVANTAGE_MULTIPLIER,
    ELEMENT_GEAR_BONUS, CLASS_ELEMENT,
    BOSS_SPAWN_CHANNEL_ID, BOSS_SPAWN_INTERVAL,
    BOSS_SPAWN_DIFFICULTY_WEIGHTS, BOSS_AUTO_TIMEOUT, BOSS_NAME_POOL,
)
from cogs.mmorpg_worldboss import WorldBossView
import logging

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Module‑level room storage — shared across all Bot instances
# ══════════════════════════════════════════════════════════════
_boss_rooms: dict[str, dict] = {}
_boss_rooms_lock = asyncio.Lock()

# ══════════════════════════════════════════════════════════════
# Boss / Dungeon definitions
# ══════════════════════════════════════════════════════════════

BOSS_TYPES = {
    "金龙": {
        "name": "金龙",
        "emoji": "\U0001f409",
        "desc": "Gold Dragon — 喷吐金色火焰！",
        "base_hp": (600, 1000),
        "base_atk": (25, 55),
        "skills": ["龙息", "龙尾扫", "金币雨"],
        "rage_skill": "\U0001f525 龙神之怒！伤害×2",
        "loot_table": [
            (0.15, "龙鳞碎片", 300), (0.10, "金龙宝珠", 800),
            (0.05, "龙牙项链", 2000), (0.02, "金龙坐骑碎片", 5000),
        ],
        "cooldown_min": {"简单": 5, "普通": 15, "困难": 30},
    },
    "暗影领主": {
        "name": "暗影领主",
        "emoji": "\U0001f479",
        "desc": "Shadow Lord — 暗影之力笼罩战场！",
        "base_hp": (600, 1000),
        "base_atk": (25, 55),
        "skills": ["暗影斩", "黑洞", "恐惧凝视"],
        "rage_skill": "\U0001f311 无尽暗影！全体伤害",
        "loot_table": [
            (0.15, "暗影碎片", 350), (0.10, "暗影之心", 900),
            (0.05, "暗影披风", 2200), (0.02, "暗影王冠", 5500),
        ],
        "cooldown_min": {"简单": 5, "普通": 15, "困难": 30},
    },
    "冰霜巨人": {
        "name": "冰霜巨人",
        "emoji": "\U0001f9ca",
        "desc": "Frost Giant — 冻结一切！",
        "base_hp": (600, 1000),
        "base_atk": (25, 55),
        "skills": ["冰锥", "暴风雪", "永冻"],
        "rage_skill": "\u2744\ufe0f 绝对零度！攻击附带冰冻",
        "loot_table": [
            (0.15, "冰晶碎片", 400), (0.10, "冰霜核心", 1000),
            (0.05, "冰封之盾", 2500), (0.02, "永冻王冠", 6000),
        ],
        "cooldown_min": {"简单": 5, "普通": 15, "困难": 30},
    },
    "地狱犬": {
        "name": "地狱犬",
        "emoji": "\U0001f525",
        "desc": "Hellhound — 三头地狱犬喷吐烈焰！",
        "base_hp": (600, 1000),
        "base_atk": (25, 55),
        "skills": ["三重撕咬", "地狱火", "咆哮"],
        "rage_skill": "\U0001f4a5 地狱烈焰！全体灼烧",
        "loot_table": [
            (0.15, "地狱火碎片", 450), (0.10, "地狱核心", 1100),
            (0.05, "地狱护符", 2800), (0.02, "三头犬缰绳", 7000),
        ],
        "cooldown_min": {"简单": 5, "普通": 15, "困难": 30},
    },
}

DIFFICULTY = {
    "简单": {"label": "Easy / 简单", "hp_mult": 1.0, "atk_mult": 0.7, "reward_mult": 0.5, "color": 0x2ECC71, "stars": "\u2b50"},
    "普通": {"label": "Normal / 普通", "hp_mult": 2.0, "atk_mult": 1.0, "reward_mult": 1.0, "color": 0xF39C12, "stars": "\u2b50\u2b50"},
    "困难": {"label": "Hard / 困难", "hp_mult": 4.0, "atk_mult": 1.5, "reward_mult": 2.0, "color": 0xE74C3C, "stars": "\u2b50\u2b50\u2b50"},
    "\u6781\u9650": {"label": "Extreme / \u6781\u9650", "hp_mult": 7.0, "atk_mult": 2.2, "reward_mult": 4.0, "color": 0x8E44AD, "stars": "\U0001f480\U0001f480\U0001f480\U0001f480"},
}

RAGE_HP_RATIO = 0.5

DIFFICULTY_LOOT = {
    "简单": {
        "label": "Easy", "gold_mult": 1.0,
        "tiers": ["T1"],
        "pools": {
            "T1": [("铁剑", "Iron Sword"), ("皮甲", "Leather Armor"),
                   ("木盾", "Wooden Shield"), ("布帽", "Cloth Hat"),
                   ("旅行靴", "Traveling Boots"), ("铜戒指", "Copper Ring")],
            "consumable": [("生命药水 Small HP Potion", "heal_hp", 30),
                           ("魔法药水 Small MP Potion", "heal_mp", 20)],
        },
        "rare_chance": 0.0, "legendary_chance": 0.0,
    },
    "普通": {
        "label": "Medium", "gold_mult": 1.5,
        "tiers": ["T1", "T2"],
        "pools": {
            "T1": [("铁剑", "Iron Sword"), ("皮甲", "Leather Armor"),
                   ("木盾", "Wooden Shield"), ("布帽", "Cloth Hat"),
                   ("旅行靴", "Traveling Boots"), ("铜戒指", "Copper Ring")],
            "T2": [("钢剑", "Steel Sword"), ("锁子甲", "Chainmail"),
                   ("精钢盾", "Reinforced Shield"), ("法师帽", "Mage Hat"),
                   ("银戒指", "Silver Ring")],
            "consumable": [("中级生命药水 Medium HP Potion", "heal_hp", 60),
                           ("中级魔法药水 Medium MP Potion", "heal_mp", 40)],
        },
        "rare_chance": 0.10, "legendary_chance": 0.0,
    },
    "困难": {
        "label": "Hard", "gold_mult": 2.5,
        "tiers": ["T2", "T3"],
        "pools": {
            "T2": [("钢剑", "Steel Sword"), ("锁子甲", "Chainmail"),
                   ("精钢盾", "Reinforced Shield"), ("法师帽", "Mage Hat"),
                   ("银戒指", "Silver Ring"), ("战士腰带", "Warrior Belt")],
            "T3": [("秘银剑", "Mithril Sword"), ("龙鳞甲", "Dragonscale Armor"),
                   ("龙纹盾", "Dragoncrest Shield"), ("贤者之帽", "Sage Hat"),
                   ("金戒指", "Gold Ring"), ("龙牙项链", "Dragon Fang Necklace")],
            "consumable": [("高级生命药水 Large HP Potion", "heal_hp", 120),
                           ("高级魔法药水 Large MP Potion", "heal_mp", 80),
                           ("力量药水 Strength Potion", "buff_atk", 15),
                           ("防御药水 Defense Potion", "buff_def", 15)],
        },
        "rare_chance": 0.20, "legendary_chance": 0.0,
    },
    "极限": {
        "label": "Extreme", "gold_mult": 5.0,
        "tiers": ["T3"],
        "pools": {
            "T3": [("秘银剑", "Mithril Sword"), ("龙鳞甲", "Dragonscale Armor"),
                   ("龙纹盾", "Dragoncrest Shield"), ("贤者之帽", "Sage Hat"),
                   ("金戒指", "Gold Ring"), ("龙牙项链", "Dragon Fang Necklace"),
                   ("凤凰披风", "Phoenix Cloak")],
            "consumable": [("终极生命药水 Elixir of Life", "heal_hp", 250),
                           ("终极魔法药水 Elixir of Mana", "heal_mp", 150),
                           ("力量药水 Strength Potion", "buff_atk", 15),
                           ("防御药水 Defense Potion", "buff_def", 15),
                           ("暴击药水 Crit Potion", "buff_crit", 20),
                           ("速度药水 Speed Potion", "buff_spd", 20)],
        },
        "rare_chance": 0.30, "legendary_chance": 0.05,
    },
}

LEGENDARY_POOL = [
    ("龙神之翼", "Dragon God Wings", 0xF1C40F),
    ("暗影王冠", "Shadow Crown", 0x9B59B6),
    ("霜冻之魂", "Frost Soul", 0x3498DB),
    ("三头犬之牙", "Cerberus Fang", 0xE74C3C),
    ("圣光之剑", "Holy Sword", 0xFFD700),
]


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _get_user_combat_stats(uid: str) -> dict:
    """Read user combat stats from DB."""
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


def _save_combat_stats(uid: str, stats: dict):
    """Persist HP/MP back to DB."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET hp = ?, mp = ? WHERE discord_id = ?",
            (stats["hp"], stats["mp"], uid),
        )
        conn.commit()


def _get_equipped_skills(uid: str) -> list[dict]:
    """Get player's equipped skills."""
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


def _get_potions(uid: str) -> list[dict]:
    """Get player's potions from inventory."""
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
            "SELECT quantity FROM user_inventory WHERE user_id = ? AND item_name = ? AND item_type = 'potion'",
            (uid, potion_name),
        )
        inv_row = cur.fetchone()
    if not inv_row or inv_row["quantity"] <= 0:
        return None
    if inv_row["quantity"] > 1:
        with get_db_ctx() as conn:
            conn.cursor().execute(
                "UPDATE user_inventory SET quantity = quantity - 1 WHERE user_id = ? AND item_name = ? AND item_type = 'potion'",
                (uid, potion_name),
            )
            conn.commit()
    else:
        with get_db_ctx() as conn:
            conn.cursor().execute(
                "DELETE FROM user_inventory WHERE user_id = ? AND item_name = ? AND item_type = 'potion'",
                (uid, potion_name),
            )
            conn.commit()
    return POTION_CATALOG.get(potion_name)


def _format_bar(current: int, maximum: int, length: int = 10, filled: str = "\u2588", empty: str = "\u2591") -> str:
    ratio = max(0, min(1, current / max(1, maximum)))
    f = int(ratio * length)
    e = length - f
    return filled * f + empty * e + f" {current}/{maximum}"


# ══════════════════════════════════════════════════════════════
# Create Boss Modal
# ══════════════════════════════════════════════════════════════

class CreateBossModal(discord.ui.Modal, title="Create Boss Room / 创建Boss房间"):
    """Modal for creating a new boss room."""

    boss_name = discord.ui.TextInput(
        label="Boss Name / Boss名称",
        placeholder="金龙 / 暗影领主 / 冰霜巨人 / 地狱犬",
        required=True,
        max_length=32,
    )
    boss_hp = discord.ui.TextInput(
        label="Boss HP (blank = random) / Boss血量（留空=随机）",
        placeholder="800",
        required=False,
        max_length=10,
    )
    difficulty_input = discord.ui.TextInput(
        label="Difficulty / 难度",
        placeholder="简单 / 普通 / 困难",
        required=False,
        default="普通",
        max_length=10,
    )

    def __init__(self, cog, channel_id: str, user_id: str, username: str, lobby_msg):
        super().__init__()
        self.cog = cog
        self.channel_id = channel_id
        self.user_id = user_id
        self.username = username
        self.lobby_msg = lobby_msg

    async def on_submit(self, interaction: discord.Interaction):
        boss_name_raw = self.boss_name.value.strip()
        hp_raw = self.boss_hp.value.strip()
        diff_raw = self.difficulty_input.value.strip()

        # Validate / resolve boss type
        if boss_name_raw in BOSS_TYPES:
            boss_type = boss_name_raw
        else:
            # Try fuzzy match
            matched = None
            for key in BOSS_TYPES:
                if boss_name_raw in key or key in boss_name_raw:
                    matched = key
                    break
            if matched:
                boss_type = matched
            else:
                types_str = " / ".join(BOSS_TYPES.keys())
                await interaction.response.send_message(
                    f"Invalid Boss! Options / 无效Boss！可选: {types_str}", ephemeral=True)
                return

        # Validate difficulty
        if diff_raw not in DIFFICULTY:
            diffs = " / ".join(DIFFICULTY.keys())
            await interaction.response.send_message(
                f"Invalid Difficulty! Options / 无效难度！可选: {diffs}", ephemeral=True)
            return

        # Check channel room
        for rid, room in _boss_rooms.items():
            if room.get("channel_id") == self.channel_id and room.get("status") in ("waiting", "fighting"):
                await interaction.response.send_message(
                    "本频道已有进行中的 Boss 战！/ Boss battle already in progress!", ephemeral=True)
                return

        # Check cooldown
        cd = self.cog._get_cooldown_remaining(self.user_id, boss_type, diff_raw)
        if cd > 0:
            m, s = divmod(cd, 60)
            await interaction.response.send_message(
                f"\u23f3 冷却中！{m}分{s}秒后可挑战", ephemeral=True)
            return

        boss = BOSS_TYPES[boss_type]
        diff = DIFFICULTY[diff_raw]

        if hp_raw:
            try:
                max_hp = int(hp_raw)
                if max_hp < 50:
                    max_hp = 50
                if max_hp > 100000:
                    max_hp = 100000
            except ValueError:
                max_hp = int(random.randint(*boss["base_hp"]) * diff["hp_mult"])
        else:
            max_hp = int(random.randint(*boss["base_hp"]) * diff["hp_mult"])

        atk = int(random.randint(*boss["base_atk"]) * diff["atk_mult"])

        stats = _get_user_combat_stats(self.user_id)

        room_id = f"{self.channel_id}_{int(time.time())}"

        room = {
            "room_id": room_id,
            "channel_id": self.channel_id,
            "host_id": self.user_id,
            "boss": boss,
            "boss_hp": max_hp,
            "boss_max_hp": max_hp,
            "boss_atk": atk,
            "phase": 1,
            "difficulty": diff_raw,
            "diff_label": diff["label"],
            "diff_color": diff["color"],
            "reward_mult": diff["reward_mult"],
            "status": "waiting",
            "turn": 0,
            "start_time": time.time(),
            "players": {},
            "loot_log": [],
            "battle_msg": None,
        }

        room["players"][self.user_id] = {
            "hp": stats["hp"],
            "mp": stats["mp"],
            "max_hp": stats["max_hp"],
            "max_mp": stats["max_mp"],
            "atk": stats["attack"],
            "def": stats["defense"],
            "damage_dealt": 0,
            "buff_atk": 0,
            "buff_def": 0,
            "buff_atk_turns": 0,
            "buff_def_turns": 0,
            "dot_dmg": 0,
            "dot_turns": 0,
            "frozen": False,
            "burn": False,
            "burn_turns": 0,
            "stunned": False,
            "username": self.username,
        }

        _boss_rooms[room_id] = room

        # Update lobby embed
        embed = self.cog._build_room_embed(room)
        await interaction.response.edit_message(
            content=f"{boss['emoji']} **{self.username}** created a Boss raid / 创建了 Boss 团战房间！\n"
                    f"Click **Join** to join / 点击 **Join** 加入 | "
                    f"Host can click **Invite** to invite / 队长可点击 **Invite** 邀请",
            embed=embed,
            view=BossLobbyView(self.user_id, self.cog, room, self.lobby_msg),
        )


# ══════════════════════════════════════════════════════════════
# Boss Battle View — Select-driven
# ══════════════════════════════════════════════════════════════

class BossBattleView(discord.ui.View):
    """Select-driven Boss battle view. Any alive player can pick an action."""

    def __init__(self, cog, room: dict, lobby_msg):
        super().__init__(timeout=600)
        self.cog = cog
        self.room = room
        self.lobby_msg = lobby_msg
        self._lock = asyncio.Lock()
        self._build_select()

    def _build_select(self):
        self.clear_items()
        options = [
            discord.SelectOption(
                label="Attack / 普通攻击",
                value="attack",
                emoji="\u2694\ufe0f",
                description="Basic physical attack / 基础物理攻击",
            ),
            discord.SelectOption(
                label="Flee / 逃跑",
                value="flee",
                emoji="\U0001f3c3",
                description="Run away from battle / 逃离战斗",
            ),
        ]

        # Add skill options (generic — validated per-player in callback)
        skill_ids = set()
        for pid in self.room["players"]:
            for sk in _get_equipped_skills(pid):
                sid = sk["skill_id"]
                if sid not in skill_ids:
                    skill_ids.add(sid)
                    options.append(discord.SelectOption(
                        label=f"{sk['emoji']} {sk['name']} (MP:{sk['mp_cost']})",
                        value=f"skill:{sid}",
                        description=sk.get("description", "")[:100],
                    ))

        # Add potion options (generic — validated per-player in callback)
        potion_keys = set()
        for pid in self.room["players"]:
            for pot in _get_potions(pid):
                pk = pot["item_name"]
                if pk not in potion_keys:
                    potion_keys.add(pk)
                    pcat = POTION_CATALOG.get(pk)
                    if pcat:
                        options.append(discord.SelectOption(
                            label=f"{pcat['emoji']} {pcat['name_cn']} / {pcat['name_en']}",
                            value=f"potion:{pk}",
                            description=f"x{pot['quantity']} — {pcat.get('effect_type', '')}",
                        ))

        select = discord.ui.Select(
            placeholder="\u2694\ufe0f Choose your action / 选择行动...",
            options=options[:25],
            row=0,
        )
        select.callback = self._on_action_select
        self.add_item(select)

    async def _on_action_select(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        # Check if player is in room and alive
        if uid not in self.room["players"]:
            await interaction.response.send_message(
                "You are not in this battle! / 你不在战斗中！", ephemeral=True)
            return

        player = self.room["players"][uid]
        if player["hp"] <= 0:
            await interaction.response.send_message(
                "You are dead! / 你已阵亡！", ephemeral=True)
            return

        if self.room["status"] != "fighting":
            await interaction.response.send_message(
                "Battle not started or already finished! / 战斗未开始或已结束！", ephemeral=True)
            return

        value = interaction.data["values"][0]

        # Use lock to prevent concurrent state modifications
        async with self._lock:
            # Re-check state after acquiring lock
            if not self.room or "room_id" not in self.room:
                await interaction.response.send_message("Room data missing.", ephemeral=True)
                return
            room = _boss_rooms.get(self.room["room_id"])
            if not room or room["status"] != "fighting":
                try:
                    await interaction.response.defer()
                except Exception:
                    logger.exception("Boss select: defer failed")
                    pass
                return

            pdata = room["players"].get(uid)
            if not pdata or pdata["hp"] <= 0:
                await interaction.response.send_message(
                    "You are dead! / 你已阵亡！", ephemeral=True)
                return

            await interaction.response.defer()

            result_lines = []

            # ── Check stunned ──
            if pdata.get("stunned"):
                pdata["stunned"] = False
                result_lines.append(f"💫 **{pdata['username']}** 被眩晕，跳过本回合！/ Stunned! Turn skipped.")
            # ── Check frozen ──
            elif pdata["frozen"]:
                pdata["frozen"] = False
                result_lines.append(f"❄️ **{pdata['username']}** 被冻结，跳过本回合！/ Frozen! Turn skipped.")
            
            else:
                # ── Tick player's dot on boss ──
                dot_log = ""
                if pdata["dot_dmg"] > 0 and pdata["dot_turns"] > 0:
                    dot_log = f"\u2620\ufe0f Boss受到 {pdata['dot_dmg']} 毒伤！"
                    room["boss_hp"] = max(0, room["boss_hp"] - pdata["dot_dmg"])
                    pdata["dot_turns"] -= 1
                    if pdata["dot_turns"] <= 0:
                        pdata["dot_dmg"] = 0

                # ── Phase check ──
                phase_announced = False
                if room["boss_hp"] <= room["boss_max_hp"] * RAGE_HP_RATIO and room["phase"] == 1:
                    room["phase"] = 2
                    room["boss_atk"] = int(room["boss_atk"] * 1.5)
                    phase_announced = True
                    result_lines.append(
                        f"\U0001f525 **Phase 2!** Boss gets stronger! (ATK x1.5) / Boss 进入暴怒阶段！（攻击力 x1.5）"
                    )

                if dot_log:
                    result_lines.append(dot_log)

                # ── Apply burn ATK debuff ──
                if pdata.get("burn"):
                    burn_penalty = int(pdata["atk"] * 0.10)
                    pdata["_orig_atk"] = pdata["atk"]
                    pdata["atk"] = max(1, pdata["atk"] - burn_penalty)
                # ── Process action ──
                action_log = self._process_action(room, uid, value)
                # Restore ATK after burn penalty
                if pdata.get("_orig_atk"):
                    pdata["atk"] = pdata.pop("_orig_atk")
                result_lines.append(action_log)

                # ── Decrement buff turns ──
                self._tick_buffs(pdata)

                # ── Boss counter-attack (single target) ──
                if room["boss_hp"] > 0:
                    boss_log = self._boss_counter(room, uid)
                    result_lines.append(boss_log)

                room["turn"] += 1

            # ── Check boss death ──
            if room["boss_hp"] <= 0:
                room["status"] = "finished"
                duration_sec = time.time() - room["start_time"]
                result_lines.append("")
                result_lines.append(
                    f"**{room['boss']['name']}** defeated! / 被击败！({duration_sec:.0f}s)"
                )
                reward_lines = self.cog._distribute_rewards(room, duration_sec)
                result_lines.append("\n**Rewards / 奖励分配:**")
                result_lines.extend(reward_lines)

            # ── Build result embed ──
            desc = "\n".join(result_lines)
            desc += f"\n\nBoss HP: {_format_bar(room['boss_hp'], room['boss_max_hp'])}"
            if room["phase"] == 2:
                desc += f"\nPhase: **Phase 2** | Turn: {room['turn']}"

            result_embed = discord.Embed(
                description=desc,
                color=room["diff_color"],
            )
            result_embed.set_footer(text=f"Turn / 回合: {room['turn']} | Status: {room['status']}")

            # Update the battle message
            self._build_select()  # Refresh Select options after state changes
            target_msg = self.lobby_msg or interaction.message
            try:
                if target_msg:
                    await target_msg.edit(content=None, embed=result_embed, view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

            # ── End battle cleanup ──
            if room["status"] == "finished":
                # Save stats
                for pid, pdata in room["players"].items():
                    _save_combat_stats(pid, pdata)
                # Clean up
                rid = room.get("room_id")
                if rid and rid in _boss_rooms:
                    del _boss_rooms[rid]
                # Disable view
                for child in self.children:
                    child.disabled = True
                try:
                    if target_msg:
                        await target_msg.edit(view=self)
                except Exception:
                    logger.exception("Boss: edit target_msg failed")
                    pass

    def _get_player_element(self, uid: str):
        """Get player element from DB."""
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT element FROM users WHERE discord_id = ?", (uid,))
            row = cur.fetchone()
        if row and row[0]:
            return row[0]
        return None

    def _calc_element_multiplier(self, attacker_element, defender_element) -> float:
        """Calculate element advantage multiplier: 1.30 if attacker > defender, else 1.0."""
        if not attacker_element or not defender_element:
            return 1.0
        if attacker_element not in ELEMENTS or defender_element not in ELEMENTS:
            return 1.0
        if ELEMENT_STRONG.get(attacker_element) == defender_element:
            return ELEMENT_ADVANTAGE_MULTIPLIER
        return 1.0

    def _try_apply_status_effects(self, pdata: dict, is_crit: bool, room: dict) -> str:
        """On CRIT hit, 30% chance to attach a random status effect to the player."""
        if not is_crit or random.random() >= 0.30:
            return ""
        statuses = ["poison", "burn", "freeze", "stun"]
        effect = random.choice(statuses)
        if effect == "poison":
            pdata["dot_dmg"] = max(1, int(pdata["max_hp"] * 0.05))
            pdata["dot_turns"] = 3
            return " | \u2620\ufe0f \u4e2d\u6bd2\uff01\u6bcf\u56de\u5408\u6263HP \u6301\u7eed3\u56de\u5408"
        elif effect == "burn":
            pdata["burn"] = True
            pdata["burn_turns"] = 3
            return " | \U0001f525 \u707c\u70e7\uff01\u6bcf\u56de\u54083%HP+\u964d10%ATK \u6301\u7eed3\u56de\u5408"
        elif effect == "freeze":
            pdata["frozen"] = True
            return " | \u2744\ufe0f \u51bb\u7ed3\uff01\u8df3\u8fc7\u4e0b\u56de\u5408"
        else:  # stun
            pdata["stunned"] = True
            return " | \U0001f4ab \u7729\u6655\uff01\u8df3\u8fc7\u4e0b\u56de\u5408"

    def _process_action(self, room: dict, uid: str, value: str) -> str:
        """Process the selected action and return a log line."""
        pdata = room["players"][uid]
        name = pdata["username"]
        boss_element = room.get("boss_element") or room["boss"].get("element")
        player_element = self._get_player_element(uid)
        elem_mult = self._calc_element_multiplier(player_element, boss_element)

        if value == "attack":
            base_atk = pdata["atk"] + pdata["buff_atk"]
            dmg = base_atk + random.randint(1, 10)
            crit = random.random() < 0.1
            if crit:
                dmg = int(dmg * 2)
            dmg = int(dmg * elem_mult)
            line = f"\u2694\ufe0f **{name}**"
            if elem_mult > 1.0:
                line += " \U0001f9ea\u5143\u7d20\u514b\u5236!"
            if crit:
                line += f" \U0001f4a5 \u66b4\u51fb\uff01\u2014 **{dmg}** \u4f24\u5bb3"
            else:
                line += f" \u666e\u901a\u653b\u51fb \u2014 {dmg} \u4f24\u5bb3"
            room["boss_hp"] = max(0, room["boss_hp"] - dmg)
            pdata["damage_dealt"] += dmg
            status_extra = self._try_apply_status_effects(pdata, crit, room)
            if status_extra:
                line += status_extra
            return line

        elif value == "flee":
            pdata["hp"] = 0  # Mark as dead/fled
            return f"\U0001f3c3 **{name}** fled from battle! / \u9003\u79bb\u4e86\u6218\u6597\uff01"

        elif value.startswith("skill:"):
            skill_id = value.split(":", 1)[1]
            if skill_id not in SKILLS:
                return f"\u26a0\ufe0f Unknown skill / \u672a\u77e5\u6280\u80fd"

            # Check if player has this skill equipped
            equipped = _get_equipped_skills(uid)
            equipped_ids = [s["skill_id"] for s in equipped]
            if skill_id not in equipped_ids:
                return f"\u26a0\ufe0f **{name}** doesn\'t have this skill! / \u672a\u88c5\u5907\u6b64\u6280\u80fd\uff01"

            skill_def = SKILLS[skill_id]
            if pdata["mp"] < skill_def["mp_cost"]:
                # Not enough MP \u2014 auto basic attack
                dmg = pdata["atk"] + random.randint(1, 10)
                room["boss_hp"] = max(0, room["boss_hp"] - dmg)
                pdata["damage_dealt"] += dmg
                return f"\u26a1 Not enough MP! Auto attack \u2014 **{dmg}** DMG / MP \u4e0d\u8db3\uff0c\u81ea\u52a8\u666e\u653b"

            pdata["mp"] -= skill_def["mp_cost"]

            if skill_id == "fireball":
                dmg = int(35 * elem_mult)
                room["boss_hp"] = max(0, room["boss_hp"] - dmg)
                pdata["damage_dealt"] += dmg
                elem_tag = " \U0001f9ea\u5143\u7d20\u514b\u5236!" if elem_mult > 1.0 else ""
                return f"\U0001f525 **\u706b\u7403\u672f\uff01** \u2014 {dmg} \u4f24\u5bb3{elem_tag}"

            elif skill_id == "ice_shard":
                dmg = int(25 * elem_mult)
                room["boss_hp"] = max(0, room["boss_hp"] - dmg)
                pdata["damage_dealt"] += dmg
                elem_tag = " \U0001f9ea\u5143\u7d20\u514b\u5236!" if elem_mult > 1.0 else ""
                return f"\u2744\ufe0f **\u51b0\u9525\u672f\uff01** \u2014 {dmg} \u4f24\u5bb3{elem_tag}"

            elif skill_id == "thunder":
                dmg = int(50 * elem_mult)
                room["boss_hp"] = max(0, room["boss_hp"] - dmg)
                pdata["damage_dealt"] += dmg
                elem_tag = " \U0001f9ea\u5143\u7d20\u514b\u5236!" if elem_mult > 1.0 else ""
                msg = f"\u26a1 **\u96f7\u9706\u4e00\u51fb\uff01** \u2014 {dmg} \u4f24\u5bb3{elem_tag}"
                if random.random() < 0.1:
                    self_dmg = int(dmg * 0.3)
                    pdata["hp"] = max(0, pdata["hp"] - self_dmg)
                    msg += f" | \u26a1 \u53cd\u566c\uff01\u81ea\u5df1\u53d7\u5230 {self_dmg} \u4f24\u5bb3"
                return msg

            elif skill_id == "heal":
                heal_val = skill_def.get("heal", 40)
                healed = min(heal_val, pdata["max_hp"] - pdata["hp"])
                pdata["hp"] += healed
                if pdata.get("burn"):
                    pdata["burn"] = False
                    pdata["burn_turns"] = 0
                return f"\U0001f49a **\u6cbb\u6108\u672f\uff01** \u6062\u590d\u4e86 {healed} HP\uff08{pdata['hp']}/{pdata['max_hp']}\uff09\U0001f525\u707c\u70e7\u5df2\u6e05\u9664"

            elif skill_id == "berserk":
                pdata["buff_atk"] += 20
                pdata["buff_atk_turns"] = 3
                return f"\U0001f621 **\u72c2\u66b4\uff01** \u653b\u51fb\u529b +20\uff0c\u6301\u7eed 3 \u56de\u5408"

            elif skill_id == "shield":
                pdata["buff_def"] += 15
                pdata["buff_def_turns"] = 3
                return f"\U0001f6e1\ufe0f **\u5723\u76fe\u672f\uff01** \u9632\u5fa1\u529b +15\uff0c\u6301\u7eed 3 \u56de\u5408"

            elif skill_id == "poison":
                dot_val = skill_def.get("dot", 10)
                dot_dur = skill_def.get("dot_duration", 3)
                pdata["dot_dmg"] = dot_val
                pdata["dot_turns"] = dot_dur
                return f"\u2620\ufe0f **\u6bd2\u96fe\uff01** Boss \u4e2d\u6bd2\uff0c\u6bcf\u56de\u5408\u6263 {dot_val} HP\uff0c\u6301\u7eed {dot_dur} \u56de\u5408"

            elif skill_id == "steal":
                return f"\U0001f4b0 \u5077\u7a83\u53ea\u5bf9\u73a9\u5bb6\u6709\u6548\uff0c\u65e0\u6cd5\u5bf9 Boss \u4f7f\u7528\uff01"

            else:
                dmg = skill_def.get("damage", 20)
                room["boss_hp"] = max(0, room["boss_hp"] - dmg)
                pdata["damage_dealt"] += dmg
                return f"{skill_def['emoji']} **{skill_def['name']}** \u2014 {dmg} \u4f24\u5bb3"

        elif value.startswith("potion:"):
            potion_name = value.split(":", 1)[1]
            potion = _consume_potion(uid, potion_name)
            if not potion:
                return f"\u80cc\u5305\u4e2d\u6ca1\u6709 **{potion_name}**\uff01/ Not in your bag!"

            effect_type = potion["effect_type"]
            effect_value = potion["effect_value"]
            duration = potion.get("duration", 3)

            if effect_type == "heal_hp":
                healed = min(effect_value, pdata["max_hp"] - pdata["hp"])
                pdata["hp"] += healed
                return f"\U0001f9ea \u4f7f\u7528\u4e86 **{potion_name}**\uff01\u6062\u590d\u4e86 {healed} HP\uff08{pdata['hp']}/{pdata['max_hp']}\uff09"

            elif effect_type == "heal_mp":
                restored = min(effect_value, pdata["max_mp"] - pdata["mp"])
                pdata["mp"] += restored
                return f"\U0001f4a7 \u4f7f\u7528\u4e86 **{potion_name}**\uff01\u6062\u590d\u4e86 {restored} MP\uff08{pdata['mp']}/{pdata['max_mp']}\uff09"

            elif effect_type == "buff_atk":
                pdata["buff_atk"] += effect_value
                pdata["buff_atk_turns"] = max(pdata["buff_atk_turns"], duration)
                return f"\u2694\ufe0f \u4f7f\u7528\u4e86 **{potion_name}**\uff01ATK +{effect_value}\uff0c\u6301\u7eed {duration} \u56de\u5408"

            elif effect_type == "buff_def":
                pdata["buff_def"] += effect_value
                pdata["buff_def_turns"] = max(pdata["buff_def_turns"], duration)
                return f"\U0001f6e1\ufe0f \u4f7f\u7528\u4e86 **{potion_name}**\uff01DEF +{effect_value}\uff0c\u6301\u7eed {duration} \u56de\u5408"

            elif effect_type == "buff_crit":
                return f"\u26a1 \u4f7f\u7528\u4e86 **{potion_name}**\uff01\u66b4\u51fb\u7387 +{effect_value}%\uff0c\u6301\u7eed {duration} min"

            elif effect_type == "buff_spd":
                return f"\U0001f4a8 \u4f7f\u7528\u4e86 **{potion_name}**\uff01\u901f\u5ea6 +{effect_value}%\uff0c\u6301\u7eed {duration} min"

            else:
                return f"\u4f7f\u7528\u4e86\u672a\u77e5\u836f\u6c34 **{potion_name}**"

        return f"\u26a0\ufe0f Unknown action / \u672a\u77e5\u64cd\u4f5c"

    def _boss_counter(self, room: dict, target_uid: str) -> str:
        """Boss single-target counter-attack against the acting player."""
        if room["boss_hp"] <= 0:
            return ""

        pdata = room["players"].get(target_uid)
        if not pdata or pdata["hp"] <= 0:
            return ""

        boss_atk = room["boss_atk"]
        boss_name = room["boss"]["name"]
        boss_emoji = room["boss"]["emoji"]

        # 80% normal, 20% crit
        if random.random() < 0.2:
            dmg = int(boss_atk * random.uniform(1.5, 2.5))
            crit_text = " \U0001f4a5 CRIT! / 暴击！"
        else:
            dmg = int(boss_atk * random.uniform(0.7, 1.3))
            crit_text = ""

        # Defense reduction
        def_reduce = random.randint(0, (pdata["def"] + pdata["buff_def"]) // 3)
        actual_dmg = max(1, dmg - def_reduce)
        pdata["hp"] = max(0, pdata["hp"] - actual_dmg)

        status = ""
        if pdata["hp"] <= 0:
            status = f" \U0001f480 {pdata['username']} 阵亡！"

        phase_tag = " (Phase 2 \U0001f525)" if room["phase"] == 2 else ""
        return (
            f"\n{boss_emoji} **{boss_name}**{phase_tag} counter-attacks{crit_text}!\n"
            f"\u3000\u2192 **{pdata['username']}**: -{actual_dmg} HP \u2192 {pdata['hp']}/{pdata['max_hp']}{status}"
        )

    def _tick_buffs(self, pdata: dict):
        if pdata["buff_atk_turns"] > 0:
            pdata["buff_atk_turns"] -= 1
            if pdata["buff_atk_turns"] <= 0:
                pdata["buff_atk"] = 0
        if pdata["buff_def_turns"] > 0:
            pdata["buff_def_turns"] -= 1
            if pdata["buff_def_turns"] <= 0:
                pdata["buff_def"] = 0

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ══════════════════════════════════════════════════════════════
# Boss Lobby View — Full button-driven lobby
# ══════════════════════════════════════════════════════════════

class BossLobbyView(discord.ui.View):
    """Boss大厅面板 / Boss lobby panel — all button-driven."""

    def __init__(self, user_id: str, cog, room: dict | None = None, lobby_msg=None, main_view=None):
        super().__init__(timeout=600)
        self.uid = user_id
        self.cog = cog
        self.room = room
        self.lobby_msg = lobby_msg
        self.main_view = main_view
        self._build()

    def build_main_embed(self):
        bal = get_balance(self.uid)
        embed = discord.Embed(
            title="\U0001f409 Boss Raid / Boss 团战",
            description=(
                "与其他玩家组队挑战强大的Boss！\n"
                "Team up with others to defeat powerful bosses!\n\n"
                f"\U0001fa99 你的余额 / Your balance: **{bal:,}**"
            ),
            color=0xC0392B,
        )
        embed.add_field(
            name="\U0001f3f0 可挑战Boss / Available Bosses",
            value="\n".join(f"{b['emoji']} **{b['name']}** — {b['desc']}" for b in BOSS_TYPES.values()),
            inline=False,
        )
        embed.add_field(
            name="\u2694\ufe0f 如何开始 / How to Start",
            value="1. Click **Create** to create a room / 点击 **Create** 创建房间\n"
                  "2. Others click **Join** / 其他人点击 **Join** 加入\n"
                  "3. Host clicks **Start** to begin / 队长点击 **Start** 开始战斗",
            inline=False,
        )
        embed.set_footer(text="Boss 战消耗技能和药水，请做好准备！/ Prepare your skills and potions!")
        return embed

    def _build(self):
        self.clear_items()

        # Row 0: Create | Join | Leave | Invite | Kick
        create_btn = discord.ui.Button(
            label="Create / 创建", style=discord.ButtonStyle.success,
            row=0, emoji="\U0001f3f0",
        )
        create_btn.callback = self._create_callback
        self.add_item(create_btn)

        join_btn = discord.ui.Button(
            label="Join / 加入", style=discord.ButtonStyle.primary,
            row=0, emoji="\U0001f4cb",
        )
        join_btn.callback = self._join_callback
        self.add_item(join_btn)

        leave_btn = discord.ui.Button(
            label="Leave / 离开", style=discord.ButtonStyle.secondary,
            row=0, emoji="\U0001f6aa",
        )
        leave_btn.callback = self._leave_callback
        self.add_item(leave_btn)

        invite_btn = discord.ui.Button(
            label="Invite / 邀请", style=discord.ButtonStyle.primary,
            row=0, emoji="\U0001f465",
        )
        invite_btn.callback = self._invite_callback
        self.add_item(invite_btn)

        kick_btn = discord.ui.Button(
            label="Kick / 踢人", style=discord.ButtonStyle.danger,
            row=0, emoji="\U0001f462",
        )
        kick_btn.callback = self._kick_callback
        self.add_item(kick_btn)

        # Row 1: Start
        start_btn = discord.ui.Button(
            label="Start / 开始", style=discord.ButtonStyle.success,
            row=1, emoji="\u2694\ufe0f",
        )
        start_btn.callback = self._start_callback
        self.add_item(start_btn)

        # Row 2: World Boss | Back
        worldboss_btn = discord.ui.Button(
            label="👹 World Boss", style=discord.ButtonStyle.primary,
            row=2, emoji="👹",
        )
        worldboss_btn.callback = self._worldboss_callback
        self.add_item(worldboss_btn)

        back_btn = discord.ui.Button(
            label="Back / 返回", style=discord.ButtonStyle.danger,
            row=2, emoji="\U0001f519",
        )
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    async def _create_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        chid = str(interaction.channel_id)

        # Check existing room in channel
        for rid, room in _boss_rooms.items():
            if room.get("channel_id") == chid and room.get("status") in ("waiting", "fighting"):
                await interaction.response.send_message(
                    "本频道已有进行中的 Boss 战！/ Boss battle already in progress!", ephemeral=True)
                return

        modal = CreateBossModal(
            self.cog, chid, uid,
            interaction.user.display_name,
            interaction.message,
        )
        await interaction.response.send_modal(modal)

    async def _join_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        chid = str(interaction.channel_id)

        # First check if there's a room in this channel
        local_room = None
        for rid, room in _boss_rooms.items():
            if room.get("channel_id") == chid and room.get("status") in ("waiting", "fighting"):
                local_room = room
                break

        if local_room:
            # Join the local room directly
            if uid in local_room["players"]:
                await interaction.response.send_message(
                    "You are already in this room! / 你已经在了！", ephemeral=True)
                return

            stats = _get_user_combat_stats(uid)
            local_room["players"][uid] = {
                "hp": stats["hp"],
                "mp": stats["mp"],
                "max_hp": stats["max_hp"],
                "max_mp": stats["max_mp"],
                "atk": stats["attack"],
                "def": stats["defense"],
                "damage_dealt": 0,
                "buff_atk": 0,
                "buff_def": 0,
                "buff_atk_turns": 0,
                "buff_def_turns": 0,
                "dot_dmg": 0,
                "dot_turns": 0,
                "frozen": False,
                "burn": False,
                "burn_turns": 0,
                "stunned": False,
                "username": interaction.user.display_name,
            }

            embed = self.cog._build_room_embed(local_room)
            await interaction.response.edit_message(
                content=f"**{interaction.user.display_name}** joined the raid! / 加入了副本！",
                embed=embed,
                view=self,
            )
            return

        # No local room — show all waiting rooms globally via Select
        waiting_rooms = []
        for rid, room in _boss_rooms.items():
            if room.get("status") == "waiting":
                waiting_rooms.append((rid, room))

        if not waiting_rooms:
            await interaction.response.send_message(
                "No active rooms to join! Create one first! / 没有可加入的房间！先创建一个！", ephemeral=True)
            return

        options = []
        for rid, room in waiting_rooms[:25]:
            boss = room["boss"]
            host_name = room["players"].get(room["host_id"], {}).get("username", "Unknown")
            player_count = len(room["players"])
            options.append(discord.SelectOption(
                label=f"{boss['emoji']} {boss['name']} ({room['difficulty']})",
                value=rid,
                description=f"Host: {host_name} | Players: {player_count} | HP: {room['boss_hp']}",
            ))

        view = discord.ui.View(timeout=30)
        select = discord.ui.Select(
            placeholder="Choose a room to join / 选择要加入的房间...",
            options=options,
        )

        async def join_select_callback(sel_interaction: discord.Interaction):
            rid = sel_interaction.data["values"][0]
            target_room = _boss_rooms.get(rid)
            if not target_room or target_room["status"] != "waiting":
                await sel_interaction.response.send_message(
                    "Room no longer available! / 房间已不可用！", ephemeral=True)
                return

            sel_uid = str(sel_interaction.user.id)
            if sel_uid in target_room["players"]:
                await sel_interaction.response.send_message(
                    "Already in this room! / 你已经在了！", ephemeral=True)
                return

            stats = _get_user_combat_stats(sel_uid)
            target_room["players"][sel_uid] = {
                "hp": stats["hp"],
                "mp": stats["mp"],
                "max_hp": stats["max_hp"],
                "max_mp": stats["max_mp"],
                "atk": stats["attack"],
                "def": stats["defense"],
                "damage_dealt": 0,
                "buff_atk": 0,
                "buff_def": 0,
                "buff_atk_turns": 0,
                "buff_def_turns": 0,
                "dot_dmg": 0,
                "dot_turns": 0,
                "frozen": False,
                "burn": False,
                "burn_turns": 0,
                "stunned": False,
                "username": sel_interaction.user.display_name,
            }

            await sel_interaction.response.send_message(
                f"Joined **{target_room['boss']['emoji']} {target_room['boss']['name']}** ({target_room['difficulty']})! / 加入成功！",
                ephemeral=True,
            )

        select.callback = join_select_callback
        view.add_item(select)
        await interaction.response.send_message(
            "Select a room to join / 选择要加入的房间:", view=view, ephemeral=True)

    async def _leave_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        chid = str(interaction.channel_id)

        room = self.cog._find_room_by_channel(chid)
        if not room:
            await interaction.response.send_message(
                "No active room in this channel! / 本频道没有进行中的房间！", ephemeral=True)
            return

        if uid not in room["players"]:
            await interaction.response.send_message(
                "You are not in this room! / 你不在房间中！", ephemeral=True)
            return

        username = room["players"][uid]["username"]
        del room["players"][uid]

        # If host left and room is waiting, transfer host or disband
        if uid == room.get("host_id") and room["status"] == "waiting":
            if room["players"]:
                new_host = next(iter(room["players"]))
                room["host_id"] = new_host
                room["players"][new_host]["username"] = room["players"][new_host].get("username", "Unknown")
                await interaction.response.send_message(
                    f"\U0001f6aa **{username}** left. New host: **{room['players'][new_host]['username']}**")
            else:
                room["status"] = "finished"
                await interaction.response.send_message(
                    f"\U0001f6aa **{username}** left. Room disbanded / 房间已解散。")
                return
        else:
            await interaction.response.send_message(
                f"\U0001f6aa **{username}** left the room! / 离开了房间！")

        if room["status"] == "waiting":
            embed = self.cog._build_room_embed(room)
            await interaction.message.edit(embed=embed, view=self)

    async def _invite_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        chid = str(interaction.channel_id)

        room = self.cog._find_room_by_channel(chid)
        if not room:
            await interaction.response.send_message(
                "No active room! / 没有进行中的房间！", ephemeral=True)
            return

        if uid != room.get("host_id"):
            await interaction.response.send_message(
                "Only the host can invite! / 只有队长可以邀请！", ephemeral=True)
            return

        if room["status"] not in ("waiting", "fighting"):
            await interaction.response.send_message(
                "Battle is over! / 战斗已结束！", ephemeral=True)
            return

        # Get online members in guild
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Guild not found!", ephemeral=True)
            return

        online_members = [m for m in guild.members
                          if m.status != discord.Status.offline
                          and not m.bot
                          and str(m.id) != uid
                          and str(m.id) not in room["players"]]

        if not online_members:
            await interaction.response.send_message(
                "No online players to invite! / 没有可邀请的在线玩家！", ephemeral=True)
            return

        options = []
        for m in online_members[:25]:
            options.append(discord.SelectOption(
                label=m.display_name,
                value=str(m.id),
                description=f"@{m.name}",
            ))

        view = discord.ui.View(timeout=60)
        select = discord.ui.Select(
            placeholder="Choose a player to invite / 选择要邀请的玩家...",
            options=options,
        )

        async def invite_select_callback(sel_interaction: discord.Interaction):
            target_id = sel_interaction.data["values"][0]
            member = guild.get_member(int(target_id))
            if not member:
                await sel_interaction.response.send_message(
                    "Player not found! / 玩家未找到！", ephemeral=True)
                return

            try:
                invite_embed = discord.Embed(
                    title=f"{room['boss']['emoji']} Boss Raid Invite / Boss 团战邀请！",
                    description=(
                        f"**{interaction.user.display_name}** invites you to a raid! / 邀请你加入副本！\n"
                        f"Boss: **{room['boss']['name']}** | Difficulty / 难度: **{room['difficulty']}**\n"
                        f"Go to {interaction.channel.mention} and click **Join** / 前往并点击 **Join**！"
                    ),
                    color=room["diff_color"],
                )
                await member.send(embed=invite_embed)
            except discord.Forbidden:
                pass

            await sel_interaction.response.send_message(
                f"\u2709\ufe0f Invite sent to **{member.display_name}**! / 邀请已发送！", ephemeral=True)

        select.callback = invite_select_callback
        view.add_item(select)
        await interaction.response.send_message(
            "Select a player to invite / 选择要邀请的玩家:", view=view, ephemeral=True)

    async def _kick_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        chid = str(interaction.channel_id)

        room = self.cog._find_room_by_channel(chid)
        if not room:
            await interaction.response.send_message(
                "No active room! / 没有进行中的房间！", ephemeral=True)
            return

        if uid != room.get("host_id"):
            await interaction.response.send_message(
                "Only the host can kick! / 只有队长可以踢人！", ephemeral=True)
            return

        if room["status"] != "waiting":
            await interaction.response.send_message(
                "Can only kick during waiting phase! / 只能在等待阶段踢人！", ephemeral=True)
            return

        # List room players (excluding host)
        kickable = {pid: pdata for pid, pdata in room["players"].items() if pid != uid}
        if not kickable:
            await interaction.response.send_message(
                "No players to kick! / 没有可踢出的玩家！", ephemeral=True)
            return

        options = []
        for pid, pdata in kickable.items():
            options.append(discord.SelectOption(
                label=pdata["username"],
                value=pid,
            ))

        view = discord.ui.View(timeout=30)
        select = discord.ui.Select(
            placeholder="Choose a player to kick / 选择要踢出的玩家...",
            options=options[:25],
        )

        async def kick_select_callback(sel_interaction: discord.Interaction):
            target_id = sel_interaction.data["values"][0]
            if target_id not in room["players"]:
                await sel_interaction.response.send_message(
                    "Player not found! / 玩家未找到！", ephemeral=True)
                return

            kicked_name = room["players"][target_id]["username"]
            del room["players"][target_id]

            await sel_interaction.response.send_message(
                f"\U0001f462 **{kicked_name}** has been kicked! / 已被踢出！", ephemeral=True)

            # Refresh lobby
            embed = self.cog._build_room_embed(room)
            try:
                await interaction.message.edit(embed=embed, view=self)
            except Exception:
                logger.exception("Boss kick: edit message failed")
                pass

        select.callback = kick_select_callback
        view.add_item(select)
        await interaction.response.send_message(
            "Select a player to kick / 选择要踢出的玩家:", view=view, ephemeral=True)

    async def _start_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        chid = str(interaction.channel_id)

        room = self.cog._find_room_by_channel(chid)
        if not room:
            await interaction.response.send_message(
                "No active room! / 没有进行中的房间！", ephemeral=True)
            return

        if uid != room.get("host_id"):
            await interaction.response.send_message(
                "Only the host can start! / 只有队长可以开始！", ephemeral=True)
            return

        if room["status"] != "waiting":
            await interaction.response.send_message(
                "Battle already started! / 战斗已经开始！", ephemeral=True)
            return

        alive = sum(1 for p in room["players"].values() if p["hp"] > 0)
        if alive < 1:
            await interaction.response.send_message(
                "No alive players! / 没有存活的玩家！", ephemeral=True)
            return

        room["status"] = "fighting"
        room["start_time"] = time.time()

        battle_view = BossBattleView(self.cog, room, interaction.message)

        embed = self.cog._build_room_embed(room)
        embed.description = (
            f"**Battle Start! / 战斗开始！**\n"
            f"Use the Select dropdown to choose your action!\n"
            f"使用下拉菜单选择你的行动！"
        )

        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=battle_view,
        )

    async def _worldboss_callback(self, interaction: discord.Interaction):
        """Open World Boss panel from BossLobby."""
        try:
            view = WorldBossView(self.uid, main_view=self.main_view)
            embed = view.build_embed()
            await interaction.response.edit_message(embed=embed, view=view)
        except Exception as e:
            logger.error(f"WorldBoss callback error (uid={self.uid}): {e}", exc_info=True)
            await interaction.response.send_message(
                "World Boss panel error", ephemeral=True)

    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            from cogs.mmorpg_shop import _get_user_stats
            uid = str(self.uid)
            stats = _get_user_stats(uid)
            bal = get_balance(uid)
            embed = discord.Embed(
                title="MMORPG Main Panel / MMORPG 主面板",
                description=(
                    f"\u2764\ufe0f HP: **{stats['hp']}/{stats['max_hp']}**  "
                    f"\U0001f52e MP: **{stats['mp']}/{stats['max_mp']}**\n"
                    f"\u2694\ufe0f ATK: **{stats['attack']}**  \U0001f6e1\ufe0f DEF: **{stats['defense']}**  "
                    f"\u2b50 Lv.**{stats['level']}**  \U0001fa99 **{bal:,}**\n\n"
                    "Click a button below / 点击下方按钮："
                ),
                color=0x9B59B6,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)


    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass

# ══════════════════════════════════════════════════════════════
# Boss Cog — simplified, only /gmpt-boss lobby
# ══════════════════════════════════════════════════════════════

class BossCog(CogBase):
    """MMORPG Boss 团战系统 / Boss Raid — button-driven."""

    gmpt_boss_group = app_commands.Group(
        name="gmpt-boss",
        description="MMORPG Boss团战 / Boss Raid — 组队挑战"
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.auto_boss_task = asyncio.create_task(self._auto_boss_spawn_loop())

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss lobby — the only slash command
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="lobby",
        description="打开Boss大厅面板 / Open Boss lobby panel"
    )
    async def boss_lobby(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        chid = str(interaction.channel_id)

        # Check if there's an active room in this channel
        existing_room = self._find_room_by_channel(chid)

        if existing_room:
            if existing_room["status"] == "fighting":
                # Show battle view
                battle_view = BossBattleView(self, existing_room, None)
                embed = self._build_room_embed(existing_room)
                await interaction.response.send_message(embed=embed, view=battle_view)
            else:
                # Show lobby with existing room
                view = BossLobbyView(uid, self, existing_room, None)
                embed = self._build_room_embed(existing_room)
                await interaction.response.send_message(embed=embed, view=view)
        else:
            view = BossLobbyView(uid, self)
            embed = view.build_main_embed()
            await interaction.response.send_message(embed=embed, view=view)

    # ══════════════════════════════════════════════════════════
    # Room helpers
    # ══════════════════════════════════════════════════════════

    def _find_room_by_channel(self, chid: str) -> dict | None:
        for rid, room in _boss_rooms.items():
            if room.get("channel_id") == chid and room.get("status") in ("waiting", "fighting"):
                return room
        return None

    def _build_room_embed(self, room: dict, defeated: bool = False) -> discord.Embed:
        boss = room["boss"]
        emoji = boss["emoji"]
        boss_name = boss["name"]
        phase = room["phase"]

        title = f"{emoji} {boss_name} Raid / 团战"
        if defeated:
            title = f"{emoji} {boss_name} — Defeated! / 已击败！"
        elif phase == 2:
            title = f"{emoji} {boss_name} — Phase 2 Rage! / 暴怒阶段！"

        embed = discord.Embed(title=title, color=room["diff_color"])
        embed.add_field(name="Difficulty / 难度", value=room["diff_label"], inline=True)
        if boss.get("element"):
            embed.add_field(name="Element / 元素", value=f"{boss['element']}", inline=True)
        embed.add_field(name="Turn / 回合", value=str(room["turn"]), inline=True)
        embed.add_field(name="Phase / 阶段", value=f"{'Rage ' if phase == 2 else ''}Phase {phase}", inline=True)

        # Boss HP bar
        embed.add_field(
            name="Boss HP",
            value=f"```{progress_bar(room['boss_hp'], room['boss_max_hp'], 15)}```\n{room['boss_hp']}/{room['boss_max_hp']}",
            inline=False,
        )

        # Boss skills
        embed.add_field(
            name="Skills / 技能",
            value=" | ".join(boss["skills"]),
            inline=True,
        )
        if phase == 2:
            embed.add_field(
                name="Rage Skill / 暴怒技能",
                value=boss["rage_skill"],
                inline=False,
            )

        embed.add_field(name="ATK / 攻击力", value=str(room["boss_atk"]), inline=True)

        # Player list with HP/MP bars and buffs
        player_lines = []
        for pid, p in room["players"].items():
            alive_mark = "" if p["hp"] > 0 else "\U0001f480"
            hp_bar = _format_bar(p["hp"], p["max_hp"], 10)
            mp_bar = _format_bar(p["mp"], p["max_mp"], 6)

            buffs = []
            if p["buff_atk"] > 0:
                buffs.append(f"ATK+{p['buff_atk']}({p['buff_atk_turns']}T)")
            if p["buff_def"] > 0:
                buffs.append(f"DEF+{p['buff_def']}({p['buff_def_turns']}T)")
            if p["frozen"]:
                buffs.append("Freeze/冻结")
            if p["stunned"]:
                buffs.append("Stun/眩晕")
            if p["dot_dmg"] > 0:
                buffs.append(f"Poison/毒({p['dot_turns']}T)")
            if p["burn"]:
                buffs.append(f"Burn/灼烧({p['burn_turns']}T)")

            buff_str = f" [{', '.join(buffs)}]" if buffs else ""
            line = (
                f"{alive_mark} **{p['username']}**\n"
                f"\u3000HP: {hp_bar}\n"
                f"\u3000MP: {mp_bar}\n"
                f"\u3000DMG: {p['damage_dealt']}{buff_str}"
            )
            player_lines.append(line)

        embed.add_field(
            name=f"Players / 玩家 ({len(room['players'])})",
            value="\n".join(player_lines) if player_lines else "Waiting to join / 等待加入...",
            inline=False,
        )

        status_text = {
            "waiting": "Waiting / 等待开始",
            "fighting": "Fighting / 战斗中",
            "finished": "Finished / 已结束",
        }
        status = room.get("status", "unknown")
        footer = f"Status / 状态: {status_text.get(status, status)}"
        if status == "fighting":
            footer += " | Select an action from dropdown / 从下拉菜单选择行动"
        elif status == "waiting":
            footer += " | Host click Start to begin / 队长点击 Start 开始"
        embed.set_footer(text=footer)
        return embed

    # ══════════════════════════════════════════════════════════
    # Cooldown / Kill record helpers
    # ══════════════════════════════════════════════════════════

    def _get_cooldown_remaining(self, user_id: str, boss_name: str, difficulty: str) -> int:
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT last_cleared_at FROM boss_dungeon_cooldowns
                WHERE user_id = ? AND boss_name = ? AND difficulty = ?
            """, (user_id, boss_name, difficulty))
            row = cur.fetchone()
        if not row:
            return 0
        cd_min = BOSS_TYPES.get(boss_name, {}).get("cooldown_min", {}).get(difficulty, 15)
        elapsed = time.time() - float(row[0])
        return max(0, cd_min * 60 - int(elapsed))

    def _set_cooldown(self, user_id: str, boss_name: str, difficulty: str):
        with get_db_ctx() as conn:
            conn.cursor().execute("""
                INSERT OR REPLACE INTO boss_dungeon_cooldowns (user_id, boss_name, difficulty, last_cleared_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, boss_name, difficulty, str(time.time())))
            conn.commit()

    def _record_kill(self, boss_name: str, difficulty: str, user_id: str, dmg: int, duration_sec: float):
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO boss_kill_stats (boss_name, difficulty, kill_count, fastest_clear_seconds, total_damage, first_clear_by)
                VALUES (?, ?, 1, ?, ?, ?)
                ON CONFLICT(boss_name, difficulty) DO UPDATE SET
                    kill_count = kill_count + 1,
                    fastest_clear_seconds = MIN(fastest_clear_seconds, ?),
                    total_damage = total_damage + ?
            """, (boss_name, difficulty, duration_sec, dmg, user_id, duration_sec, dmg))
            cur.execute("""
                INSERT INTO boss_player_kills (user_id, boss_name, difficulty, kills, top_damage, last_kill_at)
                VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(user_id, boss_name, difficulty) DO UPDATE SET
                    kills = kills + 1,
                    top_damage = MAX(top_damage, ?),
                    last_kill_at = ?
            """, (user_id, boss_name, difficulty, dmg, str(time.time()), dmg, str(time.time())))
            conn.commit()

    def _get_daily_first_kill(self, user_id: str) -> bool:
        today = datetime.date.today().isoformat()
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 1 FROM boss_player_kills
                WHERE user_id = ? AND date(last_kill_at) = ?
            """, (user_id, today))
            return cur.fetchone() is None

    def _roll_loot_by_room(self, room: dict) -> list:
        """Roll for loot drops based on difficulty tier loot pools."""
        diff = room.get("diff", room.get("difficulty", "简单"))
        loot_cfg = DIFFICULTY_LOOT.get(diff)
        if not loot_cfg:
            return []

        drops = []
        for tier_name in loot_cfg["tiers"]:
            pool = loot_cfg["pools"].get(tier_name, [])
            if pool:
                num = random.randint(1, 2)
                for _ in range(num):
                    item = random.choice(pool)
                    drops.append(f"{tier_name} {item[0]}")

        consumable_pool = loot_cfg["pools"].get("consumable", [])
        if consumable_pool:
            num_con = random.randint(1, 2)
            for _ in range(num_con):
                con = random.choice(consumable_pool)
                drops.append(f"🧪 {con[0]}")

        if random.random() < loot_cfg["rare_chance"]:
            rare_tier = "T3" if "T3" in loot_cfg["tiers"] else "T2"
            for dcfg in DIFFICULTY_LOOT.values():
                pool = dcfg["pools"].get(rare_tier)
                if pool:
                    item = random.choice(pool)
                    drops.append(f"🌟 RARE! {rare_tier} {item[0]}")
                    break

        if random.random() < loot_cfg["legendary_chance"]:
            leg = random.choice(LEGENDARY_POOL)
            drops.append(f"🏆 LEGENDARY! {leg[0]}")

        return drops

    def _distribute_rewards(self, room: dict, duration_sec: float) -> list[str]:
        """Distribute coins and loot based on damage_dealt proportion."""
        players = room["players"]
        total_dmg = sum(p["damage_dealt"] for p in players.values())
        reward_pool = int(room["boss_max_hp"] * room["reward_mult"] * 0.8)

        # Find MVP
        mvp_uid = max(players.items(), key=lambda x: x[1]["damage_dealt"])[0]
        mvp_name = players[mvp_uid]["username"]
        mvp_extra = int(reward_pool * 0.1)

        lines = [f"\U0001f3c6 MVP: **{mvp_name}** ({players[mvp_uid]['damage_dealt']} DMG) — Bonus / 额外 +{mvp_extra}\U000020B0"]

        for pid, pdata in players.items():
            if total_dmg <= 0:
                share = 0
            else:
                share = int(reward_pool * pdata["damage_dealt"] / total_dmg)

            # Daily first kill bonus
            if self._get_daily_first_kill(pid):
                share = int(share * 2)
                first_bonus = " (First Kill x2! / 首杀双倍！)"
            else:
                first_bonus = ""

            # Loot drops
            drops = self._roll_loot_by_room(room)
            loot_text = ""
            for drop_name in drops:
                is_legendary = "LEGENDARY!" in drop_name
                is_rare = "RARE!" in drop_name
                prefix = "\U0001f3c6 " if is_legendary else ("\U0001f31f " if is_rare else "\U0001f381 ")
                loot_text += f" + {prefix}{drop_name}"
# MVP bonus
            mvp_bonus = 0
            mvp_str = ""
            if pid == mvp_uid:
                mvp_bonus = mvp_extra
                mvp_str = f" + \U0001f3c6 MVP Bonus / MVP额外+{mvp_extra}\U000020B0"

            total_earn = share + mvp_bonus
            if total_earn > 0:
                add_coins(pid, total_earn, f"Boss Raid Reward / Boss副本奖励: {room['boss']['name']} {room['difficulty']}")
                # Quest progress: kill
                try:
                    from cogs.daily_quest import _update_progress
                    _update_progress(pid, "kill")
                except Exception:
                    logger.exception("Boss: _update_progress failed")
                    pass

            # Record kill
            self._set_cooldown(pid, room["boss"]["name"], room["difficulty"])
            self._record_kill(room["boss"]["name"], room["difficulty"], pid, pdata["damage_dealt"], duration_sec)

            lines.append(
                f"- **{pdata['username']}**: {pdata['damage_dealt']} DMG \u2192 +{total_earn}\U000020B0{first_bonus}{loot_text}{mvp_str}"
            )

            # Broadcast legendary / rare drops globally
            for drop_name in drops:
                if "LEGENDARY!" in drop_name:
                    try:
                        leg_embed = discord.Embed(
                            title="\U0001f3c6 LEGENDARY DROP! \u4f20\u8bf4\u6389\u843d\uff01",
                            description=f"**{pdata['username']}** \u83b7\u5f97\u4e86\u4f20\u8bf4\u4e2d\u7684\u5b9d\u7269\uff01\n**{drop_name}**",
                            color=0xFFD700,
                        )
                        leg_embed.set_footer(text="\u2728 \u4f20\u8bf4\u7ea7\u88c5\u5907\u5e26\u6709\u7279\u6b8a\u5149\u6548\uff01Legendary item with special glow effect!")
                        asyncio.create_task(channel.send(embed=leg_embed))
                    except Exception:
                        logger.exception("Boss: send legendary drop embed failed")
                        pass
                elif "RARE!" in drop_name:
                    try:
                        rare_embed = discord.Embed(
                            title="\U0001f31f RARE DROP! \u7a00\u6709\u6389\u843d\uff01",
                            description=f"**{pdata['username']}** \u83b7\u5f97\u4e86\u7a00\u6709\u7269\u54c1\uff01\n**{drop_name}**",
                            color=0x3498DB,
                        )
                        asyncio.create_task(channel.send(embed=rare_embed))
                    except Exception:
                        logger.exception("Boss: send rare drop embed failed")
                        pass

        return lines


    # ══════════════════════════════════════════════════════════════
    # Auto Boss Spawn
    # ══════════════════════════════════════════════════════════════

    async def _auto_boss_spawn_loop(self):
        """Every BOSS_SPAWN_INTERVAL seconds, spawn a random boss in the designated channel."""
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)  # initial delay after ready

        while not self.bot.is_closed():
            try:
                channel = self.bot.get_channel(int(BOSS_SPAWN_CHANNEL_ID))
                if channel:
                    # Pick random boss + element + difficulty
                    boss_names = list(BOSS_TYPES.keys())
                    boss_key = random.choice(boss_names)
                    boss_def = dict(BOSS_TYPES[boss_key])
                    boss_def["key"] = boss_key
                    boss_element = random.choice(ELEMENTS)
                    boss_def["element"] = boss_element

                    diff_key = random.choices(
                        list(BOSS_SPAWN_DIFFICULTY_WEIGHTS.keys()),
                        weights=list(BOSS_SPAWN_DIFFICULTY_WEIGHTS.values()),
                        k=1,
                    )[0]
                    diff_cfg = DIFFICULTY[diff_key]

                    # Build room
                    room_id = f"auto_{int(time.time())}_{random.randint(1000, 9999)}"
                    hp = int(250 * diff_cfg["hp_mult"])
                    atk = int(55 * diff_cfg["atk_mult"])

                    room = {
                        "room_id": room_id,
                        "channel_id": str(channel.id),
                        "boss": boss_def,
                        "difficulty": diff_key,
                        "difficulty_raw": diff_key,
                        "diff": diff_key,
                        "diff_color": diff_cfg["color"],
                        "difficulty_label": diff_cfg["label"],
                        "multiplayer": True,
                        "players": {},
                        "boss_hp": hp,
                        "boss_max_hp": hp,
                        "boss_atk": atk,
                        "reward_mult": diff_cfg["reward_mult"],
                        "status": "waiting",
                        "phase": 1,
                        "turn": 0,
                        "start_time": 0,
                        "boss_element": boss_element,
                    }

                    _boss_rooms[room_id] = room

                    # Send embed notification
                    elem_emoji = {"Fire": "\U0001f525", "Water": "\U0001f4a7", "Wind": "\U0001f4a8", "Earth": "\U0001faa8"}
                    spawn_embed = discord.Embed(
                        title=f"\U0001f4e3 Auto Boss Spawn! / \u81ea\u52a8 Boss \u751f\u6210\uff01",
                        description=(
                            f"**{boss_def['name']}** {boss_def.get('emoji', '')} \u51fa\u73b0\u4e86\uff01\n"
                            f"\U0001f9ea Element / \u5143\u7d20: **{boss_element}** {elem_emoji.get(boss_element, '')}\n"
                            f"\U0001f4ca Difficulty / \u96be\u5ea6: **{diff_cfg['label']}** {diff_cfg.get('stars', '')}\n"
                            f"HP: {hp} | ATK: {atk}\n"
                            f"\u23f0 Use `/gmpt-boss lobby` to join! / \u4f7f\u7528 `/gmpt-boss lobby` \u52a0\u5165\u6218\u6597\uff01\n"
                            f"\u26a0\ufe0f Boss \u5c06\u572830\u5206\u949f\u540e\u9003\u8dd1\uff01Will flee after 30 min!"
                        ),
                        color=diff_cfg["color"],
                    )
                    spawn_embed.set_footer(text=f"Room ID: {room_id}")
                    spawn_msg = await channel.send(embed=spawn_embed)

                    # Wait 30 min timeout
                    await asyncio.sleep(BOSS_AUTO_TIMEOUT)

                    # Check if boss still exists and not beaten
                    current_room = _boss_rooms.get(room_id)
                    if current_room and current_room["status"] != "finished":
                        try:
                            flee_embed = discord.Embed(
                                title="\U0001f3c3 Boss \u8dd1\u8dd1\u4e86\uff01The boss fled!",
                                description=f"**{boss_def['name']}** \u6d88\u5931\u5728\u9ed1\u6697\u4e2d... / vanished into darkness...",
                                color=0x95A5A6,
                            )
                            await channel.send(embed=flee_embed)
                        except Exception:
                            logger.exception("Boss: send flee embed failed")
                            pass
                        if room_id in _boss_rooms:
                            del _boss_rooms[room_id]
                else:
                    print(f"[AutoBoss] Channel {BOSS_SPAWN_CHANNEL_ID} not found!")
            except Exception as e:
                print(f"[AutoBoss] Error: {e}")

            await asyncio.sleep(BOSS_SPAWN_INTERVAL)


async def setup(bot):
    await bot.add_cog(BossCog(bot))
