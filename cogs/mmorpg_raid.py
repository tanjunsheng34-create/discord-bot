"""
GMPT Bot — MMORPG Raid / 副本系统
/gmpt-raid create  — 创建 Raid 队伍
/gmpt-raid join    — 加入队伍
/gmpt-raid start   — 队长开战
/gmpt-raid leave   — 退出队伍

3人组队，Tank/DPS/Healer定位，回合制Boss战（上限30回合）。
深度集成宠物属性 + 装备属性 + 附魔属性到战斗计算。
"""
import asyncio
import logging
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
from utils.animations import progress_bar
from cogs.economy import add_coins, get_balance

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Raid Boss Catalog
# ══════════════════════════════════════════════════════════════
RAID_BOSSES = {
    "infernal_dragon": {
        "id": "infernal_dragon",
        "name": "炼狱巨龙 Infernal Megadragon",
        "emoji": "🐉",
        "hp": 3000,
        "atk": 100,
        "def": 30,
        "min_level": 30,
        "recommend": "3人 Lv.30+",
        "rewards_gold": 500,
        "rewards_epic_chance": 0.30,
        "rewards_legendary_chance": 0,
        "rewards_title": "",
    },
    "void_walker": {
        "id": "void_walker",
        "name": "虚空行者 Void Walker",
        "emoji": "👹",
        "hp": 5000,
        "atk": 140,
        "def": 40,
        "min_level": 45,
        "recommend": "3人 Lv.45+",
        "rewards_gold": 800,
        "rewards_epic_chance": 0,
        "rewards_legendary_chance": 0.30,
        "rewards_title": "",
    },
    "ancient_god": {
        "id": "ancient_god",
        "name": "远古之神 Ancient God",
        "emoji": "👑",
        "hp": 8000,
        "atk": 180,
        "def": 50,
        "min_level": 55,
        "recommend": "3人 Lv.55+",
        "rewards_gold": 1200,
        "rewards_epic_chance": 0,
        "rewards_legendary_chance": 0.50,
        "rewards_title": "弑神者",
    },
}

ROLE_EMOJIS = {"tank": "🛡️", "dps": "⚔️", "healer": "💚"}
MAX_TURNS = 30

