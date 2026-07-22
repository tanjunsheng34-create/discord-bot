"""
GMPT Bot — Dashboard / 统一控制面板
"""
import discord
from discord import app_commands
from discord.ext import commands, tasks
from database import get_db, db_context
from cogs.match_autocomplete import match_id_autocomplete
from utils.helpers import resolve_name
from config import (POST_MATCH_VC_TEAM_A, POST_MATCH_VC_TEAM_B,
                        RESULT_CHANNEL_ID, LOL_VOTE_CHANNEL_ID,
                        MEMBER_LEAVE_LOG_CHANNEL_ID)

# Try to import shared utilities from tournament cog
from cogs.tournament import (
    get_tournament_or_none,
    fetch_player_tier,
    TIER_SEED,
    TIER_SCORE,
    ConfirmView,
    CreateTournamentView,
    ReportView,
    DraftSetupView,
    DraftView,
    swiss_pairing,
    _display_name,
)

import logging
from utils.logger import log_error
from datetime import datetime, timezone, timedelta

try:
    from croniter import croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False
from cogs.economy import get_balance, add_coins, MainMenuView
import random
import sqlite3
import time as time_mod
logger = logging.getLogger(__name__)

class CreateMatchModal(discord.ui.Modal, title="创建比赛 / Create Match"):
    match_name = discord.ui.TextInput(
        label="比赛名称 / Match Name",
        placeholder="e.g. 周五内战 / Friday Inhouse",
        max_length=100,
        required=True,
    )
    max_players = discord.ui.TextInput(
        label="最大人数 / Max Players (偶数 / Even)",
        placeholder="10",
        default="10",
        max_length=3,
        required=True,
    )

    def __init__(self, guild, session):
        super().__init__()
        self.guild = guild
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        try:
            mp = int(self.max_players.value)
        except ValueError:
            return await interaction.response.send_message("人数必须是数字 / Number required.", ephemeral=True)
        if mp < 2 or mp % 2 != 0:
            return await interaction.response.send_message("人数必须为大于2的偶数 / Must be an even number > 2.", ephemeral=True)

        try:
            team_size = mp // 2
            conn = get_db(); cur = conn.cursor()
            cur.execute(
                "INSERT INTO tournaments (name, max_teams, team_size, created_by, status) VALUES (?, 2, ?, ?, 'open')",
                (self.match_name.value, team_size, str(interaction.user.id)),
            )
            conn.commit(); tid = cur.lastrowid; conn.close()

            embed = discord.Embed(
                title=f"Match: {self.match_name.value}",
                description=f"**{mp}** 人 / Players | 每队 / Per Team: {team_size}\nClick below to sign up / 点击下方按钮报名",
                color=discord.Color.blue(),
            ).set_footer(text=f"Match ID: {tid}")
            view = MatchView()
            await interaction.response.send_message(embed=embed, view=view)
            # 持久化:保存 message → match_id 映射,Bot 重启后按钮仍可用
            save_match_view_state(tid, (await interaction.original_response()).id, interaction.channel_id)
            # 发送初始报名列表
            list_embed = discord.Embed(
                title="已报名玩家 / Signed Up (0/" + str(mp) + ")",
                description="暂无玩家 / No signups yet",
                color=discord.Color.green(),
            )
            list_msg = await interaction.followup.send(embed=list_embed)
            set_player_list_msg(tid, list_msg.id)
            # 同步更新 DB 中的 player_list_msg_id
            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute(
                "UPDATE match_view_state SET player_list_msg_id=? WHERE message_id=?",
                (str(list_msg.id), str((await interaction.original_response()).id)),
            )
            conn2.commit(); conn2.close()
        except Exception as e:
            logger.error(f"CreateMatchModal.on_submit failed: {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    "创建比赛失败，请稍后再试 / Failed to create match, please try again later.",
                    ephemeral=True,
                )
            except Exception as e:
                print(f"[Dashboard] _create_match(blind) error: {e}")
    """选路比赛:创建时 role_pick=1,报名时需选 Top/JG/Mid/ADC/Support。"""
    match_name = discord.ui.TextInput(
        label="比赛名称 / Match Name",
        placeholder="e.g. 周五内战 / Friday Inhouse",
        max_length=100,
        required=True,
    )
    max_players = discord.ui.TextInput(
        label="最大人数 / Max Players (偶数 / Even)",
        placeholder="10",
        default="10",
        max_length=3,
        required=True,
    )

    def __init__(self, guild, session):
        super().__init__()
        self.guild = guild
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        try:
            mp = int(self.max_players.value)
        except ValueError:
            return await interaction.response.send_message("人数必须是数字 / Number required.", ephemeral=True)
        if mp < 2 or mp % 2 != 0:
            return await interaction.response.send_message("人数必须为大于2的偶数 / Must be an even number > 2.", ephemeral=True)

        try:
            team_size = mp // 2
            conn = get_db(); cur = conn.cursor()
            cur.execute(
                "INSERT INTO tournaments (name, max_teams, team_size, created_by, status, role_pick) VALUES (?, 2, ?, ?, 'open', 1)",
                (self.match_name.value, team_size, str(interaction.user.id)),
            )
            conn.commit(); tid = cur.lastrowid; conn.close()

            embed = discord.Embed(
                title=f"Match (选路): {self.match_name.value}",
                description=f"**{mp}** 人 / Players | 每队 / Per Team: {team_size}\n选路比赛 — 报名时需选择路线 / Role-pick match, select lane on signup",
                color=discord.Color.purple(),
            ).set_footer(text=f"Match ID: {tid}")
            view = MatchView()
            await interaction.response.send_message(embed=embed, view=view)
            save_match_view_state(tid, (await interaction.original_response()).id, interaction.channel_id)
            # 发送初始报名列表(含路线分布)
            list_embed = discord.Embed(
                title="已报名玩家 / Signed Up (0/" + str(mp) + ")",
                description="暂无玩家 / No signups yet\n\n🎯 路线分配 / Lane Distribution\n"
                            "Top:    - (0/2)\nJG:     - (0/2)\nMid:    - (0/2)\n"
                            "ADC:    - (0/2)\nSup:    - (0/2)",
                color=discord.Color.purple(),
            )
            list_msg = await interaction.followup.send(embed=list_embed)
            set_player_list_msg(tid, list_msg.id)
            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute(
                "UPDATE match_view_state SET player_list_msg_id=? WHERE message_id=?",
                (str(list_msg.id), str((await interaction.original_response()).id)),
            )
            conn2.commit(); conn2.close()
        except Exception as e:
            logger.error(f"CreateRoleMatchModal.on_submit failed: {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    "创建比赛失败，请稍后再试 / Failed to create match, please try again later.",
                    ephemeral=True,
                )
            except Exception as e:
                print(f"[Dashboard] _create_match(role-pick) error: {e}")


class SelectModeView(discord.ui.View):
    """创建比赛模式选择 — 有分路(选路) / 无分路(盲选)"""

    def __init__(self, guild, session):
        super().__init__(timeout=60)
        self.guild = guild
        self.session = session

    @discord.ui.button(label="🎯 有分路\nWith Roles", style=discord.ButtonStyle.primary, row=0)
    async def role_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CreateRoleMatchModal(self.guild, self.session)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🎯 无分路\nBlind Pick", style=discord.ButtonStyle.secondary, row=0)
    async def blind_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CreateMatchModal(self.guild, self.session)
        await interaction.response.send_modal(modal)


class LaneSelectView(discord.ui.View):
    """选路比赛报名时的路线选择下拉菜单 / Lane selection dropdown for role-pick match signup."""

    def __init__(self, match_id: int, uid: str, user: discord.Member | discord.User):
        super().__init__(timeout=120)
        self.match_id = match_id
        self.uid = uid
        self.user = user

        lane_select = discord.ui.Select(
            placeholder="选择你的路线 / Select your lane...",
            options=[
                discord.SelectOption(label="Top", emoji="🔝", description="上路"),
                discord.SelectOption(label="JG", emoji="🌲", description="打野 / Jungle"),
                discord.SelectOption(label="Mid", emoji="⚔️", description="中路"),
                discord.SelectOption(label="ADC", emoji="🏹", description="下路射手"),
                discord.SelectOption(label="Support", emoji="🛡️", description="辅助"),
            ],
        )
        lane_select.callback = self.lane_callback
        self.add_item(lane_select)

    async def lane_callback(self, interaction: discord.Interaction):
        lane = interaction.data["values"][0]

        conn = get_db(); cur = conn.cursor()
        # 二次校验:防止并发重复报名
        cur.execute(
            "SELECT id FROM registrations WHERE tournament_id=? AND discord_id=?",
            (self.match_id, self.uid),
        )
        if cur.fetchone():
            conn.close()
            return await interaction.response.send_message(
                "你已经报名了 / You are already signed up.", ephemeral=True,
            )

        # 再次检查名额
        cur.execute("SELECT max_teams, team_size FROM tournaments WHERE id=?", (self.match_id,))
        src = cur.fetchone()
        if src:
            max_p = src["max_teams"] * src["team_size"]
            cur.execute(
                "SELECT COUNT(*) as cnt FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0)",
                (self.match_id,),
            )
            cnt = cur.fetchone()["cnt"]
            if cnt >= max_p:
                conn.close()
                return await interaction.response.send_message(
                    f"比赛已满 ({cnt}/{max_p}) / Match is full.", ephemeral=True,
                )

        cur.execute(
            "INSERT INTO registrations (tournament_id, discord_id, lane) VALUES (?,?,?)",
            (self.match_id, self.uid, lane),
        )
        cur.execute(
            "INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)",
            (self.uid, self.user.name),
        )
        conn.commit(); conn.close()

        await interaction.response.send_message(
            f"{self.user.mention} 已报名 **{lane}** / Signed up as **{lane}**.",
            ephemeral=False,
        )


class CreateTournamentModal(discord.ui.Modal, title="创建赛事 / Create Tournament"):
    tournament_name = discord.ui.TextInput(
        label="赛事名称 / Tournament Name",
        placeholder="e.g. Season 1 Championship",
        max_length=100,
        required=True,
    )
    tournament_format = discord.ui.TextInput(
        label="赛制 / Format (swiss / elimination)",
        placeholder="swiss",
        default="swiss",
        max_length=20,
        required=True,
    )
    rounds = discord.ui.TextInput(
        label="轮数 / Rounds",
        placeholder="3",
        default="3",
        max_length=2,
        required=True,
    )
    max_players = discord.ui.TextInput(
        label="最大人数 / Max Players",
        placeholder="32",
        default="32",
        max_length=3,
        required=True,
    )

    def __init__(self, guild, session):
        super().__init__()
        self.guild = guild
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        try:
            rds = int(self.rounds.value)
            mp = int(self.max_players.value)
        except ValueError:
            return await interaction.response.send_message("轮数和人数必须是数字 / Rounds & players must be numbers.", ephemeral=True)

        fmt = self.tournament_format.value.lower().strip()
        if fmt not in ("swiss", "elimination"):
            return await interaction.response.send_message("赛制仅支持 swiss 或 elimination / Format must be swiss or elimination.", ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("仅管理员可创建锦标赛 / Admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=False)

        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO tournaments "
            "(name, max_teams, team_size, status, created_by, format, max_players, rounds) "
            "VALUES (?,'0','0','signup',?,?,?,?)",
            (self.tournament_name.value, str(interaction.user.id), fmt, mp or 32, rds or 3),
        )
        conn.commit(); tid = cur.lastrowid; conn.close()

        embed = discord.Embed(
            title=f"Tournament: {self.tournament_name.value}",
            description=(
                f"Format: **{fmt.upper()}** | Rounds: **{rds}** | Max: **{mp}**\n"
                f"Status: **Signup**\n\n"
                f"Click below to sign up, view list or cancel / 点击下方按钮报名、查看列表或取消赛事"
            ),
            color=discord.Color.gold(),
        ).set_footer(text=f"Tournament ID: {tid}")
        view = CreateTournamentView(
            tournament_id=tid,
            tournament_name=self.tournament_name.value,
            tournament_format=fmt,
            rounds=rds,
            max_players=mp,
            created_by=str(interaction.user.id),
            guild=interaction.guild,
            session=self.session,
        )
        await interaction.followup.send(embed=embed, view=view)


# =============================================================================
# TeamAssignView — inline team assignment for custom matches
# =============================================================================
class TeamAssignView(discord.ui.View):
    """Simplified team assignment like CustomTeamView, used inside dashboard."""
    def __init__(self, match_id, match_name, player_ids, guild, team_size, timeout=300):
        super().__init__(timeout=None)
        self.match_id = match_id
        self.match_name = match_name
        self.guild = guild
        self.team_size = team_size
        self.all_player_ids = player_ids
        self.team_a = []
        self.team_b = []
        self.selected_player = None
        self._rebuild_select()

    def _get_unassigned(self):
        return [pid for pid in self.all_player_ids if pid not in self.team_a and pid not in self.team_b]

    def _rebuild_select(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)

        unassigned = self._get_unassigned()
        options = []
        for pid in unassigned:
            label = resolve_name(self.guild, pid)
            options.append(discord.SelectOption(label=label[:25], value=pid))

        if not options:
            options.append(discord.SelectOption(label="(无待分配玩家 / No players)", value="__none__"))

        select = discord.ui.Select(
            placeholder="选择玩家 / Select a player...",
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
        self.selected_player = val
        name = resolve_name(self.guild, val)
        await interaction.followup.send(f"已选择 / Selected: {name},点击加入 A 队或 B 队", ephemeral=True)

    @discord.ui.button(label="加入 A 队 / A", style=discord.ButtonStyle.primary, emoji="🔵", row=1)
    async def add_to_a(self, interaction: discord.Interaction, button):
        try:
            if not getattr(self, "selected_player", None):
                return await interaction.response.send_message(
                    "请先从下拉菜单选择一个玩家 / Select a player first.", ephemeral=True,
                )
            if len(self.team_a) >= self.team_size:
                return await interaction.response.send_message(
                    f"A 队已满 (上限 {self.team_size}) / Team A full.", ephemeral=True,
                )
            if self.selected_player in self.team_a or self.selected_player in self.team_b:
                return await interaction.response.send_message(
                    "该玩家已分配 / Already assigned.", ephemeral=True,
                )
            self.team_a.append(self.selected_player)
            self.selected_player = None
            self._rebuild_select()
            await interaction.response.defer()
            await interaction.edit_original_response(embed=self._build_embed(), view=self)
        except Exception as e:
            logger.error(f"[TeamAssignView] add_to_a error: {e}", exc_info=True)
            try:
                await interaction.followup.send("操作失败 / Failed, please try again.", ephemeral=True)
            except Exception as e:
                log_error("dashboard", "add_to_a", e)

    @discord.ui.button(label="加入 B 队 / B", style=discord.ButtonStyle.danger, emoji="🔴", row=1)
    async def add_to_b(self, interaction: discord.Interaction, button):
        try:
            if not getattr(self, "selected_player", None):
                return await interaction.response.send_message(
                    "请先从下拉菜单选择一个玩家 / Select a player first.", ephemeral=True,
                )
            if len(self.team_b) >= self.team_size:
                return await interaction.response.send_message(
                    f"B 队已满 (上限 {self.team_size}) / Team B full.", ephemeral=True,
                )
            if self.selected_player in self.team_a or self.selected_player in self.team_b:
                return await interaction.response.send_message(
                    "该玩家已分配 / Already assigned.", ephemeral=True,
                )
            self.team_b.append(self.selected_player)
            self.selected_player = None
            self._rebuild_select()
            await interaction.response.defer()
            await interaction.edit_original_response(embed=self._build_embed(), view=self)
        except Exception as e:
            logger.error(f"[TeamAssignView] add_to_b error: {e}", exc_info=True)
            try:
                await interaction.followup.send("操作失败 / Failed, please try again.", ephemeral=True)
            except Exception as e:
                log_error("dashboard", "add_to_b", e)

    @discord.ui.button(label="清空 / Clear", style=discord.ButtonStyle.secondary, emoji="🔄", row=2)
    async def clear_teams(self, interaction: discord.Interaction, button):
        try:
            await interaction.response.defer(ephemeral=True)
            self.team_a.clear()
            self.team_b.clear()
            self.selected_player = None
            self._rebuild_select()
            await interaction.response.defer()
            await interaction.edit_original_response(embed=self._build_embed(), view=self)
        except Exception as e:
            logger.error(f"[TeamAssignView] clear error: {e}", exc_info=True)

    @discord.ui.button(label="确认分队 / Confirm", style=discord.ButtonStyle.success, emoji="✅", row=2)
    async def confirm_teams(self, interaction: discord.Interaction, button):
        total = len(self.team_a) + len(self.team_b)
        all_players = len(self.all_player_ids)
        if total < min(2, all_players):
            return await interaction.response.send_message(
                "请至少分配 2 名玩家到队伍中 / Assign at least 2 players.", ephemeral=True,
            )
        await interaction.response.defer()

        conn = get_db(); cur = conn.cursor()
        cur.execute("DELETE FROM teams WHERE tournament_id=?", (self.match_id,))
        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (self.match_id, "A 队 Team A"))
        aid = cur.lastrowid
        for uid in self.team_a:
            cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?",
                        (aid, self.match_id, uid))
        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (self.match_id, "B 队 Team B"))
        bid = cur.lastrowid
        for uid in self.team_b:
            cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?",
                        (bid, self.match_id, uid))
        cur.execute("UPDATE tournaments SET status='closed' WHERE id=?", (self.match_id,))
        conn.commit(); conn.close()

        a_mentions = []
        for uid in self.team_a:
            m = self.guild.get_member(int(uid))
            a_mentions.append(m.mention if m else f"<@{uid}>")
        b_mentions = []
        for uid in self.team_b:
            m = self.guild.get_member(int(uid))
            b_mentions.append(m.mention if m else f"<@{uid}>")

        for child in self.children:
            child.disabled = True
        embed = self._build_embed()
        embed.title = f"Teams Confirmed — {self.match_name}"
        embed.description = (
            f"🔵 **A 队 Team A** (ID:{aid}): {' '.join(a_mentions)}\n"
            f"🔴 **B 队 Team B** (ID:{bid}): {' '.join(b_mentions)}\n\n"
            f"Settle: `/gmpt-lol-settle {self.match_id} <win_team_id>`"
        )
        embed.color = discord.Color.green()
        await interaction.edit_original_response(embed=embed, view=self)
        try:
            voice_view = VoicePullView(self.team_a, self.team_b, self.guild)
            await interaction.followup.send("📢 点击按钮将玩家拉入对应语音频道:", view=voice_view)
        except Exception as e:
            log_error("dashboard", "confirm_teams", e)

    def _build_embed(self):
        embed = discord.Embed(
            title=f"Team Assign — {self.match_name}",
            color=discord.Color.blue(),
        )
        a_names = []
        for uid in self.team_a:
            m = self.guild.get_member(int(uid))
            a_names.append(m.display_name if m else f"<@{uid}>")
        b_names = []
        for uid in self.team_b:
            m = self.guild.get_member(int(uid))
            b_names.append(m.display_name if m else f"<@{uid}>")

        unassigned = self._get_unassigned()
        un_names = []
        for uid in unassigned:
            m = self.guild.get_member(int(uid))
            un_names.append(m.display_name if m else f"<@{uid}>")

        if a_names:
            embed.add_field(name=f"🔵 A 队 / Team A ({len(self.team_a)}/{self.team_size})", value="\n".join(a_names), inline=True)
        if b_names:
            embed.add_field(name=f"🔴 B 队 / Team B ({len(self.team_b)}/{self.team_size})", value="\n".join(b_names), inline=True)
        if not a_names and not b_names:
            embed.description = "尚未分配任何玩家 / No players assigned yet."

        if un_names:
            embed.add_field(
                name=f"待分配 / Unassigned ({len(un_names)})",
                value="\n".join(un_names[:10]) + (f"\n... +{len(un_names)-10} more" if len(un_names) > 10 else ""),
                inline=False,
            )
        return embed


# =============================================================================
# MatchView — 比赛创建后附带的报名 / 查看 / 结算按钮
# =============================================================================

# ══════════ 报名列表消息缓存(match_id → message_id,内存 + DB 双写)══════════
_player_list_msgs: dict[int, int] = {}

def get_player_list_msg(match_id: int) -> int | None:
    return _player_list_msgs.get(match_id)

def set_player_list_msg(match_id: int, msg_id: int):
    _player_list_msgs[match_id] = msg_id

def remove_player_list_msg(match_id: int):
    _player_list_msgs.pop(match_id, None)


# ══════════ MatchView 持久化状态(Bot 重启后恢复报名按钮)══════════
def save_match_view_state(match_id: int, message_id: int, channel_id: int, player_list_msg_id: int | None = None):
    """Persist message_id → match_id mapping so the persistent MatchView can recover after restart."""
    with db_context() as cur:
        cur.execute(
            "INSERT OR REPLACE INTO match_view_state (message_id, match_id, channel_id, player_list_msg_id) "
            "VALUES (?, ?, ?, ?)",
            (str(message_id), match_id, channel_id, str(player_list_msg_id) if player_list_msg_id else None),
        )


def get_match_id_from_message(message_id: int) -> int | None:
    with db_context() as cur:
        cur.execute("SELECT match_id, channel_id, player_list_msg_id FROM match_view_state WHERE message_id=?", (str(message_id),))
        row = cur.fetchone()
    if not row:
        return None
    # 同步到内存缓存,方便 refresh_player_list 使用
    if row["player_list_msg_id"]:
        try:
            _player_list_msgs[row["match_id"]] = int(row["player_list_msg_id"])
        except (ValueError, TypeError):
            pass
    return row["match_id"]


def get_match_row(match_id: int):
    with db_context() as cur:
        cur.execute("SELECT * FROM tournaments WHERE id=?", (match_id,))
        row = cur.fetchone()
    return row


# ══════════ MatchViewWithID — 可持久化版(Bot 重启后按钮仍有效)══════════
class AdminAddPlayerModal(discord.ui.Modal, title="管理员加人 / Admin Add Player"):
    """弹窗让管理员输入要加入比赛的 Discord 用户。"""
    user_input = discord.ui.TextInput(
        label="玩家 / Player (@mention, name, or ID)",
        placeholder="@username 或 用户名 或 用户ID",
        max_length=100,
        required=True,
    )

    def __init__(self, match_id: int, guild: discord.Guild):
        super().__init__()
        self.match_id = match_id
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        # Try to resolve the user
        raw = self.user_input.value.strip()
        member = None

        # 1. Try as mention <@123>
        if raw.startswith("<@") and raw.endswith(">"):
            uid = raw.replace("<@", "").replace("!", "").replace(">", "")
            member = self.guild.get_member(int(uid))
        # 2. Try as raw numeric ID
        elif raw.isdigit():
            member = self.guild.get_member(int(raw))
        # 3. Try as name#discriminator or display_name
        if not member:
            member = discord.utils.get(self.guild.members, name=raw)
        if not member:
            member = discord.utils.get(self.guild.members, display_name=raw)
        if not member:
            # Try case-insensitive startswith
            lower = raw.lower()
            for m in self.guild.members:
                if m.name.lower() == lower or m.display_name.lower() == lower:
                    member = m
                    break

        if not member:
            return await interaction.response.send_message(
                f"找不到用户: `{raw}`。请检查输入。\nUser not found. Try `@mention`, username, or ID.",
                ephemeral=True,
            )

        uid = str(member.id)
        conn = get_db(); cur = conn.cursor()

        # Check match status
        cur.execute("SELECT * FROM tournaments WHERE id=?", (self.match_id,))
        t = cur.fetchone()
        if not t or t["status"] != "open":
            conn.close()
            return await interaction.response.send_message("报名已关闭或比赛不存在。", ephemeral=True)

        # Check if already signed up
        cur.execute("SELECT id FROM registrations WHERE tournament_id=? AND discord_id=?", (self.match_id, uid))
        if cur.fetchone():
            conn.close()
            return await interaction.response.send_message(
                f"{member.mention} 已经报过名了 / Already signed up.", ephemeral=True
            )

        # Check capacity (only main players, not subs)
        max_p = t["max_teams"] * t["team_size"]
        cur.execute("SELECT COUNT(*) as cnt FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0)", (self.match_id,))
        cnt = cur.fetchone()["cnt"]
        if cnt >= max_p:
            conn.close()
            return await interaction.response.send_message("报名已满 / Signup full.", ephemeral=True)

        cur.execute("INSERT INTO registrations (tournament_id, discord_id) VALUES (?,?)", (self.match_id, uid))
        cur.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (uid, member.name))
        conn.commit(); conn.close()

        await interaction.response.send_message(
            f"✅ 已将 {member.mention} 加入比赛 # {self.match_id} ({cnt+1}/{max_p})", ephemeral=True
        )

        # Refresh the signup list in the channel
        from cogs.dashboard import MatchViewWithID as _MV
        fake_view = _MV()
        await fake_view._refresh_list(interaction, self.match_id)


class AdminSubPlayerModal(discord.ui.Modal, title="设置替补 / Set Substitute"):
    """弹窗让管理员输入替补玩家。替补不占正式名额。"""
    user_input = discord.ui.TextInput(
        label="替补玩家 / Substitute (@mention, name, or ID)",
        placeholder="@username 或 用户名 或 用户ID",
        max_length=100,
        required=True,
    )

    def __init__(self, match_id: int, guild: discord.Guild):
        super().__init__()
        self.match_id = match_id
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.user_input.value.strip()
        member = None

        if raw.startswith("<@") and raw.endswith(">"):
            uid = raw.replace("<@", "").replace("!", "").replace(">", "")
            member = self.guild.get_member(int(uid))
        elif raw.isdigit():
            member = self.guild.get_member(int(raw))
        if not member:
            member = discord.utils.get(self.guild.members, name=raw)
        if not member:
            member = discord.utils.get(self.guild.members, display_name=raw)
        if not member:
            lower = raw.lower()
            for m in self.guild.members:
                if m.name.lower() == lower or m.display_name.lower() == lower:
                    member = m
                    break

        if not member:
            return await interaction.response.send_message(
                f"找不到用户: `{raw}`。请检查输入。", ephemeral=True
            )

        uid = str(member.id)
        conn = get_db(); cur = conn.cursor()

        cur.execute("SELECT * FROM tournaments WHERE id=?", (self.match_id,))
        t = cur.fetchone()
        if not t or t["status"] != "open":
            conn.close()
            return await interaction.response.send_message("报名已关闭或比赛不存在。", ephemeral=True)

        # Check if already in registrations (as main or sub)
        cur.execute("SELECT id, is_sub FROM registrations WHERE tournament_id=? AND discord_id=?", (self.match_id, uid))
        existing = cur.fetchone()
        if existing:
            conn.close()
            label = "替补" if existing["is_sub"] else "正式"
            return await interaction.response.send_message(
                f"{member.mention} 已是{label}玩家 / Already registered as {label}.", ephemeral=True
            )

        # Insert as sub (no capacity check — subs don't count toward max)
        cur.execute(
            "INSERT INTO registrations (tournament_id, discord_id, is_sub) VALUES (?,?,1)",
            (self.match_id, uid),
        )
        cur.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (uid, member.name))
        conn.commit(); conn.close()

        await interaction.response.send_message(
            f"✅ 已将 {member.mention} 设为比赛 # {self.match_id} 的替补球员", ephemeral=True
        )

        from cogs.dashboard import MatchViewWithID as _MV
        fake_view = _MV()
        await fake_view._refresh_list(interaction, self.match_id)


