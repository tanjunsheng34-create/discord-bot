"""
GMPT Bot — Dashboard / 统一控制面板
"""
import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db

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
            member = self.guild.get_member(int(pid))
            label = member.display_name if member else f"<@{pid}>"
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
            return await interaction.response.defer()
        self.selected_player = val
        member = self.guild.get_member(int(val))
        name = member.display_name if member else f"<@{val}>"
        await interaction.followup.send(f"已选择 / Selected: {name}，点击加入 A 队或 B 队", ephemeral=True)

    @discord.ui.button(label="加入 A 队 / A", style=discord.ButtonStyle.primary, emoji="🔵", row=1)
    async def add_to_a(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if not self.selected_player:
            return await interaction.followup.send("请先从下拉菜单选择一个玩家 / Select a player first.", ephemeral=True)
        if len(self.team_a) >= self.team_size:
            return await interaction.followup.send(f"A 队已满 (上限 {self.team_size}) / Team A full.", ephemeral=True)
        if self.selected_player in self.team_a or self.selected_player in self.team_b:
            return await interaction.followup.send("该玩家已分配 / Already assigned.", ephemeral=True)
        self.team_a.append(self.selected_player)
        self.selected_player = None
        self._rebuild_select()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="加入 B 队 / B", style=discord.ButtonStyle.danger, emoji="🔴", row=1)
    async def add_to_b(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if not self.selected_player:
            return await interaction.followup.send("请先从下拉菜单选择一个玩家 / Select a player first.", ephemeral=True)
        if len(self.team_b) >= self.team_size:
            return await interaction.followup.send(f"B 队已满 (上限 {self.team_size}) / Team B full.", ephemeral=True)
        if self.selected_player in self.team_a or self.selected_player in self.team_b:
            return await interaction.followup.send("该玩家已分配 / Already assigned.", ephemeral=True)
        self.team_b.append(self.selected_player)
        self.selected_player = None
        self._rebuild_select()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="清空 / Clear", style=discord.ButtonStyle.secondary, emoji="🔄", row=2)
    async def clear_teams(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        self.team_a.clear()
        self.team_b.clear()
        self.selected_player = None
        self._rebuild_select()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="确认分队 / Confirm", style=discord.ButtonStyle.success, emoji="✅", row=2)
    async def confirm_teams(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        total = len(self.team_a) + len(self.team_b)
        all_players = len(self.all_player_ids)
        if total < min(2, all_players):
            return await interaction.followup.send("请至少分配 2 名玩家到队伍中 / Assign at least 2 players.", ephemeral=True)

        conn = get_db(); cur = conn.cursor()
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
        await interaction.response.edit_message(embed=embed, view=self)

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
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO match_view_state (message_id, match_id, channel_id, player_list_msg_id) "
        "VALUES (?, ?, ?, ?)",
        (str(message_id), match_id, channel_id, str(player_list_msg_id) if player_list_msg_id else None),
    )
    conn.commit(); conn.close()


