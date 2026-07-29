"""
cogs/daily_quest.py — 每日任务 / Daily Quests
3 random quests per day, reset at UTC+8 midnight.
Quest types: kill monsters / work times / PVP wins / buy items / use potions
"""

import random
import time
import discord
from discord import app_commands

from database import get_db_ctx
from utils.helpers import CogBase, ensure_user
from cogs.economy import add_coins

QUEST_TYPES = {
    "kill": {
        "cn": "击杀怪物",
        "en": "Kill Monsters",
        "emoji": "👹",
        "targets": [3, 5, 8, 10],
    },
    "work": {
        "cn": "打工次数",
        "en": "Work Times",
        "emoji": "💼",
        "targets": [2, 3, 5, 8],
    },
    "pvp": {
        "cn": "PVP 胜利",
        "en": "PVP Wins",
        "emoji": "⚔️",
        "targets": [1, 2, 3, 5],
    },
    "buy": {
        "cn": "购买物品",
        "en": "Buy Items",
        "emoji": "🛒",
        "targets": [1, 2, 3, 5],
    },
    "potion": {
        "cn": "使用药水",
        "en": "Use Potions",
        "emoji": "🧪",
        "targets": [1, 2, 3, 5],
    },
}

REWARDS = {
    "coins": [200, 400, 600, 1000],
    "exp": [50, 100, 150, 250],
}


def _utc8_midnight_ts() -> int:
    """Return timestamp of next UTC+8 midnight."""
    import datetime
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
    return int(tomorrow.timestamp())


def _generate_daily_quests(user_id: str) -> list:
    """Generate 3 random quests for the user."""
    types = random.sample(list(QUEST_TYPES.keys()), 3)
    quests = []
    for i, qt in enumerate(types):
        info = QUEST_TYPES[qt]
        tier = random.randint(0, 3)
        target = info["targets"][tier]
        reward_coins = REWARDS["coins"][tier]
        reward_exp = REWARDS["exp"][tier]
        quests.append({
            "type": qt,
            "target": target,
            "progress": 0,
            "reward_coins": reward_coins,
            "reward_exp": reward_exp,
            "claimed": 0,
        })
    return quests


def _get_or_create_quests(user_id: str) -> dict:
    """Get today's quests, regenerate if expired."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT quests_json, reset_ts FROM daily_quests WHERE user_id=?",
            (user_id,),
        )
        row = cur.fetchone()

        now = int(time.time())
        if row:
            reset_ts = row["reset_ts"]
            if now < reset_ts:
                import json
                return json.loads(row["quests_json"])
            # Expired, regenerate
            quests = _generate_daily_quests(user_id)
            _save_quests(user_id, quests, _utc8_midnight_ts())
            return quests
        else:
            quests = _generate_daily_quests(user_id)
            _save_quests(user_id, quests, _utc8_midnight_ts())
            return quests


def _save_quests(user_id: str, quests: list, reset_ts: int):
    import json
    with get_db_ctx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO daily_quests (user_id, quests_json, reset_ts) VALUES (?,?,?)",
            (user_id, json.dumps(quests), reset_ts),
        )
        conn.commit()


def _update_progress(user_id: str, quest_type: str, amount: int = 1):
    """Increment progress for matching active quests."""
    quests = _get_or_create_quests(user_id)
    changed = False
    for q in quests:
        if q["type"] == quest_type and q["progress"] < q["target"] and not q["claimed"]:
            q["progress"] = min(q["target"], q["progress"] + amount)
            changed = True
    if changed:
        _save_quests(user_id, quests, _utc8_midnight_ts())
    return quests


def _claim_quest(user_id: str, quest_index: int) -> dict:
    """Claim a completed quest. Returns reward dict or None."""
    quests = _get_or_create_quests(user_id)
    if quest_index >= len(quests):
        return None
    q = quests[quest_index]
    if q["progress"] < q["target"] or q["claimed"]:
        return None

    q["claimed"] = 1
    _save_quests(user_id, quests, _utc8_midnight_ts())

    # Award
    add_coins(user_id, q["reward_coins"], "每日任务奖励 / Daily quest reward")
    # Add exp
    _add_quest_exp(user_id, q["reward_exp"])

    return {"coins": q["reward_coins"], "exp": q["reward_exp"]}


def _add_quest_exp(user_id: str, exp: int):
    """Add exp to user's xp column in users table."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT xp FROM users WHERE user_id=?",
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            new_exp = (row["xp"] or 0) + exp
            cur.execute(
                "UPDATE users SET xp=? WHERE user_id=?",
                (new_exp, user_id),
            )
            conn.commit()


