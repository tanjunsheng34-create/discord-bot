"""
GMPT Bot — Match Prediction (职业赛预测)
Predict on real eSports matches with dynamic odds.
"""
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
from datetime import datetime, timedelta
import logging
from utils.logger import log_error

logger = logging.getLogger(__name__)


def _get_balance(uid: str) -> int:
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (discord_id, username) VALUES (?, 'unknown') ON CONFLICT(discord_id) DO NOTHING",
        (uid,),
    )
    cur.execute("SELECT score FROM users WHERE discord_id=?", (uid,))
    row = cur.fetchone()
    conn.close()
    return row["score"] if row and row["score"] is not None else 0


def _add_coins(uid: str, amount: int, reason: str):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (discord_id, username) VALUES (?, 'unknown') ON CONFLICT(discord_id) DO NOTHING",
        (uid,),
    )
    cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, uid))
    cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)", (uid, amount, reason))
    conn.commit(); conn.close()


def _parse_match_time(time_str: str) -> tuple[str, str]:
    """Parse match time string and return (match_time, cutoff_time) in ISO format."""
    now = datetime.now()
    time_str = time_str.strip()

    # Try "今晚19:00" format
    if "今晚" in time_str:
        time_part = time_str.replace("今晚", "").strip()
        try:
            hour, minute = map(int, time_part.split(":"))
            match_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            raise ValueError("无法解析时间格式 / Cannot parse time format")
    elif "明天" in time_str:
        time_part = time_str.replace("明天", "").strip()
        try:
            hour, minute = map(int, time_part.split(":"))
            match_dt = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            raise ValueError("无法解析时间格式 / Cannot parse time format")
    else:
        # Try "2026-07-23 19:00" format
        try:
            match_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                match_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError("无法解析时间格式，请使用 YYYY-MM-DD HH:MM / Cannot parse time format")

    cutoff_dt = match_dt - timedelta(minutes=5)
    match_time_str = match_dt.strftime("%Y-%m-%d %H:%M")
    cutoff_time_str = cutoff_dt.strftime("%Y-%m-%d %H:%M")
    return match_time_str, cutoff_time_str


def _calculate_odds(predict_id: int) -> dict:
    """Calculate current dynamic odds for both teams."""
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "SELECT team, SUM(amount) as total FROM predict_bets WHERE predict_id=? GROUP BY team",
        (predict_id,),
    )
    rows = cur.fetchall()
    conn.close()

    total_a = 0
    total_b = 0
    for r in rows:
        if r["team"] == "A":
            total_a = r["total"]
        elif r["team"] == "B":
            total_b = r["total"]

    total_pool = total_a + total_b
    odds_a = round(total_pool / max(1, total_a), 1) if total_pool > 0 else 2.0
    odds_b = round(total_pool / max(1, total_b), 1) if total_pool > 0 else 2.0

    return {
        "A": max(1.1, min(odds_a, 10.0)),
        "B": max(1.1, min(odds_b, 10.0)),
        "total_a": total_a,
        "total_b": total_b,
    }


