"""
GMPT Bot — Boss Battle system
组队副本/Boss战 — Create boss rooms, join, attack, earn rewards
"""
import asyncio
import random
import time
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
from cogs.economy import get_balance, add_coins
import logging

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Boss definitions
# ══════════════════════════════════════════════════════════════

BOSS_TYPES = {
    "金龙": {"emoji": "🐉", "desc": "Gold Dragon / 金龙 — 喷吐金色火焰！", "skills": ["龙息", "龙尾扫", "金币雨"]},
    "暗影领主": {"emoji": "👹", "desc": "Shadow Lord / 暗影领主 — 暗影之力笼罩战场！", "skills": ["暗影斩", "黑洞", "恐惧凝视"]},
    "冰霜巨人": {"emoji": "🧊", "desc": "Frost Giant / 冰霜巨人 — 冻结一切！", "skills": ["冰锥", "暴风雪", "永冻"]},
    "地狱犬": {"emoji": "🔥", "desc": "Hellhound / 地狱犬 — 三头地狱犬喷吐烈焰！", "skills": ["三重撕咬", "地狱火", "咆哮"]},
}

DIFFICULTY = {
    "简单": {"label": "Easy / 简单", "hp_mult": 1.0, "atk_mult": 0.7, "reward_mult": 0.5, "color": 0x2ECC71},
    "普通": {"label": "Normal / 普通", "hp_mult": 2.0, "atk_mult": 1.0, "reward_mult": 1.0, "color": 0xF39C12},
    "困难": {"label": "Hard / 困难", "hp_mult": 4.0, "atk_mult": 1.5, "reward_mult": 2.0, "color": 0xE74C3C},
}


# ══════════════════════════════════════════════════════════════
# Boss Cog
# ══════════════════════════════════════════════════════════════

