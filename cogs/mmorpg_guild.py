"""
GMPT Bot — MMORPG Guild System / 公会系统
/gmpt-guild — 公会管理

创建/加入/退出公会，捐献获取贡献，解锁公会技能。
"""
import datetime
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Guild skills: skill_id -> (name_cn, name_en, max_level, description_cn, description_en)
# ══════════════════════════════════════════════════════════════
GUILD_SKILLS = {
    1: ("EXP加成", "EXP Boost", 5, "EXP +{}%", "EXP +{}%"),
    2: ("金币加成", "Gold Boost", 5, "金币获得 +{}%", "Gold gain +{}%"),
    3: ("攻击力加成", "ATK Boost", 5, "攻击力 +{}%", "Attack +{}%"),
    4: ("防御力加成", "DEF Boost", 5, "防御力 +{}%", "Defense +{}%"),
    5: ("暴击率", "Crit Rate", 5, "暴击率 +{}%", "Crit rate +{}%"),
    6: ("HP加成", "HP Boost", 5, "最大HP +{}%", "Max HP +{}%"),
    7: ("掉落率", "Drop Rate", 5, "掉落率 +{}%", "Drop rate +{}%"),
    8: ("减伤", "Damage Reduction", 5, "减伤 +{}%", "Dmg reduction +{}%"),
    9: ("治疗加成", "Healing Boost", 5, "治疗量 +{}%", "Healing +{}%"),
    10: ("元素抗性", "Element Resist", 5, "元素抗性 +{}%", "Element resist +{}%"),
}

SKILL_VALUE_MAP = {
    1: {1: 5, 2: 10, 3: 15, 4: 20, 5: 25},     # EXP %
    2: {1: 5, 2: 10, 3: 15, 4: 20, 5: 25},     # Gold %
    3: {1: 5, 2: 10, 3: 15, 4: 20, 5: 25},     # ATK %
    4: {1: 5, 2: 10, 3: 15, 4: 20, 5: 25},     # DEF %
    5: {1: 3, 2: 5, 3: 8, 4: 12, 5: 15},       # Crit %
    6: {1: 5, 2: 10, 3: 15, 4: 20, 5: 25},     # HP %
    7: {1: 3, 2: 5, 3: 8, 4: 12, 5: 15},       # Drop rate %
    8: {1: 2, 2: 4, 3: 6, 4: 8, 5: 10},        # Dmg reduction %
    9: {1: 5, 2: 10, 3: 15, 4: 20, 5: 25},     # Healing %
    10: {1: 5, 2: 10, 3: 15, 4: 20, 5: 25},    # Element resist %
}

SKILL_UPGRADE_CONTRIBUTION = {1: 500, 2: 2000, 3: 5000, 4: 10000, 5: 20000}

GUILD_CREATE_COST = 1000
GUILD_MAX_LEVEL = 10
GUILD_LEVEL_CONTRIBUTION = {1: 0, 2: 5000, 3: 15000, 4: 35000, 5: 70000,
                            6: 120000, 7: 200000, 8: 350000, 9: 500000, 10: 750000}


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