# ══════════════════════════════════════════════════════════════
# DB Init
# ══════════════════════════════════════════════════════════════
def _init_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS raid_rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL,
                raid_id TEXT NOT NULL,
                status TEXT DEFAULT 'waiting',
                channel_id TEXT,
                message_id TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS raid_members (
                room_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'dps',
                ready INTEGER DEFAULT 0,
                PRIMARY KEY (room_id, user_id)
            )
        """)
        conn.commit()


# ══════════════════════════════════════════════════════════════
# Stat Helpers — integrate pet + equipment + enchant
# ══════════════════════════════════════════════════════════════
def _get_base_stats(uid: str) -> dict:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT hp, max_hp, mp, max_mp, attack, defense, level FROM users WHERE discord_id = ?",
            (uid,),
        )
        row = cur.fetchone()
    if row:
        return {"hp": row["hp"], "max_hp": row["max_hp"], "mp": row["mp"], "max_mp": row["max_mp"],
                "atk": row["attack"], "def": row["defense"], "level": row["level"] or 1}
    return {"hp": 100, "max_hp": 100, "mp": 50, "max_mp": 50, "atk": 10, "def": 5, "level": 1}


def _get_pet_stats(uid: str) -> dict:
    """Get active pet bonus stats."""
    try:
        from cogs.mmorpg_pet import get_active_pet_bonus
        return get_active_pet_bonus(uid)
    except Exception:
        return {"atk": 0, "def": 0, "hp": 0}


def _get_equip_stats(uid: str) -> dict:
    """Get total equipment stats."""
    try:
        from cogs.mmorpg_equipment import _get_equip_stats as eq_stats
        return eq_stats(uid)
    except Exception:
        return {"atk": 0, "def": 0, "hp": 0, "crit": 0, "spd": 0}


def _get_enchant_stats(uid: str) -> dict:
    """Get total enchantment stats from all equipped items."""
    try:
        from cogs.mmorpg_enchant import _get_user_equipment, _get_enchantment
        items = _get_user_equipment(uid)
        stats = {"atk": 0, "def": 0, "hp": 0, "crit": 0}
        for item in items:
            ench = _get_enchantment(uid, item["item_name"])
            if ench:
                stats["atk"] += ench.get("enchant_atk", 0) or 0
                stats["def"] += ench.get("enchant_def", 0) or 0
                stats["hp"] += ench.get("enchant_hp", 0) or 0
                stats["crit"] += ench.get("enchant_crit", 0) or 0
        return stats
    except Exception:
        return {"atk": 0, "def": 0, "hp": 0, "crit": 0}


def _get_full_stats(uid: str) -> dict:
    """Get aggregated combat stats: base + pet + equipment + enchant."""
    base = _get_base_stats(uid)
    pet = _get_pet_stats(uid)
    equip = _get_equip_stats(uid)
    enchant = _get_enchant_stats(uid)
    return {
        "hp": base["hp"],
        "max_hp": base["max_hp"] + pet.get("hp", 0) + equip.get("hp", 0) + enchant.get("hp", 0),
        "mp": base["mp"],
        "max_mp": base["max_mp"],
        "atk": base["atk"] + pet.get("atk", 0) + equip.get("atk", 0) + enchant.get("atk", 0),
        "def": base["def"] + pet.get("def", 0) + equip.get("def", 0) + enchant.get("def", 0),
        "level": base["level"],
        "crit": equip.get("crit", 0) + enchant.get("crit", 0),
        "spd": equip.get("spd", 0),
    }


def _save_stats(uid: str, stats: dict):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET hp = ?, mp = ? WHERE discord_id = ?",
                     (max(0, stats["hp"]), max(0, stats["mp"]), uid))
        conn.commit()


# ══════════════════════════════════════════════════════════════
# Raid Lobby View
# ══════════════════════════════════════════════════════════════
class RaidLobbyView(discord.ui.View):
    """主 Raid 大厅面板."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="⚔️ Raid 副本 / Raid Dungeons",
            description="组建 3 人队伍，挑战强力 Boss！\nForm a 3-player party and take on powerful bosses!",
            color=0xFF4500,
        )
        for bid, boss in RAID_BOSSES.items():
            embed.add_field(
                name=f"{boss['emoji']} {boss['name']}",
                value=(
                    f"❤️ HP: **{boss['hp']}** | ⚔️ ATK: **{boss['atk']}** | 🛡️ DEF: **{boss['def']}**\n"
                    f"⭐ 推荐: {boss['recommend']} | 💰 {boss['rewards_gold']}G\n"
                    f"创建: `/gmpt-raid create {bid}`"
                ),
                inline=False,
            )
        embed.set_footer(text="选择 Boss 后在聊天中使用 /gmpt-raid create <raid_id> 创建队伍")
        return embed


