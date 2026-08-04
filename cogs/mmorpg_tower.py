"""
GMPT Bot — MMORPG 每日挑战塔 / Daily Challenge Tower
10层递增难度，奖励金币+材料，每天重置
"""
import asyncio
import random
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
import logging

logger = logging.getLogger(__name__)

# Tower floor definitions
TOWER_FLOORS = [
    (1, "哥布林哨兵", 500, 30, 10, 50),
    (2, "骷髅战士", 800, 35, 12, 70),
    (3, "巨石守卫 🔸小Boss", 1500, 40, 15, 120),
    (4, "暗影刺客", 1000, 45, 12, 90),
    (5, "火焰法师", 1200, 50, 18, 110),
    (6, "冰霜巨人 🔸小Boss", 2500, 55, 25, 200),
    (7, "亡灵骑士", 1800, 60, 22, 150),
    (8, "深渊恶魔", 2200, 70, 28, 180),
    (9, "龙血战士 🔸小Boss", 4000, 75, 35, 350),
    (10, "塔之守护者 👑最终Boss", 6000, 90, 40, 500),
]
# (floor, name, hp, atk, def, coins)


class TowerHubView(discord.ui.View):
    """挑战塔主面板入口 / Tower main panel entry."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        today = datetime.date.today().isoformat()
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT current_floor, cleared_today, last_date FROM tower_progress WHERE user_id=?",
                (self.uid,),
            )
            row = cur.fetchone()

        if row and row[2] == today and row[1]:
            desc = "今日已通关 / Already cleared today!\n花费 `1000G` 可重置 / Spend 1000G to reset"
            color = discord.Color.gold()
            floor_info = "🏆 已通关 / Cleared"
        elif row and row[2] == today:
            f = row[0]
            desc = f"当前进度 / Current: **第{f}层**\n继续挑战 / Continue climbing!"
            color = discord.Color.blue()
            floor_info = f"🗼 第{f}层 / Floor {f}"
        else:
            desc = "开始挑战10层递增难度的敌人！\nClimb 10 floors of increasing difficulty!"
            color = discord.Color.blue()
            floor_info = "🗼 第1层 / Floor 1"

        embed = discord.Embed(
            title="🗼 Challenge Tower / 挑战塔",
            description=f"{desc}\n\n{floor_info}",
            color=color,
        )
        embed.add_field(
            name="奖励 / Rewards",
            value="每层金币 + 通关强化石 & 宝石碎片\nCoins per floor + clear rewards",
            inline=False,
        )
        embed.set_footer(text="10层递增难度 | 每日重置")
        return embed

    @discord.ui.button(label="⚔️ Start 挑战", style=discord.ButtonStyle.danger, row=0)
    async def _start_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        today = datetime.date.today().isoformat()

        cog = interaction.client.get_cog("TowerCog")
        if not cog:
            await interaction.response.send_message("Tower system unavailable / 挑战塔不可用", ephemeral=True)
            return

        if uid in cog._battles:
            await interaction.response.send_message("Already in battle / 已在战斗中！", ephemeral=True)
            return

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT current_floor, cleared_today, last_date FROM tower_progress WHERE user_id=?",
                (uid,),
            )
            row = cur.fetchone()

            if row and row[2] == today and row[1]:
                await interaction.response.send_message(
                    f"今日已通关！使用 `/gmpt-tower reset` 重置。",
                    ephemeral=True,
                )
                return

            if not row or row[2] != today:
                if row:
                    cur.execute(
                        "UPDATE tower_progress SET current_floor=1, cleared_today=0, last_date=? WHERE user_id=?",
                        (today, uid),
                    )
                else:
                    cur.execute(
                        "INSERT INTO tower_progress (user_id, current_floor, last_date) VALUES (?,1,?)",
                        (uid, today),
                    )
                conn.commit()
                floor = 1
            else:
                floor = row[0]

        if floor > 10:
            await cog._tower_clear(interaction, uid)
            return

        f_num, name, hp, atk, def_, coins = TOWER_FLOORS[floor - 1]

        async with cog._lock:
            cog._battles[uid] = {
                "floor": floor,
                "monster_name": name,
                "monster_hp": hp,
                "monster_max_hp": hp,
                "monster_atk": atk,
                "monster_def": def_,
                "reward_coins": coins,
            }

        embed = discord.Embed(
            title=f"🗼 第{floor}层 / Floor {floor}",
            description=f"**{name}** 挡在你的面前！\nHP: `{hp}` | ATK: `{atk}` | DEF: `{def_}`",
            color=discord.Color.red() if floor % 3 == 0 or floor == 10 else discord.Color.blue(),
        )
        embed.set_footer(text=f"奖励: {coins}G | 使用下方按钮攻击 / Attack below")

        view = TowerFightView(cog, uid)
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.send(embed=embed, view=view)

    @discord.ui.button(label="Back 返回", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)
    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(self.uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
            return
        await interaction.response.send_message("Use /gmpt-mmorpg to return.", ephemeral=True)


class TowerCog(CogBase):
    """每日挑战塔 / Daily Challenge Tower"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()
        self._battles: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def cog_load(self):
        self._ensure_tables()
        logger.info("[Tower] 每日挑战塔已加载 / Tower loaded")

    def _ensure_tables(self):
        with get_db_ctx() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tower_progress (
                    user_id TEXT PRIMARY KEY,
                    current_floor INTEGER DEFAULT 1,
                    cleared_today INTEGER DEFAULT 0,
                    first_clear_reward TEXT DEFAULT NULL,
                    last_date TEXT DEFAULT (date('now'))
                )
            """)

    tower = app_commands.Group(name="gmpt-tower", description="每日挑战塔 / Daily Challenge Tower")

    @tower.command(name="start", description="开始挑战 / Start tower climb")
    async def start(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        today = datetime.date.today().isoformat()

        with get_db_ctx() as cur:
            cur.execute("SELECT current_floor, cleared_today, last_date FROM tower_progress WHERE user_id=?", (user_id,))
            row = cur.fetchone()

            if row and row[2] == today and row[1]:
                # Already cleared today, offer reset
                embed = discord.Embed(
                    title="🗼 挑战塔 / Challenge Tower",
                    description=(
                        f"今日已通关 / Already cleared today!\n"
                        f"花费 `1000G` 可重置挑战 / Spend 1000G to reset\n"
                        f"使用 `/gmpt-tower reset` 重置"
                    ),
                    color=discord.Color.orange(),
                )
                await interaction.response.send_message(embed=embed)
                return

            if not row or row[2] != today:
                # Reset for new day
                if row:
                    cur.execute("UPDATE tower_progress SET current_floor=1, cleared_today=0, last_date=? WHERE user_id=?", (today, user_id))
                else:
                    cur.execute("INSERT INTO tower_progress (user_id, current_floor, last_date) VALUES (?,1,?)", (user_id, today))
                floor = 1
            else:
                floor = row[0]

        await self._start_floor(interaction, user_id, floor)

    async def _start_floor(self, interaction: discord.Interaction, user_id: str, floor: int):
        if floor > 10:
            await self._tower_clear(interaction, user_id)
            return

        f_num, name, hp, atk, def_, coins = TOWER_FLOORS[floor - 1]

        async with self._lock:
            self._battles[user_id] = {
                "floor": floor,
                "monster_name": name,
                "monster_hp": hp,
                "monster_max_hp": hp,
                "monster_atk": atk,
                "monster_def": def_,
                "reward_coins": coins,
            }

        # Build fight embed
        embed = discord.Embed(
            title=f"🗼 第{floor}层 / Floor {floor}",
            description=f"**{name}** 挡在你的面前！\nHP: `{hp}` | ATK: `{atk}` | DEF: `{def_}`",
            color=discord.Color.red() if floor % 3 == 0 or floor == 10 else discord.Color.blue(),
        )
        embed.set_footer(text=f"奖励: {coins}G | 使用下方按钮攻击 / Attack below")

        view = TowerFightView(self, user_id)
        await interaction.response.send_message(embed=embed, view=view)

    async def _tower_clear(self, interaction: discord.Interaction, user_id: str):
        """Called when all 10 floors are cleared"""
        today = datetime.date.today().isoformat()
        total_coins = sum(f[5] for f in TOWER_FLOORS)

        with get_db_ctx() as cur:
            cur.execute(
                "UPDATE tower_progress SET cleared_today=1, first_clear_reward=COALESCE(first_clear_reward,'claimed') WHERE user_id=?",
                (user_id,)
            )
            # Check if first clear ever
            cur.execute("SELECT first_clear_reward FROM tower_progress WHERE user_id=?", (user_id,))
            row = cur.fetchone()
            is_first = row and row[0] == "claimed"

        from cogs.economy import add_coins
        bonus = 500 if is_first else 0  # First-time clear bonus
        await add_coins(user_id, total_coins + bonus)

        embed = discord.Embed(
            title="🏆 通关 / Tower Cleared!",
            description=(
                f"**10层全部击败！**\n\n"
                f"💰 获得金币: `{total_coins}G`\n"
                + (f"🎁 首通额外奖励: `{bonus}G`\n" if bonus else "") +
                f"💎 强化石 ×{random.randint(1,3)} 宝石碎片 ×{random.randint(1,2)}"
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.edit_message(embed=embed, view=None)

    @tower.command(name="reset", description="花费1000G重置挑战塔 / Reset tower for 1000G")
    async def reset(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        today = datetime.date.today().isoformat()

        from cogs.economy import get_balance, add_coins
        bal = await get_balance(user_id)
        if bal < 1000:
            await interaction.response.send_message(f"金币不足 / Need 1000G, you have {bal}G", ephemeral=True)
            return

        await add_coins(user_id, -1000)

        with get_db_ctx() as cur:
            cur.execute(
                "UPDATE tower_progress SET current_floor=1, cleared_today=0, last_date=? WHERE user_id=?",
                (today, user_id)
            )

        await interaction.response.send_message("🔄 挑战塔已重置 / Tower reset! 使用 `/gmpt-tower start` 开始", ephemeral=True)


class TowerFightView(discord.ui.View):
    def __init__(self, cog: TowerCog, user_id: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id

    @discord.ui.button(label="⚔️ 攻击 / Attack", style=discord.ButtonStyle.danger)
    async def attack(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("这不是你的战斗 / Not your fight", ephemeral=True)
            return

        battle = self.cog._battles.get(self.user_id)
        if not battle:
            await interaction.response.send_message("战斗已结束 / Battle ended", ephemeral=True)
            return

        # Player attack
        from cogs.mmorpg_stats import get_player_combat_stats
        stats = await get_player_combat_stats(self.user_id)
        p_atk = stats.get("atk", 30)
        p_def = stats.get("def", 10)
        p_hp = stats.get("hp", 200)
        p_crit = stats.get("crit", 0.05)

        # Damage calculation
        raw_dmg = max(1, p_atk - battle["monster_def"] // 2)
        is_crit = random.random() < p_crit
        if is_crit:
            raw_dmg = int(raw_dmg * 2)
        dmg = max(1, raw_dmg + random.randint(-3, 5))
        battle["monster_hp"] -= dmg

        lines = [f"⚔️ 你造成 `{dmg}` 伤害 {'💥暴击!' if is_crit else ''}"]

        # Monster counter-attack
        if battle["monster_hp"] > 0:
            m_dmg = max(1, battle["monster_atk"] - p_def // 2 + random.randint(-2, 3))
            lines.append(f"👊 **{battle['monster_name']}** 反击 `{m_dmg}` 伤害")
        else:
            lines.append(f"💀 **{battle['monster_name']}** 被击败！")

        # Advance floor
        if battle["monster_hp"] <= 0:
            reward = battle["reward_coins"]
            next_floor = battle["floor"] + 1

            with get_db_ctx() as cur:
                cur.execute("UPDATE tower_progress SET current_floor=? WHERE user_id=?", (next_floor, self.user_id))

            del self.cog._battles[self.user_id]

            lines.append(f"💰 获得 `{reward}G`")

            embed = discord.Embed(
                title=f"🗼 第{battle['floor']}层 通过 / Floor Cleared!",
                description="\n".join(lines),
                color=discord.Color.green(),
            )

            if next_floor <= 10:
                f_num, name, hp, atk, def_, coins = TOWER_FLOORS[next_floor - 1]

                # Restore player HP between floors
                embed.add_field(
                    name=f"下一层 / Next: 第{next_floor}层",
                    value=f"**{name}** — HP: `{hp}`",
                    inline=False
                )

                async with self.cog._lock:
                    self.cog._battles[self.user_id] = {
                        "floor": next_floor,
                        "monster_name": name,
                        "monster_hp": hp,
                        "monster_max_hp": hp,
                        "monster_atk": atk,
                        "monster_def": def_,
                        "reward_coins": coins,
                    }
            else:
                embed.add_field(name="🏆", value="前往最终层！", inline=False)

            await interaction.response.edit_message(embed=embed, view=self if next_floor <= 10 else None)
            if next_floor > 10:
                fake_interaction = type('obj', (object,), {'response': type('resp', (object,), {'edit_message': interaction.response.edit_message})()})
                await self.cog._tower_clear(interaction, self.user_id)
            return

        # Monster still alive — update embed
        hp_bar = "█" * (battle["monster_hp"] * 10 // battle["monster_max_hp"]) + "░" * (10 - battle["monster_hp"] * 10 // battle["monster_max_hp"])
        embed = discord.Embed(
            title=f"🗼 第{battle['floor']}层 / Floor {battle['floor']}",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        embed.add_field(name=f"**{battle['monster_name']}**", value=f"[{hp_bar}] HP: `{battle['monster_hp']}/{battle['monster_max_hp']}`", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🏃 逃跑 / Flee", style=discord.ButtonStyle.secondary)
    async def flee(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("不是你的战斗", ephemeral=True)
            return

        self.cog._battles.pop(self.user_id, None)
        embed = discord.Embed(title="🏃 逃跑 / Flee!", description="你逃离了挑战塔 / You fled the tower.", color=discord.Color.grey())
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        self.cog._battles.pop(self.user_id, None)
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(TowerCog(bot))
