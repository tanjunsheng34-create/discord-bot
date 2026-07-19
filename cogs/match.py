"""
GMPT Bot — 快速比赛系统 (Quick Match System)
"""
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
from cogs.economy import check_achievement, MATCH_WIN_COINS, MATCH_PARTICIPATE_COINS
from cogs.dashboard import _execute_settle, _update_mmr, VoicePullView

import logging
from utils.logger import log_error
logger = logging.getLogger(__name__)


class Match(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ══════════ 1. 创建比赛 ══════════
    @app_commands.command(
        name="gmpt-create-match",
        description="Create a new match room / 创建比赛房间"
    )
    @app_commands.describe(name="Match name / 比赛名称")
    async def create_match_cmd(self, interaction: discord.Interaction, name: str):
        uid = str(interaction.user.id)
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO matches (name, created_by, channel_id) VALUES (?, ?, ?)",
            (name, uid, str(interaction.channel_id)),
        )
        mid = cur.lastrowid
        conn.commit()
        conn.close()

        embed = discord.Embed(
            title=f"比赛已创建 / Match Created — {name}",
            description=(
                f"Match ID: **{mid}**\n"
                f"Created by: {interaction.user.mention}\n\n"
                f"报名：`/gmpt-signup {mid}`\n"
                f"Sign up with `/gmpt-signup {mid}`"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    # ══════════ 2. 报名 ══════════
    @app_commands.command(
        name="gmpt-signup",
        description="Sign up for a match / 报名参赛"
    )
    @app_commands.describe(match_id="Match ID (default: latest pending match) / 比赛ID（默认：最近未开始的比赛）")
    async def signup_cmd(self, interaction: discord.Interaction, match_id: int = None):
        uid = str(interaction.user.id)
        conn = get_db()
        cur = conn.cursor()

        if match_id is None:
            cur.execute(
                "SELECT id, name FROM matches WHERE status='pending' ORDER BY id DESC LIMIT 1"
            )
            m = cur.fetchone()
            if not m:
                conn.close()
                return await interaction.response.send_message(
                    "没有可报名的比赛。先用 `/gmpt-create-match` 创建。\n"
                    "No open matches. Create one with `/gmpt-create-match`.",
                    ephemeral=True,
                )
            match_id = m["id"]

        cur.execute("SELECT id, name, status FROM matches WHERE id=?", (match_id,))
        match_row = cur.fetchone()
        if not match_row:
            conn.close()
            return await interaction.response.send_message(f"比赛 #{match_id} 不存在。", ephemeral=True)
        if match_row["status"] != "pending":
            conn.close()
            return await interaction.response.send_message(
                f"比赛 #{match_id} 状态为 `{match_row['status']}`，无法报名。",
                ephemeral=True,
            )

        # 重复报名检查
        cur.execute(
            "SELECT id FROM match_signups WHERE match_id=? AND discord_id=?",
            (match_id, uid),
        )
        if cur.fetchone():
            conn.close()
            return await interaction.response.send_message(
                f"你已经报名了比赛 **{match_row['name']}** (ID:{match_id})！",
                ephemeral=True,
            )

        cur.execute(
            "INSERT INTO match_signups (match_id, discord_id) VALUES (?, ?)",
            (match_id, uid),
        )
        conn.commit()

        cur.execute("SELECT COUNT(*) as cnt FROM match_signups WHERE match_id=?", (match_id,))
        cnt = cur.fetchone()["cnt"]
        conn.close()

        await interaction.response.send_message(
            f"✅ {interaction.user.mention} 已报名 **{match_row['name']}** (ID:{match_id})\n"
            f"当前报名人数: **{cnt}** / Current signups: **{cnt}**"
        )

    # ══════════ 3. 随机洗牌 ══════════
    @app_commands.command(
        name="gmpt-random-teams",
        description="Shuffle all signed-up players (no team split) / 随机打乱报名玩家"
    )
    @app_commands.describe(match_id="Match ID (default: latest pending) / 比赛ID")
    async def random_teams_cmd(self, interaction: discord.Interaction, match_id: int = None):
        conn = get_db()
        cur = conn.cursor()
        if match_id is None:
            cur.execute("SELECT id, name FROM matches WHERE status='pending' ORDER BY id DESC LIMIT 1")
            m = cur.fetchone()
            if not m:
                conn.close()
                return await interaction.response.send_message("没有未开始的比赛。", ephemeral=True)
            match_id = m["id"]

        cur.execute(
            "SELECT discord_id FROM match_signups WHERE match_id=? ORDER BY id",
            (match_id,),
        )
        signups = [r["discord_id"] for r in cur.fetchall()]
        conn.close()

        if not signups:
            return await interaction.response.send_message(
                f"比赛 #{match_id} 暂无报名玩家。", ephemeral=True
            )

        random.shuffle(signups)
        names = []
        for sid in signups:
            member = interaction.guild.get_member(int(sid))
            names.append(member.display_name if member else f"<@{sid}>")

        lines = [f"**#{i+1}** {n}" for i, n in enumerate(names)]
        embed = discord.Embed(
            title=f"随机洗牌 — Match #{match_id}",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"共 {len(signups)} 人")
        await interaction.response.send_message(embed=embed)

    # ══════════ 4. A/B 分队 ══════════
    @app_commands.command(
        name="gmpt-assign-ab",
        description="Randomly split players into Team A / B / 随机分为A/B两队"
    )
    @app_commands.describe(match_id="Match ID (default: latest pending) / 比赛ID")
    async def assign_ab_cmd(self, interaction: discord.Interaction, match_id: int = None):
        uid = str(interaction.user.id)
        conn = get_db()
        cur = conn.cursor()

        if match_id is None:
            cur.execute("SELECT id, name FROM matches WHERE status='pending' ORDER BY id DESC LIMIT 1")
            m = cur.fetchone()
            if not m:
                conn.close()
                return await interaction.response.send_message("没有未开始的比赛。", ephemeral=True)
            match_id = m["id"]

        cur.execute("SELECT id, name, status FROM matches WHERE id=?", (match_id,))
        match_row = cur.fetchone()
        if not match_row:
            conn.close()
            return await interaction.response.send_message(f"比赛 #{match_id} 不存在。", ephemeral=True)

        cur.execute(
            "SELECT discord_id FROM match_signups WHERE match_id=? ORDER BY id",
            (match_id,),
        )
        signups = [r["discord_id"] for r in cur.fetchall()]

        if len(signups) < 2:
            conn.close()
            return await interaction.response.send_message(
                "至少需要 2 人报名才能分队。", ephemeral=True
            )

        random.shuffle(signups)
        mid_point = len(signups) // 2
        team_a = signups[:mid_point]
        team_b = signups[mid_point:]

        # 更新 match_signups 中的 team 字段
        for sid in team_a:
            cur.execute(
                "UPDATE match_signups SET team='A' WHERE match_id=? AND discord_id=?",
                (match_id, sid),
            )
        for sid in team_b:
            cur.execute(
                "UPDATE match_signups SET team='B' WHERE match_id=? AND discord_id=?",
                (match_id, sid),
            )
        conn.commit()
        conn.close()

        # 构建显示
        def resolve_names(id_list):
            result = []
            for sid in id_list:
                m = interaction.guild.get_member(int(sid))
                result.append(m.display_name if m else f"<@{sid}>")
            return result

        a_names = resolve_names(team_a)
        b_names = resolve_names(team_b)

        embed = discord.Embed(
            title=f"A/B 分队 — {match_row['name']} (ID:{match_id})",
            color=discord.Color.purple(),
        )
        embed.add_field(
            name="🔵 Team A",
            value="\n".join(a_names) if a_names else "(空)",
            inline=True,
        )
        embed.add_field(
            name="🔴 Team B",
            value="\n".join(b_names) if b_names else "(空)",
            inline=True,
        )
        embed.set_footer(text=f"A队 {len(team_a)} 人 | B队 {len(team_b)} 人")
        await interaction.response.send_message(embed=embed)

    # ══════════ 5. 开始比赛 ══════════
    @app_commands.command(
        name="gmpt-start-match",
        description="Start a match (Admin) / 开始比赛（管理员）"
    )
    @app_commands.describe(match_id="Match ID (default: latest pending) / 比赛ID")
    @app_commands.default_permissions(administrator=True)
    async def start_match_cmd(self, interaction: discord.Interaction, match_id: int = None):
        conn = get_db()
        cur = conn.cursor()

        if match_id is None:
            cur.execute("SELECT id, name FROM matches WHERE status='pending' ORDER BY id DESC LIMIT 1")
            m = cur.fetchone()
            if not m:
                conn.close()
                return await interaction.response.send_message("没有未开始的比赛。", ephemeral=True)
            match_id = m["id"]

        cur.execute("SELECT id, name, status FROM matches WHERE id=?", (match_id,))
        match_row = cur.fetchone()
        if not match_row:
            conn.close()
            return await interaction.response.send_message(f"比赛 #{match_id} 不存在。", ephemeral=True)
        if match_row["status"] != "pending":
            conn.close()
            return await interaction.response.send_message(
                f"比赛状态为 `{match_row['status']}`，无法开始。", ephemeral=True
            )

        # 检查分队完成
        cur.execute(
            "SELECT discord_id, team FROM match_signups WHERE match_id=? ORDER BY team, id",
            (match_id,),
        )
        signups = cur.fetchall()
        team_a = [r for r in signups if r["team"] == "A"]
        team_b = [r for r in signups if r["team"] == "B"]

        if not team_a or not team_b:
            conn.close()
            return await interaction.response.send_message(
                "请先用 `/gmpt-assign-ab` 完成 A/B 分队。",
                ephemeral=True,
            )

        # 创建 tournament 条目（兼容现有结算/MVP系统）
        cur.execute(
            "INSERT INTO tournaments (name, max_teams, team_size, status) VALUES (?, 2, 10, 'active')",
            (match_row["name"],),
        )
        tid = cur.lastrowid

        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?, 'A Team A')", (tid,))
        team_a_id = cur.lastrowid
        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?, 'B Team B')", (tid,))
        team_b_id = cur.lastrowid

        for r in team_a:
            cur.execute(
                "INSERT INTO registrations (tournament_id, discord_id, team_id) VALUES (?, ?, ?)",
                (tid, r["discord_id"], team_a_id),
            )
        for r in team_b:
            cur.execute(
                "INSERT INTO registrations (tournament_id, discord_id, team_id) VALUES (?, ?, ?)",
                (tid, r["discord_id"], team_b_id),
            )

        cur.execute("UPDATE matches SET status='active' WHERE id=?", (match_id,))

        conn.commit()
        conn.close()

        # 发送拉人视图
        voice_view = VoicePullView(
            team_a_ids=[r["discord_id"] for r in team_a],
            team_b_ids=[r["discord_id"] for r in team_b],
            guild=interaction.guild,
            timeout=600,
        )

        embed = discord.Embed(
            title=f"比赛开始 / Match Started — {match_row['name']} (ID:{match_id})",
            description=(
                f"Tournament ID: **{tid}**\n"
                f"结算命令：`/gmpt-settle {match_id}`\n"
                f"拉语音：下方按钮 / Pull VC with buttons below"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, view=voice_view)

    # ══════════ 6. 结算 ══════════
    @app_commands.command(
        name="gmpt-settle",
        description="Settle a match (Admin) / 结算比赛（管理员）"
    )
    @app_commands.describe(
        match_id="Match ID (default: latest active) / 比赛ID",
        win_team="Winning team: A or B / 获胜队伍",
    )
    @app_commands.choices(win_team=[
        app_commands.Choice(name="Team A / A队", value="A"),
        app_commands.Choice(name="Team B / B队", value="B"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def settle_cmd(
        self,
        interaction: discord.Interaction,
        win_team: str,
        match_id: int = None,
    ):
        conn = get_db()
        cur = conn.cursor()

        if match_id is None:
            cur.execute("SELECT id, name FROM matches WHERE status='active' ORDER BY id DESC LIMIT 1")
            m = cur.fetchone()
            if not m:
                conn.close()
                return await interaction.response.send_message("没有进行中的比赛。", ephemeral=True)
            match_id = m["id"]

        cur.execute("SELECT id, name, status FROM matches WHERE id=?", (match_id,))
        match_row = cur.fetchone()
        if not match_row:
            conn.close()
            return await interaction.response.send_message(f"比赛 #{match_id} 不存在。", ephemeral=True)
        if match_row["status"] != "active":
            conn.close()
            return await interaction.response.send_message(
                f"比赛状态为 `{match_row['status']}`，无法结算。",
                ephemeral=True,
            )

        cur.execute(
            "SELECT discord_id, team FROM match_signups WHERE match_id=? AND team IS NOT NULL",
            (match_id,),
        )
        signups = cur.fetchall()
        winner_ids = [r["discord_id"] for r in signups if r["team"] == win_team]
        loser_ids = [r["discord_id"] for r in signups if r["team"] != win_team]

        if not winner_ids or not loser_ids:
            conn.close()
            return await interaction.response.send_message(
                "分队数据不完整，请先 `/gmpt-assign-ab` 再 `/gmpt-start-match`。",
                ephemeral=True,
            )

        # 发金币
        for wid in winner_ids:
            cur.execute(
                "INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING",
                (wid,),
            )
            cur.execute("UPDATE users SET score=score+? WHERE discord_id=?", (MATCH_WIN_COINS, wid))
            cur.execute(
                "INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                (wid, MATCH_WIN_COINS, f"Match win #{match_id}"),
            )
        for lid in loser_ids:
            cur.execute(
                "INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING",
                (lid,),
            )
            cur.execute("UPDATE users SET score=score+? WHERE discord_id=?", (MATCH_PARTICIPATE_COINS, lid))
            cur.execute(
                "INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                (lid, MATCH_PARTICIPATE_COINS, f"Match participation #{match_id}"),
            )

        # 成就检查
        all_pids = list(set(winner_ids + loser_ids))
        if all_pids:
            placeholders = ",".join("?" * len(all_pids))
            cur.execute(
                f"SELECT discord_id, COUNT(*) as cnt FROM match_signups WHERE discord_id IN ({placeholders}) GROUP BY discord_id",
                all_pids,
            )
            cnt_map = {row["discord_id"]: row["cnt"] for row in cur.fetchall()}
            for pid in all_pids:
                match_cnt = cnt_map.get(pid, 0)
                check_achievement(pid, "首次参赛")
                if match_cnt >= 5:
                    check_achievement(pid, "参加 5 场")
                if match_cnt >= 10:
                    check_achievement(pid, "参加 10 场")
                if match_cnt >= 25:
                    check_achievement(pid, "参加 25 场")
        for wid in winner_ids:
            check_achievement(wid, "首胜")

        cur.execute("UPDATE matches SET status='finished' WHERE id=?", (match_id,))
        conn.commit()
        conn.close()

        # 更新 MMR
        _update_mmr(winner_ids, loser_ids, mvp_id=None, conn2=None)

        # 发送结算通知
        win_names = []
        for wid in winner_ids:
            m = interaction.guild.get_member(int(wid))
            win_names.append(m.display_name if m else f"<@{wid}>")
        lose_names = []
        for lid in loser_ids:
            m = interaction.guild.get_member(int(lid))
            lose_names.append(m.display_name if m else f"<@{lid}>")

        embed = discord.Embed(
            title=f"比赛结算 / Settled — {match_row['name']} (ID:{match_id})",
            description=(
                f"🏆 **获胜方 Winner**: {' '.join(win_names)}\n"
                f"🏳️ **败方 Loser**: {' '.join(lose_names)}\n\n"
                f"🪙 胜方 +{MATCH_WIN_COINS} coins | 败方 +{MATCH_PARTICIPATE_COINS} coins"
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    # ══════════ 7. 拉语音 ══════════
    @app_commands.command(
        name="gmpt-pull-vc",
        description="Pull Team A/B into voice channels / 拉A/B队成员进入语音频道"
    )
    @app_commands.describe(match_id="Match ID (default: latest active) / 比赛ID")
    async def pull_vc_cmd(self, interaction: discord.Interaction, match_id: int = None):
        conn = get_db()
        cur = conn.cursor()

        if match_id is None:
            cur.execute(
                "SELECT id, name FROM matches WHERE status IN ('pending','active') ORDER BY id DESC LIMIT 1"
            )
            m = cur.fetchone()
            if not m:
                conn.close()
                return await interaction.response.send_message("没有可用的比赛。", ephemeral=True)
            match_id = m["id"]

        cur.execute("SELECT id, name FROM matches WHERE id=?", (match_id,))
        match_row = cur.fetchone()
        if not match_row:
            conn.close()
            return await interaction.response.send_message(f"比赛 #{match_id} 不存在。", ephemeral=True)

        cur.execute(
            "SELECT discord_id, team FROM match_signups WHERE match_id=? AND team IS NOT NULL",
            (match_id,),
        )
        signups = cur.fetchall()
        conn.close()

        team_a_ids = [r["discord_id"] for r in signups if r["team"] == "A"]
        team_b_ids = [r["discord_id"] for r in signups if r["team"] == "B"]

        if not team_a_ids and not team_b_ids:
            return await interaction.response.send_message(
                "该比赛尚未完成 A/B 分队。", ephemeral=True
            )

        voice_view = VoicePullView(
            team_a_ids=team_a_ids,
            team_b_ids=team_b_ids,
            guild=interaction.guild,
            timeout=600,
        )

        embed = discord.Embed(
            title=f"拉语音 — {match_row['name']} (ID:{match_id})",
            description="点击按钮拉 A/B 队成员进入语音频道。",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=voice_view)

    # ══════════ 8. 选队长 ══════════
    @app_commands.command(
        name="gmpt-pick-captain",
        description="Randomly pick 2 captains for draft / 随机选出2位队长"
    )
    @app_commands.describe(match_id="Match ID (default: latest pending) / 比赛ID")
    async def pick_captain_cmd(self, interaction: discord.Interaction, match_id: int = None):
        conn = get_db()
        cur = conn.cursor()

        if match_id is None:
            cur.execute(
                "SELECT id, name FROM matches WHERE status IN ('pending','active') ORDER BY id DESC LIMIT 1"
            )
            m = cur.fetchone()
            if not m:
                conn.close()
                return await interaction.response.send_message("没有可用的比赛。", ephemeral=True)
            match_id = m["id"]

        cur.execute(
            "SELECT discord_id FROM match_signups WHERE match_id=? ORDER BY id",
            (match_id,),
        )
        signups = [r["discord_id"] for r in cur.fetchall()]
        conn.close()

        if len(signups) < 2:
            return await interaction.response.send_message(
                "至少需要 2 名玩家才能选队长。", ephemeral=True
            )

        captains = random.sample(signups, 2)
        cap1_member = interaction.guild.get_member(int(captains[0]))
        cap2_member = interaction.guild.get_member(int(captains[1]))

        cap1_name = cap1_member.display_name if cap1_member else f"<@{captains[0]}>"
        cap2_name = cap2_member.display_name if cap2_member else f"<@{captains[1]}>"

        embed = discord.Embed(
            title=f"队长选择 / Captains — Match #{match_id}",
            description=(
                f"**Captain 1 / 队长 1**: {cap1_name}\n"
                f"**Captain 2 / 队长 2**: {cap2_name}\n\n"
                f"使用 `/gmpt-draft` 进行选秀。\n"
                f"Use `/gmpt-draft` to start the draft."
            ),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Match(bot))
