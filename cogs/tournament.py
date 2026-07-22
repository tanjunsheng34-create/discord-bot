"""
GMPT Bot — Tournament System (Swiss / Elimination / Captain Draft)
"""
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
from config import RIOT_API_KEY
from cogs.economy import add_coins
from cogs.shared_views import ConfirmView
import aiohttp
from datetime import datetime
from collections import defaultdict

import logging
from utils.logger import log_error
logger = logging.getLogger(__name__)


# ---------- tier → seed 映射 ----------
TIER_SEED = {"CHALLENGER": 1, "GRANDMASTER": 2, "MASTER": 3,
             "DIAMOND": 4, "EMERALD": 5, "PLATINUM": 6,
             "GOLD": 7, "SILVER": 8, "BRONZE": 9, "IRON": 10}

# ---------- tier → 分数 (Captain Draft) ----------
TIER_SCORE = {
    "CHALLENGER": 5, "GRANDMASTER": 5, "MASTER": 5,
    "DIAMOND": 4, "EMERALD": 3, "PLATINUM": 3,
    "GOLD": 2, "SILVER": 1, "BRONZE": 1, "IRON": 1, "UNRANKED": 1,
}

# ---------- Swiss 配对算法 ----------
def swiss_pairing(players, tournament_id):
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

        used.add(a["discord_id"])
        used.add(players[i + 1]["discord_id"])
        matches.append((a["discord_id"], players[i + 1]["discord_id"]))

    return matches, bye_player


# ---------- 辅助函数 ----------
def get_tournament_or_none(cur, tid):
    cur.execute("SELECT * FROM tournaments WHERE id=?", (tid,))
    return cur.fetchone()


