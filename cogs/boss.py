"""
GMPT Bot — MMORPG Boss 多人团战系统 / Multiplayer Boss Raid
/gmpt-boss create     — 创建Boss房间
/gmpt-boss join       — 加入房间
/gmpt-boss attack     — 攻击Boss（可选技能）
/gmpt-boss use-potion — 战斗中使用药水
/gmpt-boss invite     — 邀请成员
/gmpt-boss kick       — 踢出成员
/gmpt-boss status     — 查看战况
/gmpt-boss dungeon    — 副本列表
/gmpt-boss leaderboard— 排行榜
/gmpt-boss stats      — 个人统计
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
from cogs.economy import get_balance, add_coins
from cogs.mmorpg_skills import SKILLS
import logging

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Boss / Dungeon definitions
# ══════════════════════════════════════════════════════════════

BOSS_TYPES = {
    "金龙": {
        "name": "金龙",
        "emoji": "🐉",
        "desc": "Gold Dragon — 喷吐金色火焰！",
        "base_hp": (600, 1000),
        "base_atk": (25, 55),
        "skills": ["龙息", "龙尾扫", "金币雨"],
        "rage_skill": "🔥 龙神之怒！伤害×2",
        "loot_table": [
            (0.15, "龙鳞碎片", 300), (0.10, "金龙宝珠", 800),
            (0.05, "龙牙项链", 2000), (0.02, "金龙坐骑碎片", 5000),
        ],
        "cooldown_min": {"简单": 5, "普通": 15, "困难": 30},
    },
    "暗影领主": {
        "name": "暗影领主",
        "emoji": "👹",
        "desc": "Shadow Lord — 暗影之力笼罩战场！",
        "base_hp": (600, 1000),
        "base_atk": (25, 55),
        "skills": ["暗影斩", "黑洞", "恐惧凝视"],
        "rage_skill": "🌑 无尽暗影！全体伤害",
        "loot_table": [
            (0.15, "暗影碎片", 350), (0.10, "暗影之心", 900),
            (0.05, "暗影披风", 2200), (0.02, "暗影王冠", 5500),
        ],
        "cooldown_min": {"简单": 5, "普通": 15, "困难": 30},
    },
    "冰霜巨人": {
        "name": "冰霜巨人",
        "emoji": "🧊",
        "desc": "Frost Giant — 冻结一切！",
        "base_hp": (600, 1000),
        "base_atk": (25, 55),
        "skills": ["冰锥", "暴风雪", "永冻"],
        "rage_skill": "❄️ 绝对零度！攻击附带冰冻",
        "loot_table": [
            (0.15, "冰晶碎片", 400), (0.10, "冰霜核心", 1000),
            (0.05, "冰封之盾", 2500), (0.02, "永冻王冠", 6000),
        ],
        "cooldown_min": {"简单": 5, "普通": 15, "困难": 30},
    },
    "地狱犬": {
        "name": "地狱犬",
        "emoji": "🔥",
        "desc": "Hellhound — 三头地狱犬喷吐烈焰！",
        "base_hp": (600, 1000),
        "base_atk": (25, 55),
        "skills": ["三重撕咬", "地狱火", "咆哮"],
        "rage_skill": "💥 地狱烈焰！全体灼烧",
        "loot_table": [
            (0.15, "地狱火碎片", 450), (0.10, "地狱核心", 1100),
            (0.05, "地狱护符", 2800), (0.02, "三头犬缰绳", 7000),
        ],
        "cooldown_min": {"简单": 5, "普通": 15, "困难": 30},
    },
}

DIFFICULTY = {
    "简单": {"label": "Easy / 简单", "hp_mult": 1.0, "atk_mult": 0.7, "reward_mult": 0.5, "color": 0x2ECC71, "stars": "⭐"},
    "普通": {"label": "Normal / 普通", "hp_mult": 2.0, "atk_mult": 1.0, "reward_mult": 1.0, "color": 0xF39C12, "stars": "⭐⭐"},
    "困难": {"label": "Hard / 困难", "hp_mult": 4.0, "atk_mult": 1.5, "reward_mult": 2.0, "color": 0xE74C3C, "stars": "⭐⭐⭐"},
}

RAGE_HP_RATIO = 0.5

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


def _format_bar(current: int, maximum: int, length: int = 10, filled: str = "▰", empty: str = "▱") -> str:
    ratio = max(0, min(1, current / max(1, maximum)))
    f = int(ratio * length)
    e = length - f
    return filled * f + empty * e + f" {current}/{maximum}"


class BossCog(CogBase):
    """MMORPG 多人团战系统 / Multiplayer Boss Raid"""

    gmpt_boss_group = app_commands.Group(
        name="gmpt-boss",
        description="MMORPG Boss团战 / Boss Raid — 组队挑战"
    )

    def __init__(self, bot):
        self.bot = bot
        # room_id = f"{channel_id}_{message_id}"
        self.rooms: dict[str, dict] = {}
        self.boss_lock = asyncio.Lock()

    # ══════════════════════════════════════════════════════════
    # Autocomplete: equipped skills for attack command
    # ══════════════════════════════════════════════════════════

    async def _skill_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        uid = str(interaction.user.id)
        skills = _get_equipped_skills(uid)
        choices = []
        for s in skills:
            display = f"{s['emoji']} {s['name']} (MP:{s['mp_cost']})"
            choices.append(app_commands.Choice(name=display, value=s["skill_id"]))
        # Add "普通攻击" option
        choices.insert(0, app_commands.Choice(name="⚔️ 普通攻击", value="__normal__"))
        if current:
            choices = [c for c in choices if current.lower() in c.name.lower()]
        return choices[:25]

    async def _potion_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        uid = str(interaction.user.id)
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT item_name FROM user_inventory WHERE user_id = ? AND item_type = 'potion' AND quantity > 0",
                (uid,),
            )
            rows = cur.fetchall()
        names = [r["item_name"] for r in rows]
        if current:
            names = [n for n in names if current.lower() in n.lower()]
        return [app_commands.Choice(name=n, value=n) for n in names[:25]]

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss dungeon
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="dungeon",
        description="查看所有副本Boss与冷却 / View all dungeon bosses & cooldowns"
    )
    async def boss_dungeon(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        embed = discord.Embed(
            title="🏰 副本大厅 / Dungeon Hall",
            description="选择 Boss 发起挑战！所有冷却按难度独立计算",
            color=0x9B59B6,
        )
        for boss_name, boss in BOSS_TYPES.items():
            lines = []
            for diff, diff_cfg in DIFFICULTY.items():
                remaining = self._get_cooldown_remaining(uid, boss_name, diff)
                if remaining <= 0:
                    status = "✅ 可挑战 / Ready"
                else:
                    m, s = divmod(remaining, 60)
                    status = f"⏳ {m}分{s}秒 / Cooling down"
                lines.append(f"{diff_cfg['stars']} {diff}: {status}")
            lines.append(f"掉落: {', '.join(f'{name}({val}₲)' for _, name, val in boss['loot_table'][:2])}")
            embed.add_field(
                name=f"{boss['emoji']} {boss_name}",
                value="\n".join(lines),
                inline=True,
            )
        embed.set_footer(text="使用 /gmpt-boss create <Boss> <难度> 创建副本")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss leaderboard
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="leaderboard",
        description="Boss击杀排行榜 / Boss kill leaderboard"
    )
    @app_commands.describe(
        boss_type="Boss类型 (留空显示全部)",
        difficulty="难度 (留空显示全部)",
    )
    async def boss_leaderboard(
        self,
        interaction: discord.Interaction,
        boss_type: str = None,
        difficulty: str = None,
    ):
        embed = discord.Embed(title="🏆 Boss排行榜 / Boss Leaderboard", color=0xF1C40F)
        with get_db_ctx() as conn:
            cur = conn.cursor()
            if boss_type:
                query = """
                    SELECT user_id, boss_name, difficulty, kills, top_damage, last_kill_at
                    FROM boss_player_kills WHERE boss_name = ?
                """
                params = [boss_type]
                if difficulty:
                    query += " AND difficulty = ?"
                    params.append(difficulty)
                query += " ORDER BY kills DESC, top_damage DESC LIMIT 10"
                cur.execute(query, params)
                rows = cur.fetchall()
                embed.title += f" — {boss_type}" + (f" ({difficulty})" if difficulty else "")
                if not rows:
                    embed.description = "暂无击杀记录 / No kills yet."
                else:
                    lines = []
                    for i, row in enumerate(rows, 1):
                        uid, bname, diff, kills, top_dmg, _ = row
                        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"#{i}")
                        lines.append(f"{medal} <@{uid}> — {kills}杀 {diff} | 最高{top_dmg}伤害")
                    embed.description = "\n".join(lines)
            else:
                cur.execute("""
                    SELECT boss_name, difficulty, kill_count, fastest_clear_seconds, first_clear_by
                    FROM boss_kill_stats ORDER BY kill_count DESC LIMIT 12
                """)
                rows = cur.fetchall()
                if not rows:
                    embed.description = "暂无击杀记录 / No kills yet."
                else:
                    for bname, diff, kills, fastest, first_clearer in rows:
                        fastest_str = f"{fastest:.0f}s" if fastest else "-"
                        embed.add_field(
                            name=f"{bname} {DIFFICULTY.get(diff, {}).get('stars', '')} {diff}",
                            value=f"击杀: {kills} | 最快: {fastest_str} | 首杀: <@{first_clearer}>",
                            inline=True,
                        )
        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss stats
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="stats",
        description="查看个人Boss统计 / Personal boss stats"
    )
    async def boss_stats(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        embed = discord.Embed(
            title=f"📊 {interaction.user.display_name} 的副本统计 / Dungeon Stats",
            color=0x3498DB,
        )
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT boss_name, difficulty, kills, top_damage, last_kill_at
                FROM boss_player_kills WHERE user_id = ?
                ORDER BY kills DESC
            """, (uid,))
            rows = cur.fetchall()
        if not rows:
            embed.description = "尚未击杀任何Boss / No boss kills yet."
        else:
            total_kills = sum(r[2] for r in rows)
            embed.description = f"总计击杀: **{total_kills}**"
            for boss_name, diff, kills, top_dmg, _ in rows:
                embed.add_field(
                    name=f"{BOSS_TYPES.get(boss_name, {}).get('emoji', '')} {boss_name} ({diff})",
                    value=f"击杀: {kills} | 最高伤害: {top_dmg}",
                    inline=True,
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss create
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="create",
        description="创建副本Boss房间 / Create dungeon boss room"
    )
    @app_commands.describe(
        boss_type="Boss: 金龙 / 暗影领主 / 冰霜巨人 / 地狱犬",
        difficulty="难度: 简单 / 普通 / 困难",
    )
    async def boss_create(
        self,
        interaction: discord.Interaction,
        boss_type: str = "金龙",
        difficulty: str = "普通",
    ):
        chid = str(interaction.channel_id)
        uid = str(interaction.user.id)

        # Check existing room in channel
        for rid, room in self.rooms.items():
            if room.get("channel_id") == chid and room.get("status") in ("waiting", "fighting"):
                return await interaction.response.send_message(
                    "本频道已有进行中的 Boss 战！/ Boss battle already in progress!", ephemeral=True)

        if boss_type not in BOSS_TYPES:
            types_str = " / ".join(BOSS_TYPES.keys())
            return await interaction.response.send_message(
                f"无效Boss！可选: {types_str}", ephemeral=True)

        if difficulty not in DIFFICULTY:
            diffs = " / ".join(DIFFICULTY.keys())
            return await interaction.response.send_message(
                f"无效难度！可选: {diffs}", ephemeral=True)

        # Check personal cooldown
        cd = self._get_cooldown_remaining(uid, boss_type, difficulty)
        if cd > 0:
            m, s = divmod(cd, 60)
            return await interaction.response.send_message(
                f"⏳ 冷却中！{m}分{s}秒后可挑战", ephemeral=True)

        boss = BOSS_TYPES[boss_type]
        diff = DIFFICULTY[difficulty]
        base_hp = random.randint(*boss["base_hp"])
        max_hp = int(base_hp * diff["hp_mult"])
        atk = int(random.randint(*boss["base_atk"]) * diff["atk_mult"])

        # Get host combat stats
        stats = _get_user_combat_stats(uid)

        room_id = f"{chid}_{int(time.time())}"

        room = {
            "room_id": room_id,
            "channel_id": chid,
            "host_id": uid,
            "boss": boss,
            "boss_hp": max_hp,
            "boss_max_hp": max_hp,
            "boss_atk": atk,
            "phase": 1,
            "difficulty": difficulty,
            "diff_label": diff["label"],
            "diff_color": diff["color"],
            "reward_mult": diff["reward_mult"],
            "status": "waiting",
            "turn": 0,
            "start_time": time.time(),
            "players": {},
            "loot_log": [],
        }

        room["players"][uid] = {
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
            "username": interaction.user.display_name,
        }

        self.rooms[room_id] = room

        embed = self._build_room_embed(room)
        await interaction.response.send_message(
            f"{boss['emoji']} **{interaction.user.display_name}** 创建了 Boss 团战房间！\n"
            f"60秒内 `/gmpt-boss join` 加入 | 队长可使用 `/gmpt-boss invite` 邀请成员",
            embed=embed,
        )

        # Start timer
        self.bot.loop.create_task(self._boss_start_timer(room_id, interaction.channel))

    async def _boss_start_timer(self, room_id: str, channel):
        await asyncio.sleep(60)
        room = self.rooms.get(room_id)
        if not room or room["status"] != "waiting":
            return
        if len(room["players"]) < 1:
            room["status"] = "finished"
            await channel.send("⏰ 副本已取消（无玩家加入）/ Dungeon cancelled (no players).")
            return
        room["status"] = "fighting"
        room["start_time"] = time.time()
        alive = sum(1 for p in room["players"].values() if p["hp"] > 0)
        await channel.send(
            f"⚔️ **副本开始！/ Dungeon begins!**\n"
            f"玩家数: {len(room['players'])} | 存活: {alive}\n"
            f"使用 `/gmpt-boss attack` 攻击！使用 `/gmpt-boss use-potion` 喝药水！"
        )

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss join
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="join",
        description="加入副本 / Join dungeon"
    )
    async def boss_join(self, interaction: discord.Interaction):
        chid = str(interaction.channel_id)
        uid = str(interaction.user.id)

        room = self._find_room_by_channel(chid)
        if not room:
            return await interaction.response.send_message("本频道无进行中的副本 / No active dungeon.", ephemeral=True)

        if uid in room["players"]:
            return await interaction.response.send_message("你已经加入了！/ You already joined!", ephemeral=True)

        if room["status"] == "fighting":
            # Late join during fight – allowed but starts with current in-memory HP
            pass

        cd = self._get_cooldown_remaining(uid, room["boss"]["name"], room["difficulty"])
        if cd > 0:
            m, s = divmod(cd, 60)
            return await interaction.response.send_message(
                f"⏳ 该Boss冷却中！{m}分{s}秒后可加入", ephemeral=True)

        stats = _get_user_combat_stats(uid)
        room["players"][uid] = {
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
            "username": interaction.user.display_name,
        }

        embed = self._build_room_embed(room)
        await interaction.response.send_message(
            f"✅ **{interaction.user.display_name}** 加入了副本！/ Joined!",
            embed=embed,
        )

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss invite
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="invite",
        description="邀请成员加入副本 / Invite a member to the dungeon"
    )
    @app_commands.describe(member="要邀请的成员 / Member to invite")
    async def boss_invite(self, interaction: discord.Interaction, member: discord.Member):
        chid = str(interaction.channel_id)
        uid = str(interaction.user.id)

        room = self._find_room_by_channel(chid)
        if not room:
            return await interaction.response.send_message("本频道无进行中的副本 / No active dungeon.", ephemeral=True)

        if uid != room["host_id"]:
            return await interaction.response.send_message("只有队长可以邀请成员！/ Only the host can invite!", ephemeral=True)

        if room["status"] not in ("waiting", "fighting"):
            return await interaction.response.send_message("战斗已结束，无法邀请 / Battle already finished.", ephemeral=True)

        target_id = str(member.id)
        if target_id in room["players"]:
            return await interaction.response.send_message(f"{member.display_name} 已经在副本中了！", ephemeral=True)

        try:
            invite_embed = discord.Embed(
                title=f"{room['boss']['emoji']} Boss 团战邀请！",
                description=f"**{interaction.user.display_name}** 邀请你加入副本！\n"
                           f"Boss: **{room['boss']['name']}** | 难度: **{room['difficulty']}**\n"
                           f"前往 {interaction.channel.mention} 使用 `/gmpt-boss join` 加入！",
                color=room["diff_color"],
            )
            await member.send(embed=invite_embed)
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            f"📨 已向 {member.mention} 发送邀请！\nInvitation sent to {member.display_name}!"
        )

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss kick
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="kick",
        description="踢出成员 / Kick a member from the dungeon"
    )
    @app_commands.describe(member="要踢出的成员 / Member to kick")
    async def boss_kick(self, interaction: discord.Interaction, member: discord.Member):
        chid = str(interaction.channel_id)
        uid = str(interaction.user.id)

        room = self._find_room_by_channel(chid)
        if not room:
            return await interaction.response.send_message("本频道无进行中的副本 / No active dungeon.", ephemeral=True)

        if uid != room["host_id"]:
            return await interaction.response.send_message("只有队长可以踢人！/ Only the host can kick!", ephemeral=True)

        if room["status"] != "waiting":
            return await interaction.response.send_message("只能在等待阶段踢人！/ Can only kick during waiting phase!", ephemeral=True)

        target_id = str(member.id)
        if target_id not in room["players"]:
            return await interaction.response.send_message(f"{member.display_name} 不在副本中！", ephemeral=True)

        if target_id == uid:
            return await interaction.response.send_message("不能踢自己！/ Cannot kick yourself!", ephemeral=True)

        del room["players"][target_id]
        await interaction.response.send_message(f"👢 **{member.display_name}** 已被移出副本！/ Kicked from dungeon!")

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss attack
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="attack",
        description="攻击Boss（可选技能）/ Attack boss (optional skill)"
    )
    @app_commands.describe(skill_id="技能（留空=普通攻击）/ Skill (leave empty = normal attack)")
    @app_commands.autocomplete(skill_id=_skill_autocomplete)
    @app_commands.checks.cooldown(1, 8.0, key=lambda i: i.user.id)
    async def boss_attack(
        self,
        interaction: discord.Interaction,
        skill_id: str = None,
    ):
        chid = str(interaction.channel_id)
        uid = str(interaction.user.id)

        room = self._find_room_by_channel(chid)
        if not room:
            return await interaction.response.send_message("本频道没有进行中的副本 / No active dungeon.", ephemeral=True)

        if room["status"] == "waiting":
            return await interaction.response.send_message("副本尚未开始！请等待 / Dungeon hasn't started yet!", ephemeral=True)

        if room["status"] == "finished":
            return await interaction.response.send_message("副本已结束 / Dungeon already finished.", ephemeral=True)

        if uid not in room["players"]:
            return await interaction.response.send_message("请先 `/gmpt-boss join` 加入 / Join first!", ephemeral=True)

        player = room["players"][uid]
        if player["hp"] <= 0:
            return await interaction.response.send_message("你已阵亡！等待副本结束 / You are dead!", ephemeral=True)

        use_skill = False
        skill_def = None
        if skill_id and skill_id != "__normal__":
            if skill_id not in SKILLS:
                return await interaction.response.send_message("技能不存在 / Skill not found.", ephemeral=True)
            skill_def = SKILLS[skill_id]
            # Check if player has this skill equipped
            equipped = _get_equipped_skills(uid)
            equipped_ids = [s["skill_id"] for s in equipped]
            if skill_id not in equipped_ids:
                return await interaction.response.send_message("你还没有装备这个技能！/ Skill not equipped!", ephemeral=True)
            if player["mp"] < skill_def["mp_cost"]:
                return await interaction.response.send_message(
                    f"MP 不足！需要 {skill_def['mp_cost']} MP，当前 {player['mp']} MP", ephemeral=True)
            player["mp"] -= skill_def["mp_cost"]
            use_skill = True

        # ═══ Phase check ═══
        if room["boss_hp"] <= room["boss_max_hp"] * RAGE_HP_RATIO and room["phase"] == 1:
            room["phase"] = 2
            room["boss_atk"] = int(room["boss_atk"] * 1.5)

        # ═══ Pre-attack: tick dot on boss ═══
        dot_log = ""
        if player["dot_dmg"] > 0 and player["dot_turns"] > 0:
            dot_log = f"☠️ Boss受到 {player['dot_dmg']} 毒伤！"
            room["boss_hp"] = max(0, room["boss_hp"] - player["dot_dmg"])
            player["dot_turns"] -= 1
            if player["dot_turns"] <= 0:
                player["dot_dmg"] = 0

        # ═══ Check frozen ═══
        if player["frozen"]:
            player["frozen"] = False
            lines = [
                f"❄️ **{player['username']}** 被冻结，跳过本回合！/ Frozen! Turn skipped.",
            ]
            # Boss still counter-attacks
            boss_log = self._boss_aoe_attack(room)
            lines.append(boss_log)
            await interaction.response.send_message("\n".join(lines))
            return

        # ═══ Calculate damage ═══
        dmg = 0
        dmg_text = ""

        if use_skill:
            skill_dmg = skill_def.get("damage", 0)
            heal_val = skill_def.get("heal", 0)
            buff_atk = skill_def.get("buff_atk", 0)
            buff_def = skill_def.get("buff_def", 0)
            dot_val = skill_def.get("dot", 0)
            dot_dur = skill_def.get("dot_duration", 0)
            duration = skill_def.get("duration", 3)

            if skill_id == "fireball":
                dmg = 35
                dmg_text = f"🔥 **火球术！** — {dmg} 伤害"
            elif skill_id == "ice_shard":
                dmg = 25
                dmg_text = f"❄️ **冰锥术！** — {dmg} 伤害"
                if random.random() < 0.3:
                    room["players"][uid]["frozen_effect"] = True  # mark boss gets frozen-like
                    dmg_text += " | 🧊 Boss 被冻结一回合！"
            elif skill_id == "thunder":
                dmg = 50
                dmg_text = f"⚡ **雷霆一击！** — {dmg} 伤害"
                if random.random() < 0.1:
                    self_dmg = int(dmg * 0.3)
                    player["hp"] = max(0, player["hp"] - self_dmg)
                    dmg_text += f" | ⚡ 反噬！自己受到 {self_dmg} 伤害"
            elif skill_id == "heal":
                healed = min(heal_val, player["max_hp"] - player["hp"])
                player["hp"] += healed
                dmg_text = f"💚 **治愈术！** 恢复了 {healed} HP（{player['hp']}/{player['max_hp']}）"
                dmg = 0
            elif skill_id == "berserk":
                player["buff_atk"] += 20
                player["buff_atk_turns"] = duration
                dmg_text = f"😡 **狂暴！** 攻击力 +20，持续 {duration} 回合"
                dmg = 0
            elif skill_id == "shield":
                player["buff_def"] += 15
                player["buff_def_turns"] = duration
                dmg_text = f"🛡️ **圣盾术！** 防御力 +15，持续 {duration} 回合"
                dmg = 0
            elif skill_id == "poison":
                # Apply dot to boss (stored on player for tracking)
                player["dot_dmg"] = dot_val
                player["dot_turns"] = dot_dur
                dmg_text = f"☠️ **毒雾！** Boss 中毒，每回合扣 {dot_val} HP，持续 {dot_dur} 回合"
                dmg = 0
            elif skill_id == "steal":
                dmg_text = "💰 偷窃只对玩家有效，无法对 Boss 使用！"
                dmg = 0
            else:
                dmg = skill_dmg
                dmg_text = f"{skill_def['emoji']} **{skill_def['name']}！** — {dmg} 伤害"
        else:
            # Normal attack
            base_atk = player["atk"] + player["buff_atk"]
            dmg = base_atk + random.randint(1, 10)
            # Critical check
            if random.random() < 0.1:
                dmg = int(dmg * 2)
                dmg_text = f"⚔️ {player['username']} 暴击！— **{dmg}** 伤害"
            else:
                dmg_text = f"⚔️ {player['username']} 普通攻击 — {dmg} 伤害"

        # Apply damage
        if dmg > 0:
            room["boss_hp"] = max(0, room["boss_hp"] - dmg)
            player["damage_dealt"] += dmg

        room["turn"] += 1

        # ═══ Decrement buff turns ═══
        if player["buff_atk_turns"] > 0:
            player["buff_atk_turns"] -= 1
            if player["buff_atk_turns"] <= 0:
                player["buff_atk"] = 0
        if player["buff_def_turns"] > 0:
            player["buff_def_turns"] -= 1
            if player["buff_def_turns"] <= 0:
                player["buff_def"] = 0

        # ═══ Boss AOE counter-attack ═══
        boss_log = self._boss_aoe_attack(room)

        lines = [dmg_text]
        if dot_log:
            lines.append(dot_log)

        # Phase 2 announcement
        if room["phase"] == 2:
            phase_lines = [
                "",
                f"⚡ **Boss 进入第二阶段！变得更强了！** （攻击力 x1.5）",
                f"Boss HP 已回复至 {room['boss_max_hp']}！",
            ]
            # Reset boss HP to max on phase 2 entry
            if room["boss_hp"] > 0 and room.get("_phase2_announced") != room_id:
                room["boss_hp"] = room["boss_max_hp"]
                room["_phase2_announced"] = room_id
                lines.extend(phase_lines)

        lines.append(boss_log)

        # HP bar
        lines.append(f"Boss HP: {_format_bar(room['boss_hp'], room['boss_max_hp'])}")
        if room["phase"] == 2:
            lines.append(f"⚠️ 阶段: **Phase 2** | 回合: {room['turn']}")

        # ═══ Check boss death ═══
        if room["boss_hp"] <= 0:
            room["status"] = "finished"
            duration_sec = time.time() - room["start_time"]
            lines.append("")
            lines.append(f"🎉 **{room['boss']['name']} 被击败！/ Defeated!** ({duration_sec:.0f}s)")

            # Distribute rewards
            reward_lines = self._distribute_rewards(room, duration_sec)
            lines.append("\n**💰 奖励分配 / Rewards:**")
            lines.extend(reward_lines)

        await interaction.response.send_message("\n".join(lines))

        if room["status"] == "finished":
            embed = self._build_room_embed(room, defeated=True)
            await interaction.channel.send(embed=embed)
            # Save final HP/MP states
            for pid, pdata in room["players"].items():
                _save_combat_stats(pid, pdata)

    def _boss_aoe_attack(self, room: dict) -> str:
        """Boss AOE counter-attack against all alive players."""
        players = room["players"]
        boss_atk = room["boss_atk"]
        num_players = len(players)
        aoe_base = int(boss_atk * (1 + 0.1 * num_players))
        phase_tag = " (Phase 2 🔥)" if room["phase"] == 2 else ""

        log_parts = [f"\n{room['boss']['emoji']} Boss 反击全体{phase_tag}！"]

        for pid, pdata in players.items():
            if pdata["hp"] <= 0:
                continue
            # Random defense reduction
            def_reduce = random.randint(0, pdata["def"] + pdata["buff_def"])
            actual_dmg = max(1, aoe_base - def_reduce)
            pdata["hp"] = max(0, pdata["hp"] - actual_dmg)
            status = ""
            if pdata["hp"] <= 0:
                status = " 💀 阵亡！"
            log_parts.append(f"　- **{pdata['username']}**: -{actual_dmg} HP → {pdata['hp']}/{pdata['max_hp']}{status}")

        return "\n".join(log_parts)

    def _distribute_rewards(self, room: dict, duration_sec: float) -> list[str]:
        """Distribute coins and loot based on damage_dealt proportion."""
        players = room["players"]
        total_dmg = sum(p["damage_dealt"] for p in players.values())
        reward_pool = int(room["boss_max_hp"] * room["reward_mult"] * 0.8)

        # Find MVP
        mvp_uid = max(players.items(), key=lambda x: x[1]["damage_dealt"])[0]
        mvp_name = players[mvp_uid]["username"]
        mvp_extra = int(reward_pool * 0.1)

        lines = [f"🏆 MVP: **{mvp_name}** ({players[mvp_uid]['damage_dealt']} 伤害) — 额外 +{mvp_extra}₲"]

        for pid, pdata in players.items():
            if total_dmg <= 0:
                share = 0
            else:
                share = int(reward_pool * pdata["damage_dealt"] / total_dmg)

            # Daily first kill bonus
            if self._get_daily_first_kill(pid):
                share = int(share * 2)
                first_bonus = " (首杀双倍！)"
            else:
                first_bonus = ""

            # Loot drops
            drops = self._roll_loot(room["boss"]["name"])
            loot_text = ""
            loot_total = 0
            for item_name, value in drops:
                loot_total += value
                loot_text += f" + 🎁 {item_name}({value}₲)"

            # MVP bonus
            mvp_bonus = 0
            mvp_str = ""
            if pid == mvp_uid:
                mvp_bonus = mvp_extra
                mvp_str = f" + 🏆 MVP额外+{mvp_extra}₲"

            total_earn = share + loot_total + mvp_bonus
            if total_earn > 0:
                add_coins(pid, total_earn, f"Boss副本奖励: {room['boss']['name']} {room['difficulty']}")

            # Record kill
            self._set_cooldown(pid, room["boss"]["name"], room["difficulty"])
            self._record_kill(room["boss"]["name"], room["difficulty"], pid, pdata["damage_dealt"], duration_sec)

            lines.append(
                f"- **{pdata['username']}**: {pdata['damage_dealt']}伤害 → 🪙 +{total_earn}{first_bonus}{loot_text}{mvp_str}"
            )

        return lines

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss use-potion
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="use-potion",
        description="战斗中使用药水 / Use a potion during battle"
    )
    @app_commands.describe(name="药水名称 / Potion name")
    @app_commands.autocomplete(name=_potion_autocomplete)
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
    async def boss_use_potion(self, interaction: discord.Interaction, name: str):
        chid = str(interaction.channel_id)
        uid = str(interaction.user.id)

        room = self._find_room_by_channel(chid)
        if not room:
            return await interaction.response.send_message("本频道没有进行中的副本 / No active dungeon.", ephemeral=True)

        if uid not in room["players"]:
            return await interaction.response.send_message("你不在副本中！/ You are not in the dungeon!", ephemeral=True)

        player = room["players"][uid]
        if player["hp"] <= 0:
            return await interaction.response.send_message("你已阵亡！/ You are dead!", ephemeral=True)

        # Check inventory
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, quantity FROM user_inventory WHERE user_id = ? AND item_id = 0 AND item_name = ? AND item_type = 'potion'",
                (uid, name),
            )
            inv_row = cur.fetchone()

        if not inv_row or inv_row["quantity"] <= 0:
            return await interaction.response.send_message(
                f"背包中没有 **{name}**！", ephemeral=True)

        # Get potion template
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM potions WHERE name = ?", (name,))
            potion = cur.fetchone()

        if not potion:
            return await interaction.response.send_message(f"药水 '{name}' 不存在", ephemeral=True)

        potion = dict(potion)
        effect_type = potion["effect_type"]
        effect_value = potion["effect_value"]

        # Consume from inventory
        if inv_row["quantity"] > 1:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE user_inventory SET quantity = quantity - 1 WHERE id = ?", (inv_row["id"],))
                conn.commit()
        else:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM user_inventory WHERE id = ?", (inv_row["id"],))
                conn.commit()

        # Apply effect to in-memory player
        result_text = ""
        if effect_type == "heal_hp":
            healed = min(effect_value, player["max_hp"] - player["hp"])
            player["hp"] += healed
            result_text = f"恢复了 **{healed}** HP！（{player['hp']}/{player['max_hp']}）"
        elif effect_type == "heal_mp":
            healed = min(effect_value, player["max_mp"] - player["mp"])
            player["mp"] += healed
            result_text = f"恢复了 **{healed}** MP！（{player['mp']}/{player['max_mp']}）"
        elif effect_type == "buff_atk":
            player["buff_atk"] += effect_value
            player["buff_atk_turns"] = max(player["buff_atk_turns"], 5)
            result_text = f"攻击力 **+{effect_value}**，持续 5 回合！"
        elif effect_type == "buff_def":
            player["buff_def"] += effect_value
            player["buff_def_turns"] = max(player["buff_def_turns"], 5)
            result_text = f"防御力 **+{effect_value}**，持续 5 回合！"
        elif effect_type == "revive":
            if player["hp"] > 0:
                # Refund
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) VALUES (?, 0, ?, 1, 'potion')",
                        (uid, name),
                    )
                    conn.commit()
                return await interaction.response.send_message("你还活着！复活药剂只能在 HP=0 时使用。", ephemeral=True)
            player["hp"] = max(1, int(player["max_hp"] * 0.5))
            player["mp"] = player["max_mp"]
            result_text = f"✨ 复活！HP 恢复到 {player['hp']}/{player['max_hp']}，MP 全满！"

        embed = discord.Embed(
            title=f"{potion['emoji']} {player['username']} 使用了 {name}",
            description=result_text,
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss status
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="status",
        description="查看副本战况 / View dungeon status"
    )
    async def boss_status(self, interaction: discord.Interaction):
        chid = str(interaction.channel_id)
        room = self._find_room_by_channel(chid)
        if not room:
            return await interaction.response.send_message("本频道无进行中的副本 / No active dungeon.", ephemeral=True)

        embed = self._build_room_embed(room)
        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # Room helpers
    # ══════════════════════════════════════════════════════════

    def _find_room_by_channel(self, chid: str) -> dict | None:
        for rid, room in self.rooms.items():
            if room.get("channel_id") == chid and room.get("status") in ("waiting", "fighting"):
                return room
        return None

    def _build_room_embed(self, room: dict, defeated: bool = False) -> discord.Embed:
        boss = room["boss"]
        emoji = boss["emoji"]
        boss_name = boss["name"]
        phase = room["phase"]

        title = f"{emoji} {boss_name} 团战 / Raid"
        if defeated:
            title = f"{emoji} {boss_name} — 已击败！/ Defeated!"
        elif phase == 2:
            title = f"{emoji} {boss_name} — ⚡ Phase 2 暴怒阶段！"

        embed = discord.Embed(title=title, color=room["diff_color"])
        embed.add_field(name="难度 / Difficulty", value=room["diff_label"], inline=True)
        embed.add_field(name="回合 / Turn", value=str(room["turn"]), inline=True)
        embed.add_field(name="阶段 / Phase", value=f"{'⚡ ' if phase == 2 else ''}Phase {phase}", inline=True)

        # Boss HP bar
        embed.add_field(
            name="Boss HP",
            value=f"```{_format_bar(room['boss_hp'], room['boss_max_hp'], 15)}```",
            inline=False,
        )

        # Boss skills
        embed.add_field(
            name="技能 / Skills",
            value=" | ".join(boss["skills"]),
            inline=True,
        )
        if phase == 2:
            embed.add_field(
                name="⚠️ 暴怒技能",
                value=boss["rage_skill"],
                inline=False,
            )

        embed.add_field(name="攻击力 / ATK", value=str(room["boss_atk"]), inline=True)

        # Player list with HP/MP bars and buffs
        player_lines = []
        for pid, p in room["players"].items():
            alive_mark = "" if p["hp"] > 0 else "💀"
            hp_bar = _format_bar(p["hp"], p["max_hp"], 10)
            mp_bar = _format_bar(p["mp"], p["max_mp"], 6)

            buffs = []
            if p["buff_atk"] > 0:
                buffs.append(f"ATK+{p['buff_atk']}({p['buff_atk_turns']}T)")
            if p["buff_def"] > 0:
                buffs.append(f"DEF+{p['buff_def']}({p['buff_def_turns']}T)")
            if p["frozen"]:
                buffs.append("❄️冻结")
            if p["dot_dmg"] > 0:
                buffs.append(f"☠️毒({p['dot_turns']}T)")

            buff_str = f" [{', '.join(buffs)}]" if buffs else ""
            line = (
                f"{alive_mark} **{p['username']}**\n"
                f"　HP: {hp_bar}\n"
                f"　MP: {mp_bar}\n"
                f"　伤害: {p['damage_dealt']}{buff_str}"
            )
            player_lines.append(line)

        embed.add_field(
            name=f"玩家 / Players ({len(room['players'])})",
            value="\n".join(player_lines) if player_lines else "等待加入 / Waiting...",
            inline=False,
        )

        status_text = {"waiting": "⏳ 等待开始", "fighting": "⚔️ 战斗中", "finished": "🏁 已结束"}
        embed.set_footer(text=f"状态: {status_text.get(room['status'], room['status'])} | /gmpt-boss attack 攻击")
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
            """, (boss_name, difficulty, duration_sec, user_id, duration_sec, dmg))
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

    def _roll_loot(self, boss_name: str) -> list[tuple[str, int]]:
        loot_table = BOSS_TYPES.get(boss_name, {}).get("loot_table", [])
        drops = []
        for prob, item_name, value in loot_table:
            if random.random() < prob:
                drops.append((item_name, value))
        return drops


async def setup(bot):
    await bot.add_cog(BossCog(bot))