def _get_coins(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT score FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return (row["score"] or 0) if row else 0


def _get_guild_member_count(guild_id: int) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM mmorpg_guild_members WHERE guild_id = ?", (guild_id,))
        row = cur.fetchone()
    return row["cnt"] if row else 0


def _get_user_guild(uid: str) -> dict | None:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT g.*, gm.contribution, gm.joined_at FROM mmorpg_guilds g "
            "JOIN mmorpg_guild_members gm ON g.id = gm.guild_id WHERE gm.user_id = ?",
            (uid,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _get_guild_level(total_contrib: int) -> int:
    level = 1
    for lv in range(2, GUILD_MAX_LEVEL + 1):
        if total_contrib >= GUILD_LEVEL_CONTRIBUTION[lv]:
            level = lv
        else:
            break
    return level


# ══════════════════════════════════════════════════════════════
# DB Init
# ══════════════════════════════════════════════════════════════
def _init_guild_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mmorpg_guilds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                owner_id TEXT NOT NULL,
                level INTEGER NOT NULL DEFAULT 1,
                exp INTEGER NOT NULL DEFAULT 0,
                total_contribution INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mmorpg_guild_members (
                user_id TEXT NOT NULL,
                guild_id INTEGER NOT NULL,
                contribution INTEGER NOT NULL DEFAULT 0,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (user_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mmorpg_guild_skills (
                guild_id INTEGER NOT NULL,
                skill_id INTEGER NOT NULL,
                level INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, skill_id)
            )
        """)
        conn.commit()

_init_guild_tables()


def _init_guild_skills(guild_id: int):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        for skill_id in GUILD_SKILLS:
            cur.execute(
                "INSERT OR IGNORE INTO mmorpg_guild_skills (guild_id, skill_id, level) VALUES (?, ?, 0)",
                (guild_id, skill_id),
            )
        conn.commit()


# ══════════════════════════════════════════════════════════════
# GuildPanelView — Main UI
# ══════════════════════════════════════════════════════════════
class GuildPanelView(discord.ui.View):
    """公会主面板 / Guild main panel."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        guild = _get_user_guild(self.uid)
        if not guild:
            embed = discord.Embed(
                title="🏰 Guild / 公会",
                description=(
                    "You are not in a guild yet!\n你还没有加入公会！\n\n"
                    "Use `/gmpt-guild create <name>` to create one (🪙 1,000)\n"
                    "使用 `/gmpt-guild create <名称>` 创建公会 (🪙 1,000)\n"
                    "Or `/gmpt-guild join <id>` to join!\n"
                    "或使用 `/gmpt-guild join <ID>` 加入！"
                ),
                color=0x607D8B,
            )
            return embed

        member_count = _get_guild_member_count(guild["id"])
        level = _get_guild_level(guild["total_contribution"])
        next_level_req = GUILD_LEVEL_CONTRIBUTION.get(level + 1, 0) if level < GUILD_MAX_LEVEL else -1

        desc = (
            f"**{guild['name']}** — Lv.{level}\n"
            f"Owner / 会长: <@{guild['owner_id']}>\n"
            f"Members / 成员: {member_count}\n"
            f"Total Contribution / 总贡献: {guild['total_contribution']:,}\n"
        )
        if next_level_req > 0:
            pct = min(100, int(guild["total_contribution"] / next_level_req * 100))
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            desc += f"Next Level: {bar} {guild['total_contribution']:,}/{next_level_req:,} ({pct}%)\n"

        desc += f"\nYour Contribution / 你的贡献: {guild['contribution']:,}"

        embed = discord.Embed(
            title=f"🏰 Guild / 公会 — {guild['name']}",
            description=desc,
            color=0x8E44AD,
        )

        # Skills
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT skill_id, level FROM mmorpg_guild_skills WHERE guild_id = ? ORDER BY skill_id",
                (guild["id"],),
            )
            skills = cur.fetchall()

        skill_lines = []
        for s in skills:
            sinfo = GUILD_SKILLS.get(s["skill_id"])
            if sinfo and s["level"] > 0:
                value = SKILL_VALUE_MAP[s["skill_id"]].get(s["level"], 0)
                desc_text = sinfo[3].format(value)
                skill_lines.append(f"✨ {sinfo[0]} Lv.{s['level']}: {desc_text}")
            elif sinfo:
                skill_lines.append(f"⬜ {sinfo[0]}: Locked / 未解锁")

        if skill_lines:
            embed.add_field(name="Skills / 公会技能", value="\n".join(skill_lines), inline=False)
        else:
            embed.add_field(name="Skills / 公会技能", value="No skills unlocked / 无已解锁技能", inline=False)

        embed.set_footer(text="Donate gold to unlock guild skills! | 捐献金币解锁公会技能！")
        return embed

    @discord.ui.button(label="Donate 捐献", emoji="💰", style=discord.ButtonStyle.success, row=0)
    async def donate_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel", ephemeral=True)
            return

        guild = _get_user_guild(uid)
        if not guild:
            embed = discord.Embed(
                title="💰 Donate / 捐献",
                description="You are not in a guild!\n你还没有加入公会！",
                color=0xE74C3C,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)
            return

        # Default donate 100
        donate_amount = 100
        coins = _get_coins(uid)
        if coins < donate_amount:
            embed = discord.Embed(
                title="💰 Donate Failed / 捐献失败",
                description=f"Need 🪙 {donate_amount:,} but you have {coins:,}.",
                color=0xE74C3C,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)
            return

        _add_coins(uid, -donate_amount, f"公会捐献 — Guild Donation: {guild['name']}")

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE mmorpg_guilds SET total_contribution = total_contribution + ? WHERE id = ?",
                (donate_amount, guild["id"]),
            )
            cur.execute(
                "UPDATE mmorpg_guild_members SET contribution = contribution + ? WHERE user_id = ?",
                (donate_amount, uid),
            )
            conn.commit()

        embed = discord.Embed(
            title="💰 Donation Success! / 捐献成功！",
            description=(
                f"Donated 🪙 **{donate_amount:,}** to {guild['name']}!\n"
                f"Your contribution: {guild['contribution'] + donate_amount:,}\n"
                f"Guild total: {guild['total_contribution'] + donate_amount:,}"
            ),
            color=0x2ECC71,
        )

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Members 成员", emoji="📊", style=discord.ButtonStyle.primary, row=0)
    async def members_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel", ephemeral=True)
            return

        guild = _get_user_guild(uid)
        if not guild:
            await interaction.response.send_message("Not in a guild.", ephemeral=True)
            return

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT user_id, contribution FROM mmorpg_guild_members WHERE guild_id = ? ORDER BY contribution DESC LIMIT 20",
                (guild["id"],),
            )
            members = cur.fetchall()

        lines = []
        for i, m in enumerate(members, 1):
            tag = "👑" if m["user_id"] == guild["owner_id"] else "👤"
            lines.append(f"{i}. {tag} <@{m['user_id']}> — {m['contribution']:,} 贡献")

        embed = discord.Embed(
            title=f"📊 Members / 成员 — {guild['name']}",
            description="\n".join(lines),
            color=0x3498DB,
        )

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Skills 技能", emoji="✨", style=discord.ButtonStyle.primary, row=0)
    async def skills_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel", ephemeral=True)
            return

        guild = _get_user_guild(uid)
        if not guild:
            await interaction.response.send_message("Not in a guild.", ephemeral=True)
            return

        # Only owner can unlock/upgrade skills
        if uid != guild["owner_id"]:
            embed = discord.Embed(
                title="✨ Skills / 公会技能",
                description="Only the guild owner can unlock skills.\n只有会长可以解锁技能。",
                color=0xF39C12,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)
            return

        view = GuildSkillView(self.uid, guild, main_view=self)
        embed = view.build_embed()

        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="Storage 公会仓库", emoji="📦", style=discord.ButtonStyle.primary, row=0)
    async def storage_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Guild Storage / 公会仓库."""
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel", ephemeral=True)
            return

        guild = _get_user_guild(uid)
        if not guild:
            await interaction.response.send_message("Not in a guild.", ephemeral=True)
            return

        view = GuildStorageView(self.uid, guild, main_view=self)
        embed = view.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="Guild War 公会战", emoji="⚔️", style=discord.ButtonStyle.danger, row=0)
    async def war_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel", ephemeral=True)
            return

        guild = _get_user_guild(uid)
        if not guild:
            await interaction.response.send_message("Not in a guild.", ephemeral=True)
            return

        embed = discord.Embed(
            title="⚔️ Guild War / 公会战",
            description=(
                "Guild Wars happen every **Saturday 20:00**!\n"
                "公会战在 **每周六 20:00** 自动开启！\n\n"
                f"**{guild['name']}** is ready for battle!\n"
                "Use `/gmpt-guild-war` to join the fight! / 用 `/gmpt-guild-war` 参战！"
            ),
            color=0xE74C3C,
        )

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(self.uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
        else:
            embed = discord.Embed(
                title="🏰 Guild / 公会",
                description="Use `/gmpt-mmorpg` to return.",
                color=0x95A5A6,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass



# ══════════════════════════════════════════════════════════════
# GuildStorageView — Guild shared storage
# ══════════════════════════════════════════════════════════════
class GuildStorageView(discord.ui.View):
    """公会仓库面板 / Guild Storage panel."""

    def __init__(self, uid: str, guild: dict, main_view=None):
        super().__init__(timeout=180)
        self.uid = uid
        self.guild = guild
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, item_name, item_type, quantity, donated_by, exchange_price "
                "FROM guild_storage WHERE guild_id = ? AND quantity > 0 ORDER BY id",
                (self.guild["id"],),
            )
            items = [dict(r) for r in cur.fetchall()]

        embed = discord.Embed(
            title=f"📦 Guild Storage / 公会仓库 — {self.guild['name']}",
            color=0x8E44AD,
        )
        if not items:
            embed.description = "仓库空空如也 / Storage is empty.\n使用 `/gmpt-guild donate-item` 捐献物品！"
        else:
            lines = []
            for item in items:
                price_str = f"{item['exchange_price']}贡献" if item['exchange_price'] > 0 else "免费"
                lines.append(
                    f"**#{item['id']}** {item['item_name']} x{item['quantity']} "
                    f"({item['item_type']}) — {price_str} | by <@{item['donated_by']}>"
                )
            embed.description = "\n".join(lines[:20])
            if len(items) > 20:
                embed.set_footer(text=f"... 及另外 {len(items) - 20} 件物品")

        embed.add_field(
            name="使用方式 / How to Use",
            value=(
                "捐献 / Donate: `/gmpt-guild donate-item`\n"
                "兑换 / Exchange: 点击下方兑换按钮\n"
                "设置价格: 管理员 `/gmpt-guild set-storage-price`"
            ),
            inline=False,
        )
        return embed

    @discord.ui.button(label="🔄 Exchange / 兑换", style=discord.ButtonStyle.primary, row=0)
    async def exchange_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "使用 `/gmpt-guild exchange <item_id>` 兑换仓库物品。\n"
            "Use `/gmpt-guild exchange <item_id>` to exchange storage items.",
            ephemeral=True,
        )

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.main_view:
            view = GuildPanelView(self.uid, main_view=self.main_view)
            embed = view.build_embed()
            try:
                await interaction.response.edit_message(embed=embed, view=view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=view)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass


class GuildSkillView(discord.ui.View):
    """公会技能管理面板 (会长专用)."""

    def __init__(self, uid: str, guild: dict, main_view=None):
        super().__init__(timeout=120)
        self.uid = uid
        self.guild = guild
        self.main_view = main_view

        # Add skill upgrade buttons
        available = []
        for skill_id in GUILD_SKILLS:
            current_level = self._get_skill_level(guild["id"], skill_id)
            max_lvl = GUILD_SKILLS[skill_id][2]
            if current_level < max_lvl:
                available.append(skill_id)

        if not available:
            self._add_label("All skills maxed! / 所有技能已满级！")
            return

        options = []
        for sid in available:
            sinfo = GUILD_SKILLS[sid]
            current = self._get_skill_level(guild["id"], sid)
            cost = SKILL_UPGRADE_CONTRIBUTION.get(current + 1, 99999)
            label = f"{sinfo[0]} Lv.{current}→{current + 1} ({cost}贡献)"
            options.append(discord.SelectOption(label=label[:100], value=str(sid)))

        select = discord.ui.Select(
            placeholder="Select skill to upgrade... / 选择要升级的技能...",
            options=options,
            row=0,
        )
        select.callback = self._skill_callback
        self.add_item(select)

    def _get_skill_level(self, guild_id: int, skill_id: int) -> int:
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT level FROM mmorpg_guild_skills WHERE guild_id = ? AND skill_id = ?",
                (guild_id, skill_id),
            )
            row = cur.fetchone()
        return row["level"] if row else 0

    def build_embed(self) -> discord.Embed:
        desc_lines = []
        for skill_id in GUILD_SKILLS:
            sinfo = GUILD_SKILLS[skill_id]
            current = self._get_skill_level(self.guild["id"], skill_id)
            max_lvl = sinfo[2]
            if current > 0:
                value = SKILL_VALUE_MAP[skill_id].get(current, 0)
                desc = sinfo[3].format(value)
                desc_lines.append(f"✨ Lv.{current}/{max_lvl} — {sinfo[0]}: {desc}")
            else:
                cost = SKILL_UPGRADE_CONTRIBUTION.get(1, 0)
                desc_lines.append(f"⬜ Lv.0/{max_lvl} — {sinfo[0]} (Unlock: {cost} 贡献)")

        return discord.Embed(
            title=f"✨ Guild Skills / 公会技能 — {self.guild['name']}",
            description="\n".join(desc_lines),
            color=0x9B59B6,
        )

    async def _skill_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return

        skill_id = int(interaction.data["values"][0])
        current = self._get_skill_level(self.guild["id"], skill_id)
        next_level = current + 1
        cost = SKILL_UPGRADE_CONTRIBUTION.get(next_level, 99999)

        if self.guild["total_contribution"] < cost:
            embed = discord.Embed(
                title="✨ Upgrade Failed / 升级失败",
                description=f"Guild needs {cost} total contribution but has {self.guild['total_contribution']}.\n"
                            f"公会需要{cost}总贡献，当前仅有{self.guild['total_contribution']}。",
                color=0xE74C3C,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)
            return

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE mmorpg_guild_skills SET level = ? WHERE guild_id = ? AND skill_id = ?",
                (next_level, self.guild["id"], skill_id),
            )
            conn.commit()

        sinfo = GUILD_SKILLS[skill_id]
        value = SKILL_VALUE_MAP[skill_id].get(next_level, 0)

        embed = discord.Embed(
            title="✨ Skill Upgraded! / 技能升级！",
            description=f"**{sinfo[0]}** → Lv.{next_level}: {sinfo[3].format(value)}",
            color=0x2ECC71,
        )

        guild_panel = GuildPanelView(self.uid, main_view=self.main_view)
        try:
            await interaction.response.edit_message(embed=embed, view=guild_panel)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=guild_panel)

    def _add_label(self, text: str):
        label = discord.ui.Button(label=text, style=discord.ButtonStyle.secondary, disabled=True, row=1)
        self.add_item(label)

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = GuildPanelView(self.uid, main_view=self.main_view)
        embed = view.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)


# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass


class GuildCog(commands.Cog):
    """公会系统 / Guild System."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    guild_group = app_commands.Group(name="gmpt-guild", description="Guild System / 公会系统")

    @guild_group.command(name="create", description="Create a new guild (1000G)")
    @app_commands.describe(name="Guild name / 公会名称")
    async def guild_create(self, interaction: discord.Interaction, name: str):
        uid = str(interaction.user.id)

        # Check if already in a guild
        existing = _get_user_guild(uid)
        if existing:
            await interaction.response.send_message(
                f"You are already in guild **{existing['name']}**! Leave first.\n你已在公会 **{existing['name']}**！请先退出。",
                ephemeral=True,
            )
            return

        coins = _get_coins(uid)
        if coins < GUILD_CREATE_COST:
            await interaction.response.send_message(
                f"Need 🪙 {GUILD_CREATE_COST:,} to create a guild. You have {coins:,}.\n需要 🪙 {GUILD_CREATE_COST:,} 创建公会，你只有 {coins:,}。",
                ephemeral=True,
            )
            return

        name = name.strip()
        if len(name) < 2 or len(name) > 32:
            await interaction.response.send_message("Guild name must be 2-32 characters.", ephemeral=True)
            return

        _add_coins(uid, -GUILD_CREATE_COST, f"创建公会 — Create Guild: {name}")
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with get_db_ctx() as conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO mmorpg_guilds (name, owner_id, level, exp, total_contribution, created_at) VALUES (?, ?, 1, 0, 0, ?)",
                    (name, uid, now),
                )
                guild_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO mmorpg_guild_members (user_id, guild_id, contribution, joined_at) VALUES (?, ?, 0, ?)",
                    (uid, guild_id, now),
                )
                conn.commit()
            except Exception:
                await interaction.response.send_message(
                    "Guild name already taken!\n公会名已被占用！",
                    ephemeral=True,
                )
                return

        _init_guild_skills(guild_id)

        embed = discord.Embed(
            title="🏰 Guild Created! / 公会创建成功！",
            description=f"**{name}** has been created!\nGuild ID: {guild_id}\nOwner: <@{uid}>",
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed)

    @guild_group.command(name="join", description="Join a guild by ID")
    @app_commands.describe(guild_id="Guild ID / 公会ID")
    async def guild_join(self, interaction: discord.Interaction, guild_id: int):
        uid = str(interaction.user.id)

        existing = _get_user_guild(uid)
        if existing:
            await interaction.response.send_message(
                f"You are already in guild **{existing['name']}**! Leave first.\n你已在公会 **{existing['name']}**！",
                ephemeral=True,
            )
            return

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM mmorpg_guilds WHERE id = ?", (guild_id,))
            guild = cur.fetchone()

        if not guild:
            await interaction.response.send_message("Guild not found! / 公会不存在！", ephemeral=True)
            return

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO mmorpg_guild_members (user_id, guild_id, contribution, joined_at) VALUES (?, ?, 0, ?)",
                (uid, guild_id, now),
            )
            conn.commit()

        embed = discord.Embed(
            title="🏰 Joined Guild! / 加入公会！",
            description=f"You have joined **{guild['name']}**!\n你已加入 **{guild['name']}**！",
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed)

    @guild_group.command(name="leave", description="Leave your current guild")
    async def guild_leave(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        guild = _get_user_guild(uid)
        if not guild:
            await interaction.response.send_message("You are not in a guild! / 你不在任何公会中！", ephemeral=True)
            return

        if guild["owner_id"] == uid:
            # Transfer ownership or disband
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT user_id FROM mmorpg_guild_members WHERE guild_id = ? AND user_id != ? ORDER BY contribution DESC LIMIT 1",
                    (guild["id"], uid),
                )
                next_owner = cur.fetchone()

            if next_owner:
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute("UPDATE mmorpg_guilds SET owner_id = ? WHERE id = ?", (next_owner["user_id"], guild["id"]))
                    cur.execute("DELETE FROM mmorpg_guild_members WHERE user_id = ?", (uid,))
                    conn.commit()
                embed = discord.Embed(
                    title="🏰 Left Guild / 退出公会",
                    description=f"Ownership transferred to <@{next_owner['user_id']}>.\n"
                                f"会长已转让给 <@{next_owner['user_id']}>。",
                    color=0xF39C12,
                )
            else:
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM mmorpg_guild_members WHERE guild_id = ?", (guild["id"],))
                    cur.execute("DELETE FROM mmorpg_guild_skills WHERE guild_id = ?", (guild["id"],))
                    cur.execute("DELETE FROM mmorpg_guilds WHERE id = ?", (guild["id"],))
                    conn.commit()
                embed = discord.Embed(
                    title="🏰 Guild Disbanded / 公会解散",
                    description=f"**{guild['name']}** has been disbanded.",
                    color=0xE74C3C,
                )
        else:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM mmorpg_guild_members WHERE user_id = ?", (uid,))
                conn.commit()
            embed = discord.Embed(
                title="🏰 Left Guild / 退出公会",
                description=f"You have left **{guild['name']}**.",
                color=0xF39C12,
            )

        await interaction.response.send_message(embed=embed)

    @guild_group.command(name="info", description="View guild information")
    async def guild_info(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        guild = _get_user_guild(uid)
        if not guild:
            await interaction.response.send_message("You are not in a guild! Use `/gmpt-guild` to get started.", ephemeral=True)
            return

        view = GuildPanelView(uid)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)

    @guild_group.command(name="donate", description="Donate gold for guild contribution")
    @app_commands.describe(amount="Amount of gold to donate / 捐献金币数量")
    async def guild_donate(self, interaction: discord.Interaction, amount: int):
        uid = str(interaction.user.id)
        guild = _get_user_guild(uid)
        if not guild:
            await interaction.response.send_message("You are not in a guild!", ephemeral=True)
            return

        if amount < 10:
            await interaction.response.send_message("Minimum donation is 10G.", ephemeral=True)
            return

        coins = _get_coins(uid)
        if coins < amount:
            await interaction.response.send_message(
                f"You only have 🪙 {coins:,}. Cannot donate {amount:,}.",
                ephemeral=True,
            )
            return

        _add_coins(uid, -amount, f"公会捐献 — Guild Donation: {guild['name']}")

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE mmorpg_guilds SET total_contribution = total_contribution + ? WHERE id = ?",
                (amount, guild["id"]),
            )
            cur.execute(
                "UPDATE mmorpg_guild_members SET contribution = contribution + ? WHERE user_id = ?",
                (amount, uid),
            )
            conn.commit()

        embed = discord.Embed(
            title="💰 Donation Success! / 捐献成功！",
            description=f"Donated 🪙 **{amount:,}** to {guild['name']}!",
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed)

    @guild_group.command(name="donate-item", description="Donate an item to guild storage / 捐献物品到公会仓库")
    @app_commands.describe(item_name="物品名称 / Item name", item_type="物品类型 / Item type (equipment/potion/material)", quantity="数量 / Quantity")
    async def donate_item(self, interaction: discord.Interaction, item_name: str, item_type: str = "material", quantity: int = 1):
        uid = str(interaction.user.id)
        guild = _get_user_guild(uid)
        if not guild:
            await interaction.response.send_message("You are not in a guild!", ephemeral=True)
            return

        if quantity < 1:
            await interaction.response.send_message("Quantity must be >= 1.", ephemeral=True)
            return
        if item_type not in ("equipment", "potion", "material"):
            await interaction.response.send_message("Type must be: equipment / potion / material", ephemeral=True)
            return

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO guild_storage (guild_id, item_name, item_type, quantity, donated_by) VALUES (?, ?, ?, ?, ?)",
                (guild["id"], item_name, item_type, quantity, uid),
            )
            # Award contribution for donating
            contrib_gain = quantity * 50
            cur.execute(
                "UPDATE mmorpg_guild_members SET contribution = contribution + ? WHERE user_id = ?",
                (contrib_gain, uid),
            )
            cur.execute(
                "UPDATE mmorpg_guilds SET total_contribution = total_contribution + ? WHERE id = ?",
                (contrib_gain, guild["id"]),
            )
            conn.commit()

        await interaction.response.send_message(
            f"📦 Donated **{item_name}** x{quantity} ({item_type}) to guild storage! +{contrib_gain}贡献 / 捐献成功！"
        )

    @guild_group.command(name="exchange", description="Exchange guild storage item with contribution / 用贡献兑换仓库物品")
    @app_commands.describe(item_id="仓库物品ID / Storage item ID")
    async def exchange_item(self, interaction: discord.Interaction, item_id: int):
        uid = str(interaction.user.id)
        guild = _get_user_guild(uid)
        if not guild:
            await interaction.response.send_message("You are not in a guild!", ephemeral=True)
            return

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM guild_storage WHERE id = ? AND guild_id = ?",
                (item_id, guild["id"]),
            )
            item = cur.fetchone()

        if not item:
            await interaction.response.send_message("Item not found! / 物品不存在！", ephemeral=True)
            return
        if item["quantity"] <= 0:
            await interaction.response.send_message("Item out of stock! / 物品已兑完！", ephemeral=True)
            return

        price = item["exchange_price"]
        if price > 0 and guild["contribution"] < price:
            await interaction.response.send_message(
                f"You need {price} contribution, but have {guild['contribution']}. / 贡献不足！",
                ephemeral=True,
            )
            return

        # Deduct contribution and item
        with get_db_ctx() as conn:
            cur = conn.cursor()
            if price > 0:
                cur.execute(
                    "UPDATE mmorpg_guild_members SET contribution = contribution - ? WHERE user_id = ?",
                    (price, uid),
                )
            cur.execute(
                "UPDATE guild_storage SET quantity = quantity - 1 WHERE id = ?",
                (item_id,),
            )
            conn.commit()

        await interaction.response.send_message(
            f"🔄 Exchanged **{item['item_name']}** for {price} contribution! / 兑换成功！"
        )

    @guild_group.command(name="set-storage-price", description="Set exchange price for storage item (admin only) / 设置仓库物品兑换价格")
    @app_commands.describe(item_id="仓库物品ID / Storage item ID", price="兑换价格(贡献值) / Exchange price")
    async def set_storage_price(self, interaction: discord.Interaction, item_id: int, price: int):
        uid = str(interaction.user.id)
        guild = _get_user_guild(uid)
        if not guild:
            await interaction.response.send_message("You are not in a guild!", ephemeral=True)
            return
        if guild["owner_id"] != uid:
            await interaction.response.send_message("Only guild owner can set prices! / 只有会长可以设置价格！", ephemeral=True)
            return

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE guild_storage SET exchange_price = ? WHERE id = ? AND guild_id = ?",
                (price, item_id, guild["id"]),
            )
            conn.commit()

        await interaction.response.send_message(f"✅ Price set to {price} contribution for item #{item_id}.")

    @app_commands.command(name="gmpt-guild", description="Guild System / 公会系统 — manage your guild!")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def guild_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        view = GuildPanelView(uid)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildCog(bot))
    logger.info("MMORPG Guild cog loaded")
