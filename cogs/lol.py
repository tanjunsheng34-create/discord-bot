"""
Gaming Planet Bot — LOL 比赛 + OP.GG 战绩查询
"""
import random
import asyncio
import io
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
from cogs.economy import check_achievement, add_coins
import aiohttp
import os
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("[LOL] Pillow not installed — image features disabled")

RIOT_KEY = os.getenv("RIOT_API_KEY", "")

REGIONS = {
    "kr": ("KR", "asia"),
    "na1": ("NA", "americas"),
    "euw1": ("EUW", "europe"),
    "eun1": ("EUNE", "europe"),
    "jp1": ("JP", "asia"),
    "br1": ("BR", "americas"),
    "la1": ("LAN", "americas"),
    "la2": ("LAS", "americas"),
    "oc1": ("OCE", "sea"),
    "tr1": ("TR", "europe"),
    "ru": ("RU", "europe"),
    "ph2": ("PH", "sea"),
    "sg2": ("SG", "sea"),
    "th2": ("TH", "sea"),
    "tw2": ("TW", "sea"),
    "vn2": ("VN", "sea"),
}

# ---------- Riot API 工具 ----------

async def riot_request(session, url):
    """返回 (status_code, data_or_None)。200 时返回数据，其他返回 None。"""
    headers = {"X-Riot-Token": RIOT_KEY}
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return (200, await resp.json())
            return (resp.status, None)
    except Exception as e:
        return (0, str(e))


async def get_puuid(session, region, name, tag):
    """返回 (puuid, None) 或 (None, error_msg)"""
    url = f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
    code, data = await riot_request(session, url)
    if code == 200 and data:
        return (data["puuid"], None)
    elif code == 403:
        return (None, "API Key 过期或无效（403 Forbidden）。请前往 https://developer.riotgames.com 重新生成。")
    elif code == 404:
        return (None, f"找不到玩家 `{name}#{tag}`。请检查 Riot ID 和 tag 是否正确。")
    elif code == 429:
        return (None, "请求太频繁，请稍后再试。")
    else:
        return (None, f"API 请求失败 (状态码: {code})。")


def tier_emoji(tier):
    emojis = {
        "IRON": "🪨", "BRONZE": "🥉", "SILVER": "🥈",
        "GOLD": "🥇", "PLATINUM": "💎", "EMERALD": "💠",
        "DIAMOND": "🔹", "MASTER": "👑", "GRANDMASTER": "🏆", "CHALLENGER": "⚡"
    }
    return emojis.get(tier.upper(), "❓")


# ---------- 对战图生成 ----------