def _init_daily_quest_db():
    with get_db_ctx() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_quests (
                user_id TEXT PRIMARY KEY,
                quests_json TEXT,
                reset_ts INTEGER
            )
        """)
        conn.commit()


class DailyQuestView(discord.ui.View):
    """每日任务面板 / Daily quest panel."""

    def __init__(self, user_id: str, main_view=None):
        super().__init__(timeout=180)
        self.uid = user_id
        self.main_view = main_view
        self._build()

    def build_main_embed(self):
        quests = _get_or_create_quests(self.uid)
        embed = discord.Embed(
            title=f"📅 每日任务 / Daily Quests",
            description="每天 UTC+8 午夜刷新 / Resets daily at UTC+8 midnight",
            color=0x2ECC71,
        )
        for i, q in enumerate(quests):
            info = QUEST_TYPES[q["type"]]
            progress = q["progress"]
            target = q["target"]
            pct = int(progress / target * 10) if target > 0 else 0
            bar = "█" * pct + "░" * (10 - pct)
            status = "✅ 已完成" if q["claimed"] else ("🎁 可领取" if progress >= target else "⏳ 进行中")
            embed.add_field(
                name=f"{info['emoji']} {info['cn']} {info['en']}",
                value=(
                    f"[{bar}] {progress}/{target}\n"
                    f"🪙 {q['reward_coins']} | ✨ {q['reward_exp']} EXP\n"
                    f"状态 Status: {status}"
                ),
                inline=True,
            )
        return embed

    def _build(self):
        self.clear_items()
        quests = _get_or_create_quests(self.uid)
        for i, q in enumerate(quests):
            info = QUEST_TYPES[q["type"]]
            if q["claimed"]:
                style = discord.ButtonStyle.success
                label = f"✅ {info['emoji']} {info['cn']} (已领取 Claimed)"
                disabled = True
            elif q["progress"] >= q["target"]:
                style = discord.ButtonStyle.primary
                label = f"🎁 {info['emoji']} {info['cn']} (可领取 Claim)"
                disabled = False
            else:
                style = discord.ButtonStyle.secondary
                label = f"{info['emoji']} {info['cn']} {q['progress']}/{q['target']}"
                disabled = True

            btn = discord.ui.Button(
                label=label,
                style=style,
                row=i,
                disabled=disabled,
                custom_id=f"quest_{i}",
            )
            btn.callback = self._make_claim_callback(i)
            self.add_item(btn)

        if self.main_view:
            back_btn = discord.ui.Button(
                label="Back to MMORPG / 返回", style=discord.ButtonStyle.danger,
                row=3, emoji="🏠", custom_id="dq_back",
            )
            back_btn.callback = self._back_callback
            self.add_item(back_btn)

    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            uid = str(self.uid)
            embed = build_main_embed(uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)

    def _make_claim_callback(self, idx: int):
        async def cb(interaction: discord.Interaction):
            reward = _claim_quest(self.uid, idx)
            if reward:
                await interaction.response.send_message(
                    f"🎉 任务完成！获得 🪙 **{reward['coins']}** 金币 + **{reward['exp']}** 经验！\n"
                    f"Quest complete! Earned 🪙 **{reward['coins']}** coins + **{reward['exp']}** EXP!",
                    ephemeral=True,
                )
                # Rebuild view and refresh panel message
                self._build()
                try:
                    await interaction.message.edit(embed=self.build_main_embed(), view=self)
                except (discord.NotFound, discord.HTTPException):
                    pass
            else:
                await interaction.response.send_message(
                    "❌ 任务未完成或已领取 / Quest not complete or already claimed",
                    ephemeral=True,
                )
        return cb


class DailyQuest(CogBase):
    """每日任务 / Daily Quests"""

    def __init__(self, bot):
        super().__init__(bot)
        _init_daily_quest_db()

    @app_commands.command(name="gmpt-dailyquest", description="📅 每日任务 / Daily quests")
    async def daily_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        uname = interaction.user.display_name
        quests = _get_or_create_quests(uid)

        embed = discord.Embed(
            title=f"📅 {uname} 每日任务 / Daily Quests",
            description="每天 UTC+8 午夜刷新 / Resets daily at UTC+8 midnight",
            color=0x2ECC71,
        )

        for i, q in enumerate(quests):
            info = QUEST_TYPES[q["type"]]
            progress = q["progress"]
            target = q["target"]
            pct = int(progress / target * 10)
            bar = "█" * pct + "░" * (10 - pct)
            status = "✅ 已完成" if q["claimed"] else ("🎁 可领取" if progress >= target else "⏳ 进行中")
            embed.add_field(
                name=f"{info['emoji']} {info['cn']} {info['en']}",
                value=(
                    f"[{bar}] {progress}/{target}\n"
                    f"🪙 {q['reward_coins']} | ✨ {q['reward_exp']} EXP\n"
                    f"状态 Status: {status}"
                ),
                inline=True,
            )

        view = DailyQuestView(uid)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(DailyQuest(bot))
