"""
GMPT Bot — MMORPG Class System / MMORPG 职业系统

6 classes with passive effects + exclusive skills.
/gmpt-class info — View all classes / 查看所有职业
/gmpt-class choose — Choose a class / 选择职业（首次免费，更换 500G）
Data stored in users table: mmorpg_class TEXT column.
"""
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db, get_db_ctx
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Class Definitions
# ══════════════════════════════════════════════════════════════
CLASS_DEFS = {
    "warrior": {
        "name_cn": "战士",
        "name_en": "Warrior",
        "emoji": "⚔️",
        "passive_cn": "HP +20%, ATK +10%",
        "passive_en": "HP +20%, ATK +10%",
        "skill_cn": "旋风斩 / Whirlwind — 全体伤害",
        "skill_en": "Whirlwind — AoE damage to all enemies",
        "color": 0xE74C3C,
        "hp_bonus": 20,
        "atk_bonus": 10,
        "def_bonus": 0,
        "mp_bonus": 0,
        "matk_bonus": 0,
        "crit_bonus": 0,
        "spd_bonus": 0,
    },
    "mage": {
        "name_cn": "法师",
        "name_en": "Mage",
        "emoji": "🔮",
        "passive_cn": "MP +20%, MATK +15%",
        "passive_en": "MP +20%, MATK +15%",
        "skill_cn": "火球术 / Fireball — 高伤害",
        "skill_en": "Fireball — High damage single target",
        "color": 0x3498DB,
        "hp_bonus": 0,
        "atk_bonus": 0,
        "def_bonus": 0,
        "mp_bonus": 20,
        "matk_bonus": 15,
        "crit_bonus": 0,
        "spd_bonus": 0,
    },
    "assassin": {
        "name_cn": "刺客",
        "name_en": "Assassin",
        "emoji": "🗡️",
        "passive_cn": "Crit +25%, SPD +10%",
        "passive_en": "Crit +25%, SPD +10%",
        "skill_cn": "暗杀 / Assassinate — 无视防御",
        "skill_en": "Assassinate — Ignores enemy DEF",
        "color": 0x9B59B6,
        "hp_bonus": 0,
        "atk_bonus": 0,
        "def_bonus": 0,
        "mp_bonus": 0,
        "matk_bonus": 0,
        "crit_bonus": 25,
        "spd_bonus": 10,
    },
    "priest": {
        "name_cn": "牧师",
        "name_en": "Priest",
        "emoji": "✝️",
        "passive_cn": "DEF +15%, 回合回复 5% HP",
        "passive_en": "DEF +15%, recover 5% HP per turn",
        "skill_cn": "治愈 / Heal — 恢复 30% HP",
        "skill_en": "Heal — Restore 30% HP",
        "color": 0x1ABC9C,
        "hp_bonus": 0,
        "atk_bonus": 0,
        "def_bonus": 15,
        "mp_bonus": 0,
        "matk_bonus": 0,
        "crit_bonus": 0,
        "spd_bonus": 0,
    },
    "paladin": {
        "name_cn": "圣骑士",
        "name_en": "Paladin",
        "emoji": "🛡️",
        "passive_cn": "DEF +25%, HP +10%",
        "passive_en": "DEF +25%, HP +10%",
        "skill_cn": "圣盾 / Divine Shield — 2 回合无敌",
        "skill_en": "Divine Shield — Invincible for 2 turns",
        "color": 0xF1C40F,
        "hp_bonus": 10,
        "atk_bonus": 0,
        "def_bonus": 25,
        "mp_bonus": 0,
        "matk_bonus": 0,
        "crit_bonus": 0,
        "spd_bonus": 0,
    },
    "archer": {
        "name_cn": "弓箭手",
        "name_en": "Archer",
        "emoji": "🏹",
        "passive_cn": "SPD +20%, ATK +10%",
        "passive_en": "SPD +20%, ATK +10%",
        "skill_cn": "连射 / Barrage — 攻击 3 次",
        "skill_en": "Barrage — Attacks 3 times",
        "color": 0x2ECC71,
        "hp_bonus": 0,
        "atk_bonus": 10,
        "def_bonus": 0,
        "mp_bonus": 0,
        "matk_bonus": 0,
        "crit_bonus": 0,
        "spd_bonus": 20,
    },
}

# ══════════════════════════════════════════════════════════════
# Data helpers
# ══════════════════════════════════════════════════════════════

