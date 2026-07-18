"""
GMPT Bot — Dashboard / 统一控制面板
"""
import asyncio
import datetime
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db, db_context
from cogs.match_autocomplete import match_id_autocomplete
from utils.helpers import resolve_name

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
        # 持久化：保存 message → match_id 映射，Bot 重启后按钮仍可用
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


class CreateRoleMatchModal(discord.ui.Modal, title="创建选路比赛 / Create Role-Pick Match"):
    """选路比赛：创建时 role_pick=1，报名时需选 Top/JG/Mid/ADC/Support。"""
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
        # 发送初始报名列表（含路线分布）
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
        await interaction.followup.send(f"已选择 / Selected: {name}，点击加入 A 队或 B 队", ephemeral=True)

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
            except Exception:
                pass

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
            except Exception:
                pass

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
            f"Settle: `/gmpt-settle {self.match_id} <win_team_id>`"
        )
        embed.color = discord.Color.green()
        await interaction.edit_original_response(embed=embed, view=self)
        try:
            voice_view = VoicePullView(self.team_a, self.team_b, self.guild)
            await interaction.followup.send("📢 点击按钮将玩家拉入对应语音频道：", view=voice_view)
        except Exception:
            pass

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

# ══════════ 报名列表消息缓存（match_id → message_id，内存 + DB 双写）══════════
_player_list_msgs: dict[int, int] = {}

def get_player_list_msg(match_id: int) -> int | None:
    return _player_list_msgs.get(match_id)

def set_player_list_msg(match_id: int, msg_id: int):
    _player_list_msgs[match_id] = msg_id

def remove_player_list_msg(match_id: int):
    _player_list_msgs.pop(match_id, None)


# ══════════ MatchView 持久化状态（Bot 重启后恢复报名按钮）══════════
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
    # 同步到内存缓存，方便 refresh_player_list 使用
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


