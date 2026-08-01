"""
cogs/dungeon.py — 地下城 / Dungeon
Select-driven turn-based battle. Multi-floor sequential run from selected floor.
5F/10F Boss floors with equipment drops. Daily 1 free run (+200G per extra).
"""
import random
import time
import asyncio
import logging
import discord
from discord import app_commands

from database import get_db_ctx
from utils.cog_base import CogBase
from utils.animations import progress_bar
from cogs.economy import add_coins, get_balance

logger = logging.getLogger(__name__)

# ── Dungeon Monsters ──
DUNGEON_MONSTERS = {
    1: [
        {"name": "史莱姆 Slime", "hp": 60, "atk": 15, "def": 2, "exp": 20, "coins": 50, "emoji": "🟢"},
        {"name": "哥布林 Goblin", "hp": 80, "atk": 18, "def": 3, "exp": 30, "coins": 70, "emoji": "👺"},
        {"name": "巨型老鼠 Giant Rat", "hp": 55, "atk": 16, "def": 1, "exp": 25, "coins": 60, "emoji": "🐀"},
    ],
    2: [
        {"name": "骷髅战士 Skeleton Warrior", "hp": 110, "atk": 25, "def": 5, "exp": 50, "coins": 120, "emoji": "💀"},
        {"name": "暗影法师 Shadow Mage", "hp": 85, "atk": 30, "def": 3, "exp": 55, "coins": 130, "emoji": "🧙‍♂️"},
        {"name": "石像鬼 Gargoyle", "hp": 130, "atk": 20, "def": 7, "exp": 45, "coins": 110, "emoji": "🗿"},
    ],
    3: [
        {"name": "牛头人 Minotaur", "hp": 180, "atk": 40, "def": 10, "exp": 100, "coins": 250, "emoji": "🐂"},
        {"name": "亡灵骑士 Death Knight", "hp": 200, "atk": 38, "def": 12, "exp": 110, "coins": 280, "emoji": "⚰️"},
        {"name": "地狱犬 Hellhound", "hp": 150, "atk": 45, "def": 8, "exp": 95, "coins": 230, "emoji": "🐺"},
    ],
    4: [
        {"name": "狮鹫 Griffin", "hp": 280, "atk": 55, "def": 15, "exp": 180, "coins": 450, "emoji": "🦅"},
        {"name": "九头蛇 Hydra", "hp": 350, "atk": 50, "def": 18, "exp": 200, "coins": 500, "emoji": "🐍"},
        {"name": "岩石巨人 Stone Golem", "hp": 400, "atk": 45, "def": 22, "exp": 170, "coins": 420, "emoji": "🗻"},
    ],
    5: [
        {"name": "暗影巨龙 Shadow Dragon", "hp": 600, "atk": 75, "def": 18, "exp": 500, "coins": 1200, "emoji": "🐉"},
        {"name": "魔王 Demon Lord", "hp": 650, "atk": 70, "def": 16, "exp": 550, "coins": 1300, "emoji": "👹"},
        {"name": "远古巫妖 Ancient Lich", "hp": 500, "atk": 80, "def": 14, "exp": 600, "coins": 1400, "emoji": "💀"},
    ],
    6: [
        {"name": "魔沼蛙 Gromp", "hp": 420, "atk": 62, "def": 22, "exp": 220, "coins": 520, "emoji": "🐸"},
        {"name": "暗影狼 Murk Wolf", "hp": 380, "atk": 68, "def": 18, "exp": 240, "coins": 550, "emoji": "🐺"},
        {"name": "锋喙鸟 Crimson Raptor", "hp": 400, "atk": 58, "def": 24, "exp": 230, "coins": 530, "emoji": "🦅"},
    ],
    7: [
        {"name": "近战兵 Melee Minion", "hp": 500, "atk": 72, "def": 28, "exp": 300, "coins": 700, "emoji": "⚔️"},
        {"name": "远程兵 Caster Minion", "hp": 440, "atk": 82, "def": 22, "exp": 320, "coins": 720, "emoji": "🔮"},
        {"name": "炮车兵 Siege Minion", "hp": 620, "atk": 65, "def": 35, "exp": 350, "coins": 800, "emoji": "💣"},
    ],
    8: [
        {"name": "炼狱亚龙 Infernal Drake", "hp": 700, "atk": 95, "def": 30, "exp": 450, "coins": 1100, "emoji": "🔥"},
        {"name": "海洋亚龙 Ocean Drake", "hp": 750, "atk": 85, "def": 35, "exp": 430, "coins": 1050, "emoji": "🌊"},
        {"name": "云端亚龙 Cloud Drake", "hp": 650, "atk": 90, "def": 28, "exp": 460, "coins": 1150, "emoji": "☁️"},
        {"name": "山脉亚龙 Mountain Drake", "hp": 800, "atk": 80, "def": 40, "exp": 420, "coins": 1000, "emoji": "⛰️"},
    ],
    9: [
        {"name": "峡谷先锋 Rift Herald", "hp": 950, "atk": 110, "def": 38, "exp": 600, "coins": 1500, "emoji": "🦀"},
        {"name": "纳什男爵 Baron Nashor", "hp": 1100, "atk": 120, "def": 42, "exp": 700, "coins": 1800, "emoji": "🐍"},
    ],
    10: [
        {"name": "远古巨龙 Elder Dragon", "hp": 1400, "atk": 140, "def": 45, "exp": 900, "coins": 2500, "emoji": "🐉"},
        {"name": "龙王 Aurelion Sol", "hp": 1600, "atk": 155, "def": 40, "exp": 1000, "coins": 3000, "emoji": "🌟"},
    ],
}

