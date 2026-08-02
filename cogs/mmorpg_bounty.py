"""
GMPT Bot — MMORPG 悬赏任务板 / Bounty Board
/gmpt-bounty — 每日随机悬赏，杀怪/收集获得金币+EXP

Bilingual (中文 / English)
"""
import logging
import random
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone
from database import get_db_ctx
from utils.cog_base import CogBase
from cogs.mmorpg_stats import _get_user_stats as _stats_get_user_stats

logger = logging.getLogger(__name__)

# ── Bounty definitions ──
BOUNTY_TEMPLATES = [
    # (name_cn, name_en, target_type, target_count, coins, exp, emoji)
    ("史莱姆", "Slime", "kill", 10, 200, 50, "🟢"),
    ("骷髅兵", "Skeleton", "kill", 8, 300, 80, "💀"),
    ("哥布林", "Goblin", "kill", 12, 250, 60, "👺"),
    ("巨蜘蛛", "Giant Spider", "kill", 5, 400, 100, "🕷️"),
    ("暗影刺客", "Shadow Assassin", "kill", 3, 600, 150, "🗡️"),
    ("火元素", "Fire Elemental", "kill", 4, 500, 120, "🔥"),
    ("草药", "Herb", "gather", 15, 150, 40, "🌿"),
    ("矿石", "Ore", "gather", 10, 200, 50, "⛏️"),
    ("魔法水晶", "Magic Crystal", "gather", 5, 350, 80, "💎"),
    ("龙鳞碎片", "Dragon Scale", "gather", 3, 500, 120, "🐉"),
]

# ── DB Init ──
def _init_bounty_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mmorpg_bounties (
                user_id TEXT NOT NULL,
                bounty_id INTEGER NOT NULL,
                target_type TEXT NOT NULL,
                target_count INTEGER NOT NULL,
                progress INTEGER DEFAULT 0,
                coins INTEGER NOT NULL,
                exp INTEGER NOT NULL,
                claimed INTEGER DEFAULT 0,
                assigned_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, bounty_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mmorpg_bounty_tracker (
                user_id TEXT NOT NULL,
                enemy_name TEXT NOT NULL,
                kills INTEGER DEFAULT 1,
                PRIMARY KEY (user_id, enemy_name)
            )
        """)
        conn.commit()

_init_bounty_tables()

DAILY_BOUNTY_LIMIT = 3


def _get_daily_bounties(uid: str) -> list[dict]:
    """Get today's active bounties for user."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cur.execute(
            "SELECT * FROM mmorpg_bounties WHERE user_id=? AND claimed=0 AND assigned_at LIKE ?",
            (uid, f"{today}%"),
        )
        return [dict(r) for r in cur.fetchall()]


def _assign_bounties(uid: str):
    """Assign today's bounties if none exist yet."""
    existing = _get_daily_bounties(uid)
    if existing:
        return existing

    chosen = random.sample(BOUNTY_TEMPLATES, min(DAILY_BOUNTY_LIMIT, len(BOUNTY_TEMPLATES)))
    with get_db_ctx() as conn:
        cur = conn.cursor()
        for i, (cn, en, ttype, cnt, coins, exp, emoji) in enumerate(chosen):
            cur.execute(
                "INSERT OR IGNORE INTO mmorpg_bounties (user_id, bounty_id, target_type, target_count, coins, exp)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (uid, i, ttype, cnt, coins, exp),
            )
        conn.commit()
    return _get_daily_bounties(uid)


def record_kill(uid: str, enemy_name: str):
    """Called after killing an enemy in boss/dungeon/etc."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO mmorpg_bounty_tracker (user_id, enemy_name, kills) VALUES (?, ?, 1)"
            " ON CONFLICT(user_id, enemy_name) DO UPDATE SET kills = kills + 1",
            (uid, enemy_name),
        )
        # Update bounty progress
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cur.execute(
            "SELECT bounty_id, target_type, target_count, progress FROM mmorpg_bounties"
            " WHERE user_id=? AND claimed=0 AND assigned_at LIKE ?",
            (uid, f"{today}%"),
        )
        bounties = cur.fetchall()
        for b in bounties:
            if b["target_type"] == "kill":
                # Check total kills for this bounty type
                cur.execute(
                    "SELECT SUM(kills) as total FROM mmorpg_bounty_tracker WHERE user_id=?",
                    (uid,),
                )
                total = cur.fetchone()["total"] or 0
                new_progress = min(total, b["target_count"])
                cur.execute(
                    "UPDATE mmorpg_bounties SET progress=? WHERE user_id=? AND bounty_id=?",
                    (new_progress, uid, b["bounty_id"]),
                )
        conn.commit()


def record_gather(uid: str, item_name: str):
    """Called after gathering an item."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO mmorpg_bounty_tracker (user_id, enemy_name, kills) VALUES (?, ?, 1)"
            " ON CONFLICT(user_id, enemy_name) DO UPDATE SET kills = kills + 1",
            (uid, item_name),
        )
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cur.execute(
            "SELECT bounty_id, target_type, target_count, progress FROM mmorpg_bounties"
            " WHERE user_id=? AND claimed=0 AND assigned_at LIKE ?",
            (uid, f"{today}%"),
        )
        bounties = cur.fetchall()
        for b in bounties:
            if b["target_type"] == "gather":
                cur.execute(
                    "SELECT SUM(kills) as total FROM mmorpg_bounty_tracker WHERE user_id=?",
                    (uid,),
                )
                total = cur.fetchone()["total"] or 0
                new_progress = min(total, b["target_count"])
                cur.execute(
                    "UPDATE mmorpg_bounties SET progress=? WHERE user_id=? AND bounty_id=?",
                    (new_progress, uid, b["bounty_id"]),
                )
        conn.commit()


