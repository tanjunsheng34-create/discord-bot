"""
GMPT Bot — Dashboard / 统一控制面板
"""
import asyncio
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
        placeholder="e.g. 周五内战",
        max_length=100,
        required=True,
    )
    max_players = discord.ui.TextInput(
        label="最大人数 / Max Players (偶数)",
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
            return await interaction.response.send_message("人数必须是数字。", ephemeral=True)
        if mp < 2 or mp % 2 != 0:
            return await interaction.response.send_message("人数必须为大于2的偶数。", ephemeral=True)

        team_size = mp // 2
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO tournaments (name, max_teams, team_size, created_by, status) VALUES (?, 2, ?, ?, 'open')",
            (self.match_name.value, team_size, str(interaction.user.id)),
        )
        conn.commit(); tid = cur.lastrowid; conn.close()

        embed = discord.Embed(
            title=f"Match: {self.match_name.value}",
            description=f"**{mp}** 人 | 每队 {team_size}\n报名: `/gmpt-join {tid}`",
            color=discord.Color.blue(),
        ).set_footer(text=f"Match ID: {tid}")
        await interaction.response.send_message(embed=embed)


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
            return await interaction.response.send_message("轮数和人数必须是数字。", ephemeral=True)

        fmt = self.tournament_format.value.lower().strip()
        if fmt not in ("swiss", "elimination"):
            return await interaction.response.send_message("赛制仅支持 swiss 或 elimination。", ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("仅管理员可创建锦标赛。", ephemeral=True)

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
                f"点击下方按钮报名、查看列表或取消赛事。"
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
        super().__init__(timeout=timeout)
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
            label = member.display_name if member else pid
            options.append(discord.SelectOption(label=label[:25], value=pid))

        if not options:
            options.append(discord.SelectOption(label="(无待分配玩家)", value="__none__"))

        select = discord.ui.Select(
            placeholder="选择一个玩家 / Select a player...",
            options=options[:25],
            row=0,
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        val = interaction.data["values"][0]
        if val == "__none__":
            return await interaction.response.defer()
        self.selected_player = val
        member = self.guild.get_member(int(val))
        name = member.display_name if member else val
        await interaction.response.send_message(f"已选择: {name}，点击加入A队或B队", ephemeral=True)

    @discord.ui.button(label="加入A队", style=discord.ButtonStyle.primary, emoji="🔵", row=1)
    async def add_to_a(self, interaction: discord.Interaction, button):
        if not self.selected_player:
            return await interaction.response.send_message("请先从下拉菜单选择一个玩家。", ephemeral=True)
        if len(self.team_a) >= self.team_size:
            return await interaction.response.send_message(f"A队已满 ({self.team_size}人)。", ephemeral=True)
        if self.selected_player in self.team_a or self.selected_player in self.team_b:
            return await interaction.response.send_message("该玩家已分配。", ephemeral=True)
        self.team_a.append(self.selected_player)
        self.selected_player = None
        self._rebuild_select()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="加入B队", style=discord.ButtonStyle.danger, emoji="🔴", row=1)
    async def add_to_b(self, interaction: discord.Interaction, button):
        if not self.selected_player:
            return await interaction.response.send_message("请先从下拉菜单选择一个玩家。", ephemeral=True)
        if len(self.team_b) >= self.team_size:
            return await interaction.response.send_message(f"B队已满 ({self.team_size}人)。", ephemeral=True)
        if self.selected_player in self.team_a or self.selected_player in self.team_b:
            return await interaction.response.send_message("该玩家已分配。", ephemeral=True)
        self.team_b.append(self.selected_player)
        self.selected_player = None
        self._rebuild_select()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="清空", style=discord.ButtonStyle.secondary, emoji="🔄", row=2)
    async def clear_teams(self, interaction: discord.Interaction, button):
        self.team_a.clear()
        self.team_b.clear()
        self.selected_player = None
        self._rebuild_select()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="确认分队", style=discord.ButtonStyle.success, emoji="✅", row=2)
    async def confirm_teams(self, interaction: discord.Interaction, button):
        total = len(self.team_a) + len(self.team_b)
        all_players = len(self.all_player_ids)
        if total < min(2, all_players):
            return await interaction.response.send_message("请至少分配2名玩家到队伍中。", ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (self.match_id, "A队 Team A"))
        aid = cur.lastrowid
        for uid in self.team_a:
            cur.execute("UPDATE registrations SET team_id=? WHERE tournament_id=? AND discord_id=?",
                        (aid, self.match_id, uid))
        cur.execute("INSERT INTO teams (tournament_id, name) VALUES (?,?)", (self.match_id, "B队 Team B"))
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
            f"🔵 **A队** (ID:{aid}): {' '.join(a_mentions)}\n"
            f"🔴 **B队** (ID:{bid}): {' '.join(b_mentions)}\n\n"
            f"结算: `/gmpt-settle {self.match_id} <获胜队伍ID>`"
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
            a_names.append(m.display_name if m else uid)
        b_names = []
        for uid in self.team_b:
            m = self.guild.get_member(int(uid))
            b_names.append(m.display_name if m else uid)

        unassigned = self._get_unassigned()
        un_names = []
        for uid in unassigned:
            m = self.guild.get_member(int(uid))
            un_names.append(m.display_name if m else uid)

        if a_names:
            embed.add_field(name=f"🔵 A队 ({len(self.team_a)}/{self.team_size})", value="\n".join(a_names), inline=True)
        if b_names:
            embed.add_field(name=f"🔴 B队 ({len(self.team_b)}/{self.team_size})", value="\n".join(b_names), inline=True)
        if not a_names and not b_names:
            embed.description = "尚未分配任何玩家。"

        if un_names:
            embed.add_field(
                name=f"待分配 ({len(un_names)})",
                value="\n".join(un_names[:10]) + (f"\n... 还有 {len(un_names)-10} 人" if len(un_names) > 10 else ""),
                inline=False,
            )
        return embed