# ══════════════════════════════════════════════════════════════
# Raid Room View
# ══════════════════════════════════════════════════════════════
class RaidRoomView(discord.ui.View):
    """队伍房间面板 — 选角色、准备、开战."""

    def __init__(self, cog, room_id: int, owner_id: str, raid_id: str, uid: str):
        super().__init__(timeout=600)
        self.cog = cog
        self.room_id = room_id
        self.owner_id = owner_id
        self.raid_id = raid_id
        self.uid = uid  # current viewer
        self._build()

    def _build(self):
        self.clear_items()
        boss = RAID_BOSSES.get(self.raid_id, RAID_BOSSES["infernal_dragon"])

        # Role select buttons
        tank_btn = discord.ui.Button(
            label="Tank 坦克", emoji="🛡️", style=discord.ButtonStyle.primary,
            row=0, custom_id=f"raid_role_tank_{self.room_id}"
        )
        tank_btn.callback = self._role_tank
        self.add_item(tank_btn)

        dps_btn = discord.ui.Button(
            label="DPS 输出", emoji="⚔️", style=discord.ButtonStyle.danger,
            row=0, custom_id=f"raid_role_dps_{self.room_id}"
        )
        dps_btn.callback = self._role_dps
        self.add_item(dps_btn)

        healer_btn = discord.ui.Button(
            label="Healer 辅助", emoji="💚", style=discord.ButtonStyle.success,
            row=0, custom_id=f"raid_role_healer_{self.room_id}"
        )
        healer_btn.callback = self._role_healer
        self.add_item(healer_btn)

        # Action buttons
        ready_btn = discord.ui.Button(
            label="Ready 准备", emoji="✅", style=discord.ButtonStyle.secondary,
            row=1, custom_id=f"raid_ready_{self.room_id}"
        )
        ready_btn.callback = self._ready
        self.add_item(ready_btn)

        leave_btn = discord.ui.Button(
            label="Leave 离开", emoji="❌", style=discord.ButtonStyle.secondary,
            row=1, custom_id=f"raid_leave_{self.room_id}"
        )
        leave_btn.callback = self._leave
        self.add_item(leave_btn)

    def build_embed(self) -> discord.Embed:
        boss = RAID_BOSSES.get(self.raid_id, RAID_BOSSES["infernal_dragon"])
        members = self.cog.raid_members.get(self.room_id, {})

        embed = discord.Embed(
            title=f"Raid Room #{self.room_id} / 副本房间",
            color=0xFF6600,
        )
        embed.add_field(
            name=f"{boss['emoji']} {boss['name']}",
            value=f"❤️ {boss['hp']} | ⚔️ {boss['atk']} | 🛡️ {boss['def']} | ⭐ {boss['recommend']}",
            inline=False,
        )

        lines = []
        roles_taken = set()
        for uid_key, data in members.items():
            role = data.get("role", "?")
            ready_str = "✅" if data.get("ready") else "⏳"
            lines.append(f"{ready_str} <@{uid_key}> — {ROLE_EMOJIS.get(role, '❓')} **{role.upper()}**")
            roles_taken.add(role)
        if not lines:
            lines.append("(empty / 空)")
        embed.add_field(name="队伍成员 / Party", value="\n".join(lines), inline=False)

        available = []
        for r in ["tank", "dps", "healer"]:
            if r not in roles_taken:
                available.append(f"{ROLE_EMOJIS[r]} {r.upper()}")
        embed.add_field(name="可选取位 / Available Roles", value=", ".join(available) if available else "已满",
                        inline=False)

        embed.add_field(
            name="使用说明 / How to",
            value="点击角色按钮选定位 → 点 ✅ Ready → 队长点 `/gmpt-raid start` 开战",
            inline=False,
        )
        embed.set_footer(text=f"队长 / Owner: {self.owner_id}")
        return embed

    async def _role_tank(self, interaction: discord.Interaction):
        await self._set_role(interaction, "tank")

    async def _role_dps(self, interaction: discord.Interaction):
        await self._set_role(interaction, "dps")

    async def _role_healer(self, interaction: discord.Interaction):
        await self._set_role(interaction, "healer")

    async def _set_role(self, interaction: discord.Interaction, role: str):
        uid_key = str(interaction.user.id)
        members = self.cog.raid_members.get(self.room_id, {})
        if uid_key not in members:
            await interaction.response.send_message("You are not in this room! / 你不在这个房间里！", ephemeral=True)
            return

        # Check if role already taken
        for mid, mdata in members.items():
            if mdata.get("role") == role and mid != uid_key:
                await interaction.response.send_message(
                    f"{ROLE_EMOJIS[role]} {role.upper()} 已被 <@{mid}> 占用！",
                    ephemeral=True,
                )
                return

        members[uid_key]["role"] = role
        members[uid_key]["ready"] = 0
        self.cog.raid_members[self.room_id] = members

        embed = self.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    async def _ready(self, interaction: discord.Interaction):
        uid_key = str(interaction.user.id)
        members = self.cog.raid_members.get(self.room_id, {})
        if uid_key not in members:
            await interaction.response.send_message("You are not in this room! / 你不在这个房间里！", ephemeral=True)
            return
        if members[uid_key].get("role") not in ("tank", "dps", "healer"):
            await interaction.response.send_message("请先选择定位！/ Select a role first!", ephemeral=True)
            return
        members[uid_key]["ready"] = 1
        self.cog.raid_members[self.room_id] = members
        embed = self.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    async def _leave(self, interaction: discord.Interaction):
        uid_key = str(interaction.user.id)
        members = self.cog.raid_members.get(self.room_id, {})
        if uid_key not in members:
            await interaction.response.send_message("You are not in this room! / 你不在这个房间里！", ephemeral=True)
            return

        del members[uid_key]
        if not members:
            self.cog.raid_members.pop(self.room_id, None)
            self.cog.raid_rooms.pop(self.room_id, None)
            embed = discord.Embed(description="队伍已解散 / Room disbanded.", color=0x999999)
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)
            return

        self.cog.raid_members[self.room_id] = members
        embed = self.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)