class PredictBetModal(discord.ui.Modal, title="下注 / Place Bet"):
    def __init__(self, predict_id: int, team: str, team_name: str):
        super().__init__(timeout=None)
        self.predict_id = predict_id
        self.team = team
        self.team_name = team_name

        self.amount_field = discord.ui.TextInput(
            label="下注金额 / Bet Amount",
            placeholder="输入正整数 / Enter a positive integer",
            min_length=1,
            max_length=6,
        )
        self.add_item(self.amount_field)

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        try:
            amount = int(self.amount_field.value)
        except ValueError:
            return await interaction.response.send_message("请输入有效数字 / Enter a valid number.", ephemeral=True)

        if amount <= 0:
            return await interaction.response.send_message("下注金额必须为正整数 / Amount must be positive.", ephemeral=True)

        conn = get_db(); cur = conn.cursor()

        # Check game status
        cur.execute("SELECT * FROM predict_games WHERE id=? AND status='open'", (self.predict_id,))
        game = cur.fetchone()
        if not game:
            conn.close()
            return await interaction.response.send_message("预测已截止或不存在 / Prediction closed or not found.", ephemeral=True)

        # Check cutoff
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        if game["cutoff_time"] and now >= game["cutoff_time"]:
            conn.close()
            return await interaction.response.send_message("投注已截止 / Betting is closed.", ephemeral=True)

        # Check if already bet
        cur.execute(
            "SELECT id FROM predict_bets WHERE predict_id=? AND user_id=?",
            (self.predict_id, uid),
        )
        if cur.fetchone():
            conn.close()
            return await interaction.response.send_message("你已在此预测投注过 / You already bet on this match.", ephemeral=True)

        # Check balance
        balance = _get_balance(uid)
        if balance < amount:
            conn.close()
            return await interaction.response.send_message(
                f"金币不足 / Insufficient coins. 余额: 🪙 {balance}", ephemeral=True
            )

        # Deduct and place bet
        _add_coins(uid, -amount, f"预测下注 #{self.predict_id} — {game['team_a' if self.team == 'A' else 'team_b']}")
        cur.execute(
            "INSERT INTO predict_bets (predict_id, user_id, team, amount) VALUES (?,?,?,?)",
            (self.predict_id, uid, self.team, amount),
        )
        conn.commit(); conn.close()

        odds = _calculate_odds(self.predict_id)

        await interaction.response.send_message(
            f"✅ 下注成功！🪙 **{amount}** → **{self.team_name}**\n"
            f"当前赔率：{game['team_a']} {odds['A']}x | {game['team_b']} {odds['B']}x",
            ephemeral=True,
        )

        # Update the original embed with new odds
        try:
            await self._update_odds_display(interaction)
        except Exception:
            pass

    async def _update_odds_display(self, interaction: discord.Interaction):
        """Try to update the original message embed with new odds."""
        pass  # Discord limitations prevent editing the original interaction message here


class PredictView(discord.ui.View):
    def __init__(self, predict_id: int, team_a: str, team_b: str):
        super().__init__(timeout=None)
        self.predict_id = predict_id
        self.team_a = team_a
        self.team_b = team_b

    @discord.ui.button(label="投注 A 队", style=discord.ButtonStyle.primary, emoji="🅰️")
    async def bet_a(self, interaction: discord.Interaction, button):
        modal = PredictBetModal(self.predict_id, "A", self.team_a)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="投注 B 队", style=discord.ButtonStyle.danger, emoji="🅱️")
    async def bet_b(self, interaction: discord.Interaction, button):
        modal = PredictBetModal(self.predict_id, "B", self.team_b)
        await interaction.response.send_modal(modal)


