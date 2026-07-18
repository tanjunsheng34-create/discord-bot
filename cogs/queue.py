"""
GMPT Bot — Queue/LFG 排队匹配系统
"""
import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
from datetime import datetime

import logging
logger = logging.getLogger(__name__)

VALID_POSITIONS = ["Top", "JG", "Mid", "ADC", "Support", "Any"]


class QueueCog(commands.Cog):
    """Queue/LFG 排队匹配"""

    def __init__(self, bot):
        self.bot = bot
        self.queue: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    # ========== 进入匹配池 ==========
    @app_commands.command(
        name="gmpt-queue",
        description="进入匹配池 / Join the match queue",
    )
    @app_commands.describe(
        position="位置 / Position (Top/JG/Mid/ADC/Support/Any)",
    )
    @app_commands.choices(position=[
        app_commands.Choice(name="Top", value="Top"),
        app_commands.Choice(name="JG", value="JG"),
        app_commands.Choice(name="Mid", value="Mid"),
        app_commands.Choice(name="ADC", value="ADC"),
        app_commands.Choice(name="Support", value="Support"),
        app_commands.Choice(name="Any", value="Any"),
    ])
    async def queue_join(
        self, interaction: discord.Interaction,
        position: str = "Any",
    ):
        uid = str(interaction.user.id)

        async with self._lock:
            if uid in self.queue:
                return await interaction.response.send_message(
                    "你已在匹配池中 / Already in queue.", ephemeral=True,
                )

            self.queue[uid] = {
                "position": position,
                "joined_at": datetime.utcnow(),
            }
            count = len(self.queue)

            if count >= 10:
                await self._create_match(interaction)
            else:
                await interaction.response.send_message(
                    f"✅ {interaction.user.mention} 已加入匹配池 / Joined queue ({count}/10)\n"
                    f"位置 / Position: **{position}**"
                )

    # ========== 退出匹配池 ==========
    @app_commands.command(
        name="gmpt-leave-queue",
        description="退出匹配池 / Leave the queue",
    )
    async def queue_leave(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        async with self._lock:
            if uid not in self.queue:
                return await interaction.response.send_message(
                    "你不在匹配池中 / Not in queue.", ephemeral=True,
                )
            del self.queue[uid]
            count = len(self.queue)
            await interaction.response.send_message(
                f"🚪 {interaction.user.mention} 已退出匹配池 / Left the queue ({count}/10)"
            )

    # ========== 查看匹配池状态 ==========
    @app_commands.command(
        name="gmpt-queue-status",
        description="查看匹配池状态 / View queue status",
    )
    async def queue_status(self, interaction: discord.Interaction):
        async with self._lock:
            count = len(self.queue)
            if count == 0:
                return await interaction.response.send_message(
                    "匹配池为空 / Queue is empty."
                )

            embed = discord.Embed(
                title=f"匹配池 / Queue ({count}/10)",
                color=discord.Color.blurple(),
            )

            pos_counts = {}
            for _, data in self.queue.items():
                pos = data["position"]
                pos_counts[pos] = pos_counts.get(pos, 0) + 1

            pos_lines = []
            for pos in VALID_POSITIONS:
                cnt = pos_counts.get(pos, 0)
                bar = "█" * cnt
                pos_lines.append(f"`{pos:<8}` {bar} {cnt}")
            embed.add_field(
                name="位置分布 / Position Distribution",
                value="\n".join(pos_lines),
                inline=False,
            )

            player_lines = []
            for uid, data in self.queue.items():
                member = interaction.guild.get_member(int(uid))
                name = member.display_name if member else uid
                player_lines.append(f"- {name} ({data['position']})")
            embed.add_field(
                name="玩家 / Players",
                value="\n".join(player_lines),
                inline=False,
            )

            await interaction.response.send_message(embed=embed)

    # ========== 自动创建比赛（满10人） ==========
    async def _create_match(self, interaction: discord.Interaction):
        player_items = list(self.queue.items())
        random.shuffle(player_items)

        team_a = player_items[:5]
        team_b = player_items[5:10]

        conn = get_db(); cur = conn.cursor()
        match_name = f"Auto Queue Match {datetime.utcnow().strftime('%H:%M')}"
        cur.execute(
            "INSERT INTO tournaments (name, max_teams, team_size, created_by, status) VALUES (?, 2, 5, ?, 'open')",
            (match_name, str(self.bot.user.id)),
        )
        conn.commit()
        match_id = cur.lastrowid

        for uid, data in player_items:
            cur.execute(
                "INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)",
                (uid, "unknown"),
            )
            lane = data["position"] if data["position"] != "Any" else None
            cur.execute(
                "INSERT INTO registrations (tournament_id, discord_id, lane) VALUES (?,?,?)",
                (match_id, uid, lane),
            )

        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (match_id, "蓝队 Blue"))
        aid = cur.lastrowid
        for uid, _ in team_a:
            cur.execute(
                "UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?",
                (aid, match_id, uid),
            )

        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (match_id, "红队 Red"))
        bid = cur.lastrowid
        for uid, _ in team_b:
            cur.execute(
                "UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?",
                (bid, match_id, uid),
            )

        cur.execute("UPDATE tournaments SET status='closed' WHERE id=?", (match_id,))
        conn.commit(); conn.close()

        self.queue.clear()

        a_mentions = " ".join(f"<@{uid}>" for uid, _ in team_a)
        b_mentions = " ".join(f"<@{uid}>" for uid, _ in team_b)

        embed = discord.Embed(
            title=f"⚔️ 自动匹配完成 / Auto Match Ready! — {match_name}",
            description=(
                f"匹配池满 10 人，已自动创建比赛！\n\n"
                f"🔵 **蓝队 Blue** (ID:{aid}): {a_mentions}\n"
                f"🔴 **红队 Red** (ID:{bid}): {b_mentions}\n\n"
                f"结算: `/gmpt-settle {match_id} <获胜队伍ID>`"
            ),
            color=discord.Color.gold(),
        ).set_footer(text=f"Match ID: {match_id}")

        try:
            await interaction.response.send_message("@everyone", embed=embed)
        except Exception:
            await interaction.response.send_message(embed=embed)
            logger.warning("Failed to @everyone in queue match announcement.")

        # Send match view with buttons for settlement
        try:
            from cogs.dashboard import MatchView, save_match_view_state, set_player_list_msg
            view = MatchView()
            match_msg = await interaction.channel.send(embed=embed, view=view)
            save_match_view_state(match_id, match_msg.id, interaction.channel_id)
            list_embed = discord.Embed(
                title=f"已报名玩家 / Signed Up (10/10)",
                description=f"🔵 蓝队: {a_mentions}\n🔴 红队: {b_mentions}",
                color=discord.Color.green(),
            )
            list_msg = await interaction.channel.send(embed=list_embed)
            set_player_list_msg(match_id, list_msg.id)
        except Exception as e:
            logger.error(f"Failed to send MatchView for queue match {match_id}: {e}")


async def setup(bot):
    await bot.add_cog(QueueCog(bot))
