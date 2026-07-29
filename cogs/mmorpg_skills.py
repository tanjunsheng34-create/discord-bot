"""
GMPT Bot — MMORPG 技能系统 / Skill System
/gmpt-skill learn   — 学习技能
/gmpt-skill list    — 列出已学技能
/gmpt-skill equip   — 装备技能
/gmpt-skill unequip — 卸载技能
"""
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db, get_db_ctx
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)

SKILLS = {
    "fireball": {
        "name": "火球术", "emoji": "🔥", "mp_cost": 15, "damage": 35,
        "min_level": 1, "price": 500, "description": "发射火球造成魔法伤害",
    },
    "ice_shard": {
        "name": "冰锥术", "emoji": "❄️", "mp_cost": 10, "damage": 25,
        "min_level": 3, "price": 400, "description": "射出冰锥，有概率冻结对手一回合",
    },
    "thunder": {
        "name": "雷霆一击", "emoji": "⚡", "mp_cost": 25, "damage": 50,
        "min_level": 5, "price": 800, "description": "召唤雷电，高伤害但有10%概率自伤",
    },
    "heal": {
        "name": "治愈术", "emoji": "💚", "mp_cost": 20, "heal": 40,
        "min_level": 2, "price": 600, "description": "恢复自身HP",
    },
    "berserk": {
        "name": "狂暴", "emoji": "😡", "mp_cost": 30, "buff_atk": 20, "duration": 3,
        "min_level": 7, "price": 1000, "description": "攻击力大幅提升，持续3回合",
    },
    "shield": {
        "name": "圣盾术", "emoji": "🛡️", "mp_cost": 25, "buff_def": 15, "duration": 3,
        "min_level": 4, "price": 700, "description": "防御力提升，持续3回合",
    },
    "poison": {
        "name": "毒雾", "emoji": "☠️", "mp_cost": 15, "dot": 10, "dot_duration": 3,
        "min_level": 6, "price": 600, "description": "使对手中毒3回合，每回合扣10HP",
    },
    "steal": {
        "name": "偷窃", "emoji": "💰", "mp_cost": 20,
        "min_level": 8, "price": 1200, "description": "从对手身上偷取金币（按对手余额比例）",
    },
}


def _get_balance(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT score FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return row["score"] if row else 0


def _add_coins(uid: str, amount: int, reason: str):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (discord_id, username) VALUES (?, '') ON CONFLICT(discord_id) DO NOTHING",
            (uid,),
        )
        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, uid))
        cur.execute(
            "INSERT INTO transactions (discord_id, amount, reason) VALUES (?, ?, ?)",
            (uid, amount, reason),
        )
        conn.commit()