class Predict(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    predict_group = app_commands.Group(
        name="gmpt-predict",
        description="Match prediction betting / 比赛预测竞猜"
    )

    @predict_group.command(name="create", description="Create a prediction game (Admin) / 创建预测盘（管理员）")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        team_a="Team A name / A队名称",
        team_b="Team B name / B队名称",
        match_time="Match time / 比赛时间（如 '今晚19:00' 或 '2026-07-23 19:00'）",
    )
    async def predict_create(self, interaction: discord.Interaction, team_a: str, team_b: str, match_time: str):
        try:
            mt_str, ct_str = _parse_match_time(match_time)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO predict_games (team_a, team_b, match_time, cutoff_time, creator_id) VALUES (?,?,?,?,?)",
            (team_a, team_b, mt_str, ct_str, str(interaction.user.id)),
        )
        predict_id = cur.lastrowid
        conn.commit(); conn.close()

        embed = discord.Embed(
            title="🏆 比赛预测",
            description=f"**{team_a} 🆚 {team_b}**",
            color=discord.Color.blue(),
        )
        embed.add_field(name="比赛时间 / Match Time", value=mt_str, inline=True)
        embed.add_field(name="投注截止 / Cutoff", value=ct_str, inline=True)
        embed.add_field(name="赔率 / Odds", value=f"{team_a}: 2.0x | {team_b}: 2.0x", inline=False)
        embed.set_footer(text=f"预测盘 #{predict_id} | 点击下方按钮投注 ⬇️")

        view = PredictView(predict_id, team_a, team_b)
        await interaction.response.send_message(embed=embed, view=view)

    @predict_group.command(name="settle", description="Settle a prediction game (Admin) / 结算预测盘（管理员）")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        predict_id="Prediction ID / 预测盘编号",
        winner="Winner team / 获胜队伍 (A or B)",
    )
    @app_commands.choices(winner=[
        app_commands.Choice(name="Team A", value="A"),
        app_commands.Choice(name="Team B", value="B"),
    ])
    async def predict_settle(self, interaction: discord.Interaction, predict_id: int, winner: str):
        conn = get_db(); cur = conn.cursor()

        cur.execute("SELECT * FROM predict_games WHERE id=?", (predict_id,))
        game = cur.fetchone()
        if not game:
            conn.close()
            return await interaction.response.send_message("预测盘不存在 / Prediction not found.", ephemeral=True)
        if game["status"] != "open" and game["status"] != "closed":
            conn.close()
            return await interaction.response.send_message("该预测盘已结算 / Already settled.", ephemeral=True)

        # Calculate odds
        cur.execute(
            "SELECT team, SUM(amount) as total FROM predict_bets WHERE predict_id=? GROUP BY team",
            (predict_id,),
        )
        rows = cur.fetchall()
        total_a = 0; total_b = 0
        for r in rows:
            if r["team"] == "A":
                total_a = r["total"]
            elif r["team"] == "B":
                total_b = r["total"]

        total_pool = total_a + total_b
        winners_total = total_a if winner == "A" else total_b

        # Get all bets
        cur.execute("SELECT * FROM predict_bets WHERE predict_id=?", (predict_id,))
        bets = cur.fetchall()

        won_count = 0
        lost_count = 0
        for bet in bets:
            if bet["team"] == winner:
                won_count += 1
                # Payout = amount * (total_pool / winner_pool), with div-by-zero guard
                payout = int(bet["amount"] * total_pool / max(1, winners_total))
                _add_coins(
                    bet["user_id"],
                    payout,
                    f"预测获胜 #{predict_id} — {game['team_a'] if winner == 'A' else game['team_b']} 获胜"
                )
            else:
                lost_count += 1

        cur.execute(
            "UPDATE predict_games SET status='settled', winner=? WHERE id=?",
            (winner, predict_id),
        )
        conn.commit(); conn.close()

        winner_name = game["team_a"] if winner == "A" else game["team_b"]
        odds_val = round(total_pool / max(1, winners_total), 1)

        await interaction.response.send_message(
            f"✅ 预测盘 #{predict_id} 已结算！\n"
            f"🏆 获胜方: **{winner_name}** (Team {winner})\n"
            f"📊 赔率: {odds_val}x | 总奖池: 🪙 {total_pool}\n"
            f"🎉 {won_count} 人获胜 | ❌ {lost_count} 人落败"
        )

    @predict_group.command(name="list", description="List all prediction games / 列出所有预测盘")
    async def predict_list(self, interaction: discord.Interaction):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT * FROM predict_games ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'closed' THEN 1 ELSE 2 END, created_at DESC LIMIT 20"
        )
        games = cur.fetchall()
        conn.close()

        if not games:
            return await interaction.response.send_message("暂无预测盘 / No prediction games yet.")

        embed = discord.Embed(
            title="🏆 预测盘列表 / Prediction Games",
            color=discord.Color.blue(),
        )

        for game in games:
            status_icon = {"open": "🟢", "closed": "🔴", "settled": "✅"}.get(game["status"], "❓")
            status_text = {"open": "进行中", "closed": "已截止", "settled": "已结算"}.get(game["status"], game["status"])

            if game["status"] == "settled":
                winner_name = game["team_a"] if game["winner"] == "A" else game["team_b"]
                value = f"胜者: {winner_name} | {game['match_time']}"
            else:
                value = f"时间: {game['match_time']} | 截止: {game['cutoff_time']}"

            embed.add_field(
                name=f"{status_icon} #{game['id']} — {game['team_a']} vs {game['team_b']} [{status_text}]",
                value=value,
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @predict_create.error
    @predict_settle.error
    @predict_list.error
    async def predict_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        log_error("predict", interaction.command.name if interaction.command else "unknown", error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("发生错误 / An error occurred.", ephemeral=True)
            else:
                await interaction.followup.send("发生错误 / An error occurred.", ephemeral=True)
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(Predict(bot))
