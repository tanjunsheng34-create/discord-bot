"""
GMPT Bot — MMORPG Stats Panel / MMORPG 属性面板
/gmpt-stats — View detailed character stats / 查看详细角色属性
"""
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase


def _get_user_stats(uid: str):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT hp, max_hp, mp, max_mp, attack, defense, level, xp FROM users WHERE discord_id = ?",
            (uid,),
        )
        row = cur.fetchone()
    if row:
        return dict(row)
    return {"hp": 100, "max_hp": 100, "mp": 50, "max_mp": 50, "attack": 10, "defense": 5, "level": 1, "xp": 0}


def _get_balance(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT score FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return row["score"] if row else 0


def _get_equipped(uid: str) -> dict:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT slot, name, quality, stat, stat_value, emoji FROM user_equipment WHERE user_id=?", (uid,))
        rows = cur.fetchall()
    result = {}
    for r in rows:
        result[r["slot"]] = dict(r)
    return result


def _get_total_coins_earned(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE discord_id = ? AND amount > 0", (uid,))
        row = cur.fetchone()
    return row["total"] if row else 0


def _get_player_stats(uid: str) -> dict:
    """Get RPG-like stats: SPD, CRIT, ACC, EVA."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT spd, crit_rate, accuracy, evasion, boss_kills, pvp_wins, dungeon_clears FROM users WHERE discord_id = ?",
            (uid,),
        )
        row = cur.fetchone()
    if row:
        return {
            "spd": row["spd"] or 5,
            "crit_rate": row["crit_rate"] or 5,
            "accuracy": row["accuracy"] or 90,
            "evasion": row["evasion"] or 3,
            "boss_kills": row["boss_kills"] or 0,
            "pvp_wins": row["pvp_wins"] or 0,
            "dungeon_clears": row["dungeon_clears"] or 0,
        }
    return {"spd": 5, "crit_rate": 5, "accuracy": 90, "evasion": 3, "boss_kills": 0, "pvp_wins": 0, "dungeon_clears": 0}


class StatsView(discord.ui.View):
    """Stats panel with Refresh and Back buttons."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=None)
        self.uid = uid
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        """Build stats embed for main panel integration."""
        return build_stats_embed(self.uid)

    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Refresh", emoji="\U0001f504", style=discord.ButtonStyle.primary, row=0)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_stats_embed(self.uid, interaction.user.display_name)
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Back 返回", emoji="\U0001f519", style=discord.ButtonStyle.secondary, row=0)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(self.uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.followup.edit_message(embed=embed, view=self.main_view)
        else:
            await interaction.response.edit_message(content="Main panel not available.", view=None)


def build_stats_embed(uid: str, display_name: str = None) -> discord.Embed:
    """Build the detailed stats embed."""
    stats = _get_user_stats(uid)
    pstats = _get_player_stats(uid)
    bal = _get_balance(uid)
    equipped = _get_equipped(uid)
    total_earned = _get_total_coins_earned(uid)

    from cogs.mmorpg_class import _get_class, CLASS_DEFS
    current_key = _get_class(uid)
    if current_key and current_key in CLASS_DEFS:
        cd = CLASS_DEFS[current_key]
        class_emoji = cd["emoji"]
        class_name = f"{cd['name_cn']} / {cd['name_en']}"
    else:
        class_emoji = "\U0001f9d1"
        class_name = "\u672a\u9009\u62e9 / None"

    xp_for_level = 1000
    xp_progress = stats["xp"] % xp_for_level

    embed = discord.Embed(
        title=f"\U0001f4ca {display_name or 'Adventurer'}\u2019s Stats / \u5c5e\u6027\u9762\u677f",
        color=0x9B59B6,
    )

    # Header info
    embed.add_field(
        name=f"{class_emoji} Class / \u804c\u4e1a",
        value=f"**{class_name}** Lv.**{stats['level']}**",
        inline=True,
    )
    embed.add_field(
        name="\u26a1 Total EXP / \u603b\u7ecf\u9a8c",
        value=f"**{xp_progress:,}** / {xp_for_level:,}",
        inline=True,
    )
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    # Core stats - two column
    embed.add_field(name="\u2764\ufe0f HP", value=f"**{stats['hp']}** / {stats['max_hp']}", inline=True)
    embed.add_field(name="\U0001f4a1 MP", value=f"**{stats['mp']}** / {stats['max_mp']}", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    embed.add_field(name="\u2694\ufe0f ATK", value=f"**{stats['attack']}**", inline=True)
    embed.add_field(name="\U0001f6e1\ufe0f DEF", value=f"**{stats['defense']}**", inline=True)
    embed.add_field(name="\u26a1 SPD", value=f"**{pstats['spd']}**", inline=True)

    embed.add_field(name="\U0001f4a5 CRIT", value=f"**{pstats['crit_rate']}%**", inline=True)
    embed.add_field(name="\U0001f3af ACC", value=f"**{pstats['accuracy']}%**", inline=True)
    embed.add_field(name="\U0001f6e1\ufe0f EVA", value=f"**{pstats['evasion']}%**", inline=True)

    # Equipment section
    embed.add_field(name="\u2501" * 20, value="\u200b", inline=False)
    embed.add_field(
        name="\U0001f6e1\ufe0f Equipped / \u88c5\u5907\u4e2d",
        value="\u200b",
        inline=False,
    )

    slot_labels = {"weapon": "\u2694\ufe0f Weapon", "armor": "\U0001f6e1\ufe0f Armor", "helmet": "\u26d1\ufe0f Helmet", "ring": "\U0001f48d Ring", "accessory": "\U0001f4bf Accessory"}
    for slot in ["weapon", "armor", "helmet", "ring", "accessory"]:
        eq = equipped.get(slot)
        if eq:
            label = slot_labels.get(slot, slot)
            embed.add_field(
                name=label,
                value=f"**{eq['name']}** (+{eq['stat_value']} {eq['stat'].upper()})",
                inline=True,
            )
        else:
            embed.add_field(name=slot_labels.get(slot, slot), value="\u2b1c Empty / \u7a7a", inline=True)

    # Statistics section
    embed.add_field(name="\u2501" * 20, value="\u200b", inline=False)
    embed.add_field(
        name="\U0001f4ca Records / \u7edf\u8ba1",
        value=(
            f"\U0001f409 Boss Kills: **{pstats['boss_kills']}**\n"
            f"\u2694\ufe0f PVP Wins: **{pstats['pvp_wins']}**\n"
            f"\U0001f3f0 Dungeon Clears: **{pstats['dungeon_clears']}**\n"
            f"\U0001f4b0 Total Coins Earned: **{total_earned:,}**\n"
            f"\U0001f4b0 Current Balance: **{bal:,}**"
        ),
        inline=False,
    )

    embed.set_footer(text=f"{display_name or 'Player'}  |  /gmpt-stats")
    return embed


class MMORPGStats(CogBase):
    """MMORPG Stats Panel / MMORPG 属性面板"""

    def __init__(self, bot):
        super().__init__()
        self._init_stats_columns()

    def _init_stats_columns(self):
        """Ensure extra stat columns exist in users table."""
        extra_cols = {
            "spd": "INTEGER DEFAULT 5",
            "crit_rate": "INTEGER DEFAULT 5",
            "accuracy": "INTEGER DEFAULT 90",
            "evasion": "INTEGER DEFAULT 3",
            "boss_kills": "INTEGER DEFAULT 0",
            "pvp_wins": "INTEGER DEFAULT 0",
            "dungeon_clears": "INTEGER DEFAULT 0",
        }
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(users)")
            existing = {r["name"] for r in cur.fetchall()}
            for col, col_def in extra_cols.items():
                if col not in existing:
                    cur.execute(f"ALTER TABLE users ADD COLUMN {col} {col_def}")
            conn.commit()

    @app_commands.command(name="gmpt-mmorpg-stats", description="\U0001f4ca View detailed character stats / 查看详细角色属性")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def stats_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        embed = build_stats_embed(uid, interaction.user.display_name)
        view = StatsView(uid)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(MMORPGStats(bot))