def _get_class(uid: str) -> str | None:
    """Return the user's current class key, or None."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT mmorpg_class FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    if row and row[0]:
        return row[0]
    return None


def _set_class(uid: str, class_key: str):
    with get_db_ctx() as conn:
        conn.execute(
            "UPDATE users SET mmorpg_class = ? WHERE discord_id = ?",
            (class_key, uid),
        )
        conn.commit()


def _get_balance(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT score FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return row["score"] if row else 0


def _add_coins(uid: str, amount: int, reason: str = ""):
    with get_db_ctx() as conn:
        conn.execute(
            "UPDATE users SET score = score + ? WHERE discord_id = ?",
            (amount, uid),
        )
        conn.execute(
            "INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
            (uid, amount, reason),
        )
        conn.commit()


# ══════════════════════════════════════════════════════════════
# Views
# ══════════════════════════════════════════════════════════════

class ClassSelectView(discord.ui.View):
    """View with buttons for each class."""

    COST_CHANGE = 500

    def __init__(self, user_id: str, current_class: str | None, balance: int = None, main_view=None):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.current_class = current_class
        self.balance = balance if balance is not None else _get_balance(user_id)
        self.main_view = main_view
        self._build()

    def build_main_embed(self):
        embed = discord.Embed(
            title="MMORPG Class System / MMORPG 职业系统",
            description="点击下方按钮选择职业 / Click a button to choose your class",
            color=0x9B59B6,
        )
        if self.current_class:
            cd = CLASS_DEFS.get(self.current_class)
            if cd:
                embed.add_field(
                    name=f"当前职业 / Current: {cd['emoji']} {cd['name_cn']} / {cd['name_en']}",
                    value=f"被动: {cd['passive_cn']}\n技能: {cd['skill_cn']}",
                    inline=False,
                )
        else:
            embed.add_field(
                name="未选择 / None selected",
                value="首次选择免费 / First choice is free!\n更换职业: 500G / Change class: 500G",
                inline=False,
            )
        embed.set_footer(text=f"余额 / Balance: {self.balance:,}G")
        return embed

    def _build(self):
        self.clear_items()

        row = 0
        for key, cd in CLASS_DEFS.items():
            is_current = self.current_class == key
            label = f"{cd['emoji']} {cd['name_cn']} / {cd['name_en']}"
            if is_current:
                label += " ✅"
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.success if is_current else discord.ButtonStyle.primary,
                row=row // 3,
                disabled=is_current,
                custom_id=f"class_{key}",
            )
            btn.callback = self._make_class_callback(key)
            self.add_item(btn)
            row += 1

        if self.main_view:
            back_btn = discord.ui.Button(
                label="Back to MMORPG / 返回", style=discord.ButtonStyle.danger,
                row=2, emoji="🏠", custom_id="cls_back",
            )
            back_btn.callback = self._back_callback
            self.add_item(back_btn)

    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "Not your panel / 这不是你的面板", ephemeral=True
            )
            return False
        return True

    def _make_class_callback(self, class_key: str):
        async def cb(interaction: discord.Interaction):
            cd = CLASS_DEFS[class_key]
            cost = self.COST_CHANGE if self.current_class else 0

            if cost > 0 and self.balance < cost:
                await interaction.response.send_message(
                    f"❌ 余额不足！需要 🪙 **{cost}**G，你只有 **{self.balance}**G\n"
                    f"Need 🪙 **{cost}**G, you have **{self.balance}**G",
                    ephemeral=True,
                )
                return

            if cost > 0:
                _add_coins(self.user_id, -cost, f"Change class to {class_key}")

            _set_class(self.user_id, class_key)
            self.current_class = class_key
            self.balance = _get_balance(self.user_id)
            self._build()

            embed = self.build_main_embed()
            try:
                await interaction.message.edit(embed=embed, view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

            changetext = f"花费 🪙 **{cost}**G" if cost > 0 else "免费 / Free"
            await interaction.response.send_message(
                f"✅ 职业切换成功！{changetext}\n"
                f"New class: {cd['emoji']} **{cd['name_cn']} / {cd['name_en']}**",
                ephemeral=True,
            )
        return cb

    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            from cogs.mmorpg_shop import _get_user_stats
            uid = str(self.user_id)
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


# ══════════════════════════════════════════════════════════════
# Class Cog
# ══════════════════════════════════════════════════════════════
class MMORPGClass(CogBase):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    # ── Autocomplete for class keys ──
    async def _class_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        choices = []
        for key, cdef in CLASS_DEFS.items():
            display = f"{cdef['emoji']} {cdef['name_cn']} / {cdef['name_en']}"
            if not current or current.lower() in display.lower() or current.lower() in key:
                choices.append(app_commands.Choice(name=display, value=key))
        return choices[:25]

    # ══════════════════════════════════════════════════════════
    # /gmpt-class info
    # ══════════════════════════════════════════════════════════
    @app_commands.command(name="gmpt-class", description="View all classes / 查看所有职业")
    @app_commands.describe(action="info or choose / 查看或选择", class_name="Class key / 职业代号")
    @app_commands.choices(action=[
        app_commands.Choice(name="查看职业 / Info", value="info"),
        app_commands.Choice(name="选择职业 / Choose", value="choose"),
    ])
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def class_cmd(
        self,
        interaction: discord.Interaction,
        action: str = "info",
        class_name: str | None = None,
    ):
        """MMORPG Class command — info or choose."""
        uid = str(interaction.user.id)
        current_key = _get_class(uid)

        if action == "info":
            embed = discord.Embed(
                title="MMORPG Class System / MMORPG 职业系统",
                color=0x9B59B6,
            )
            lines = []
            if current_key:
                cd = CLASS_DEFS.get(current_key)
                if cd:
                    lines.append(
                        f"**当前职业 / Current Class:** {cd['emoji']} **{cd['name_cn']} / {cd['name_en']}**\n"
                        f"　被动 / Passive: {cd['passive_cn']}\n"
                        f"　技能 / Skill: {cd['skill_cn']}\n"
                    )
            else:
                lines.append("**未选择职业 / No class selected**\n")
            lines.append("")

            # List all
            for key, cd in CLASS_DEFS.items():
                lines.append(
                    f"{cd['emoji']} **{cd['name_cn']} / {cd['name_en']}**\n"
                    f"　被动 / Passive: {cd['passive_cn']}\n"
                    f"　专属技能 / Skill: {cd['skill_cn']}"
                )

            embed.description = "\n".join(lines)
            embed.set_footer(text="选择: /gmpt-class choose <class> / 首次免费，更换 500G")
            view = ClassSelectView(uid, current_key)
            await interaction.response.send_message(embed=embed, view=view)

        elif action == "choose":
            if class_name is None or class_name not in CLASS_DEFS:
                valid_keys = ", ".join(f"`{k}`" for k in CLASS_DEFS)
                return await interaction.response.send_message(
                    f"请选择有效职业 / Please choose a valid class: {valid_keys}\n"
                    f"示例 / Example: `/gmpt-class choose mage`",
                    ephemeral=True,
                )
            cd = CLASS_DEFS[class_name]

            if current_key is None:
                # First choice free
                _set_class(uid, class_name)
                try:
                    await interaction.response.defer()
                except discord.InteractionResponded:
                    pass
                from utils.animations import class_select_animation
                await class_select_animation(
                    interaction, f"{cd['name_cn']} / {cd['name_en']}", cd['emoji']
                )
            elif current_key == class_name:
                return await interaction.response.send_message(
                    f"{cd['emoji']} 你已经是 **{cd['name_cn']} / {cd['name_en']}** 了！\n"
                    f"You are already a **{cd['name_cn']}**!",
                    ephemeral=True,
                )
            else:
                # Change class costs 500G
                cost = 500
                bal = _get_balance(uid)
                if bal < cost:
                    return await interaction.response.send_message(
                        f"❌ 余额不足！更换职业需要 🪙 {cost}，你只有 🪙 {bal:,}\n"
                        f"Not enough coins! Change costs {cost}G, you have {bal}G.",
                        ephemeral=True,
                    )
                _add_coins(uid, -cost, f"转职 {class_name} / Class change to {class_name}")
                _set_class(uid, class_name)
                try:
                    await interaction.response.defer()
                except discord.InteractionResponded:
                    pass
                from utils.animations import class_select_animation
                await class_select_animation(
                    interaction, f"{cd['name_cn']} / {cd['name_en']}", cd['emoji']
                )


async def setup(bot):
    await bot.add_cog(MMORPGClass(bot))