def get_match_id_from_message(message_id: int) -> int | None:
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT match_id, channel_id, player_list_msg_id FROM match_view_state WHERE message_id=?", (str(message_id),))
    row = cur.fetchone()
    conn.close()
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
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM tournaments WHERE id=?", (match_id,))
    row = cur.fetchone()
    conn.close()
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
        cur.execute("SELECT discord_id, is_sub FROM registrations WHERE tournament_id=? ORDER BY is_sub ASC, id ASC", (match_id,))
        rows = cur.fetchall()
        cur.execute("SELECT max_teams, team_size FROM tournaments WHERE id=?", (match_id,))
        t = cur.fetchone()
        conn.close()
        max_p = (t["max_teams"] * t["team_size"]) if t else 0

        main_names = []
        sub_names = []
        for r in rows:
            member = interaction.guild.get_member(int(r["discord_id"]))
            name = member.display_name if member else f"<@{r['discord_id']}>"
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
        embed = discord.Embed(
            title=f"已报名玩家 / Signed Up ({count}/{max_p})" + (f" + {len(sub_names)} 替补" if sub_names else ""),
            description=desc,
            color=discord.Color.green(),
        )
        new_msg = await interaction.channel.send(embed=embed)
        _player_list_msgs[match_id] = new_msg.id
        # Also persist player_list_msg_id in DB
        conn2 = get_db(); cur2 = conn2.cursor()
        cur2.execute(
            "UPDATE match_view_state SET player_list_msg_id=? WHERE message_id=?",
            (str(new_msg.id), str(interaction.message.id)),
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

            cur.execute("INSERT INTO registrations (tournament_id, discord_id) VALUES (?,?)", (mid, uid))
            cur.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (uid, interaction.user.name))
            conn.commit(); conn.close()
            await interaction.followup.send(
                f"✅ {interaction.user.mention} 报名成功！ Signed up! ({cnt+1}/{max_p})", ephemeral=True
            )
            await self._refresh_list(interaction, mid)
        except Exception as e:
            import traceback
            print(f"[MatchView] signup error: {e}")
            traceback.print_exc()
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
                member = guild.get_member(int(r["discord_id"]))
                name = member.display_name if member else f"<@{r['discord_id']}>"
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
            import traceback
            print(f"[MatchView] view error: {e}")
            traceback.print_exc()
            await interaction.followup.send("查询失败 / Query failed.", ephemeral=True)

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
                    member = guild.get_member(int(p["discord_id"]))
                    name = member.display_name if member else f"<@{p['discord_id']}>"
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

                    await _execute_settle(
                        match_id=mid,
                        win_team_id=flow.win_team_id,
                        mvp_id=flow.mvp_id,
                        guild=guild,
                        match_name=t["name"],
                    )

                    await mvp_int.edit_original_response(
                        content="✅ 结算完成！ / Settle complete!", embed=None, view=None
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
            import traceback
            print(f"[MatchView] settle error: {e}")
            traceback.print_exc()
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

            cur.execute("DELETE FROM registrations WHERE tournament_id=? AND discord_id=?", (mid, uid))
            conn.commit(); conn.close()
            await interaction.followup.send(
                f"🚪 {interaction.user.mention} 已退赛 / Left the match.", ephemeral=True
            )
            await self._refresh_list(interaction, mid)
        except Exception as e:
            import traceback
            print(f"[MatchView] leave error: {e}")
            traceback.print_exc()
            await interaction.followup.send("退赛失败 / Leave failed, please try again.", ephemeral=True)

    @discord.ui.button(label="管理员加人", style=discord.ButtonStyle.primary, emoji="➕", row=2, custom_id="matchv2_admin_add")
    async def admin_add_btn(self, interaction: discord.Interaction, button):
        """Admin-only: manually add a player to the match via a modal."""
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("管理员专用 / Admin only.", ephemeral=True)

        mid, t, guild = await self._get_context(interaction)
        if not t:
            return await interaction.response.send_message("比赛不存在 / Match not found.", ephemeral=True)
        if t["status"] != "open":
            return await interaction.response.send_message("报名已关闭 / Signup closed.", ephemeral=True)

        modal = AdminAddPlayerModal(match_id=mid, guild=guild)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="替补", style=discord.ButtonStyle.secondary, emoji="🔄", row=2, custom_id="matchv2_sub")
    async def sub_btn(self, interaction: discord.Interaction, button):
        """Admin-only: set a player as substitute (does not count toward capacity)."""
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("管理员专用 / Admin only.", ephemeral=True)

        mid, t, guild = await self._get_context(interaction)
        if not t:
            return await interaction.response.send_message("比赛不存在 / Match not found.", ephemeral=True)
        if t["status"] != "open":
            return await interaction.response.send_message("报名已关闭 / Signup closed.", ephemeral=True)

        modal = AdminSubPlayerModal(match_id=mid, guild=guild)
        await interaction.response.send_modal(modal)


# ══════════ 向后兼容别名══════════
MatchView = MatchViewWithID


# =============================================================================
# Helper: execute settlement (coin distribution + achievements)
# =============================================================================
async def _execute_settle(match_id, win_team_id, mvp_id, guild, match_name):
    """Distribute coins, record results, check achievements. Reused by both dashboard and MatchView."""
    from cogs.economy import check_achievement

    conn = get_db(); cur = conn.cursor()

    # Winner +150
    cur.execute("SELECT discord_id FROM registrations WHERE tournament_id=? AND team_id=?", (match_id, win_team_id))
    winner_ids = [r["discord_id"] for r in cur.fetchall()]
    for wid in winner_ids:
        cur.execute("INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING", (wid,))
        cur.execute("UPDATE users SET score=score+150 WHERE discord_id=?", (wid,))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (wid, 150, f"Match win #{match_id}"))
    cur.execute("INSERT INTO results (tournament_id,team_id,rank,score_awarded) VALUES (?,?,1,150)", (match_id, win_team_id))

    # Loser +50
    cur.execute("SELECT discord_id FROM registrations WHERE tournament_id=? AND team_id!=?", (match_id, win_team_id))
    loser_ids = [r["discord_id"] for r in cur.fetchall()]
    for lid in loser_ids:
        cur.execute("INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING", (lid,))
        cur.execute("UPDATE users SET score=score+50 WHERE discord_id=?", (lid,))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (lid, 50, f"Match participation #{match_id}"))

    # MVP +50
    if mvp_id:
        cur.execute("INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING", (mvp_id,))
        cur.execute("UPDATE users SET score=score+50 WHERE discord_id=?", (mvp_id,))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (mvp_id, 50, f"MVP #{match_id}"))

    cur.execute("UPDATE tournaments SET status='finished' WHERE id=?", (match_id,))
    conn.commit(); conn.close()

    # Achievement checks
    all_participants = winner_ids + loser_ids
    for pid in set(all_participants):
        conn2 = get_db(); cur2 = conn2.cursor()
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