def _get_user_level(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT level FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return row["level"] if row else 1


def _get_learned_skills(uid: str) -> list[str]:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT skill_id FROM player_skills WHERE user_id = ?", (uid,))
        return [r["skill_id"] for r in cur.fetchall()]


class Skills(CogBase):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    # ── Autocomplete: unlearned skills ──
    async def _unlearned_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        uid = str(interaction.user.id)
        learned = _get_learned_skills(uid)
        choices = []
        for sid, sdef in SKILLS.items():
            if sid not in learned:
                display = f"{sdef['emoji']} {sdef['name']} ({sid}) — 🪙{sdef['price']}"
                if not current or current.lower() in display.lower():
                    choices.append(app_commands.Choice(name=display, value=sid))
        return choices[:25]

    # ── Autocomplete: learned skills (for equip/unequip) ──
    async def _learned_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        uid = str(interaction.user.id)
        learned = _get_learned_skills(uid)
        choices = []
        for sid in learned:
            sdef = SKILLS.get(sid, {})
            display = f"{sdef.get('emoji', '❓')} {sdef.get('name', sid)} ({sid})"
            if not current or current.lower() in display.lower():
                choices.append(app_commands.Choice(name=display, value=sid))
        return choices[:25]

    # ══════════════════════════════════════════════════════════
    # /gmpt-skill group
    # ══════════════════════════════════════════════════════════
    skill_group = app_commands.Group(
        name="gmpt-skill",
        description="MMORPG 技能系统 / Skill System",
    )

    @skill_group.command(name="learn", description="学习技能 / Learn a skill")
    @app_commands.describe(skill_id="技能 ID / Skill ID")
    @app_commands.autocomplete(skill_id=_unlearned_autocomplete)
    @app_commands.checks.cooldown(1, 2.0, key=lambda i: (i.guild_id, i.user.id))
    async def learn_cmd(self, interaction: discord.Interaction, skill_id: str):
        """学习技能."""
        uid = str(interaction.user.id)

        if skill_id not in SKILLS:
            return await interaction.response.send_message(
                f"技能 '{skill_id}' 不存在 / Skill not found.", ephemeral=True
            )

        sdef = SKILLS[skill_id]
        user_level = _get_user_level(uid)

        if user_level < sdef["min_level"]:
            return await interaction.response.send_message(
                f"等级不足！需要 Lv.{sdef['min_level']}，你当前 Lv.{user_level}\n"
                f"Level too low! Requires Lv.{sdef['min_level']}, you are Lv.{user_level}",
                ephemeral=True,
            )

        # Check if already learned
        if skill_id in _get_learned_skills(uid):
            return await interaction.response.send_message(
                f"你已经学会了 {sdef['emoji']} **{sdef['name']}**！\nYou already know this skill.",
                ephemeral=True,
            )

        price = sdef["price"]
        bal = _get_balance(uid)
        if bal < price:
            return await interaction.response.send_message(
                f"余额不足！需要 🪙 {price:,}，你只有 🪙 {bal:,}",
                ephemeral=True,
            )

        _add_coins(uid, -price, f"学习技能 {sdef['name']} / Learn {skill_id}")

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO player_skills (user_id, skill_id, level, equipped) VALUES (?, ?, 1, 0)",
                (uid, skill_id),
            )
            conn.commit()

        new_bal = _get_balance(uid)
        embed = discord.Embed(
            title=f"{sdef['emoji']} Learned / 学会了: {sdef['name']}！",
            description=sdef["description"],
            color=0x2ECC71,
        )
        embed.add_field(name="Balance / 余额", value=f"🪙 {new_bal:,}", inline=True)
        embed.add_field(name="Hint / 提示", value="Use `/gmpt-skill equip` / 使用 `/gmpt-skill equip` 装备技能", inline=True)
        embed.set_footer(text=f"Skill ID: {skill_id}")
        await interaction.response.send_message(embed=embed)

    @skill_group.command(name="list", description="查看已学技能 / List learned skills")
    @app_commands.checks.cooldown(1, 2.0, key=lambda i: (i.guild_id, i.user.id))
    async def list_cmd(self, interaction: discord.Interaction):
        """列出已学技能."""
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT skill_id, level, equipped FROM player_skills WHERE user_id = ? ORDER BY skill_id", (uid,))
            rows = cur.fetchall()

        if not rows:
            return await interaction.response.send_message(
                "你还没有学习任何技能！使用 `/gmpt-skill learn` 来学习。\n"
                "You haven't learned any skills! Use `/gmpt-skill learn` to learn some.",
                ephemeral=True,
            )

        equipped_count = sum(1 for r in rows if r["equipped"])

        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Skills / 技能列表",
            description=f"Equipped / 已装备: **{equipped_count}** / 4\n",
            color=0x8E44AD,
        )

        lines = []
        for row in rows:
            sdef = SKILLS.get(row["skill_id"], {})
            emoji = sdef.get("emoji", "❓")
            name = sdef.get("name", row["skill_id"])
            desc = sdef.get("description", "")
            equipped_str = "Equipped" if row["equipped"] else "Unequipped"
            lines.append(f"{emoji} **{name}** ({row['skill_id']}) — Lv.{row['level']} {equipped_str}\n　{desc}")

        embed.add_field(name="Skills / 技能", value="\n".join(lines), inline=False)
        embed.set_footer(text="/gmpt-skill equip <SkillID> / /gmpt-skill unequip <SkillID>")
        await interaction.response.send_message(embed=embed)

    @skill_group.command(name="equip", description="装备技能 / Equip a skill")
    @app_commands.describe(skill_id="技能 ID / Skill ID")
    @app_commands.autocomplete(skill_id=_learned_autocomplete)
    @app_commands.checks.cooldown(1, 2.0, key=lambda i: (i.guild_id, i.user.id))
    async def equip_cmd(self, interaction: discord.Interaction, skill_id: str):
        """装备技能."""
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, level, equipped FROM player_skills WHERE user_id = ? AND skill_id = ?",
                (uid, skill_id),
            )
            row = cur.fetchone()

        if not row:
            return await interaction.response.send_message(
                f"你还没有学习技能 '{skill_id}'！先使用 `/gmpt-skill learn`。",
                ephemeral=True,
            )

        if row["equipped"]:
            return await interaction.response.send_message(
                f"技能 '{skill_id}' 已经装备了！",
                ephemeral=True,
            )

        # Check max equipped count
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as cnt FROM player_skills WHERE user_id = ? AND equipped = 1", (uid,))
            equipped_count = cur.fetchone()["cnt"]

        if equipped_count >= 4:
            return await interaction.response.send_message(
                f"最多装备 4 个技能！请先卸载一个再试。\nMax 4 skills equipped! Unequip one first.",
                ephemeral=True,
            )

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE player_skills SET equipped = 1 WHERE user_id = ? AND skill_id = ?",
                (uid, skill_id),
            )
            conn.commit()

        sdef = SKILLS.get(skill_id, {})
        await interaction.response.send_message(
            f"{sdef.get('emoji', '✅')} Equipped / 已装备 **{sdef.get('name', skill_id)}**！（{equipped_count + 1}/4）"
        )

    @skill_group.command(name="unequip", description="卸载技能 / Unequip a skill")
    @app_commands.describe(skill_id="技能 ID / Skill ID")
    @app_commands.autocomplete(skill_id=_learned_autocomplete)
    @app_commands.checks.cooldown(1, 2.0, key=lambda i: (i.guild_id, i.user.id))
    async def unequip_cmd(self, interaction: discord.Interaction, skill_id: str):
        """卸载技能."""
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, level, equipped FROM player_skills WHERE user_id = ? AND skill_id = ?",
                (uid, skill_id),
            )
            row = cur.fetchone()

        if not row:
            return await interaction.response.send_message(
                f"你还没有学习技能 '{skill_id}'！",
                ephemeral=True,
            )

        if not row["equipped"]:
            return await interaction.response.send_message(
                f"技能 '{skill_id}' 没有装备着。",
                ephemeral=True,
            )

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE player_skills SET equipped = 0 WHERE user_id = ? AND skill_id = ?",
                (uid, skill_id),
            )
            conn.commit()

        sdef = SKILLS.get(skill_id, {})
        await interaction.response.send_message(
            f"Unequipped / 已卸载 **{sdef.get('name', skill_id)}**"
        )