class ReShuffleView(discord.ui.View):
    """结算后显示的「重新分队」按钮视图(4 个按钮一行)。"""

    def __init__(self, match_id: int, guild: discord.Guild):
        super().__init__(timeout=604800)  # 7 days
        self.match_id = match_id
        self.guild = guild
        self._voice_used_a = False
        self._voice_used_b = False

    def _get_main_players(self):
        """只取正式玩家(is_sub=0),替补不计入。"""
        with db_context() as cur:
            cur.execute(
                "SELECT discord_id FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0)",
                (self.match_id,),
            )
            players = [r["discord_id"] for r in cur.fetchall()]
        return players

    def _get_source(self):
        with db_context() as cur:
            cur.execute("SELECT * FROM tournaments WHERE id=?", (self.match_id,))
            src = cur.fetchone()
        return src

    def _build_player_list_embed(self) -> discord.Embed:
        """Build embed showing settle title + current player list."""
        src = self._get_source()
        name = src["name"] if src else f"Match #{self.match_id}"

        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT discord_id FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0) ORDER BY id ASC",
            (self.match_id,),
        )
        rows = cur.fetchall()
        conn.close()

        max_p = (src["max_teams"] * src["team_size"]) if src else (len(rows) * 2)

        if rows:
            lines = []
            for i, r in enumerate(rows, 1):
                name_str = resolve_name(self.guild, r["discord_id"])
                lines.append(f"{i}. {name_str}")
            desc = "\n".join(lines)
        else:
            desc = "(暂无参赛玩家 / No players)"

        return discord.Embed(
            title=f"结算完成 — {name}",
            description=f"**当前参赛玩家 ({len(rows)}/{max_p}):**\n{desc}",
            color=discord.Color.gold(),
        )

    async def _refresh_embed(self, interaction: discord.Interaction):
        """Update the ReShuffleView message embed with current player list."""
        try:
            embed = self._build_player_list_embed()
            await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            log_error("dashboard", "_refresh_embed", e)

    @discord.ui.button(label="完赛", style=discord.ButtonStyle.success, emoji="✅", row=0)
    async def finish_btn(self, interaction: discord.Interaction, button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("管理员专用 / Admin only.", ephemeral=True)
        await interaction.response.defer(ephemeral=False)

        src = self._get_source()
        if not src:
            return await interaction.followup.send("源比赛不存在 / Source match not found.")
        if src["status"] == "finished":
            return await interaction.followup.send("比赛已完赛 / Already finished.")

        with db_context() as cur:
            cur.execute("UPDATE tournaments SET status='finished' WHERE id=?", (self.match_id,))

        # Disable all buttons on this view
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title=f"🏁 比赛已完赛 — {src['name']}",
            description="本场比赛已结束,按钮已禁用 / Match finished, all buttons disabled.",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed)
        try:
            await interaction.message.edit(view=self)
        except Exception as e:
            log_error("dashboard", "finish_btn", e)

    @discord.ui.button(label="重新分队", style=discord.ButtonStyle.primary, emoji="🔄", row=0)
    async def reshuffle_btn(self, interaction: discord.Interaction, button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("管理员专用 / Admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=False)

        src = self._get_source()
        if not src:
            return await interaction.followup.send("源比赛不存在 / Source match not found.")

        players = self._get_main_players()
        if len(players) < 2:
            return await interaction.followup.send("参赛人数不足 (至少2人) / Not enough players (min 2).")

        # Ensure even
        if len(players) % 2 != 0:
            players = players[:-1]

        team_size = len(players) // 2
        match_name = f"{src['name']} (续战 #{self.match_id})"

        # Retry on database locked with exponential backoff
        import time
        for attempt in range(3):
            try:
                conn = get_db(); cur = conn.cursor()
                cur.execute(
                    "INSERT INTO tournaments (name, max_teams, team_size, created_by, status) VALUES (?, 2, ?, ?, 'open')",
                    (match_name, team_size, str(interaction.user.id)),
                )
                conn.commit()
                new_mid = cur.lastrowid

                for pid in players:
                    cur.execute("INSERT INTO registrations (tournament_id, discord_id) VALUES (?,?)", (new_mid, pid))
                    cur.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (pid, "unknown"))

                random.shuffle(players)
                split = len(players) // 2
                ta, tb = players[:split], players[split:]

                cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (new_mid, "A 队 Team A"))
                aid = cur.lastrowid
                for u in ta:
                    cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?", (aid, new_mid, u))

                cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (new_mid, "B 队 Team B"))
                bid = cur.lastrowid
                for u in tb:
                    cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?", (bid, new_mid, u))

                cur.execute("UPDATE tournaments SET status='closed' WHERE id=?", (new_mid,))
                conn.commit(); conn.close()
                break  # success
            except sqlite3.OperationalError as e:
                try:
                    conn.close()
                except Exception:
                    pass
                if "locked" in str(e).lower() and attempt < 2:
                    time.sleep(0.3 * (attempt + 1))
                    continue
                raise

        a_mentions = [f"<@{uid}>" for uid in ta]
        b_mentions = [f"<@{uid}>" for uid in tb]

        embed = discord.Embed(
            title=f"🔄 重新分队 — {match_name}",
            description=(
                f"🔵 **A 队 Team A** (ID:{aid}): {' '.join(a_mentions)}\n"
                f"🔴 **B 队 Team B** (ID:{bid}): {' '.join(b_mentions)}\n\n"
                f"Match ID: {new_mid}\n"
                f"Settle: `/gmpt-lol-settle {new_mid} <win_team_id>`"
            ),
            color=discord.Color.gold(),
        )
        await interaction.followup.send(embed=embed)

    @discord.ui.button(label="自己分队", style=discord.ButtonStyle.secondary, emoji="✋", row=0)
    async def manual_btn(self, interaction: discord.Interaction, button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("管理员专用 / Admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        src = self._get_source()
        if not src:
            return await interaction.followup.send("源比赛不存在 / Source match not found.")

        players = self._get_main_players()
        if len(players) < 2:
            return await interaction.followup.send("参赛人数不足 (至少2人) / Not enough players (min 2).")

        if len(players) % 2 != 0:
            players = players[:-1]

        team_size = len(players) // 2
        match_name = f"{src['name']} (续战 #{self.match_id})"

        view = ManualTeamView(
            src_match_id=self.match_id,
            match_name=match_name,
            player_ids=players,
            guild=self.guild,
            team_size=team_size,
            created_by=str(interaction.user.id),
        )
        await interaction.followup.send(
            f"**手动分队 / Manual Team Assign** — {match_name}\n选择玩家后点击 A 队 / B 队",
            embed=view._build_embed(),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="队长分队", style=discord.ButtonStyle.secondary, emoji="👑", row=0)
    async def captain_btn(self, interaction: discord.Interaction, button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("管理员专用 / Admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        src = self._get_source()
        if not src:
            return await interaction.followup.send("源比赛不存在 / Source match not found.")

        players = self._get_main_players()
        if len(players) < 4:
            return await interaction.followup.send("参赛人数不足 (至少4人) / Not enough players (min 4).")

        if len(players) % 2 != 0:
            players = players[:-1]

        team_size = len(players) // 2
        match_name = f"{src['name']} (续战 #{self.match_id})"

        view = CaptainDraftView(
            src_match_id=self.match_id,
            match_name=match_name,
            player_ids=players,
            guild=self.guild,
            team_size=team_size,
            created_by=str(interaction.user.id),
        )
        await interaction.followup.send(
            f"**队长分队 / Captain Draft** — {match_name}\n第一步:选择 2 名队长",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="结算", style=discord.ButtonStyle.danger, emoji="💰", row=1)
    async def settle_btn(self, interaction: discord.Interaction, button):
        """Settle the match -- select winner + MVP, distribute coins."""
        await interaction.response.defer(ephemeral=True)

        src = self._get_source()
        if not src:
            return await interaction.followup.send("源比赛不存在 / Source match not found.", ephemeral=True)
        if src["status"] == "finished":
            return await interaction.followup.send("该比赛已结算 / Already settled.", ephemeral=True)
        if src["status"] != "closed":
            return await interaction.followup.send("比赛尚未分队 / Match not yet assigned teams.", ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id, name FROM teams WHERE tournament_id=?", (self.match_id,))
        teams = cur.fetchall()
        conn.close()

        if len(teams) < 2:
            return await interaction.followup.send("未找到两支队伍 / Two teams not found.", ephemeral=True)

        team_options = [discord.SelectOption(label=tm["name"][:100], value=str(tm["id"])) for tm in teams]

        class SettleState:
            win_team_id = None
            mvp_id = None

        state = SettleState()

        async def _do_settle(s_int, mid, win_tid, mvp_uid):
            conn_name = get_db(); cur_name = conn_name.cursor()
            cur_name.execute("SELECT name FROM tournaments WHERE id=?", (mid,))
            name_row = cur_name.fetchone()
            match_name = name_row["name"] if name_row else f"Match #{mid}"
            conn_name.close()

            analysis_embed = await _execute_settle(
                match_id=mid, win_team_id=win_tid, mvp_id=mvp_uid,
                guild=self.guild, match_name=match_name, bot=interaction.client,
            )

            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.label == "结算":
                    child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception as e:
                log_error("dashboard", "_do_settle", e)

            await _post_settle_actions(mid, match_name, self.guild, interaction.channel, analysis_embed, interaction.client)

            mvp_text = f"\n🏅 MVP: <@{mvp_uid}> +50" if mvp_uid else ""
            await s_int.response.send_message(
                f"💰 结算完成 / Settled!{mvp_text}\n胜方 +150 | 参与 +50",
                ephemeral=False,
            )

        async def mvp_cb(mvp_int: discord.Interaction):
            mvp_val = mvp_int.data["values"][0]
            state.mvp_id = None if mvp_val == "__none__" else mvp_val
            await _do_settle(mvp_int, self.match_id, state.win_team_id, state.mvp_id)

        async def win_cb(sel_int: discord.Interaction):
            state.win_team_id = int(sel_int.data["values"][0])

            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute(
                "SELECT discord_id FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0)",
                (self.match_id,),
            )
            players = cur2.fetchall(); conn2.close()

            mvp_opts = [discord.SelectOption(label="无 MVP / Skip", value="__none__")]
            for p in players:
                label = resolve_name(self.guild, p["discord_id"])
                mvp_opts.append(discord.SelectOption(label=label[:100], value=p["discord_id"]))

            mvp_view = discord.ui.View(timeout=120)
            mvp_sel = discord.ui.Select(placeholder="选择 MVP / Select MVP (可选)...", options=mvp_opts[:25])
            mvp_sel.callback = mvp_cb
            mvp_view.add_item(mvp_sel)
            await sel_int.response.send_message("请选择 MVP (可选) / Select MVP:", view=mvp_view, ephemeral=True)

        win_view = discord.ui.View(timeout=120)
        win_select = discord.ui.Select(placeholder="选择获胜队伍 / Select winning team...", options=team_options)
        win_select.callback = win_cb
        win_view.add_item(win_select)
        await interaction.followup.send("选择获胜队伍 / Select winning team:", view=win_view, ephemeral=True)

    @discord.ui.button(label="报名", style=discord.ButtonStyle.primary, emoji="📝", row=1)
    async def signup_btn(self, interaction: discord.Interaction, button):
        """Re-add the clicking user to this match's registrations."""
        await interaction.response.defer(ephemeral=True)

        src = self._get_source()
        if not src:
            return await interaction.followup.send("源比赛不存在 / Source match not found.", ephemeral=True)

        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()

        # Check if already registered
        cur.execute("SELECT id FROM registrations WHERE tournament_id=? AND discord_id=?", (self.match_id, uid))
        if cur.fetchone():
            conn.close()
            return await interaction.followup.send("你已经报名了 / You are already signed up.", ephemeral=True)

        # Check capacity
        max_p = src["max_teams"] * src["team_size"]
        cur.execute(
            "SELECT COUNT(*) as cnt FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0)",
            (self.match_id,),
        )
        cnt = cur.fetchone()["cnt"]
        if cnt >= max_p:
            conn.close()
            return await interaction.followup.send(f"比赛已满 ({cnt}/{max_p}) / Match is full.", ephemeral=True)

        # 选路比赛:弹出路线选择
        if src.get("role_pick"):
            conn.close()
            lane_view = LaneSelectView(self.match_id, uid, interaction.user)
            return await interaction.followup.send(
                "请选择你的路线 / Select your lane:", view=lane_view, ephemeral=True,
            )

        cur.execute("INSERT INTO registrations (tournament_id, discord_id) VALUES (?,?)", (self.match_id, uid))
        cur.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (uid, interaction.user.name))
        conn.commit(); conn.close()

        await interaction.followup.send(f"{interaction.user.mention} 已报名 / Signed up.", ephemeral=False)
        await self._refresh_embed(interaction)

    @discord.ui.button(label="退出", style=discord.ButtonStyle.secondary, emoji="🚪", row=1)
    async def leave_btn(self, interaction: discord.Interaction, button):
        """Remove self from this match's registrations and update embed."""
        await interaction.response.defer(ephemeral=True)

        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id FROM registrations WHERE tournament_id=? AND discord_id=?", (self.match_id, uid))
        row = cur.fetchone()
        if not row:
            conn.close()
            return await interaction.followup.send("你未报名该比赛 / You are not signed up.", ephemeral=True)

        cur.execute("DELETE FROM registrations WHERE tournament_id=? AND discord_id=?", (self.match_id, uid))
        conn.commit(); conn.close()
        await interaction.followup.send(f"{interaction.user.mention} 已退出比赛 / Left the match.", ephemeral=False)
        await self._refresh_embed(interaction)

    def _resolve_team_ids(self):
        """从 DB 解析本 match 的 A/B 队成员(按 id DESC 取最新一组)。"""
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id, name FROM teams WHERE tournament_id=? ORDER BY id DESC", (self.match_id,))
        teams = cur.fetchall()
        team_a_ids = []
        team_b_ids = []
        for t in teams:
            cur.execute(
                "SELECT discord_id FROM registrations WHERE team_id=? AND (is_sub IS NULL OR is_sub=0)",
                (t["id"],),
            )
            pids = [r["discord_id"] for r in cur.fetchall()]
            if not pids:
                continue
            # 名称为 "A 队 Team A" / "B 队 Team B",按首字符精确匹配,避免 "B 队 TEAM B" 中的 "A" 误判
            name_upper = (t["name"] or "").strip().upper()
            is_a = name_upper.startswith("A ") or name_upper.startswith("A队") or "蓝" in name_upper
            if is_a and not team_a_ids:
                team_a_ids = pids
            elif (not is_a) and not team_b_ids:
                team_b_ids = pids
            if team_a_ids and team_b_ids:
                break
        conn.close()
        return team_a_ids, team_b_ids

    async def _do_pull(self, interaction, uids, channel_id, team_label):
        channel = self.guild.get_channel(channel_id)
        if not channel:
            return [f"⚠️ 语音频道未找到 ({team_label}队)"]
        moved = []
        not_in = []
        for uid in uids:
            member = self.guild.get_member(int(uid))
            if member and member.voice and member.voice.channel:
                try:
                    await member.move_to(channel)
                    moved.append(member)
                except Exception:
                    not_in.append(member.mention if member else f"<@{uid}>")
            else:
                not_in.append(member.mention if member else f"<@{uid}>")
        lines = []
        if moved:
            lines.append(f"✅ {team_label}队已拉入:{' '.join(m.mention for m in moved)}")
        if not_in:
            lines.append(f"⚠️ {team_label}队未在语音频道(无法拉入):{' '.join(not_in)}")
        return lines

    @discord.ui.button(label="🔵 拉 A 队入语音", style=discord.ButtonStyle.primary, emoji="📢", row=2)
    async def pull_voice_a_btn(self, interaction: discord.Interaction, button):
        if self._voice_used_a:
            return await interaction.response.send_message("A队已经拉过了!", ephemeral=True)
        team_a_ids, team_b_ids = self._resolve_team_ids()
        uid = str(interaction.user.id)
        if not interaction.user.guild_permissions.administrator and uid not in team_a_ids and uid not in team_b_ids:
            return await interaction.response.send_message("仅参赛者或管理员可操作", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        lines = await self._do_pull(interaction, team_a_ids, POST_MATCH_VC_TEAM_B, "A")
        notify_channel = self.guild.get_channel(POST_MATCH_VC_TEAM_A)
        if notify_channel and lines:
            try:
                await notify_channel.send("\n".join(lines))
            except Exception as e:
                log_error("dashboard", "pull_voice_a_btn", e)
        button.disabled = True
        self._voice_used_a = True
        await interaction.edit_original_response(view=self)
        await interaction.followup.send("A 队拉入完成!", ephemeral=True)

    @discord.ui.button(label="🔴 拉 B 队入语音", style=discord.ButtonStyle.primary, emoji="📢", row=2)
    async def pull_voice_b_btn(self, interaction: discord.Interaction, button):
        if self._voice_used_b:
            return await interaction.response.send_message("B队已经拉过了!", ephemeral=True)
        team_a_ids, team_b_ids = self._resolve_team_ids()
        uid = str(interaction.user.id)
        if not interaction.user.guild_permissions.administrator and uid not in team_a_ids and uid not in team_b_ids:
            return await interaction.response.send_message("仅参赛者或管理员可操作", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        lines = await self._do_pull(interaction, team_b_ids, 1437626921394372658, "B")
        notify_channel = self.guild.get_channel(POST_MATCH_VC_TEAM_A)
        if notify_channel and lines:
            try:
                await notify_channel.send("\n".join(lines))
            except Exception as e:
                log_error("dashboard", "pull_voice_b_btn", e)
        button.disabled = True
        self._voice_used_b = True
        await interaction.edit_original_response(view=self)
        await interaction.followup.send("B 队拉入完成!", ephemeral=True)


class RematchView(discord.ui.View):
    """赛后重赛/结束按钮。"""

    def __init__(self, match_id: int, guild: discord.Guild, match_name: str, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.match_id = match_id
        self.guild = guild
        self.match_name = match_name

    @discord.ui.button(label="🔄 重赛 Rematch", style=discord.ButtonStyle.primary, row=0)
    async def rematch_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        try:
            conn = get_db(); cur = conn.cursor()
            # Reset status to open, clear team assignments
            cur.execute("UPDATE tournaments SET status='open' WHERE id=?", (self.match_id,))
            cur.execute("UPDATE registrations SET team_id=NULL WHERE tournament_id=?", (self.match_id,))
            cur.execute("DELETE FROM teams WHERE tournament_id=?", (self.match_id,))
            conn.commit(); conn.close()

            for child in self.children:
                child.disabled = True
            await interaction.edit_original_response(view=self)
            await interaction.channel.send(
                f"🔄 **{self.match_name}** 重赛已开启！/ Rematch started!\n使用 `/gmpt-register {self.match_id}` 重新报名 / Use `/gmpt-register {self.match_id}` to re-register."
            )
        except Exception as e:
            logger.error(f"RematchView.rematch_btn failed: {e}", exc_info=True)
            await interaction.followup.send("❌ 重赛失败，请重试 / Rematch failed, please try again.", ephemeral=True)

    @discord.ui.button(label="📊 查看战绩 View Stats", style=discord.ButtonStyle.secondary, row=0)
    async def stats_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        try:
            conn = get_db(); cur = conn.cursor()

            # Match info
            cur.execute("SELECT name, status FROM tournaments WHERE id=?", (self.match_id,))
            match = cur.fetchone()
            if not match:
                conn.close()
                return await interaction.followup.send("比赛不存在 / Match not found.", ephemeral=True)

            # Teams and results
            cur.execute(
                "SELECT t.id, t.name, r.rank, r.score_awarded FROM teams t "
                "LEFT JOIN results r ON r.team_id=t.id AND r.tournament_id=? "
                "WHERE t.tournament_id=? ORDER BY t.id",
                (self.match_id, self.match_id),
            )
            teams = cur.fetchall()

            # Build embed
            embed = discord.Embed(
                title=f"📊 {match['name']} 战绩 / Match Stats",
                color=discord.Color.gold(),
            )
            embed.add_field(name="状态 / Status", value=match["status"], inline=False)

            total_players = 0
            for t in teams:
                cur.execute(
                    "SELECT discord_id FROM registrations WHERE team_id=? AND tournament_id=?",
                    (t["id"], self.match_id),
                )
                players = cur.fetchall()
                total_players += len(players)
                player_mentions = "\n".join(f"<@{p['discord_id']}>" for p in players) if players else "（无人 / Empty）"
                rank_str = {1: "🥇 胜方 Winner", 2: "🥈 负方 Loser"}.get(t["rank"], f"Rank {t['rank']}") if t["rank"] else "未记录 / No result"
                score_str = f" (+{t['score_awarded']} coin)" if t["score_awarded"] else ""
                embed.add_field(
                    name=f"{t['name']} — {rank_str}{score_str}",
                    value=player_mentions,
                    inline=False,
                )
            conn.close()

            embed.set_footer(text=f"比赛 ID: {self.match_id} | 总参赛: {total_players} 人")
            button.disabled = True
            await interaction.edit_original_response(view=self)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"RematchView.stats_btn failed: {e}", exc_info=True)
            await interaction.followup.send("❌ 查询失败，请重试 / Query failed, please try again.", ephemeral=True)

    @discord.ui.button(label="❌ 结束 End", style=discord.ButtonStyle.secondary, row=0)
    async def end_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        try:
            for child in self.children:
                child.disabled = True
            await interaction.edit_original_response(view=self)
            await interaction.channel.send(f"GG! **{self.match_name}** 比赛结束 / Match ended. Well played!")
        except Exception as e:
            logger.error(f"RematchView.end_btn failed: {e}", exc_info=True)
            await interaction.followup.send("❌ 操作失败，请重试 / Failed, please try again.", ephemeral=True)


class VoicePullView(discord.ui.View):
    """赛前/赛后语音频道管理。从 A/B 队语音频道拉人。"""

    TEAM_A_VC_ID = POST_MATCH_VC_TEAM_B
    TEAM_B_VC_ID = 1437626921394372658
    LIVE_ROOM_ID = 1442412877301416006
    NOTIFY_CHANNEL_ID = POST_MATCH_VC_TEAM_A

    def __init__(self, team_a_ids: list, team_b_ids: list, guild: discord.Guild, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.team_a_ids = list(team_a_ids)
        self.team_b_ids = list(team_b_ids)
        self.guild = guild
        self._used_a = False
        self._used_b = False
        self._used_live = False

    @classmethod
    def from_match(cls, match_id: int, guild: discord.Guild, timeout: float = 300):
        """从数据库查询 match 的 A/B 队成员创建 VoicePullView。"""
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id, name FROM teams WHERE tournament_id=? ORDER BY id DESC", (match_id,))
        teams = cur.fetchall()
        team_a_ids = []
        team_b_ids = []
        for t in teams:
            cur.execute(
                "SELECT discord_id FROM registrations WHERE team_id=? AND (is_sub IS NULL OR is_sub=0)",
                (t["id"],),
            )
            pids = [r["discord_id"] for r in cur.fetchall()]
            if not pids:
                continue
            # 名称为 "A 队 Team A" / "B 队 Team B",按首字符精确匹配,避免 "B 队 TEAM B" 中的 "A" 误判
            name_upper = (t["name"] or "").strip().upper()
            is_a = name_upper.startswith("A ") or name_upper.startswith("A队") or "蓝" in name_upper
            if is_a and not team_a_ids:
                team_a_ids = pids
            elif (not is_a) and not team_b_ids:
                team_b_ids = pids
            if team_a_ids and team_b_ids:
                break
        conn.close()
        return cls(team_a_ids, team_b_ids, guild, timeout)

    async def _do_pull_from_vc(self, interaction, source_vc_id, target_vc_id, label):
        """从 source_vc_id 语音频道拉所有在线成员到 target_vc_id,返回通知行。"""
        source_channel = self.guild.get_channel(source_vc_id)
        if not source_channel:
            return [f"⚠️ {label}队语音频道未找到 (ID:{source_vc_id})"]

        target_channel = self.guild.get_channel(target_vc_id)
        if not target_channel:
            return [f"⚠️ 目标语音频道未找到 ({label}队, ID:{target_vc_id})"]

        moved = []
        not_in = []
        for member in source_channel.members:
            if member.voice and member.voice.channel:
                try:
                    await member.move_to(target_channel)
                    moved.append(member)
                except Exception:
                    not_in.append(member.mention)
            else:
                not_in.append(member.mention)

        lines = []
        if moved:
            lines.append(f"✅ {label}队已拉入 Live Room: {' '.join(m.mention for m in moved)}")
        if not_in:
            lines.append(f"⚠️ {label}队无法拉入: {' '.join(not_in)}")
        return lines

    async def _notify(self, lines):
        """发送通知到 NOTIFY_CHANNEL_ID。"""
        if not lines:
            return
        notify_channel = self.guild.get_channel(self.NOTIFY_CHANNEL_ID)
        if notify_channel:
            try:
                await notify_channel.send("\n".join(lines))
            except Exception as e:
                log_error("dashboard", "VoicePullView._notify", e)

    @discord.ui.button(label="🔵 拉 A 队入语音", style=discord.ButtonStyle.primary, row=0)
    async def pull_a_btn(self, interaction: discord.Interaction, button):
        if self._used_a:
            return await interaction.response.send_message("A队已经拉过了!", ephemeral=True)
        uid = str(interaction.user.id)
        if not interaction.user.guild_permissions.administrator and uid not in self.team_a_ids and uid not in self.team_b_ids:
            return await interaction.response.send_message("仅参赛者或管理员可操作", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        lines = await self._do_pull_from_vc(interaction, self.TEAM_A_VC_ID, self.LIVE_ROOM_ID, "A")
        await self._notify(lines)
        button.disabled = True
        self._used_a = True
        await interaction.edit_original_response(view=self)
        await interaction.followup.send("A 队拉入完成!", ephemeral=True)

    @discord.ui.button(label="🔴 拉 B 队入语音", style=discord.ButtonStyle.primary, row=0)
    async def pull_b_btn(self, interaction: discord.Interaction, button):
        if self._used_b:
            return await interaction.response.send_message("B队已经拉过了!", ephemeral=True)
        uid = str(interaction.user.id)
        if not interaction.user.guild_permissions.administrator and uid not in self.team_a_ids and uid not in self.team_b_ids:
            return await interaction.response.send_message("仅参赛者或管理员可操作", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        lines = await self._do_pull_from_vc(interaction, self.TEAM_B_VC_ID, self.LIVE_ROOM_ID, "B")
        await self._notify(lines)
        button.disabled = True
        self._used_b = True
        await interaction.edit_original_response(view=self)
        await interaction.followup.send("B 队拉入完成!", ephemeral=True)

    @discord.ui.button(label="🏠 回大厅 Return to Live Room", style=discord.ButtonStyle.success, row=1)
    async def pull_live_btn(self, interaction: discord.Interaction, button):
        if self._used_live:
            return await interaction.response.send_message("已经拉过了!", ephemeral=True)
        uid = str(interaction.user.id)
        if not interaction.user.guild_permissions.administrator and uid not in self.team_a_ids and uid not in self.team_b_ids:
            return await interaction.response.send_message("仅参赛者或管理员可操作", ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        lines_a = await self._do_pull_from_vc(interaction, self.TEAM_A_VC_ID, self.LIVE_ROOM_ID, "A+B")
        lines_b = await self._do_pull_from_vc(interaction, self.TEAM_B_VC_ID, self.LIVE_ROOM_ID, "A+B")
        await self._notify(lines_a + lines_b)

        button.disabled = True
        self._used_live = True
        await interaction.edit_original_response(view=self)
        await interaction.followup.send("全员拉入 Live Room 完成!", ephemeral=True)


class KillReportView(discord.ui.View):
    """赛后击杀上报按钮 — 选手可上报击杀/死亡事件用于回放。"""

    def __init__(self, match_id, guild):
        super().__init__(timeout=600)
        self.match_id = match_id
        self.guild = guild

    async def _record_event(self, interaction: discord.Interaction, event_type: str, target_id: str = None):
        uid = str(interaction.user.id)
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO match_events (tournament_id, event_type, actor_id, target_id) VALUES (?, ?, ?, ?)",
                (self.match_id, event_type, uid, target_id),
            )
            conn.commit()
        finally:
            conn.close()

        label = {"kill": "击杀", "death": "阵亡", "assist": "助攻"}.get(event_type, event_type)
        await interaction.response.send_message(
            f"✅ {interaction.user.mention} 上报了 **{label}** 事件!", ephemeral=True
        )

    @discord.ui.button(label="⚔️ 我击杀了", style=discord.ButtonStyle.danger, row=0)
    async def kill_btn(self, interaction: discord.Interaction, button):
        # Show user select for target
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT discord_id FROM registrations WHERE tournament_id=?",
                (self.match_id,),
            )
            players = [r["discord_id"] for r in cur.fetchall()]
        finally:
            conn.close()

        if not players:
            return await interaction.response.send_message("没有参赛玩家 / No players found.", ephemeral=True)

        options = []
        for pid in players:
            if pid == str(interaction.user.id):
                continue
            member = self.guild.get_member(int(pid))
            name = member.display_name if member else pid
            options.append(discord.SelectOption(label=name[:100], value=pid))

        if not options:
            return await interaction.response.send_message("没有可选目标 / No targets available.", ephemeral=True)

        class KillTargetSelect(discord.ui.Select):
            def __init__(self):
                super().__init__(placeholder="选择被击杀的玩家 / Select kill target...", options=options[:25])

            async def callback(self, sel_int: discord.Interaction):
                target = self.values[0]
                await self.view._record_event(sel_int, "kill", target)

        view = discord.ui.View(timeout=60)
        view.add_item(KillTargetSelect())
        view._record_event = self._record_event
        await interaction.response.send_message("选择击杀目标:", view=view, ephemeral=True)

    @discord.ui.button(label="💀 我阵亡了", style=discord.ButtonStyle.secondary, row=0)
    async def death_btn(self, interaction: discord.Interaction, button):
        await self._record_event(interaction, "death")

    @discord.ui.button(label="🤝 助攻", style=discord.ButtonStyle.primary, row=0)
    async def assist_btn(self, interaction: discord.Interaction, button):
        await self._record_event(interaction, "assist")


class PostMatchPullView(discord.ui.View):
    """赛后统一拉入按钮 — 将 A/B 两队语音频道中所有人拉入赛后集合频道。"""

    VA_CHANNEL_ID = POST_MATCH_VC_TEAM_B
    VB_CHANNEL_ID = 1437626921394372658
    POST_MATCH_VC_ID = 1442412877301416006
    NOTIFY_CHANNEL_ID = POST_MATCH_VC_TEAM_A

    def __init__(self, guild: discord.Guild, timeout: float = 600):
        super().__init__(timeout=timeout)
        self.guild = guild

    @discord.ui.button(label="拉入赛后频道", style=discord.ButtonStyle.success, emoji="📢", row=0)
    async def pull_post_match(self, interaction: discord.Interaction, button):
        # Permission check: admins only (no match context available for participant check)
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message(
                "❌ 只有管理员才能使用此功能", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)

        target_vc = self.guild.get_channel(self.POST_MATCH_VC_ID)
        if not target_vc:
            return await interaction.followup.send("⚠️ 赛后集合频道未找到 / Post-match VC not found", ephemeral=True)

        notify_channel = self.guild.get_channel(self.NOTIFY_CHANNEL_ID)
        results = []

        for vc_id, label in [(self.VA_CHANNEL_ID, "A"), (self.VB_CHANNEL_ID, "B")]:
            vc = self.guild.get_channel(vc_id)
            if not vc:
                results.append(f"⚠️ {label}队语音频道未找到")
                continue

            moved = []
            not_in = []
            for member in vc.members:
                try:
                    await member.move_to(target_vc)
                    moved.append(member)
                except Exception:
                    not_in.append(member.mention)

            if moved:
                results.append(f"✅ {label}队已拉入赛后频道:{' '.join(m.mention for m in moved)}")
            if not_in:
                results.append(f"⚠️ {label}队无法拉入:{' '.join(not_in)}")
            if not moved and not not_in:
                results.append(f"ℹ️ {label}队语音频道为空")

        lines = "\n".join(results)
        await interaction.followup.send(lines, ephemeral=True)

        if notify_channel and results:
            try:
                await notify_channel.send(f"📢 赛后集合 — {interaction.user.mention} 将队员拉入赛后频道\n{lines}")
            except Exception as e:
                log_error("dashboard", "pull_post_match", e)


class ManualTeamView(discord.ui.View):
    """管理员手动将每个玩家分配到 A/B 队(自己分队)。"""

    def __init__(self, src_match_id, match_name, player_ids, guild, team_size, created_by, timeout=300):
        super().__init__(timeout=timeout)
        self.src_match_id = src_match_id
        self.match_name = match_name
        self.guild = guild
        self.team_size = team_size
        self.created_by = created_by
        self.all_player_ids = list(player_ids)
        self.team_a = []
        self.team_b = []
        self.selected_player = None
        self._processing = False  # anti-spam
        self._rebuild_select()

    def _get_unassigned(self):
        return [pid for pid in self.all_player_ids if pid not in self.team_a and pid not in self.team_b]

    def _rebuild_select(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)

        unassigned = self._get_unassigned()
        options = []
        for pid in unassigned:
            label = resolve_name(self.guild, pid)
            options.append(discord.SelectOption(label=label[:25], value=pid))

        if not options:
            options.append(discord.SelectOption(label="(无待分配玩家 / No players)", value="__none__"))

        select = discord.ui.Select(
            placeholder="选择玩家 / Select a player...",
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
        self.selected_player = val
        name = resolve_name(self.guild, val)
        await interaction.followup.send(f"已选择 / Selected: {name},点击加入 A 队或 B 队", ephemeral=True)

    @discord.ui.button(label="加入 A 队 / A", style=discord.ButtonStyle.primary, emoji="🔵", row=1)
    async def add_to_a(self, interaction: discord.Interaction, button):
        try:
            if not getattr(self, "selected_player", None):
                return await interaction.response.send_message(
                    "请先从下拉菜单选择一个玩家 / Select a player first.", ephemeral=True,
                )
            if len(self.team_a) >= self.team_size:
                return await interaction.response.send_message(
                    f"A 队已满 (上限 {self.team_size}) / Team A full.", ephemeral=True,
                )
            if self.selected_player in self.team_a or self.selected_player in self.team_b:
                return await interaction.response.send_message(
                    "该玩家已分配 / Already assigned.", ephemeral=True,
                )
            self.team_a.append(self.selected_player)
            self.selected_player = None
            self._rebuild_select()
            await interaction.response.defer()
            await interaction.edit_original_response(embed=self._build_embed(), view=self)
        except Exception as e:
            logger.error(f"[TeamAssignView] add_to_a error: {e}", exc_info=True)
            try:
                await interaction.followup.send("操作失败 / Failed, please try again.", ephemeral=True)
            except Exception as e:
                log_error("dashboard", "add_to_a", e)

    @discord.ui.button(label="加入 B 队 / B", style=discord.ButtonStyle.danger, emoji="🔴", row=1)
    async def add_to_b(self, interaction: discord.Interaction, button):
        try:
            if not getattr(self, "selected_player", None):
                return await interaction.response.send_message(
                    "请先从下拉菜单选择一个玩家 / Select a player first.", ephemeral=True,
                )
            if len(self.team_b) >= self.team_size:
                return await interaction.response.send_message(
                    f"B 队已满 (上限 {self.team_size}) / Team B full.", ephemeral=True,
                )
            if self.selected_player in self.team_a or self.selected_player in self.team_b:
                return await interaction.response.send_message(
                    "该玩家已分配 / Already assigned.", ephemeral=True,
                )
            self.team_b.append(self.selected_player)
            self.selected_player = None
            self._rebuild_select()
            await interaction.response.defer()
            await interaction.edit_original_response(embed=self._build_embed(), view=self)
        except Exception as e:
            logger.error(f"[TeamAssignView] add_to_b error: {e}", exc_info=True)
            try:
                await interaction.followup.send("操作失败 / Failed, please try again.", ephemeral=True)
            except Exception as e:
                log_error("dashboard", "add_to_b", e)

    @discord.ui.button(label="清空 / Clear", style=discord.ButtonStyle.secondary, emoji="🔄", row=2)
    async def clear_teams(self, interaction: discord.Interaction, button):
        try:
            await interaction.response.defer(ephemeral=True)
            self.team_a.clear()
            self.team_b.clear()
            self.selected_player = None
            self._rebuild_select()
            await interaction.response.defer()
            await interaction.edit_original_response(embed=self._build_embed(), view=self)
        except Exception as e:
            logger.error(f"[TeamAssignView] clear error: {e}", exc_info=True)

    @discord.ui.button(label="确认分队 / Confirm", style=discord.ButtonStyle.success, emoji="✅", row=2)
    async def confirm_teams(self, interaction: discord.Interaction, button):
        total = len(self.team_a) + len(self.team_b)
        all_players = len(self.all_player_ids)
        if total < min(2, all_players):
            return await interaction.response.send_message(
                "请至少分配 2 名玩家到队伍中 / Assign at least 2 players.", ephemeral=True,
            )
        await interaction.response.defer()

        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO tournaments (name, max_teams, team_size, created_by, status) VALUES (?, 2, ?, ?, 'open')",
            (self.match_name, self.team_size, self.created_by),
        )
        conn.commit()
        new_mid = cur.lastrowid

        for pid in self.all_player_ids:
            cur.execute("INSERT INTO registrations (tournament_id, discord_id) VALUES (?,?)", (new_mid, pid))
            cur.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (pid, "unknown"))

        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (new_mid, "A 队 Team A"))
        aid = cur.lastrowid
        for uid in self.team_a:
            cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?",
                        (aid, new_mid, uid))
        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (new_mid, "B 队 Team B"))
        bid = cur.lastrowid
        for uid in self.team_b:
            cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?",
                        (bid, new_mid, uid))
        cur.execute("UPDATE tournaments SET status='closed' WHERE id=?", (new_mid,))
        conn.commit(); conn.close()

        a_mentions = [f"<@{uid}>" for uid in self.team_a]
        b_mentions = [f"<@{uid}>" for uid in self.team_b]

        for child in self.children:
            child.disabled = True

        embed = self._build_embed()
        embed.title = f"✋ 手动分队完成 — {self.match_name}"
        embed.description = (
            f"🔵 **A 队 Team A** (ID:{aid}): {' '.join(a_mentions)}\n"
            f"🔴 **B 队 Team B** (ID:{bid}): {' '.join(b_mentions)}\n\n"
            f"Match ID: {new_mid}\n"
            f"Settle: `/gmpt-lol-settle {new_mid} <win_team_id>`"
        )
        embed.color = discord.Color.green()
        await interaction.edit_original_response(embed=embed, view=self)
        try:
            voice_view = VoicePullView(self.team_a, self.team_b, self.guild)
            await interaction.followup.send("📢 点击按钮将玩家拉入对应语音频道:", view=voice_view)
        except Exception as e:
            log_error("dashboard", "confirm_teams", e)
        await VoteView.send_vote(match_id=new_mid, match_name=self.match_name, channel=interaction.channel)

    def _build_embed(self):
        embed = discord.Embed(
            title=f"手动分队 — {self.match_name}",
            color=discord.Color.blue(),
        )
        a_names = []
        for uid in self.team_a:
            m = self.guild.get_member(int(uid))
            a_names.append(m.display_name if m else f"<@{uid}>")
        b_names = []
        for uid in self.team_b:
            m = self.guild.get_member(int(uid))
            b_names.append(m.display_name if m else f"<@{uid}>")

        unassigned = self._get_unassigned()
        un_names = []
        for uid in unassigned:
            m = self.guild.get_member(int(uid))
            un_names.append(m.display_name if m else f"<@{uid}>")

        if a_names:
            embed.add_field(name=f"🔵 A 队 / Team A ({len(self.team_a)}/{self.team_size})", value="\n".join(a_names), inline=True)
        if b_names:
            embed.add_field(name=f"🔴 B 队 / Team B ({len(self.team_b)}/{self.team_size})", value="\n".join(b_names), inline=True)
        if not a_names and not b_names:
            embed.description = "尚未分配任何玩家 / No players assigned yet."

        if un_names:
            embed.add_field(
                name=f"待分配 / Unassigned ({len(un_names)})",
                value="\n".join(un_names[:10]) + (f"\n... +{len(un_names)-10} more" if len(un_names) > 10 else ""),
                inline=False,
            )
        return embed


class CaptainDraftView(discord.ui.View):
    """队长分队:先选 2 名队长,再轮流选人(draft 模式)。"""

    def __init__(self, src_match_id, match_name, player_ids, guild, team_size, created_by, timeout=300):
        super().__init__(timeout=timeout)
        self.src_match_id = src_match_id
        self.match_name = match_name
        self.guild = guild
        self.team_size = team_size
        self.created_by = created_by
        self.all_player_ids = list(player_ids)
        self.captain_a = None
        self.captain_b = None
        self.team_a = []
        self.team_b = []
        self.turn = "A"  # whose turn to pick
        self._build_captain_select()

    def _get_unassigned(self):
        return [pid for pid in self.all_player_ids
                if pid not in self.team_a and pid not in self.team_b
                and pid != self.captain_a and pid != self.captain_b]

    def _build_captain_select(self):
        for child in list(self.children):
            self.remove_item(child)

        options = []
        for pid in self.all_player_ids:
            label = resolve_name(self.guild, pid)
            options.append(discord.SelectOption(label=label[:25], value=pid))

        select = discord.ui.Select(
            placeholder="选择 2 名队长 / Select 2 captains...",
            options=options[:25],
            min_values=2,
            max_values=2,
            row=0,
        )
        select.callback = self.captain_select_callback
        self.add_item(select)

    async def captain_select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        vals = interaction.data["values"]
        if len(vals) != 2:
            return await interaction.followup.send("请选择恰好 2 名队长 / Select exactly 2 captains.", ephemeral=True)
        self.captain_a, self.captain_b = vals[0], vals[1]
        self.team_a = [self.captain_a]
        self.team_b = [self.captain_b]
        self.turn = "A"
        self._build_draft_view()
        await interaction.edit_original_response(
            content=f"**队长分队 / Captain Draft** — {self.match_name}\n队长已选定,开始轮流选人!",
            embed=self._build_embed(),
            view=self,
        )

    def _build_draft_view(self):
        for child in list(self.children):
            self.remove_item(child)

        unassigned = self._get_unassigned()
        options = []
        for pid in unassigned:
            label = resolve_name(self.guild, pid)
            options.append(discord.SelectOption(label=label[:25], value=pid))

        if not options:
            options.append(discord.SelectOption(label="(无待选玩家 / No players)", value="__none__"))

        select = discord.ui.Select(
            placeholder=f"轮到 {'🔵 A队' if self.turn == 'A' else '🔴 B队'} 选人 / {self.turn} picks...",
            options=options[:25],
            row=0,
        )
        select.callback = self.draft_pick_callback
        self.add_item(select)

        # Show current turn indicator
        turn_btn = discord.ui.Button(
            label=f"当前: {'🔵 A队' if self.turn == 'A' else '🔴 B队'}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=1,
        )
        self.add_item(turn_btn)

    async def draft_pick_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        val = interaction.data["values"][0]
        if val == "__none__":
            return
        if self.turn == "A":
            self.team_a.append(val)
            self.turn = "B"
        else:
            self.team_b.append(val)
            self.turn = "A"

        if not self._get_unassigned():
            # All picked — show confirm
            self._build_confirm_view()
            await interaction.edit_original_response(
                content=f"**队长分队 / Captain Draft** — {self.match_name}\n所有玩家已选完,确认分队!",
                embed=self._build_embed(),
                view=self,
            )
        else:
            self._build_draft_view()
            await interaction.edit_original_response(embed=self._build_embed(), view=self)

    def _build_confirm_view(self):
        for child in list(self.children):
            self.remove_item(child)
        confirm = discord.ui.Button(label="确认分队 / Confirm", style=discord.ButtonStyle.success, emoji="✅", row=0)
        confirm.callback = self.confirm_draft
        self.add_item(confirm)

        cancel = discord.ui.Button(label="重选队长 / Reset", style=discord.ButtonStyle.secondary, emoji="🔄", row=0)
        cancel.callback = self.reset_draft
        self.add_item(cancel)

    async def reset_draft(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.captain_a = None
        self.captain_b = None
        self.team_a = []
        self.team_b = []
        self.turn = "A"
        self._build_captain_select()
        await interaction.edit_original_response(
            content=f"**队长分队 / Captain Draft** — {self.match_name}\n第一步:选择 2 名队长",
            embed=None,
            view=self,
        )

    async def confirm_draft(self, interaction: discord.Interaction, button=None):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO tournaments (name, max_teams, team_size, created_by, status) VALUES (?, 2, ?, ?, 'open')",
            (self.match_name, self.team_size, self.created_by),
        )
        conn.commit()
        new_mid = cur.lastrowid

        for pid in self.all_player_ids:
            cur.execute("INSERT INTO registrations (tournament_id, discord_id) VALUES (?,?)", (new_mid, pid))
            cur.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (pid, "unknown"))

        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (new_mid, "A 队 Team A"))
        aid = cur.lastrowid
        for uid in self.team_a:
            cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?",
                        (aid, new_mid, uid))
        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (new_mid, "B 队 Team B"))
        bid = cur.lastrowid
        for uid in self.team_b:
            cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?",
                        (bid, new_mid, uid))
        cur.execute("UPDATE tournaments SET status='closed' WHERE id=?", (new_mid,))
        conn.commit(); conn.close()

        a_mentions = [f"<@{uid}>" for uid in self.team_a]
        b_mentions = [f"<@{uid}>" for uid in self.team_b]

        for child in self.children:
            child.disabled = True

        embed = discord.Embed(
            title=f"👑 队长分队完成 — {self.match_name}",
            description=(
                f"🔵 **A 队 Team A** (ID:{aid}, 队长 <@{self.captain_a}>): {' '.join(a_mentions)}\n"
                f"🔴 **B 队 Team B** (ID:{bid}, 队长 <@{self.captain_b}>): {' '.join(b_mentions)}\n\n"
                f"Match ID: {new_mid}\n"
                f"Settle: `/gmpt-lol-settle {new_mid} <win_team_id>`"
            ),
            color=discord.Color.green(),
        )
        await interaction.edit_original_response(embed=embed, view=self)
        try:
            voice_view = VoicePullView(self.team_a, self.team_b, self.guild)
            await interaction.followup.send("📢 点击按钮将玩家拉入对应语音频道:", view=voice_view)
        except Exception as e:
            log_error("dashboard", "confirm_draft", e)
        await VoteView.send_vote(match_id=new_mid, match_name=self.match_name, channel=interaction.channel)

    def _build_embed(self):
        embed = discord.Embed(
            title=f"队长分队 — {self.match_name}",
            color=discord.Color.gold(),
        )
        a_names = []
        for uid in self.team_a:
            m = self.guild.get_member(int(uid))
            prefix = "👑 " if uid == self.captain_a else ""
            a_names.append(prefix + (m.display_name if m else f"<@{uid}>"))
        b_names = []
        for uid in self.team_b:
            m = self.guild.get_member(int(uid))
            prefix = "👑 " if uid == self.captain_b else ""
            b_names.append(prefix + (m.display_name if m else f"<@{uid}>"))

        unassigned = self._get_unassigned()
        un_names = []
        for uid in unassigned:
            m = self.guild.get_member(int(uid))
            un_names.append(m.display_name if m else f"<@{uid}>")

        if a_names:
            embed.add_field(name=f"🔵 A 队 / Team A ({len(self.team_a)}/{self.team_size})", value="\n".join(a_names), inline=True)
        if b_names:
            embed.add_field(name=f"🔴 B 队 / Team B ({len(self.team_b)}/{self.team_size})", value="\n".join(b_names), inline=True)
        if un_names:
            embed.add_field(
                name=f"待选 / Remaining ({len(un_names)})",
                value="\n".join(un_names[:10]) + (f"\n... +{len(un_names)-10} more" if len(un_names) > 10 else ""),
                inline=False,
            )
        if self.captain_a and self.captain_b:
            embed.set_footer(text=f"当前轮到: {'🔵 A队' if self.turn == 'A' else '🔴 B队'}")
        return embed



