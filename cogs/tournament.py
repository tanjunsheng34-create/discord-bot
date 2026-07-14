"""
GMPT Bot — Tournament System (Swiss / Elimination)
Create, signup, bracket, standings, report, economy rewards.
"""
import os
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
from cogs.economy import add_coins
from cogs.lol import get_puuid, riot_request, REGIONS, tier_emoji
import aiohttp
from datetime import datetime

RIOT_KEY = os.getenv("RIOT_API_KEY", "")

# ---------- tier → seed 映射 ----------
TIER_SEED = {"CHALLENGER": 1, "GRANDMASTER": 2, "MASTER": 3,
             "DIAMOND": 4, "EMERALD": 5, "PLATINUM": 6,
             "GOLD": 7, "SILVER": 8, "BRONZE": 9, "IRON": 10}

# ---------- Swiss 配对算法 ----------
def swiss_pairing(players, tournament_id):
    """
    players: list of dicts {discord_id, points, seed}
    existing_matchups: set of frozenset(player_id pairs)
    Returns (matches, bye_player) where matches = [(id_a, id_b), ...], bye_player = discord_id or None
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT player_a_id, player_b_id FROM tournament_matches WHERE tournament_id=?",
        (tournament_id,),
    )
    existing = set()
    for r in cur.fetchall():
        pair = frozenset([r["player_a_id"], r["player_b_id"]]) if r["player_b_id"] else None
        if pair:
            existing.add(pair)
    conn.close()

    # 按积分降序 -> seed 升序排序
    players.sort(key=lambda p: (-p["points"], p["seed"]))

    if len(players) == 0:
        return [], None

    bye_player = None
    if len(players) % 2 == 1:
        bye_player = players[-1]["discord_id"]
        players = players[:-1]

    matches = []
    used = set()

    for i in range(0, len(players), 2):
        a = players[i]
        b = players[i + 1]
        pair_key = frozenset([a["discord_id"], b["discord_id"]])

        if pair_key in existing:
            swapped = False
            for j in range(i + 2, len(players)):
                if players[j]["discord_id"] in used:
                    continue
                alt_key = frozenset([a["discord_id"], players[j]["discord_id"]])
                if alt_key not in existing:
                    players[i + 1], players[j] = players[j], players[i + 1]
                    swapped = True
                    break
            # fallback: allow rematch

        used.add(a["discord_id"])
        used.add(players[i + 1]["discord_id"])
        matches.append((a["discord_id"], players[i + 1]["discord_id"]))

    return matches, bye_player


# ---------- 辅助函数 ----------
def get_tournament_or_none(cur, tid):
    cur.execute("SELECT * FROM tournaments WHERE id=?", (tid,))
    return cur.fetchone()


async def fetch_player_tier(session, uid):
    """根据 player_riot 表查询玩家 Riot 段位，返回 (tier_str, None) 或 (None, error)"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT summoner_name, tag_line, region FROM player_riot WHERE discord_id=?", (uid,))
    riot = cur.fetchone()
    conn.close()

    if not riot:
        return (None, "未关联")

    if not RIOT_KEY:
        return (None, "API Key 未配置")

    cont_region = REGIONS[riot["region"]][1]
    puuid, err = await get_puuid(session, cont_region, riot["summoner_name"], riot["tag_line"])
    if err:
        return (None, err[:50])

    url = f"https://{riot['region']}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
    code, summ = await riot_request(session, url)
    if code != 200:
        return (None, "获取召唤师失败")

    url2 = f"https://{riot['region']}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summ['id']}"
    _, leagues = await riot_request(session, url2)
    leagues = leagues or []

    solo = next((l for l in leagues if l["queueType"] == "RANKED_SOLO_5x5"), None)
    if solo:
        return (f"{solo['tier']} {solo['rank']}", solo["tier"])
    flex = next((l for l in leagues if l["queueType"] == "RANKED_FLEX_SR"), None)
    if flex:
        return (f"{flex['tier']} {flex['rank']} (Flex)", flex["tier"])
    return ("Unranked", "UNRANKED")


