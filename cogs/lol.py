"""
Gaming Planet Bot — LOL 比赛 + OP.GG 战绩查询
"""
import random
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
import aiohttp
import os

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
    headers = {"X-Riot-Token": RIOT_KEY}
    async with session.get(url, headers=headers) as resp:
        if resp.status == 200:
            return await resp.json()
        return None


async def get_puuid(session, region, name, tag):
    url = f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
    data = await riot_request(session, url)
    return data["puuid"] if data else None


def tier_emoji(tier):
    emojis = {
        "IRON": "🪨", "BRONZE": "🥉", "SILVER": "🥈",
        "GOLD": "🥇", "PLATINUM": "💎", "EMERALD": "💠",
        "DIAMOND": "🔹", "MASTER": "👑", "GRANDMASTER": "🏆", "CHALLENGER": "⚡"
    }
    return emojis.get(tier.upper(), "❓")


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
        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (match_id, "蓝队 Blue"))
        aid = cur.lastrowid
        for u in ta: cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?", (aid, match_id, u))
        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (match_id, "红队 Red"))
        bid = cur.lastrowid
        for u in tb: cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?", (bid, match_id, u))
        cur.execute("UPDATE tournaments SET status='closed' WHERE id=?", (match_id,))
        conn.commit(); conn.close()
        await interaction.response.send_message(
            f"**{t['name']}** 分队结果：\n\n"
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
        cur.execute("SELECT discord_id FROM registrations WHERE tournament_id=? AND team_id=?", (match_id, win_team_id))
        for r in cur.fetchall():
            cur.execute("UPDATE users SET score=score+100 WHERE discord_id=?", (r["discord_id"],))
        cur.execute("INSERT INTO results (tournament_id,team_id,rank,score_awarded) VALUES (?,?,1,100)", (match_id, win_team_id))
        cur.execute("SELECT discord_id FROM registrations WHERE tournament_id=? AND team_id!=?", (match_id, win_team_id))
        for r in cur.fetchall():
            cur.execute("UPDATE users SET score=score+20 WHERE discord_id=?", (r["discord_id"],))
        mvp_text = ""
        if mvp:
            cur.execute("UPDATE users SET score=score+50 WHERE discord_id=?", (str(mvp.id),))
            mvp_text = f"\n🏅 MVP: {mvp.mention} +50"
        cur.execute("UPDATE tournaments SET status='finished' WHERE id=?", (match_id,))
        conn.commit(); conn.close()
        await interaction.response.send_message(
            f"**{t['name']}** 结算完毕！\n胜方每人 +100 | 败方每人 +20{mvp_text}"
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
        puuid = await get_puuid(self.session, cont_region, name, tag)
        if not puuid:
            return await interaction.followup.send(f"找不到玩家 `{name}#{tag}`。")

        # 查召唤师等级 + 头像
        url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        summ = await riot_request(self.session, url)
        if not summ:
            return await interaction.followup.send("获取召唤师数据失败。")

        # 查段位
        url2 = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summ['id']}"
        leagues = await riot_request(self.session, url2)
        if not leagues:
            leagues = []

        # 查大师分段
        url3 = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summ['id']}"
        leagues = await riot_request(self.session, url3) or []

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
        puuid = await get_puuid(self.session, cont_region, name, tag)
        if not puuid:
            return await interaction.followup.send(f"找不到玩家 `{name}#{tag}`。")

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
        puuid = await get_puuid(self.session, cont_region, name, tag)
        if not puuid: return await interaction.followup.send(f"找不到玩家。")

        url = f"https://{region}.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/{puuid}"
        data = await riot_request(self.session, url)
        if not data:
            return await interaction.followup.send(f"`{name}#{tag}` 当前不在对局中。")

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


async def setup(bot):
    await bot.add_cog(GMPT(bot))