class BetModal(discord.ui.Modal, title="下注 / Place Bet"):
    """Modal for placing coin bets on a team."""
    def __init__(self, match_id: int, team_id: int, guild: discord.Guild):
        super().__init__(timeout=300)
        self.match_id = match_id
        self.team_id = team_id
        self.guild = guild

    amount = discord.ui.TextInput(
        label="下注金额 / Bet Amount (coins)",
        placeholder="1-500",
        min_length=1,
        max_length=5,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value.strip())
        except ValueError:
            return await interaction.response.send_message("请输入有效数字 / Enter a valid number.", ephemeral=True)

        if amount < 1 or amount > 500:
            return await interaction.response.send_message("金额需在 1-500 之间 / Amount must be 1-500.", ephemeral=True)

        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()

        cur.execute("SELECT score FROM users WHERE discord_id=?", (uid,))
        row = cur.fetchone()
        balance = row["score"] if row else 0
        if balance < amount:
            conn.close()
            return await interaction.response.send_message(
                f"余额不足 / Insufficient balance. You have {balance} coins.",
                ephemeral=True,
            )

        cur.execute("UPDATE users SET score=score-? WHERE discord_id=?", (amount, uid))
        cur.execute(
            "INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
            (uid, -amount, f"Bet on match #{self.match_id} team #{self.team_id}"),
        )
        cur.execute(
            "INSERT OR REPLACE INTO active_bets (match_id, discord_id, team_id, amount) VALUES (?,?,?,?)",
            (self.match_id, uid, self.team_id, amount),
        )
        conn.commit()
        conn.close()

        await interaction.response.send_message(
            f"已下注 {amount} coins! / Bet placed: {amount} coins on team #{self.team_id}",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error):
        logger.error(f"[BetModal] error: {error}", exc_info=True)
        await interaction.response.send_message("下注失败 / Bet failed.", ephemeral=True)