async def fetch_player_tier(session, uid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT summoner_name, tag_line, region FROM player_riot WHERE discord_id=?", (uid,))
    riot = cur.fetchone()
    conn.close()

    if not riot:
        return (None, "未关联", None)

    if not RIOT_API_KEY:
        return (None, "API Key 未配置", None)

    cont_region = {"kr": "asia", "jp": "asia", "na": "americas", "euw": "europe",
                   "eune": "europe", "oce": "americas", "br": "americas",
                   "lan": "americas", "las": "americas", "tr": "europe", "ru": "europe"}.get(
        riot["region"], "asia")
    from cogs.lol import get_puuid, riot_request

    puuid, err = await get_puuid(session, cont_region, riot["summoner_name"], riot["tag_line"])
    if err:
        return (None, err[:50], None)

    url = f"https://{riot['region']}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
    code, summ = await riot_request(session, url)
    if code != 200:
        return (None, "获取召唤师失败", None)

    url2 = f"https://{riot['region']}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summ['id']}"
    _, leagues = await riot_request(session, url2)
    leagues = leagues or []

    solo = next((l for l in leagues if l["queueType"] == "RANKED_SOLO_5x5"), None)
    if solo:
        return (f"{solo['tier']} {solo['rank']}", solo["tier"], TIER_SCORE.get(solo["tier"].upper(), 1))
    flex = next((l for l in leagues if l["queueType"] == "RANKED_FLEX_SR"), None)
    if flex:
        return (f"{flex['tier']} {flex['rank']} (Flex)", flex["tier"], TIER_SCORE.get(flex["tier"].upper(), 1))
    return ("Unranked", "UNRANKED", 1)


def tier_sort_key(tier_name):
    order = {"CHALLENGER": 0, "GRANDMASTER": 1, "MASTER": 2,
             "DIAMOND": 3, "EMERALD": 4, "PLATINUM": 5,
             "GOLD": 6, "SILVER": 7, "BRONZE": 8, "IRON": 9, "UNRANKED": 10}
    return order.get(tier_name.upper() if tier_name else "UNRANKED", 10)


def _display_name(guild, discord_id):
    if not guild:
        return f"<@{discord_id}>"
    member = guild.get_member(int(discord_id))
    return member.display_name if member else f"<@{discord_id}>"


# =============================================================================
# DraftView — 队长选秀交互界面
# =============================================================================
class DraftView(discord.ui.View):
    def __init__(self, draft_id, captains_info, available_players, guild, timeout=600):
        super().__init__(timeout=None)
        self.draft_id = draft_id
        self.captains = captains_info  # list of {captain_id, team_name, pick_order, tier_score}
        self.available_players = available_players  # list of (discord_id, tier_score, display_name, tier_str)
        self.guild = guild
        self.drafted_players = []  # (captain_id, player_id)
        self.current_pick = 0
        self.snake_round = 1
        self.snake_direction = 1  # 1 = forward, -1 = backward
        self._pending_pick = None

        # Sort captains by pick_order
        self.captains.sort(key=lambda c: c["pick_order"])
        self._rebuild_select()

    @property
    def current_captain(self):
        if not self.captains:
            return None
        idx = self.current_pick % len(self.captains)
        return self.captains[idx]

    def _get_unassigned(self):
        drafted_ids = {p[1] for p in self.drafted_players}
        return [p for p in self.available_players if p[0] not in drafted_ids]

    def _get_team_players(self, captain_id):
        return [p[1] for p in self.drafted_players if p[0] == captain_id]

    def _get_team_score(self, captain_id):
        cap = next((c for c in self.captains if c["captain_id"] == captain_id), None)
        cap_score = cap["tier_score"] if cap else 0
        team_picks = self._get_team_players(captain_id)
        pick_score = 0
        for pid in team_picks:
            player_info = next((p for p in self.available_players if p[0] == pid), None)
            if player_info:
                pick_score += player_info[1]
        return cap_score + pick_score

    def _rebuild_select(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)

        unassigned = self._get_unassigned()
        options = []
        for pid, score, name, tier_str in unassigned:
            desc = f"Score: {score} | {tier_str}"
            options.append(discord.SelectOption(
                label=name[:25], value=pid,
                description=desc[:50],
            ))

        if not options:
            options.append(discord.SelectOption(
                label="(无待选玩家 / No players left)",
                value="__none__", default=False
            ))

        select = discord.ui.Select(
            placeholder="选择玩家 / Pick a player...",
            options=options[:25],
            custom_id="draft_select",
            row=0,
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        cap = self.current_captain
        if not cap:
            return await interaction.response.send_message("Draft error.", ephemeral=True)
        if str(interaction.user.id) != cap["captain_id"]:
            return await interaction.response.send_message(
                f"现在轮到 **{_display_name(self.guild, cap['captain_id'])}** 选人 / Not your turn!",
                ephemeral=True,
            )

        val = interaction.data["values"][0]
        if val == "__none__":
            return await interaction.response.defer()

        self._pending_pick = val
        player_info = next((p for p in self.available_players if p[0] == val), None)
        pname = player_info[2] if player_info else val
        await interaction.response.send_message(
            f"已选择: **{pname}**，点击下方按钮确认挑入你的队伍 / "
            f"Selected: **{pname}**, click button to confirm.",
            ephemeral=True,
        )

    @discord.ui.button(label="确认选入 / Confirm Pick", style=discord.ButtonStyle.success,
                       emoji="✅", row=1, custom_id="draft_confirm")
    async def confirm_pick(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        cap = self.current_captain
        if not cap:
            return await interaction.followup.send("Draft error.", ephemeral=True)
        if str(interaction.user.id) != cap["captain_id"]:
            return await interaction.followup.send(
                f"现在轮到 **{_display_name(self.guild, cap['captain_id'])}** 选人 / Not your turn!",
                ephemeral=True,
            )

        if not self._pending_pick:
            return await interaction.followup.send(
                "请先从下拉菜单选择一个玩家 / Pick a player first.",
                ephemeral=True,
            )

        # Check if already drafted
        if self._pending_pick in [p[1] for p in self.drafted_players]:
            self._pending_pick = None
            return await interaction.followup.send("该玩家已被选走。", ephemeral=True)

        # Save to DB
        conn = get_db(); cur = conn.cursor()
        pick_num = len(self.drafted_players) + 1
        cur.execute(
            "INSERT INTO draft_picks (draft_id, captain_id, player_id, pick_number) VALUES (?,?,?,?)",
            (self.draft_id, cap["captain_id"], self._pending_pick, pick_num),
        )
        conn.commit(); conn.close()

        self.drafted_players.append((cap["captain_id"], self._pending_pick))
        self._pending_pick = None

        # Advance pick
        self.current_pick += 1
        if self.current_pick > 0 and self.current_pick % len(self.captains) == 0:
            self.snake_round += 1
            self.snake_direction *= -1

        # Check if draft complete
        unassigned = self._get_unassigned()
        if not unassigned or len(unassigned) == 0:
            for child in self.children:
                child.disabled = True

        self._rebuild_select()
        embed = self.build_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="跳过 / Skip Turn", style=discord.ButtonStyle.secondary,
                       emoji="⏭️", row=1, custom_id="draft_skip")
    async def skip_turn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        cap = self.current_captain
        if not cap:
            return await interaction.followup.send("Draft error.", ephemeral=True)
        if str(interaction.user.id) != cap["captain_id"]:
            return await interaction.followup.send(
                f"现在轮到 **{_display_name(self.guild, cap['captain_id'])}** 选人 / Not your turn!",
                ephemeral=True,
            )

        # Find any unassigned player and auto-pick the first one
        unassigned = self._get_unassigned()
        if not unassigned:
            return await interaction.followup.send("没有可选的玩家了 / No players left.", ephemeral=True)

        auto_pick = unassigned[0]  # auto-pick first available

        conn = get_db(); cur = conn.cursor()
        pick_num = len(self.drafted_players) + 1
        cur.execute(
            "INSERT INTO draft_picks (draft_id, captain_id, player_id, pick_number) VALUES (?,?,?,?)",
            (self.draft_id, cap["captain_id"], auto_pick[0], pick_num),
        )
        conn.commit(); conn.close()

        self.drafted_players.append((cap["captain_id"], auto_pick[0]))
        self._pending_pick = None

        self.current_pick += 1
        if self.current_pick > 0 and self.current_pick % len(self.captains) == 0:
            self.snake_round += 1
            self.snake_direction *= -1

        unassigned = self._get_unassigned()
        if not unassigned or len(unassigned) == 0:
            for child in self.children:
                child.disabled = True

        self._rebuild_select()
        embed = self.build_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="结束选秀 / End Draft", style=discord.ButtonStyle.danger,
                       emoji="🏁", row=2, custom_id="draft_end")
    async def end_draft(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        cap = self.current_captain
        if not cap:
            return await interaction.followup.send("Draft error.", ephemeral=True)
        if str(interaction.user.id) != cap["captain_id"]:
            # Allow any captain to end
            is_any_captain = any(c["captain_id"] == str(interaction.user.id) for c in self.captains)
            if not is_any_captain:
                return await interaction.followup.send(
                    "Only captains can end the draft. / 仅队长可结束选秀。",
                    ephemeral=True,
                )

        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE draft_sessions SET status='completed' WHERE id=?", (self.draft_id,))
        conn.commit(); conn.close()

        for child in self.children:
            child.disabled = True
        self._rebuild_select()
        embed = self.build_embed()
        embed.title = f"Draft Complete — {embed.title.replace('Draft — ', '')}"
        embed.description = "✅ 队长选秀已完成！ / Captain Draft completed!"
        embed.color = discord.Color.gold()
        await interaction.edit_original_response(embed=embed, view=self)

    def build_embed(self):
        embed = discord.Embed(
            title=f"Draft — Round {self.snake_round}",
            description=f"Pick #{self.current_pick + 1} — 轮到: **{_display_name(self.guild, self.current_captain['captain_id']) if self.current_captain else 'N/A'}**",
            color=discord.Color.blue(),
        )

        # Team rosters
        for cap in self.captains:
            team = self._get_team_players(cap["captain_id"])
            total_score = self._get_team_score(cap["captain_id"])
            names = [_display_name(self.guild, pid) for pid in team]
            embed.add_field(
                name=f"{cap['team_name']} (总 {total_score} pts)",
                value="\n".join(names) if names else "(暂无队员 / Empty)",
                inline=True,
            )

        # Balance report
        scores = [self._get_team_score(c["captain_id"]) for c in self.captains]
        if len(scores) >= 2:
            balance_lines = []
            for i, cap in enumerate(self.captains):
                balance_lines.append(
                    f"{cap['team_name']}: **{scores[i]}** pts (队长 {cap['tier_score']})"
                )
            diff = max(scores) - min(scores) if scores else 0
            balance_lines.append(f"差距 / Gap: **{diff}** pts")
            embed.add_field(
                name="DRAFT BALANCE REPORT",
                value="\n".join(balance_lines),
                inline=False,
            )

        # Remaining players
        unassigned = self._get_unassigned()
        if unassigned:
            remaining = [f"{p[2]} ({p[3]}, {p[1]}pts)" for p in unassigned]
            if len(remaining) > 10:
                remaining = remaining[:10] + [f"... 还有 {len(unassigned) - 10} 人"]
            embed.add_field(
                name=f"待选池 / Available ({len(unassigned)})",
                value="\n".join(remaining),
                inline=False,
            )

        return embed


# =============================================================================
# CreateTournamentView — 创建赛事后直接附带报名/查看/取消按钮
# =============================================================================


class CreateTournamentView(discord.ui.View):
    def __init__(self, tournament_id, tournament_name, tournament_format,
                 rounds, max_players, created_by, guild, session, timeout=None):
        super().__init__(timeout=None)
        self.tournament_id = tournament_id
        self.tournament_name = tournament_name
        self.tournament_format = tournament_format
        self.rounds = rounds
        self.max_players = max_players
        self.created_by = created_by
        self.guild = guild
        self.session = session

    # ---------------------------------------------------------------
    # 报名 / Sign Up
    # ---------------------------------------------------------------
    @discord.ui.button(label="报名 Sign Up", style=discord.ButtonStyle.primary, emoji="✍️", row=0)
    async def signup_button(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        t = get_tournament_or_none(cur, self.tournament_id)
        if not t or t["status"] != "signup":
            conn.close()
            return await interaction.followup.send("该锦标赛报名已关闭。", ephemeral=True)

        uid = str(interaction.user.id)

        tier_restriction = t["tier_restriction"]
        if tier_restriction:
            allowed = set(x.strip().upper() for x in tier_restriction.split(","))
            _, tier_name, _ = await fetch_player_tier(self.session, uid)
            if tier_name and tier_name.upper() not in allowed:
                conn.close()
                return await interaction.followup.send(
                    f"你的段位 **{tier_name}** 不符合本赛事要求（限 {', '.join(sorted(allowed))}）。",
                    ephemeral=True,
                )

        cur.execute(
            "SELECT id FROM tournament_players WHERE tournament_id=? AND discord_id=?",
            (self.tournament_id, uid),
        )
        if cur.fetchone():
            conn.close()
            return await interaction.followup.send("你已经报名了这个锦标赛。", ephemeral=True)

        max_p = t["max_players"] or 32
        cur.execute("SELECT COUNT(*) as cnt FROM tournament_players WHERE tournament_id=?",
                     (self.tournament_id,))
        cnt = cur.fetchone()["cnt"]
        if cnt >= max_p:
            conn.close()
            return await interaction.followup.send(f"报名已满（{max_p}人）。", ephemeral=True)

        tier_display, tier_key, _ = await fetch_player_tier(self.session, uid)
        if tier_display is None:
            tier_display = "未关联"
            tier_key = "UNRANKED"

        conn.close()

        conn = get_db(); cur = conn.cursor()
        seed_val = TIER_SEED.get(tier_key.upper() if tier_key else "UNRANKED", 10)
        cur.execute(
            "SELECT MAX(seed) as max_seed FROM tournament_players WHERE tournament_id=? AND tier=?",
            (self.tournament_id, tier_key.upper()),
        )
        row = cur.fetchone()
        if row and row["max_seed"] is not None:
            seed_val = row["max_seed"] + 1

        cur.execute(
            "INSERT INTO tournament_players (tournament_id, discord_id, seed, tier) VALUES (?,?,?,?)",
            (self.tournament_id, uid, seed_val, tier_key.upper() if tier_key else "UNRANKED"),
        )
        cur.execute(
            "INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)",
            (uid, interaction.user.name),
        )
        conn.commit(); conn.close()

        await interaction.followup.send(
            f"✅ {interaction.user.mention} 报名成功！\n"
            f"锦标赛: **{self.tournament_name}** | 段位: **{tier_display}** | ({cnt+1}/{max_p})",
            ephemeral=True,
        )

    # ---------------------------------------------------------------
    # 查看报名列表 / View Signups
    # ---------------------------------------------------------------
    @discord.ui.button(label="查看报名 View Signups", style=discord.ButtonStyle.secondary, row=0)
    async def view_signups(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT tp.discord_id, tp.seed, tp.tier, u.username "
            "FROM tournament_players tp "
            "LEFT JOIN users u ON u.discord_id = tp.discord_id "
            "WHERE tp.tournament_id=? "
            "ORDER BY tp.seed ASC",
            (self.tournament_id,),
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return await interaction.followup.send("暂无玩家报名。", ephemeral=True)

        lines = [f"**{self.tournament_name} 报名列表 ({len(rows)}人)**\n"]
        for i, r in enumerate(rows, 1):
            name = r["username"] if r["username"] else r["discord_id"]
            tier_str = f" `{r['tier']}`" if r["tier"] else ""
            lines.append(f"`#{i}` **{name}** — Seed: {r['seed']}{tier_str}")

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # ---------------------------------------------------------------
    # 取消赛事 (仅管理员/创建者) / Cancel Tournament
    # ---------------------------------------------------------------
    @discord.ui.button(label="取消赛事(管理员) Cancel", style=discord.ButtonStyle.danger, row=0)
    async def cancel_tournament(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        t = get_tournament_or_none(cur, self.tournament_id)
        if not t:
            conn.close()
            return await interaction.followup.send("锦标赛不存在。", ephemeral=True)

        is_admin = interaction.user.guild_permissions.administrator
        is_creator = str(interaction.user.id) == (t["created_by"] or "")
        if not is_admin and not is_creator:
            conn.close()
            return await interaction.followup.send("仅管理员或赛事创建者可取消。", ephemeral=True)

        if t["status"] == "cancelled":
            conn.close()
            return await interaction.followup.send("该赛事已被取消。", ephemeral=True)
        conn.close()

        embed = discord.Embed(
            title="确认取消 / Confirm Cancel",
            description=f"确定要取消锦标赛 **{self.tournament_name}** (`#{self.tournament_id}`) 吗？",
            color=discord.Color.red(),
        )
        confirm_view = ConfirmView(timeout=60)
        await interaction.followup.send(embed=embed, view=confirm_view, ephemeral=True)
        await confirm_view.wait()
        if confirm_view.value is None or not confirm_view.value:
            return

        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE tournaments SET status='cancelled' WHERE id=?", (self.tournament_id,))
        conn.commit(); conn.close()

        await interaction.edit_original_response(
            content=f"锦标赛 **{self.tournament_name}** (`#{self.tournament_id}`) 已取消 / cancelled.",
            embed=None,
            view=None,
        )
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)


# =============================================================================
# ReportView — button-based match score reporting
# =============================================================================


class ReportView(discord.ui.View):
    def __init__(self, tournament_id, user_id, guild, timeout=300):
        super().__init__(timeout=None)
        self.tournament_id = tournament_id
        self.user_id = user_id
        self.guild = guild
        self._pending_match = None
        self._matches = []
        self._build_match_select()

    def _build_match_select(self):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, player_a_id, player_b_id, round, match_index FROM tournament_matches "
            "WHERE tournament_id=? AND status='pending' AND (player_a_id=? OR player_b_id=?) "
            "ORDER BY round, match_index",
            (self.tournament_id, self.user_id, self.user_id),
        )
        self._matches = [dict(r) for r in cur.fetchall()]
        conn.close()

        options = []
        for m in self._matches:
            opp_id = m["player_b_id"] if m["player_a_id"] == self.user_id else m["player_a_id"]
            opp_name = _display_name(self.guild, opp_id) if self.guild else f"<@{opp_id}>"
            label = f"R{m['round']} #{m['match_index']} vs {opp_name}"
            options.append(discord.SelectOption(
                label=label[:100],
                value=str(m["id"]),
                description=f"Round {m['round']} Match {m['match_index']}",
            ))

        if not options:
            options.append(discord.SelectOption(
                label="(无待上报比赛 / No pending matches)",
                value="__none__",
            ))

        select = discord.ui.Select(
            placeholder="选择要上报的比赛 / Select a match...",
            options=options[:25],
            row=0,
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        val = interaction.data["values"][0]
        if val == "__none__":
            return
        self._pending_match = int(val)
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = False
        await interaction.edit_original_response(view=self)

    @discord.ui.button(label="我赢了 / I Won", style=discord.ButtonStyle.success,
                       emoji="🏆", row=1, disabled=True)
    async def i_won(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        await self._do_report(interaction, self.user_id)

    @discord.ui.button(label="对手赢了 / Opponent Won", style=discord.ButtonStyle.danger,
                       emoji="❌", row=1, disabled=True)
    async def opp_won(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if not self._pending_match:
            return await interaction.followup.send("请先选择比赛。", ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT player_a_id, player_b_id FROM tournament_matches WHERE id=?",
                     (self._pending_match,))
        m = cur.fetchone()
        conn.close()
        if not m:
            return await interaction.followup.send("比赛不存在。", ephemeral=True)
        opp_id = m["player_b_id"] if m["player_a_id"] == self.user_id else m["player_a_id"]
        await self._do_report(interaction, opp_id)

    async def _do_report(self, interaction: discord.Interaction, winner_id: str):
        if not self._pending_match:
            return await interaction.response.send_message("请先选择比赛。", ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        m = cur.execute("SELECT * FROM tournament_matches WHERE id=?", (self._pending_match,)).fetchone()
        if not m or m["status"] != "pending":
            conn.close()
            return await interaction.response.send_message("比赛状态已变更，请重试。", ephemeral=True)

        loser_id = m["player_b_id"] if winner_id == m["player_a_id"] else m["player_a_id"]
        score_a = 1 if winner_id == m["player_a_id"] else 0
        score_b = 1 if winner_id == m["player_b_id"] else 0

        from datetime import datetime as dt
        cur.execute(
            "UPDATE tournament_matches SET score_a=?, score_b=?, winner_id=?, status='reported', "
            "reported_by=?, reported_at=? WHERE id=?",
            (score_a, score_b, winner_id, str(interaction.user.id), dt.now().isoformat(), self._pending_match),
        )
        cur.execute(
            "UPDATE tournament_players SET wins=wins+1, points=points+3 WHERE tournament_id=? AND discord_id=?",
            (self.tournament_id, winner_id),
        )
        cur.execute(
            "UPDATE tournament_players SET losses=losses+1 WHERE tournament_id=? AND discord_id=?",
            (self.tournament_id, loser_id),
        )

        from cogs.economy import add_coins
        add_coins(winner_id, 150, f"Tournament win / 锦标赛胜利 (Match #{self._pending_match})")
        add_coins(loser_id, 50, f"Tournament loss / 锦标赛失利 (Match #{self._pending_match})")

        # Advance round if needed
        t = cur.execute("SELECT * FROM tournaments WHERE id=?", (self.tournament_id,)).fetchone()
        cur_round = m["round"]
        max_rounds = (t["rounds"] or 3) if t else 3
        cur.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status IN ('reported','bye') THEN 1 ELSE 0 END) as done "
            "FROM tournament_matches WHERE tournament_id=? AND round=?",
            (self.tournament_id, cur_round),
        )
        stats = cur.fetchone()
        round_done = (stats["total"] == stats["done"])
        next_round_info = ""

        if round_done:
            if cur_round >= max_rounds:
                cur.execute("UPDATE tournaments SET status='completed' WHERE id=?", (self.tournament_id,))
                cur.execute(
                    "SELECT discord_id FROM tournament_players WHERE tournament_id=? ORDER BY points DESC, wins DESC LIMIT 2",
                    (self.tournament_id,),
                )
                top2 = [r["discord_id"] for r in cur.fetchall()]
                if len(top2) >= 1:
                    add_coins(top2[0], 1000, "Tournament Champion / 锦标赛冠军")
                if len(top2) >= 2:
                    add_coins(top2[1], 500, "Tournament Runner-up / 锦标赛亚军")
                conn.commit()
                next_round_info = "\n🏆 **锦标赛已结束！** 最终排名可用 `/gmpt-tournament standings` 查看。"
            else:
                # Generate next round
                cur.execute(
                    "SELECT discord_id, seed, points FROM tournament_players WHERE tournament_id=? ORDER BY points DESC, seed ASC",
                    (self.tournament_id,),
                )
                players = [dict(r) for r in cur.fetchall()]
                new_matches, new_bye = swiss_pairing(players, self.tournament_id)
                next_round = cur_round + 1
                for i, (a_id, b_id) in enumerate(new_matches):
                    cur.execute(
                        "INSERT INTO tournament_matches (tournament_id, round, match_index, player_a_id, player_b_id, status) "
                        "VALUES (?,?,?,?,?,'pending')",
                        (self.tournament_id, next_round, i + 1, a_id, b_id),
                    )
                if new_bye:
                    cur.execute(
                        "INSERT INTO tournament_matches (tournament_id, round, match_index, player_a_id, status) "
                        "VALUES (?,?,?,?,'bye')",
                        (self.tournament_id, next_round, len(new_matches) + 1, new_bye),
                    )
                    cur.execute(
                        "UPDATE tournament_players SET points=points+3, wins=wins+1 WHERE tournament_id=? AND discord_id=?",
                        (self.tournament_id, new_bye),
                    )
                conn.commit()
                next_round_info = f"\n📢 Round {cur_round} 完成！**Round {next_round}** 已自动生成。"

        conn.close()

        winner_name = _display_name(self.guild, winner_id)
        for child in self.children:
            child.disabled = True
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed:
            embed.title = f"✅ Match Reported — {winner_name} wins!"
            embed.color = discord.Color.green()
            if embed.description:
                embed.description += next_round_info
        await interaction.edit_original_response(embed=embed, view=self)


class DraftSetupView(discord.ui.View):
    def __init__(self, tournament_id, available_players, guild, timeout=300):
        super().__init__(timeout=None)
        self.tournament_id = tournament_id
        self.available_players = available_players  # list of (discord_id, display_name, tier_str, tier_score)
        self.guild = guild
        self.captains = {}  # discord_id -> {team_name, pick_order, tier_score}
        self._pending_player = None
        self._rebuild_select()

    def _rebuild_select(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)

        # Only show non-captain players
        uncaptained = [p for p in self.available_players if p[0] not in self.captains]
        options = []
        for pid, name, tier, score in uncaptained:
            options.append(discord.SelectOption(
                label=name[:100],
                value=pid,
                description=f"{tier} | Score: {score}",
            ))

        if not options:
            options.append(discord.SelectOption(
                label="(所有玩家已设为队长)",
                value="__none__",
            ))

        select = discord.ui.Select(
            placeholder="选择玩家设为/移除队长 / Select player...",
            options=options[:25],
            row=0,
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("仅管理员可操作。", ephemeral=True)
        val = interaction.data["values"][0]
        if val == "__none__":
            return await interaction.followup.send("已取消选择。", ephemeral=True)
        self._pending_player = val
        # Enable buttons
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id in ("draft_add_cap", "draft_rm_cap"):
                child.disabled = False
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="设为队长 / Add Captain", style=discord.ButtonStyle.success,
                       row=1, disabled=True, custom_id="draft_add_cap")
    async def add_captain(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("仅管理员可操作。", ephemeral=True)
        if not self._pending_player:
            return await interaction.followup.send("请先从下拉菜单选一个玩家。", ephemeral=True)

        pid = self._pending_player
        if pid in self.captains:
            return await interaction.followup.send("该玩家已是队长。", ephemeral=True)

        player = next((p for p in self.available_players if p[0] == pid), None)
        if not player:
            return await interaction.followup.send("玩家不在列表中。", ephemeral=True)
        _, name, tier, score = player

        self.captains[pid] = {
            "team_name": f"Team {_display_name(self.guild, pid)}",
            "pick_order": len(self.captains) + 1,
            "tier_score": score,
            "display_name": _display_name(self.guild, pid),
        }
        self._pending_player = None
        self._rebuild_select()
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id in ("draft_add_cap", "draft_rm_cap"):
                child.disabled = True
        # Enable start button if >= 2 captains
        for child in self.children:
            if child.custom_id == "draft_start":
                child.disabled = len(self.captains) < 2
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="移除队长 / Remove", style=discord.ButtonStyle.danger,
                       row=1, disabled=True, custom_id="draft_rm_cap")
    async def remove_captain(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("仅管理员可操作。", ephemeral=True)
        if not self._pending_player:
            return await interaction.followup.send("请先从下拉菜单选一个玩家。", ephemeral=True)

        pid = self._pending_player
        if pid not in self.captains:
            return await interaction.followup.send("该玩家不是队长。", ephemeral=True)

        del self.captains[pid]
        # Re-number pick_order
        for i, cid in enumerate(self.captains, 1):
            self.captains[cid]["pick_order"] = i

        self._pending_player = None
        self._rebuild_select()
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id in ("draft_add_cap", "draft_rm_cap"):
                child.disabled = True
            if child.custom_id == "draft_start":
                child.disabled = len(self.captains) < 2
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="确认开始选秀 / Start Draft", style=discord.ButtonStyle.primary,
                       emoji="🚀", row=2, disabled=True, custom_id="draft_start")
    async def start_draft(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("仅管理员可操作。", ephemeral=True)
        if len(self.captains) < 2:
            return await interaction.followup.send("至少需要 2 名队长。", ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO draft_sessions (tournament_id, status, created_by) VALUES (?, 'active', ?)",
            (self.tournament_id, str(interaction.user.id)),
        )
        draft_id = cur.lastrowid

        for pid, cap_info in self.captains.items():
            cur.execute(
                "INSERT INTO draft_captains (draft_id, captain_id, team_name, pick_order, tier_score) VALUES (?,?,?,?,?)",
                (draft_id, pid, cap_info["team_name"], cap_info["pick_order"], cap_info["tier_score"]),
            )

        conn.commit(); conn.close()

        # Prepare available players for DraftView (exclude captains)
        captain_ids = set(self.captains.keys())
        draft_pool = [(p[0], p[3], p[1], p[2]) for p in self.available_players if p[0] not in captain_ids]

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT captain_id, team_name, pick_order, tier_score FROM draft_captains WHERE draft_id=? ORDER BY pick_order", (draft_id,))
        captains_info = [dict(r) for r in cur.fetchall()]
        conn.close()

        view = DraftView(draft_id, captains_info, draft_pool, interaction.guild)
        embed = view.build_embed()
        embed.description = (
            f"队长选秀已开始！\n"
            f"轮到: **{_display_name(interaction.guild, view.current_captain['captain_id'])}**\n\n"
            f"使用下拉菜单选人 → 点击确认按钮\n"
            f"Use dropdown to pick → click Confirm"
        )

        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(embed=embed, view=view)

    def build_embed(self):
        embed = discord.Embed(
            title="Captain Draft Setup / 队长选秀设置",
            description=f"Tournament ID: {self.tournament_id}\n\n"
                        f"从下方下拉菜单选择玩家，点击按钮设为/移除队长。\n"
                        f"选好至少 2 名队长后点击「确认开始选秀」。",
            color=discord.Color.blurple(),
        )

        if self.captains:
            cap_lines = []
            for pid, c in sorted(self.captains.items(), key=lambda x: x[1]["pick_order"]):
                cap_lines.append(f"**#{c['pick_order']}** {c['display_name']} — `{c['team_name']}` (Score: {c['tier_score']})")
            embed.add_field(
                name=f"队长 / Captains ({len(self.captains)})",
                value="\n".join(cap_lines) if cap_lines else "(无)",
                inline=False,
            )

        uncaptained = [p for p in self.available_players if p[0] not in self.captains]
        if uncaptained:
            lines = [f"{p[1]} ({p[2]}, {p[3]}pts)" for p in uncaptained[:15]]
            if len(uncaptained) > 15:
                lines.append(f"... 还有 {len(uncaptained) - 15} 人")
            embed.add_field(
                name=f"可选玩家 / Available ({len(uncaptained)})",
                value="\n".join(lines),
                inline=False,
            )

        return embed


# =============================================================================
# Tournament Cog
# =============================================================================


class Tournament(commands.Cog):
    """锦标赛 Tournament System"""

    async def cog_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        try:
            if isinstance(error, app_commands.CommandOnCooldown):
                remaining = int(error.retry_after)
                msg = f"⏳ 冷却中，请等 {remaining} 秒 / Cooldown, wait {remaining}s."
                if not interaction.response.is_done():
                    await interaction.response.send_message(msg, ephemeral=True)
                else:
                    await interaction.followup.send(msg, ephemeral=True)
            else:
                err_msg = f"❌ 错误: {error}"
                if not interaction.response.is_done():
                    await interaction.response.send_message(err_msg, ephemeral=True)
                else:
                    await interaction.followup.send(err_msg, ephemeral=True)
        except Exception:
            pass

    def __init__(self, bot):
        self.bot = bot
        self.session = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    tournament = app_commands.Group(
        name="gmpt-tournament",
        description="Tournament commands / 锦标赛命令",
    )

    # =====================================================================
    # create
    # =====================================================================
    @tournament.command(
        name="create",
        description="Create a tournament / 创建赛事",
    )
    @app_commands.describe(
        tournament_name="Tournament name / 赛事名称",
        tournament_format="Format / 赛制",
        rounds="Number of Swiss rounds / Swiss 轮数",
        max_players="Max players / 最大人数",
    )
    @app_commands.choices(tournament_format=[
        app_commands.Choice(name="Swiss (瑞士轮)", value="swiss"),
        app_commands.Choice(name="Elimination (淘汰赛)", value="elimination"),
    ])
    async def create_cmd(
        self, interaction: discord.Interaction,
        tournament_name: str,
        tournament_format: str = "swiss",
        rounds: int = 3,
        max_players: int = 32,
    ):
        # Defer immediately to avoid Discord 3-second timeout on DB operations
        await interaction.response.defer(ephemeral=False)

        try:
            if not interaction.user.guild_permissions.administrator:
                return await interaction.followup.send(
                    "仅管理员可创建锦标赛。", ephemeral=True
                )
            if not tournament_name:
                return await interaction.followup.send("请提供赛事名称。", ephemeral=True)

            conn = get_db(); cur = conn.cursor()
            cur.execute(
                "INSERT INTO tournaments "
                "(name, max_teams, team_size, status, created_by, format, max_players, rounds) "
                "VALUES (?,'0','0','signup',?,?,?,?)",
                (tournament_name, str(interaction.user.id),
                 tournament_format, max_players or 32, rounds or 3),
            )
            conn.commit(); tid = cur.lastrowid; conn.close()

            embed = discord.Embed(
                title=f"Tournament: {tournament_name}",
                description=(
                    f"Format: **{tournament_format.upper()}** | Rounds: **{rounds}** | Max: **{max_players}**\n"
                    f"Status: **Signup**\n\n"
                    f"点击下方按钮报名、查看列表或取消赛事。"
                ),
                color=discord.Color.gold(),
            ).set_footer(text=f"Tournament ID: {tid}")
            view = CreateTournamentView(
                tournament_id=tid,
                tournament_name=tournament_name,
                tournament_format=tournament_format,
                rounds=rounds,
                max_players=max_players,
                created_by=str(interaction.user.id),
                guild=interaction.guild,
                session=self.session,
            )
            await interaction.followup.send(embed=embed, view=view)

        except Exception as e:
            logger.error(f"create tournament error: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    f"创建锦标赛失败 / Failed to create tournament: {e}", ephemeral=True
                )
            except Exception as e:
                log_error("tournament", "create_cmd", e)

    # =====================================================================
    # cancel
    # =====================================================================
    @tournament.command(
        name="cancel",
        description="Cancel a tournament / 取消赛事（管理员/创建者）",
    )
    @app_commands.describe(tournament_id="Tournament ID / 赛事ID")
    async def cancel_cmd(self, interaction: discord.Interaction, tournament_id: int):
        await interaction.response.defer(ephemeral=False)
        conn = get_db(); cur = conn.cursor()
        t = get_tournament_or_none(cur, tournament_id)
        if not t:
            conn.close()
            return await interaction.followup.send("锦标赛不存在。", ephemeral=True)

        is_admin = interaction.user.guild_permissions.administrator
        is_creator = str(interaction.user.id) == (t["created_by"] or "")
        if not is_admin and not is_creator:
            conn.close()
            return await interaction.followup.send("仅管理员或赛事创建者可取消。", ephemeral=True)

        if t["status"] == "cancelled":
            conn.close()
            return await interaction.followup.send("该赛事已被取消。", ephemeral=True)

        cur.execute("UPDATE tournaments SET status='cancelled' WHERE id=?", (tournament_id,))
        conn.commit(); conn.close()
        await interaction.followup.send(
            f"锦标赛 **{t['name']}** (`#{tournament_id}`) 已取消 / cancelled."
        )

    # =====================================================================
    # signup
    # =====================================================================
    @tournament.command(
        name="signup",
        description="Sign up for a tournament / 报名参赛",
    )
    @app_commands.describe(tournament_id="Tournament ID (leave empty for latest) / 赛事ID（留空选最新）")
    async def signup_cmd(self, interaction: discord.Interaction, tournament_id: int = None):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()

        if tournament_id is None:
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

        tier_restriction = t["tier_restriction"]
        if tier_restriction:
            allowed = set(x.strip().upper() for x in tier_restriction.split(","))
            _, tier_name, _ = await fetch_player_tier(self.session, uid)
            if tier_name and tier_name.upper() not in allowed:
                conn.close()
                return await interaction.followup.send(
                    f"你的段位 **{tier_name}** 不符合本赛事要求（限 {', '.join(sorted(allowed))}）。"
                )

        cur.execute(
            "SELECT id FROM tournament_players WHERE tournament_id=? AND discord_id=?",
            (tournament_id, uid),
        )
        if cur.fetchone():
            conn.close()
            return await interaction.followup.send("你已经报名了这个锦标赛。")

        max_p = t["max_players"] or 32
        cur.execute("SELECT COUNT(*) as cnt FROM tournament_players WHERE tournament_id=?", (tournament_id,))
        cnt = cur.fetchone()["cnt"]
        if cnt >= max_p:
            conn.close()
            return await interaction.followup.send(f"报名已满（{max_p}人）。")

        tier_display, tier_key, _ = await fetch_player_tier(self.session, uid)
        if tier_display is None:
            tier_display = "未关联"
            tier_key = "UNRANKED"

        conn.close()

        conn = get_db(); cur = conn.cursor()
        seed_val = TIER_SEED.get(tier_key.upper() if tier_key else "UNRANKED", 10)
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
            f"✅ {interaction.user.mention} 报名成功！\n"
            f"锦标赛: **{t['name']}** | 段位: **{tier_display}** | ({cnt+1}/{max_p})",
            ephemeral=True,
        )

    # =====================================================================
    # players
    # =====================================================================
    @tournament.command(
        name="players",
        description="List registered players / 报名列表",
    )
    @app_commands.describe(tournament_id="Tournament ID (leave empty for latest) / 赛事ID（留空选最新）")
    async def players_cmd(self, interaction: discord.Interaction, tournament_id: int = None):
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

    # =====================================================================
    # start
    # =====================================================================
    @tournament.command(
        name="start",
        description="Start tournament / 开始比赛（管理员/创建者）",
    )
    @app_commands.describe(tournament_id="Tournament ID / 赛事ID")
    async def start_cmd(self, interaction: discord.Interaction, tournament_id: int):
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

        cur.execute(
            "SELECT discord_id, seed, points FROM tournament_players WHERE tournament_id=? ORDER BY seed ASC",
            (tournament_id,),
        )
        players = [dict(r) for r in cur.fetchall()]
        player_count = len(players)
        conn.close()

        if player_count < 2:
            return await interaction.response.send_message("至少需要 2 名玩家。", ephemeral=True)

        # Show confirm dialog
        embed = discord.Embed(
            title="确认开始比赛？",
            description=(
                f"锦标赛: **{t['name']}** (`#{tournament_id}`)\n"
                f"Format: **{t['format'].upper()}** | Rounds: **{t['rounds'] or 3}**\n"
                f"玩家数: **{player_count}**\n\n"
                f"开始后将生成第一轮对阵，无法撤销。"
            ),
            color=discord.Color.orange(),
        )
        view = ConfirmView(timeout=60)
        await interaction.response.send_message(embed=embed, view=view)

        await view.wait()
        if view.value is None:
            return
        if not view.value:
            return

        # User confirmed — execute start
        conn = get_db(); cur = conn.cursor()
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
            cur.execute(
                "UPDATE tournament_players SET points=points+3, wins=wins+1 WHERE tournament_id=? AND discord_id=?",
                (tournament_id, bye),
            )

        cur.execute("UPDATE tournaments SET status='active' WHERE id=?", (tournament_id,))
        conn.commit()

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
            a_name = _display_name(interaction.guild, m["player_a_id"])
            if m["player_b_id"]:
                b_name = _display_name(interaction.guild, m["player_b_id"])
                match_lines.append(f"`#{m['id']}` {a_name} vs {b_name} — {m['status']}")
            else:
                match_lines.append(f"`#{m['id']}` {a_name} — **BYE** (自动获胜)")

        embed.add_field(name="对阵表", value="\n".join(match_lines), inline=False)
        embed.set_footer(text=f"Tournament ID: {tournament_id} | 上报: /gmpt-tournament report tournament_id:{tournament_id}")
        conn.close()
        await interaction.edit_original_response(embed=embed, view=None)

    # =====================================================================
    # bracket
    # =====================================================================
    @tournament.command(
        name="bracket",
        description="View bracket / 查看对阵图",
    )
    @app_commands.describe(tournament_id="Tournament ID (leave empty for latest active) / 赛事ID")
    async def bracket_cmd(self, interaction: discord.Interaction, tournament_id: int = None):
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

        by_round = defaultdict(list)
        for m in matches:
            by_round[m["round"]].append(m)

        for rnd in sorted(by_round.keys()):
            lines = []
            for m in by_round[rnd]:
                a_name = _display_name(interaction.guild, m["player_a_id"])
                if m["player_b_id"]:
                    b_name = _display_name(interaction.guild, m["player_b_id"])
                    if m["status"] == "reported":
                        winner = "👑" if m["winner_id"] == m["player_a_id"] else ""
                        lines.append(
                            f"`#{m['id']}` **{a_name}** {m['score_a']}-{m['score_b']} {b_name} {winner}"
                        )
                    else:
                        lines.append(
                            f"`#{m['id']}` {a_name} vs {b_name} (Pending)"
                        )
                else:
                    lines.append(f"`#{m['id']}` {a_name} — **BYE**")
            embed.add_field(
                name=f"Round {rnd}",
                value="\n".join(lines) if lines else "(无)",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    # =====================================================================
    # standings
    # =====================================================================
    @tournament.command(
        name="standings",
        description="View standings / 查看排名",
    )
    @app_commands.describe(tournament_id="Tournament ID (leave empty for latest active) / 赛事ID")
    async def standings_cmd(self, interaction: discord.Interaction, tournament_id: int = None):
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

    # =====================================================================
    # report
    # =====================================================================
    @tournament.command(
        name="report",
        description="Report match score / 上报比分（按钮交互）",
    )
    @app_commands.describe(tournament_id="Tournament ID / 赛事ID")
    async def report_cmd(self, interaction: discord.Interaction, tournament_id: int):
        conn = get_db(); cur = conn.cursor()
        t = get_tournament_or_none(cur, tournament_id)
        if not t:
            conn.close()
            return await interaction.response.send_message("锦标赛不存在。", ephemeral=True)
        if t["status"] != "active":
            conn.close()
            return await interaction.response.send_message("锦标赛不在进行中。", ephemeral=True)
        conn.close()

        uid = str(interaction.user.id)
        view = ReportView(tournament_id, uid, interaction.guild)

        if not view._matches:
            return await interaction.response.send_message(
                "你没有待上报的比赛 / No pending matches found.", ephemeral=True
            )

        embed = discord.Embed(
            title="Report Match Score / 上报比分",
            description=(
                f"Tournament: **{t['name']}** (`#{tournament_id}`)\n\n"
                f"1. 从下拉菜单选择要上报的比赛\n"
                f"2. 点击「我赢了」或「对手赢了」按钮\n\n"
                f"Select a match → click result button"
            ),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, view=view)

    # =====================================================================
    # list
    # =====================================================================
    @tournament.command(
        name="list",
        description="List all tournaments / 赛事列表",
    )
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
    async def list_cmd(self, interaction: discord.Interaction):
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

    # =====================================================================
    # draft-setup — 队长选秀设置（按钮交互）
    # =====================================================================
    @tournament.command(
        name="draft-setup",
        description="Setup captain draft / 设置队长选秀（管理员，按钮交互）",
    )
    @app_commands.describe(tournament_id="Tournament ID / 赛事ID")
    async def draft_setup_cmd(
        self, interaction: discord.Interaction,
        tournament_id: int = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("仅管理员可设置队长选秀。", ephemeral=True)

        await interaction.response.defer(ephemeral=False)

        conn = get_db(); cur = conn.cursor()
        if tournament_id:
            cur.execute(
                "SELECT discord_id, tier FROM tournament_players WHERE tournament_id=?",
                (tournament_id,),
            )
            available = cur.fetchall()
        else:
            cur.execute("SELECT discord_id, 'UNRANKED' as tier FROM player_riot")
            available = cur.fetchall()

        if len(available) < 2:
            conn.close()
            return await interaction.followup.send(f"可用玩家不足（{len(available)}人），至少需要 2 人。")

        # Build available players list with tier scores
        available_players = []
        for r in available:
            tier_key = r["tier"].upper() if r["tier"] else "UNRANKED"
            r_score = TIER_SCORE.get(tier_key, 1)
            available_players.append((
                r["discord_id"],
                _display_name(interaction.guild, r["discord_id"]),
                tier_key,
                r_score,
            ))

        # Try to fetch Riot tiers for more accurate scores
        if self.session:
            for i, (pid, name, tier, score) in enumerate(available_players):
                try:
                    tier_display, tier_key, tier_score = await fetch_player_tier(self.session, pid)
                    if tier_key and tier_key != "UNRANKED":
                        available_players[i] = (pid, name, tier_key.upper(), tier_score)
                except Exception as e:
                    log_error("tournament", "draft_setup_cmd", e)
        conn.close()

        view = DraftSetupView(tournament_id, available_players, interaction.guild)
        embed = view.build_embed()
        await interaction.followup.send(embed=embed, view=view)

    # =====================================================================
    # draft-status
    # =====================================================================
    @tournament.command(
        name="draft-status",
        description="View draft status / 查看选秀状态",
    )
    @app_commands.describe(draft_id="Draft ID / 选秀ID")
    async def draft_status_cmd(self, interaction: discord.Interaction, draft_id: int):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM draft_sessions WHERE id=?", (draft_id,))
        draft = cur.fetchone()
        if not draft:
            conn.close()
            return await interaction.response.send_message("选秀不存在。", ephemeral=True)

        cur.execute("SELECT * FROM draft_captains WHERE draft_id=? ORDER BY pick_order", (draft_id,))
        caps = cur.fetchall()

        cur.execute("SELECT * FROM draft_picks WHERE draft_id=? ORDER BY pick_number", (draft_id,))
        picks = cur.fetchall()
        conn.close()

        embed = discord.Embed(
            title=f"Draft #{draft_id} — {draft['status']}",
            color=discord.Color.blue(),
        )

        for cap in caps:
            team_picks = [p for p in picks if p["captain_id"] == cap["captain_id"]]
            names = [_display_name(interaction.guild, p["player_id"]) for p in team_picks]
            embed.add_field(
                name=f"{cap['team_name']} ({cap['tier_score']} pts)",
                value="\n".join(names) if names else "(暂无队员 / Empty)",
                inline=True,
            )

        await interaction.response.send_message(embed=embed)

    # =====================================================================
    # draft-roster
    # =====================================================================
    @tournament.command(
        name="draft-roster",
        description="View final draft roster / 查看最终选秀名单",
    )
    @app_commands.describe(draft_id="Draft ID / 选秀ID")
    async def draft_roster_cmd(self, interaction: discord.Interaction, draft_id: int):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM draft_sessions WHERE id=?", (draft_id,))
        draft = cur.fetchone()
        if not draft:
            conn.close()
            return await interaction.response.send_message("选秀不存在。", ephemeral=True)

        cur.execute("SELECT * FROM draft_captains WHERE draft_id=? ORDER BY pick_order", (draft_id,))
        caps = cur.fetchall()

        cur.execute("SELECT * FROM draft_picks WHERE draft_id=? ORDER BY pick_number", (draft_id,))
        picks = cur.fetchall()
        conn.close()

        embed = discord.Embed(
            title=f"FINAL ROSTER — Draft #{draft_id}",
            description="✅ 队长选秀最终名单",
            color=discord.Color.gold(),
        )

        for cap in caps:
            team_picks = [p for p in picks if p["captain_id"] == cap["captain_id"]]
            names = []
            total_score = cap["tier_score"]
            for p in team_picks:
                # Try to get tier score from available data
                names.append(_display_name(interaction.guild, p["player_id"]))
            total_score += len(team_picks)  # approximate

            embed.add_field(
                name=f"{cap['team_name']} (队长 {cap['tier_score']} pts)",
                value="\n".join(names) if names else "(空)",
                inline=True,
            )

        # Draft pick order summary
        pick_lines = []
        for p in picks:
            cap_info = next((c for c in caps if c["captain_id"] == p["captain_id"]), None)
            team_label = cap_info["team_name"] if cap_info else p["captain_id"]
            pick_lines.append(
                f"`#{p['pick_number']}` {team_label} → {_display_name(interaction.guild, p['player_id'])}"
            )
        if pick_lines:
            embed.add_field(name="选秀顺序 / Pick Order", value="\n".join(pick_lines), inline=False)

        await interaction.response.send_message(embed=embed)

    # =====================================================================
    # draft-cancel
    # =====================================================================
    @tournament.command(
        name="draft-cancel",
        description="Cancel a draft / 取消选秀（管理员）",
    )
    @app_commands.describe(draft_id="Draft ID / 选秀ID")
    async def draft_cancel_cmd(self, interaction: discord.Interaction, draft_id: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("仅管理员可取消选秀。", ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM draft_sessions WHERE id=?", (draft_id,))
        draft = cur.fetchone()
        if not draft:
            conn.close()
            return await interaction.response.send_message("选秀不存在。", ephemeral=True)

        cur.execute("UPDATE draft_sessions SET status='cancelled' WHERE id=?", (draft_id,))
        conn.commit(); conn.close()
        await interaction.response.send_message(f"Draft #{draft_id} 已取消 / cancelled.")


async def setup(bot):
    await bot.add_cog(Tournament(bot))