FLOOR_NAMES = {
    1: "阴暗洞穴 Dark Cave",
    2: "亡灵墓穴 Undead Tomb",
    3: "烈焰深渊 Fire Abyss",
    4: "风暴之巅 Storm Peak",
    5: "魔王宫殿 Demon Lord's Palace",
    6: "扭曲丛林 Twisted Treeline",
    7: "召唤师峡谷 Summoner's Rift",
    8: "龙坑 Dragon Pit",
    9: "男爵坑 Baron Pit",
    10: "远古龙坑 Elder Pit",
}

EXTRA_RUN_COST = 200
MAX_FLOOR = 10


def _init_dungeon_db():
    with get_db_ctx() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dungeon_runs (
                user_id TEXT PRIMARY KEY,
                free_runs_used INTEGER DEFAULT 0,
                last_reset_ts INTEGER DEFAULT 0
            )
        """)
        conn.commit()


def _get_dungeon_runs(user_id: str) -> tuple:
    """Return (free_remaining, extra_cost)."""
    import datetime
    now = int(time.time())
    utc8_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    midnight_ts = int(utc8_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    tomorrow_ts = midnight_ts + 86400

    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT free_runs_used, last_reset_ts FROM dungeon_runs WHERE user_id=?", (user_id,))
        row = cur.fetchone()

    if not row or row["last_reset_ts"] <= midnight_ts:
        free_runs_used = 0
        _save_dungeon_state(user_id, 0, tomorrow_ts)
    else:
        free_runs_used = row["free_runs_used"]

    free_remaining = max(0, 1 - free_runs_used)
    extra_cost = EXTRA_RUN_COST if free_runs_used >= 1 else 0
    return free_remaining, extra_cost


def _save_dungeon_state(user_id: str, free_runs_used: int, reset_ts: int):
    with get_db_ctx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO dungeon_runs (user_id, free_runs_used, last_reset_ts) VALUES (?,?,?)",
            (user_id, free_runs_used, reset_ts),
        )
        conn.commit()


def _get_player_stats(user_id: str) -> dict:
    """Get player combat stats from users table + equipment."""
    from cogs.mmorpg_equipment import _get_equip_stats
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT level, hp, max_hp, attack, defense FROM users WHERE discord_id=?",
            (user_id,),
        )
        row = cur.fetchone()
    if not row:
        return {"level": 1, "hp": 100, "max_hp": 100, "atk": 15, "def": 5, "crit": 5, "spd": 10}

    equip_stats = _get_equip_stats(user_id)
    return {
        "level": row["level"],
        "hp": row["hp"],
        "max_hp": row["max_hp"],
        "atk": row["attack"] + equip_stats.get("atk", 0),
        "def": row["defense"] + equip_stats.get("def", 0),
        "crit": 5 + equip_stats.get("crit", 0),
        "spd": 10 + equip_stats.get("spd", 0),
    }


def _persist_hp(uid: str, hp: int):
    with get_db_ctx() as conn:
        conn.execute("UPDATE users SET hp = ? WHERE discord_id = ?", (hp, uid))
        conn.commit()


# ══════════════════════════════════════════════════════════════
# DungeonBattleView — Select 驱动回合制战斗
# ══════════════════════════════════════════════════════════════
class DungeonBattleView(discord.ui.View):
    """Select-driven turn-based dungeon battle."""

    def __init__(self, uid: str, uname: str, start_floor: int, player: dict,
                 monster: dict, msg: discord.Message):
        super().__init__(timeout=600)
        self.uid = uid
        self.uname = uname
        self.cur_floor = start_floor
        self.player = dict(player)
        self.p_max_hp = player["max_hp"]
        self.monster = dict(monster)
        self.m_max_hp = monster["hp"]
        self.msg = msg
        self.battle_ended = False
        self.potions = 3  # 3 potions per dungeon run
        self._build_select()

    def _build_select(self):
        self.clear_items()

        options = [
            discord.SelectOption(
                label="⚔️ Attack 攻击", value="attack",
                description="普通攻击 — deal normal damage",
            ),
            discord.SelectOption(
                label="⚡ Skill 技能", value="skill",
                description="Power Strike — 1.5x 伤害",
            ),
        ]

        if self.potions > 0:
            options.append(discord.SelectOption(
                label=f"🧪 Potion 喝药 (×{self.potions})", value="potion",
                description="恢复 30% 最大 HP / restore 30% max HP",
            ))

        options.append(discord.SelectOption(
            label="🏃 Flee 逃跑", value="flee",
            description="逃离地下城 / escape the dungeon",
        ))

        select = discord.ui.Select(
            placeholder="⚔️ Choose Action / 选择动作",
            options=options,
            custom_id="dungeon_battle_action",
            row=0,
        )
        select.callback = self._action_callback
        self.add_item(select)

    def _build_embed(self, extra_text: str = "") -> discord.Embed:
        p_hp = self.player["hp"]
        m_hp = self.monster["hp"]
        m = self.monster

        p_bar = progress_bar(p_hp, self.p_max_hp, 14)
        m_bar = progress_bar(m_hp, self.m_max_hp, 14)

        boss_tag = " 👑 BOSS" if self.cur_floor in (5, 10) else ""

        embed = discord.Embed(
            title=f"🏰 地下城 Dungeon | {FLOOR_NAMES[self.cur_floor]}{boss_tag}",
            description=f"第 **{self.cur_floor}/{MAX_FLOOR}** 层 / Floor",
            color=0xFF6600 if m_hp > 0 else 0x2ECC71,
        )
        embed.add_field(
            name=f"🧑 {self.uname}  Lv.{self.player['level']}",
            value=f"❤️ HP: {p_bar}\n⚔️ ATK: {self.player['atk']}  |  🛡️ DEF: {self.player['def']}",
            inline=True,
        )
        embed.add_field(
            name=f"{m['emoji']} {m['name']}",
            value=f"❤️ HP: {m_bar}\n⚔️ ATK: {m['atk']}  |  🛡️ DEF: {m['def']}",
            inline=True,
        )

        if extra_text:
            embed.add_field(name="📜 战斗日志 / Battle Log", value=extra_text, inline=False)

        embed.set_footer(text="⚔️ 选择你的动作 / Choose your action above ↑")
        return embed

    async def _action_callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("这不是你的战斗！/ Not your battle!", ephemeral=True)
            return

        if self.battle_ended:
            await interaction.response.send_message("战斗已结束！/ Battle already ended!", ephemeral=True)
            return

        action = interaction.data["values"][0]

        if action == "flee":
            await interaction.response.defer()
            self.battle_ended = True
            _persist_hp(self.uid, self.player["hp"])
            embed = discord.Embed(
                title="🏃 逃跑！Fled!",
                description=f"你逃离了 **{FLOOR_NAMES[self.cur_floor]}** ！\nYou fled from the dungeon!\n\n❤️ 剩余HP: {self.player['hp']}/{self.p_max_hp}",
                color=0x95A5A6,
            )
            await self.msg.edit(embed=embed, view=None)
            return

        await interaction.response.defer()

        log_lines = []

        # ── Player Action ──
        if action == "attack":
            dmg = self._calc_player_dmg()
            crit = random.random() < (self.player["crit"] / 100)
            if crit:
                dmg = int(dmg * 2.0)
                log_lines.append(f"⚔️ 你发动攻击 — **{dmg}** DMG！💥 暴击！")
            else:
                log_lines.append(f"⚔️ 你发动攻击 — **{dmg}** DMG！")
            self.monster["hp"] = max(0, self.monster["hp"] - dmg)

        elif action == "skill":
            dmg = int(self._calc_player_dmg() * 1.5)
            crit = random.random() < (self.player["crit"] / 100)
            if crit:
                dmg = int(dmg * 2.0)
                log_lines.append(f"⚡ 你使用 Power Strike — **{dmg}** DMG！💥 暴击！")
            else:
                log_lines.append(f"⚡ 你使用 Power Strike — **{dmg}** DMG！")
            self.monster["hp"] = max(0, self.monster["hp"] - dmg)

        elif action == "potion":
            heal = int(self.p_max_hp * 0.3)
            self.player["hp"] = min(self.p_max_hp, self.player["hp"] + heal)
            self.potions -= 1
            log_lines.append(f"🧪 喝了一瓶药水！+**{heal}** HP (剩余 ×{self.potions})")
            # Rebuild select to update potion count
            self._build_select()

        # ── Check monster death ──
        if self.monster["hp"] <= 0:
            await self._handle_victory(log_lines)
            return

        # ── Monster Counter-Attack ──
        self._monster_counter(log_lines)

        # ── Check player death ──
        if self.player["hp"] <= 0:
            await self._handle_defeat(log_lines)
            return

        # ── Refresh embed ──
        embed = self._build_embed(extra_text="\n".join(log_lines))
        await self.msg.edit(embed=embed, view=self)

    def _calc_player_dmg(self) -> int:
        return max(1, random.randint(self.player["atk"] // 2, self.player["atk"]) - self.monster["def"] // 3)

    def _monster_counter(self, log_lines: list):
        """Monster counter-attack: 80% normal / 20% crit (x2 damage)."""
        m = self.monster
        base_dmg = max(1, random.randint(m["atk"] // 2, m["atk"]) - self.player["def"] // 3)
        is_crit = random.random() < 0.20

        if is_crit:
            dmg = int(base_dmg * 2)
            log_lines.append(f"💢 {m['emoji']} {m['name']} 暴击反击！— **{dmg}** DMG！💥")
        else:
            dmg = base_dmg
            log_lines.append(f"💢 {m['emoji']} {m['name']} 反击 — **{dmg}** DMG！")

        self.player["hp"] = max(0, self.player["hp"] - dmg)

    async def _handle_victory(self, log_lines: list):
        """Monster defeated — reward and advance to next floor or complete."""
        m = self.monster

        # Rewards
        coins_earned = m["coins"] + random.randint(-20, 50)
        exp_earned = m["exp"]
        add_coins(self.uid, coins_earned, f"地下城第{self.cur_floor}层奖励")
        from cogs.daily_quest import _update_progress
        _update_progress(self.uid, "kill")
        from cogs.economy_jobs import _add_user_xp
        _add_user_xp(self.uid, exp_earned)

        # Persist HP
        _persist_hp(self.uid, self.player["hp"])

        log_lines.append(f"\n🎉 击败了 {m['emoji']} **{m['name']}**！")
        log_lines.append(f"🪙 +{coins_earned}G  |  ✨ +{exp_earned} EXP")

        # Boss floor drops
        if self.cur_floor in (5, 10) and random.random() < 0.3:
            log_lines.append("🎁 获得随机装备一件！/ Random equipment obtained!")
            if self.cur_floor == 10 and random.random() < 0.15:
                log_lines.append("🏆 LOL 传说装备 Legendary Drop!")

        # Check if dungeon complete
        if self.cur_floor >= MAX_FLOOR:
            self.battle_ended = True
            embed = discord.Embed(
                title="🏆 地下城通关！Dungeon Complete!",
                description=f"恭喜 {self.uname} 通关全部 {MAX_FLOOR} 层！\nAll {MAX_FLOOR} floors cleared!\n\n❤️ HP: {self.player['hp']}/{self.p_max_hp}",
                color=0xF1C40F,
            )
            embed.add_field(name="📜 最终战报", value="\n".join(log_lines), inline=False)
            embed.set_footer(text=f"每日免费1次 / 1 free daily (extra: 🪙 {EXTRA_RUN_COST})")
            await self.msg.edit(embed=embed, view=None)
            return

        # Advance to next floor
        self.cur_floor += 1
        next_monster = random.choice(DUNGEON_MONSTERS[self.cur_floor])
        self.monster = dict(next_monster)
        self.m_max_hp = next_monster["hp"]
        self._build_select()

        advance_text = f"\n⬇️ 进入 **第{self.cur_floor}层 {FLOOR_NAMES[self.cur_floor]}**！\n{self.monster['emoji']} **{self.monster['name']}** 出现了！"
        log_lines.append(advance_text)

        embed = self._build_embed(extra_text="\n".join(log_lines))
        await self.msg.edit(embed=embed, view=self)

    async def _handle_defeat(self, log_lines: list):
        """Player died."""
        self.battle_ended = True
        _persist_hp(self.uid, 0)

        embed = discord.Embed(
            title=f"💀 战败！Defeat! | {FLOOR_NAMES[self.cur_floor]}",
            description=(
                f"你被 {self.monster['emoji']} **{self.monster['name']}** 击败了！\n"
                f"You were defeated!\n\n"
                f"💡 提示: 提升等级和装备再来挑战 / Level up and gear up then try again!"
            ),
            color=0xE74C3C,
        )
        embed.add_field(name="📜 战斗日志", value="\n".join(log_lines), inline=False)
        embed.set_footer(text=f"地下城每日免费1次 / Dungeon: 1 free run daily (extra: 🪙 {EXTRA_RUN_COST})")
        await self.msg.edit(embed=embed, view=None)


# ══════════════════════════════════════════════════════════════
# DungeonView — 地城主面板
# ══════════════════════════════════════════════════════════════
class DungeonView(discord.ui.View):
    """地下城主面板 / Dungeon main panel."""

    def __init__(self, guild, user_id: str, user_name: str):
        super().__init__(timeout=300)
        self.guild = guild
        self.uid = user_id
        self.uname = user_name
        self._build()

    def _build(self):
        self.clear_items()
        options = []
        for floor in range(1, 11):
            if floor == 6:
                desc = "Lv.20-28 | LOL 扭曲丛林"
                emoji = "🟣"
            elif floor == 7:
                desc = "Lv.28-36 | LOL 召唤师峡谷"
                emoji = "🟣"
            elif floor == 8:
                desc = "Lv.36-45 | LOL 龙坑"
                emoji = "🟣"
            elif floor == 9:
                desc = "Lv.45-55 | LOL 男爵坑"
                emoji = "🟣"
            elif floor == 10:
                desc = "Lv.55+ | LOL 远古龙坑"
                emoji = "🟣"
            else:
                desc = None
                emoji = None
            options.append(
                discord.SelectOption(
                    label=f"第{floor}层 Floor {floor} | {FLOOR_NAMES[floor]}",
                    value=str(floor),
                    description=desc,
                    emoji=emoji,
                )
            )

        select = discord.ui.Select(
            placeholder="选择楼层 / Select a floor...",
            options=options,
            custom_id="dungeon_floor_select",
        )
        select.callback = self._select_floor_callback
        self.add_item(select)

    async def _select_floor_callback(self, interaction: discord.Interaction):
        floor = int(interaction.data["values"][0])
        await self._start_floor(interaction, floor)

    async def _start_floor(self, interaction: discord.Interaction, floor: int):
        free, extra = _get_dungeon_runs(self.uid)
        cost = extra if free == 0 else 0

        if cost > 0:
            bal = get_balance(self.uid)
            if bal < cost:
                await interaction.response.send_message(
                    f"❌ 金币不足！需要 🪙 **{cost}** / Not enough coins! Need 🪙 **{cost}**",
                    ephemeral=True,
                )
                return
            logger.info(f"Dungeon entry: {self.uname}({self.uid}) floor={floor} cost={cost}G balance_before={bal}")
            add_coins(self.uid, -cost, "地下城入场费 / Dungeon entry fee")
            new_bal = get_balance(self.uid)
            logger.info(f"Dungeon entry: {self.uname}({self.uid}) deducted {cost}G balance_after={new_bal}")

        # Mark run used
        free_runs_used = 1 if free > 0 else 2
        import datetime
        utc8_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        _save_dungeon_state(self.uid, free_runs_used,
                            int(utc8_now.replace(hour=0, minute=0, second=0).timestamp()) + 86400)

        await interaction.response.defer()

        # Entry animation
        msg = await interaction.followup.send("🚪 ...")
        entry_frames = [
            f"🚪 {self.uname} 走向地下城入口...\n🚪 {self.uname} approaches the dungeon...",
            f"🏰 **{FLOOR_NAMES[floor]}**\n黑暗中传来低沉的咆哮...\nA low growl echoes in the darkness...",
            f"⚔️ {self.uname} 进入了 **{FLOOR_NAMES[floor]}**！\n⚔️ {self.uname} enters **{FLOOR_NAMES[floor]}**!",
        ]
        for frame_text in entry_frames:
            embed = discord.Embed(description=frame_text, color=0x8E44AD)
            await msg.edit(embed=embed)
            await asyncio.sleep(0.8)

        # Pick random monster
        monster = random.choice(DUNGEON_MONSTERS[floor])
        player = _get_player_stats(self.uid)

        # Encounter animation
        encounter_frames = [
            f"👀 {self.uname} 环顾四周...",
            f"❓ 前方有动静... Something stirs ahead...",
            f"{monster['emoji']} **{monster['name']}** 出现了！\n{monster['emoji']} **{monster['name']}** appears!",
        ]
        for frame_text in encounter_frames:
            embed = discord.Embed(description=frame_text, color=0xFF6600)
            await msg.edit(embed=embed)
            await asyncio.sleep(0.5)

        # Create Select-driven battle view
        battle_view = DungeonBattleView(self.uid, self.uname, floor, player, monster, msg)
        embed = battle_view._build_embed()
        await msg.edit(embed=embed, view=battle_view)


class Dungeon(CogBase):
    """地下城系统 / Dungeon System"""

    def __init__(self, bot):
        super().__init__()
        _init_dungeon_db()

    @app_commands.command(name="gmpt-dungeon", description="🏰 地下城副本 / Dungeon — explore and fight monsters!")
    async def dungeon_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        uname = interaction.user.display_name
        free, extra = _get_dungeon_runs(uid)
        player = _get_player_stats(uid)

        cost_text = "免费 Free" if free > 0 else f"🪙 {extra}"
        embed = discord.Embed(
            title=f"🏰 地下城 Dungeon | {uname}",
            description=(
                f"❤️ HP: {player['hp']}/{player['max_hp']}  |  ⚔️ ATK: {player['atk']}  |  🛡️ DEF: {player['def']}\n"
                f"Lv.{player['level']}  |  入场费 Entry: **{cost_text}**\n"
                f"每日免费 1 次 / 1 free daily (额外 extra: 🪙 {EXTRA_RUN_COST})"
            ),
            color=0x8E44AD,
        )
        embed.add_field(
            name="📜 楼层信息 / Floors",
            value=(
                "**1F 阴暗洞穴 Dark Cave** — Lv.1-5\n"
                "**2F 亡灵墓穴 Undead Tomb** — Lv.5-10\n"
                "**3F 烈焰深渊 Fire Abyss** — Lv.10-15\n"
                "**4F 风暴之巅 Storm Peak** — Lv.15-20\n"
                "**5F 魔王宫殿 Demon Lord's Palace** — Lv.20+ 👑\n"
                "**6F 扭曲丛林 Twisted Treeline** — Lv.20-28 🟣\n"
                "**7F 召唤师峡谷 Summoner's Rift** — Lv.28-36 🟣\n"
                "**8F 龙坑 Dragon Pit** — Lv.36-45 🟣\n"
                "**9F 男爵坑 Baron Pit** — Lv.45-55 🟣\n"
                "**10F 远古龙坑 Elder Pit** — Lv.55+ 🟣"
            ),
            inline=False,
        )
        embed.set_footer(text="选择楼层开始探索 / Select a floor to begin exploring!")

        view = DungeonView(interaction.guild, uid, uname)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(Dungeon(bot))


# ══════════════════════════════════════════════════════════════
# Dungeon Lobby View — Interactive Dungeon hub
# ══════════════════════════════════════════════════════════════
class DungeonLobbyView(discord.ui.View):
    """地下城大厅面板 / Dungeon lobby panel."""

    def __init__(self, user_id: str, main_view=None):
        super().__init__(timeout=300)
        self.uid = user_id
        self.main_view = main_view
        self._build()

    def build_main_embed(self):
        bal = get_balance(self.uid)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            today = time.strftime("%Y-%m-%d")
            cur.execute(
                "SELECT daily_used FROM dungeon_daily WHERE user_id = ? AND date = ?",
                (self.uid, today),
            )
            row = cur.fetchone()
        used_today = row["daily_used"] if row else 0
        free_left = "1 次免费" if used_today == 0 else "已用完 (used)"

        embed = discord.Embed(
            title="🏰 Dungeon / 地下城",
            description=(
                "10 层随机怪物，奖励随层数递增！\n"
                "10 floors, rewards increase with depth!\n\n"
                f"🆓 今日免费 / Free today: **{free_left}**\n"
                f"💵 额外探索 / Extra: **200G**\n"
                f"🪙 余额 / Balance: **{bal:,}**"
            ),
            color=0x8E44AD,
        )
        embed.add_field(
            name="⚔️ 开始探索 / Start",
            value="点击下方按钮直接进入地下城 / Click below to enter!",
            inline=False,
        )
        embed.set_footer(text="每日免费 1 次，额外每次 200G")
        return embed

    def _build(self):
        self.clear_items()
        explore_btn = discord.ui.Button(
            label="⚔️ Explore / 探索", style=discord.ButtonStyle.success,
            row=0, emoji="🏰", custom_id="dungeon_explore",
        )
        explore_btn.callback = self._explore_info_callback
        self.add_item(explore_btn)

        if self.main_view:
            back_btn = discord.ui.Button(
                label="Back to MMORPG / 返回", style=discord.ButtonStyle.danger,
                row=1, emoji="🏠", custom_id="dungeon_back",
            )
            back_btn.callback = self._back_callback
            self.add_item(back_btn)

    async def _explore_info_callback(self, interaction: discord.Interaction):
        """Directly open the full DungeonView for floor selection."""
        uid = str(interaction.user.id)
        uname = interaction.user.display_name
        free, extra = _get_dungeon_runs(uid)
        player = _get_player_stats(uid)
        cost_text = "免费 Free" if free > 0 else f"🪙 {extra}"
        embed = discord.Embed(
            title=f"🏰 地下城 Dungeon | {uname}",
            description=(
                f"❤️ HP: {player['hp']}/{player['max_hp']}  |  ⚔️ ATK: {player['atk']}  |  🛡️ DEF: {player['def']}\n"
                f"Lv.{player['level']}  |  入场费 Entry: **{cost_text}**\n"
                f"每日免费 1 次 / 1 free daily (额外 extra: 🪙 {EXTRA_RUN_COST})"
            ),
            color=0x8E44AD,
        )
        embed.add_field(
            name="📜 楼层信息 / Floors",
            value=(
                "**1F 阴暗洞穴 Dark Cave** — Lv.1-5\n"
                "**2F 亡灵墓穴 Undead Tomb** — Lv.5-10\n"
                "**3F 烈焰深渊 Fire Abyss** — Lv.10-15\n"
                "**4F 风暴之巅 Storm Peak** — Lv.15-20\n"
                "**5F 魔王宫殿 Demon Lord's Palace** — Lv.20+ 👑\n"
                "**6F 扭曲丛林 Twisted Treeline** — Lv.20-28 🟣\n"
                "**7F 召唤师峡谷 Summoner's Rift** — Lv.28-36 🟣\n"
                "**8F 龙坑 Dragon Pit** — Lv.36-45 🟣\n"
                "**9F 男爵坑 Baron Pit** — Lv.45-55 🟣\n"
                "**10F 远古龙坑 Elder Pit** — Lv.55+ 🟣"
            ),
            inline=False,
        )
        embed.set_footer(text="选择楼层开始探索 / Select a floor to begin exploring!")
        view = DungeonView(interaction.guild, uid, uname)
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

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