class MatchViewWithID(discord.ui.View):
    """
    持久化比赛视图:通过 message_id → DB 反查 match_id,Bot 重启后按钮仍可响应。
    不存实例状态,所有数据通过 interaction.message.id 实时从 DB 查询。
    """
    def __init__(self):
        super().__init__(timeout=None)

    async def _get_context(self, interaction: discord.Interaction):
        """从 interaction.message.id 反查 match 和 tournament 数据,返回 (match_id, t, guild)。"""
        mid = get_match_id_from_message(interaction.message.id)
        if not mid:
            return (None, None, interaction.guild)
        t = get_match_row(mid)
        return (mid, t, interaction.guild)

    async def _get_betting_stats(self, match_id: int):
        """Return (a_count, a_total, b_count, b_total) for betting display."""
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id FROM teams WHERE tournament_id=? ORDER BY id ASC", (match_id,))
        team_ids = [r["id"] for r in cur.fetchall()]
        cur.execute(
            "SELECT team_id, COUNT(*) as cnt, SUM(amount) as total FROM active_bets WHERE match_id=? GROUP BY team_id",
            (match_id,),
        )
        rows = {r["team_id"]: (r["cnt"], r["total"] or 0) for r in cur.fetchall()}
        conn.close()
        a_id = team_ids[0] if len(team_ids) > 0 else None
        b_id = team_ids[1] if len(team_ids) > 1 else None
        a_cnt, a_total = rows.get(a_id, (0, 0))
        b_cnt, b_total = rows.get(b_id, (0, 0))
        return a_cnt, a_total, b_cnt, b_total

    # ── 辅助:更新报名列表 ──
    async def _refresh_list(self, interaction: discord.Interaction, match_id: int):
        old_msg_id = _player_list_msgs.get(match_id)
        if old_msg_id:
            try:
                old_msg = await interaction.channel.fetch_message(old_msg_id)
                await old_msg.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT discord_id, is_sub, lane FROM registrations WHERE tournament_id=? ORDER BY is_sub ASC, id ASC", (match_id,))
        rows = cur.fetchall()
        cur.execute("SELECT max_teams, team_size, role_pick FROM tournaments WHERE id=?", (match_id,))
        t = cur.fetchone()
        conn.close()
        max_p = (t["max_teams"] * t["team_size"]) if t else 0
        is_role_pick = t["role_pick"] if t else 0

        if is_role_pick:
            # 选路比赛:按路线分组显示
            LANES = ["Top", "JG", "Mid", "ADC", "Sup"]
            lane_players = {lane: [] for lane in LANES}
            sub_names = []
            main_count = 0
            for r in rows:
                name = resolve_name(interaction.guild, r["discord_id"])
                if r["is_sub"]:
                    sub_names.append(name)
                else:
                    lane = r["lane"] or "未选 / None"
                    if lane in lane_players:
                        lane_players[lane].append(name)
                    else:
                        lane_players[lane] = [name]
                    main_count += 1

            count = main_count
            desc_parts = ["🎯 路线分配 / Lane Distribution"]
            for lane in LANES:
                players = lane_players[lane]
                names_line = ", ".join(players) if players else "-"
                desc_parts.append(f"{lane}:    {names_line}    ({len(players)}/2)")
            desc_parts.append("")
            desc_parts.append(f"总计 / Total: {count}/{max_p}")
            if sub_names:
                desc_parts.append("")
                desc_parts.append("**替补 / Substitutes:**")
                desc_parts.append(", ".join(sub_names))
            desc = "\n".join(desc_parts)
            color = discord.Color.purple()
        else:
            main_names = []
            sub_names = []
            for r in rows:
                name = resolve_name(interaction.guild, r["discord_id"])
                if r["is_sub"]:
                    sub_names.append(name)
                else:
                    main_names.append(name)

            count = len(main_names)
            desc_parts = []
            if main_names:
                desc_parts.append("\n".join(f"{i+1}. {n}" for i, n in enumerate(main_names)))
            else:
                desc_parts.append("暂无玩家 / No signups yet")
            if sub_names:
                desc_parts.append("")
                desc_parts.append("**替补 / Substitutes:**")
                desc_parts.append("\n".join(f"S{i+1}. {n}" for i, n in enumerate(sub_names)))
            desc = "\n".join(desc_parts)
            color = discord.Color.green()

        embed = discord.Embed(
            title=f"已报名玩家 / Signed Up ({count}/{max_p})" + (f" + {len(sub_names)} 替补" if sub_names else ""),
            description=desc,
            color=color,
        )
        new_msg = await interaction.channel.send(embed=embed)
        _player_list_msgs[match_id] = new_msg.id
        # Also persist player_list_msg_id in DB
        # 优先用 match_id 反查 panel message_id,避免非面板交互时写错记录
        conn2 = get_db(); cur2 = conn2.cursor()
        cur2.execute("SELECT message_id FROM match_view_state WHERE match_id=?", (match_id,))
        panel_row = cur2.fetchone()
        panel_msg_id = panel_row["message_id"] if panel_row else str(interaction.message.id)
        cur2.execute(
            "UPDATE match_view_state SET player_list_msg_id=? WHERE message_id=?",
            (str(new_msg.id), panel_msg_id),
        )
        conn2.commit(); conn2.close()

    @discord.ui.button(label="报名 Sign Up", style=discord.ButtonStyle.success, emoji="✋", row=0, custom_id="matchv2_signup")
    async def signup_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        try:
            mid, t, guild = await self._get_context(interaction)
            if not t or t["status"] != "open":
                return await interaction.followup.send("报名已关闭或比赛不存在 / Signup closed or match not found.", ephemeral=True)

            max_p = t["max_teams"] * t["team_size"]
            conn = get_db(); cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as cnt FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0)", (mid,))
            cnt = cur.fetchone()["cnt"]
            if cnt >= max_p:
                conn.close()
                return await interaction.followup.send("报名已满 / Signup full.", ephemeral=True)

            uid = str(interaction.user.id)
            cur.execute("SELECT id FROM registrations WHERE tournament_id=? AND discord_id=?", (mid, uid))
            if cur.fetchone():
                conn.close()
                return await interaction.followup.send("你已经报过名了 / Already signed up.", ephemeral=True)

            # 选路比赛:弹出路线选择
            if t["role_pick"]:
                conn.close()
                LANES = ["Top", "JG", "Mid", "ADC", "Sup"]
                lane_counts = {}
                lane_conn = get_db(); lane_cur = lane_conn.cursor()
                for lane in LANES:
                    lane_cur.execute(
                        "SELECT COUNT(*) as cnt FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0) AND lane=?",
                        (mid, lane),
                    )
                    lane_counts[lane] = lane_cur.fetchone()["cnt"]
                lane_conn.close()

                lane_options = []
                for lane in LANES:
                    full = lane_counts[lane] >= 2
                    lane_options.append(discord.SelectOption(
                        label=lane,
                        value=lane,
                        description=f"{lane_counts[lane]}/2" + (" (已满)" if full else ""),
                    ))

                lane_select = discord.ui.Select(
                    placeholder="选择你的路线 / Pick your lane...",
                    options=lane_options,
                )

                async def lane_callback(lane_interaction: discord.Interaction):
                    chosen_lane = lane_interaction.data["values"][0]
                    lconn = get_db(); lcur = lconn.cursor()
                    # 重新检查名额
                    lcur.execute(
                        "SELECT COUNT(*) as cnt FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0) AND lane=?",
                        (mid, chosen_lane),
                    )
                    if lcur.fetchone()["cnt"] >= 2:
                        lconn.close()
                        return await lane_interaction.response.send_message(
                            f"该路线已满 / Lane {chosen_lane} is full. 请重新选择 / Please pick another lane.", ephemeral=True
                        )
                    # 检查重复报名
                    lcur.execute("SELECT id FROM registrations WHERE tournament_id=? AND discord_id=?", (mid, uid))
                    if lcur.fetchone():
                        lconn.close()
                        return await lane_interaction.response.send_message("已报名 / Already signed up.", ephemeral=True)
                    try:
                        lcur.execute(
                            "INSERT INTO registrations (tournament_id, discord_id, lane) VALUES (?,?,?)",
                            (mid, uid, chosen_lane),
                        )
                        lcur.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (uid, lane_interaction.user.name))
                        lconn.commit()
                    except Exception as e:
                        lconn.close()
                        return await lane_interaction.response.send_message("报名失败 / Signup failed.", ephemeral=True)
                    lconn.close()
                    await self._refresh_list(lane_interaction, mid)
                    await lane_interaction.response.send_message(
                        f"✅ {lane_interaction.user.mention} 报名成功! Signed up! ({chosen_lane})", ephemeral=True
                    )

                lane_select.callback = lane_callback
                lane_view = discord.ui.View(timeout=60)
                lane_view.add_item(lane_select)
                return await interaction.followup.send(
                    f"请选择你的路线 / Pick your lane for **{t['name']}**:", view=lane_view, ephemeral=True
                )

            cur.execute("INSERT INTO registrations (tournament_id, discord_id) VALUES (?,?)", (mid, uid))
            cur.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (uid, interaction.user.name))
            conn.commit(); conn.close()
            await interaction.followup.send(
                f"✅ {interaction.user.mention} 报名成功! Signed up! ({cnt+1}/{max_p})", ephemeral=True
            )
            await self._refresh_list(interaction, mid)

        except Exception as e:
            logger.error(f"[MatchView] signup error: {e}", exc_info=True)
            await interaction.followup.send("报名失败 / Signup failed, please try again.", ephemeral=True)

    @discord.ui.button(label="查看已报名 / List", style=discord.ButtonStyle.secondary, emoji="📋", row=0, custom_id="matchv2_view")
    async def view_signups_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        try:
            mid, t, guild = await self._get_context(interaction)
            if not mid:
                return await interaction.followup.send("比赛不存在 / Match not found.", ephemeral=True)

            conn = get_db(); cur = conn.cursor()
            cur.execute("SELECT discord_id, is_sub FROM registrations WHERE tournament_id=? ORDER BY is_sub ASC, id ASC", (mid,))
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return await interaction.followup.send("暂无玩家报名 / No signups yet.", ephemeral=True)

            main_names = []
            sub_names = []
            for r in rows:
                name = resolve_name(guild, r["discord_id"])
                if r["is_sub"]:
                    sub_names.append(name)
                else:
                    main_names.append(name)

            text = "\n".join(f"{i+1}. {n}" for i, n in enumerate(main_names))
            if sub_names:
                text += f"\n\n**替补 / Substitutes:**\n" + "\n".join(f"S{i+1}. {n}" for i, n in enumerate(sub_names))
            await interaction.followup.send(
                f"**已报名玩家 / Signed up ({len(main_names)}人):**\n{text}", ephemeral=True
            )
        except Exception as e:
            logger.error(f"[MatchView] view error: {e}", exc_info=True)
            await interaction.followup.send("查询失败 / Query failed.", ephemeral=True)

    @discord.ui.button(label="替补", style=discord.ButtonStyle.primary, emoji="📋", row=0, custom_id="matchv2_sub_signup")
    async def sub_signup_btn(self, interaction: discord.Interaction, button):
        """任何玩家点击直接以 is_sub=1 报名。"""
        await interaction.response.defer(ephemeral=True)
        try:
            mid, t, guild = await self._get_context(interaction)
            if not t or t["status"] != "open":
                return await interaction.followup.send("报名已关闭或比赛不存在 / Signup closed or match not found.", ephemeral=True)

            uid = str(interaction.user.id)
            conn = get_db(); cur = conn.cursor()
            cur.execute("SELECT id, is_sub FROM registrations WHERE tournament_id=? AND discord_id=?", (mid, uid))
            existing = cur.fetchone()
            if existing:
                conn.close()
                if existing["is_sub"]:
                    return await interaction.followup.send("你已经是替补了 / Already a substitute.", ephemeral=True)
                else:
                    return await interaction.followup.send("你已经报名正选了 / Already signed up as main player.", ephemeral=True)

            cur.execute("INSERT INTO registrations (tournament_id, discord_id, is_sub) VALUES (?,?,1)", (mid, uid))
            cur.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (uid, interaction.user.name))
            conn.commit(); conn.close()
            await interaction.followup.send("✅ 已报名替补 / Signed up as substitute!", ephemeral=True)
            await self._refresh_list(interaction, mid)
        except Exception as e:
            logger.error(f"[MatchView] sub signup error: {e}", exc_info=True)
            await interaction.followup.send("替补报名失败 / Sub signup failed.", ephemeral=True)

    @discord.ui.button(label="结算 Settle", style=discord.ButtonStyle.danger, emoji="💰", row=1, custom_id="matchv2_settle")
    async def settle_btn(self, interaction: discord.Interaction, button):
        """Settle button on match message — select winner + optional MVP → confirm → distribute coins."""
        await interaction.response.defer(ephemeral=True)
        try:
            mid, t, guild = await self._get_context(interaction)
            if not t:
                return await interaction.followup.send("比赛不存在 / Match not found.", ephemeral=True)
            if t["status"] == "finished":
                return await interaction.followup.send("已结算 / Already settled.", ephemeral=True)
            if t["status"] != "closed":
                return await interaction.followup.send("比赛尚未开始 / Match not started yet.", ephemeral=True)

            conn = get_db(); cur = conn.cursor()
            cur.execute("SELECT id, name FROM teams WHERE tournament_id=?", (mid,))
            teams = cur.fetchall()
            conn.close()

            if len(teams) < 2:
                return await interaction.followup.send("未找到两支队伍 / Two teams not found.", ephemeral=True)

            team_options = []
            for tm in teams:
                team_options.append(discord.SelectOption(label=tm["name"][:100], value=str(tm["id"])))

            win_select = discord.ui.Select(
                placeholder="选择获胜队伍 / Select winning team...",
                options=team_options,
            )

            class SettleFlow:
                def __init__(self):
                    self.win_team_id = None
                    self.mvp_id = None

            flow = SettleFlow()

            async def win_callback(sel_int: discord.Interaction):
                flow.win_team_id = int(sel_int.data["values"][0])

                conn2 = get_db(); cur2 = conn2.cursor()
                cur2.execute("SELECT discord_id FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0)", (mid,))
                players = cur2.fetchall()
                conn2.close()

                mvp_options = [discord.SelectOption(label="无 MVP / Skip", value="__none__")]
                for p in players:
                    name = resolve_name(guild, p["discord_id"])
                    mvp_options.append(discord.SelectOption(label=name[:100], value=p["discord_id"]))

                mvp_select = discord.ui.Select(
                    placeholder="选择 MVP (可选) / Select MVP...",
                    options=mvp_options[:25],
                )

                async def mvp_callback(mvp_int: discord.Interaction):
                    val = mvp_int.data["values"][0]
                    if val != "__none__":
                        flow.mvp_id = val

                    conn3 = get_db(); cur3 = conn3.cursor()
                    win_name = cur3.execute("SELECT name FROM teams WHERE id=?", (flow.win_team_id,)).fetchone()
                    cur3.execute("SELECT name FROM teams WHERE tournament_id=? AND id!=?", (mid, flow.win_team_id))
                    lose_row = cur3.fetchone()
                    conn3.close()
                    win_name = win_name["name"] if win_name else "胜方"
                    lose_name = lose_row["name"] if lose_row else "败方"

                    mvp_text = ""
                    if flow.mvp_id:
                        mvp_member = guild.get_member(int(flow.mvp_id))
                        mvp_text = f"\n🏅 MVP: {mvp_member.mention if mvp_member else flow.mvp_id}"

                    # AI MVP recommendation
                    conn_ai = get_db(); cur_ai = conn_ai.cursor()
                    cur_ai.execute(
                        "SELECT r.discord_id FROM registrations r WHERE r.tournament_id=? AND r.team_id=? AND (r.is_sub IS NULL OR r.is_sub=0)",
                        (mid, flow.win_team_id),
                    )
                    win_players = [r["discord_id"] for r in cur_ai.fetchall()]
                    ai_mvp_id = None; highest_mmr = 0
                    for pid in win_players:
                        cur_ai.execute("SELECT mmr FROM mmr WHERE discord_id=?", (pid,))
                        row = cur_ai.fetchone()
                        if row and row["mmr"] > highest_mmr:
                            highest_mmr = row["mmr"]
                            ai_mvp_id = pid
                    conn_ai.close()
                    ai_mvp_text = ""
                    if ai_mvp_id:
                        ai_member = guild.get_member(int(ai_mvp_id))
                        ai_mvp_text = f"\n🤖 AI推荐MVP: {ai_member.mention if ai_member else f'<@{ai_mvp_id}>'} (MMR:{highest_mmr})"

                    embed = discord.Embed(
                        title="确认结算 / Confirm Settle",
                        description=(
                            f"Match: **{t['name']}** (ID:{mid})\n"
                            f"🏆 胜方 Winner: **{win_name}**\n"
                            f"💔 败方 Loser: **{lose_name}**"
                            f"{mvp_text}"
                            f"{ai_mvp_text}\n\n"
                            f"胜方 +150 / 败方 +50 / MVP +50\n"
                            f"Click Confirm to proceed / 点击确认执行"
                        ),
                        color=discord.Color.orange(),
                    )
                    confirm_view = ConfirmView(timeout=60)
                    await mvp_int.response.send_message(embed=embed, view=confirm_view, ephemeral=True)
                    await confirm_view.wait()

                    if confirm_view.value is None or not confirm_view.value:
                        return await mvp_int.edit_original_response(
                            content="结算已取消 / Settle cancelled.", embed=None, view=None
                        )

                    analysis_embed = await _execute_settle(
                        match_id=mid,
                        win_team_id=flow.win_team_id,
                        mvp_id=flow.mvp_id,
                        guild=guild,
                        match_name=t["name"],
                        bot=interaction.client,
                    )

                    await mvp_int.edit_original_response(
                        content="✅ 结算完成! / Settle complete!", embed=None, view=None
                    )

                    await _post_settle_actions(mid, t["name"], guild, interaction.channel, analysis_embed, interaction.client)

                mvp_select.callback = mvp_callback
                mvp_view = discord.ui.View(timeout=120)
                mvp_view.add_item(mvp_select)
                await sel_int.response.send_message(
                    "选择本场 MVP (可选 / Optional):", view=mvp_view, ephemeral=True
                )

            win_select.callback = win_callback
            win_view = discord.ui.View(timeout=120)
            win_view.add_item(win_select)
            await interaction.followup.send(
                "选择获胜队伍 / Select winning team:", view=win_view, ephemeral=True
            )

        except Exception as e:
            logger.error(f"[MatchView] settle error: {e}", exc_info=True)
            try:
                await interaction.followup.send("结算失败 / Settle failed.", ephemeral=True)
            except Exception as e:
                log_error("dashboard", "mvp_callback", e)

    @discord.ui.button(label="退出 Leave", style=discord.ButtonStyle.danger, emoji="🚪", row=1, custom_id="matchv2_leave")
    async def leave_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        try:
            mid, t, guild = await self._get_context(interaction)
            if not t or t["status"] != "open":
                return await interaction.followup.send("报名已关闭或比赛不存在 / Signup closed or match not found.", ephemeral=True)

            conn = get_db(); cur = conn.cursor()
            uid = str(interaction.user.id)
            cur.execute("SELECT id FROM registrations WHERE tournament_id=? AND discord_id=?", (mid, uid))
            if not cur.fetchone():
                conn.close()
                return await interaction.followup.send("你未报名 / You are not signed up.", ephemeral=True)
            conn.close()

            # Confirmation before leaving
            confirm_view = ConfirmView(timeout=60)
            await interaction.followup.send(
                f"确认退出比赛? / Confirm leave match **{t['name']}**?",
                view=confirm_view,
                ephemeral=True,
            )
            await confirm_view.wait()
            if confirm_view.value is None or not confirm_view.value:
                return await interaction.edit_original_response(
                    content="已取消 / Cancelled.", view=None
                )

            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute("DELETE FROM registrations WHERE tournament_id=? AND discord_id=?", (mid, uid))
            conn2.commit(); conn2.close()
            await interaction.edit_original_response(
                content=f"🚪 {interaction.user.mention} 已退赛 / Left the match.", view=None
            )
            await self._refresh_list(interaction, mid)
        except Exception as e:
            logger.error(f"[MatchView] leave error: {e}", exc_info=True)
            await interaction.followup.send("退赛失败 / Leave failed, please try again.", ephemeral=True)

    @discord.ui.button(label="下注 A队", style=discord.ButtonStyle.primary, emoji="🔵", row=3, custom_id="matchv2_bet_a")
    async def bet_a_btn(self, interaction: discord.Interaction, button):
        mid, t, guild = await self._get_context(interaction)
        if not mid:
            return await interaction.response.send_message("比赛不存在", ephemeral=True)
        if not t or t["status"] not in ("active", "closed"):
            return await interaction.response.send_message("下注已关闭", ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id FROM teams WHERE tournament_id=? ORDER BY id ASC LIMIT 1", (mid,))
        ta = cur.fetchone(); conn.close()
        if not ta:
            return await interaction.response.send_message("A队不存在", ephemeral=True)
        await interaction.response.send_modal(BetModal(mid, ta["id"], guild))

    @discord.ui.button(label="下注 B队", style=discord.ButtonStyle.danger, emoji="🔴", row=3, custom_id="matchv2_bet_b")
    async def bet_b_btn(self, interaction: discord.Interaction, button):
        mid, t, guild = await self._get_context(interaction)
        if not mid:
            return await interaction.response.send_message("比赛不存在", ephemeral=True)
        if not t or t["status"] not in ("active", "closed"):
            return await interaction.response.send_message("下注已关闭", ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id FROM teams WHERE tournament_id=? ORDER BY id ASC LIMIT 1 OFFSET 1", (mid,))
        tb = cur.fetchone(); conn.close()
        if not tb:
            return await interaction.response.send_message("B队不存在", ephemeral=True)
        await interaction.response.send_modal(BetModal(mid, tb["id"], guild))

    @discord.ui.button(label="踢出 Kick", style=discord.ButtonStyle.danger, emoji="👢", row=1, custom_id="matchv2_kick")
    async def kick_btn(self, interaction: discord.Interaction, button):
        """Admin-only: select a player or sub to kick from the match."""
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("管理员专用 / Admin only.", ephemeral=True)

        mid, t, guild = await self._get_context(interaction)
        if not t:
            return await interaction.response.send_message("比赛不存在 / Match not found.", ephemeral=True)
        if t["status"] != "open":
            return await interaction.response.send_message("报名已关闭 / Signup closed.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # Get all registrations
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT discord_id, is_sub FROM registrations WHERE tournament_id=? ORDER BY id ASC", (mid,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return await interaction.followup.send("无人可踢 / No one to kick.", ephemeral=True)

        # Build UserSelect
        user_select = discord.ui.UserSelect(
            placeholder="选择要踢出的用户 / Select users to kick...",
            min_values=1,
            max_values=1,
        )

        async def kick_select_callback(sel_int: discord.Interaction):
            await sel_int.response.defer(ephemeral=True)
            member = user_select.values[0]
            uid = str(member.id)

            # Check if user is registered
            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute("SELECT id FROM registrations WHERE tournament_id=? AND discord_id=?", (mid, uid))
            if not cur2.fetchone():
                conn2.close()
                return await sel_int.followup.send(
                    f"{member.display_name} 未报名 / Not signed up.", ephemeral=True
                )

            # Confirmation
            confirm_view = ConfirmView(timeout=60)
            await sel_int.followup.send(
                f"确认踢出 {member.mention}? / Confirm kick?",
                view=confirm_view,
                ephemeral=True,
            )
            await confirm_view.wait()
            if confirm_view.value is None or not confirm_view.value:
                conn2.close()
                return await sel_int.edit_original_response(
                    content="已取消 / Cancelled.", view=None
                )

            cur2.execute("DELETE FROM registrations WHERE tournament_id=? AND discord_id=?", (mid, uid))
            for attempt in range(3):
                try:
                    conn2.commit()
                    break
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower() and attempt < 2:
                        time_mod.sleep(0.2 * (attempt + 1))
                        continue
                    raise
            conn2.close()
            await sel_int.edit_original_response(
                content=f"👢 已踢出 {member.mention} / Kicked.",
                view=None,
            )
            await self._refresh_list(sel_int, mid)

        user_select.callback = kick_select_callback
        kview = discord.ui.View(timeout=60)
        kview.add_item(user_select)
        await interaction.followup.send(
            "选择要踢出的玩家 / Select player to kick:",
            view=kview,
            ephemeral=True,
        )

    @discord.ui.button(label="🔄 重新分队", style=discord.ButtonStyle.secondary, emoji="🎲", row=2, custom_id="matchv2_reshuffle")
    async def reshuffle_btn(self, interaction: discord.Interaction, button):
        """Re-shuffle existing registered players into new teams (in-place)."""
        await interaction.response.defer(ephemeral=True)
        try:
            mid, t, guild = await self._get_context(interaction)
            if not t:
                return await interaction.followup.send("比赛不存在 / Match not found.", ephemeral=True)
        except Exception:
            return await interaction.followup.send("无法获取比赛信息 / Unable to fetch match.", ephemeral=True)

        uid = str(interaction.user.id)

        # Permission: must be a non-sub participant or admin
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM registrations WHERE tournament_id=? AND discord_id=? AND (is_sub IS NULL OR is_sub=0)",
            (mid, uid),
        )
        is_participant = cur.fetchone() is not None
        conn.close()
        if not interaction.user.guild_permissions.administrator and not is_participant:
            return await interaction.followup.send("仅参赛者或管理员可操作", ephemeral=True)

        # Get all non-sub players
        conn2 = get_db(); cur2 = conn2.cursor()
        cur2.execute(
            "SELECT discord_id FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0)",
            (mid,),
        )
        players = [r["discord_id"] for r in cur2.fetchall()]
        if len(players) < 2:
            conn2.close()
            return await interaction.followup.send("参赛人数不足 (至少2人) / Not enough players (min 2).", ephemeral=True)

        if len(players) % 2 != 0:
            players = players[:-1]

        import random as _random
        _random.shuffle(players)
        split = len(players) // 2
        ta, tb = players[:split], players[split:]

        cur2.execute("DELETE FROM teams WHERE tournament_id=?", (mid,))
        cur2.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (mid, "A 队 Team A"))
        aid = cur2.lastrowid
        for u in ta:
            cur2.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?", (aid, mid, u))
        cur2.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (mid, "B 队 Team B"))
        bid = cur2.lastrowid
        for u in tb:
            cur2.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?", (bid, mid, u))
        for attempt in range(3):
            try:
                conn2.commit()
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < 2:
                    time_mod.sleep(0.2 * (attempt + 1))
                    continue
                raise
        conn2.close()

        match_name = t["name"]

        a_mentions = [f"<@{uid}>" for uid in ta]
        b_mentions = [f"<@{uid}>" for uid in tb]
        embed = discord.Embed(
            title=f"🔄 重新分队 — {match_name}",
            description=(
                f"🔵 **A 队 Team A** (ID:{aid}): {' '.join(a_mentions)}\n"
                f"🔴 **B 队 Team B** (ID:{bid}): {' '.join(b_mentions)}\n\n"
                f"Match ID: {mid}\n"
                f"Settle: `/gmpt-lol-settle {mid} <win_team_id>`"
            ),
            color=discord.Color.gold(),
        )
        await interaction.channel.send(embed=embed)

        # Send voice pull view
        try:
            voice_view = VoicePullView(ta, tb, guild)
            await interaction.channel.send("📢 点击按钮将玩家拉入对应语音频道:", view=voice_view)
        except Exception as e:
            log_error("dashboard", "reshuffle_btn", e)

        # Send vote view
        await VoteView.send_vote(match_id=mid, match_name=match_name, channel=interaction.channel)

        await interaction.followup.send("重新分队完成!", ephemeral=True)

    @discord.ui.button(label="管理员加人", style=discord.ButtonStyle.primary, emoji="➕", row=2, custom_id="matchv2_admin_add")
    async def admin_add_btn(self, interaction: discord.Interaction, button):
        """Admin-only: batch add players or substitutes via UserSelect + type dropdown."""
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("管理员专用 / Admin only.", ephemeral=True)

        mid, t, guild = await self._get_context(interaction)
        if not t:
            return await interaction.response.send_message("比赛不存在 / Match not found.", ephemeral=True)
        if t["status"] != "open":
            return await interaction.response.send_message("报名已关闭 / Signup closed.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # Step 1: UserSelect for multi-select
        user_select = discord.ui.UserSelect(
            placeholder="选择要添加的用户 / Select users to add...",
            min_values=1,
            max_values=25,
        )

        async def user_select_callback(sel_int: discord.Interaction):
            await sel_int.response.defer(ephemeral=True)
            selected_members = list(user_select.values)

            # Step 2: dropdown for player/sub choice
            type_select = discord.ui.Select(
                placeholder="选择类型 / Select type...",
                options=[
                    discord.SelectOption(label="玩家 / Player", value="player",
                                         description="占用正式名额 / Counts toward capacity"),
                    discord.SelectOption(label="替补 / Substitute", value="sub",
                                         description="不占名额 / Does not count toward capacity"),
                ],
            )

            async def type_select_callback(type_int: discord.Interaction):
                await type_int.response.defer(ephemeral=True)
                is_sub = type_int.data["values"][0] == "sub"
                added = []
                skipped = []
                full_skipped = []

                conn = get_db(); cur = conn.cursor()

                # Re-check match status
                cur.execute("SELECT * FROM tournaments WHERE id=?", (mid,))
                t2 = cur.fetchone()
                if not t2 or t2["status"] != "open":
                    conn.close()
                    return await type_int.followup.send("报名已关闭 / Signup closed.", ephemeral=True)

                max_p = t2["max_teams"] * t2["team_size"]

                for member in selected_members:
                    uid = str(member.id)
                    cur.execute("SELECT id FROM registrations WHERE tournament_id=? AND discord_id=?", (mid, uid))
                    if cur.fetchone():
                        skipped.append(member.display_name)
                        continue

                    if not is_sub:
                        cur.execute(
                            "SELECT COUNT(*) as cnt FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0)",
                            (mid,),
                        )
                        cnt = cur.fetchone()["cnt"]
                        if cnt >= max_p:
                            full_skipped.append(member.display_name)
                            continue

                    cur.execute(
                        "INSERT INTO registrations (tournament_id, discord_id, is_sub) VALUES (?,?,?)",
                        (mid, uid, 1 if is_sub else 0),
                    )
                    cur.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (uid, member.name))
                    added.append(member.display_name)

                conn.commit(); conn.close()

                msg = []
                role = "替补" if is_sub else "玩家"
                if added:
                    msg.append(f"✅ 已添加 {len(added)} 名{role}: {', '.join(added)}")
                if skipped:
                    msg.append(f"⏭️ 已跳过 (重复): {', '.join(skipped)}")
                if full_skipped:
                    msg.append(f"🚫 已跳过 (名额已满): {', '.join(full_skipped)}")
                await type_int.followup.send("\n".join(msg) or "无操作", ephemeral=True)

                await self._refresh_list(type_int, mid)

            type_select.callback = type_select_callback
            tview = discord.ui.View(timeout=60)
            tview.add_item(type_select)
            await sel_int.followup.send(
                f"已选择 {len(selected_members)} 人。请选择添加类型 / Select type:",
                view=tview,
                ephemeral=True,
            )

        user_select.callback = user_select_callback
        view = discord.ui.View(timeout=120)
        view.add_item(user_select)
        await interaction.followup.send("选择要添加的用户 / Select users to add:", view=view, ephemeral=True)

    @discord.ui.button(label="开始比赛 Start", style=discord.ButtonStyle.success, emoji="▶️", row=2, custom_id="matchv2_start")
    async def start_btn(self, interaction: discord.Interaction, button):
        """正式开赛：锁定报名，不能再报名或退出。"""
        mid, t, guild = await self._get_context(interaction)
        if not t:
            return await interaction.response.send_message("比赛不存在 / Match not found.", ephemeral=True)
        if t["status"] != "open":
            return await interaction.response.send_message("比赛已开始或已结束 / Match already started or finished.", ephemeral=True)
        if str(interaction.user.id) != t["created_by"] and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("仅创建者或管理员可操作 / Creator or admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE tournaments SET status='closed' WHERE id=?", (mid,))
            conn.commit()
        finally:
            conn.close()

        await interaction.followup.send(
            "▶️ **比赛已开始！报名已锁定。** / Match started! Signups are now locked.",
            ephemeral=True,
        )

        # 更新公开消息
        try:
            embeds = interaction.message.embeds
            if embeds:
                embed = embeds[0]
                embed.color = discord.Color.orange()
                embed.set_footer(text=embed.footer.text + " | 已开始/Started" if embed.footer.text else "已开始/Started")
                await interaction.message.edit(embed=embed)
        except Exception as e:
            log_error("dashboard", "message_edit", e)

        await self._refresh_list(interaction, mid)

    @discord.ui.button(label="拉入语音 Voice", style=discord.ButtonStyle.primary, emoji="🎙️", row=2, custom_id="matchv2_voice")
    async def voice_btn(self, interaction: discord.Interaction, button):
        """将参赛者拉入语音频道。"""
        mid, t, guild = await self._get_context(interaction)
        if not t:
            return await interaction.response.send_message("比赛不存在 / Match not found.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT discord_id, is_sub FROM registrations WHERE tournament_id=? ORDER BY is_sub ASC, id ASC", (mid,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return await interaction.followup.send("无人报名 / No one signed up.", ephemeral=True)

        view = PostMatchPullView(guild)
        await interaction.followup.send(
            "🎙️ **拉入语音 / Voice Pull**\n选择要将队员拉入的频道：",
            view=view,
            ephemeral=True,
        )

# =============================================================================
# LoL Vote View — 模式投票（ARAM / Summoner's Rift / TFT）
# =============================================================================
class LolVoteView(discord.ui.View):
    """Persistent view for LoL mode voting: ARAM / Summoner's Rift / TFT."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _get_session(self, message_id: int):
        """Look up vote session by message_id."""
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, channel_id, vote_date, status, winner_mode FROM lol_vote_sessions WHERE message_id=?",
            (str(message_id),),
        )
        row = cur.fetchone()
        conn.close()
        return row

    async def _record_vote(self, session_id: int, discord_id: str, mode: str):
        """Record or overwrite a vote (one vote per user per session)."""
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM lol_vote_results WHERE session_id=? AND discord_id=?",
            (session_id, discord_id),
        )
        cur.execute(
            "INSERT INTO lol_vote_results (session_id, discord_id, mode) VALUES (?,?,?)",
            (session_id, discord_id, mode),
        )
        conn.commit()
        conn.close()

    async def _update_embed(self, interaction: discord.Interaction, session):
        """Refresh embed with current vote counts."""
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT mode, COUNT(*) as cnt FROM lol_vote_results WHERE session_id=? GROUP BY mode",
            (session["id"],),
        )
        rows = cur.fetchall()
        conn.close()

        counts = {"ARAM": 0, "Summoner's Rift": 0, "TFT": 0, "URF": 0, "Arena": 0}
        for r in rows:
            mode_name = r["mode"]
            if mode_name in counts:
                counts[mode_name] = r["cnt"]

        sr_votes = counts.get("Summoner's Rift", 0)
        urf_votes = counts.get("URF", 0)
        arena_votes = counts.get("Arena", 0)
        embed = discord.Embed(
            title="🎮 今天玩什么？What to play today?",
            description=(
                f"📅 {session['vote_date']}\n\n"
                f"点击下方按钮投票，每人一票！Vote below, one per person!\n"
                f"下午 1:00 自动结算并创建比赛 🏆 Auto-settle at 1PM\n\n"
                f"🏹 ARAM 大乱斗: **{counts['ARAM']}** 票\n"
                f"⚔️ 召唤师峡谷 Summoner's Rift: **{sr_votes}** 票\n"
                f"🎯 TFT 云顶: **{counts['TFT']}** 票\n"
                f"🎪 无限火力 URF: **{urf_votes}** 票\n"
                f"👊 斗魂竞技场 Arena: **{arena_votes}** 票"
            ),
            color=discord.Color.gold(),
        )
        await interaction.message.edit(embed=embed)

    @discord.ui.button(label="🏹 ARAM 大乱斗", style=discord.ButtonStyle.primary, row=0, custom_id="lolvote_aram")
    async def vote_aram(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        session = await self._get_session(interaction.message.id)
        if not session:
            return await interaction.followup.send("投票会话不存在。", ephemeral=True)
        if session["status"] != "pending":
            return await interaction.followup.send("投票已结束。", ephemeral=True)
        await self._record_vote(session["id"], str(interaction.user.id), "ARAM")
        await self._update_embed(interaction, session)
        await interaction.followup.send("已投票 ARAM 大乱斗！Voted!", ephemeral=True)

    @discord.ui.button(label="⚔️ 召唤师峡谷 Summoner's Rift", style=discord.ButtonStyle.primary, row=0, custom_id="lolvote_sr")
    async def vote_sr(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        session = await self._get_session(interaction.message.id)
        if not session:
            return await interaction.followup.send("投票会话不存在。", ephemeral=True)
        if session["status"] != "pending":
            return await interaction.followup.send("投票已结束。", ephemeral=True)
        await self._record_vote(session["id"], str(interaction.user.id), "Summoner's Rift")
        await self._update_embed(interaction, session)
        await interaction.followup.send("已投票 召唤师峡谷 Summoner's Rift！Voted!", ephemeral=True)

    @discord.ui.button(label="🎯 TFT 云顶", style=discord.ButtonStyle.primary, row=0, custom_id="lolvote_tft")
    async def vote_tft(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        session = await self._get_session(interaction.message.id)
        if not session:
            return await interaction.followup.send("投票会话不存在。", ephemeral=True)
        if session["status"] != "pending":
            return await interaction.followup.send("投票已结束。", ephemeral=True)
        await self._record_vote(session["id"], str(interaction.user.id), "TFT")
        await self._update_embed(interaction, session)
        await interaction.followup.send("已投票 TFT 云顶！Voted!", ephemeral=True)

    @discord.ui.button(label="🎪 无限火力 URF", style=discord.ButtonStyle.primary, row=1, custom_id="lolvote_urf")
    async def vote_urf(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        session = await self._get_session(interaction.message.id)
        if not session:
            return await interaction.followup.send("投票会话不存在。Vote session not found.", ephemeral=True)
        if session["status"] != "pending":
            return await interaction.followup.send("投票已结束。Vote closed.", ephemeral=True)
        await self._record_vote(session["id"], str(interaction.user.id), "URF")
        await self._update_embed(interaction, session)
        await interaction.followup.send("已投票 无限火力 URF！Voted!", ephemeral=True)

    @discord.ui.button(label="👊 斗魂竞技场 Arena", style=discord.ButtonStyle.primary, row=1, custom_id="lolvote_arena")
    async def vote_arena(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        session = await self._get_session(interaction.message.id)
        if not session:
            return await interaction.followup.send("投票会话不存在。Vote session not found.", ephemeral=True)
        if session["status"] != "pending":
            return await interaction.followup.send("投票已结束。Vote closed.", ephemeral=True)
        await self._record_vote(session["id"], str(interaction.user.id), "Arena")
        await self._update_embed(interaction, session)
        await interaction.followup.send("已投票 斗魂竞技场 Arena！Voted!", ephemeral=True)

# ══════════ 向后兼容别名══════════
MatchView = MatchViewWithID


# =============================================================================
# MVP Vote View — 赛后 MVP 投票
# =============================================================================
class MvpVoteView(discord.ui.View):
    """赛后自动发送 MVP 投票,队员互投,5 分钟超时,得票最高 +10 MMR。"""

    def __init__(self, match_id: int, match_name: str, player_ids: list[str], guild: discord.Guild, timeout=300):
        super().__init__(timeout=timeout)
        self.match_id = match_id
        self.match_name = match_name
        self.guild = guild
        self.votes: dict[str, str] = {}  # voter_id -> voted_id
        self._message = None

        options = []
        for pid in player_ids:
            member = guild.get_member(int(pid))
            name = member.display_name if member else f"<@{pid}>"
            options.append(discord.SelectOption(label=name[:100], value=pid))

        self.select = discord.ui.Select(
            placeholder="选择本场 MVP / Select match MVP...",
            options=options[:25],
        )
        self.select.callback = self._select_callback
        self.add_item(self.select)

    async def _select_callback(self, interaction: discord.Interaction):
        voter_id = str(interaction.user.id)

        # Check voter is a participant
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id FROM registrations WHERE tournament_id=? AND discord_id=?",
            (self.match_id, voter_id),
        )
        if not cur.fetchone():
            conn.close()
            return await interaction.response.send_message(
                "只有参赛者可以投票 / Only participants can vote.", ephemeral=True,
            )
        conn.close()

        voted_id = interaction.data["values"][0]

        # Cannot vote for self
        if voted_id == voter_id:
            return await interaction.response.send_message(
                "不能投给自己 / Cannot vote for yourself.", ephemeral=True,
            )

        # Already voted
        if voter_id in self.votes:
            return await interaction.response.send_message(
                "你已投过票 / You already voted.", ephemeral=True,
            )

        self.votes[voter_id] = voted_id
        member = self.guild.get_member(int(voted_id))
        name = member.display_name if member else f"<@{voted_id}>"
        await interaction.response.send_message(
            f"✅ 你已投票给 **{name}** / Voted!", ephemeral=True,
        )

    async def on_timeout(self):
        """Voting ended — tally results and update MMR."""
        if not self._message:
            return

        # Tally votes
        tally: dict[str, int] = {}
        for _, voted_id in self.votes.items():
            tally[voted_id] = tally.get(voted_id, 0) + 1

        if not tally:
            try:
                await self._message.edit(content="⏰ MVP 投票结束 — 无人投票 / No votes cast.", view=None)
            except Exception as e:
                log_error("dashboard", "on_timeout", e)
            return

        max_votes = max(tally.values())
        winners = [pid for pid, cnt in tally.items() if cnt == max_votes]
        bonus = 10 if len(winners) == 1 else 5

        conn = get_db(); cur = conn.cursor()
        for pid in winners:
            cur.execute("UPDATE users SET mmr=mmr+? WHERE discord_id=?", (bonus, pid))
            cur.execute(
                "INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                (pid, 0, f"MVP投票获胜 #{self.match_id} +{bonus} MMR"),
            )
        conn.commit(); conn.close()

        w_names = []
        for pid in winners:
            m = self.guild.get_member(int(pid))
            w_names.append(m.display_name if m else f"<@{pid}>")

        result_lines = [f"🎖️ **MVP 投票结果 / Results:**"]
        for pid, cnt in sorted(tally.items(), key=lambda x: -x[1]):
            m = self.guild.get_member(int(pid))
            name = m.mention if m else f"<@{pid}>"
            result_lines.append(f"  {name} — **{cnt}** 票 / votes")

        result_lines.append("")
        if len(winners) == 1:
            result_lines.append(f"🏆 <@{winners[0]}> 获得 MVP!**+{bonus} MMR**")
        else:
            mentions = " ".join(f"<@{pid}>" for pid in winners)
            result_lines.append(f"🏆 平票! {mentions} 各 **+{bonus} MMR**")

        embed = discord.Embed(
            title=f"🎖️ MVP 投票结束 — {self.match_name}",
            description="\n".join(result_lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Match ID: {self.match_id} | 共 {len(self.votes)} 人投票")

        try:
            await self._message.edit(content="", embed=embed, view=None)
        except Exception as e:
            logger.error(f"[MvpVoteView] on_timeout edit error: {e}")

    @classmethod
    async def send_vote(cls, match_id: int, match_name: str, channel, guild):
        """发送 MVP 投票消息。"""
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT discord_id FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0)",
            (match_id,),
        )
        rows = cur.fetchall(); conn.close()
        player_ids = [r["discord_id"] for r in rows]

        if len(player_ids) < 2:
            return

        embed = discord.Embed(
            title=f"🏆 MVP 投票 — {match_name}",
            description=(
                f"参赛队员请投出你心中的 MVP!\n"
                f"Match participants, vote for the MVP!\n\n"
                f"得票最高 **+10 MMR** | 平票各 **+5 MMR**\n"
                f"5 分钟自动截止 / Auto-close in 5 min"
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Match ID: {match_id}")

        view = cls(match_id, match_name, player_ids, guild)
        view._message = await channel.send(embed=embed, view=view)


# =============================================================================
# Helper: execute settlement (coin distribution + achievements)
# =============================================================================
async def _execute_settle(match_id, win_team_id, mvp_id, guild, match_name, bot=None):
    """Distribute coins, record results, check achievements. Reused by both dashboard and MatchView."""
    from cogs.economy import check_achievement, MATCH_WIN_COINS, MATCH_PARTICIPATE_COINS

    conn = get_db(); cur = conn.cursor()

    # Winner +150
    cur.execute("SELECT discord_id FROM registrations WHERE tournament_id=? AND team_id=?", (match_id, win_team_id))
    winner_ids = [r["discord_id"] for r in cur.fetchall()]

    # Loser +50
    cur.execute("SELECT discord_id FROM registrations WHERE tournament_id=? AND team_id!=?", (match_id, win_team_id))
    loser_ids = [r["discord_id"] for r in cur.fetchall()]

    # Batch coin distribution: merge winner + loser + MVP into single batch ops
    all_coin_ops = []
    for wid in winner_ids:
        all_coin_ops.append((wid, MATCH_WIN_COINS, f"Match win #{match_id}"))
    for lid in loser_ids:
        all_coin_ops.append((lid, MATCH_PARTICIPATE_COINS, f"Match participation #{match_id}"))
    # MVP +50
    if mvp_id:
        all_coin_ops.append((mvp_id, MATCH_PARTICIPATE_COINS, f"MVP #{match_id}"))

    # Batch insert users (deduplicate by using set)
    all_ids = list(set([op[0] for op in all_coin_ops]))
    if all_ids:
        cur.executemany("INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING",
                        [(uid,) for uid in all_ids])
        cur.executemany("UPDATE users SET score=score+? WHERE discord_id=?", [(op[0], op[1]) for op in all_coin_ops])
        cur.executemany("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)", all_coin_ops)

    cur.execute("INSERT INTO results (tournament_id,team_id,rank,score_awarded) VALUES (?,?,1,?)", (match_id, win_team_id, MATCH_WIN_COINS))

    cur.execute("UPDATE tournaments SET status='finished' WHERE id=?", (match_id,))
    try:
        conn.commit()
    finally:
        conn.close()

    # Achievement checks — batch query to avoid N+1
    all_participants = winner_ids + loser_ids
    unique_pids = list(set(all_participants))
    if unique_pids:
        placeholders = ",".join("?" * len(unique_pids))
        conn2 = get_db(); cur2 = conn2.cursor()
        cur2.execute(
            f"SELECT discord_id, COUNT(*) as cnt FROM registrations WHERE discord_id IN ({placeholders}) GROUP BY discord_id",
            unique_pids,
        )
        cnt_map = {row["discord_id"]: row["cnt"] for row in cur2.fetchall()}
        conn2.close()
        for pid in unique_pids:
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

    if mvp_id:
        check_achievement(mvp_id, "MVP")

    # ── 道具效果处理 / Active Item Effects ──
    effect_msgs = []
    conn_eff = get_db(); cur_eff = conn_eff.cursor()
    all_pids = winner_ids + loser_ids

    # 查询所有参赛者的未消耗激活效果
    placeholders = ",".join("?" * len(all_pids))
    cur_eff.execute(
        f"SELECT id, user_id, effect_type FROM active_effects WHERE user_id IN ({placeholders}) AND consumed=0",
        all_pids,
    )
    active_map = {}  # user_id -> set of effect_types
    for row in cur_eff.fetchall():
        active_map.setdefault(row["user_id"], set()).add(row["effect_type"])

    # 双倍MMR:赢家
    double_mmr_ids = set()
    for wid in winner_ids:
        if "double_mmr" in active_map.get(wid, set()):
            double_mmr_ids.add(wid)
            cur_eff.execute("UPDATE active_effects SET consumed=1 WHERE user_id=? AND effect_type='double_mmr' AND consumed=0", (wid,))
            effect_msgs.append(f"⚡ <@{wid}> 双倍MMR生效! / Double MMR active!")

    # MMR保护:输家
    protect_ids = set()
    for lid in loser_ids:
        if "mmr_protect" in active_map.get(lid, set()):
            protect_ids.add(lid)
            cur_eff.execute("UPDATE active_effects SET consumed=1 WHERE user_id=? AND effect_type='mmr_protect' AND consumed=0", (lid,))
            effect_msgs.append(f"🛡️ <@{lid}> MMR保护生效! / MMR protected!")

    # 偷金币:赢家偷对手
    for wid in winner_ids:
        if "steal_coins" in active_map.get(wid, set()):
            cur_eff.execute("UPDATE active_effects SET consumed=1 WHERE user_id=? AND effect_type='steal_coins' AND consumed=0", (wid,))
            # 从每个对手偷 30 coins
            stolen_total = 0
            for lid in loser_ids:
                cur_eff.execute("UPDATE users SET score=MAX(0, score-30) WHERE discord_id=?", (lid,))
                stolen_total += 30
                cur_eff.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                                (lid, -30, f"Coin stolen by <@{wid}> in match #{match_id}"))
            cur_eff.execute("UPDATE users SET score=score+? WHERE discord_id=?", (stolen_total, wid))
            cur_eff.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                            (wid, stolen_total, f"Stole coins in match #{match_id}"))
            effect_msgs.append(f"🥷 <@{wid}> 偷了 {stolen_total} coins! / Stole {stolen_total} coins!")

    # 经验加成:+50% coins
    for pid in all_pids:
        if "xp_boost" in active_map.get(pid, set()):
            cur_eff.execute("UPDATE active_effects SET consumed=1 WHERE user_id=? AND effect_type='xp_boost' AND consumed=0", (pid,))
            bonus = 75 if pid in winner_ids else 25  # 150*0.5=75, 50*0.5=25
            cur_eff.execute("UPDATE users SET score=score+? WHERE discord_id=?", (bonus, pid))
            cur_eff.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                            (pid, bonus, f"XP Boost bonus in match #{match_id}"))
            effect_msgs.append(f"📈 <@{pid}> 经验加成 +{bonus} coins! / XP Boost +{bonus} coins!")

    conn_eff.commit(); conn_eff.close()

    # ── MMR 排位更新 ──
    _update_mmr(winner_ids, loser_ids, mvp_id, conn2=None, double_mmr_ids=double_mmr_ids, protect_ids=protect_ids)

    # ── 竞猜结算 / Vote Resolution ──
    vote_winners = _resolve_vote_bets(match_id, win_team_id)
    vote_text = ""
    if vote_winners:
        vote_text = f"\n\U0001f4ca 竞猜: {len(vote_winners)} 人猜对,各 +5 MMR"

    # ── 金币下注结算 / Betting Settlement ──
    try:
        from cogs.economy import settle_bets
        bet_lines = settle_bets(match_id, win_team_id)
    except Exception as e:
        logger.error(f"[_execute_settle] settle_bets error: {e}", exc_info=True)
        bet_lines = []

    # ── 刷新实时排行榜 ──
    if bot is not None:
        try:
            await _refresh_mmr_board(bot, guild)
        except Exception as e:
            logger.error(f"[_execute_settle] _refresh_mmr_board failed: {e}", exc_info=True)

    # ── AI 赛事分析 ──
    analysis_embed = _generate_match_analysis(match_id, match_name, winner_ids, loser_ids, mvp_id, guild)
    # Append vote results, betting, and item effects to analysis embed
    extra_lines = []
    if vote_text:
        extra_lines.append(vote_text.strip())
    if bet_lines:
        extra_lines.append("\n🎲 **金币下注 / Betting:**")
        extra_lines.extend(bet_lines)
    if effect_msgs:
        extra_lines.append("\n🎒 **道具效果 / Item Effects:**")
        extra_lines.extend(effect_msgs)
    if analysis_embed and extra_lines:
        analysis_embed.description = (analysis_embed.description or "") + "\n".join(extra_lines)
    return analysis_embed


class PostSettleView(discord.ui.View):
    """Consolidated post-settle actions as buttons in a single view."""
    def __init__(self, match_id: int, match_name: str, guild: discord.Guild, include_kill_report: bool = False):
        super().__init__(timeout=600)
        self.match_id = match_id
        self.match_name = match_name
        self.guild = guild
        self.include_kill_report = include_kill_report

    @discord.ui.button(label="MVP 投票", style=discord.ButtonStyle.primary, emoji="🏅", row=0)
    async def mvp_vote(self, interaction: discord.Interaction, button):
        try:
            await MvpVoteView.send_vote(
                match_id=self.match_id, match_name=self.match_name,
                channel=interaction.channel, guild=self.guild,
            )
            await interaction.response.send_message("MVP投票已开启 / MVP vote started!", ephemeral=True)
        except Exception as e:
            logger.error(f"[PostSettleView] mvp_vote error: {e}")
            await interaction.response.send_message("MVP投票失败 / MVP vote failed.", ephemeral=True)

    @discord.ui.button(label="重新分队", style=discord.ButtonStyle.secondary, emoji="🔄", row=0)
    async def reshuffle(self, interaction: discord.Interaction, button):
        try:
            reshuffle_view = ReShuffleView(match_id=self.match_id, guild=self.guild)
            reshuffle_embed = reshuffle_view._build_player_list_embed()
            await interaction.channel.send(embed=reshuffle_embed, view=reshuffle_view)
            await interaction.response.send_message("重新分队面板已发送 / Reshuffle panel sent!", ephemeral=True)
        except Exception as e:
            logger.error(f"[PostSettleView] reshuffle error: {e}")
            await interaction.response.send_message("重新分队失败 / Reshuffle failed.", ephemeral=True)

    @discord.ui.button(label="再来一局", style=discord.ButtonStyle.success, emoji="🔁", row=0)
    async def rematch(self, interaction: discord.Interaction, button):
        try:
            rematch_view = RematchView(match_id=self.match_id, guild=self.guild, match_name=self.match_name)
            await interaction.channel.send(
                content="比赛已结束！是否再来一局？ / Match finished! Rematch?",
                view=rematch_view,
            )
            await interaction.response.send_message("已发送 / Sent!", ephemeral=True)
        except Exception as e:
            logger.error(f"[PostSettleView] rematch error: {e}")
            await interaction.response.send_message("失败 / Failed.", ephemeral=True)

    @discord.ui.button(label="赛后拉语音", style=discord.ButtonStyle.secondary, emoji="🎙️", row=1)
    async def pull_vc(self, interaction: discord.Interaction, button):
        try:
            post_match_view = PostMatchPullView(guild=self.guild)
            await interaction.channel.send(
                content=f"📢 **{self.match_name}** 结算完成! 点击下方按钮将队员拉入赛后集合频道:",
                view=post_match_view,
            )
            await interaction.response.send_message("已发送 / Sent!", ephemeral=True)
        except Exception as e:
            logger.error(f"[PostSettleView] pull_vc error: {e}")
            await interaction.response.send_message("失败 / Failed.", ephemeral=True)

    @discord.ui.button(label="比赛回放", style=discord.ButtonStyle.primary, emoji="⚔️", row=1)
    async def kill_report(self, interaction: discord.Interaction, button):
        if not self.include_kill_report:
            return await interaction.response.send_message("此功能未启用 / This feature is disabled.", ephemeral=True)
        try:
            kill_report_view = KillReportView(match_id=self.match_id, guild=self.guild)
            await interaction.channel.send(
                content=f"⚔️ **{self.match_name}** 比赛回放 - 点击下方按钮上报击杀/死亡事件:",
                view=kill_report_view,
            )
            await interaction.response.send_message("已发送 / Sent!", ephemeral=True)
        except Exception as e:
            logger.error(f"[PostSettleView] kill_report error: {e}")
            await interaction.response.send_message("失败 / Failed.", ephemeral=True)


# =============================================================================
# Helper: post-settle actions (AI analysis, MVP vote, views, result-room)
# =============================================================================
async def _post_settle_actions(match_id, match_name, guild, channel, analysis_embed, bot,
                               include_kill_report=False):
    """Shared post-settle actions — merged into single rich embed + interactive buttons."""
    try:
        # Build consolidated post-settle embed
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id, name FROM teams WHERE tournament_id=?", (match_id,))
        teams = {row["id"]: row["name"] for row in cur.fetchall()}
        cur.execute("SELECT team_id FROM results WHERE tournament_id=? AND rank=1", (match_id,))
        win_row = cur.fetchone()
        conn.close()
        win_tid = win_row["team_id"] if win_row else None
        win_name = teams.get(win_tid, "胜方") if win_tid else "胜方"
        lose_name = next((name for tid, name in teams.items() if tid != win_tid), "败方")

        # Build merged embed
        main_lines = [
            f"🏆 **{match_name}** 结算完成！/ Match Settled!",
            "",
            f"**胜方 Winner:** {win_name}",
            f"**败方 Loser:** {lose_name}",
            "",
            "💰 胜方 +150 coins / 败方 +50 coins / MVP +50 coins",
            "📊 胜方 +25 MMR / 败方 -25 MMR",
        ]
        if analysis_embed and analysis_embed.description:
            main_lines.append("")
            main_lines.append("📈 **AI 分析 / Analysis:**")
            # Truncate if too long
            ai_text = analysis_embed.description[:800]
            if len(analysis_embed.description) > 800:
                ai_text += "..."
            main_lines.append(ai_text)

        merged_embed = discord.Embed(
            title=f"🏆 结算结果 / Match Result — {match_name}",
            description="\n".join(main_lines),
            color=discord.Color.gold(),
        )
        merged_embed.set_footer(text=f"Match ID: {match_id}")

        # Create PostSettleView with all actions as buttons
        post_view = PostSettleView(
            match_id=match_id, match_name=match_name, guild=guild,
            include_kill_report=include_kill_report,
        )
        await channel.send(embed=merged_embed, view=post_view)

        # Send to result-room channel
        result_channel = guild.get_channel(RESULT_CHANNEL_ID)
        if result_channel:
            result_summary = discord.Embed(
                title=f"🏆 {match_name}",
                description=f"**胜方:** {win_name}\n**败方:** {lose_name}",
                color=discord.Color.gold(),
            ).set_footer(text=f"Match ID: {match_id}")
            await result_channel.send(embed=result_summary)
    except Exception as e:
        logger.error(f"[_post_settle] merged actions error: {e}", exc_info=True)


# ══════════ MMR 排位系统 / MMR Ranking System ══════════

MMR_RANKS = [
    ("Iron", 0, 799),
    ("Bronze", 800, 999),
    ("Silver", 1000, 1199),
    ("Gold", 1200, 1399),
    ("Platinum", 1400, 1599),
    ("Diamond", 1600, 1799),
    ("Master", 1800, 1999),
    ("Challenger", 2000, 99999),
]


def _get_rank(mmr: int) -> str:
    for name, lo, hi in MMR_RANKS:
        if lo <= mmr <= hi:
            return name
    return "Iron"


def _get_rank_emoji(rank: str) -> str:
    emoji_map = {
        "Iron": "\U0001faa8", "Bronze": "\U0001f949", "Silver": "\U0001f948",
        "Gold": "\U0001f947", "Platinum": "\U0001f4a0", "Diamond": "\U0001f48e",
        "Master": "\U0001f451", "Challenger": "\U0001f320",
    }
    return emoji_map.get(rank, "")


def _mmr_change_amt(is_winner: bool, is_mvp: bool, streak: int, underdog_bonus: int) -> int:
    delta = 25 if is_winner else -25
    if is_winner and is_mvp:
        delta += 5
    if underdog_bonus > 0:
        delta += underdog_bonus
    if is_winner and streak >= 7:
        delta += 15
    elif is_winner and streak >= 5:
        delta += 10
    elif is_winner and streak >= 3:
        delta += 5
    return delta


def _update_mmr(winner_ids: list, loser_ids: list, mvp_id, conn2=None, double_mmr_ids: set = None, protect_ids: set = None):
    conn = get_db(); cur = conn.cursor()
    all_w_mmr, all_l_mmr = [], []
    for wid in winner_ids:
        cur.execute("SELECT mmr FROM mmr WHERE discord_id=?", (wid,))
        row = cur.fetchone()
        all_w_mmr.append(row["mmr"] if row else 1000)
    for lid in loser_ids:
        cur.execute("SELECT mmr FROM mmr WHERE discord_id=?", (lid,))
        row = cur.fetchone()
        all_l_mmr.append(row["mmr"] if row else 1000)

    avg_winner = sum(all_w_mmr) / len(all_w_mmr) if all_w_mmr else 1000
    avg_loser = sum(all_l_mmr) / len(all_l_mmr) if all_l_mmr else 1000
    underdog = max(0, int(avg_loser - avg_winner)) if avg_loser > avg_winner + 100 else 0
    underdog_bonus = underdog // 10

    for wid in winner_ids:
        cur.execute("INSERT OR IGNORE INTO mmr (discord_id, mmr, wins, losses, streak, rank) VALUES (?,1000,0,0,0,'Iron')", (wid,))
        cur.execute("SELECT streak, mmr FROM mmr WHERE discord_id=?", (wid,))
        row = cur.fetchone()
        old_mmr = row["mmr"] if row else 1000
        streak = row["streak"] + 1 if row["streak"] >= 0 else 1
        delta = _mmr_change_amt(True, wid == mvp_id, streak, underdog_bonus)
        if double_mmr_ids and wid in double_mmr_ids:
            delta *= 2
        new_mmr = max(0, old_mmr + delta)
        cur.execute(
            "UPDATE mmr SET mmr=?, wins=wins+1, streak=?, rank=? WHERE discord_id=?",
            (new_mmr, streak, _get_rank(new_mmr), wid),
        )

    for lid in loser_ids:
        cur.execute("INSERT OR IGNORE INTO mmr (discord_id, mmr, wins, losses, streak, rank) VALUES (?,1000,0,0,0,'Iron')", (lid,))
        cur.execute("SELECT streak, mmr FROM mmr WHERE discord_id=?", (lid,))
        row = cur.fetchone()
        old_mmr = row["mmr"] if row else 1000
        streak = row["streak"] - 1 if row["streak"] <= 0 else -1
        if protect_ids and lid in protect_ids:
            delta = 0
            new_mmr = old_mmr
        else:
            delta = _mmr_change_amt(False, lid == mvp_id, -99, 0)
            new_mmr = max(0, old_mmr + delta)
        cur.execute(
            "UPDATE mmr SET mmr=?, losses=losses+1, streak=?, rank=? WHERE discord_id=?",
            (new_mmr, streak, _get_rank(new_mmr), lid),
        )

    conn.commit(); conn.close()


# ══════════ Ready Check — 满人自动确认 ══════════

class ReadyCheckView(discord.ui.View):
    """Ready check view: 60s countdown, all-confirm triggers auto-shuffle."""

    def __init__(self, match_id: int, match_name: str, player_ids: list,
                 guild: discord.Guild, channel, timeout=65):
        super().__init__(timeout=timeout)
        self.match_id = match_id
        self.match_name = match_name
        self.guild = guild
        self.channel = channel
        self.ready: set = set()
        self.all_ids: set = set(player_ids)
        self.expired = False

    async def _do_auto_shuffle(self, interaction: discord.Interaction):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM tournaments WHERE id=?", (self.match_id,))
        t = cur.fetchone()
        if not t or t["status"] != "open":
            conn.close()
            return
        cur.execute("SELECT discord_id FROM registrations WHERE tournament_id=? ORDER BY RANDOM()", (self.match_id,))
        players = [r["discord_id"] for r in cur.fetchall()]
        if len(players) < 2:
            conn.close()
            return
        ts = t["team_size"] or 5
        split = min(ts, len(players) // 2)
        ta, tb = players[:split], players[split:split * 2]
        cur.execute("DELETE FROM teams WHERE tournament_id=?", (self.match_id,))
        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (self.match_id, "A \u961f Team A"))
        aid = cur.lastrowid
        for u in ta:
            cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?", (aid, self.match_id, u))
        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (self.match_id, "B \u961f Team B"))
        bid = cur.lastrowid
        for u in tb:
            cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?", (bid, self.match_id, u))
        cur.execute("UPDATE tournaments SET status='closed' WHERE id=?", (self.match_id,))
        conn.commit(); conn.close()

        a_mentions = [getattr(self.guild.get_member(int(uid)), 'mention', f'<@{uid}>') for uid in ta]
        b_mentions = [getattr(self.guild.get_member(int(uid)), 'mention', f'<@{uid}>') for uid in tb]
        embed = discord.Embed(
            title=f"\u2705 Ready Check Complete \u2014 {self.match_name}",
            description=(
                f"\U0001f7e2 **A \u961f Team A** (ID:{aid}): {' '.join(a_mentions)}\n"
                f"\U0001f534 **B \u961f Team B** (ID:{bid}): {' '.join(b_mentions)}\n\n"
                "All confirmed. Auto-shuffle complete."
            ),
            color=discord.Color.green(),
        )
        await self.channel.send(embed=embed)
        reshuffle_view = ReShuffleView(match_id=self.match_id, guild=self.guild)
        reshuffle_embed = reshuffle_view._build_player_list_embed()
        await self.channel.send(embed=reshuffle_embed, view=reshuffle_view)
        await VoteView.send_vote(match_id=self.match_id, match_name=self.match_name, channel=self.channel)

    async def _timeout_cleanup(self):
        self.expired = True
        embed = discord.Embed(
            title=f"\u23f0 Ready Check Timeout \u2014 {self.match_name}",
            description="Not all confirmed in time. Match back to waiting, signups re-opened.",
            color=discord.Color.orange(),
        )
        await self.channel.send(embed=embed)

    async def _build_embed(self, remaining: int) -> discord.Embed:
        unconfirmed = self.all_ids - self.ready
        confirmed_lines = []
        unconfirmed_lines = []
        for uid in self.all_ids:
            m = self.guild.get_member(int(uid))
            name = m.display_name if m else f"<@{uid}>"
            if uid in self.ready:
                confirmed_lines.append(f"\u2705 {name}")
            else:
                unconfirmed_lines.append(f"\u23f3 {name}")
        desc = f"\u23f1\ufe0f Countdown: **{remaining}s**\n\n"
        if confirmed_lines:
            desc += "Confirmed:\n" + "\n".join(confirmed_lines) + "\n\n"
        desc += "Pending:\n" + "\n".join(unconfirmed_lines)
        return discord.Embed(
            title=f"\u26a1 Ready Check \u2014 {self.match_name} ({len(self.ready)}/{len(self.all_ids)})",
            description=desc,
            color=discord.Color.blue() if remaining > 20 else discord.Color.orange(),
        )

    @discord.ui.button(label="\u2705 Ready", style=discord.ButtonStyle.success)
    async def ready_btn(self, interaction: discord.Interaction, button):
        if self.expired:
            return await interaction.response.send_message("Ready check expired.", ephemeral=True)
        uid = str(interaction.user.id)
        if uid not in self.all_ids:
            return await interaction.response.send_message("You are not in this match.", ephemeral=True)
        if uid in self.ready:
            return await interaction.response.send_message("Already confirmed.", ephemeral=True)
        self.ready.add(uid)
        remaining = max(0, 60 - int(60 * len(self.ready) / len(self.all_ids)))
        embed = await self._build_embed(remaining)
        await interaction.edit_original_response(embed=embed, view=self)
        if self.ready == self.all_ids:
            self.expired = True
            await self._do_auto_shuffle(interaction)
            self.stop()

    @discord.ui.button(label="\u274c Cancel", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction, button):
        if self.expired:
            return await interaction.response.send_message("Ready check expired.", ephemeral=True)
        uid = str(interaction.user.id)
        if uid not in self.all_ids:
            return await interaction.response.send_message("You are not in this match.", ephemeral=True)
        self.expired = True
        embed = discord.Embed(
            title=f"\u274c Ready Check Cancelled \u2014 {self.match_name}",
            description=f"{interaction.user.mention} cancelled. Match back to waiting.",
            color=discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    async def on_timeout(self):
        if not self.expired:
            await self._timeout_cleanup()


# ══════════ AI 赛事分析 / AI Match Analysis ══════════

def _generate_match_analysis(match_id: int, match_name: str,
                              winner_ids: list, loser_ids: list,
                              mvp_id, guild: discord.Guild) -> discord.Embed:
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, name FROM teams WHERE tournament_id=?", (match_id,))
    teams = {r["id"]: r["name"] for r in cur.fetchall()}
    cur.execute("SELECT discord_id, team_id FROM registrations WHERE tournament_id=?", (match_id,))
    regs = cur.fetchall()
    total_players = len(regs)

    mmr_lines = []
    for r in regs:
        uid = r["discord_id"]
        cur.execute("SELECT mmr, wins, losses, streak, rank FROM mmr WHERE discord_id=?", (uid,))
        row = cur.fetchone()
        if row:
            emoji = _get_rank_emoji(row["rank"])
            mmr_lines.append(
                f"{emoji} <@{uid}>: **{row['mmr']}** MMR ({row['rank']}) "
                f"| {row['wins']}W/{row['losses']}L"
            )

    mvp_name = ""
    if mvp_id:
        mvp_member = guild.get_member(int(mvp_id))
        mvp_name = mvp_member.display_name if mvp_member else f"<@{mvp_id}>"

    import random
    commentaries = [
        "A fiery victory for the bravest warriors!",
        "A spectacular showdown \u2014 skill speaks for itself!",
        "Every point was earned through sweat and determination!",
        "An intense battle, one for the history books!",
        "Top-tier competition with maximum suspense!",
    ]
    commentary = random.choice(commentaries)

    embed = discord.Embed(
        title=f"\U0001f4ca Match Analysis \u2014 {match_name}",
        description=(
            f"\u2501" * 20 + "\n"
            f"\U0001f3c6 **Result:** Winners {len(winner_ids)} vs Losers {len(loser_ids)}\n"
            f"\U0001f465 **Players:** {total_players}\n"
        ),
        color=discord.Color.purple(),
    )

    if mmr_lines:
        embed.add_field(
            name="\U0001f4c8 MMR Rankings",
            value="\n".join(mmr_lines[:15]) + ("\n..." if len(mmr_lines) > 15 else ""),
            inline=False,
        )

    if mvp_name:
        embed.add_field(
            name="\U0001f3c5 Match MVP",
            value=f"\U0001f451 **{mvp_name}** \u2014 outstanding performance!",
            inline=False,
        )

    embed.add_field(
        name="\U0001f4ac AI Commentary",
        value=f"\u2728 {commentary}",
        inline=False,
    )
    embed.set_footer(text=f"Match ID: {match_id} | GMPT AI Analysis")
    conn.close()
    return embed


# ══════════ 竞猜投票 / Betting VoteView ══════════

class VoteView(discord.ui.View):
    """竞猜投票面板 — 比赛开始前观众选谁会赢,猜对 +5 MMR。"""

    def __init__(self, match_id: int, match_name: str, team_a_name: str, team_b_name: str, timeout=None):
        super().__init__(timeout=None)
        self.match_id = match_id
        self.match_name = match_name
        self.team_a_name = team_a_name
        self.team_b_name = team_b_name
        # Unique custom_ids per match
        self.vote_a_btn.custom_id = f"vote_a_{match_id}"
        self.vote_b_btn.custom_id = f"vote_b_{match_id}"
        self._update_vote_labels()

    def _get_vote_counts(self):
        with db_context() as cur:
            cur.execute("SELECT vote_team, COUNT(*) as cnt FROM votes WHERE tournament_id=? GROUP BY vote_team", (self.match_id,))
            rows = cur.fetchall()
        counts = {"A": 0, "B": 0}
        for r in rows:
            counts[r["vote_team"]] = r["cnt"]
        return counts

    def _update_vote_labels(self):
        counts = self._get_vote_counts()
        self.vote_a_btn.label = f"\U0001f535 {self.team_a_name} 赢 ({counts['A']})"
        self.vote_b_btn.label = f"\U0001f534 {self.team_b_name} 赢 ({counts['B']})"

    @discord.ui.button(label="A队赢", style=discord.ButtonStyle.primary, emoji="\U0001f535", row=0)
    async def vote_a_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO votes (tournament_id, discord_id, vote_team) VALUES (?,?,?) "
            "ON CONFLICT(tournament_id, discord_id) DO UPDATE SET vote_team=?, voted_at=datetime('now')",
            (self.match_id, uid, "A", "A"),
        )
        conn.commit(); conn.close()
        self._update_vote_labels()
        await interaction.message.edit(view=self)
        await interaction.followup.send(
            f"\u2705 你投给了 **{self.team_a_name}**!You voted for {self.team_a_name}!", ephemeral=True
        )

    @discord.ui.button(label="B队赢", style=discord.ButtonStyle.danger, emoji="\U0001f534", row=0)
    async def vote_b_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO votes (tournament_id, discord_id, vote_team) VALUES (?,?,?) "
            "ON CONFLICT(tournament_id, discord_id) DO UPDATE SET vote_team=?, voted_at=datetime('now')",
            (self.match_id, uid, "B", "B"),
        )
        conn.commit(); conn.close()
        self._update_vote_labels()
        await interaction.message.edit(view=self)
        await interaction.followup.send(
            f"\u2705 你投给了 **{self.team_b_name}**!You voted for {self.team_b_name}!", ephemeral=True
        )

    def build_embed(self) -> discord.Embed:
        counts = self._get_vote_counts()
        total = counts["A"] + counts["B"]
        pct_a = f"{counts['A'] / total * 100:.0f}%" if total > 0 else "0%"
        pct_b = f"{counts['B'] / total * 100:.0f}%" if total > 0 else "0%"
        return discord.Embed(
            title=f"\U0001f4ca 比赛竞猜 / Match Betting",
            description=(
                f"**{self.match_name}**\n\n"
                f"\U0001f535 **{self.team_a_name}**: {counts['A']} 票 ({pct_a})\n"
                f"\U0001f534 **{self.team_b_name}**: {counts['B']} 票 ({pct_b})\n"
                f"共 {total} 人参与投票\n\n"
                f"\u2b50 猜对可获得 **+5 MMR**!"
            ),
            color=discord.Color.blue(),
        )

    @staticmethod
    async def send_vote(match_id: int, match_name: str, channel):
        """Send a VoteView to a channel. Uses fresh DB query for team names."""
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id, name FROM teams WHERE tournament_id=? ORDER BY id ASC", (match_id,))
        teams = cur.fetchall(); conn.close()
        if len(teams) < 2:
            return None

        team_a_name = teams[0]["name"]
        team_b_name = teams[1]["name"]

        # Check if votes already exist for this match (avoid duplicates)
        conn2 = get_db(); cur2 = conn2.cursor()
        cur2.execute("SELECT COUNT(*) as cnt FROM votes WHERE tournament_id=?", (match_id,))
        vote_exists = cur2.fetchone()["cnt"] > 0
        conn2.close()

        # Also check if vote message already sent by scanning recent messages (best-effort)
        # We use a simple DB-only check; if votes exist we skip.
        try:
            if vote_exists:
                # Votes exist but message might be gone — update label counts on existing message if found
                return None  # Skip re-sending; existing message handles it
        except Exception as e:
            log_error("dashboard", "send_vote", e)

        view = VoteView(match_id, match_name, team_a_name, team_b_name)
        embed = view.build_embed()
        try:
            msg = await channel.send(embed=embed, view=view)
            return msg
        except Exception:
            return None


def _resolve_vote_bets(match_id: int, win_team_id: int) -> list:
    """Resolve votes: determine winning team (A/B), give +5 MMR to correct bettors.
    Returns list of (discord_id, name) of winners for the summary."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, name FROM teams WHERE tournament_id=? ORDER BY id ASC", (match_id,))
    teams = cur.fetchall()
    if len(teams) < 2:
        conn.close()
        return []

    # Determine which slot (A=first, B=second) is the winner
    win_slot = None
    for i, tm in enumerate(teams):
        if tm["id"] == win_team_id:
            win_slot = "A" if i == 0 else "B"
            break

    if win_slot is None:
        conn.close()
        return []

    # Find bettors who voted for the winning team
    cur.execute("SELECT discord_id FROM votes WHERE tournament_id=? AND vote_team=?", (match_id, win_slot))
    winners = [r["discord_id"] for r in cur.fetchall()]

    # Give +5 MMR to each correct bettor
    for wid in winners:
        cur.execute("INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING", (wid,))
        cur.execute("INSERT OR IGNORE INTO mmr (discord_id, mmr, wins, losses, streak, rank) VALUES (?,1000,0,0,0,'Iron')", (wid,))
        cur.execute("SELECT mmr FROM mmr WHERE discord_id=?", (wid,))
        row = cur.fetchone()
        if row:
            new_mmr = row["mmr"] + 5
            cur.execute("UPDATE mmr SET mmr=?, rank=? WHERE discord_id=?", (new_mmr, _get_rank(new_mmr), wid))

    conn.commit()
    winner_names = winners  # discord IDs
    conn.close()
    return winner_names


# ══════════ MMR 排行榜 实时面板 / MMR Board Live Panel ══════════

async def _build_mmr_board_embed(guild: discord.Guild) -> discord.Embed:
    """Build the MMR leaderboard embed. Returns an embed even if empty."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM mmr ORDER BY mmr DESC LIMIT 25")
    rows = cur.fetchall()
    conn.close()

    embed = discord.Embed(
        title="\U0001f3c6 GMPT MMR Leaderboard",
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc),
    )

    if not rows:
        embed.description = "No MMR data yet — play some matches first!"
        embed.set_footer(text="Live Leaderboard")
        return embed

    lines = []
    for i, row in enumerate(rows):
        uid = row["discord_id"]
        name = resolve_name(guild, uid)
        emoji = _get_rank_emoji(row["rank"])
        streak_str = f" \U0001f525{row['streak']}" if row["streak"] > 0 else ""
        medal = {0: "\U0001f947", 1: "\U0001f948", 2: "\U0001f949"}.get(i, f"#{i+1}")
        lines.append(
            f"{medal} {emoji} **{name}** \u2014 {row['mmr']} MMR "
            f"({row['wins']}W/{row['losses']}L){streak_str}"
        )

    embed.description = "\n".join(lines)
    embed.set_footer(text=f"Live Leaderboard \u2022 {len(rows)} players")
    return embed


async def _refresh_mmr_board(bot, guild: discord.Guild):
    """Refresh the persistent MMR leaderboard message for a guild.
    If no board is configured, silently returns."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT message_id, channel_id FROM mmr_board WHERE guild_id=?",
        (str(guild.id),),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return

    channel = guild.get_channel(int(row["channel_id"]))
    if not channel:
        return

    embed = await _build_mmr_board_embed(guild)

    try:
        msg = await channel.fetch_message(int(row["message_id"]))
        await msg.edit(embed=embed)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        # Original message deleted/blocked — recreate and update DB
        try:
            new_msg = await channel.send(embed=embed)
            conn2 = get_db()
            conn2.cursor().execute(
                "UPDATE mmr_board SET message_id=?, channel_id=? WHERE guild_id=?",
                (str(new_msg.id), str(channel.id), str(guild.id)),
            )
            conn2.commit()
            conn2.close()
        except Exception as e:
            log_error("dashboard", "_refresh_mmr_board", e)


# =============================================================================
# DashboardView — 统一控制面板 / Unified Control Panel
# =============================================================================


# =============================================================================
# DashboardView — 5-page button-based control panel / 全按钮分页控制面板
# =============================================================================
class DashboardView(discord.ui.View):
    """Unified control panel with 5 pages + navigation buttons."""

    PAGE_COLORS = {
        1: discord.Color.blue(),
        2: discord.Color.gold(),
        3: discord.Color.green(),
        4: discord.Color.teal(),
        5: discord.Color.purple(),
        6: discord.Color.dark_purple(),
    }

    PAGE_TITLES = {
        1: "⚔️ 比赛 Match",
        2: "🏆 赛事 Tournament",
        3: "👤 玩家 Player",
        4: "🛒 经济 Economy",
        5: "🧰 常用工具 Common Tools",
        6: "🔧 管理工具 Admin Tools",
    }

    def __init__(self, guild=None, session=None, *args, **kwargs):
        super().__init__(timeout=None, *args, **kwargs)
        self.guild = guild
        self.session = session
        self.page = 1
        # Only build page buttons on initial creation (not during persistent view reconstruction)
        if not args and not kwargs:
            self.build_page_buttons()

    # ═══════════════════ Page Builder ═══════════════════

    def build_page_buttons(self):
        """Rebuild all buttons for current page."""
        self.clear_items()
        page = self.page

        if page == 1:
            btns = [
                ("🎮 创建比赛\nCreate Match", "create_match"),
                ("📋 报名\nSign Up", "signup"),
                ("🎲 随机分队\nRandom Teams", "shuffle"),
                ("🔴🔵 分AB队\nTeam A/B", "assign_teams"),
                ("⚔️ 开始比赛\nStart Match", "start_match"),
                ("🏁 结算\nSettle", "settle"),
                ("🔊 拉入语音\nPull VC", "pull_voice"),
                ("👑 选队长\nPick Captain", "pick_captain"),
            ]
        elif page == 2:
            btns = [
                ("🏆 创建赛事\nCreate", "create_tournament"),
                ("✍️ 报名\nSign Up", "signup_tournament"),
                ("👤 队长选秀\nDraft", "draft_setup"),
                ("📊 上报比分\nReport", "report_score"),
                ("📈 赛事排名\nStandings", "tournament_standings"),
                ("🗺️ 对阵表\nBracket", "tournament_bracket"),
                ("📋 赛事记录\nHistory", "tournament_history"),
                ("📅 定时赛事\nScheduled", "scheduled_event"),
            ]
            # Pad to 8 slots for consistent grid
            while len(btns) < 8:
                btns.append(None)
        elif page == 3:
            btns = [
                ("👤 个人资料\nProfile", "profile"),
                ("📜 比赛历史\nHistory", "history"),
                ("📅 每周挑战\nWeekly", "weekly"),
                ("📅 排位赛季\nSeason", "season"),
                ("💎 MVP排行榜\nMVP LB", "mvp_lb"),
                ("📊 数据总览\nStats", "stats"),
                ("🎖️ 段位列表\nRanks", "ranks"),
                ("🔥 连胜王\nWin Streak", "win_streak"),
            ]
            while len(btns) < 8:
                btns.append(None)
        elif page == 4:
            btns = [
                ("🛒 积分商店\nShop", "shop"),
                ("🎒 我的背包\nInventory", "inventory"),
                ("💰 余额\nBalance", "balance"),
                ("🎁 赠送金币\nGift", "gift"),
                ("📊 交易记录\nTransactions", "transactions"),
                ("🏅 成就列表\nAchievements", "achievements"),
                ("🎟️ 抽奖\nGiveaway", "giveaway"),
                ("🗓️ 每日奖励\nDaily", "daily"),
            ]
            while len(btns) < 8:
                btns.append(None)
        elif page == 5:
            # 常用工具 (Common Tools)
            btns = [
                ("🎤 语音排行\nVoice LB", "voice_lb"),
                ("🔊 排队状态\nQueue Status", "queue_status"),
                ("📊 全部玩家\nAll Players", "all_players"),
                ("🏅 MMR排行\nMMR LB", "mmr_lb"),
                ("🎬 比赛回放\nReplay", "replay"),
            ]
            while len(btns) < 8:
                btns.append(None)
        elif page == 6:
            # 管理工具 (Admin Tools)
            btns = [
                ("📤 导出数据\nExport CSV", "export_data"),
                ("🔒 管理面板\nAdmin", "admin"),
                ("📢 发送公告\nAnnounce", "announce"),
                ("🔄 赛季重置\nSeason Reset", "season_reset"),
                ("🎙️ 赛后拉入\nPost-Match VC", "post_match_pull"),
            ]
            while len(btns) < 8:
                btns.append(None)

        # Layout: rows of 4
        rows = []
        current_row = []
        for btn in btns:
            if btn is None:
                continue
            current_row.append(btn)
            if len(current_row) == 4:
                rows.append(current_row)
                current_row = []
        if current_row:
            rows.append(current_row)

        for row_idx, row_btns in enumerate(rows):
            for col_idx, (label, cb_id) in enumerate(row_btns):
                btn = discord.ui.Button(
                    label=label,
                    style=discord.ButtonStyle.secondary,
                    row=row_idx,
                    custom_id=cb_id,
                )
                btn.callback = self.make_callback(cb_id)
                self.add_item(btn)

        # Navigation rows — page tabs split across 2 rows (Discord max 5 cols/row)
        # Row 3: ◀ P1 P2 P3 P4 (5 cols)
        self.prev_btn = discord.ui.Button(label="◀", style=discord.ButtonStyle.primary, row=3,
                                           disabled=(page == 1), custom_id="dashboard_prev")
        self.prev_btn.callback = self.prev_page
        self.add_item(self.prev_btn)

        for p in range(1, 5):
            is_current = (p == page)
            btn = discord.ui.Button(
                label=f"P{p}",
                style=discord.ButtonStyle.success if is_current else discord.ButtonStyle.secondary,
                row=3,
                disabled=is_current,
                custom_id=f"dashboard_page_{p}",
            )
            btn.callback = self.make_page_callback(p)
            self.add_item(btn)

        # Row 4: P5 P6 ▶ (3 cols)
        for p in range(5, 7):
            is_current = (p == page)
            btn = discord.ui.Button(
                label=f"P{p}",
                style=discord.ButtonStyle.success if is_current else discord.ButtonStyle.secondary,
                row=4,
                disabled=is_current,
                custom_id=f"dashboard_page_{p}",
            )
            btn.callback = self.make_page_callback(p)
            self.add_item(btn)

        self.next_btn = discord.ui.Button(label="▶", style=discord.ButtonStyle.primary, row=4,
                                           disabled=(page == 6), custom_id="dashboard_next")
        self.next_btn.callback = self.next_page
        self.add_item(self.next_btn)

    def make_callback(self, cb_id):
        """Factory to create lambda-free callbacks (avoids closure issues)."""
        async def inner(interaction: discord.Interaction):
            method = getattr(self, "_" + cb_id, None)
            if method:
                try:
                    await method(interaction)
                except Exception as e:
                    logger.error(f"Dashboard callback '{cb_id}' failed: {e}", exc_info=True)
                    try:
                        await interaction.followup.send("❌ 操作失败，请重试 / Error, please try again.", ephemeral=True)
                    except Exception:
                        try:
                            await interaction.response.send_message("❌ 操作失败，请重试 / Error, please try again.", ephemeral=True)
                        except Exception as e:
                            log_error("dashboard", "fallback_send", e)
        return inner

    def make_page_callback(self, target_page: int):
        """Factory for page-tab navigation buttons (highlights current page)."""
        async def go_page(interaction: discord.Interaction):
            self.page = target_page
            self.build_page_buttons()
            embed = self._build_page_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        return go_page

    # ═══════════════════ Navigation ═══════════════════

    async def prev_page(self, interaction: discord.Interaction):
        if self.page > 1:
            self.page -= 1
        self.build_page_buttons()
        embed = self._build_page_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def next_page(self, interaction: discord.Interaction):
        if self.page < 6:
            self.page += 1
        self.build_page_buttons()
        embed = self._build_page_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    def _build_page_embed(self):
        title = f"🎮 GMPT 控制面板 Control Panel | {self.PAGE_TITLES.get(self.page, '')}"
        color = self.PAGE_COLORS.get(self.page, discord.Color.blurple())

        if self.page == 1:
            desc = "⚔️ **Match System / 比赛系统** — 创建、报名、分队、结算\nClick a button below / 点击下方按钮"
        elif self.page == 2:
            desc = "🏆 **Tournament System / 赛事系统** — 创建赛事、报名、选秀、上报\nClick a button below / 点击下方按钮"
        elif self.page == 3:
            desc = "👤 **Player / 玩家** — 资料、历史、挑战、排行\ne.g. 赛季、Profile、History、MVP"
        elif self.page == 4:
            desc = "🛒 **Economy / 经济** — 商店、背包、金币、抽奖、每日\ne.g. Shop、Balance、Achievements、Daily"
        elif self.page == 5:
            desc = "🧰 **Common Tools / 常用工具** — 语音排行、排队、全部玩家、MMR、回放\ne.g. Voice LB、Queue、All Players、MMR、Replay"
        elif self.page == 6:
            desc = "🔧 **Admin Tools / 管理工具** — 导出、管理面板、公告、赛季重置、赛后拉语音\ne.g. Export、Admin、Announce、Season Reset、Post-Match VC"
        # legacy page 5 fallback
        elif self.page == 5:
            desc = "🎧 **Tools / 工具** — 语音排行、排队、管理\ne.g. Voice LB、Queue、Admin"

        return discord.Embed(
            title=title,
            description=desc,
            color=color,
        ).set_footer(text=f"GMPT Dashboard v3.2 | Page {self.page}/6")

    # ═══════════════════ Page 1 — Match ═══════════════════

    async def _create_match(self, interaction: discord.Interaction):
        view = SelectModeView(self.guild, self.session)
        await interaction.response.send_message(
            "**Select Match Mode / 选择比赛模式**\n"
            "🎯 **有分路 With Roles** — 报名时需选择 Top/JG/Mid/ADC/Support\n"
            "🎯 **无分路 Blind Pick** — 自由报名，不分路线",
            view=view,
            ephemeral=True,
        )

    async def _signup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id, name, status FROM matches WHERE status='pending' ORDER BY id DESC LIMIT 5")
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.followup.send("No open matches. Create one first.", ephemeral=True)

        class SignupSelect(discord.ui.Select):
            def __init__(self):
                options = [
                    discord.SelectOption(label=f"#{m['id']} - {m['name']}", value=str(m["id"]))
                    for m in matches
                ]
                super().__init__(placeholder="Select a match to join", options=options)
            async def callback(self, sel_int: discord.Interaction):
                await sel_int.response.defer(ephemeral=True)
                mid = int(self.values[0])
                suid = str(sel_int.user.id)
                conn2 = get_db(); cur2 = conn2.cursor()
                cur2.execute("SELECT id, name, status FROM matches WHERE id=?", (mid,))
                mr = cur2.fetchone()
                if not mr or mr["status"] != "pending":
                    conn2.close()
                    return await sel_int.followup.send("Match not available.", ephemeral=True)
                cur2.execute("SELECT id FROM match_signups WHERE match_id=? AND discord_id=?", (mid, suid))
                if cur2.fetchone():
                    conn2.close()
                    return await sel_int.followup.send(f"Already signed up for #{mid}.", ephemeral=True)
                cur2.execute("INSERT INTO match_signups (match_id, discord_id) VALUES (?,?)", (mid, suid))
                try:
                    conn2.commit()
                finally:
                    conn2.close()
                await sel_int.followup.send(f"Signed up for match **{mr['name']}** (#{mid})!", ephemeral=True)

        view = discord.ui.View(timeout=60)
        view.add_item(SignupSelect())
        await interaction.followup.send("Select a match to sign up:", view=view, ephemeral=True)

    async def _shuffle(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name, max_teams, team_size FROM tournaments "
            "WHERE status='open' AND max_teams=2 ORDER BY id DESC LIMIT 25"
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.followup.send("当前没有可随机分队的比赛 / No open matches.", ephemeral=True)

        options = []
        for m in matches:
            ts = m["team_size"] or 5
            options.append(discord.SelectOption(
                label=m["name"][:100],
                value=str(m["id"]),
                description=f"{ts}v{ts} | ID: {m['id']}",
            ))

        select = discord.ui.Select(
            placeholder="选择比赛 / Select a match...",
            options=options[:25],
        )

        async def shuffle_callback(sel_int: discord.Interaction):
            mid = int(sel_int.data["values"][0])
            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute("SELECT * FROM tournaments WHERE id=?", (mid,))
            t = cur2.fetchone()
            if not t or t["status"] != "open":
                conn2.close()
                return await sel_int.response.send_message("比赛已关闭或不存在 / Match closed or not found.", ephemeral=True)

            cur2.execute("SELECT discord_id FROM registrations WHERE tournament_id=? ORDER BY RANDOM()", (mid,))
            players = [r["discord_id"] for r in cur2.fetchall()]
            if len(players) < 2:
                conn2.close()
                return await sel_int.response.send_message("人数不足 (至少2人) / Not enough players (min 2).", ephemeral=True)

            ts = t["team_size"] or 5
            split = min(ts, len(players) // 2)
            ta, tb = players[:split], players[split:split * 2]

            cur2.execute("DELETE FROM teams WHERE tournament_id=?", (mid,))
            cur2.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (mid, "A 队 Team A"))
            aid = cur2.lastrowid
            for u in ta:
                cur2.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?", (aid, mid, u))
            cur2.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (mid, "B 队 Team B"))
            bid = cur2.lastrowid
            for u in tb:
                cur2.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?", (bid, mid, u))
            cur2.execute("UPDATE tournaments SET status='closed' WHERE id=?", (mid,))
            try:
                conn2.commit()
            finally:
                conn2.close()

            await VoteView.send_vote(match_id=mid, match_name=t["name"], channel=sel_int.channel)

            a_mentions = []
            for uid in ta:
                m = self.guild.get_member(int(uid))
                a_mentions.append(m.mention if m else f"<@{uid}>")
            b_mentions = []
            for uid in tb:
                m = self.guild.get_member(int(uid))
                b_mentions.append(m.mention if m else f"<@{uid}>")

            embed = discord.Embed(
                title=f"Shuffle — {t['name']}",
                description=(
                    f"🔵 **A 队 Team A** (ID:{aid}): {' '.join(a_mentions)}\n"
                    f"🔴 **B 队 Team B** (ID:{bid}): {' '.join(b_mentions)}\n\n"
                    f"Settle: `/gmpt-lol-settle {mid} <win_team_id>`"
                ),
                color=discord.Color.gold(),
            )
            await sel_int.response.send_message(embed=embed, ephemeral=False)

        select.callback = shuffle_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    async def _assign_teams(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name, max_teams, team_size FROM tournaments "
            "WHERE status='open' AND max_teams=2 ORDER BY id DESC LIMIT 25"
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.followup.send("当前没有可分配的比赛 / No open matches.", ephemeral=True)

        options = []
        for m in matches:
            ts = m["team_size"] or 5
            options.append(discord.SelectOption(
                label=m["name"][:100],
                value=str(m["id"]),
                description=f"{ts}v{ts} | ID: {m['id']}",
            ))

        select = discord.ui.Select(
            placeholder="选择比赛 / Select a match...",
            options=options[:25],
        )

        async def assign_callback(sel_int: discord.Interaction):
            mid = int(sel_int.data["values"][0])
            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute("SELECT * FROM tournaments WHERE id=?", (mid,))
            t = cur2.fetchone()
            cur2.execute("SELECT discord_id FROM registrations WHERE tournament_id=?", (mid,))
            players = cur2.fetchall()
            conn2.close()

            if not t or not players:
                return await sel_int.response.send_message("比赛不存在或无报名玩家 / Match not found or no players.", ephemeral=True)

            player_ids = [r["discord_id"] for r in players]
            ts = t["team_size"] or 5
            view = TeamAssignView(mid, t["name"], player_ids, self.guild, ts)
            embed = view._build_embed()
            await sel_int.response.send_message(embed=embed, view=view, ephemeral=False)

        select.callback = assign_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    async def _start_match(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM tournaments WHERE status='open' AND max_teams=2 ORDER BY id DESC LIMIT 25"
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.followup.send("当前没有可开始的比赛 / No open matches.", ephemeral=True)

        options = []
        for m in matches:
            options.append(discord.SelectOption(
                label=m["name"][:100],
                value=str(m["id"]),
                description=f"ID: {m['id']}",
            ))

        select = discord.ui.Select(
            placeholder="选择比赛 / Select a match...",
            options=options[:25],
        )

        async def start_callback(sel_int: discord.Interaction):
            mid = int(sel_int.data["values"][0])

            embed = discord.Embed(
                title="确认开始 / Confirm Start",
                description=f"确定要关闭比赛报名并开始吗?\nClose signup and start?\nMatch ID: {mid}",
                color=discord.Color.orange(),
            )
            confirm_view = ConfirmView(timeout=30)
            await sel_int.response.send_message(embed=embed, view=confirm_view, ephemeral=True)
            await confirm_view.wait()
            if confirm_view.value is None or not confirm_view.value:
                return

            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute("UPDATE tournaments SET status='closed' WHERE id=? AND status='open'", (mid,))
            try:
                conn2.commit()
                # Record match start event for replay
                cur2.execute(
                    "INSERT INTO match_events (tournament_id, event_type) VALUES (?, 'start')",
                    (mid,),
                )
                conn2.commit()
            finally:
                conn2.close()
            await sel_int.edit_original_response(
                content=f"比赛 / Match (ID: {mid}) 已开始! Started! 报名已关闭 / Signup closed.",
                embed=None,
                view=None,
            )

            conn3 = get_db(); cur3 = conn3.cursor()
            cur3.execute("SELECT name FROM tournaments WHERE id=?", (mid,))
            t_name_row = cur3.fetchone()
            match_name = t_name_row["name"] if t_name_row else "Unknown"
            conn3.close()
            await VoteView.send_vote(match_id=mid, match_name=match_name, channel=sel_int.channel)

        select.callback = start_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    async def _settle(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM tournaments WHERE status='closed' AND max_teams=2 ORDER BY id DESC LIMIT 25"
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.followup.send("当前没有待结算的比赛 / No closed matches to settle.", ephemeral=True)

        options = []
        for m in matches:
            options.append(discord.SelectOption(
                label=m["name"][:100],
                value=str(m["id"]),
                description=f"ID: {m['id']}",
            ))

        select = discord.ui.Select(
            placeholder="选择比赛 / Select a match to settle...",
            options=options[:25],
        )

        async def settle_match_callback(sel_int: discord.Interaction):
            mid = int(sel_int.data["values"][0])
            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute("SELECT * FROM tournaments WHERE id=?", (mid,))
            t = cur2.fetchone()
            if not t:
                conn2.close()
                return await sel_int.response.send_message(f"比赛 #{mid} 不存在 / Match not found.", ephemeral=True)
            if t["status"] == "finished":
                conn2.close()
                return await sel_int.response.send_message("已结算 / Already settled.", ephemeral=True)

            cur2.execute("SELECT id, name FROM teams WHERE tournament_id=?", (mid,))
            teams = cur2.fetchall()
            conn2.close()

            if len(teams) < 2:
                return await sel_int.response.send_message("未找到两支队伍 / Two teams not found.", ephemeral=True)

            team_options = []
            for tm in teams:
                team_options.append(discord.SelectOption(
                    label=tm["name"][:100],
                    value=str(tm["id"]),
                ))

            win_select = discord.ui.Select(
                placeholder="选择获胜队伍 / Select winning team...",
                options=team_options,
            )

            class SettleFlowDash:
                def __init__(self):
                    self.win_team_id = None
                    self.mvp_id = None

            flow = SettleFlowDash()

            async def win_callback_dash(inner_int: discord.Interaction):
                flow.win_team_id = int(inner_int.data["values"][0])

                conn3 = get_db(); cur3 = conn3.cursor()
                cur3.execute(
                    "SELECT discord_id FROM registrations WHERE tournament_id=?",
                    (mid,),
                )
                players = cur3.fetchall()
                conn3.close()

                mvp_options = [discord.SelectOption(label="不选 MVP / Skip", value="__none__")]
                for p in players:
                    name = resolve_name(self.guild, p["discord_id"])
                    mvp_options.append(discord.SelectOption(label=name[:100], value=p["discord_id"]))

                mvp_select = discord.ui.Select(
                    placeholder="选择 MVP (可选) / Select MVP...",
                    options=mvp_options[:25],
                )

                async def mvp_callback_dash(mvp_int: discord.Interaction):
                    val = mvp_int.data["values"][0]
                    if val != "__none__":
                        flow.mvp_id = val

                    conn4 = get_db(); cur4 = conn4.cursor()
                    win_name = cur4.execute("SELECT name FROM teams WHERE id=?", (flow.win_team_id,)).fetchone()
                    cur4.execute("SELECT name FROM teams WHERE tournament_id=? AND id!=?", (mid, flow.win_team_id))
                    lose_row = cur4.fetchone()
                    conn4.close()
                    win_name = win_name["name"] if win_name else "胜方"
                    lose_name = lose_row["name"] if lose_row else "败方"

                    mvp_text = ""
                    if flow.mvp_id:
                        mvp_member = self.guild.get_member(int(flow.mvp_id))
                        mvp_text = f"\n🅠MVP: {mvp_member.mention if mvp_member else flow.mvp_id}"

                    # AI MVP recommendation
                    conn_ai = get_db(); cur_ai = conn_ai.cursor()
                    cur_ai.execute(
                        "SELECT r.discord_id FROM registrations r WHERE r.tournament_id=? AND r.team_id=? AND (r.is_sub IS NULL OR r.is_sub=0)",
                        (mid, flow.win_team_id),
                    )
                    win_players = [r["discord_id"] for r in cur_ai.fetchall()]
                    ai_mvp_id = None; highest_mmr = 0
                    for pid in win_players:
                        cur_ai.execute("SELECT mmr FROM mmr WHERE discord_id=?", (pid,))
                        row = cur_ai.fetchone()
                        if row and row["mmr"] > highest_mmr:
                            highest_mmr = row["mmr"]
                            ai_mvp_id = pid
                    conn_ai.close()
                    ai_mvp_text = ""
                    if ai_mvp_id:
                        ai_member = guild.get_member(int(ai_mvp_id))
                        ai_mvp_text = f"\n🤖 AI推荐MVP: {ai_member.mention if ai_member else f'<@{ai_mvp_id}>'} (MMR:{highest_mmr})"

                    embed = discord.Embed(
                        title="确认结算 / Confirm Settle",
                        description=(
                            f"Match: **{t['name']}** (ID:{mid})\n"
                            f"🏆 胜方 Winner: **{win_name}**\n"
                            f"💔 败方 Loser: **{lose_name}**"
                            f"{mvp_text}"
                            f"{ai_mvp_text}\n\n"
                            f"胜方 +150 / 败方 +50 / MVP +50\n"
                            f"Click Confirm to proceed / 点击确认执行"
                        ),
                        color=discord.Color.orange(),
                    )
                    confirm_view = ConfirmView(timeout=60)
                    await mvp_int.response.send_message(embed=embed, view=confirm_view, ephemeral=True)
                    await confirm_view.wait()

                    if confirm_view.value is None or not confirm_view.value:
                        return await mvp_int.edit_original_response(
                            content="结算已取消 / Settle cancelled.", embed=None, view=None
                        )

                    analysis_embed = await _execute_settle(
                        match_id=mid,
                        win_team_id=flow.win_team_id,
                        mvp_id=flow.mvp_id,
                        guild=self.guild,
                        match_name=t["name"],
                        bot=interaction.client,
                    )
                    await mvp_int.edit_original_response(
                        content="✅ 结算完成! / Settle complete!", embed=None, view=None
                    )

                    try:
                        await _post_settle_actions(
                            mid, t["name"], self.guild, interaction.channel,
                            analysis_embed, interaction.client, include_kill_report=True,
                        )
                    except Exception as e:
                        logger.error(f"[DashboardView] mvp_callback_dash outer error: {e}")

                mvp_select.callback = mvp_callback_dash
                mvp_view = discord.ui.View(timeout=120)
                mvp_view.add_item(mvp_select)
                await inner_int.response.send_message(
                    "选择本场 MVP (可选 / Optional):", view=mvp_view, ephemeral=True
                )

            win_select.callback = win_callback_dash
            win_view = discord.ui.View(timeout=120)
            win_view.add_item(win_select)
            await sel_int.response.send_message(
                "选择获胜队伍 / Select winning team:", view=win_view, ephemeral=True
            )

        select.callback = settle_match_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    async def _pull_voice(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT t.id, t.name FROM tournaments t "
            "INNER JOIN registrations r ON r.tournament_id = t.id "
            "WHERE t.max_teams=2 AND r.team_id IS NOT NULL AND t.status != 'finished' "
            "ORDER BY t.id DESC LIMIT 25"
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.followup.send("当前没有已分队的比赛 / No matches with teams assigned.", ephemeral=True)

        options = []
        for m in matches:
            options.append(discord.SelectOption(
                label=m["name"][:100],
                value=str(m["id"]),
                description=f"ID: {m['id']}",
            ))

        select = discord.ui.Select(
            placeholder="选择比赛 / Select a match...",
            options=options[:25],
        )

        async def pull_callback(sel_int: discord.Interaction):
            mid = int(sel_int.data["values"][0])

            # Permission check: participant or admin only
            conn0 = get_db(); cur0 = conn0.cursor()
            cur0.execute(
                "SELECT r.discord_id FROM registrations r WHERE r.tournament_id=?",
                (mid,),
            )
            player_ids = [row["discord_id"] for row in cur0.fetchall()]
            conn0.close()
            is_participant = str(sel_int.user.id) in player_ids
            is_admin = sel_int.user.guild_permissions.manage_channels
            if not is_participant and not is_admin:
                return await sel_int.response.send_message(
                    "❌ 只有参赛者和管理员才能使用此功能", ephemeral=True
                )

            voice_view = VoicePullView.from_match(mid, self.guild)
            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute("SELECT name FROM tournaments WHERE id=?", (mid,))
            t = cur2.fetchone()
            conn2.close()

            a_mentions = []
            for uid in voice_view.team_a_ids:
                m = self.guild.get_member(int(uid))
                a_mentions.append(m.mention if m else f"<@{uid}>")
            b_mentions = []
            for uid in voice_view.team_b_ids:
                m = self.guild.get_member(int(uid))
                b_mentions.append(m.mention if m else f"<@{uid}>")

            embed = discord.Embed(
                title=f"拉入语音 — {t['name'] if t else f'Match #{mid}'}",
                description=(
                    f"🔵 **A 队**:{' '.join(a_mentions) if a_mentions else '(无)'}\n"
                    f"🔴 **B 队**:{' '.join(b_mentions) if b_mentions else '(无)'}"
                ),
                color=discord.Color.blurple(),
            )
            await sel_int.response.send_message(embed=embed, view=voice_view, ephemeral=False)

        select.callback = pull_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    async def _pick_captain(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM tournaments WHERE status='open' AND max_teams=2 ORDER BY id DESC LIMIT 25"
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.followup.send("当前没有可分队的比赛 / No open matches.", ephemeral=True)

        options = []
        for m in matches:
            options.append(discord.SelectOption(
                label=m["name"][:100],
                value=str(m["id"]),
                description=f"ID: {m['id']}",
            ))

        select = discord.ui.Select(
            placeholder="选择比赛 / Select a match...",
            options=options[:25],
        )

        async def captain_select_callback(sel_int: discord.Interaction):
            mid = int(sel_int.data["values"][0])
            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute(
                "SELECT r.discord_id, u.username FROM registrations r "
                "LEFT JOIN users u ON u.discord_id=r.discord_id WHERE r.tournament_id=?",
                (mid,),
            )
            players = cur2.fetchall()
            conn2.close()

            if len(players) < 2:
                return await sel_int.response.send_message("需要至少2名玩家 / Need at least 2 players.", ephemeral=True)

            cap_options = []
            for p in players:
                name = p["username"] or p["discord_id"]
                cap_options.append(discord.SelectOption(label=name[:100], value=p["discord_id"]))

            cap_select = discord.ui.Select(
                placeholder="选择副队长 (Captain 2) / Select Captain 2...",
                options=cap_options[:25],
                max_values=1,
            )

            async def final_captain_cb(inner_int: discord.Interaction):
                cap2_id = inner_int.data["values"][0]
                caplist = [str(sel_int.user.id), cap2_id]

                a_mentions = []
                b_mentions = []
                for i, uid in enumerate(caplist):
                    m = self.guild.get_member(int(uid)) if uid.isdigit() else None
                    if i == 0:
                        a_mentions.append(m.mention if m else f"<@{uid}> (先手)")
                    else:
                        b_mentions.append(m.mention if m else f"<@{uid}> (后手)")

                embed = discord.Embed(
                    title="👑 选出队长 / Captains Picked!",
                    description=(
                        f"🔵 **A 队 Team A**: {a_mentions[0] if a_mentions else 'N/A'}\n"
                        f"🔴 **B 队 Team B**: {b_mentions[0] if b_mentions else 'N/A'}\n\n"
                        f"现在可以使用 `/gmpt-vote` 开始投票观战!"
                    ),
                    color=discord.Color.gold(),
                )
                await inner_int.response.send_message(embed=embed, ephemeral=False)

            cap_select.callback = final_captain_cb
            cap_view = discord.ui.View(timeout=60)
            cap_view.add_item(cap_select)
            await sel_int.response.send_message("选择副队长 (B队) / Select Co-Captain (Team B):", view=cap_view, ephemeral=True)

        select.callback = captain_select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    # ═══════════════════ Page 2 — Tournament ═══════════════════

    async def _create_tournament(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.defer(ephemeral=True)
            return await interaction.followup.send("仅管理员可创建锦标赛 / Admin only.", ephemeral=True)
        modal = CreateTournamentModal(self.guild, self.session)
        await interaction.response.send_modal(modal)

    async def _signup_tournament(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name, max_players FROM tournaments WHERE status='signup' ORDER BY id DESC LIMIT 25"
        )
        tournaments = cur.fetchall()
        conn.close()

        if not tournaments:
            return await interaction.followup.send("当前没有可报名的锦标赛 / No open tournaments.", ephemeral=True)

        options = []
        for t in tournaments:
            options.append(discord.SelectOption(
                label=t["name"][:100],
                value=str(t["id"]),
                description=f"Max: {t['max_players']} | ID: {t['id']}",
            ))

        select = discord.ui.Select(
            placeholder="选择锦标赛 / Select a tournament...",
            options=options[:25],
        )

        async def signup_callback(sel_int: discord.Interaction):
            tid = int(sel_int.data["values"][0])
            conn2 = get_db(); cur2 = conn2.cursor()
            t = get_tournament_or_none(cur2, tid)

            if not t or t["status"] != "signup":
                conn2.close()
                reason = "赛事不存在" if not t else f"状态为 {t['status']}"
                return await sel_int.response.send_message(f"该锦标赛报名已关闭 / Signup closed ({reason}).", ephemeral=True)

            uid = str(sel_int.user.id)
            tier_restriction = t["tier_restriction"]
            if tier_restriction:
                allowed = set(x.strip().upper() for x in tier_restriction.split(","))
                _, tier_name, _ = await fetch_player_tier(self.session, uid)
                if tier_name and tier_name.upper() not in allowed:
                    conn2.close()
                    return await sel_int.response.send_message(
                        f"你的段位 **{tier_name}** 不符合本赛事要求 / Tier restricted.", ephemeral=True
                    )

            cur2.execute(
                "SELECT id FROM tournament_players WHERE tournament_id=? AND discord_id=?",
                (tid, uid),
            )
            if cur2.fetchone():
                conn2.close()
                return await sel_int.response.send_message("你已经报名了 / Already signed up.", ephemeral=True)

            max_p = t["max_players"] or 32
            cur2.execute("SELECT COUNT(*) as cnt FROM tournament_players WHERE tournament_id=?", (tid,))
            cnt = cur2.fetchone()["cnt"]
            if cnt >= max_p:
                conn2.close()
                return await sel_int.response.send_message(f"报名已满 / Full ({max_p}人).", ephemeral=True)

            tier_display, tier_key, _ = await fetch_player_tier(self.session, uid)
            if tier_display is None:
                tier_display = "未关联"
                tier_key = "UNRANKED"

            conn2.close()
            conn3 = get_db(); cur3 = conn3.cursor()
            seed_val = TIER_SEED.get(tier_key.upper() if tier_key else "UNRANKED", 10)
            cur3.execute(
                "SELECT MAX(seed) as max_seed FROM tournament_players WHERE tournament_id=? AND tier=?",
                (tid, tier_key.upper()),
            )
            row = cur3.fetchone()
            if row and row["max_seed"] is not None:
                seed_val = row["max_seed"] + 1

            cur3.execute(
                "INSERT INTO tournament_players (tournament_id, discord_id, seed, tier) VALUES (?,?,?,?)",
                (tid, uid, seed_val, tier_key.upper() if tier_key else "UNRANKED"),
            )
            cur3.execute(
                "INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)",
                (uid, sel_int.user.name),
            )
            try:
                conn3.commit()
            finally:
                conn3.close()

            await sel_int.followup.send(
                f"✅ {sel_int.user.mention} 报名成功! Signed up!\n"
                f"锦标赛: **{t['name']}** | Tier: **{tier_display}** | ({cnt+1}/{max_p})",
                ephemeral=True,
            )

        select.callback = signup_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    async def _draft_setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("仅管理员可设置队长选秀 / Admin only.", ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM tournaments WHERE status IN ('signup','active') ORDER BY id DESC LIMIT 25"
        )
        tournaments = cur.fetchall()
        conn.close()

        if not tournaments:
            return await interaction.followup.send("没有可用的锦标赛 / No tournaments available.", ephemeral=True)

        options = []
        for t in tournaments:
            options.append(discord.SelectOption(
                label=t["name"][:100],
                value=str(t["id"]),
                description=f"ID: {t['id']}",
            ))

        select = discord.ui.Select(
            placeholder="选择锦标赛 / Select a tournament...",
            options=options[:25],
        )

        async def draft_callback(sel_int: discord.Interaction):
            tid = int(sel_int.data["values"][0])
            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute(
                "SELECT tp.discord_id, tp.tier, u.username "
                "FROM tournament_players tp "
                "LEFT JOIN users u ON u.discord_id = tp.discord_id "
                "WHERE tp.tournament_id=?",
                (tid,),
            )
            players = cur2.fetchall()
            conn2.close()

            if len(players) < 2:
                return await sel_int.response.send_message(f"可用玩家不足 (至少2人) / Need at least 2 players ({len(players)}).", ephemeral=True)

            available_players = []
            for r in players:
                tier_key = r["tier"].upper() if r["tier"] else "UNRANKED"
                r_score = TIER_SCORE.get(tier_key, 1)
                display_name = r["username"] if r["username"] else r["discord_id"]
                available_players.append((r["discord_id"], display_name, tier_key, r_score))

            view = DraftSetupView(tid, available_players, self.guild)
            embed = view.build_embed()
            await sel_int.response.send_message(embed=embed, view=view, ephemeral=False)

        select.callback = draft_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    async def _report_score(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM tournaments WHERE status='active' ORDER BY id DESC LIMIT 25"
        )
        tournaments = cur.fetchall()
        conn.close()

        if not tournaments:
            return await interaction.followup.send("没有进行中的锦标赛 / No active tournaments.", ephemeral=True)

        options = []
        for t in tournaments:
            options.append(discord.SelectOption(
                label=t["name"][:100],
                value=str(t["id"]),
                description=f"ID: {t['id']}",
            ))

        select = discord.ui.Select(
            placeholder="选择锦标赛 / Select a tournament...",
            options=options[:25],
        )

        async def report_callback(sel_int: discord.Interaction):
            tid = int(sel_int.data["values"][0])
            view = ReportView(tid, str(sel_int.user.id), self.guild)
            await sel_int.response.send_message(
                "选择你的比赛并上报比分 / Select your match and report score:",
                view=view,
                ephemeral=True,
            )

        select.callback = report_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    async def _tournament_standings(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM tournaments WHERE status IN ('active','completed') ORDER BY id DESC LIMIT 25"
        )
        tournaments = cur.fetchall()
        conn.close()

        if not tournaments:
            return await interaction.followup.send("没有可查看的锦标赛 / No tournaments.", ephemeral=True)

        options = []
        for t in tournaments:
            options.append(discord.SelectOption(
                label=t["name"][:100],
                value=str(t["id"]),
                description=f"ID: {t['id']}",
            ))

        select = discord.ui.Select(
            placeholder="选择锦标赛 / Select a tournament...",
            options=options[:25],
        )

        async def standings_callback(sel_int: discord.Interaction):
            tid = int(sel_int.data["values"][0])
            conn2 = get_db(); cur2 = conn2.cursor()
            t = get_tournament_or_none(cur2, tid)
            cur2.execute(
                "SELECT tp.discord_id, tp.wins, tp.losses, tp.draws, tp.points, tp.tier, u.username "
                "FROM tournament_players tp "
                "LEFT JOIN users u ON u.discord_id = tp.discord_id "
                "WHERE tp.tournament_id=? "
                "ORDER BY tp.points DESC, tp.wins DESC",
                (tid,),
            )
            rows = cur2.fetchall()
            conn2.close()

            if not rows:
                return await sel_int.response.send_message("暂无玩家数据 / No player data.", ephemeral=True)

            embed = discord.Embed(
                title=f"Standings — {t['name']}",
                color=discord.Color.gold(),
            )
            lines = ["` #   Player             W-L    Pts`"]
            for i, r in enumerate(rows, 1):
                name = (r["username"] if r["username"] else r["discord_id"])[:16]
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f" #{i}"
                lines.append(
                    f"{medal} `{name:<16} {r['wins']}-{r['losses']}  {r['points']:>4}`"
                )
            embed.description = "\n".join(lines)
            await sel_int.response.send_message(embed=embed, ephemeral=True)

        select.callback = standings_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    async def _tournament_bracket(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM tournaments WHERE status IN ('active','completed') ORDER BY id DESC LIMIT 25"
        )
        tournaments = cur.fetchall()
        conn.close()

        if not tournaments:
            return await interaction.followup.send("没有可查看的锦标赛 / No tournaments.", ephemeral=True)

        options = []
        for t in tournaments:
            options.append(discord.SelectOption(
                label=t["name"][:100],
                value=str(t["id"]),
                description=f"ID: {t['id']}",
            ))

        select = discord.ui.Select(
            placeholder="选择锦标赛 / Select a tournament...",
            options=options[:25],
        )

        async def bracket_callback(sel_int: discord.Interaction):
            tid = int(sel_int.data["values"][0])
            conn2 = get_db(); cur2 = conn2.cursor()
            t = get_tournament_or_none(cur2, tid)
            from collections import defaultdict
            cur2.execute(
                "SELECT * FROM tournament_matches WHERE tournament_id=? ORDER BY round, match_index",
                (tid,),
            )
            matches = cur2.fetchall()
            conn2.close()

            if not matches:
                return await sel_int.response.send_message("暂无对阵数据 / No bracket data.", ephemeral=True)

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
                    a_name = _display_name(self.guild, m["player_a_id"])
                    if m["player_b_id"]:
                        b_name = _display_name(self.guild, m["player_b_id"])
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
                        lines.append(
                            f"`#{m['id']}` {a_name} — BYE"
                        )
                embed.add_field(
                    name=f"Round {rnd}",
                    value="\n".join(lines) if lines else "(空)",
                    inline=False,
                )

            await sel_int.response.send_message(embed=embed, ephemeral=True)

        select.callback = bracket_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    # ═══════════════════ Page 3 — Player ═══════════════════

    async def _profile(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        target = interaction.user

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT score, mmr FROM users WHERE discord_id=?", (uid,))
        ur = cur.fetchone()
        coins = ur["score"] if ur else 0
        mmr = ur["mmr"] if (ur and ur["mmr"]) else 1000

        cur.execute("SELECT streak FROM daily_checkin WHERE discord_id=?", (uid,))
        sr = cur.fetchone()
        streak = sr["streak"] if sr else 0

        cur.execute("SELECT COUNT(*) as cnt FROM tournament_players WHERE discord_id=?", (uid,))
        total_matches = cur.fetchone()["cnt"]
        cur.execute("SELECT COALESCE(SUM(wins), 0) as wins, COALESCE(SUM(losses), 0) as losses FROM tournament_players WHERE discord_id=?", (uid,))
        wr = cur.fetchone()
        wins = wr["wins"]
        losses = wr["losses"]
        total_played = wins + losses
        win_rate = f"{wins / total_played * 100:.1f}%" if total_played > 0 else "N/A"

        cur.execute("SELECT COUNT(*) as cnt FROM user_achievements WHERE user_id=?", (uid,))
        ach_ct = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM user_inventory WHERE user_id=? AND quantity > 0", (uid,))
        inv_ct = cur.fetchone()["cnt"]
        conn.close()

        embed = discord.Embed(
            title=f"{target.display_name}'s Profile / 资料卡",
            color=discord.Color.blue(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Coins / 金币", value=str(coins), inline=True)
        embed.add_field(name="MMR", value=str(mmr), inline=True)
        embed.add_field(name="Streak / 签到连胜", value=f"{streak} days", inline=True)
        embed.add_field(name="Matches / 比赛数", value=str(total_matches), inline=True)
        embed.add_field(name="Win Rate / 胜率", value=win_rate, inline=True)
        embed.add_field(name="Achievements / 成就", value=f"{ach_ct}", inline=True)
        embed.add_field(name="Items / 道具", value=str(inv_ct), inline=True)
        embed.set_footer(text="View others: /gmpt-profile @user")

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _history(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            SELECT tp.tournament_id, tp.wins, tp.losses, tp.draws,
                   t.name as match_name, t.created_at,
                   r.team_id, rt.name as team_name
            FROM tournament_players tp
            JOIN tournaments t ON t.id = tp.tournament_id
            LEFT JOIN registrations r ON r.tournament_id = tp.tournament_id AND r.discord_id = tp.discord_id
            LEFT JOIN teams rt ON rt.id = r.team_id
            WHERE tp.discord_id=? AND t.status='finished'
            ORDER BY t.created_at DESC LIMIT 5
        """, (uid,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return await interaction.followup.send("No match history. / 暂无比赛记录。", ephemeral=True)

        embed = discord.Embed(
            title=f"Match History / 比赛历史 — {interaction.user.display_name}",
            color=discord.Color.blue(),
        )
        for r in rows:
            date_str = r["created_at"][:10] if r["created_at"] else "N/A"
            w = r["wins"] or 0
            l = r["losses"] or 0
            d = r["draws"] or 0
            if w > l:
                result = "win"
                icon = "🟢"
            elif l > w:
                result = "loss"
                icon = "🔴"
            else:
                result = "draw"
                icon = "⚪"
            embed.add_field(
                name=f"#{r['tournament_id']} — {r['match_name']}",
                value=f"{date_str} | {icon} {result.upper()} | {r['team_name'] or 'N/A'}",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _weekly(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d")

        cur.execute("SELECT id, week_start FROM weekly_challenges WHERE week_start <= ? ORDER BY week_start DESC LIMIT 1", (now_str,))
        latest = cur.fetchone()
        week_start = now_str
        if not latest or latest["week_start"] < week_start:
            # Auto-generate weekly challenges — seed from a curated pool
            import random as _random
            seed_challenges = [
                {"title": "参加3场比赛 / Play 3 matches", "desc": "参加3场比赛", "reward": 150, "target": 3, "task_type": "play_match"},
                {"title": "赢得2场比赛 / Win 2 matches", "desc": "赢得2场比赛", "reward": 200, "target": 2, "task_type": "win_match"},
                {"title": "在频道聊天50条 / Send 50 messages", "desc": "发送50条消息", "reward": 100, "target": 50, "task_type": "send_message"},
                {"title": "语音通话2小时 / Voice 2hrs", "desc": "语音通话120分钟", "reward": 150, "target": 120, "task_type": "voice_time"},
                {"title": "邀请1位新朋友 / Invite 1 friend", "desc": "邀请1位新朋友", "reward": 300, "target": 1, "task_type": "invite"},
                {"title": "使用3次道具 / Use 3 items", "desc": "使用3次道具", "reward": 100, "target": 3, "task_type": "use_item"},
                {"title": "连续签到3天 / Check in 3 days", "desc": "连续签到3天", "reward": 120, "target": 3, "task_type": "checkin_streak"},
                {"title": "赠送1次金币 / Gift coins once", "desc": "赠送金币1次", "reward": 80, "target": 1, "task_type": "gift_coins"},
                {"title": "下注2场比赛 / Bet on 2 matches", "desc": "下注2场比赛", "reward": 150, "target": 2, "task_type": "place_bet"},
            ]
            selected = _random.sample(seed_challenges, min(3, len(seed_challenges)))
            for ch in selected:
                cur.execute(
                    "INSERT INTO weekly_challenges (week_start, title, description, reward, target, task_type) VALUES (?,?,?,?,?,?)",
                    (week_start, ch["title"], ch["desc"], ch["reward"], ch["target"], ch["task_type"]),
                )
            conn.commit()
        else:
            week_start = latest["week_start"]

        cur.execute("""
            SELECT wc.id, wc.title, wc.description, wc.reward, wc.target, wc.task_type,
                   COALESCE(uc.progress, 0) as progress, COALESCE(uc.completed, 0) as completed
            FROM weekly_challenges wc
            LEFT JOIN user_challenges uc ON uc.challenge_id = wc.id AND uc.discord_id = ?
            WHERE wc.week_start = ?
            ORDER BY wc.id
        """, (uid, week_start))
        challenges = cur.fetchall()
        conn.commit(); conn.close()

        if not challenges:
            return await interaction.followup.send("No challenges this week. / 本周暂无挑战。", ephemeral=True)

        embed = discord.Embed(
            title="Weekly Challenges / 每周挑战",
            description=f"Week of {week_start}",
            color=discord.Color.purple(),
        )
        for ch in challenges:
            prog = ch["progress"]
            target = ch["target"]
            done = "✅" if ch["completed"] else "⬜"
            bar = "█" * min(prog, target) + "░" * max(0, target - prog)
            embed.add_field(
                name=f"{done} {ch['title']} (+{ch['reward']}g)",
                value=f"Progress: {prog}/{target} [{bar}]",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _season(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            SELECT discord_id, mmr, wins, losses
            FROM season_standings ORDER BY mmr DESC LIMIT 10
        """)
        rows = cur.fetchall(); conn.close()

        if not rows:
            return await interaction.followup.send("No season data yet. / 暂无赛季数据。", ephemeral=True)

        embed = discord.Embed(title="Season Standings / 赛季排行", color=discord.Color.gold())
        lines = []
        for i, r in enumerate(rows, 1):
            name = resolve_name(interaction.guild, r["discord_id"]) or str(r["discord_id"])
            lines.append(f"{i}. {name} — MMR:{r['mmr']} | W:{r['wins']} L:{r['losses']}")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _mvp_lb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            SELECT discord_id, SUM(wins) as total_wins, SUM(points) as total_points
            FROM tournament_players
            GROUP BY discord_id ORDER BY total_wins DESC LIMIT 10
        """)
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return await interaction.followup.send("暂无数据 / No data yet.", ephemeral=True)

        embed = discord.Embed(title="Wins Leaderboard / 胜场排行榜", color=discord.Color.gold())
        lines = []
        for i, r in enumerate(rows, 1):
            name = resolve_name(self.guild, r["discord_id"])
            lines.append(f"{i}. **{name}** — {r['total_wins']} Wins | {r['total_points']} Pts")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    # ═══════════════════ Page 4 — Economy ═══════════════════

    async def _shop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        bal = get_balance(uid)

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id, name, description, price, item_type, category FROM shop_items ORDER BY price")
        all_items = [dict(r) for r in cur.fetchall()]
        conn.close()

        if not all_items:
            return await interaction.followup.send("Shop is empty.", ephemeral=True)

        categories = list(dict.fromkeys(it.get("category", "Other") for it in all_items))
        embed = discord.Embed(title="Item Shop", description=f"Your balance: {bal} coins\nSelect a category:", color=0xFFD700)
        await interaction.followup.send(embed=embed, view=MainMenuView(all_items, categories, uid, bal), ephemeral=True)

    async def _inventory(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            SELECT inv.item_id, si.name, si.description, inv.quantity
            FROM user_inventory inv
            JOIN shop_items si ON si.id = inv.item_id
            WHERE inv.user_id=? AND inv.quantity > 0
        """, (uid,))
        rows = cur.fetchall(); conn.close()

        if not rows:
            return await interaction.followup.send(
                "Backpack is empty. / 背包是空的。", ephemeral=True
            )

        lines = ["**Backpack / 背包**\n"]
        for r in rows:
            lines.append(f"`#{r['item_id']}` **{r['name']}** x{r['quantity']} — {r['description']}")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    async def _balance(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        bal = get_balance(uid)
        await interaction.followup.send(
            f"💰 **Balance / 余额**\n{interaction.user.mention}: 🪙 **{bal}** coins",
            ephemeral=True,
        )

    async def _gift(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        class GiftAmountModal(discord.ui.Modal, title="Gift Coins"):
            amount = discord.ui.TextInput(
                label="Amount",
                placeholder="Enter amount",
                max_length=6,
                required=True,
            )
            def __init__(self, target_member):
                super().__init__()
                self.target_member = target_member
            async def on_submit(self, modal_int: discord.Interaction):
                try:
                    amt = int(self.amount.value)
                except ValueError:
                    return await modal_int.response.send_message("Invalid amount.", ephemeral=True)
                if amt <= 0:
                    return await modal_int.response.send_message("Amount must be positive.", ephemeral=True)
                sender = str(modal_int.user.id)
                receiver = str(self.target_member.id)
                sbal = get_balance(sender)
                if sbal < amt:
                    return await modal_int.response.send_message(
                        f"Insufficient balance! You have {sbal} coins.", ephemeral=True
                    )
                add_coins(sender, -amt, f"Gift to {self.target_member.display_name}")
                add_coins(receiver, amt, f"Gift from {modal_int.user.display_name}")
                new_bal = get_balance(sender)
                await modal_int.response.send_message(
                    f"Sent {amt} coins to {self.target_member.mention}. Balance: {new_bal}",
                    ephemeral=True,
                )

        class GiftUserSelect(discord.ui.UserSelect):
            def __init__(self):
                super().__init__(placeholder="Select recipient", min_values=1, max_values=1)
            async def callback(self, sel_int: discord.Interaction):
                target = self.values[0]
                if target.bot:
                    return await sel_int.response.send_message("不能给机器人送礼 / Cannot gift to a bot.", ephemeral=True)
                if target.id == sel_int.user.id:
                    return await sel_int.response.send_message("不能给自己送礼 / Cannot gift to yourself.", ephemeral=True)
                await sel_int.response.send_modal(GiftAmountModal(target))

        view = discord.ui.View(timeout=60)
        view.add_item(GiftUserSelect())
        await interaction.followup.send("Select recipient to gift coins:", view=view, ephemeral=True)

    async def _transactions(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT amount, reason, created_at FROM transactions WHERE discord_id=? ORDER BY id DESC LIMIT 10",
            (uid,),
        )
        rows = cur.fetchall(); conn.close()

        if not rows:
            return await interaction.followup.send("No transactions yet.", ephemeral=True)

        embed = discord.Embed(title="Transactions", color=discord.Color.blue())
        lines = []
        for r in rows:
            sign = "+" if r["amount"] >= 0 else ""
            lines.append(f"`{r['created_at'][:16]}` {sign}{r['amount']} - {r['reason']}")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _achievements(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()

        # seed if needed
        cur.execute("SELECT COUNT(*) as cnt FROM achievements")
        if cur.fetchone()["cnt"] == 0:
            from cogs.economy import ACHIEVEMENTS as _ACH
            for a in _ACH:
                cur.execute("INSERT INTO achievements (name, description, reward, hidden) VALUES (?,?,?,?)",
                            (a[0], a[1], a[2], a[3]))
            conn.commit()

        cur.execute("""
            SELECT a.id, a.name, a.description, a.reward,
                   CASE WHEN ua.user_id IS NOT NULL THEN 1 ELSE 0 END as unlocked
            FROM achievements a
            LEFT JOIN user_achievements ua ON ua.achievement_id = a.id AND ua.user_id=?
            ORDER BY a.id
        """, (uid,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        unlocked_ct = sum(1 for r in rows if r["unlocked"])
        total_ct = len(rows)

        embed = discord.Embed(title="Achievements", color=0x00DC82)
        embed.add_field(name="Progress", value=f"{unlocked_ct} / {total_ct} Unlocked", inline=False)
        parts = []
        for r in rows:
            if r["unlocked"]:
                parts.append(f":white_check_mark: **{r['name']}** - {r['description']} (+{r['reward']}g)")
            else:
                parts.append(f":black_large_square: {r['name']} - {r['description']} (+{r['reward']}g)")
        value = "\n".join(parts[:20])
        if len(value) > 1024:
            value = value[:1020] + "..."
        embed.add_field(name="", value=value, inline=False)
        if total_ct > 20:
            embed.set_footer(text=f"Showing first 20 of {total_ct}. Use /gmpt-achievements for full list.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _daily(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        myt = timezone(timedelta(hours=8))
        today = datetime.now(myt).strftime("%Y-%m-%d")

        # Get daily config
        cur.execute("SELECT value FROM daily_config WHERE key='minutes'")
        min_row = cur.fetchone()
        target_minutes = int(min_row["value"]) if min_row else 30
        cur.execute("SELECT value FROM daily_config WHERE key='reward'")
        rew_row = cur.fetchone()
        base_reward = int(rew_row["value"]) if rew_row else 50

        # Get today's voice minutes
        cur.execute("SELECT voice_minutes, claimed, reward_amount FROM daily_rewards WHERE discord_id=? AND date=?", (uid, today))
        dr = cur.fetchone()
        voice_mins = dr["voice_minutes"] if dr else 0
        claimed = dr["claimed"] if dr else 0
        reward_amount = dr["reward_amount"] if dr else 0

        # Calculate streak
        cur.execute("SELECT streak FROM daily_checkin WHERE discord_id=?", (uid,))
        streak_row = cur.fetchone()
        streak = streak_row["streak"] if streak_row else 0

        # Calculate milestone bonus
        milestone_bonus = 0
        for days, bonus in [(7, 200), (14, 350), (21, 500), (30, 1000), (60, 2000), (100, 5000)]:
            if streak > 0 and streak % days == 0:
                milestone_bonus = bonus
                break

        progress_pct = min(100, int(voice_mins / target_minutes * 100)) if target_minutes > 0 else 100
        bar = "█" * (progress_pct // 10) + "░" * (10 - progress_pct // 10)

        if claimed:
            status_line = f"✅ Claimed / 已领取 — +{reward_amount} coins\n"
        elif voice_mins >= target_minutes:
            status_line = f"🎁 Ready to claim / 可领取 — {base_reward} coins\n"
        else:
            status_line = f"⏳ Not yet / 未达标 — need {target_minutes} mins\n"

        embed = discord.Embed(
            title="🗓️ Daily Reward / 每日奖励",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name=f"Voice Progress / 语音进度 [{progress_pct}%]",
            value=f"{bar}\n{voice_mins} / {target_minutes} minutes",
            inline=False,
        )
        embed.add_field(name="Status / 状态", value=status_line, inline=False)
        embed.add_field(name="Base Reward / 基础奖励", value=f"{base_reward} coins", inline=True)
        embed.add_field(name="Streak / 连胜", value=f"{streak} days", inline=True)
        if milestone_bonus > 0:
            embed.add_field(name="Milestone Bonus / 里程碑奖励", value=f"+{milestone_bonus} coins", inline=True)
        embed.set_footer(text="Use /gmpt-daily claim to claim | 使用 /gmpt-daily claim 领取")
        conn.close()
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _giveaway(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id, prize, draw_at FROM giveaways WHERE drawn=0 ORDER BY id DESC LIMIT 1")
        gw = cur.fetchone()

        if gw:
            cur.execute("SELECT COUNT(*) as cnt FROM giveaway_entries WHERE giveaway_id=?", (gw["id"],))
            entry_count = cur.fetchone()["cnt"]
            cur.execute("SELECT tickets FROM giveaway_tickets WHERE discord_id=?", (uid,))
            tix_row = cur.fetchone()
            user_tickets = tix_row["tickets"] if tix_row else 0
            conn.close()

            embed = discord.Embed(
                title="🎟️ Active Giveaway / 活动抽奖",
                description=(
                    f"**Prize / 奖品:** {gw['prize']}\n"
                    f"**Draw Time / 开奖时间:** {gw['draw_at']}\n"
                    f"**Entries / 参与条目:** {entry_count}\n"
                    f"**Your Tickets / 你的抽奖券:** {user_tickets}"
                ),
                color=0xFFD700,
            )
            embed.set_footer(text=f"Giveaway #{gw['id']} | Use /gmpt-giveaway enter {gw['id']} to enter with tickets")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            conn.close()
            await interaction.followup.send(
                "No active giveaway. / 暂无活动抽奖。\n"
                "Get tickets from `/gmpt-shop` / 去商店购买抽奖券: `/gmpt-shop`",
                ephemeral=True,
            )

    # ═══════════════════ Page 5 — Tools ═══════════════════

    async def _voice_lb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT user_id, total_seconds, login_days, total_joins "
            "FROM voice_tracker ORDER BY total_seconds DESC"
        )
        data = cur.fetchall()
        conn.close()

        if not data:
            return await interaction.followup.send("No voice data yet.", ephemeral=True)

        from cogs.voice_tracker import VoiceLeaderboardView
        view = VoiceLeaderboardView()
        embed = VoiceLeaderboardView._build_embed(data, 0, interaction.guild)
        view.prev_btn.disabled = True
        view.next_btn.disabled = len(data) <= 10
        await interaction.followup.send(embed=embed, view=view)

    async def _queue_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM queue WHERE status='waiting'")
        row = cur.fetchone()
        conn.close()
        await interaction.followup.send(
            f"🔊 **Queue Status / 排队状态**\n{row['cnt']} players in queue / 人在排队。\nUse `/gmpt-queue` to join.",
            ephemeral=True,
        )

    async def _all_players(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self._show_players_page(interaction, page=0, search_term=None)

    async def _show_players_page(self, interaction: discord.Interaction, page: int, search_term: str = None):
        """分页展示玩家列表，每页 20 条。search_term 可选模糊搜索。"""
        per_page = 20
        conn = get_db()
        try:
            cur = conn.cursor()
            if search_term:
                like_term = f"%{search_term}%"
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM registrations r "
                    "LEFT JOIN users u ON u.discord_id = r.discord_id "
                    "WHERE u.username LIKE ?",
                    (like_term,),
                )
                total = cur.fetchone()["cnt"]
                cur.execute(
                    "SELECT DISTINCT r.discord_id, u.username, u.mmr FROM registrations r "
                    "LEFT JOIN users u ON u.discord_id = r.discord_id "
                    "WHERE u.username LIKE ? "
                    "ORDER BY u.mmr DESC LIMIT ? OFFSET ?",
                    (like_term, per_page, page * per_page),
                )
            else:
                cur.execute("SELECT COUNT(DISTINCT r.discord_id) as cnt FROM registrations r")
                total = cur.fetchone()["cnt"]
                cur.execute(
                    "SELECT DISTINCT r.discord_id, u.username, u.mmr FROM registrations r "
                    "LEFT JOIN users u ON u.discord_id = r.discord_id "
                    "ORDER BY u.mmr DESC LIMIT ? OFFSET ?",
                    (per_page, page * per_page),
                )
            rows = cur.fetchall()
        finally:
            conn.close()

        if not rows:
            return await interaction.followup.send("No registered players found.", ephemeral=True)

        total_pages = max(1, (total + per_page - 1) // per_page)

        embed = discord.Embed(
            title=f"All Players{f' (search: {search_term})' if search_term else ''}",
            color=discord.Color.blue(),
        )
        lines = []
        for i, row in enumerate(rows, 1):
            name = row["username"] if row["username"] else row["discord_id"]
            mmr = row["mmr"] or 1000
            lines.append(f"{page * per_page + i}. {name} - MMR {mmr}")
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Page {page+1}/{total_pages} | Total: {total} players")

        dashboard_self = self  # 捕获外层 DashboardView 引用

        class PlayerPagerView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=120)
                if page <= 0:
                    self.prev_btn.disabled = True
                if page >= total_pages - 1:
                    self.next_btn.disabled = True

            @discord.ui.button(label="⬅️ 上一页", style=discord.ButtonStyle.secondary)
            async def prev_btn(self, btn_int: discord.Interaction, button):
                await btn_int.response.defer()
                await dashboard_self._show_players_page(btn_int, page - 1, search_term)

            @discord.ui.button(label="下一页 ➡️", style=discord.ButtonStyle.secondary)
            async def next_btn(self, btn_int: discord.Interaction, button):
                await btn_int.response.defer()
                await dashboard_self._show_players_page(btn_int, page + 1, search_term)

            @discord.ui.button(label="🔍 搜索", style=discord.ButtonStyle.primary)
            async def search_btn(self, btn_int: discord.Interaction, button):
                class SearchModal(discord.ui.Modal, title="搜索玩家 / Search Player"):
                    keyword = discord.ui.TextInput(
                        label="用户名关键词 / Username keyword",
                        placeholder="输入用户名部分内容...",
                        required=True,
                        max_length=50,
                    )
                    async def on_submit(self, modal_int: discord.Interaction):
                        await modal_int.response.defer()
                        await dashboard_self._show_players_page(modal_int, 0, self.keyword.value.strip())

                await btn_int.response.send_modal(SearchModal())

        view = PlayerPagerView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def _admin(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("仅管理员可使用 / Admin only.", ephemeral=True)
        await interaction.followup.send(
            "🔒 **Admin Panel / 管理面板**\n"
            "`/gmpt-admin-coins` — Manage coins / 管理金币\n"
            "`/gmpt-season-start` — Start season / 开启赛季\n"
            "`/gmpt-season-end` — End season / 结束赛季\n"
            "`/gmpt-mmr-reset` — Reset MMR / 重置MMR",
            ephemeral=True,
        )

    # ═══════════════════ Page 2 — Tournament History ═══════════════════

    async def _tournament_history(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name, status, max_teams, team_size, created_at "
            "FROM tournaments WHERE status='finished' ORDER BY created_at DESC LIMIT 10"
        )
        rows = cur.fetchall(); conn.close()

        if not rows:
            return await interaction.followup.send(
                "No finished tournaments yet. / 暂无已完成的赛事。", ephemeral=True
            )

        embed = discord.Embed(
            title="Tournament History / 赛事记录",
            color=discord.Color.blue(),
        )
        for r in rows:
            created = r["created_at"][:10] if r["created_at"] else "N/A"
            embed.add_field(
                name=f"#{r['id']} — {r['name']}",
                value=f"{r['team_size']}v{r['team_size']} | {r['max_teams']} teams | {created}",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ═══════════════════ Page 3 — Stats ═══════════════════

    async def _stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()

        # MMR + coins
        cur.execute("SELECT score, mmr FROM users WHERE discord_id=?", (uid,))
        ur = cur.fetchone()
        mmr = ur["mmr"] if (ur and ur["mmr"]) else 1000
        coins = ur["score"] if ur else 0

        # Tournament stats
        cur.execute(
            "SELECT COALESCE(SUM(wins),0), COALESCE(SUM(losses),0), COALESCE(SUM(draws),0), "
            "COALESCE(SUM(points),0), COUNT(*) "
            "FROM tournament_players WHERE discord_id=?",
            (uid,),
        )
        tr = cur.fetchone()
        tw, tl, td, tp, tm = tr[0], tr[1], tr[2], tr[3], tr[4]

        # Season rank
        cur.execute(
            "SELECT rank FROM season_standings WHERE discord_id=? ORDER BY id DESC LIMIT 1",
            (uid,),
        )
        sr = cur.fetchone()
        season_rank = sr["rank"] if sr else "Unranked"

        # Achievements
        cur.execute("SELECT COUNT(*) FROM user_achievements WHERE user_id=?", (uid,))
        ach_ct = cur.fetchone()[0]
        conn.close()

        total_played = tw + tl + td
        win_rate = f"{tw / total_played * 100:.1f}%" if total_played > 0 else "N/A"

        embed = discord.Embed(
            title=f"Stats / 数据总览 — {interaction.user.display_name}",
            color=discord.Color.blue(),
        )
        embed.add_field(name="🎯 MMR", value=str(mmr), inline=True)
        embed.add_field(name="🪙 Coins / 金币", value=str(coins), inline=True)
        embed.add_field(name="🎖️ Season Rank / 赛季段位", value=season_rank, inline=True)
        embed.add_field(name="🎮 Matches / 总场次", value=str(tm), inline=True)
        embed.add_field(name="✅ Wins / 胜", value=str(tw), inline=True)
        embed.add_field(name="❌ Losses / 负", value=str(tl), inline=True)
        embed.add_field(name="🤝 Draws / 平", value=str(td), inline=True)
        embed.add_field(name="📊 Win Rate / 胜率", value=win_rate, inline=True)
        embed.add_field(name="⭐ Achievements / 成就", value=str(ach_ct), inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _ranks(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT r.discord_id, u.username "
            "FROM registrations r LEFT JOIN users u ON u.discord_id = r.discord_id "
            "ORDER BY u.username"
        )
        rows = cur.fetchall()

        if not rows:
            conn.close()
            return await interaction.followup.send(
                "No registered players. / 暂无已报名玩家。", ephemeral=True
            )

        lines = []
        for i, row in enumerate(rows, 1):
            uid = row["discord_id"]
            name = row["username"] if row["username"] else uid

            cur.execute(
                "SELECT summoner_name, tag_line, region "
                "FROM player_riot WHERE discord_id=?",
                (uid,),
            )
            riot = cur.fetchone()

            if not riot:
                lines.append(f"{i}. {name} — Not linked / 未关联")
            else:
                region_label = riot["region"].upper()
                lines.append(
                    f"{i}. {name} — {riot['summoner_name']}#{riot['tag_line']} "
                    f"({region_label})"
                )

        conn.close()

        embed = discord.Embed(
            title="Player Ranks / 段位列表",
            description="\n".join(lines),
            color=discord.Color.purple(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ═══════════════════ Page 5 — MMR LB + Announce ═══════════════════

    async def _mmr_lb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT discord_id, username, mmr FROM users "
            "WHERE mmr IS NOT NULL ORDER BY mmr DESC LIMIT 10"
        )
        rows = cur.fetchall(); conn.close()

        if not rows:
            return await interaction.followup.send("No MMR data yet. / 暂无MMR数据。", ephemeral=True)

        embed = discord.Embed(
            title="MMR Leaderboard / MMR 排行榜",
            color=discord.Color.gold(),
        )
        lines = []
        for i, r in enumerate(rows, 1):
            name = r["username"] or r["discord_id"]
            mmr = r["mmr"] or 1000
            lines.append(f"{i}. **{name}** — {mmr} MMR")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _announce(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.followup.send(
                "You need **Manage Messages** permission. / 需要 **管理消息** 权限。",
                ephemeral=True,
            )
        await interaction.followup.send(
            "📢 **Announce / 发送公告**\n"
            "Use `/announce` command to send a styled announcement.\n"
            "使用 `/announce` 命令发送公告。\n\n"
            "**Usage / 用法:**\n"
            "`/announce title:标题 content:内容 [channel:目标频道]`",
            ephemeral=True,
        )

    # ── Page 2 补位: 定时赛事 ──
    async def _scheduled_event(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.defer(ephemeral=True)
            return await interaction.followup.send("管理员专用 / Admin only.", ephemeral=True)

        class ScheduledEventModal(discord.ui.Modal, title="新建定时赛事 / New Scheduled Event"):
            event_name = discord.ui.TextInput(
                label="赛事名称 / Event Name",
                placeholder="e.g. 周五晚内部赛",
                required=True,
                max_length=100,
            )
            cron_expr = discord.ui.TextInput(
                label="Cron 表达式 / Cron Expression",
                placeholder="e.g. 30 20 * * 5 (周五20:30)",
                required=True,
                max_length=32,
            )
            template_id = discord.ui.TextInput(
                label="模板ID (可选) / Template ID (optional)",
                placeholder="留空则使用默认设置",
                required=False,
                max_length=10,
            )
            channel_id = discord.ui.TextInput(
                label="发布频道ID / Channel ID (可选)",
                placeholder="留空则使用当前频道",
                required=False,
                max_length=20,
            )

            async def on_submit(self, modal_int: discord.Interaction):
                await modal_int.response.defer(ephemeral=True)
                name = self.event_name.value.strip()
                cron = self.cron_expr.value.strip()
                tpl = self.template_id.value.strip()
                ch = self.channel_id.value.strip() or str(modal_int.channel_id)

                # Basic cron validation: 5 fields
                if len(cron.split()) != 5:
                    return await modal_int.followup.send(
                        "❌ Cron 表达式格式错误，需要 5 个字段 (分 时 日 月 周)。",
                        ephemeral=True,
                    )
                tid = int(tpl) if tpl else None

                conn = get_db()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO scheduled_events (event_name, cron_expr, template_id, channel_id, created_by) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (name, cron, tid, ch, str(modal_int.user.id)),
                    )
                    conn.commit()
                finally:
                    conn.close()

                await modal_int.followup.send(
                    f"✅ 定时赛事已创建 / Scheduled event created:\n"
                    f"**名称**: {name}\n**Cron**: `{cron}`\n**频道**: <#{ch}>",
                    ephemeral=True,
                )

        await interaction.response.send_modal(ScheduledEventModal())

    # ── Page 3 补位: 连胜王 ──
    async def _win_streak(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT discord_id, username, win_streak FROM users "
            "WHERE win_streak IS NOT NULL AND win_streak > 0 "
            "ORDER BY win_streak DESC LIMIT 10"
        )
        rows = cur.fetchall(); conn.close()

        if not rows:
            return await interaction.followup.send(
                "暂无连胜记录 / No win streak data yet.", ephemeral=True
            )

        embed = discord.Embed(
            title="🔥 连胜王 / Win Streak Leaderboard",
            color=discord.Color.orange(),
        )
        lines = []
        for i, r in enumerate(rows, 1):
            name = r["username"] or r["discord_id"]
            streaks = r["win_streak"] or 0
            lines.append(f"{i}. **{name}** — {streaks} 连胜 / Win Streak")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Page 5 补位: 数据导出 ──
    async def _export_data(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.defer(ephemeral=True)
            return await interaction.followup.send("管理员专用 / Admin only.", ephemeral=True)

        class ExportModal(discord.ui.Modal, title="导出数据 / Export Data"):
            export_type = discord.ui.TextInput(
                label="导出类型 (players/matches/transactions)",
                placeholder="players, matches, transactions (逗号分隔)",
                required=True,
                max_length=100,
            )

            async def on_submit(self, modal_int: discord.Interaction):
                await modal_int.response.defer(ephemeral=True)
                import csv as _csv
                import os as _os
                import io

                types = [t.strip().lower() for t in self.export_type.value.split(",")]
                valid = {"players", "matches", "transactions"}
                selected = [t for t in types if t in valid]
                if not selected:
                    return await modal_int.followup.send(
                        "无效类型。支持: players, matches, transactions", ephemeral=True
                    )

                temp_dir = _os.path.join(
                    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                    "temp",
                )
                _os.makedirs(temp_dir, exist_ok=True)

                files_sent = []
                conn = get_db()
                try:
                    cur = conn.cursor()
                    for etype in selected:
                        if etype == "players":
                            cur.execute(
                                "SELECT u.discord_id, u.username, u.mmr, u.score, "
                                "COUNT(r.id) as games "
                                "FROM users u LEFT JOIN registrations r ON u.discord_id=r.discord_id "
                                "GROUP BY u.discord_id ORDER BY u.mmr DESC"
                            )
                            rows = cur.fetchall()
                            csv_path = _os.path.join(temp_dir, f"players_export_{modal_int.user.id}.csv")
                            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                                w = _csv.writer(f)
                                w.writerow(["discord_id", "username", "mmr", "coins", "games_played"])
                                for r in rows:
                                    w.writerow([r["discord_id"], r["username"] or "", r["mmr"] or 1000, r["score"] or 0, r["games"] or 0])
                            files_sent.append(("players", csv_path))

                        elif etype == "matches":
                            cur.execute(
                                "SELECT id, name, status, max_teams, team_size, created_at "
                                "FROM tournaments ORDER BY created_at DESC LIMIT 500"
                            )
                            rows = cur.fetchall()
                            csv_path = _os.path.join(temp_dir, f"matches_export_{modal_int.user.id}.csv")
                            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                                w = _csv.writer(f)
                                w.writerow(["id", "name", "status", "max_teams", "team_size", "created_at"])
                                for r in rows:
                                    w.writerow([r["id"], r["name"], r["status"], r["max_teams"], r["team_size"], r["created_at"]])
                            files_sent.append(("matches", csv_path))

                        elif etype == "transactions":
                            cur.execute(
                                "SELECT id, discord_id, amount, reason, created_at "
                                "FROM transactions ORDER BY created_at DESC LIMIT 500"
                            )
                            rows = cur.fetchall()
                            csv_path = _os.path.join(temp_dir, f"transactions_export_{modal_int.user.id}.csv")
                            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                                w = _csv.writer(f)
                                w.writerow(["id", "discord_id", "amount", "reason", "created_at"])
                                for r in rows:
                                    w.writerow([r["id"], r["discord_id"], r["amount"], r["reason"], r["created_at"]])
                            files_sent.append(("transactions", csv_path))
                finally:
                    conn.close()

                if not files_sent:
                    return await modal_int.followup.send("没有数据可导出 / No data to export.", ephemeral=True)

                for label, fp in files_sent:
                    try:
                        await modal_int.followup.send(
                            f"📤 **{label}** 导出完成:",
                            file=discord.File(fp, f"{label}_export.csv"),
                            ephemeral=True,
                        )
                    except Exception as e:
                        logger.error(f"[Export] send file error: {e}")

                # 清理临时文件
                for _, fp in files_sent:
                    try:
                        _os.remove(fp)
                    except Exception:
                        pass

                await modal_int.followup.send(
                    f"✅ 导出完成! 共导出 {len(files_sent)} 个文件。", ephemeral=True
                )

        await interaction.response.send_modal(ExportModal())

    # ── Page 5 补位: 赛季重置 ──
    async def _season_reset(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.defer(ephemeral=True)
            return await interaction.followup.send("管理员专用 / Admin only.", ephemeral=True)

        class SeasonResetModal(discord.ui.Modal, title="赛季重置 / Season Reset"):
            season_label = discord.ui.TextInput(
                label="赛季标签 / Season Label",
                placeholder="e.g. S4-2026Q3",
                required=True,
                max_length=32,
            )

            async def on_submit(self, modal_int: discord.Interaction):
                await modal_int.response.defer(ephemeral=True)
                label = self.season_label.value.strip()
                try:
                    conn = get_db()
                    cur = conn.cursor()
                    # 1. 创建新赛季记录
                    cur.execute(
                        "INSERT INTO seasons (name, start_date, active) VALUES (?, datetime('now'), 1)",
                        (label,),
                    )
                    season_id = cur.lastrowid
                    # 2. 归档所有玩家当前 MMR/段位（从 users + mmr 表联合读取）
                    cur.execute(
                        "SELECT u.discord_id, u.mmr, u.games_played, "
                        "COALESCE(m.rank, 'Unranked') as rank_tier "
                        "FROM users u LEFT JOIN mmr m ON u.discord_id = m.discord_id"
                    )
                    players = cur.fetchall()
                    for p in players:
                        cur.execute(
                            "INSERT INTO season_history "
                            "(season_id, discord_id, mmr_before, mmr_after, rank_before, rank_after, games_played) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                season_id,
                                p["discord_id"],
                                p["mmr"] if p["mmr"] is not None else 1000,
                                1000,
                                p["rank_tier"] if p["rank_tier"] else "Unranked",
                                "Unranked",
                                p["games_played"] if p["games_played"] else 0,
                            ),
                        )
                    # 3. 重置所有玩家 MMR/段位
                    cur.execute("UPDATE users SET mmr=1000")
                    cur.execute("UPDATE mmr SET mmr=1000, rank='Unranked'")
                    conn.commit()
                    conn.close()

                    embed = discord.Embed(
                        title="🔄 赛季重置完成 / Season Reset Complete",
                        description=(
                            f"**赛季**: {label}\n"
                            f"**归档玩家数**: {len(players)}\n"
                            f"所有玩家 MMR 已重置为 1000，段位重置为 Unranked。"
                        ),
                        color=discord.Color.green(),
                    )
                    await modal_int.followup.send(embed=embed, ephemeral=True)
                    # 公告到当前频道
                    try:
                        await modal_int.channel.send(
                            f"📢 **新赛季开启**: {label}\n所有玩家 MMR 已重置，历史数据已归档。"
                        )
                    except Exception as e:
                        log_error("dashboard", "season_announce", e)
                except Exception as e:
                    log_error("dashboard", "season_reset", e)
                    await modal_int.followup.send(
                        "❌ 赛季重置失败 / Season reset failed.", ephemeral=True
                    )

        await interaction.response.send_modal(SeasonResetModal())

    # ── Page 5 补位: 比赛回放 ──
    async def _replay(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, status, created_at FROM tournaments "
            "WHERE status='finished' ORDER BY created_at DESC LIMIT 10"
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.followup.send("没有已结束的比赛 / No finished matches.", ephemeral=True)

        options = []
        for m in matches:
            options.append(discord.SelectOption(
                label=m["name"][:100],
                value=str(m["id"]),
                description=f"ID:{m['id']} | {m['created_at'][:10] if m['created_at'] else '?'}",
            ))

        select = discord.ui.Select(
            placeholder="选择比赛查看回放 / Select a match...",
            options=options[:25],
        )

        async def replay_select_cb(sel_int: discord.Interaction):
            mid = int(sel_int.data["values"][0])
            conn2 = get_db()
            cur2 = conn2.cursor()
            cur2.execute(
                "SELECT event_type, actor_id, target_id, team_id, timestamp, data "
                "FROM match_events WHERE tournament_id=? ORDER BY timestamp ASC",
                (mid,),
            )
            events = cur2.fetchall()
            conn2.close()

            if not events:
                return await sel_int.response.send_message(
                    "该比赛暂无回放数据 / No replay data for this match.", ephemeral=True
                )

            # 分页：每页 10 条
            pages = [events[i:i+10] for i in range(0, len(events), 10)]
            page_idx = [0]

            def build_embed(page):
                embed = discord.Embed(
                    title=f"🎬 比赛回放 — #{mid}",
                    description="",
                    color=discord.Color.blurple(),
                )
                lines = []
                for e in page:
                    ts = e["timestamp"][11:19] if e["timestamp"] else "--:--:--"
                    atype = e["event_type"]
                    if atype == "start":
                        lines.append(f"`{ts}` ⏯️ 比赛开始")
                    elif atype == "end":
                        lines.append(f"`{ts}` ⏹️ 比赛结束")
                    elif atype == "kill":
                        lines.append(
                            f"`{ts}` ⚔️ <@{e['actor_id']}> 击杀 <@{e['target_id']}>"
                        )
                    elif atype == "score_change":
                        d = e.get("data") and json_loads(e["data"]) if e["data"] else {}
                        lines.append(
                            f"`{ts}` 🏆 得分变更: <@{e['actor_id']}> "
                            f"+{d.get('delta', '?')}"
                        )
                embed.description = "\n".join(lines) if lines else "无事件"
                embed.set_footer(text=f"第 {page_idx[0]+1}/{len(pages)} 页 | 共 {len(events)} 条事件")
                return embed

            class ReplayPager(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=120)

                @discord.ui.button(label="⬅️ 上一页", style=discord.ButtonStyle.secondary, row=0)
                async def prev_btn(self, btn_int: discord.Interaction, button):
                    if page_idx[0] <= 0:
                        return await btn_int.response.defer()
                    page_idx[0] -= 1
                    await btn_int.response.edit_message(
                        embed=build_embed(pages[page_idx[0]]), view=self
                    )

                @discord.ui.button(label="下一页 ➡️", style=discord.ButtonStyle.secondary, row=0)
                async def next_btn(self, btn_int: discord.Interaction, button):
                    if page_idx[0] >= len(pages) - 1:
                        return await btn_int.response.defer()
                    page_idx[0] += 1
                    await btn_int.response.edit_message(
                        embed=build_embed(pages[page_idx[0]]), view=self
                    )

            pager = ReplayPager()
            await sel_int.response.send_message(
                embed=build_embed(pages[0]), view=pager, ephemeral=True
            )

        select.callback = replay_select_cb
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    # ── Page 5 补位: 赛后拉入语音 ──
    async def _post_match_pull(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # Reuse VoicePullView / PostMatchPullView from the match flow
        view = PostMatchPullView(self.guild)
        await interaction.followup.send(
            "🎙️ **赛后拉入语音 / Post-Match Voice Pull**\n"
            "选择要将队员拉入的频道：",
            view=view,
            ephemeral=True,
        )



class Dashboard(commands.Cog):
    """统一控制面板 / Unified Control Panel — 一个界面完成所有操作"""

    _croniter_warned = False

    async def cog_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        try:
            await interaction.followup.send(f"❌ 错误: {error}", ephemeral=True)
        except Exception:
            pass

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """发送欢迎消息到指定频道。"""
        welcome_channel = member.guild.get_channel(1398991787523313675)
        if welcome_channel:
            embed = discord.Embed(
                title="👋 欢迎来到 Gaming Planet！",
                description=f"{member.mention} 加入了我们！\nWelcome to Gaming Planet!",
                color=0x9B59B6,
            )
            embed.add_field(
                name="快速开始 | Quick Start",
                value="输入 `/gmpt-help` 查看所有功能\nType `/gmpt-help` to see all features",
                inline=False,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await welcome_channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        log_channel = member.guild.get_channel(MEMBER_LEAVE_LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="👋 成员离开 | Member Left",
                description=f"{member.mention} ({member.name}) 离开了服务器\nleft the server",
                color=0xE74C3C
            )
            embed.add_field(name="加入时间 | Joined", value=discord.utils.format_dt(member.joined_at, 'R') if member.joined_at else "未知")
            embed.set_thumbnail(url=member.display_avatar.url)
            await log_channel.send(embed=embed)

    # ── LoL Vote: 发投票 ──
    async def _post_lol_vote(self):
        """Post daily LoL mode vote to channel."""
        channel_id = LOL_VOTE_CHANNEL_ID
        channel = self.bot.get_channel(channel_id)
        if not channel:
            logger.warning(f"[LoLVote] Channel {channel_id} not found")
            return

        myt = timezone(timedelta(hours=8))
        today = datetime.now(myt).strftime("%Y-%m-%d")

        # 防重复：检查今天是否已发过
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM lol_vote_sessions WHERE vote_date=? AND status='pending'",
            (today,),
        )
        if cur.fetchone():
            conn.close()
            return
        conn.close()

        embed = discord.Embed(
            title="🎮 今天玩什么？What to play today?",
            description=(
                f"📅 {today}\n\n"
                f"点击下方按钮投票，每人一票！Vote below, one per person!\n"
                f"下午 1:00 自动结算并创建比赛 🏆 Auto-settle at 1PM\n\n"
                f"🏹 ARAM 大乱斗: **0** 票\n"
                f"⚔️ 召唤师峡谷 Summoner's Rift: **0** 票\n"
                f"🎯 TFT 云顶: **0** 票\n"
                f"🎪 无限火力 URF: **0** 票\n"
                f"👊 斗魂竞技场 Arena: **0** 票"
            ),
            color=discord.Color.gold(),
        )

        view = LolVoteView()
        msg = await channel.send(embed=embed, view=view)

        conn2 = get_db()
        cur2 = conn2.cursor()
        cur2.execute(
            "INSERT INTO lol_vote_sessions (channel_id, message_id, vote_date, status) VALUES (?,?,?,?)",
            (str(channel_id), str(msg.id), today, "pending"),
        )
        conn2.commit()
        conn2.close()
        logger.info(f"[LoLVote] Vote posted for {today}")

    # ── LoL Vote: 结算投票 ──
    async def _close_lol_vote(self):
        """Close today's vote, determine winner, create match."""
        channel_id = LOL_VOTE_CHANNEL_ID
        channel = self.bot.get_channel(channel_id)
        if not channel:
            logger.warning(f"[LoLVote] Channel {channel_id} not found")
            return

        myt = timezone(timedelta(hours=8))
        today = datetime.now(myt).strftime("%Y-%m-%d")

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, message_id FROM lol_vote_sessions WHERE vote_date=? AND status='pending'",
            (today,),
        )
        session = cur.fetchone()
        if not session:
            conn.close()
            return

        # 统计票数
        cur.execute(
            "SELECT mode, COUNT(*) as cnt FROM lol_vote_results WHERE session_id=? GROUP BY mode ORDER BY cnt DESC",
            (session["id"],),
        )
        rows = cur.fetchall()

        if not rows:
            # 无人投票，默认 ARAM
            winner_mode = "ARAM"
        else:
            winner_mode = rows[0]["mode"]

        # 更新 session 状态
        cur.execute(
            "UPDATE lol_vote_sessions SET status='closed', winner_mode=? WHERE id=?",
            (winner_mode, session["id"]),
        )
        conn.commit()

        # 创建比赛：插入 tournaments 表
        match_name = f"[投票] {winner_mode} — {today}"
        team_size = 5
        cur.execute(
            "INSERT INTO tournaments (name, max_teams, team_size, created_by, status) VALUES (?, 2, ?, 'system', 'open')",
            (match_name, team_size),
        )
        tid = cur.lastrowid
        conn.commit()
        conn.close()

        # 发送比赛报名 embed
        embed = discord.Embed(
            title=f"🏆 投票结束！Vote closed! 今天玩 {winner_mode}！点击报名 👇",
            description=(
                f"📅 {today}\n\n"
                f"最高票模式 Winner: **{winner_mode}**\n"
                f"比赛已自动创建，点击下方按钮报名 Match created, click below to sign up 👇"
            ),
            color=discord.Color.green(),
        ).set_footer(text=f"Match ID: {tid}")

        view = MatchView()
        msg = await channel.send(embed=embed, view=view)
        save_match_view_state(tid, msg.id, channel_id)

        # 发送初始报名列表
        list_embed = discord.Embed(
            title="已报名玩家 / Signed Up (0/10)",
            description="暂无玩家 / No signups yet",
            color=discord.Color.green(),
        )
        list_msg = await channel.send(embed=list_embed)
        set_player_list_msg(tid, list_msg.id)
        conn2 = get_db()
        cur2 = conn2.cursor()
        cur2.execute(
            "UPDATE match_view_state SET player_list_msg_id=? WHERE message_id=?",
            (str(list_msg.id), str(msg.id)),
        )
        conn2.commit()
        conn2.close()

        logger.info(f"[LoLVote] Vote closed for {today}, winner: {winner_mode}, match #{tid}")


    @app_commands.command(
        name="lol-vote",
        description="Manual start LoL mode vote",
    )
    @app_commands.default_permissions(administrator=True)
    async def lol_vote_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self._post_lol_vote()
        await interaction.followup.send("已发起投票 / Vote posted.", ephemeral=True)

    @app_commands.command(
        name="lol-vote-close",
        description="手动结算LoL投票并创建比赛 / Manually close vote and create match",
    )
    @app_commands.default_permissions(administrator=True)
    async def lol_vote_close_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self._close_lol_vote()
        await interaction.followup.send("已结算投票 / Vote closed.", ephemeral=True)

    @app_commands.command(
        name="gmpt-test-welcome",
        description="Preview welcome message",
    )
    @app_commands.default_permissions(administrator=True)
    async def gmpt_test_welcome(self, interaction: discord.Interaction):
        welcome_channel = interaction.guild.get_channel(1398991787523313675)
        if not welcome_channel:
            await interaction.response.send_message("未找到welcome频道", ephemeral=True)
            return

        embed = discord.Embed(
            title="👋 欢迎来到 Gaming Planet！",
            description=f"{interaction.user.mention} 加入了我们！\nWelcome to Gaming Planet!",
            color=0x9B59B6,
        )
        embed.add_field(
            name="快速开始 | Quick Start",
            value="输入 `/gmpt-help` 查看所有功能\nType `/gmpt-help` to see all features",
            inline=False,
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await welcome_channel.send(embed=embed)
        await interaction.response.send_message("已发送欢迎预览到welcome频道", ephemeral=True)

    @app_commands.command(
        name="setup-economy-info",
        description="Setup economy info panel in economy-info channel",
    )
    @app_commands.default_permissions(administrator=True)
    async def setup_economy_info_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = discord.utils.get(interaction.guild.text_channels, name="economy-info")
        if not channel:
            await interaction.followup.send("未找到 #economy-info 频道", ephemeral=True)
            return

        embed = discord.Embed(
            title="经济系统 Economy",
            color=0x2ECC71,
            description=(
                "`/shop` — 积分商店 Shop\n"
                "> 双倍MMR卡 · MMR保护卡 · 偷金币卡 · 经验加成卡 · 语音加成卡 · 抽奖券\n\n"
                "`/inventory` — 查看背包 Inventory\n\n"
                "`/balance` — 查看积分余额 Balance\n\n"
                "`/daily` — 每日签到 Daily\n"
                "> 连续签到额外奖励，查看 #daily\n\n"
                "`/achievements` — 成就列表 Achievements\n\n"
                "`/giveaway` — 限时抽奖 Giveaway\n\n"
                "`/gift @用户 金额` — 赠送积分 Gift\n\n"
                "`/transactions` — 收支明细 Transactions\n\n"
                "💡 比赛赚积分 · 挂语音30分钟 · 连胜更多积分\n"
                "🛍️ 购买记录看 #shop-log"
            ),
        )

        await channel.send(embed=embed)
        await interaction.followup.send("已发送经济系统介绍到 #economy-info", ephemeral=True)

    async def cog_load(self):
        import aiohttp
        self.session = aiohttp.ClientSession()
        # 启动定时赛事轮询
        if not hasattr(self, '_scheduled_loop_started'):
            self._scheduled_loop_started = True
            self.scheduled_event_loop.start()

    @tasks.loop(minutes=1)
    async def scheduled_event_loop(self):
        """每分钟检查一次 cron 表达式，触发到期的定时赛事。"""
        if not HAS_CRONITER:
            if not Dashboard._croniter_warned:
                logger.warning("[ScheduledEventLoop] croniter not installed, scheduled events disabled")
                Dashboard._croniter_warned = True
            return

        try:
            from datetime import datetime as dt, timezone, timedelta
            import json as _json

            MYT = timezone(timedelta(hours=8))
            now = dt.now(MYT)

            # ── LoL Vote: 每天 早上9点发投票 (马来西亚时间) ──
            if now.hour == 9 and now.minute == 0:
                await self._post_lol_vote()

            # ── LoL Vote: 每天 下午1点结算 (马来西亚时间) ──
            if now.hour == 13 and now.minute == 0:
                await self._close_lol_vote()
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT event_id, event_name, cron_expr, template_id, channel_id, created_by "
                    "FROM scheduled_events WHERE enabled=1"
                )
                events = cur.fetchall()
                for ev in events:
                    try:
                        cron = croniter(ev["cron_expr"], now.replace(second=0, microsecond=0))
                        prev_time = cron.get_prev(dt)
                        # 如果上一次触发时间在最近 65 秒内（允许一些偏差）
                        if (now - prev_time).total_seconds() < 65:
                            # 防止重复触发：检查最近 3 分钟内是否已创建同名赛事
                            cur.execute(
                                "SELECT COUNT(*) as cnt FROM tournaments "
                                "WHERE name=? AND created_at > datetime('now', '-3 minutes')",
                                (f"[定时] {ev['event_name']}",),
                            )
                            if cur.fetchone()["cnt"] > 0:
                                continue

                            # 从模板复制配置
                            max_teams = 2
                            team_size = 5
                            if ev["template_id"]:
                                cur.execute(
                                    "SELECT max_teams, team_size FROM match_templates WHERE template_id=?",
                                    (ev["template_id"],),
                                )
                                tpl = cur.fetchone()
                                if tpl:
                                    max_teams = tpl["max_teams"]
                                    team_size = tpl["team_size"]

                            cur.execute(
                                "INSERT INTO tournaments (name, max_teams, team_size, created_by, status) "
                                "VALUES (?, ?, ?, ?, 'open')",
                                (f"[定时] {ev['event_name']}", max_teams, team_size, ev["created_by"]),
                            )
                            tid = cur.lastrowid
                            conn.commit()

                            # 发送报名 embed 到指定频道
                            channel_id = int(ev["channel_id"]) if ev["channel_id"] else None
                            if channel_id:
                                channel = self.bot.get_channel(channel_id)
                                if channel:
                                    embed = discord.Embed(
                                        title=f"📅 定时赛事: {ev['event_name']}",
                                        description=(
                                            f"**{team_size}v{team_size}** | **{max_teams}** 队\n"
                                            f"报名已自动开启，点击下方按钮报名！\n"
                                            f"Match ID: {tid}"
                                        ),
                                        color=discord.Color.blue(),
                                    )
                                    view = MatchView()
                                    msg = await channel.send(embed=embed, view=view)
                                    save_match_view_state(tid, msg.id, channel_id)
                    except Exception as e:
                        logger.error(f"[ScheduledEventLoop] event {ev['event_id']} error: {e}")
                        continue
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[ScheduledEventLoop] loop error: {e}")

    @scheduled_event_loop.before_loop
    async def before_scheduled_loop(self):
        await self.bot.wait_until_ready()

    def _build_dashboard_embed(self):
        return discord.Embed(
            title="🎮 GMPT 控制面板 Control Panel | ⚔️ 比赛 Match",
            description="⚔️ **Match System / 比赛系统** — 创建、报名、分队、结算\nClick a button below / 点击下方按钮",
            color=discord.Color.blue(),
        ).set_footer(text="GMPT Dashboard v3.2 | Page 1/6")

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    @app_commands.command(
        name="gmpt-dashboard",
        description="Open the unified control panel / 打开统一控制面板",
    )
    @app_commands.describe(
        channel="Target channel / 目标频道 (default: current)",
    )
    async def dashboard_cmd(
        self, interaction: discord.Interaction,
        channel: discord.TextChannel = None,
    ):
        try:
            # Defer immediately to avoid 3-second Discord interaction timeout
            await interaction.response.defer()

            target = channel or interaction.channel

            # Dedup: delete old dashboard panels (bot messages with "GMPT 控制面板" in embed title)
            try:
                async for msg in target.history(limit=50):
                    if msg.author != self.bot.user:
                        continue
                    is_panel = False
                    if msg.embeds:
                        for emb in msg.embeds:
                            if emb.title and "GMPT 控制面板" in emb.title:
                                is_panel = True
                                break
                    if is_panel:
                        await msg.delete()
            except Exception as e:
                log_error("dashboard", "dashboard_cmd", e)

            view = DashboardView(guild=interaction.guild, session=self.session)
            embed = view._build_page_embed()

            if target != interaction.channel:
                msg = await target.send(embed=embed, view=view)
                await interaction.followup.send(
                    f"Dashboard sent to {target.mention}", ephemeral=True
                )
            else:
                msg = await interaction.followup.send(embed=embed, view=view)
        except Exception as e:
            logger.error(f"[Dashboard] Error in dashboard_cmd: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "控制面板加载失败 / Dashboard failed to load. Please try again.", ephemeral=True
                )
            except Exception as e:
                log_error("dashboard", "dashboard_cmd", e)

    @app_commands.command(
        name="gmpt-stats",
        description="View player MMR, rank, and win/loss stats / 查看玩家MMR/段位/胜负",
    )
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.describe(
        user="Target user / 目标用户 (default: yourself)",
    )
    async def gmpt_stats(
        self, interaction: discord.Interaction,
        user: discord.Member = None,
    ):
        target = user or interaction.user
        uid = str(target.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM mmr WHERE discord_id=?", (uid,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return await interaction.response.send_message(
                f"{target.display_name} 暂无 MMR 数据 / No MMR data yet.",
                ephemeral=True,
            )
        mmr = row["mmr"]; wins = row["wins"]; losses = row["losses"]
        streak = row["streak"]; rank = row["rank"]
        conn.close()

        winrate = f"{wins / (wins + losses) * 100:.1f}%" if (wins + losses) > 0 else "N/A"
        streak_text = f"+{streak} Win Streak!" if streak > 0 else f"{abs(streak)} Loss Streak" if streak < 0 else "-"
        emoji = _get_rank_emoji(rank)

        embed = discord.Embed(
            title=f"{emoji} {target.display_name} MMR Stats",
            description=(
                f"**MMR:** {mmr}\n"
                f"**Rank:** {emoji} {rank}\n"
                f"**Wins:** {wins} | **Losses:** {losses} | **Win Rate:** {winrate}\n"
                f"**Streak:** {streak_text}"
            ),
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="gmpt-leaderboard-mmr",
        description="View MMR leaderboard / 查看MMR排行榜",
    )
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.describe(
        limit="Number of players to show / 显示人数 (default: 10)",
    )
    async def gmpt_leaderboard_mmr(
        self, interaction: discord.Interaction,
        limit: int = 10,
    ):
        limit = max(1, min(limit, 25))
        with db_context() as cur:
            cur.execute("SELECT * FROM mmr ORDER BY mmr DESC LIMIT ?", (limit,))
            rows = cur.fetchall()

        if not rows:
            return await interaction.response.send_message(
                "暂无 MMR 数据 / No MMR data yet.", ephemeral=True
            )

        lines = []
        for i, row in enumerate(rows):
            uid = row["discord_id"]
            name = resolve_name(interaction.guild, uid)
            emoji = _get_rank_emoji(row["rank"])
            streak_str = f" [{row['streak']:+d}]" if row["streak"] != 0 else ""
            medal = ":first_place:" if i == 0 else ":second_place:" if i == 1 else ":third_place:" if i == 2 else f"#{i+1}"
            lines.append(
                f"{medal} {emoji} **{name}** \u2014 {row['mmr']} MMR "
                f"({row['wins']}W/{row['losses']}L){streak_str}"
            )

        embed = discord.Embed(
            title=":trophy: MMR Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="gmpt-mmr-board",
        description="Send a live MMR leaderboard to a channel (auto-refreshes after each match)",
    )
    @app_commands.describe(
        channel="Target channel for the live leaderboard / 目标频道",
    )
    async def gmpt_mmr_board(
        self, interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        # Check bot permissions in target channel
        perms = channel.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.read_message_history:
            return await interaction.response.send_message(
                "I need Send Messages + Read Message History permissions in that channel.",
                ephemeral=True,
            )

        guild_id = str(interaction.guild.id)

        # Check if a board already exists for this guild
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT message_id, channel_id FROM mmr_board WHERE guild_id=?", (guild_id,))
        existing = cur.fetchone()
        conn.close()

        # If existing board is in a different channel, delete the old message
        if existing and str(channel.id) != existing["channel_id"]:
            old_channel = interaction.guild.get_channel(int(existing["channel_id"]))
            if old_channel:
                try:
                    old_msg = await old_channel.fetch_message(int(existing["message_id"]))
                    await old_msg.delete()
                except Exception as e:
                    log_error("dashboard", "gmpt_mmr_board", e)

        # Send new board
        embed = await _build_mmr_board_embed(interaction.guild)
        new_msg = await channel.send(embed=embed)

        # Upsert mmr_board record
        conn2 = get_db()
        conn2.cursor().execute(
            "INSERT INTO mmr_board (guild_id, message_id, channel_id) VALUES (?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET message_id=?, channel_id=?",
            (guild_id, str(new_msg.id), str(channel.id), str(new_msg.id), str(channel.id)),
        )
        conn2.commit()
        conn2.close()

        await interaction.response.send_message(
            f"MMR leaderboard sent to {channel.mention} — will auto-refresh after each match settlement.",
            ephemeral=True,
        )

    @app_commands.command(
        name="gmpt-mmr-reset",
        description="Reset MMR (admin only). No @user = reset all; @user = reset one player",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        user="Target player to reset / 目标玩家 (leave empty to reset ALL)",
    )
    async def gmpt_mmr_reset(
        self, interaction: discord.Interaction,
        user: discord.Member = None,
    ):
        conn = get_db()
        cur = conn.cursor()

        if user is not None:
            uid = str(user.id)
            cur.execute(
                "INSERT INTO mmr (discord_id, mmr, wins, losses, streak, rank) "
                "VALUES (?, 1000, 0, 0, 0, 'Iron') "
                "ON CONFLICT(discord_id) DO UPDATE SET mmr=1000, wins=0, losses=0, streak=0, rank='Iron'",
                (uid,),
            )
            conn.commit()
            conn.close()
            return await interaction.response.send_message(
                f"{user.display_name} 的 MMR 已重置为 1000 (Iron).",
                ephemeral=True,
            )

        # Reset all
        cur.execute("UPDATE mmr SET mmr=1000, wins=0, losses=0, streak=0, rank='Iron'")
        affected = cur.rowcount
        conn.commit()
        conn.close()

        await interaction.response.send_message(
            f"已重置 {affected} 名玩家的 MMR 为 1000 (Iron).",
            ephemeral=True,
        )

    @app_commands.command(
        name="gmpt-recover",
        description="Recover a deleted match panel / 恢复被删除的比赛面板",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        match_id="Match ID to recover / 要恢复的比赛ID",
    )
    @app_commands.autocomplete(match_id=match_id_autocomplete)
    async def gmpt_recover(self, interaction: discord.Interaction, match_id: int):
        await interaction.response.defer(ephemeral=True)
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute("SELECT * FROM tournaments WHERE id=?", (match_id,))
            t = cur.fetchone()
            if not t:
                conn.close()
                return await interaction.followup.send(f"未找到比赛 #{match_id} / Match not found.")
            conn.close()

            mp = t["max_teams"] * t["team_size"]
            embed = discord.Embed(
                title=f"Match: {t['name']}",
                description=f"**{mp}** 人 / Players | 每队 / Per Team: {t['team_size']}\nClick below to sign up / 点击下方按钮报名",
                color=discord.Color.blue(),
            ).set_footer(text=f"Match ID: {match_id}")
            view = MatchView()
            try:
                msg = await interaction.channel.send(embed=embed, view=view)
            except Exception as e:
                logger.error(f"[gmpt_recover] channel.send (match panel) error: {e}")
                return await interaction.followup.send("发送比赛面板失败，请检查频道权限。", ephemeral=True)
            save_match_view_state(match_id, msg.id, interaction.channel_id)

            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute(
                "SELECT discord_id FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0) ORDER BY id ASC",
                (match_id,),
            )
            main_players = [r["discord_id"] for r in cur2.fetchall()]
            cur2.execute(
                "SELECT discord_id FROM registrations WHERE tournament_id=? AND is_sub=1 ORDER BY id ASC",
                (match_id,),
            )
            sub_players = [r["discord_id"] for r in cur2.fetchall()]
            conn2.close()

            lines = []
            for i, uid in enumerate(main_players, 1):
                name = resolve_name(interaction.guild, uid)
                lines.append(f"{i}. {name}")
            desc = "\n".join(lines) if lines else "暂无玩家 / No signups yet"
            title = f"已报名玩家 / Signed Up ({len(main_players)}/{mp})"
            if sub_players:
                title += f" +{len(sub_players)}替补"

            list_embed = discord.Embed(
                title=title,
                description=desc,
                color=discord.Color.green(),
            )
            try:
                list_msg = await interaction.channel.send(embed=list_embed)
            except Exception as e:
                logger.error(f"[gmpt_recover] channel.send (player list) error: {e}")
                return await interaction.followup.send("发送玩家列表失败，请检查频道权限。", ephemeral=True)
            set_player_list_msg(match_id, list_msg.id)
            conn3 = get_db(); cur3 = conn3.cursor()
            cur3.execute(
                "UPDATE match_view_state SET player_list_msg_id=? WHERE message_id=?",
                (str(list_msg.id), str(msg.id)),
            )
            conn3.commit(); conn3.close()

            await interaction.followup.send(f"已恢复比赛面板 #{match_id} / Panel recovered.", ephemeral=True)
        except Exception as e:
            logger.error(f"[gmpt_recover] unexpected error: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"恢复失败 / Recovery failed: {e}", ephemeral=True)
            except Exception as e:
                log_error("dashboard", "followup_send", e)


async def setup(bot):
    await bot.add_cog(Dashboard(bot))
    # 注册持久化 View，使 Bot 重启后按钮仍可响应
    bot.add_view(DashboardView(guild=None, session=None))
    bot.add_view(MatchView())
    bot.add_view(LolVoteView())