# ══════════ MatchViewWithID — 可持久化版（Bot 重启后按钮仍有效）══════════
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
    """结算后显示的「重新分队」按钮视图（4 个按钮一行）。"""

    def __init__(self, match_id: int, guild: discord.Guild):
        super().__init__(timeout=604800)  # 7 days
        self.match_id = match_id
        self.guild = guild
        self._voice_used_a = False
        self._voice_used_b = False

    def _get_main_players(self):
        """只取正式玩家（is_sub=0），替补不计入。"""
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
            description=f"**当前参赛玩家 ({len(rows)}/{max_p})：**\n{desc}",
            color=discord.Color.gold(),
        )

    async def _refresh_embed(self, interaction: discord.Interaction):
        """Update the ReShuffleView message embed with current player list."""
        try:
            embed = self._build_player_list_embed()
            await interaction.message.edit(embed=embed, view=self)
        except Exception:
            pass

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
            description="本场比赛已结束，按钮已禁用 / Match finished, all buttons disabled.",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed)
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

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

        a_mentions = [f"<@{uid}>" for uid in ta]
        b_mentions = [f"<@{uid}>" for uid in tb]

        embed = discord.Embed(
            title=f"🔄 重新分队 — {match_name}",
            description=(
                f"🔵 **A 队 Team A** (ID:{aid}): {' '.join(a_mentions)}\n"
                f"🔴 **B 队 Team B** (ID:{bid}): {' '.join(b_mentions)}\n\n"
                f"Match ID: {new_mid}\n"
                f"Settle: `/gmpt-settle {new_mid} <win_team_id>`"
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
            f"**队长分队 / Captain Draft** — {match_name}\n第一步：选择 2 名队长",
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
            from cogs.economy import MATCH_WIN_COINS, MATCH_PARTICIPATE_COINS
            conn3 = get_db(); cur3 = conn3.cursor()
            cur3.execute("SELECT discord_id FROM registrations WHERE tournament_id=? AND team_id=?", (mid, win_tid))
            for r in cur3.fetchall():
                wid = r["discord_id"]
                cur3.execute("INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING", (wid,))
                cur3.execute("UPDATE users SET score=score+? WHERE discord_id=?", (MATCH_WIN_COINS, wid))
                cur3.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)", (wid, MATCH_WIN_COINS, f"比赛胜利 #{mid}"))
            cur3.execute("INSERT INTO results (tournament_id,team_id,rank,score_awarded) VALUES (?,?,1,?)", (mid, win_tid, MATCH_WIN_COINS))

            cur3.execute("SELECT discord_id FROM registrations WHERE tournament_id=? AND team_id!=?", (mid, win_tid))
            for r in cur3.fetchall():
                lid = r["discord_id"]
                cur3.execute("INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING", (lid,))
                cur3.execute("UPDATE users SET score=score+? WHERE discord_id=?", (MATCH_PARTICIPATE_COINS, lid))
                cur3.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)", (lid, MATCH_PARTICIPATE_COINS, f"比赛参与 #{mid}"))

            if mvp_uid:
                cur3.execute("INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING", (mvp_uid,))
                cur3.execute("UPDATE users SET score=score+? WHERE discord_id=?", (MATCH_PARTICIPATE_COINS, mvp_uid))
                cur3.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)", (mvp_uid, MATCH_PARTICIPATE_COINS, f"MVP #{mid}"))

            cur3.execute("UPDATE tournaments SET status='finished' WHERE id=?", (mid,))
            conn3.commit()

            # ── MMR update ──
            cur3.execute("SELECT discord_id, team_id FROM registrations WHERE tournament_id=?", (mid,))
            all_regs = cur3.fetchall()
            w_ids = [r["discord_id"] for r in all_regs if r["team_id"] == win_tid]
            l_ids = [r["discord_id"] for r in all_regs if r["team_id"] != win_tid]
            cur3.close()
            _update_mmr(w_ids, l_ids, mvp_uid, conn2=None)

            # ── 刷新实时排行榜 ──
            await _refresh_mmr_board(interaction.client, self.guild)

            conn3 = get_db(); cur3 = conn3.cursor()
            cur3.execute("SELECT name FROM tournaments WHERE id=?", (mid,))
            name_row = cur3.fetchone()
            match_name = name_row["name"] if name_row else f"Match #{mid}"
            conn3.close()
            analysis_embed = _generate_match_analysis(mid, match_name, w_ids, l_ids, mvp_uid, self.guild)

            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.label == "结算":
                    child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

            # Send AI analysis
            if analysis_embed:
                try:
                    await interaction.channel.send(embed=analysis_embed)
                except Exception:
                    pass

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
        """从 DB 解析本 match 的 A/B 队成员（按 id DESC 取最新一组）。"""
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
            # 名称为 "A 队 Team A" / "B 队 Team B"，按首字符精确匹配，避免 "B 队 TEAM B" 中的 "A" 误判
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
            lines.append(f"✅ {team_label}队已拉入：{' '.join(m.mention for m in moved)}")
        if not_in:
            lines.append(f"⚠️ {team_label}队未在语音频道（无法拉入）：{' '.join(not_in)}")
        return lines

    @discord.ui.button(label="🔵 拉 A 队入语音", style=discord.ButtonStyle.primary, emoji="📢", row=2)
    async def pull_voice_a_btn(self, interaction: discord.Interaction, button):
        if self._voice_used_a:
            return await interaction.response.send_message("A队已经拉过了！", ephemeral=True)
        team_a_ids, team_b_ids = self._resolve_team_ids()
        uid = str(interaction.user.id)
        if not interaction.user.guild_permissions.administrator and uid not in team_a_ids and uid not in team_b_ids:
            return await interaction.response.send_message("仅参赛者或管理员可操作", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        lines = await self._do_pull(interaction, team_a_ids, 1438050912814895186, "A")
        notify_channel = self.guild.get_channel(1462616745197043722)
        if notify_channel and lines:
            try:
                await notify_channel.send("\n".join(lines))
            except Exception:
                pass
        button.disabled = True
        self._voice_used_a = True
        await interaction.edit_original_response(view=self)
        await interaction.followup.send("A 队拉入完成！", ephemeral=True)

    @discord.ui.button(label="🔴 拉 B 队入语音", style=discord.ButtonStyle.primary, emoji="📢", row=2)
    async def pull_voice_b_btn(self, interaction: discord.Interaction, button):
        if self._voice_used_b:
            return await interaction.response.send_message("B队已经拉过了！", ephemeral=True)
        team_a_ids, team_b_ids = self._resolve_team_ids()
        uid = str(interaction.user.id)
        if not interaction.user.guild_permissions.administrator and uid not in team_a_ids and uid not in team_b_ids:
            return await interaction.response.send_message("仅参赛者或管理员可操作", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        lines = await self._do_pull(interaction, team_b_ids, 1437626921394372658, "B")
        notify_channel = self.guild.get_channel(1462616745197043722)
        if notify_channel and lines:
            try:
                await notify_channel.send("\n".join(lines))
            except Exception:
                pass
        button.disabled = True
        self._voice_used_b = True
        await interaction.edit_original_response(view=self)
        await interaction.followup.send("B 队拉入完成！", ephemeral=True)


class VoicePullView(discord.ui.View):
    """双按钮独立拉入 A/B 队语音频道。"""

    VA_CHANNEL_ID = 1438050912814895186
    VB_CHANNEL_ID = 1437626921394372658
    NOTIFY_CHANNEL_ID = 1462616745197043722

    def __init__(self, team_a_ids: list, team_b_ids: list, guild: discord.Guild, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.team_a_ids = list(team_a_ids)
        self.team_b_ids = list(team_b_ids)
        self.guild = guild
        self._used_a = False
        self._used_b = False

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
            # 名称为 "A 队 Team A" / "B 队 Team B"，按首字符精确匹配，避免 "B 队 TEAM B" 中的 "A" 误判
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

    async def _do_pull(self, interaction, uids, channel_id, team_label):
        """将 uid 列表的成员拉入指定频道，返回通知行列表。"""
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
            lines.append(f"✅ {team_label}队已拉入：{' '.join(m.mention for m in moved)}")
        if not_in:
            lines.append(f"⚠️ {team_label}队未在语音频道（无法拉入）：{' '.join(not_in)}")
        return lines

    @discord.ui.button(label="🔵 拉 A 队入语音", style=discord.ButtonStyle.primary, row=0)
    async def pull_a_btn(self, interaction: discord.Interaction, button):
        if self._used_a:
            return await interaction.response.send_message("A队已经拉过了！", ephemeral=True)
        uid = str(interaction.user.id)
        if not interaction.user.guild_permissions.administrator and uid not in self.team_a_ids and uid not in self.team_b_ids:
            return await interaction.response.send_message("仅参赛者或管理员可操作", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        lines = await self._do_pull(interaction, self.team_a_ids, self.VA_CHANNEL_ID, "A")
        notify_channel = self.guild.get_channel(self.NOTIFY_CHANNEL_ID)
        if notify_channel and lines:
            try:
                await notify_channel.send("\n".join(lines))
            except Exception:
                pass
        button.disabled = True
        self._used_a = True
        await interaction.edit_original_response(view=self)
        await interaction.followup.send("A 队拉入完成！", ephemeral=True)

    @discord.ui.button(label="🔴 拉 B 队入语音", style=discord.ButtonStyle.primary, row=0)
    async def pull_b_btn(self, interaction: discord.Interaction, button):
        if self._used_b:
            return await interaction.response.send_message("B队已经拉过了！", ephemeral=True)
        uid = str(interaction.user.id)
        if not interaction.user.guild_permissions.administrator and uid not in self.team_a_ids and uid not in self.team_b_ids:
            return await interaction.response.send_message("仅参赛者或管理员可操作", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        lines = await self._do_pull(interaction, self.team_b_ids, self.VB_CHANNEL_ID, "B")
        notify_channel = self.guild.get_channel(self.NOTIFY_CHANNEL_ID)
        if notify_channel and lines:
            try:
                await notify_channel.send("\n".join(lines))
            except Exception:
                pass
        button.disabled = True
        self._used_b = True
        await interaction.edit_original_response(view=self)
        await interaction.followup.send("B 队拉入完成！", ephemeral=True)


class ManualTeamView(discord.ui.View):
    """管理员手动将每个玩家分配到 A/B 队（自己分队）。"""

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
        await interaction.followup.send(f"已选择 / Selected: {name}，点击加入 A 队或 B 队", ephemeral=True)

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
            except Exception:
                pass

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
            except Exception:
                pass

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
            f"Settle: `/gmpt-settle {new_mid} <win_team_id>`"
        )
        embed.color = discord.Color.green()
        await interaction.edit_original_response(embed=embed, view=self)
        try:
            voice_view = VoicePullView(self.team_a, self.team_b, self.guild)
            await interaction.followup.send("📢 点击按钮将玩家拉入对应语音频道：", view=voice_view)
        except Exception:
            pass
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
    """队长分队：先选 2 名队长，再轮流选人（draft 模式）。"""

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
        await interaction.response.edit_message(
            content=f"**队长分队 / Captain Draft** — {self.match_name}\n队长已选定，开始轮流选人！",
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
            await interaction.response.edit_message(
                content=f"**队长分队 / Captain Draft** — {self.match_name}\n所有玩家已选完，确认分队！",
                embed=self._build_embed(),
                view=self,
            )
        else:
            self._build_draft_view()
            await interaction.response.edit_message(embed=self._build_embed(), view=self)

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
        await interaction.response.edit_message(
            content=f"**队长分队 / Captain Draft** — {self.match_name}\n第一步：选择 2 名队长",
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
                f"Settle: `/gmpt-settle {new_mid} <win_team_id>`"
            ),
            color=discord.Color.green(),
        )
        await interaction.edit_original_response(embed=embed, view=self)
        try:
            voice_view = VoicePullView(self.team_a, self.team_b, self.guild)
            await interaction.followup.send("📢 点击按钮将玩家拉入对应语音频道：", view=voice_view)
        except Exception:
            pass
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


class MatchViewWithID(discord.ui.View):
    """
    持久化比赛视图：通过 message_id → DB 反查 match_id，Bot 重启后按钮仍可响应。
    不存实例状态，所有数据通过 interaction.message.id 实时从 DB 查询。
    """
    def __init__(self):
        super().__init__(timeout=None)

    async def _get_context(self, interaction: discord.Interaction):
        """从 interaction.message.id 反查 match 和 tournament 数据，返回 (match_id, t, guild)。"""
        mid = get_match_id_from_message(interaction.message.id)
        if not mid:
            return (None, None, interaction.guild)
        t = get_match_row(mid)
        return (mid, t, interaction.guild)

    # ── 辅助：更新报名列表 ──
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
            # 选路比赛：按路线分组显示
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
        # 优先用 match_id 反查 panel message_id，避免非面板交互时写错记录
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

            # 选路比赛：弹出路线选择
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
                        f"✅ {lane_interaction.user.mention} 报名成功！ Signed up! ({chosen_lane})", ephemeral=True
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
                f"✅ {interaction.user.mention} 报名成功！ Signed up! ({cnt+1}/{max_p})", ephemeral=True
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

                    embed = discord.Embed(
                        title="确认结算 / Confirm Settle",
                        description=(
                            f"Match: **{t['name']}** (ID:{mid})\n"
                            f"🏆 胜方 Winner: **{win_name}**\n"
                            f"💔 败方 Loser: **{lose_name}**"
                            f"{mvp_text}\n\n"
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
                        content="✅ 结算完成！ / Settle complete!", embed=None, view=None
                    )

                    # Send AI analysis
                    if analysis_embed:
                        await interaction.channel.send(embed=analysis_embed)

                    # Send public re-shuffle button with player list
                    reshuffle_view = ReShuffleView(match_id=mid, guild=guild)
                    reshuffle_embed = reshuffle_view._build_player_list_embed()
                    await interaction.channel.send(
                        embed=reshuffle_embed,
                        view=reshuffle_view,
                    )

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
            except Exception:
                pass

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
                f"确认退出比赛？ / Confirm leave match **{t['name']}**?",
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

        # Get all registrations
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT discord_id, is_sub FROM registrations WHERE tournament_id=? ORDER BY id ASC", (mid,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return await interaction.response.send_message("无人可踢 / No one to kick.", ephemeral=True)

        # Build UserSelect
        user_select = discord.ui.UserSelect(
            placeholder="选择要踢出的用户 / Select users to kick...",
            min_values=1,
            max_values=1,
        )

        async def kick_select_callback(sel_int: discord.Interaction):
            member = user_select.values[0]
            uid = str(member.id)

            # Check if user is registered
            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute("SELECT id FROM registrations WHERE tournament_id=? AND discord_id=?", (mid, uid))
            if not cur2.fetchone():
                conn2.close()
                return await sel_int.response.send_message(
                    f"{member.display_name} 未报名 / Not signed up.", ephemeral=True
                )

            # Confirmation
            confirm_view = ConfirmView(timeout=60)
            await sel_int.response.send_message(
                f"确认踢出 {member.mention}？ / Confirm kick?",
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
            conn2.commit(); conn2.close()
            await sel_int.edit_original_response(
                content=f"👢 已踢出 {member.mention} / Kicked.",
                view=None,
            )
            await self._refresh_list(sel_int, mid)

        user_select.callback = kick_select_callback
        kview = discord.ui.View(timeout=60)
        kview.add_item(user_select)
        await interaction.response.send_message(
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
        conn2.commit(); conn2.close()

        match_name = t["name"]

        a_mentions = [f"<@{uid}>" for uid in ta]
        b_mentions = [f"<@{uid}>" for uid in tb]
        embed = discord.Embed(
            title=f"🔄 重新分队 — {match_name}",
            description=(
                f"🔵 **A 队 Team A** (ID:{aid}): {' '.join(a_mentions)}\n"
                f"🔴 **B 队 Team B** (ID:{bid}): {' '.join(b_mentions)}\n\n"
                f"Match ID: {mid}\n"
                f"Settle: `/gmpt-settle {mid} <win_team_id>`"
            ),
            color=discord.Color.gold(),
        )
        await interaction.channel.send(embed=embed)

        # Send voice pull view
        try:
            voice_view = VoicePullView(ta, tb, guild)
            await interaction.channel.send("📢 点击按钮将玩家拉入对应语音频道：", view=voice_view)
        except Exception:
            pass

        # Send vote view
        await VoteView.send_vote(match_id=mid, match_name=match_name, channel=interaction.channel)

        await interaction.followup.send("重新分队完成！", ephemeral=True)

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

        # Step 1: UserSelect for multi-select
        user_select = discord.ui.UserSelect(
            placeholder="选择要添加的用户 / Select users to add...",
            min_values=1,
            max_values=25,
        )

        async def user_select_callback(sel_int: discord.Interaction):
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
                    return await type_int.response.send_message("报名已关闭 / Signup closed.", ephemeral=True)

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
                await type_int.response.send_message("\n".join(msg) or "无操作", ephemeral=True)

                await self._refresh_list(type_int, mid)

            type_select.callback = type_select_callback
            tview = discord.ui.View(timeout=60)
            tview.add_item(type_select)
            await sel_int.response.send_message(
                f"已选择 {len(selected_members)} 人。请选择添加类型 / Select type:",
                view=tview,
                ephemeral=True,
            )

        user_select.callback = user_select_callback
        view = discord.ui.View(timeout=120)
        view.add_item(user_select)
        await interaction.response.send_message("选择要添加的用户 / Select users to add:", view=view, ephemeral=True)

# ══════════ 向后兼容别名══════════
MatchView = MatchViewWithID


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
    for wid in winner_ids:
        cur.execute("INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING", (wid,))
        cur.execute("UPDATE users SET score=score+? WHERE discord_id=?", (MATCH_WIN_COINS, wid))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (wid, MATCH_WIN_COINS, f"Match win #{match_id}"))
    cur.execute("INSERT INTO results (tournament_id,team_id,rank,score_awarded) VALUES (?,?,1,?)", (match_id, win_team_id, MATCH_WIN_COINS))

    # Loser +50
    cur.execute("SELECT discord_id FROM registrations WHERE tournament_id=? AND team_id!=?", (match_id, win_team_id))
    loser_ids = [r["discord_id"] for r in cur.fetchall()]
    for lid in loser_ids:
        cur.execute("INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING", (lid,))
        cur.execute("UPDATE users SET score=score+? WHERE discord_id=?", (MATCH_PARTICIPATE_COINS, lid))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (lid, MATCH_PARTICIPATE_COINS, f"Match participation #{match_id}"))

    # MVP +50
    if mvp_id:
        cur.execute("INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING", (mvp_id,))
        cur.execute("UPDATE users SET score=score+? WHERE discord_id=?", (MATCH_PARTICIPATE_COINS, mvp_id))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (mvp_id, MATCH_PARTICIPATE_COINS, f"MVP #{match_id}"))

    cur.execute("UPDATE tournaments SET status='finished' WHERE id=?", (match_id,))
    conn.commit(); conn.close()

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

    # ── MMR 排位更新 ──
    _update_mmr(winner_ids, loser_ids, mvp_id, conn2=None)

    # ── 竞猜结算 / Vote Resolution ──
    vote_winners = _resolve_vote_bets(match_id, win_team_id)
    vote_text = ""
    if vote_winners:
        vote_text = f"\n\U0001f4ca 竞猜: {len(vote_winners)} 人猜对，各 +5 MMR"

    # ── 刷新实时排行榜 ──
    if bot is not None:
        await _refresh_mmr_board(bot, guild)

    # ── AI 赛事分析 ──
    analysis_embed = _generate_match_analysis(match_id, match_name, winner_ids, loser_ids, mvp_id, guild)
    # Append vote results to analysis embed
    if analysis_embed and vote_text:
        analysis_embed.description = (analysis_embed.description or "") + vote_text
    return analysis_embed


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


def _update_mmr(winner_ids: list, loser_ids: list, mvp_id, conn2=None):
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
    """竞猜投票面板 — 比赛开始前观众选谁会赢，猜对 +5 MMR。"""

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
            f"\u2705 你投给了 **{self.team_a_name}**！You voted for {self.team_a_name}!", ephemeral=True
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
            f"\u2705 你投给了 **{self.team_b_name}**！You voted for {self.team_b_name}!", ephemeral=True
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
                f"\u2b50 猜对可获得 **+5 MMR**！"
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
        except Exception:
            pass

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
        timestamp=datetime.datetime.now(datetime.timezone.utc),
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
        except Exception:
            pass


# =============================================================================
# DashboardView — 统一控制面板 / Unified Control Panel
# =============================================================================

class DashboardView(discord.ui.View):
    def __init__(self, guild, session, timeout=None):
        super().__init__(timeout=None)
        self.guild = guild
        self.session = session

        # ===== 比赛系统 Select Menu =====
        self._bisai_select = discord.ui.Select(
            placeholder="比赛系统 / Match System...",
            options=[
                discord.SelectOption(label="创建比赛", value="create_match", description="Create a new match"),
                discord.SelectOption(label="报名参加", value="join_match", description="Join a match"),
                discord.SelectOption(label="随机分队", value="shuffle", description="Random shuffle into teams"),
                discord.SelectOption(label="分 AB 队", value="assign_teams", description="Manually assign teams"),
                discord.SelectOption(label="开打", value="start_match", description="Close signup & start match"),
                discord.SelectOption(label="结算", value="settle", description="Settle match & distribute coins"),
                discord.SelectOption(label="拉入语音", value="pull_voice", description="Pull teams into voice channels"),
                discord.SelectOption(label="创建选路比赛", value="create_role_match", description="Create a role-pick match"),
            ],
            row=0,
        )
        self._bisai_select.callback = self._on_bisai_select
        self.add_item(self._bisai_select)

        # ===== 赛事系统 Select Menu =====
        self._saishi_select = discord.ui.Select(
            placeholder="赛事系统 / Tournament System...",
            options=[
                discord.SelectOption(label="创建赛事", value="create_tournament", description="Create a new tournament"),
                discord.SelectOption(label="报名赛事", value="signup_tournament", description="Sign up for a tournament"),
                discord.SelectOption(label="队长选秀", value="draft_setup", description="Captain draft setup"),
                discord.SelectOption(label="上报比分", value="report", description="Report match score"),
                discord.SelectOption(label="赛事排名", value="standings", description="View tournament standings"),
                discord.SelectOption(label="对阵表", value="bracket", description="View tournament bracket"),
            ],
            row=1,
        )
        self._saishi_select.callback = self._on_saishi_select
        self.add_item(self._saishi_select)

        # ===== 独立按钮 / Standalone Buttons (选队长 + Voice LB) =====
        captain_btn = discord.ui.Button(
            label="选队长 / Captain",
            style=discord.ButtonStyle.secondary,
            emoji="👑",
            row=2,
        )
        captain_btn.callback = self._pick_captain
        self.add_item(captain_btn)

        voice_lb_btn = discord.ui.Button(
            label="Voice LB 语音排行",
            style=discord.ButtonStyle.secondary,
            emoji="🎤",
            row=2,
        )
        voice_lb_btn.callback = self._voice_lb
        self.add_item(voice_lb_btn)

    async def _on_bisai_select(self, interaction: discord.Interaction):
        value = interaction.data["values"][0]
        dispatch = {
            "create_match": self._create_match,
            "join_match": self._join_match,
            "shuffle": self._shuffle,
            "assign_teams": self._assign_teams,
            "start_match": self._start_match,
            "settle": self._settle,
            "pull_voice": self._pull_voice,
            "create_role_match": self._create_role_match,
        }
        await dispatch[value](interaction)

    async def _on_saishi_select(self, interaction: discord.Interaction):
        value = interaction.data["values"][0]
        dispatch = {
            "create_tournament": self._create_tournament,
            "signup_tournament": self._signup_tournament,
            "draft_setup": self._draft_setup,
            "report": self._report,
            "standings": self._standings,
            "bracket": self._bracket,
        }
        await dispatch[value](interaction)


    async def _create_match(self, interaction: discord.Interaction):
        modal = CreateMatchModal(self.guild, self.session)
        await interaction.response.send_modal(modal)

    async def _create_role_match(self, interaction: discord.Interaction):
        modal = CreateRoleMatchModal(self.guild, self.session)
        await interaction.response.send_modal(modal)


    async def _join_match(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name, max_teams, team_size, role_pick FROM tournaments "
            "WHERE status='open' AND max_teams=2 ORDER BY id DESC LIMIT 25"
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.followup.send("当前没有可报名的比赛 / No open matches.", ephemeral=True)

        options = []
        for m in matches:
            ts = m["team_size"] or 5
            rp_tag = " [选路]" if m["role_pick"] else ""
            options.append(discord.SelectOption(
                label=m["name"][:100],
                value=str(m["id"]),
                description=f"5v5 | ID: {m['id']}{rp_tag}",
            ))

        select = discord.ui.Select(
            placeholder="选择比赛 / Select a match...",
            options=options[:25],
        )

        async def join_callback(sel_interaction: discord.Interaction):
            mid = int(sel_interaction.data["values"][0])
            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute("SELECT * FROM tournaments WHERE id=?", (mid,))
            t = cur2.fetchone()
            if not t or t["status"] != "open":
                conn2.close()
                reason = "比赛不存在" if not t else f"状态为 {t['status']}"
                return await sel_interaction.followup.send(f"报名已关闭 / Signup closed ({reason}).", ephemeral=True)

            max_p = t["max_teams"] * t["team_size"]
            cur2.execute("SELECT COUNT(*) as cnt FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0)", (mid,))
            cnt = cur2.fetchone()["cnt"]
            if cnt >= max_p:
                conn2.close()
                return await sel_interaction.followup.send("报名已满 / Signup full.", ephemeral=True)

            uid = str(sel_interaction.user.id)

            # 选路比赛：弹出路线选择菜单
            if t["role_pick"]:
                conn2.close()
                await sel_interaction.response.defer(ephemeral=True)
                # 查询各路线已报名人数
                lane_conn = get_db(); lane_cur = lane_conn.cursor()
                LANES = ["Top", "JG", "Mid", "ADC", "Sup"]
                lane_counts = {}
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
                    # 重新检查该路是否已满
                    lcur.execute(
                        "SELECT COUNT(*) as cnt FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0) AND lane=?",
                        (mid, chosen_lane),
                    )
                    if lcur.fetchone()["cnt"] >= 2:
                        lconn.close()
                        return await lane_interaction.response.send_message(
                            f"该路线已满 / Lane {chosen_lane} is full. 请重新选择 / Please pick another lane.", ephemeral=True
                        )
                    # 检查是否已报名
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

                    # 更新比赛面板的报名列表（含路线分布）
                    # 找到该比赛的 MatchView 实例对应的消息并刷新
                    from cogs.dashboard import MatchViewWithID as _MV
                    mv = _MV()
                    await mv._refresh_list(lane_interaction, mid)
                    await lane_interaction.response.send_message(
                        f"✅ {lane_interaction.user.mention} 报名成功！ Signed up! ({chosen_lane})", ephemeral=True
                    )

                lane_select.callback = lane_callback
                lane_view = discord.ui.View(timeout=60)
                lane_view.add_item(lane_select)
                return await sel_interaction.followup.send(
                    f"请选择你的路线 / Pick your lane for **{t['name']}**:", view=lane_view, ephemeral=True
                )

            # 普通比赛：直接报名
            try:
                cur2.execute("INSERT INTO registrations (tournament_id, discord_id) VALUES (?,?)", (mid, uid))
                cur2.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (uid, sel_interaction.user.name))
                conn2.commit()
            except Exception as e:
                conn2.close()
                if "UNIQUE" in str(e).upper():
                    return await sel_interaction.followup.send("已报名 / Already signed up.", ephemeral=True)
                logger.error(f"Join match error: mid={mid} uid={uid}: {e}", exc_info=True)
                return await sel_interaction.followup.send("报名失败，请重试 / Signup failed, try again.", ephemeral=True)
            conn2.close()
            await sel_interaction.followup.send(
                f"✅ {sel_interaction.user.mention} 报名成功！ Signed up! ({cnt+1}/{max_p})", ephemeral=True
            )

        select.callback = join_callback
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
            return await interaction.followup.send("当前没有可报名的比赛 / No open matches.", ephemeral=True)

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
            cur2.execute("SELECT discord_id FROM registrations WHERE tournament_id=?", (mid,))
            players = cur2.fetchall()
            conn2.close()

            if not players:
                return await sel_int.response.send_message("该比赛暂无报名玩家 / No signups yet.", ephemeral=True)

            pids = [r["discord_id"] for r in players]
            poptions = []
            for pid in pids:
                name = resolve_name(self.guild, pid)
                poptions.append(discord.SelectOption(label=name[:100], value=pid))

            pselect = discord.ui.Select(
                placeholder="选择队长 / Select captains (最多2人)...",
                options=poptions[:25],
                max_values=min(2, len(poptions)),
            )

            async def final_captain_cb(inner_int: discord.Interaction):
                captains = inner_int.data["values"]
                cap_names = []
                for cid in captains:
                    m = self.guild.get_member(int(cid))
                    cap_names.append(m.display_name if m else f"<@{cid}>")
                await inner_int.response.send_message(
                    f"已选队长 / Captains: {', '.join(cap_names)}\n使用「分 A/B 队」按钮分配队伍 / Use Teams button to assign.",
                    ephemeral=True,
                )

            pselect.callback = final_captain_cb
            pview = discord.ui.View(timeout=60)
            pview.add_item(pselect)
            await sel_int.response.send_message(view=pview, ephemeral=True)

        select.callback = captain_select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)


    async def _shuffle(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        """Randomly split registered players into A/B teams."""
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
            conn2.commit(); conn2.close()

            # Send VoteView for betting
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
                    f"Settle: `/gmpt-settle {mid} <win_team_id>`"
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
                description=f"确定要关闭比赛报名并开始吗？\nClose signup and start?\nMatch ID: {mid}",
                color=discord.Color.orange(),
            )
            confirm_view = ConfirmView(timeout=30)
            await sel_int.response.send_message(embed=embed, view=confirm_view, ephemeral=True)
            await confirm_view.wait()
            if confirm_view.value is None or not confirm_view.value:
                return

            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute("UPDATE tournaments SET status='closed' WHERE id=? AND status='open'", (mid,))
            conn2.commit(); conn2.close()
            await sel_int.edit_original_response(
                content=f"比赛 / Match (ID: {mid}) 已开始！ Started! 报名已关闭 / Signup closed.",
                embed=None,
                view=None,
            )

            # Send VoteView for betting
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
        """Settle a custom match — select match → winner → MVP → confirm → coins."""
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
                return await sel_int.response.send_message(f"比赛 #{mid} 不存在 / Match not found. 试试 /gmpt-list 查看可用比赛", ephemeral=True)
            if t["status"] == "finished":
                conn2.close()
                return await sel_int.response.send_message("已结算 / Already settled.", ephemeral=True)

            cur2.execute("SELECT id, name FROM teams WHERE tournament_id=?", (mid,))
            teams = cur2.fetchall()
            conn2.close()

            if len(teams) < 2:
                return await sel_int.response.send_message("未找到两支队伍 / Two teams not found.", ephemeral=True)

            # Step 1: pick winner
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

                mvp_options = [discord.SelectOption(label="无 MVP / Skip", value="__none__")]
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
                        mvp_text = f"\n🏅 MVP: {mvp_member.mention if mvp_member else flow.mvp_id}"

                    embed = discord.Embed(
                        title="确认结算 / Confirm Settle",
                        description=(
                            f"Match: **{t['name']}** (ID:{mid})\n"
                            f"🏆 胜方 Winner: **{win_name}**\n"
                            f"💔 败方 Loser: **{lose_name}**"
                            f"{mvp_text}\n\n"
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
                        content="✅ 结算完成！ / Settle complete!", embed=None, view=None
                    )

                    # Send AI analysis
                    if analysis_embed:
                        await interaction.channel.send(embed=analysis_embed)

                    # Send public re-shuffle button with player list
                    reshuffle_view = ReShuffleView(match_id=mid, guild=self.guild)
                    reshuffle_embed = reshuffle_view._build_player_list_embed()
                    await interaction.channel.send(
                        embed=reshuffle_embed,
                        view=reshuffle_view,
                    )

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
                    f"🔵 **A 队**：{' '.join(a_mentions) if a_mentions else '(无)'}\n"
                    f"🔴 **B 队**：{' '.join(b_mentions) if b_mentions else '(无)'}"
                ),
                color=discord.Color.blurple(),
            )
            await sel_int.response.send_message(embed=embed, view=voice_view, ephemeral=False)

        select.callback = pull_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)


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
            conn3.commit(); conn3.close()

            await sel_int.followup.send(
                f"✅ {sel_int.user.mention} 报名成功！ Signed up!\n"
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


    async def _report(self, interaction: discord.Interaction):
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


    async def _standings(self, interaction: discord.Interaction):
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


    async def _bracket(self, interaction: discord.Interaction):
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


class Dashboard(commands.Cog):
    """统一控制面板 / Unified Control Panel — 一个界面完成所有操作"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        import aiohttp
        self.session = aiohttp.ClientSession()

    def _build_dashboard_embed(self):
        return discord.Embed(
            title="🎮 GMPT 控制面板 / Control Panel",
            description=(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "**比赛系统 / Match System** | **赛事系统 / Tournament System**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Choose a function from the dropdown menus below / 从下方下拉菜单选择功能\n\n"
                "**比赛系统**：创建比赛 | 报名参加 | 随机分队 | 分 AB 队 | 开打 | 结算 | 拉入语音\n"
                "**赛事系统**：创建赛事 | 报名赛事 | 队长选秀 | 上报比分 | 赛事排名 | 对阵表\n\n"
                "**独立按钮**：选队长 / Captain | Voice LB 语音排行"
            ),
            color=discord.Color.blurple(),
        ).set_footer(text="GMPT Dashboard v3.0")

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

            # Dedup: delete old dashboard panels (bot messages with embed title OR components)
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
                    if not is_panel and msg.components:
                        is_panel = True
                    if is_panel:
                        await msg.delete()
            except Exception:
                pass

            embed = self._build_dashboard_embed()
            view = DashboardView(guild=interaction.guild, session=self.session)

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
            except Exception:
                pass

    @app_commands.command(
        name="gmpt-stats",
        description="View player MMR, rank, and win/loss stats / 查看玩家MMR/段位/胜负",
    )
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
                except Exception:
                    pass

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
        msg = await interaction.channel.send(embed=embed, view=view)
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
        list_msg = await interaction.channel.send(embed=list_embed)
        set_player_list_msg(match_id, list_msg.id)
        conn3 = get_db(); cur3 = conn3.cursor()
        cur3.execute(
            "UPDATE match_view_state SET player_list_msg_id=? WHERE message_id=?",
            (str(list_msg.id), str(msg.id)),
        )
        conn3.commit(); conn3.close()

        await interaction.followup.send(f"已恢复比赛面板 #{match_id} / Panel recovered.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Dashboard(bot))
    # 注册持久化 MatchView，使 Bot 重启后按钮仍可响应
    bot.add_view(MatchView())