# ══════════════════════════════════════════════════════════════
# Raid Cog
# ══════════════════════════════════════════════════════════════
class RaidCog(CogBase):
    """MMORPG Raid 副本系统."""

    gmpt_raid_group = app_commands.Group(
        name="gmpt-raid",
        description="Raid 副本 / Raid Dungeon — 3人组队挑战Boss"
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        _init_tables()
        # In-memory state: room_id -> {owner_id, raid_id, status, channel_id, message_id}
        self.raid_rooms: dict[int, dict] = {}
        # room_id -> {user_id: {role, ready, stats}}
        self.raid_members: dict[int, dict] = {}

    # ══════════════════════════════════════════════════════════
    # /gmpt-raid create
    # ══════════════════════════════════════════════════════════
    @gmpt_raid_group.command(
        name="create",
        description="创建 Raid 队伍 / Create a Raid party"
    )
    @app_commands.describe(raid_id="Boss ID: infernal_dragon / void_walker / ancient_god")
    async def raid_create(self, interaction: discord.Interaction, raid_id: str):
        if raid_id not in RAID_BOSSES:
            valid = ", ".join(RAID_BOSSES.keys())
            return await interaction.response.send_message(
                f"Invalid Raid ID! Valid: {valid}\n无效 Raid ID！可选: {valid}", ephemeral=True)

        uid = str(interaction.user.id)
        boss = RAID_BOSSES[raid_id]
        user_stats = _get_full_stats(uid)
        if user_stats["level"] < boss["min_level"]:
            return await interaction.response.send_message(
                f"需要 Lv.{boss['min_level']}+ 才能挑战 {boss['name']}！你的等级: Lv.{user_stats['level']}\n"
                f"Requires Lv.{boss['min_level']}+ to challenge {boss['name']}! Your level: Lv.{user_stats['level']}",
                ephemeral=True,
            )

        # Check if user already in a room
        for rid, mems in self.raid_members.items():
            if uid in mems:
                return await interaction.response.send_message(
                    f"你已在房间 #{rid} 中，请先 `/gmpt-raid leave`！", ephemeral=True)

        room_id = len(self.raid_rooms) + 1
        self.raid_rooms[room_id] = {
            "owner_id": uid, "raid_id": raid_id, "status": "waiting",
            "channel_id": str(interaction.channel_id), "message_id": "",
        }
        self.raid_members[room_id] = {
            uid: {"role": "", "ready": 0}
        }

        view = RaidRoomView(self, room_id, uid, raid_id, uid)
        embed = view.build_embed()
        await interaction.response.send_message(
            content=f"<@{uid}> 创建了 Raid 队伍 #{room_id} — **{boss['emoji']} {boss['name']}**！\n"
                    f"使用 `/gmpt-raid join {room_id}` 加入队伍！",
            embed=embed, view=view,
        )

    # ══════════════════════════════════════════════════════════
    # /gmpt-raid join
    # ══════════════════════════════════════════════════════════
    @gmpt_raid_group.command(
        name="join",
        description="加入 Raid 队伍 / Join a Raid room"
    )
    @app_commands.describe(room_id="房间 ID / Room ID")
    async def raid_join(self, interaction: discord.Interaction, room_id: int):
        uid = str(interaction.user.id)
        room = self.raid_rooms.get(room_id)
        if not room:
            return await interaction.response.send_message("房间不存在 / Room not found!", ephemeral=True)
        if room["status"] != "waiting":
            return await interaction.response.send_message("该房间已开战 / Room already in battle!", ephemeral=True)

        members = self.raid_members.get(room_id, {})
        if len(members) >= 3:
            return await interaction.response.send_message("队伍已满 (3/3)！/ Party is full!", ephemeral=True)
        if uid in members:
            return await interaction.response.send_message("你已经在房间里了！/ You are already in this room!", ephemeral=True)

        # Check player's role is already set by checking if they have one
        boss = RAID_BOSSES.get(room["raid_id"], RAID_BOSSES["infernal_dragon"])
        user_stats = _get_full_stats(uid)
        if user_stats["level"] < boss["min_level"]:
            return await interaction.response.send_message(
                f"需要 Lv.{boss['min_level']}+ 才能挑战！你的等级: Lv.{user_stats['level']}", ephemeral=True)

        # Check if in another room
        for rid, mems in self.raid_members.items():
            if uid in mems and rid != room_id:
                return await interaction.response.send_message(
                    f"你已在房间 #{rid} 中，请先 `/gmpt-raid leave`！", ephemeral=True)

        members[uid] = {"role": "", "ready": 0}
        self.raid_members[room_id] = members

        view = RaidRoomView(self, room_id, room["owner_id"], room["raid_id"], uid)
        embed = view.build_embed()
        await interaction.response.send_message(
            content=f"<@{uid}> 加入了 Raid 队伍 #{room_id}！({len(members)}/3)",
            embed=embed, view=view,
        )

    # ══════════════════════════════════════════════════════════
    # /gmpt-raid start
    # ══════════════════════════════════════════════════════════
    @gmpt_raid_group.command(
        name="start",
        description="队长开战 / Start the Raid (Owner only)"
    )
    async def raid_start(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        # Find room owned by user
        room_id = None
        for rid, room in self.raid_rooms.items():
            if room["owner_id"] == uid and room["status"] == "waiting":
                room_id = rid
                break
        if not room_id:
            return await interaction.response.send_message("你没有等待中的房间 / No waiting room owned by you!",
                                                            ephemeral=True)

        members = self.raid_members.get(room_id, {})
        if len(members) < 3:
            return await interaction.response.send_message(
                f"需要 3 人才能开战！当前 {len(members)}/3\nNeed 3 players! Currently {len(members)}/3", ephemeral=True)

        # Check all roles filled
        roles = set()
        for mid, md in members.items():
            roles.add(md.get("role"))
        if "tank" not in roles or "dps" not in roles or "healer" not in roles:
            return await interaction.response.send_message(
                "需要 Tank/DPS/Healer 各 1 人！当前: " + ", ".join(sorted(roles)) + "\nNeed one of each role!",
                ephemeral=True)

        # Check all ready
        for mid, md in members.items():
            if not md.get("ready"):
                return await interaction.response.send_message(f"<@{mid}> 还未准备！/ not ready!", ephemeral=True)

        # Set status
        room = self.raid_rooms[room_id]
        room["status"] = "fighting"

        await interaction.response.send_message(
            f"⚔️ Raid #{room_id} 开始！**{RAID_BOSSES[room['raid_id']]['emoji']} {RAID_BOSSES[room['raid_id']]['name']}** 出现了！"
        )
        # Start battle loop in background
        self.bot.loop.create_task(self._raid_battle(room_id, interaction.channel))

    # ══════════════════════════════════════════════════════════
    # /gmpt-raid leave
    # ══════════════════════════════════════════════════════════
    @gmpt_raid_group.command(
        name="leave",
        description="退出 Raid 队伍 / Leave the Raid room"
    )
    async def raid_leave(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        found_room = None
        for rid, mems in self.raid_members.items():
            if uid in mems:
                found_room = rid
                break
        if not found_room:
            return await interaction.response.send_message("你不在任何房间里 / Not in any room.", ephemeral=True)

        room = self.raid_rooms.get(found_room, {})
        if room.get("status") == "fighting":
            return await interaction.response.send_message("战斗中无法退出！/ Cannot leave during battle!", ephemeral=True)

        del self.raid_members[found_room][uid]
        if not self.raid_members[found_room]:
            self.raid_members.pop(found_room, None)
            self.raid_rooms.pop(found_room, None)
            await interaction.response.send_message(f"你离开了房间 #{found_room}，房间已解散。")
        else:
            members = self.raid_members[found_room]
            owner_id = room.get("owner_id", "")
            if uid == owner_id:
                # Transfer ownership
                new_owner = next(iter(members.keys()))
                room["owner_id"] = new_owner
                self.raid_rooms[found_room] = room
                await interaction.response.send_message(
                    f"你离开了房间 #{found_room}，<@{new_owner}> 成为新房主。")
            else:
                await interaction.response.send_message(f"你离开了房间 #{found_room}。({len(members)}/3)")

    # ══════════════════════════════════════════════════════════
    # Raid Battle Engine
    # ══════════════════════════════════════════════════════════
    async def _raid_battle(self, room_id: int, channel):
        room = self.raid_rooms.get(room_id)
        if not room:
            return
        boss_def = RAID_BOSSES[room["raid_id"]]
        members = self.raid_members.get(room_id, {})

        # Initialize player combat states with full stats
        players = {}
        for mid, md in members.items():
            stats = _get_full_stats(mid)
            role = md["role"]
            p_state = {
                "hp": stats["hp"],
                "max_hp": stats["max_hp"],
                "atk": stats["atk"],
                "def": stats["def"],
                "crit": stats.get("crit", 0),
                "spd": stats.get("spd", 0),
                "role": role,
                "alive": True,
                "aggro": 0,
                "total_dmg": 0,
                "total_heal": 0,
            }
            # Role multipliers
            if role == "tank":
                p_state["def"] = int(p_state["def"] * 1.5)
            elif role == "dps":
                p_state["atk"] = int(p_state["atk"] * 1.3)
            players[mid] = p_state

        # Boss state
        boss = {
            "name": boss_def["name"],
            "emoji": boss_def["emoji"],
            "hp": boss_def["hp"],
            "max_hp": boss_def["hp"],
            "atk": boss_def["atk"],
            "def": boss_def["def"],
            "base_atk": boss_def["atk"],
            "base_def": boss_def["def"],
            "enraged": False,
            "frenzy": False,
        }

        boss_70_triggered = False
        boss_30_triggered = False
        boss_10_triggered = False

        # Send battle start embed
        embed = self._build_battle_embed(players, boss, 0, "")
        battle_msg = await channel.send(embed=embed)

        for turn in range(1, MAX_TURNS + 1):
            # Check win/lose conditions
            if boss["hp"] <= 0:
                break
            alive_players = [mid for mid, p in players.items() if p["alive"]]
            if not alive_players:
                break

            turn_log = []

            # ── Boss phase triggers ──
            hp_pct = boss["hp"] / boss["max_hp"]
            if hp_pct <= 0.3 and not boss_30_triggered:
                boss_30_triggered = True
                aoe_dmg = int(boss["atk"] * 0.6)
                turn_log.append(f"💥 **{boss['emoji']} {boss['name']}** releases AOE attack! / 释放范围攻击！全员受伤 {aoe_dmg}！")
                for mid, p in players.items():
                    if p["alive"]:
                        dmg = max(1, aoe_dmg - p["def"] // 2)
                        p["hp"] = max(0, p["hp"] - dmg)

            if hp_pct <= 0.7 and not boss_70_triggered:
                boss_70_triggered = True
                boss["atk"] = int(boss["atk"] * 1.2)
                boss["enraged"] = True
                turn_log.append(f"😡 **{boss['emoji']} {boss['name']}** goes into RAGE mode! ATK +20%! / 进入狂暴状态！攻击力+20%！")

            if hp_pct <= 0.1 and not boss_10_triggered:
                boss_10_triggered = True
                boss["atk"] = int(boss["atk"] * 1.4)
                boss["def"] = int(boss["def"] * 0.5)
                boss["frenzy"] = True
                turn_log.append(f"🔥 **{boss['emoji']} {boss['name']}** enters DEATH FRENZY! ATK +40%, DEF -50%! / 濒死狂暴！")

            # ── Players attack each turn ──
            for mid, p in players.items():
                if not p["alive"]:
                    continue
                # Aggro accumulation
                if p["role"] == "tank":
                    p["aggro"] += 2
                elif p["role"] == "dps":
                    p["aggro"] += 3
                else:
                    p["aggro"] += 1

                # Calculate damage
                base_dmg = p["atk"]
                dmg = max(1, base_dmg + random.randint(-5, 10) - boss["def"] // 3)
                # Crit check
                if p["crit"] > 0 and random.randint(1, 100) <= p["crit"]:
                    dmg = int(dmg * 2.0)
                    turn_log.append(f"💥 <@{mid}> **CRIT!** {dmg} DMG! / 暴击！")
                else:
                    turn_log.append(f"⚔️ <@{mid}> attacks — **{dmg}** DMG!")

                boss["hp"] = max(0, boss["hp"] - dmg)
                p["total_dmg"] += dmg

                # Healer passive: every 3 turns heal all
                if p["role"] == "healer" and turn % 3 == 0:
                    heal_val = int(p["atk"] * 0.5)
                    for pid2, p2 in players.items():
                        if p2["alive"]:
                            healed = min(heal_val, p2["max_hp"] - p2["hp"])
                            p2["hp"] += healed
                    p["total_heal"] += heal_val
                    turn_log.append(f"💚 <@{mid}> heals party **{heal_val}** HP! / 全队恢复 {heal_val} HP！")

                if boss["hp"] <= 0:
                    break

            # ── Boss attacks ──
            if boss["hp"] > 0:
                alive_players = [mid for mid, p in players.items() if p["alive"]]
                if alive_players:
                    # Target: highest aggro alive
                    alive_sorted = sorted(alive_players, key=lambda mid: players[mid]["aggro"], reverse=True)
                    target_id = alive_sorted[0]
                    target = players[target_id]
                    boss_dmg = max(1, boss["atk"] + random.randint(-10, 10) - target["def"] // 2)
                    target["hp"] = max(0, target["hp"] - boss_dmg)
                    turn_log.append(f"👊 **{boss['emoji']} {boss['name']}** attacks <@{target_id}> — **{boss_dmg}** DMG"
                                    f" (仇恨: {target['aggro']})")
                    if target["hp"] <= 0:
                        target["alive"] = False
                        turn_log.append(f"💀 <@{target_id}> has fallen! / 倒下了！")

            # Update battle embed
            embed = self._build_battle_embed(players, boss, turn, "\n".join(turn_log))
            try:
                await battle_msg.edit(embed=embed)
            except (discord.NotFound, discord.HTTPException):
                battle_msg = await channel.send(embed=embed)

            await asyncio.sleep(2)

        # ── Battle End ──
        await self._end_raid_battle(room_id, players, boss, channel, battle_msg)

    def _build_battle_embed(self, players: dict, boss: dict, turn: int, log: str) -> discord.Embed:
        hp_pct = boss["hp"] / boss["max_hp"]
        if hp_pct > 0.5:
            color = 0x00FF00
        elif hp_pct > 0.25:
            color = 0xFFA500
        else:
            color = 0xFF0000

        embed = discord.Embed(
            title=f"{boss['emoji']} {boss['name']} — Turn {turn}/{MAX_TURNS}",
            color=color,
        )
        status_tags = []
        if boss.get("enraged"):
            status_tags.append("😡 Enraged")
        if boss.get("frenzy"):
            status_tags.append("🔥 Death Frenzy")

        boss_hp_bar = progress_bar(boss["hp"], boss["max_hp"], 20)
        embed.add_field(
            name=f"Boss {' '.join(status_tags)}" if status_tags else "Boss",
            value=f"❤️ HP: {boss_hp_bar}\n⚔️ ATK: {boss['atk']} | 🛡️ DEF: {boss['def']}",
            inline=False,
        )

        for mid, p in players.items():
            hp_bar = progress_bar(p["hp"], p["max_hp"], 10)
            status = ""
            if not p["alive"]:
                status = " 💀DEAD"
            embed.add_field(
                name=f"{ROLE_EMOJIS.get(p['role'], '?')} <@{mid}>{status}",
                value=f"❤️ {hp_bar} | 🗡️ {p['total_dmg']} DMG | 😡 Aggro: {p['aggro']}",
                inline=True,
            )

        if log:
            embed.set_footer(text=log[:2048])
        return embed

    async def _end_raid_battle(self, room_id: int, players: dict, boss: dict, channel, msg):
        room = self.raid_rooms.get(room_id, {})
        boss_def = RAID_BOSSES.get(room.get("raid_id", ""), RAID_BOSSES.get("infernal_dragon", {}))

        alive = [mid for mid, p in players.items() if p["alive"]]
        victory = boss["hp"] <= 0

        embed = discord.Embed(
            title=f"Raid #{room_id} — {'VICTORY / 胜利！' if victory else 'DEFEAT / 失败...'}",
            color=0xF1C40F if victory else 0x999999,
        )

        if victory:
            embed.description = f"**{boss['emoji']} {boss['name']}** 已被击败！/ Defeated!"
            # Distribute rewards
            gold = boss_def.get("rewards_gold", 500)
            for mid in alive:
                add_coins(mid, gold, f"Raid: 击败 {boss_def.get('name', 'Boss')}")
                embed.add_field(
                    name=f"<@{mid}> +{gold}G",
                    value=f"🗡️ {players[mid]['total_dmg']} DMG | 💚 {players[mid].get('total_heal', 0)} Heal",
                    inline=True,
                )

            # Title reward
            if boss_def.get("rewards_title"):
                embed.add_field(
                    name="称号 / Title Unlocked",
                    value=f"**{boss_def['rewards_title']}** — 全员获得 / earned by all!",
                    inline=False,
                )
                for mid in alive:
                    try:
                        with get_db_ctx() as conn:
                            cur = conn.cursor()
                            cur.execute(
                                "INSERT OR IGNORE INTO mmorpg_titles (user_id, title_name, unlocked_at) VALUES (?, ?, datetime('now'))",
                                (mid, boss_def['rewards_title']),
                            )
                            conn.commit()
                    except Exception:
                        pass
        else:
            embed.description = f"全员阵亡... {boss['emoji']} {boss['name']} 战胜了你们！/ Total party wipe!"
            embed.add_field(name="存活 0 人 / 0 survived", value="重整旗鼓，再战吧！/ Try again!", inline=False)

        try:
            await msg.edit(embed=embed)
        except (discord.NotFound, discord.HTTPException):
            await channel.send(embed=embed)

        # Save stats and cleanup
        for mid, p in players.items():
            _save_stats(mid, p)

        self.raid_members.pop(room_id, None)
        self.raid_rooms.pop(room_id, None)


# ══════════════════════════════════════════════════════════════
# Setup
# ══════════════════════════════════════════════════════════════
async def setup(bot):
    await bot.add_cog(RaidCog(bot))