# =============================================================================
# DashboardView — 统一控制面板 / Unified Control Panel
# =============================================================================

class DashboardView(discord.ui.View):
    def __init__(self, guild, session, timeout=None):
        super().__init__(timeout=None)
        self.guild = guild
        self.session = session

    # ================================================================
    # Row 0 — 自定义分队 / Custom Team
    # ================================================================

    @discord.ui.button(label="创建比赛 Create", style=discord.ButtonStyle.primary, emoji="🆕", row=0)
    async def create_match_btn(self, interaction: discord.Interaction, button):
        modal = CreateMatchModal(self.guild, self.session)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="报名参加 Join", style=discord.ButtonStyle.success, emoji="✋", row=0)
    async def join_match_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name, max_teams, team_size FROM tournaments "
            "WHERE status='open' AND max_teams=2 ORDER BY id DESC LIMIT 25"
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.followup.send("当前没有可报名的比赛 / No open matches.", ephemeral=True)

        options = []
        for m in matches:
            ts = m["team_size"] or 5
            options.append(discord.SelectOption(
                label=m["name"][:100],
                value=str(m["id"]),
                description=f"5v5 | ID: {m['id']}",
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
                return await sel_interaction.followup.send("报名已关闭 / Signup closed.", ephemeral=True)

            max_p = t["max_teams"] * t["team_size"]
            cur2.execute("SELECT COUNT(*) as cnt FROM registrations WHERE tournament_id=? AND (is_sub IS NULL OR is_sub=0)", (mid,))
            cnt = cur2.fetchone()["cnt"]
            if cnt >= max_p:
                conn2.close()
                return await sel_interaction.followup.send("报名已满 / Signup full.", ephemeral=True)

            uid = str(sel_interaction.user.id)
            try:
                cur2.execute("INSERT INTO registrations (tournament_id, discord_id) VALUES (?,?)", (mid, uid))
                cur2.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (uid, sel_interaction.user.name))
                conn2.commit()
            except Exception:
                conn2.close()
                return await sel_interaction.followup.send("已报名 / Already signed up.", ephemeral=True)
            conn2.close()
            await sel_interaction.followup.send(
                f"✅ {sel_interaction.user.mention} 报名成功！ Signed up! ({cnt+1}/{max_p})", ephemeral=True
            )

        select.callback = join_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    @discord.ui.button(label="选队长 Captain", style=discord.ButtonStyle.secondary, emoji="👑", row=0)
    async def pick_captain_btn(self, interaction: discord.Interaction, button):
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
                member = self.guild.get_member(int(pid))
                name = member.display_name if member else f"<@{pid}>"
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

    @discord.ui.button(label="随机分队 Shuffle", style=discord.ButtonStyle.secondary, emoji="🎲", row=0)
    async def shuffle_btn(self, interaction: discord.Interaction, button):
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

    @discord.ui.button(label="分 A/B 队 Teams", style=discord.ButtonStyle.secondary, emoji="⚔️", row=0)
    async def assign_teams_btn(self, interaction: discord.Interaction, button):
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

    # ================================================================
    # Row 1 — 自定义分队 / Custom Team (continued)
    # ================================================================

    @discord.ui.button(label="开打 Start", style=discord.ButtonStyle.danger, emoji="🔥", row=1)
    async def start_match_btn(self, interaction: discord.Interaction, button):
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

        select.callback = start_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    @discord.ui.button(label="结算 Settle", style=discord.ButtonStyle.success, emoji="💰", row=1)
    async def settle_btn(self, interaction: discord.Interaction, button):
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
                return await sel_int.response.send_message("比赛不存在 / Match not found.", ephemeral=True)
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
                    member = self.guild.get_member(int(p["discord_id"]))
                    name = member.display_name if member else f"<@{p['discord_id']}>"
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

                    await _execute_settle(
                        match_id=mid,
                        win_team_id=flow.win_team_id,
                        mvp_id=flow.mvp_id,
                        guild=self.guild,
                        match_name=t["name"],
                    )
                    await mvp_int.edit_original_response(
                        content="✅ 结算完成！ / Settle complete!", embed=None, view=None
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

    # ================================================================
    # Row 2 — 锦标赛 / Tournament
    # ================================================================

    @discord.ui.button(label="创建赛事 Tournament", style=discord.ButtonStyle.primary, emoji="🏆", row=2)
    async def create_tournament_btn(self, interaction: discord.Interaction, button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.defer(ephemeral=True)
            return await interaction.followup.send("仅管理员可创建锦标赛 / Admin only.", ephemeral=True)
        modal = CreateTournamentModal(self.guild, self.session)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="报名 Sign Up", style=discord.ButtonStyle.success, emoji="📝", row=2)
    async def signup_tournament_btn(self, interaction: discord.Interaction, button):
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
                return await sel_int.response.send_message("该锦标赛报名已关闭 / Signup closed.", ephemeral=True)

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

    @discord.ui.button(label="选秀/选队长 Draft", style=discord.ButtonStyle.secondary, emoji="🎯", row=2)
    async def draft_setup_btn(self, interaction: discord.Interaction, button):
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

    @discord.ui.button(label="上报比分 Report", style=discord.ButtonStyle.danger, emoji="📊", row=2)
    async def report_btn(self, interaction: discord.Interaction, button):
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

    @discord.ui.button(label="排名 Standings", style=discord.ButtonStyle.secondary, emoji="📈", row=2)
    async def standings_btn(self, interaction: discord.Interaction, button):
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

    @discord.ui.button(label="对阵表 Bracket", style=discord.ButtonStyle.secondary, emoji="📋", row=3)
    async def bracket_btn(self, interaction: discord.Interaction, button):
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

    @discord.ui.button(label="Voice LB 语音排行", style=discord.ButtonStyle.secondary, emoji="🎤", row=3)
    async def voice_lb_btn(self, interaction: discord.Interaction, button):
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

    def _get_voice_cog(self, interaction):
        """Obtain the VoiceTracker cog from the bot."""
        from cogs.voice_tracker import VoiceTracker
        for cog in interaction.client.cogs.values():
            if isinstance(cog, VoiceTracker):
                return cog
        # Fallback: create a lightweight wrapper
        from cogs.voice_tracker import format_duration
        class LightVoiceTracker:
            def _build_leaderboard_embed(self, data, page, guild):
                per_page = 10
                start = page * per_page
                end = min(start + per_page, len(data))
                page_data = data[start:end]
                total_pages = (len(data) + per_page - 1) // per_page
                embed = discord.Embed(
                    title="Voice Leaderboard",
                    description=f"Total **{len(data)}** users | Page **{page + 1}/{total_pages}**",
                    color=discord.Color.purple(),
                )
                lines = []
                for i, row in enumerate(page_data, start + 1):
                    uid = row["user_id"]
                    member = guild.get_member(int(uid)) if guild else None
                    name = member.display_name if member else f"<@{uid}>"
                    total_seconds = row["total_seconds"] or 0
                    login_days = row["login_days"] or 0
                    total_joins = row["total_joins"] or 0
                    medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f" #{i}"
                    lines.append(
                        f"{medal} **{name}**\n"
                        f"　　Time: `{format_duration(total_seconds)}` | Days: `{login_days}` | Joins: `{total_joins}`"
                    )
                embed.add_field(
                    name=f"Top {start + 1}-{end}",
                    value="\n".join(lines) if lines else "(Empty)",
                    inline=False,
                )
                return embed
        return LightVoiceTracker()


# =============================================================================
# Dashboard Cog
# =============================================================================

class Dashboard(commands.Cog):
    """统一控制面板 / Unified Control Panel — 一个界面完成所有操作"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        import aiohttp
        self.session = aiohttp.ClientSession()

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
            await interaction.response.defer(ephemeral=False, thinking=False)

            embed = discord.Embed(
                title="🎮 GMPT 控制面板 / Control Panel",
                description=(
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "**自定义分队 / Custom Team** | **锦标赛 / Tournament**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Choose a function to begin / 选择一个功能开始操作\n\n"
                    "Row 1: 创建比赛 Create | 报名参加 Join | 选队长 Captain | 随机分队 Shuffle | 分 A/B 队 Teams\n"
                    "Row 2: 开打 Start | 结算 Settle\n"
                    "Row 3: 创建赛事 Tournament | 报名 Sign Up | 选秀/选队长 Draft | 上报比分 Report | 排名 Standings\n"
                    "Row 4: 对阵表 Bracket | Voice LB 语音排行"
                ),
                color=discord.Color.blurple(),
            ).set_footer(text="GMPT Dashboard v1.2")
            view = DashboardView(guild=interaction.guild, session=self.session)

            target = channel or interaction.channel
            if target != interaction.channel:
                await target.send(embed=embed, view=view)
                await interaction.followup.send(
                    f"Dashboard sent to {target.mention}", ephemeral=True
                )
            else:
                await interaction.followup.send(embed=embed, view=view)
        except Exception as e:
            import traceback
            print(f"[Dashboard] Error in dashboard_cmd: {e}")
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    "控制面板加载失败 / Dashboard failed to load. Please try again.", ephemeral=True
                )
            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(Dashboard(bot))
    # 注册持久化 MatchView，使 Bot 重启后按钮仍可响应
    bot.add_view(MatchView())