def _generate_battle_image(tournament_name, blue_team, red_team):
    """
    生成一张蓝队 vs 红队的对战图片。
    """
    W, H = 800, 100 + max(len(blue_team), len(red_team)) * 56
    img = Image.new("RGB", (W, H), "#1a1a2e")
    draw = ImageDraw.Draw(img)

    try:
        title_font = ImageFont.truetype("arial.ttf", 32)
        team_font = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        title_font = ImageFont.load_default()
        team_font = ImageFont.load_default()

    draw.text((W // 2, 20), tournament_name, fill="#f5c842", font=title_font, anchor="ma")
    draw.line([(0, 60), (W, 60)], fill="#444", width=2)

    draw.text((W // 4, 75), "BLUE TEAM", fill="#00b4d8", font=team_font, anchor="ma")
    for i, name in enumerate(blue_team):
        y = 110 + i * 52
        draw.text((W // 4, y), name, fill="#e0e0e0", font=team_font, anchor="ma")

    draw.text((W * 3 // 4, 75), "RED TEAM", fill="#e63946", font=team_font, anchor="ma")
    for i, name in enumerate(red_team):
        y = 110 + i * 52
        draw.text((W * 3 // 4, y), name, fill="#e0e0e0", font=team_font, anchor="ma")

    draw.line([(W // 2, 70), (W // 2, H)], fill="#555", width=2)
    vs_y = 105 + max(len(blue_team), len(red_team)) * 26
    draw.ellipse([(W // 2 - 40, vs_y - 40), (W // 2 + 40, vs_y + 40)], fill="#f5c842")
    draw.text((W // 2, vs_y), "VS", fill="#1a1a2e", font=title_font, anchor="ma")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _generate_result_image(tournament_name, winner_name, winner_players, loser_players):
    """生成比赛结果图，胜方高亮。"""
    W, H = 800, 130 + max(len(winner_players), len(loser_players)) * 56
    img = Image.new("RGB", (W, H), "#1a1a2e")
    draw = ImageDraw.Draw(img)

    try:
        title_font = ImageFont.truetype("arial.ttf", 30)
        team_font = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        title_font = ImageFont.load_default()
        team_font = ImageFont.load_default()

    draw.text((W // 2, 20), f"MATCH RESULT", fill="#f5c842", font=title_font, anchor="ma")
    draw.text((W // 2, 55), tournament_name, fill="#c0c0c0", font=team_font, anchor="ma")
    draw.line([(0, 80), (W, 80)], fill="#444", width=2)

    # 胜方
    draw.text((W // 4, 95), f"WINNER: {winner_name}", fill="#ffd700", font=team_font, anchor="ma")
    for i, name in enumerate(winner_players):
        y = 130 + i * 48
        draw.text((W // 4, y), f"🏆 {name}", fill="#ffd700", font=team_font, anchor="ma")

    # 败方
    draw.text((W * 3 // 4, 95), "LOSER", fill="#999", font=team_font, anchor="ma")
    for i, name in enumerate(loser_players):
        y = 130 + i * 48
        draw.text((W * 3 // 4, y), name, fill="#888", font=team_font, anchor="ma")

    draw.line([(W // 2, 85), (W // 2, H)], fill="#555", width=2)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ---------- Cog ----------

class GMPT(commands.Cog):
    """Gaming Planet 全能 Bot"""

    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.watch_channels = set()  # 被监控的频道 ID

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    # ---------- 自动检测开黑 ----------
    LFG_KEYWORDS = [
        "有人玩吗", "有人吗", "找人", "开黑", "组队", "来不来",
        "来玩", "有人玩", "一起玩", "缺人", "来个人",
        "duo", "flex", "aram", "clash", "custom", "5v5",
        "ranked", "looking", "lfg", "need", "s/d", "sd",
        "单双", "灵活", "大乱斗", "极地", "custom", "tft",
    ]

    # 关键词 → 身份组名（模糊匹配）
    ROLE_MAP = [
        (["s/d", "sd", "solo", "duo", "单双"], "S/D"),
        (["flex", "灵活"], "Flex"),
        (["aram", "大乱斗", "极地"], "ARAM"),
        (["summoner", "rift", "sr", "召唤"], "Summoner's Rift"),
        (["custom", "自定义"], "Custom Game"),
        (["tft", "云顶"], "TFT"),
    ]

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.channel.id not in self.watch_channels:
            return

        content = message.content.lower()
        if not any(kw in content for kw in self.LFG_KEYWORDS):
            return

        guild = message.guild
        if not guild:
            return

        # 匹配身份组
        ping_roles = []
        for keywords, role_name in self.ROLE_MAP:
            if any(kw in content for kw in keywords):
                role = discord.utils.find(
                    lambda r: role_name.lower() in r.name.lower(), guild.roles
                )
                if role:
                    ping_roles.append(role.mention)

        # 创建临时频道
        ch_name = f"lfg-{message.author.name}"[:25].replace(" ", "-")
        category = discord.utils.get(guild.categories, name="TEMP ZONES")
        if not category:
            category = await guild.create_category("TEMP ZONES")

        ch = await guild.create_text_channel(
            name=ch_name,
            category=category,
            topic=f"{message.author.name} 找人开黑 — 5分钟后自动关闭",
        )

        role_tags = " ".join(ping_roles) if ping_roles else ""
        first_line = (
            f"{message.author.mention} 在 {message.channel.mention} 找人开黑！"
        )
        await ch.send(
            f"{role_tags}\n"
            f"{first_line}\n"
            f"> {message.content[:200]}\n\n"
            f"此频道 5 分钟后自动删除。"
        )
        await message.add_reaction("🎮")

        # 5 分钟后删除
        await asyncio.sleep(300)
        try:
            await ch.delete()
        except:
            pass

    # ============ 设置自动监控 ============
    @app_commands.command(
        name="gmpt-autozone",
        description="Toggle auto LFG detect / 开启/关闭当前频道自动开黑检测",
    )
    async def autozone(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if cid in self.watch_channels:
            self.watch_channels.discard(cid)
            await interaction.response.send_message("已关闭本频道的自动开黑检测。", ephemeral=True)
        else:
            self.watch_channels.add(cid)
            await interaction.response.send_message(
                "已开启本频道自动检测！有人发找人/开黑等消息时自动创建临时频道，5分钟后删除。",
                ephemeral=True,
            )

    # ============ 创建比赛 ============
    @app_commands.command(
        name="gmpt-create",
        description="Create a LOL match / 创建比赛",
    )
    @app_commands.describe(
        match_name="Match name / 比赛名称",
        max_players="Max players / 最大人数 (默认10)",
    )
    async def create_match(
        self, interaction: discord.Interaction,
        match_name: str, max_players: int = 10,
    ):
        if max_players < 2 or max_players % 2 != 0:
            return await interaction.response.send_message(
                "人数必须为大于2的偶数。", ephemeral=True,
            )
        team_size = max_players // 2
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO tournaments (name, max_teams, team_size, created_by) VALUES (?, 2, ?, ?)",
            (match_name, team_size, str(interaction.user.id)),
        )
        conn.commit(); tid = cur.lastrowid; conn.close()

        embed = discord.Embed(
            title=f"Match: {match_name}",
            description=f"**{max_players}** 人 | 每队 {team_size}\n报名: `/gmpt-join {tid}`",
            color=discord.Color.gold(),
        ).set_footer(text=f"Match ID: {tid}")
        await interaction.response.send_message(embed=embed)

    # ============ 报名 ============
    @app_commands.command(
        name="gmpt-join",
        description="Join a match / 报名",
    )
    @app_commands.describe(match_id="Match ID")
    async def join_match(
        self, interaction: discord.Interaction,
        match_id: int,
    ):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM tournaments WHERE id=?", (match_id,))
        t = cur.fetchone()
        if not t: conn.close(); return await interaction.response.send_message("比赛不存在。", ephemeral=True)
        if t["status"] != "open": conn.close(); return await interaction.response.send_message("报名已关闭。", ephemeral=True)
        max_p = t["max_teams"] * t["team_size"]
        cur.execute("SELECT COUNT(*) as cnt FROM registrations WHERE tournament_id=?", (match_id,))
        cnt = cur.fetchone()["cnt"]
        if cnt >= max_p: conn.close(); return await interaction.response.send_message("报名已满。", ephemeral=True)
        uid = str(interaction.user.id)
        try:
            cur.execute("INSERT INTO registrations (tournament_id, discord_id) VALUES (?,?)", (match_id, uid))
            cur.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (uid, interaction.user.name))
            conn.commit()
        except: conn.close(); return await interaction.response.send_message("已报名。", ephemeral=True)
        conn.close()
        await interaction.response.send_message(f"{interaction.user.mention} 报名成功！({cnt+1}/{max_p})")

    # ============ 分队 ============
    @app_commands.command(
        name="gmpt-shuffle",
        description="Split into 2 teams / 分队",
    )
    @app_commands.describe(match_id="Match ID")
    async def shuffle(self, interaction: discord.Interaction, match_id: int):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM tournaments WHERE id=?", (match_id,))
        t = cur.fetchone()
        if not t: conn.close(); return await interaction.response.send_message("比赛不存在。", ephemeral=True)
        if t["status"] != "open": conn.close(); return await interaction.response.send_message("已分队。", ephemeral=True)
        cur.execute("SELECT discord_id FROM registrations WHERE tournament_id=? ORDER BY RANDOM()", (match_id,))
        players = [r["discord_id"] for r in cur.fetchall()]
        if len(players) < 2: conn.close(); return await interaction.response.send_message("人数不足。", ephemeral=True)
        mid = min(t["team_size"], len(players)//2)
        ta, tb = players[:mid], players[mid:mid*2]

        # 获取用户名用于图片
        blue_names = []
        red_names = []
        for uid in ta:
            member = interaction.guild.get_member(int(uid))
            blue_names.append(member.display_name if member else uid)
        for uid in tb:
            member = interaction.guild.get_member(int(uid))
            red_names.append(member.display_name if member else uid)

        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (match_id, "蓝队 Blue"))
        aid = cur.lastrowid
        for u in ta: cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?", (aid, match_id, u))
        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (match_id, "红队 Red"))
        bid = cur.lastrowid
        for u in tb: cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?", (bid, match_id, u))
        cur.execute("UPDATE tournaments SET status='closed' WHERE id=?", (match_id,))
        conn.commit(); conn.close()

        # 生成对战图
        if PIL_AVAILABLE:
            img_buf = _generate_battle_image(t["name"], blue_names, red_names)
            f = discord.File(img_buf, filename="battle.png")
            embed = discord.Embed(
                title=f"Match: {t['name']}",
                description=(
                    f"🔵 **蓝队 Blue** (ID:{aid}): {' '.join(f'<@{u}>' for u in ta)}\n"
                    f"🔴 **红队 Red** (ID:{bid}): {' '.join(f'<@{u}>' for u in tb)}\n\n"
                    f"结算: `/gmpt-settle {match_id} <获胜队伍ID>`"
                ),
                color=discord.Color.gold(),
            )
            embed.set_image(url="attachment://battle.png")
            await interaction.response.send_message(file=f, embed=embed)
        else:
            await interaction.response.send_message(
                f"**Match: {t['name']}**\n\n"
                f"🔵 **蓝队 Blue** (ID:{aid}): {' '.join(f'<@{u}>' for u in ta)}\n"
                f"🔴 **红队 Red** (ID:{bid}): {' '.join(f'<@{u}>' for u in tb)}\n\n"
                f"结算: `/gmpt-settle {match_id} <获胜队伍ID>`"
            )

    # ============ 结算 ============
    @app_commands.command(
        name="gmpt-settle",
        description="Settle match / 结算积分",
    )
    @app_commands.describe(match_id="Match ID", win_team_id="Winning team ID", mvp="MVP")
    async def settle(
        self, interaction: discord.Interaction,
        match_id: int, win_team_id: int,
        mvp: discord.Member = None,
    ):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM tournaments WHERE id=?", (match_id,))
        t = cur.fetchone()
        if not t: conn.close(); return await interaction.response.send_message("比赛不存在。", ephemeral=True)
        if t["status"] == "finished": conn.close(); return await interaction.response.send_message("已结算。", ephemeral=True)

        # 胜方 +150 coins
        cur.execute("SELECT discord_id FROM registrations WHERE tournament_id=? AND team_id=?", (match_id, win_team_id))
        winner_ids = [r["discord_id"] for r in cur.fetchall()]
        for wid in winner_ids:
            cur.execute("UPDATE users SET score=score+150 WHERE discord_id=?", (wid,))
            cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                         (wid, 150, f"比赛胜利 #{match_id}"))
        cur.execute("INSERT INTO results (tournament_id,team_id,rank,score_awarded) VALUES (?,?,1,150)", (match_id, win_team_id))

        # 败方 +50 coins
        cur.execute("SELECT discord_id FROM registrations WHERE tournament_id=? AND team_id!=?", (match_id, win_team_id))
        loser_ids = [r["discord_id"] for r in cur.fetchall()]
        for lid in loser_ids:
            cur.execute("UPDATE users SET score=score+50 WHERE discord_id=?", (lid,))
            cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                         (lid, 50, f"比赛参与 #{match_id}"))

        mvp_text = ""
        mvp_id = ""
        if mvp:
            mvp_id = str(mvp.id)
            cur.execute("UPDATE users SET score=score+50 WHERE discord_id=?", (mvp_id,))
            cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                         (mvp_id, 50, f"MVP #{match_id}"))
            mvp_text = f"\n🏅 MVP: {mvp.mention} +50"

        cur.execute("UPDATE tournaments SET status='finished' WHERE id=?", (match_id,))
        conn.commit()

        # === 成就检测 ===
        all_participants = winner_ids + loser_ids
        for pid in set(all_participants):
            conn2 = get_db(); cur2 = conn2.cursor()
            # 参赛次数
            cur2.execute("SELECT COUNT(*) as cnt FROM registrations WHERE discord_id=?", (pid,))
            match_cnt = cur2.fetchone()["cnt"]
            conn2.close()
            check_achievement(pid, "首次参赛")
            if match_cnt >= 5:
                check_achievement(pid, "参加 5 场")
            if match_cnt >= 10:
                check_achievement(pid, "参加 10 场")
            if match_cnt >= 25:
                check_achievement(pid, "参加 25 场")

        for wid in winner_ids:
            check_achievement(wid, "首胜")

        if mvp_id:
            check_achievement(mvp_id, "MVP")

        # 获取两队玩家名用于生成结果图
        winner_name = cur.execute("SELECT name FROM teams WHERE id=?", (win_team_id,)).fetchone()
        winner_name = winner_name["name"] if winner_name else "胜方"
        cur.execute("SELECT name FROM teams WHERE tournament_id=? AND id!=?", (match_id, win_team_id))
        loser_row = cur.fetchone()
        loser_name = loser_row["name"] if loser_row else "败方"

        win_names = []
        los_names = []
        for uid in winner_ids:
            m = interaction.guild.get_member(int(uid))
            win_names.append(m.display_name if m else uid)
        for uid in loser_ids:
            m = interaction.guild.get_member(int(uid))
            los_names.append(m.display_name if m else uid)

        conn.close()

        if PIL_AVAILABLE:
            img_buf = _generate_result_image(t["name"], winner_name, win_names, los_names)
            f = discord.File(img_buf, filename="result.png")
            embed = discord.Embed(
                title=f"Match: {t['name']} - 已结算",
                description=(
                    f"🏆 **{winner_name}** 胜方每人 +100\n"
                    f"💔 败方每人 +20{mvp_text}"
                ),
                color=discord.Color.gold(),
            )
            embed.set_image(url="attachment://result.png")
            await interaction.response.send_message(file=f, embed=embed)
        else:
            await interaction.response.send_message(
                f"**Match: {t['name']} - 已结算**\n\n"
                f"🏆 **{winner_name}** 胜方每人 +100\n"
                f"💔 败方每人 +20{mvp_text}"
            )

    # ============ 查看玩家 ============
    @app_commands.command(
        name="gmpt-players",
        description="List match players / 查看报名玩家",
    )
    @app_commands.describe(match_id="Match ID")
    async def players(self, interaction: discord.Interaction, match_id: int):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM tournaments WHERE id=?", (match_id,))
        t = cur.fetchone()
        if not t: conn.close(); return await interaction.response.send_message("比赛不存在。", ephemeral=True)
        cur.execute("SELECT discord_id FROM registrations WHERE tournament_id=?", (match_id,))
        rows = cur.fetchall(); conn.close()
        if not rows: return await interaction.response.send_message("暂无玩家报名。")
        max_p = t["max_teams"] * t["team_size"]
        pings = " ".join(f"<@{r['discord_id']}>" for r in rows)
        await interaction.response.send_message(
            f"**{t['name']}** 报名玩家 ({len(rows)}/{max_p}):\n{pings}"
        )

    # ============ 踢人 ============
    @app_commands.command(
        name="gmpt-kick",
        description="Kick a player / 踢出玩家",
    )
    @app_commands.describe(match_id="Match ID", player="Player to kick")
    async def kick(
        self, interaction: discord.Interaction,
        match_id: int, player: discord.Member,
    ):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT created_by FROM tournaments WHERE id=?", (match_id,))
        t = cur.fetchone()
        if not t: conn.close(); return await interaction.response.send_message("比赛不存在。", ephemeral=True)
        if str(interaction.user.id) != t["created_by"]:
            conn.close(); return await interaction.response.send_message("只有比赛创建者可以踢人。", ephemeral=True)
        cur.execute("DELETE FROM registrations WHERE tournament_id=? AND discord_id=?", (match_id, str(player.id)))
        conn.commit(); conn.close()
        await interaction.response.send_message(f"{player.mention} 已被踢出比赛。")

    # ============ 取消比赛 ============
    @app_commands.command(
        name="gmpt-cancel",
        description="Cancel a match / 取消比赛",
    )
    @app_commands.describe(match_id="Match ID")
    async def cancel(self, interaction: discord.Interaction, match_id: int):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT created_by, status FROM tournaments WHERE id=?", (match_id,))
        t = cur.fetchone()
        if not t: conn.close(); return await interaction.response.send_message("比赛不存在。", ephemeral=True)
        if str(interaction.user.id) != t["created_by"]:
            conn.close(); return await interaction.response.send_message("只有创建者可以取消。", ephemeral=True)
        cur.execute("DELETE FROM registrations WHERE tournament_id=?", (match_id,))
        cur.execute("DELETE FROM teams WHERE tournament_id=?", (match_id,))
        cur.execute("DELETE FROM results WHERE tournament_id=?", (match_id,))
        cur.execute("DELETE FROM tournaments WHERE id=?", (match_id,))
        conn.commit(); conn.close()
        await interaction.response.send_message(f"比赛 {match_id} 已取消，所有报名数据已清除。")

    # ============ 历史记录 ============
    @app_commands.command(
        name="gmpt-history",
        description="Match history / 历史比赛",
    )
    async def history(self, interaction: discord.Interaction):
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            SELECT t.id, t.name, t.team_size, r.win_team, r.mvp_id, t.created_at
            FROM tournaments t
            LEFT JOIN (
                SELECT tournament_id,
                       MAX(CASE WHEN rank=1 THEN team_id END) as win_team,
                       NULL as mvp_id
                FROM results GROUP BY tournament_id
            ) r ON t.id = r.tournament_id
            WHERE t.status='finished'
            ORDER BY t.created_at DESC LIMIT 10
        """)
        rows = cur.fetchall()
        if not rows: conn.close(); return await interaction.response.send_message("暂无历史比赛。")
        lines = ["**历史比赛 Top 10**\n"]
        for i, row in enumerate(rows, 1):
            cur.execute("SELECT discord_id FROM registrations WHERE tournament_id=? AND team_id=?", (row["id"], row["win_team"]))
            winners = [f"<@{r['discord_id']}>" for r in cur.fetchall()]
            lines.append(
                f"`#{i}` **{row['name']}** | {row['team_size']}v{row['team_size']} | "
                f"胜方: {' '.join(winners) if winners else '?'}"
            )
        conn.close()
        await interaction.response.send_message("\n".join(lines))

    # ============ 选手直播通知 ============
    @app_commands.command(
        name="gmpt-stream",
        description="Share your stream link / 分享直播链接",
    )
    @app_commands.describe(
        match_id="Match ID",
        link="Stream URL (Twitch/YouTube/Bilibili etc.)",
    )
    async def stream(self, interaction: discord.Interaction, match_id: int, link: str):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id, name FROM tournaments WHERE id=?", (match_id,))
        t = cur.fetchone()
        if not t:
            conn.close(); return await interaction.response.send_message("比赛不存在。", ephemeral=True)
        cur.execute(
            "SELECT discord_id FROM registrations WHERE tournament_id=? AND discord_id=?",
            (match_id, str(interaction.user.id)),
        )
        reg = cur.fetchone()
        if not reg:
            conn.close(); return await interaction.response.send_message("你未报名该比赛。", ephemeral=True)
        cur.execute(
            "SELECT discord_id FROM registrations WHERE tournament_id=? AND discord_id!=?",
            (match_id, str(interaction.user.id)),
        )
        others = cur.fetchall(); conn.close()

        pings = " ".join([f"<@{r['discord_id']}>" for r in others])
        if not pings:
            return await interaction.response.send_message("该比赛暂无其他选手。")
        await interaction.response.send_message(
            f"**📺 {interaction.user.display_name} 开播啦！**\n"
            f"比赛: **{t['name']}** (ID: {match_id})\n"
            f"{pings}\n"
            f"直播链接: {link}"
        )

    # ============ 排行榜 ============
    @app_commands.command(
        name="gmpt-rank",
        description="Leaderboard / 排行榜",
    )
    async def rank(self, interaction: discord.Interaction):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT username, score FROM users WHERE score>0 ORDER BY score DESC LIMIT 20")
        rows = cur.fetchall(); conn.close()
        if not rows: return await interaction.response.send_message("暂无积分。")
        lines = ["**积分排行榜 Top 20**\n"]
        for i, r in enumerate(rows, 1):
            m = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"#{i}"
            lines.append(f"{m} **{r['username']}** — {r['score']} 分")
        await interaction.response.send_message("\n".join(lines))

    # ============ 查段位 ============
    @app_commands.command(
        name="gmpt-profile",
        description="Lookup summoner profile / 查玩家段位",
    )
    @app_commands.describe(
        name="Riot ID name (名前)", tag="Riot ID tag (タグ #后面的)",
        region="Server region / 服务器",
    )
    @app_commands.choices(region=[
        app_commands.Choice(name="KR (한국)", value="kr"),
        app_commands.Choice(name="NA (北美)", value="na1"),
        app_commands.Choice(name="EUW (欧西)", value="euw1"),
        app_commands.Choice(name="JP (日本)", value="jp1"),
        app_commands.Choice(name="TW (台湾)", value="tw2"),
        app_commands.Choice(name="VN (越南)", value="vn2"),
        app_commands.Choice(name="SG (新加坡)", value="sg2"),
        app_commands.Choice(name="PH (菲律宾)", value="ph2"),
    ])
    async def profile(
        self, interaction: discord.Interaction,
        name: str, tag: str, region: str,
    ):
        await interaction.response.defer()
        if not RIOT_KEY:
            return await interaction.followup.send("Riot API Key 未配置。")

        cont_region = REGIONS[region][1]
        puuid, err = await get_puuid(self.session, cont_region, name, tag)
        if err:
            return await interaction.followup.send(err)

        # 查召唤师等级 + 头像
        url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        code, summ = await riot_request(self.session, url)
        if code != 200:
            return await interaction.followup.send(f"获取召唤师数据失败 (状态码: {code})。")

        # 查段位
        url2 = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summ['id']}"
        _, leagues = await riot_request(self.session, url2)
        if not leagues:
            leagues = []

        icon = f"https://ddragon.leagueoflegends.com/cdn/13.24.1/img/profileicon/{summ['profileIconId']}.png"
        embed = discord.Embed(
            title=f"{name}#{tag}",
            description=f"Level {summ['summonerLevel']}",
            color=discord.Color.blue(),
        ).set_thumbnail(url=icon)

        solo = next((l for l in leagues if l["queueType"] == "RANKED_SOLO_5x5"), None)
        flex = next((l for l in leagues if l["queueType"] == "RANKED_FLEX_SR"), None)

        if solo:
            embed.add_field(name="单双排 Solo/Duo", value=f"{tier_emoji(solo['tier'])} {solo['tier']} {solo['rank']} - {solo['leaguePoints']}LP\n{solo['wins']}W {solo['losses']}L ({round(solo['wins']/(solo['wins']+solo['losses'])*100)}%)", inline=False)
        if flex:
            embed.add_field(name="灵活组排 Flex", value=f"{tier_emoji(flex['tier'])} {flex['tier']} {flex['rank']} - {flex['leaguePoints']}LP\n{flex['wins']}W {flex['losses']}L ({round(flex['wins']/(flex['wins']+flex['losses'])*100)}%)", inline=False)
        if not leagues:
            embed.add_field(name="段位", value="Unranked 未定级", inline=False)

        await interaction.followup.send(embed=embed)

    # ============ 战绩 ============
    @app_commands.command(
        name="gmpt-match",
        description="Recent match history / 最近战绩",
    )
    @app_commands.describe(
        name="Riot ID name", tag="Riot ID tag",
        region="Server region", count="Number of matches (1-10)",
    )
    @app_commands.choices(region=[
        app_commands.Choice(name="KR", value="kr"),
        app_commands.Choice(name="NA", value="na1"),
        app_commands.Choice(name="EUW", value="euw1"),
        app_commands.Choice(name="JP", value="jp1"),
        app_commands.Choice(name="TW", value="tw2"),
        app_commands.Choice(name="VN", value="vn2"),
        app_commands.Choice(name="SG", value="sg2"),
    ])
    async def match_history(
        self, interaction: discord.Interaction,
        name: str, tag: str, region: str, count: int = 5,
    ):
        await interaction.response.defer()
        if not RIOT_KEY or not self.session:
            return await interaction.followup.send("Riot API Key 未配置。")

        cont_region = REGIONS[region][1]
        puuid, err = await get_puuid(self.session, cont_region, name, tag)
        if err:
            return await interaction.followup.send(err)

        count = min(count, 10)
        url = f"https://{cont_region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count={count}"
        headers = {"X-Riot-Token": RIOT_KEY}
        async with self.session.get(url, headers=headers) as resp:
            match_ids = await resp.json() if resp.status == 200 else []

        if not match_ids:
            return await interaction.followup.send("未找到战绩。")

        lines = [f"**{name}#{tag}** 最近 {len(match_ids)} 场:\n"]
        for i, mid in enumerate(match_ids, 1):
            murl = f"https://{cont_region}.api.riotgames.com/lol/match/v5/matches/{mid}"
            async with self.session.get(murl, headers=headers) as resp:
                if resp.status != 200: continue
                m = await resp.json()
            part = next((p for p in m["info"]["participants"] if p["puuid"]==puuid), None)
            if not part: continue
            win = "✅" if part["win"] else "❌"
            k = part["kills"]; d = part["deaths"]; a = part["assists"]
            kda = f"{k}/{d}/{a}"
            cs = part["totalMinionsKilled"] + part.get("neutralMinionsKilled", 0)
            dur = f"{m['info']['gameDuration']//60}min"
            lines.append(f"`#{i}` {win} **{part['championName']}** {kda} | CS:{cs} | {dur}")

        await interaction.followup.send("\n".join(lines))

    # ============ 实时对局 ============
    @app_commands.command(
        name="gmpt-live",
        description="Live game info / 当前对局",
    )
    @app_commands.describe(
        name="Riot ID name", tag="Riot ID tag", region="Server region",
    )
    @app_commands.choices(region=[
        app_commands.Choice(name="KR", value="kr"),
        app_commands.Choice(name="NA", value="na1"),
        app_commands.Choice(name="EUW", value="euw1"),
        app_commands.Choice(name="JP", value="jp1"),
        app_commands.Choice(name="TW", value="tw2"),
        app_commands.Choice(name="VN", value="vn2"),
        app_commands.Choice(name="SG", value="sg2"),
    ])
    async def live_game(
        self, interaction: discord.Interaction,
        name: str, tag: str, region: str,
    ):
        await interaction.response.defer()
        if not RIOT_KEY: return await interaction.followup.send("Riot API Key 未配置。")

        cont_region = REGIONS[region][1]
        puuid, err = await get_puuid(self.session, cont_region, name, tag)
        if err: return await interaction.followup.send(err)

        url = f"https://{region}.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/{puuid}"
        code, data = await riot_request(self.session, url)
        if code == 404:
            return await interaction.followup.send(f"`{name}#{tag}` 当前不在对局中。")
        if code != 200:
            return await interaction.followup.send(f"查询失败 (状态码: {code})。")

        part = next((p for p in data["participants"] if p["puuid"]==puuid), None)
        if not part: return await interaction.followup.send("数据异常。")

        team100 = [p for p in data["participants"] if p["teamId"]==100]
        team200 = [p for p in data["participants"] if p["teamId"]==200]
        player_team = "蓝队" if part["teamId"]==100 else "红队"

        lines = [
            f"**{name}#{tag}** 当前对局中 ({player_team})",
            f"模式: {data['gameMode']} | 时长: {data['gameLength']//60}min",
            "",
            "🔵 **蓝队**: " + " ".join(p["championName"] for p in team100),
            "🔴 **红队**: " + " ".join(p["championName"] for p in team200),
        ]
        await interaction.followup.send("\n".join(lines))


    # ============ 临时讨论区 ============
    @app_commands.command(
        name="gmpt-zone",
        description="Create temp channels / 创建临时子区 (自动删除)",
    )
    @app_commands.describe(
        topics="Channel topics (逗号分隔)", minutes="Auto-close mins (default 5)",
    )
    async def temp_zone(
        self, interaction: discord.Interaction,
        topics: str = "Summoner's Rift,S/D,Flex,ARAM",
        minutes: int = 5,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            return await interaction.followup.send("仅限服务器内使用。")

        # 找或创建父分类
        category = discord.utils.get(guild.categories, name="TEMP ZONES")
        if not category:
            category = await guild.create_category("TEMP ZONES")

        channel_list = topics.split(",")
        created = []

        for ch_name in channel_list:
            ch_name = ch_name.strip()
            if not ch_name:
                continue
            ch = await guild.create_text_channel(
                name=ch_name.replace("'", ""),
                category=category,
                topic=f"临时频道 - {minutes}分钟后自动删除",
            )
            created.append(ch.mention)

        await interaction.followup.send(
            f"已创建 {len(created)} 个临时频道：{' '.join(created)}\n"
            f"{minutes} 分钟后自动删除。",
        )

        # 延迟删除
        await asyncio.sleep(minutes * 60)
        for ch_name in channel_list:
            ch_name = ch_name.strip()
            if not ch_name:
                continue
            ch = discord.utils.get(guild.text_channels, name=ch_name.replace("'", ""), category=category)
            if ch:
                try:
                    await ch.delete()
                except:
                    pass

    # ============ Riot API 状态检测 ============
    @app_commands.command(
        name="gmpt-riot-status",
        description="Check Riot API Key status / 检测 API Key 是否有效",
    )
    async def riot_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not RIOT_KEY:
            return await interaction.followup.send("❌ Riot API Key 未配置。请在 Railway 环境变量中设置 `RIOT_API_KEY`。")

        # 用已知玩家测试 key 有效性
        url = "https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/Hide%20on%20bush/KR1"
        code, data = await riot_request(self.session, url)
        if code == 200:
            await interaction.followup.send(
                f"✅ API Key 有效！\n测试玩家: `{data.get('gameName', 'N/A')}#{data.get('tagLine', 'N/A')}`\nPUUID: `{data['puuid']}`"
            )
        elif code == 403:
            await interaction.followup.send(
                "❌ API Key **已过期或无效** (403 Forbidden)。\n"
                "Riot 开发密钥有效期仅 **24 小时**。\n"
                "请前往 https://developer.riotgames.com 重新生成，然后更新 Railway 环境变量。"
            )
        elif code == 429:
            await interaction.followup.send("⚠️ 请求太频繁，请稍后再试 (429)。")
        else:
            await interaction.followup.send(f"⚠️ 请求失败，状态码: {code}")


async def setup(bot):
    await bot.add_cog(GMPT(bot))