# ══════════════════════════════════════════════════════════════
# Skill Shop View — Interactive skill learning panel
# ══════════════════════════════════════════════════════════════
class SkillShopView(discord.ui.View):
    """技能商店面板 / Skill shop panel with Buy buttons."""

    def __init__(self, user_id: str, main_view=None):
        super().__init__(timeout=180)
        self.uid = user_id
        self.main_view = main_view
        self._build()

    def build_main_embed(self):
        learned = _get_learned_skills(self.uid)
        user_level = _get_user_level(self.uid)
        bal = _get_balance(self.uid)

        embed = discord.Embed(
            title="⚔️ 技能商店 / Skill Shop",
            description=f"你的等级 / Your Lv: **{user_level}** | 余额 / Balance: 🪙 **{bal:,}**",
            color=0xE67E22,
        )

        for sid, sdef in SKILLS.items():
            is_learned = sid in learned
            prefix = "✅" if is_learned else ("🔒" if user_level < sdef["min_level"] else "🛒")
            embed.add_field(
                name=f"{sdef['emoji']} {sdef['name']} / {sdef.get('name_en', sid)} {prefix}",
                value=(
                    f"{sdef['description']}\n"
                    f"🪙 **{sdef['price']:,}** | Lv.{sdef['min_level']}+ | "
                    f"MP: {sdef.get('mp_cost', '—')}"
                ),
                inline=False,
            )

        embed.set_footer(text="已学技能装备: /gmpt-skill equip | Tip: 最多装备4个技能")
        return embed

    def _build(self):
        self.clear_items()
        learned = _get_learned_skills(self.uid)
        user_level = _get_user_level(self.uid)

        for i, (sid, sdef) in enumerate(SKILLS.items()):
            is_learned = sid in learned
            locked = user_level < sdef["min_level"]
            disabled = is_learned or locked

            style = discord.ButtonStyle.success
            if is_learned:
                style = discord.ButtonStyle.secondary
            elif locked:
                style = discord.ButtonStyle.secondary

            label = f"{sdef['emoji']} {sdef['name']} 🪙{sdef['price']:,}"[:80]
            if is_learned:
                label = f"{sdef['emoji']} {sdef['name']} (已学)"[:80]
            elif locked:
                label = f"🔒 {sdef['name']} Lv.{sdef['min_level']}"[:80]

            btn = discord.ui.Button(
                label=label,
                style=style,
                row=i // 2,
                custom_id=f"skill_{sid}",
                emoji=sdef["emoji"],
                disabled=disabled,
            )
            btn.callback = self._make_learn_callback(sid)
            self.add_item(btn)

        if self.main_view:
            back_btn = discord.ui.Button(
                label="Back to MMORPG / 返回", style=discord.ButtonStyle.danger,
                row=4, emoji="🏠", custom_id="skill_back",
            )
            back_btn.callback = self._back_callback
            self.add_item(back_btn)

    def _make_learn_callback(self, skill_id: str):
        async def cb(interaction: discord.Interaction):
            sdef = SKILLS[skill_id]
            uid = str(interaction.user.id)
            user_level = _get_user_level(uid)
            if user_level < sdef["min_level"]:
                return await interaction.response.send_message(
                    f"等级不足 Need Lv.{sdef['min_level']} / You are Lv.{user_level}", ephemeral=True)
            if skill_id in _get_learned_skills(uid):
                return await interaction.response.send_message(
                    f"已学会该技能 Already learned!", ephemeral=True)
            bal = _get_balance(uid)
            if bal < sdef["price"]:
                return await interaction.response.send_message(
                    f"金币不足 Insufficient coins. Need 🪙 {sdef['price']:,}, you have 🪙 {bal:,}", ephemeral=True)

            _add_coins(uid, -sdef["price"], f"Learn skill / 学习技能: {sdef['name']}")
            with get_db_ctx() as conn:
                conn.execute(
                    "INSERT INTO player_skills (user_id, skill_id, level, equipped) VALUES (?, ?, 1, 0)",
                    (uid, skill_id),
                )
                conn.commit()

            self._build()
            try:
                await interaction.message.edit(embed=self.build_main_embed(), view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

            new_bal = _get_balance(uid)
            await interaction.response.send_message(
                f"✅ 学会了 {sdef['emoji']} **{sdef['name']}**！余额 / Balance: 🪙 {new_bal:,}",
                ephemeral=True,
            )
        return cb

    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            from cogs.mmorpg_shop import _get_user_stats, _get_balance
            uid = str(self.uid)
            stats = _get_user_stats(uid)
            bal = _get_balance(uid)
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
    await bot.add_cog(Skills(bot))