# =============================================================================
# DashboardView — 统一控制面板
# =============================================================================
class DashboardView(discord.ui.View):
    def __init__(self, guild, session, timeout=None):
        super().__init__(timeout=timeout)
        self.guild = guild
        self.session = session

    # ================================================================
    # Row 0 — 自定义分队 (Custom Team)
    # ================================================================

    @discord.ui.button(label="创建比赛", style=discord.ButtonStyle.primary, emoji="🆕", row=0)
    async def create_match_btn(self, interaction: discord.Interaction, button):
        modal = CreateMatchModal(self.guild, self.session)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="报名参加", style=discord.ButtonStyle.success, emoji="✋", row=0)
    async def join_match_btn(self, interaction: discord.Interaction, button):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name, max_teams, team_size FROM tournaments "
            "WHERE status='open' AND max_teams=2 ORDER BY id DESC LIMIT 25"
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.response.send_message("当前没有可报名的比赛。", ephemeral=True)

        options = []
        for m in matches:
            ts = m["team_size"] or 5
            options.append(discord.SelectOption(
                label=m["name"][:100],
                value=str(m["id"]),
                description=f"5v5 | ID: {m['id']}",
            ))

        select = discord.ui.Select(
            placeholder="选择要报名的比赛 / Select a match...",
            options=options[:25],
        )

        async def join_callback(sel_interaction: discord.Interaction):
            mid = int(sel_interaction.data["values"][0])
            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute("SELECT * FROM tournaments WHERE id=?", (mid,))
            t = cur2.fetchone()
            if not t or t["status"] != "open":
                conn2.close()
                return await sel_interaction.response.send_message("报名已关闭。", ephemeral=True)

            max_p = t["max_teams"] * t["team_size"]
            cur2.execute("SELECT COUNT(*) as cnt FROM registrations WHERE tournament_id=?", (mid,))
            cnt = cur2.fetchone()["cnt"]
            if cnt >= max_p:
                conn2.close()
                return await sel_interaction.response.send_message("报名已满。", ephemeral=True)

            uid = str(sel_interaction.user.id)
            try:
                cur2.execute("INSERT INTO registrations (tournament_id, discord_id) VALUES (?,?)", (mid, uid))
                cur2.execute("INSERT OR IGNORE INTO users (discord_id, username) VALUES (?,?)", (uid, sel_interaction.user.name))
                conn2.commit()
            except Exception:
                conn2.close()
                return await sel_interaction.response.send_message("已报名。", ephemeral=True)
            conn2.close()
            await sel_interaction.response.send_message(
                f"✅ {sel_interaction.user.mention} 报名成功！({cnt+1}/{max_p})", ephemeral=True
            )

        select.callback = join_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message(view=view, ephemeral=True)

    @discord.ui.button(label="选队长", style=discord.ButtonStyle.secondary, emoji="👑", row=0)
    async def pick_captain_btn(self, interaction: discord.Interaction, button):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM tournaments WHERE status='open' AND max_teams=2 ORDER BY id DESC LIMIT 25"
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.response.send_message("当前没有可报名的比赛。", ephemeral=True)

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
                return await sel_int.response.send_message("该比赛暂无报名玩家。", ephemeral=True)

            pids = [r["discord_id"] for r in players]
            poptions = []
            for pid in pids:
                member = self.guild.get_member(int(pid))
                name = member.display_name if member else pid
                poptions.append(discord.SelectOption(label=name[:100], value=pid))

            pselect = discord.ui.Select(
                placeholder="选择队长 (最多2人) / Select captains...",
                options=poptions[:25],
                max_values=min(2, len(poptions)),
            )

            async def final_captain_cb(inner_int: discord.Interaction):
                captains = inner_int.data["values"]
                # Store captains in a simple way - for custom matches, just acknowledge
                cap_names = []
                for cid in captains:
                    m = self.guild.get_member(int(cid))
                    cap_names.append(m.display_name if m else cid)
                await inner_int.response.send_message(
                    f"已选队长: {', '.join(cap_names)}\n使用「分 A/B 队」按钮分配队伍。",
                    ephemeral=True,
                )

            pselect.callback = final_captain_cb
            pview = discord.ui.View(timeout=60)
            pview.add_item(pselect)
            await sel_int.response.send_message(view=pview, ephemeral=True)

        select.callback = captain_select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message(view=view, ephemeral=True)

    @discord.ui.button(label="分 A/B 队", style=discord.ButtonStyle.secondary, emoji="⚔️", row=0)
    async def assign_teams_btn(self, interaction: discord.Interaction, button):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name, max_teams, team_size FROM tournaments "
            "WHERE status='open' AND max_teams=2 ORDER BY id DESC LIMIT 25"
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.response.send_message("当前没有可分配的比赛。", ephemeral=True)

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
                return await sel_int.response.send_message("比赛不存在或无报名玩家。", ephemeral=True)

            player_ids = [r["discord_id"] for r in players]
            ts = t["team_size"] or 5
            view = TeamAssignView(mid, t["name"], player_ids, self.guild, ts)
            embed = view._build_embed()
            await sel_int.response.send_message(embed=embed, view=view, ephemeral=False)

        select.callback = assign_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message(view=view, ephemeral=True)

    @discord.ui.button(label="开打", style=discord.ButtonStyle.danger, emoji="🔥", row=0)
    async def start_match_btn(self, interaction: discord.Interaction, button):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM tournaments WHERE status='open' AND max_teams=2 ORDER BY id DESC LIMIT 25"
        )
        matches = cur.fetchall()
        conn.close()

        if not matches:
            return await interaction.response.send_message("当前没有可开始的比赛。", ephemeral=True)

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
                description=f"确定要关闭比赛报名并开始吗？\nMatch ID: {mid}",
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
                content=f"比赛 (ID: {mid}) 已开始！报名已关闭。",
                embed=None,
                view=None,
            )

        select.callback = start_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message(view=view, ephemeral=True)

    # ================================================================
    # Row 1 — 锦标赛 (Tournament)
    # ================================================================

    @discord.ui.button(label="创建赛事", style=discord.ButtonStyle.primary, emoji="🏆", row=1)
    async def create_tournament_btn(self, interaction: discord.Interaction, button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("仅管理员可创建锦标赛。", ephemeral=True)
        modal = CreateTournamentModal(self.guild, self.session)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="报名", style=discord.ButtonStyle.success, emoji="📝", row=1)
    async def signup_tournament_btn(self, interaction: discord.Interaction, button):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name, max_players FROM tournaments WHERE status='signup' ORDER BY id DESC LIMIT 25"
        )
        tournaments = cur.fetchall()
        conn.close()

        if not tournaments:
            return await interaction.response.send_message("当前没有可报名的锦标赛。", ephemeral=True)

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
                return await sel_int.response.send_message("该锦标赛报名已关闭。", ephemeral=True)

            uid = str(sel_int.user.id)

            tier_restriction = t["tier_restriction"]
            if tier_restriction:
                allowed = set(x.strip().upper() for x in tier_restriction.split(","))
                _, tier_name, _ = await fetch_player_tier(self.session, uid)
                if tier_name and tier_name.upper() not in allowed:
                    conn2.close()
                    return await sel_int.response.send_message(
                        f"你的段位 **{tier_name}** 不符合本赛事要求。", ephemeral=True
                    )

            cur2.execute(
                "SELECT id FROM tournament_players WHERE tournament_id=? AND discord_id=?",
                (tid, uid),
            )
            if cur2.fetchone():
                conn2.close()
                return await sel_int.response.send_message("你已经报名了这个锦标赛。", ephemeral=True)

            max_p = t["max_players"] or 32
            cur2.execute("SELECT COUNT(*) as cnt FROM tournament_players WHERE tournament_id=?", (tid,))
            cnt = cur2.fetchone()["cnt"]
            if cnt >= max_p:
                conn2.close()
                return await sel_int.response.send_message(f"报名已满（{max_p}人）。", ephemeral=True)

            tier_display, tier_key, _ = await fetch_player_tier(self.session, uid)
            if tier_display is None:
                tier_display = "未关联"
                tier_key = "UNRANKED"

            conn2.close()

            embed = discord.Embed(
                title="确认报名 / Confirm Signup",
                description=(
                    f"锦标赛: **{t['name']}**\n"
                    f"段位: **{tier_display}**\n"
                    f"人数: **{cnt}/{max_p}**\n\n"
                    f"点击下方按钮确认报名。"
                ),
                color=discord.Color.gold(),
            )
            confirm_view = ConfirmView(timeout=60)
            await sel_int.response.send_message(embed=embed, view=confirm_view, ephemeral=True)
            await confirm_view.wait()
            if confirm_view.value is None or not confirm_view.value:
                return

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

            await sel_int.edit_original_response(
                content=f"✅ {sel_int.user.mention} 报名成功！\n"
                        f"锦标赛: **{t['name']}** | 段位: **{tier_display}** | ({cnt+1}/{max_p})",
                embed=None,
                view=None,
            )

        select.callback = signup_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message(view=view, ephemeral=True)

    @discord.ui.button(label="选秀/选队长", style=discord.ButtonStyle.secondary, emoji="🎯", row=1)
    async def draft_setup_btn(self, interaction: discord.Interaction, button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("仅管理员可设置队长选秀。", ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM tournaments WHERE status IN ('signup','active') ORDER BY id DESC LIMIT 25"
        )
        tournaments = cur.fetchall()
        conn.close()

        if not tournaments:
            return await interaction.response.send_message("没有可用的锦标赛。", ephemeral=True)

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
                return await sel_int.response.send_message(f"可用玩家不足（{len(players)}人），至少需要 2 人。", ephemeral=True)

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
        await interaction.response.send_message(view=view, ephemeral=True)

    @discord.ui.button(label="上报比分", style=discord.ButtonStyle.danger, emoji="📊", row=1)
    async def report_btn(self, interaction: discord.Interaction, button):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM tournaments WHERE status='active' ORDER BY id DESC LIMIT 25"
        )
        tournaments = cur.fetchall()
        conn.close()

        if not tournaments:
            return await interaction.response.send_message("没有进行中的锦标赛。", ephemeral=True)

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
                "选择你的比赛并上报比分：",
                view=view,
                ephemeral=True,
            )

        select.callback = report_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message(view=view, ephemeral=True)

    @discord.ui.button(label="排名", style=discord.ButtonStyle.secondary, emoji="📈", row=1)
    async def standings_btn(self, interaction: discord.Interaction, button):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM tournaments WHERE status IN ('active','completed') ORDER BY id DESC LIMIT 25"
        )
        tournaments = cur.fetchall()
        conn.close()

        if not tournaments:
            return await interaction.response.send_message("没有可查看的锦标赛。", ephemeral=True)

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
                return await sel_int.response.send_message("暂无玩家数据。", ephemeral=True)

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
            await sel_int.response.send_message(embed=embed, ephemeral=True)

        select.callback = standings_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message(view=view, ephemeral=True)

    @discord.ui.button(label="对阵表", style=discord.ButtonStyle.secondary, emoji="📋", row=1)
    async def bracket_btn(self, interaction: discord.Interaction, button):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM tournaments WHERE status IN ('active','completed') ORDER BY id DESC LIMIT 25"
        )
        tournaments = cur.fetchall()
        conn.close()

        if not tournaments:
            return await interaction.response.send_message("没有可查看的锦标赛。", ephemeral=True)

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
                return await sel_int.response.send_message("暂无对阵数据。", ephemeral=True)

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
        await interaction.response.send_message(view=view, ephemeral=True)


# =============================================================================
# Dashboard Cog
# =============================================================================
class Dashboard(commands.Cog):
    """统一控制面板 — 一个界面完成所有操作"""

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
    async def dashboard_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="GMPT 控制面板",
            description=(
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "**自定义分队 (Custom Team)** | **锦标赛 (Tournament)**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "选择一个功能开始操作\n\n"
                "第一行: 创建比赛 | 报名参加 | 选队长 | 分 A/B 队 | 开打\n"
                "第二行: 创建赛事 | 报名 | 选秀/选队长 | 上报比分 | 排名 | 对阵表"
            ),
            color=discord.Color.blurple(),
        ).set_footer(text="GMPT Dashboard v1.0")
        view = DashboardView(guild=interaction.guild, session=self.session)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(Dashboard(bot))