class BossCog(CogBase):
    """Boss 战系统 / Boss Battle System"""

    gmpt_boss_group = app_commands.Group(
        name="gmpt-boss",
        description="Boss战 / Boss Battle — 组队副本"
    )

    def __init__(self, bot):
        self.bot = bot
        self.boss_sessions: dict[str, dict] = {}  # channel_id -> boss battle session
        self.boss_lock = asyncio.Lock()

    # ── helper ──

    @staticmethod
    def _format_hp_bar(current: int, maximum: int, length: int = 20) -> str:
        ratio = max(0, current / max(1, maximum))
        filled = int(ratio * length)
        bar = "█" * filled + "░" * (length - filled)
        pct = int(ratio * 100)
        return f"[{bar}] {pct}% ({current}/{maximum})"

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss create <type> <difficulty>
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="create",
        description="创建Boss房间 / Create a boss battle room"
    )
    @app_commands.describe(
        boss_type="Boss类型: 金龙 / 暗影领主 / 冰霜巨人 / 地狱犬",
        difficulty="难度: 简单 / 普通 / 困难",
    )
    async def boss_create(
        self,
        interaction: discord.Interaction,
        boss_type: str = "金龙",
        difficulty: str = "普通",
    ):
        chid = str(interaction.channel_id)

        if chid in self.boss_sessions and self.boss_sessions[chid].get("active"):
            return await interaction.response.send_message(
                "本频道已有进行中的 Boss 战！/ Boss battle already in progress!", ephemeral=True)

        if boss_type not in BOSS_TYPES:
            types_str = " / ".join(BOSS_TYPES.keys())
            return await interaction.response.send_message(
                f"Boss 类型无效！可选: {types_str}\nInvalid boss type! Options: {types_str}", ephemeral=True)

        if difficulty not in DIFFICULTY:
            diffs = " / ".join(DIFFICULTY.keys())
            return await interaction.response.send_message(
                f"难度无效！可选: {diffs}\nInvalid difficulty! Options: {diffs}", ephemeral=True)

        boss = BOSS_TYPES[boss_type]
        diff = DIFFICULTY[difficulty]
        base_hp = random.randint(500, 800)
        hp = int(base_hp * diff["hp_mult"])
        atk = int(random.randint(20, 50) * diff["atk_mult"])

        session = {
            "active": True,
            "boss_type": boss_type,
            "emoji": boss["emoji"],
            "difficulty": difficulty,
            "diff_label": diff["label"],
            "hp": hp,
            "max_hp": hp,
            "atk": atk,
            "color": diff["color"],
            "reward_mult": diff["reward_mult"],
            "skills": boss["skills"],
            "players": {},  # uid -> {"name": ..., "dmg": ..., "alive": True, "joined_at": ...}
            "creator": str(interaction.user.id),
            "channel_id": chid,
            "turn": 0,
            "log": [],
        }

        session["players"][str(interaction.user.id)] = {
            "name": interaction.user.display_name,
            "dmg": 0,
            "alive": True,
            "joined_at": time.time(),
        }

        self.boss_sessions[chid] = session

        embed = self._build_boss_embed(session)
        await interaction.response.send_message(
            f"🐉 **{interaction.user.display_name}** 创建了 Boss 战！\n"
            f"Boss Battle created by {interaction.user.display_name}!",
            embed=embed,
        )

        # Auto-start timer (60s to join)
        self.bot.loop.create_task(self._boss_start_timer(interaction, chid))

    async def _boss_start_timer(self, interaction: discord.Interaction, chid: str):
        await asyncio.sleep(60)
        session = self.boss_sessions.get(chid)
        if not session or not session.get("active"):
            return
        if len(session["players"]) < 1:
            session["active"] = False
            await interaction.channel.send("⏰ Boss 战已取消（无玩家加入）/ Boss battle cancelled (no players).")
            return

        await interaction.channel.send("⚔️ **Boss 战开始！** / Boss battle begins!")

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss join
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="join",
        description="加入Boss战 / Join the boss battle"
    )
    async def boss_join(self, interaction: discord.Interaction):
        chid = str(interaction.channel_id)
        uid = str(interaction.user.id)

        session = self.boss_sessions.get(chid)
        if not session or not session.get("active"):
            return await interaction.response.send_message("本频道没有进行中的 Boss 战 / No active boss battle.", ephemeral=True)

        if uid in session["players"]:
            return await interaction.response.send_message("你已经加入了！/ You already joined!", ephemeral=True)

        session["players"][uid] = {
            "name": interaction.user.display_name,
            "dmg": 0,
            "alive": True,
            "joined_at": time.time(),
        }

        embed = self._build_boss_embed(session)
        await interaction.response.send_message(
            f"✅ **{interaction.user.display_name}** 加入了 Boss 战！Joined the battle!",
            embed=embed,
        )

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss attack
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="attack",
        description="攻击Boss / Attack the boss"
    )
    @app_commands.checks.cooldown(1, 8.0, key=lambda i: i.user.id)
    async def boss_attack(self, interaction: discord.Interaction):
        chid = str(interaction.channel_id)
        uid = str(interaction.user.id)

        session = self.boss_sessions.get(chid)
        if not session or not session.get("active"):
            return await interaction.response.send_message("本频道没有进行中的 Boss 战 / No active boss battle.", ephemeral=True)

        if uid not in session["players"]:
            return await interaction.response.send_message("请先 `/gmpt-boss join` 加入 / Join first!", ephemeral=True)

        player = session["players"][uid]
        if not player["alive"]:
            return await interaction.response.send_message("你已阵亡！等待下一轮 / You are dead! Wait for next round.", ephemeral=True)

        # Player attacks
        atk_type = random.choices(
            ["普通攻击", "普通攻击", "普通攻击", "暴击", "技能"],
            weights=[50, 50, 50, 25, 15],
            k=1,
        )[0]

        if atk_type == "暴击":
            dmg = random.randint(50, 120)
            dmg_text = f"⚡ **暴击！/ CRIT!** — {dmg} 伤害"
        elif atk_type == "技能":
            dmg = random.randint(40, 90)
            dmg_text = f"✨ **技能！/ Skill!** — {dmg} 伤害"
        else:
            dmg = random.randint(15, 45)
            dmg_text = f"⚔️ 普通攻击 — {dmg} 伤害"

        session["hp"] = max(0, session["hp"] - dmg)
        player["dmg"] += dmg
        session["turn"] += 1

        # Boss counter-attacks
        boss_dmg = random.randint(5, session["atk"])
        boss_target = random.choice(list(session["players"].keys()))
        boss_target_player = session["players"][boss_target]
        boss_dmg_text = (
            f"\n{session['emoji']} Boss 反击了 **{boss_target_player['name']}** ！"
            f" — {boss_dmg} 伤害"
        )

        # Player death chance
        player_death = ""
        if random.random() < 0.1:  # 10% chance for player to "die" this turn
            boss_target_player["alive"] = False
            player_death = f"\n💀 **{boss_target_player['name']}** 被 Boss 击倒了！/ Knocked down!"

        # Check if boss is defeated
        boss_defeated = session["hp"] <= 0

        # Build result
        lines = [
            f"**{interaction.user.display_name}** {dmg_text}",
            f"HP: {self._format_hp_bar(session['hp'], session['max_hp'])}",
            boss_dmg_text,
        ]
        if player_death:
            lines.append(player_death)

        if boss_defeated:
            session["active"] = False
            lines.append("")
            lines.append(f"🎉 **Boss 被击败！/ Boss defeated!**")

            # Distribute rewards
            reward_pool = int(session["max_hp"] * session["reward_mult"] * 0.8)
            total_dmg = sum(p["dmg"] for p in session["players"].values())
            reward_lines = []
            for pid, p in session["players"].items():
                share = int(reward_pool * p["dmg"] / max(1, total_dmg))
                add_coins(pid, share, f"Boss战奖励 / Boss battle reward ({session['boss_type']})")
                reward_lines.append(f"- **{p['name']}**: 伤害 {p['dmg']} → 🪙 +{share}")
            lines.append("\n**💰 奖励分配 / Rewards:**")
            lines.extend(reward_lines)

        await interaction.response.send_message("\n".join(lines))

        if boss_defeated:
            embed = self._build_boss_embed(session, defeated=True)
            await interaction.channel.send(embed=embed)

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss status
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="status",
        description="查看Boss战况 / View boss battle status"
    )
    async def boss_status(self, interaction: discord.Interaction):
        chid = str(interaction.channel_id)
        session = self.boss_sessions.get(chid)
        if not session:
            return await interaction.response.send_message("本频道没有进行中的 Boss 战 / No active boss battle.", ephemeral=True)

        embed = self._build_boss_embed(session)
        await interaction.response.send_message(embed=embed)

    def _build_boss_embed(self, session: dict, defeated: bool = False) -> discord.Embed:
        emoji = session["emoji"]
        boss_name = session["boss_type"]
        title = f"{emoji} {boss_name} Boss 战 / Boss Battle"
        if defeated:
            title = f"{emoji} {boss_name} — 已击败！/ Defeated!"

        embed = discord.Embed(title=title, color=session["color"])
        embed.add_field(
            name="难度 / Difficulty",
            value=session["diff_label"],
            inline=True,
        )
        embed.add_field(
            name="Boss HP",
            value=self._format_hp_bar(session["hp"], session["max_hp"]),
            inline=False,
        )
        embed.add_field(
            name="攻击力 / ATK",
            value=str(session["atk"]),
            inline=True,
        )
        embed.add_field(
            name="回合 / Turn",
            value=str(session["turn"]),
            inline=True,
        )
        embed.add_field(
            name="技能 / Skills",
            value=" | ".join(session["skills"]),
            inline=False,
        )

        # Player list
        player_list = []
        damage_list = []
        for pid, p in session["players"].items():
            status_icon = "" if p["alive"] else "💀"
            player_list.append(f"{status_icon} {p['name']}")
            damage_list.append(f"{p['dmg']} dmg")
        embed.add_field(
            name=f"玩家 / Players ({len(session['players'])})",
            value="\n".join(player_list) if player_list else "等待加入 / Waiting...",
            inline=True,
        )
        embed.add_field(
            name="伤害贡献 / Damage",
            value="\n".join(damage_list) if damage_list else "-",
            inline=True,
        )

        embed.set_footer(text="使用 /gmpt-boss attack 攻击 | Use /gmpt-boss attack to strike!")
        return embed


# ══════════════════════════════════════════════════════════════
# Cog setup
# ══════════════════════════════════════════════════════════════

async def setup(bot):
    await bot.add_cog(BossCog(bot))