class BountyPanelView(discord.ui.View):
    """悬赏任务板按钮面板 / Bounty Board button panel."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()

        bounties = _assign_bounties(self.uid)

        for i, b in enumerate(bounties):
            template = BOUNTY_TEMPLATES[b["bounty_id"]]
            emoji, cn, en = template[6], template[0], template[1]
            progress = min(b["progress"], b["target_count"])
            pct = int(progress / max(1, b["target_count"]) * 100)
            status = "✅" if progress >= b["target_count"] else f"{pct}%"
            label = f"{emoji} {cn}/{en} [{status}]"
            btn = discord.ui.Button(
                label=label[:80],
                style=discord.ButtonStyle.primary if progress >= b["target_count"] else discord.ButtonStyle.secondary,
                row=i, custom_id=f"bounty_{i}",
            )
            btn.callback = self._make_bounty_callback(b["bounty_id"])
            self.add_item(btn)

        back_btn = discord.ui.Button(
            label="返回主面板 | Back to Main",
            style=discord.ButtonStyle.danger, row=3, custom_id="bounty_back",
        )
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    def _make_bounty_callback(self, bounty_id: int):
        async def cb(interaction: discord.Interaction):
            uid = str(interaction.user.id)
            if uid != self.uid:
                return await interaction.response.send_message("Not your panel!", ephemeral=True)

            bounties = _get_daily_bounties(uid)
            target = None
            for b in bounties:
                if b["bounty_id"] == bounty_id:
                    target = b
                    break

            if not target:
                return await interaction.response.send_message("Bounty not found!", ephemeral=True)

            if target["progress"] < target["target_count"]:
                template = BOUNTY_TEMPLATES[bounty_id]
                embed = discord.Embed(
                    title=f"Bounty Progress / 悬赏进度",
                    description=(
                        f"{template[6]} **{template[0]} / {template[1]}**\n"
                        f"Progress / 进度: {target['progress']}/{target['target_count']}\n"
                        f"Reward / 奖励: 🪙 {target['coins']} | ⚡ {target['exp']} EXP"
                    ),
                    color=0xE67E22,
                )
                return await interaction.response.send_message(embed=embed, ephemeral=True)

            # Claim reward
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE mmorpg_bounties SET claimed=1 WHERE user_id=? AND bounty_id=?",
                    (uid, bounty_id),
                )
                conn.commit()

            from cogs.mmorpg_shop import _add_coins, _get_user_stats
            _add_coins(uid, target["coins"], f"Bounty reward: {BOUNTY_TEMPLATES[bounty_id][0]}")

            # XP via direct DB write (same pattern as economy_jobs._add_user_xp)
            stats = _get_user_stats(uid)
            new_xp = stats.get("xp", 0) + target["exp"]
            level = stats["level"]
            while new_xp >= level * 1000:
                new_xp -= level * 1000
                level += 1
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE users SET xp=?, level=? WHERE discord_id=?", (new_xp, level, uid))
                conn.commit()

            template = BOUNTY_TEMPLATES[bounty_id]
            embed = discord.Embed(
                title=f"Bounty Complete! / 悬赏完成！",
                description=(
                    f"{template[6]} **{template[0]} / {template[1]}** 已完成！\n"
                    f"Reward / 奖励: 🪙 **+{target['coins']}** | ⚡ **+{target['exp']}** EXP"
                ),
                color=0x2ECC71,
            )
            import asyncio as _asyncio
            from utils.animations import bounty_claim_animation
            await interaction.response.defer(ephemeral=True)
            await bounty_claim_animation(interaction, template[0], target['coins'], target['exp'])
            # Rebuild view
            self._build()
            try:
                await interaction.message.edit(embed=self.build_main_embed(), view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

        return cb

    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(self.uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
            return
        await interaction.response.send_message("Use /gmpt-panel to return.", ephemeral=True)


    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass

class BountyBoard(commands.Cog):
    """悬赏任务板系统 / Bounty Board system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="gmpt-bounty", description="悬赏任务板 / Bounty Board — daily kill & gather quests")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def bounty_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        bounties = _assign_bounties(uid)

        embed = discord.Embed(
            title="Bounty Board / 悬赏任务板",
            description="Daily bounties — kill enemies or gather items for rewards!\n每日悬赏 — 击杀敌人或收集物品获取奖励！",
            color=0xE67E22,
        )

        for b in bounties:
            template = BOUNTY_TEMPLATES[b["bounty_id"]]
            emoji, cn, en = template[6], template[0], template[1]
            pct = int(b["progress"] / max(1, b["target_count"]) * 100)
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            status = "✅ COMPLETE" if b["progress"] >= b["target_count"] else f"{bar} {b['progress']}/{b['target_count']}"
            embed.add_field(
                name=f"{emoji} {cn} / {en}",
                value=(
                    f"Type / 类型: {'Kill 击杀' if b['target_type'] == 'kill' else 'Gather 采集'} × {b['target_count']}\n"
                    f"Progress / 进度: {status}\n"
                    f"Reward / 奖励: 🪙 {b['coins']} | ⚡ {b['exp']} EXP"
                ),
                inline=False,
            )

        embed.set_footer(text="Earn progress by fighting bosses/dungeons! Use the panel to claim rewards.")
        view = BountyPanelView(uid, main_view=None)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(BountyBoard(bot))