def tier_sort_key(tier_name):
    """将 tier 名转为排序键"""
    order = {"CHALLENGER": 0, "GRANDMASTER": 1, "MASTER": 2,
             "DIAMOND": 3, "EMERALD": 4, "PLATINUM": 5,
             "GOLD": 6, "SILVER": 7, "BRONZE": 8, "IRON": 9, "UNRANKED": 10}
    return order.get(tier_name.upper() if tier_name else "UNRANKED", 10)


# ---------- Cog ----------
class Tournament(commands.Cog):
    """锦标赛 Tournament System"""

    def __init__(self, bot):
        self.bot = bot
        self.session = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    # ========== 创建锦标赛 ==========
    @app_commands.command(
        name="gmpt-tournament",
        description="Tournament commands / 锦标赛命令",
    )
    @app_commands.describe(
        action="Action / 操作",
        tournament_name="Tournament name / 赛事名称",
        tournament_format="Format / 赛制",
        rounds="Number of Swiss rounds / Swiss 轮数",
        max_players="Max players / 最大人数",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Create / 创建", value="create"),
        app_commands.Choice(name="Signup / 报名", value="signup"),
        app_commands.Choice(name="Players / 报名列表", value="players"),
        app_commands.Choice(name="Start / 开始", value="start"),
        app_commands.Choice(name="Bracket / 对阵图", value="bracket"),
        app_commands.Choice(name="Standings / 排名", value="standings"),
        app_commands.Choice(name="Report / 上报比分", value="report"),
        app_commands.Choice(name="List / 赛事列表", value="list"),
    ])
    @app_commands.choices(tournament_format=[
        app_commands.Choice(name="Swiss (瑞士轮)", value="swiss"),
        app_commands.Choice(name="Elimination (淘汰赛)", value="elimination"),
    ])
    async def tournament_cmd(
        self, interaction: discord.Interaction,
        action: str,
        tournament_name: str = None,
        tournament_format: str = "swiss",
        rounds: int = 3,
        max_players: int = 32,
        tournament_id: int = None,
        match_id: int = None,
        score_a: int = 0,
        score_b: int = 0,
    ):
        if action == "create":
            await self._create(interaction, tournament_name, tournament_format, rounds, max_players)
        elif action == "signup":
            await self._signup(interaction, tournament_id)
        elif action == "players":
            await self._players(interaction, tournament_id)
        elif action == "start":
            await self._start(interaction, tournament_id)
        elif action == "bracket":
            await self._bracket(interaction, tournament_id)
        elif action == "standings":
            await self._standings(interaction, tournament_id)
        elif action == "report":
            await self._report(interaction, tournament_id, match_id, score_a, score_b)
        elif action == "list":
            await self._list(interaction)

    # ---------- create ----------
    async def _create(self, interaction, tournament_name, tournament_format, rounds, max_players):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "仅管理员可创建锦标赛。", ephemeral=True
            )
        if not tournament_name:
            return await interaction.response.send_message("请提供赛事名称。", ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO tournaments (name, format, max_players, rounds, status, created_by) "
            "VALUES (?,?,?,?,'signup',?)",
            (tournament_name, tournament_format, max_players, rounds, str(interaction.user.id)),
        )
        conn.commit(); tid = cur.lastrowid; conn.close()

        embed = discord.Embed(
            title=f"Tournament: {tournament_name}",
            description=(
                f"Format: **{tournament_format.upper()}** | Rounds: **{rounds}** | Max: **{max_players}**\n"
                f"Status: **Signup**\n\n"
                f"报名: `/gmpt-tournament signup tournament_id:{tid}`"
            ),
            color=discord.Color.gold(),
        ).set_footer(text=f"Tournament ID: {tid}")
        await interaction.response.send_message(embed=embed)

    # ---------- signup ----------
    async def _signup(self, interaction, tournament_id):
        await interaction.response.defer(ephemeral=False)

        conn = get_db(); cur = conn.cursor()

        if tournament_id is None:
            # 自动选当前可报名的赛事
            cur.execute(
                "SELECT id, name, max_players FROM tournaments WHERE status='signup' ORDER BY id DESC LIMIT 1"
            )
            t = cur.fetchone()
            if not t:
                conn.close()
                return await interaction.followup.send("当前没有可报名的锦标赛。")
            tournament_id = t["id"]
        else:
            t = get_tournament_or_none(cur, tournament_id)

        if not t:
            conn.close()
            return await interaction.followup.send("锦标赛不存在。")
        if t["status"] != "signup":
            conn.close()
            return await interaction.followup.send("该锦标赛报名已关闭。")

        uid = str(interaction.user.id)

        # 检查段位限制
        tier_restriction = t["tier_restriction"]
        if tier_restriction:
            allowed = set(x.strip().upper() for x in tier_restriction.split(","))
            _, tier_name = await fetch_player_tier(self.session, uid)
            if tier_name and tier_name.upper() not in allowed:
                conn.close()
                return await interaction.followup.send(
                    f"你的段位 **{tier_name}** 不符合本赛事要求（限 {', '.join(sorted(allowed))}）。"
                )

        # 检查是否已报名
        cur.execute(
            "SELECT id FROM tournament_players WHERE tournament_id=? AND discord_id=?",
            (tournament_id, uid),
        )
        if cur.fetchone():
            conn.close()
            return await interaction.followup.send("你已经报名了这个锦标赛。")

        # 检查名额
        max_p = t["max_players"] or 32
        cur.execute("SELECT COUNT(*) as cnt FROM tournament_players WHERE tournament_id=?", (tournament_id,))
        cnt = cur.fetchone()["cnt"]
        if cnt >= max_p:
            conn.close()
            return await interaction.followup.send(f"报名已满（{max_p}人）。")

        # 获取段位并计算 seed
        tier_display, tier_key = await fetch_player_tier(self.session, uid)
        if tier_display is None:
            tier_display = "未关联"
            tier_key = "UNRANKED"

        seed_val = TIER_SEED.get(tier_key.upper() if tier_key else "UNRANKED", 10)

        # 同一 tier 内按报名顺序递增 seed（微调避免 seed 完全相同）
        cur.execute(
            "SELECT MAX(seed) as max_seed FROM tournament_players WHERE tournament_id=? AND tier=?",
            (tournament_id, tier_key.upper()),
        )
        row = cur.fetchone()
        if row and row["max_seed"] is not None:
            seed_val = row["max_seed"] + 1

        cur.execute(
            "INSERT INTO tournament_players (tournament_id, discord_id, seed, tier) VALUES (?,?,?,?)",
            (tournament_id, uid, seed_val, tier_key.upper() if tier_key else "UNRANKED"),
        )
        cur.execute(
            "INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)",
            (uid, interaction.user.name),
        )
        conn.commit(); conn.close()

        await interaction.followup.send(
            f"{interaction.user.mention} 报名成功！\n"
            f"锦标赛: **{t['name']}** | 段位: **{tier_display}** | ({cnt+1}/{max_p})"
        )

    # ---------- players ----------
    async def _players(self, interaction, tournament_id):
        conn = get_db(); cur = conn.cursor()

        if tournament_id is None:
            cur.execute("SELECT id FROM tournaments WHERE status='signup' ORDER BY id DESC LIMIT 1")
            t = cur.fetchone()
            if not t:
                conn.close()
                return await interaction.response.send_message("当前没有可报名的锦标赛。")
            tournament_id = t["id"]
        else:
            t = get_tournament_or_none(cur, tournament_id)
            if not t:
                conn.close()
                return await interaction.response.send_message("锦标赛不存在。")

        cur.execute(
            "SELECT tp.discord_id, tp.seed, tp.tier, tp.wins, tp.losses, tp.points, u.username "
            "FROM tournament_players tp "
            "LEFT JOIN users u ON u.discord_id = tp.discord_id "
            "WHERE tp.tournament_id=? "
            "ORDER BY tp.seed ASC",
            (tournament_id,),
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return await interaction.response.send_message("暂无玩家报名。")

        lines = [f"**报名玩家 ({len(rows)}人)**\n"]
        for i, r in enumerate(rows, 1):
            name = r["username"] if r["username"] else r["discord_id"]
            tier_str = f" `{r['tier']}`" if r["tier"] else ""
            lines.append(f"`#{i}` **{name}** — Seed: {r['seed']}{tier_str}")

        await interaction.response.send_message("\n".join(lines))

    # ---------- start ----------
    async def _start(self, interaction, tournament_id):
        if tournament_id is None:
            return await interaction.response.send_message("请提供 tournament_id。", ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        t = get_tournament_or_none(cur, tournament_id)
        if not t:
            conn.close()
            return await interaction.response.send_message("锦标赛不存在。", ephemeral=True)

        is_admin = interaction.user.guild_permissions.administrator
        is_creator = str(interaction.user.id) == t["created_by"]
        if not is_admin and not is_creator:
            conn.close()
            return await interaction.response.send_message("仅管理员或赛事创建者可开始比赛。", ephemeral=True)

        if t["status"] != "signup":
            conn.close()
            return await interaction.response.send_message("锦标赛状态不允许开始。", ephemeral=True)

        # 获取所有报名玩家，按 seed 排序
        cur.execute(
            "SELECT discord_id, seed, points FROM tournament_players WHERE tournament_id=? ORDER BY seed ASC",
            (tournament_id,),
        )
        players = [dict(r) for r in cur.fetchall()]
        if len(players) < 2:
            conn.close()
            return await interaction.response.send_message("至少需要 2 名玩家。", ephemeral=True)

        # 生成 Round 1 对阵（按 seed 1vs2, 3vs4...）
        matches, bye = swiss_pairing(players, tournament_id)

        for i, (a_id, b_id) in enumerate(matches):
            cur.execute(
                "INSERT INTO tournament_matches (tournament_id, round, match_index, player_a_id, player_b_id, status) "
                "VALUES (?,1,?,?,?,'pending')",
                (tournament_id, i + 1, a_id, b_id),
            )

        if bye:
            cur.execute(
                "INSERT INTO tournament_matches (tournament_id, round, match_index, player_a_id, status) "
                "VALUES (?,1,?,?,'bye')",
                (tournament_id, len(matches) + 1, bye),
            )
            # BYE 自动计分
            cur.execute(
                "UPDATE tournament_players SET points=points+3, wins=wins+1 WHERE tournament_id=? AND discord_id=?",
                (tournament_id, bye),
            )

        cur.execute("UPDATE tournaments SET status='active' WHERE id=?", (tournament_id,))
        conn.commit()

        # 生成 Embed 展示
        embed = discord.Embed(
            title=f"Round 1 — {t['name']}",
            description="Swiss 锦标赛已开始！",
            color=discord.Color.blue(),
        )

        match_lines = []
        cur.execute(
            "SELECT id, player_a_id, player_b_id, status FROM tournament_matches "
            "WHERE tournament_id=? AND round=1 ORDER BY match_index",
            (tournament_id,),
        )
        for m in cur.fetchall():
            a_name = self._get_display_name(interaction, m["player_a_id"])
            if m["player_b_id"]:
                b_name = self._get_display_name(interaction, m["player_b_id"])
                match_lines.append(
                    f"`#{m['id']}` {a_name} vs {b_name} — {m['status']}"
                )
            else:
                match_lines.append(
                    f"`#{m['id']}` {a_name} — **BYE** (自动获胜)"
                )

        embed.add_field(name="对阵表", value="\n".join(match_lines), inline=False)
        embed.set_footer(
            text=f"Tournament ID: {tournament_id} | "
                 f"上报: /gmpt-tournament report tournament_id:{tournament_id} match_id:<id> score_a:<x> score_b:<y>"
        )
        conn.close()
        await interaction.response.send_message(embed=embed)

    # ---------- bracket ----------
    async def _bracket(self, interaction, tournament_id):
        conn = get_db(); cur = conn.cursor()

        if tournament_id is None:
            cur.execute("SELECT id FROM tournaments WHERE status IN ('active','completed') ORDER BY id DESC LIMIT 1")
            t = cur.fetchone()
            if not t:
                conn.close()
                return await interaction.response.send_message("没有进行中的锦标赛。")
            tournament_id = t["id"]
        else:
            t = get_tournament_or_none(cur, tournament_id)
            if not t:
                conn.close()
                return await interaction.response.send_message("锦标赛不存在。")

        max_rounds = t["rounds"] or 3

        cur.execute(
            "SELECT * FROM tournament_matches WHERE tournament_id=? ORDER BY round, match_index",
            (tournament_id,),
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.response.send_message("暂无对阵数据。")

        embed = discord.Embed(
            title=f"Bracket — {t['name']}",
            description=f"Format: {t['format'].upper()} | Status: {t['status']}",
            color=discord.Color.purple(),
        )

        # 按 round 分组
        from collections import defaultdict
        by_round = defaultdict(list)
        for m in matches:
            by_round[m["round"]].append(m)

        for rnd in sorted(by_round.keys()):
            lines = []
            for m in by_round[rnd]:
                a_name = self._get_display_name(interaction, m["player_a_id"])
                if m["player_b_id"]:
                    b_name = self._get_display_name(interaction, m["player_b_id"])
                    if m["status"] == "reported":
                        lines.append(
                            f"`#{m['id']}` **{a_name}** {m['score_a']}-{m['score_b']} {b_name}"
                        )
                    else:
                        lines.append(
                            f"`#{m['id']}` {a_name} vs {b_name} (Pending)"
                        )
                else:
                    lines.append(
                        f"`#{m['id']}` {a_name} — **BYE**"
                    )
            embed.add_field(
                name=f"Round {rnd}",
                value="\n".join(lines) if lines else "(无)",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    # ---------- standings ----------
    async def _standings(self, interaction, tournament_id):
        conn = get_db(); cur = conn.cursor()

        if tournament_id is None:
            cur.execute("SELECT id FROM tournaments WHERE status IN ('active','completed') ORDER BY id DESC LIMIT 1")
            t = cur.fetchone()
            if not t:
                conn.close()
                return await interaction.response.send_message("没有进行中的锦标赛。")
            tournament_id = t["id"]
        else:
            t = get_tournament_or_none(cur, tournament_id)
            if not t:
                conn.close()
                return await interaction.response.send_message("锦标赛不存在。")

        cur.execute(
            "SELECT tp.discord_id, tp.wins, tp.losses, tp.draws, tp.points, tp.tier, u.username "
            "FROM tournament_players tp "
            "LEFT JOIN users u ON u.discord_id = tp.discord_id "
            "WHERE tp.tournament_id=? "
            "ORDER BY tp.points DESC, tp.wins DESC",
            (tournament_id,),
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return await interaction.response.send_message("暂无玩家数据。")

        embed = discord.Embed(
            title=f"Standings — {t['name']}",
            color=discord.Color.gold(),
        )

        lines = ["` #  玩家                W-L   积分`"]
        for i, r in enumerate(rows, 1):
            name = (r["username"] if r["username"] else r["discord_id"])[:16]
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f" #{i}"
            lines.append(
                f"{medal} `{name:<16} {r['wins']}-{r['losses']}  {r['points']:>4}`"
            )

        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    # ---------- report ----------
    async def _report(self, interaction, tournament_id, match_id, score_a, score_b):
        if not tournament_id or not match_id:
            return await interaction.response.send_message(
                "用法: `/gmpt-tournament report tournament_id:<id> match_id:<id> score_a:<x> score_b:<y>`",
                ephemeral=True,
            )

        conn = get_db(); cur = conn.cursor()
        t = get_tournament_or_none(cur, tournament_id)
        if not t:
            conn.close()
            return await interaction.response.send_message("锦标赛不存在。", ephemeral=True)
        if t["status"] != "active":
            conn.close()
            return await interaction.response.send_message("锦标赛不在进行中。", ephemeral=True)

        cur.execute("SELECT * FROM tournament_matches WHERE id=? AND tournament_id=?", (match_id, tournament_id))
        m = cur.fetchone()
        if not m:
            conn.close()
            return await interaction.response.send_message("比赛不存在。", ephemeral=True)
        if m["status"] == "reported":
            conn.close()
            return await interaction.response.send_message("该比赛已上报。", ephemeral=True)
        if m["status"] == "bye":
            conn.close()
            return await interaction.response.send_message("BYE 无需上报。", ephemeral=True)

        uid = str(interaction.user.id)
        is_participant = uid in (m["player_a_id"], (m["player_b_id"] or ""))
        is_admin = interaction.user.guild_permissions.administrator

        if not is_participant and not is_admin:
            conn.close()
            return await interaction.response.send_message("仅比赛双方或管理员可上报比分。", ephemeral=True)

        # 判定胜者
        winner_id = m["player_a_id"] if score_a > score_b else m["player_b_id"]
        loser_id = m["player_b_id"] if score_a > score_b else m["player_a_id"]

        # 更新 match
        cur.execute(
            "UPDATE tournament_matches SET score_a=?, score_b=?, winner_id=?, status='reported', "
            "reported_by=?, reported_at=? WHERE id=?",
            (score_a, score_b, winner_id, uid, datetime.now().isoformat(), match_id),
        )

        # 更新玩家战绩
        cur.execute(
            "UPDATE tournament_players SET wins=wins+1, points=points+3 WHERE tournament_id=? AND discord_id=?",
            (tournament_id, winner_id),
        )
        cur.execute(
            "UPDATE tournament_players SET losses=losses+1 WHERE tournament_id=? AND discord_id=?",
            (tournament_id, loser_id),
        )
        # 败方也有参与分
        cur.execute(
            "UPDATE tournament_players SET points=points+0 WHERE tournament_id=? AND discord_id=?",
            (tournament_id, loser_id),
        )

        # 经济奖励
        add_coins(winner_id, 150, f"Tournament win / 锦标赛胜利 (Match #{match_id})")
        add_coins(loser_id, 50, f"Tournament loss / 锦标赛失利 (Match #{match_id})")

        conn.commit()

        # 检查当前轮是否全部完成
        cur_round = m["round"]
        max_rounds = t["rounds"] or 3

        cur.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status='reported' OR status='bye' THEN 1 ELSE 0 END) as done "
            "FROM tournament_matches WHERE tournament_id=? AND round=?",
            (tournament_id, cur_round),
        )
        stats = cur.fetchone()

        round_done = (stats["total"] == stats["done"])

        embed = discord.Embed(
            title=f"Match #{match_id} Reported",
            description=(
                f"**{self._get_display_name(interaction, winner_id)}** wins!\n"
                f"Score: **{score_a} - {score_b}**\n"
                f"Winner +150 coins | Loser +50 coins"
            ),
            color=discord.Color.green(),
        )

        if round_done:
            if cur_round >= max_rounds:
                # 锦标赛结束
                cur.execute("UPDATE tournaments SET status='completed' WHERE id=?", (tournament_id,))

                # 冠军 + 亚军奖励
                cur.execute(
                    "SELECT discord_id FROM tournament_players WHERE tournament_id=? ORDER BY points DESC, wins DESC LIMIT 2",
                    (tournament_id,),
                )
                top2 = [r["discord_id"] for r in cur.fetchall()]
                if len(top2) >= 1:
                    add_coins(top2[0], 1000, "Tournament Champion / 锦标赛冠军")
                if len(top2) >= 2:
                    add_coins(top2[1], 500, "Tournament Runner-up / 锦标赛亚军")

                conn.commit()

                # 最终排名
                cur.execute(
                    "SELECT tp.discord_id, tp.wins, tp.losses, tp.points, u.username "
                    "FROM tournament_players tp "
                    "LEFT JOIN users u ON u.discord_id = tp.discord_id "
                    "WHERE tp.tournament_id=? "
                    "ORDER BY tp.points DESC, tp.wins DESC",
                    (tournament_id,),
                )
                final_rows = cur.fetchall()

                embed.add_field(
                    name="Tournament Complete!",
                    value="所有轮次已完成。最终排名如下：",
                    inline=False,
                )
                rank_lines = []
                for i, r in enumerate(final_rows, 1):
                    name = (r["username"] if r["username"] else r["discord_id"])[:14]
                    medal = "👑" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                    bonus = ""
                    if i == 1:
                        bonus = " +1000 coins"
                    elif i == 2:
                        bonus = " +500 coins"
                    rank_lines.append(
                        f"{medal} **{name}** — {r['wins']}W-{r['losses']}L — {r['points']}pts{bonus}"
                    )
                embed.add_field(name="Final Standings", value="\n".join(rank_lines), inline=False)
            else:
                # 生成下一轮 Swiss 对阵
                cur.execute(
                    "SELECT discord_id, seed, points FROM tournament_players WHERE tournament_id=? ORDER BY points DESC, seed ASC",
                    (tournament_id,),
                )
                players = [dict(r) for r in cur.fetchall()]
                new_matches, new_bye = swiss_pairing(players, tournament_id)

                next_round = cur_round + 1
                for i, (a_id, b_id) in enumerate(new_matches):
                    cur.execute(
                        "INSERT INTO tournament_matches (tournament_id, round, match_index, player_a_id, player_b_id, status) "
                        "VALUES (?,?,?,?,?,'pending')",
                        (tournament_id, next_round, i + 1, a_id, b_id),
                    )
                if new_bye:
                    cur.execute(
                        "INSERT INTO tournament_matches (tournament_id, round, match_index, player_a_id, status) "
                        "VALUES (?,?,?,?,'bye')",
                        (tournament_id, next_round, len(new_matches) + 1, new_bye),
                    )
                    cur.execute(
                        "UPDATE tournament_players SET points=points+3, wins=wins+1 WHERE tournament_id=? AND discord_id=?",
                        (tournament_id, new_bye),
                    )

                conn.commit()

                embed.add_field(
                    name=f"Round {next_round} Generated!",
                    value=f"Round {cur_round} 全部完成。新一轮对阵已自动生成。",
                    inline=False,
                )

                cur.execute(
                    "SELECT id, player_a_id, player_b_id, status FROM tournament_matches "
                    "WHERE tournament_id=? AND round=? ORDER BY match_index",
                    (tournament_id, next_round),
                )
                match_lines = []
                for nm in cur.fetchall():
                    a_name = self._get_display_name(interaction, nm["player_a_id"])
                    if nm["player_b_id"]:
                        b_name = self._get_display_name(interaction, nm["player_b_id"])
                        match_lines.append(f"`#{nm['id']}` {a_name} vs {b_name}")
                    else:
                        match_lines.append(f"`#{nm['id']}` {a_name} — **BYE**")
                embed.add_field(name=f"Round {next_round} 对阵", value="\n".join(match_lines), inline=False)

        conn.close()
        await interaction.response.send_message(embed=embed)

    # ---------- list ----------
    async def _list(self, interaction):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT t.id, t.name, t.format, t.status, t.max_players, t.rounds, "
            "COALESCE(p.cnt,0) as player_count "
            "FROM tournaments t "
            "LEFT JOIN (SELECT tournament_id, COUNT(*) as cnt FROM tournament_players GROUP BY tournament_id) p "
            "ON p.tournament_id = t.id "
            "ORDER BY t.id DESC LIMIT 10"
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return await interaction.response.send_message("暂无锦标赛记录。")

        lines = ["**Tournament List / 锦标赛列表**\n"]
        status_map = {"signup": "📝报名中", "active": "🟢进行中", "completed": "✅已结束"}
        for r in rows:
            st = status_map.get(r["status"], r["status"])
            lines.append(
                f"`#{r['id']}` **{r['name']}** | {r['format'].upper()} | {st} | "
                f"{r['player_count']}/{r['max_players']} players | {r['rounds']} rounds"
            )

        await interaction.response.send_message("\n".join(lines))

    # ---------- 辅助 ----------
    def _get_display_name(self, interaction, discord_id):
        if not interaction.guild:
            return f"<@{discord_id}>"
        member = interaction.guild.get_member(int(discord_id))
        return member.display_name if member else f"<@{discord_id}>"


async def setup(bot):
    await bot.add_cog(Tournament(bot))
