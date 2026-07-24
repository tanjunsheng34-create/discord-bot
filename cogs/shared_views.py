"""
Shared Discord UI Views — imported by multiple cogs to avoid circular imports.
"""
import logging
import discord

logger = logging.getLogger(__name__)
def _display_name(guild, discord_id):
    """Get member display name, fallback to mention."""
    if not guild:
        return f"<@{discord_id}>"
    member = guild.get_member(int(discord_id))
    return member.display_name if member else f"<@{discord_id}>"




class ConfirmView(discord.ui.View):
    """Two-button confirmation dialog (Confirm / Cancel).

    Usage:
        view = ConfirmView(timeout=60)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if view.value:
            ...  # user confirmed
    """

    def __init__(self, timeout=60):
        super().__init__(timeout=timeout)
        self.value = None  # True / False after user clicks

    @discord.ui.button(label="确认 / Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button):
        try:
            await interaction.response.defer(ephemeral=True)
            self.value = True
            for child in self.children:
                child.disabled = True
            await interaction.edit_original_response(view=self)
        except Exception as e:
            logger.error(f"confirm error: {e}")
        finally:
            self.stop()

    @discord.ui.button(label="取消 / Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button):
        try:
            await interaction.response.defer(ephemeral=True)
            self.value = False
            for child in self.children:
                child.disabled = True
            await interaction.edit_original_response(view=self)
        except Exception as e:
            logger.error(f"cancel error: {e}")
        finally:
            self.stop()


# ---- Tournament Views (moved from tournament.py) ----

class CaptainCoinflipView(discord.ui.View):
    """抛硬币决定选人顺序 — 仅两队队长可点。"""

    def __init__(self, captains_info, guild, start_draft_callback):
        super().__init__(timeout=300)
        self.captains = captains_info  # list of {captain_id, team_name, pick_order, tier_score}
        self.guild = guild
        self.start_draft_callback = start_draft_callback
        self._done = False
        self.captain_ids = {str(c["captain_id"]) for c in self.captains}

    def _embed(self, result_text=""):
        cap1 = self.captains[0]
        cap2 = self.captains[1] if len(self.captains) > 1 else None
        name1 = _display_name(self.guild, cap1["captain_id"])
        name2 = _display_name(self.guild, cap2["captain_id"]) if cap2 else "?"
        embed = discord.Embed(
            title="🪙 抛硬币决定选人顺序 / Coinflip for Pick Order",
            description=f"**{name1}** vs **{name2}**\n\n点击按钮选择你猜的正反面，随机决定谁先选！",
            color=discord.Color.gold(),
        )
        if result_text:
            embed.add_field(name="结果 / Result", value=result_text, inline=False)
        return embed

    async def _handle_pick(self, interaction: discord.Interaction, guess: str):
        if self._done:
            return await interaction.response.send_message("硬币已抛过。", ephemeral=True)
        if str(interaction.user.id) not in self.captain_ids:
            return await interaction.response.send_message("只有两队队长可以抛硬币！", ephemeral=True)

        self._done = True
        is_heads = random.choice([True, False])
        result = "正面 Heads" if is_heads else "反面 Tails"

        # captains[0] 默认先选；若反面，则交换 pick_order
        if not is_heads and len(self.captains) > 1:
            self.captains[0], self.captains[1] = self.captains[1], self.captains[0]
        for i, c in enumerate(self.captains, 1):
            c["pick_order"] = i

        winner = _display_name(self.guild, self.captains[0]["captain_id"])
        result_text = f"🪙 硬币结果 Coin Toss Result: {result}！\n👑 **{winner}** 先选！picks first！"

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=self._embed(result_text), view=self)

        # 进入选秀
        await self.start_draft_callback(self.captains)

    @discord.ui.button(label="🪙 正面 Heads", style=discord.ButtonStyle.primary, custom_id="coinflip_heads")
    async def heads_btn(self, interaction: discord.Interaction, button):
        await self._handle_pick(interaction, "heads")

    @discord.ui.button(label="🪙 反面 Tails", style=discord.ButtonStyle.secondary, custom_id="coinflip_tails")
    async def tails_btn(self, interaction: discord.Interaction, button):
        await self._handle_pick(interaction, "tails")


# =============================================================================

class DraftView(discord.ui.View):
    def __init__(self, draft_id, captains_info, available_players, guild, tournament_id=None, timeout=600):
        super().__init__(timeout=None)
        self.draft_id = draft_id
        self.tournament_id = tournament_id
        self.captains = captains_info  # list of {captain_id, team_name, pick_order, tier_score}
        self.available_players = available_players  # list of (discord_id, tier_score, display_name, tier_str)
        self.guild = guild
        self.drafted_players = []  # (captain_id, player_id)
        self.current_pick = 0
        self.snake_round = 1
        self.snake_direction = 1  # 1 = forward, -1 = backward
        self._pending_pick = None
        self._timer_task = None
        self._deadline = 0  # monotonic timestamp when current pick expires
        self._completed = False  # prevents duplicate AssignView sends
        self._last_interaction = None  # stored for auto_skip → AssignView transition

        # Sort captains by pick_order
        self.captains.sort(key=lambda c: c["pick_order"])
        self._rebuild_select()
        self._start_timer()

    def _start_timer(self):
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._deadline = asyncio.get_event_loop().time() + 30
        self._timer_task = asyncio.create_task(self._countdown())

    async def _countdown(self):
        try:
            await asyncio.sleep(30)
            await self._auto_skip()
        except asyncio.CancelledError:
            pass

    async def _auto_skip(self):
        """Auto-skip current captain's turn."""
        unassigned = self._get_unassigned()
        if not unassigned:
            # Draft complete — transition to AssignView if we have a stored interaction
            if self._last_interaction and not self._completed:
                await self._complete_draft(self._last_interaction, auto_balance=False)
            return

        cap = self.current_captain
        if not cap:
            return

        # Auto-pick first available
        auto_pick = unassigned[0]
        with get_db_ctx() as conn:
            cur = conn.cursor()
            pick_num = len(self.drafted_players) + 1
            cur.execute(
                "INSERT INTO draft_picks (draft_id, captain_id, player_id, pick_number) VALUES (?,?,?,?)",
                (self.draft_id, cap["captain_id"], auto_pick[0], pick_num),
            )
            conn.commit()
        self.drafted_players.append((cap["captain_id"], auto_pick[0]))
        self._pending_pick = None

        self.current_pick += 1
        if self.current_pick > 0 and self.current_pick % len(self.captains) == 0:
            self.snake_round += 1
            self.snake_direction *= -1

        # Check if draft complete
        unassigned = self._get_unassigned()
        if not unassigned or len(unassigned) == 0:
            for child in self.children:
                child.disabled = True
            # If we have a stored interaction, auto-transition
            if self._last_interaction and not self._completed:
                self._timer_task = None  # prevent double-fire
                await self._complete_draft(self._last_interaction, auto_balance=False)
                return

        self._rebuild_select()
        self._start_timer()

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
        cap_score = (cap["tier_score"] or 0) if cap else 0
        team_picks = self._get_team_players(captain_id)
        pick_score = 0
        for pid in team_picks:
            player_info = next((p for p in self.available_players if p[0] == pid), None)
            if player_info:
                pick_score += (player_info[1] or 0)
        return cap_score + pick_score

    async def _complete_draft(self, interaction: discord.Interaction, *, auto_balance: bool = False):
        """Transition from DraftView to AssignView when draft completes."""
        if self._completed:
            return
        self._completed = True

        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()

        # Resolve tournament_id from DB if not set
        tid = self.tournament_id
        if not tid:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("SELECT tournament_id FROM draft_sessions WHERE id=?", (self.draft_id,))
                row = cur.fetchone()
                tid = row["tournament_id"] if row else None

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE draft_sessions SET status='completed' WHERE id=?", (self.draft_id,))
            conn.commit()

        # Build all_players for AssignView
        all_players = []
        if tid:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT tp.discord_id, tp.tier, u.display_name FROM tournament_players tp "
                    "LEFT JOIN users u ON u.discord_id=tp.discord_id "
                    "WHERE tp.tournament_id=?",
                    (tid,),
                )
                for row in cur.fetchall():
                    pid = str(row["discord_id"])
                    tier = row["tier"] or ""
                    name = row.get("display_name") or pid
                    score = TIER_SCORE.get(tier.upper(), 0)
                    all_players.append((pid, score, name, tier))

        # Disable current view
        for child in self.children:
            child.disabled = True
        embed = self.build_embed()
        embed.title = "选秀已结束 / Draft Ended"
        embed.description = "⚡ 正在打开分队面板..." if auto_balance else "✅ 正在打开分配面板..."
        embed.color = discord.Color.orange() if auto_balance else discord.Color.gold()
        await interaction.edit_original_response(embed=embed, view=self)

        # Send AssignView as followup
        assign_view = AssignView(
            draft_id=self.draft_id,
            captains_info=self.captains,
            all_players=all_players,
            guild=self.guild,
        )
        if auto_balance:
            assign_view._auto_balance()
            assign_view._rebuild_select()
        await interaction.followup.send(embed=assign_view.build_embed(), view=assign_view)

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
        self._last_interaction = interaction
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
        with get_db_ctx() as conn:
            cur = conn.cursor()
            pick_num = len(self.drafted_players) + 1
            cur.execute(
                "INSERT INTO draft_picks (draft_id, captain_id, player_id, pick_number) VALUES (?,?,?,?)",
                (self.draft_id, cap["captain_id"], self._pending_pick, pick_num),
            )
            conn.commit()

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
            # Auto-transition to AssignView
            self._rebuild_select()
            embed = self.build_embed()
            await interaction.edit_original_response(embed=embed, view=self)
            await self._complete_draft(interaction, auto_balance=False)
            return

        self._rebuild_select()
        self._start_timer()
        embed = self.build_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="跳过 / Skip Turn", style=discord.ButtonStyle.secondary,
                       emoji="⏭️", row=1, custom_id="draft_skip")
    async def skip_turn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        self._last_interaction = interaction
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

        with get_db_ctx() as conn:
            cur = conn.cursor()
            pick_num = len(self.drafted_players) + 1
            cur.execute(
                "INSERT INTO draft_picks (draft_id, captain_id, player_id, pick_number) VALUES (?,?,?,?)",
                (self.draft_id, cap["captain_id"], auto_pick[0], pick_num),
            )
            conn.commit()

        self.drafted_players.append((cap["captain_id"], auto_pick[0]))
        self._pending_pick = None

        self.current_pick += 1
        if self.current_pick > 0 and self.current_pick % len(self.captains) == 0:
            self.snake_round += 1
            self.snake_direction *= -1

        unassigned2 = self._get_unassigned()
        if not unassigned2 or len(unassigned2) == 0:
            for child in self.children:
                child.disabled = True

        self._rebuild_select()
        self._start_timer()
        embed = self.build_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Skip»自动平衡 / Auto Balance", style=discord.ButtonStyle.primary,
                       emoji="⚡", row=2, custom_id="draft_autobalance")
    async def skip_to_autobalance(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        self._last_interaction = interaction
        cap = self.current_captain
        if not cap:
            return await interaction.followup.send("Draft error.", ephemeral=True)
        if str(interaction.user.id) != cap["captain_id"]:
            is_any_captain = any(c["captain_id"] == str(interaction.user.id) for c in self.captains)
            if not is_any_captain:
                return await interaction.followup.send(
                    "Only captains can use this. / 仅队长可用。",
                    ephemeral=True,
                )
        await self._complete_draft(interaction, auto_balance=True)

    @discord.ui.button(label="结束选秀 / End Draft", style=discord.ButtonStyle.danger,
                       emoji="🏁", row=2, custom_id="draft_end")
    async def end_draft(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        self._last_interaction = interaction
        cap = self.current_captain
        if not cap:
            return await interaction.followup.send("Draft error.", ephemeral=True)
        if str(interaction.user.id) != cap["captain_id"]:
            is_any_captain = any(c["captain_id"] == str(interaction.user.id) for c in self.captains)
            if not is_any_captain:
                return await interaction.followup.send(
                    "Only captains can end the draft. / 仅队长可结束选秀。",
                    ephemeral=True,
                )
        await self._complete_draft(interaction, auto_balance=False)

    def build_embed(self):
        remaining = max(0, int(self._deadline - asyncio.get_event_loop().time()))
        cap_name = _display_name(self.guild, self.current_captain['captain_id']) if self.current_captain else 'N/A'
        embed = discord.Embed(
            title=f"Draft — Round {self.snake_round}",
            description=f"Pick #{self.current_pick + 1} — 轮到: **{cap_name}**\n⏱️ 剩余 {remaining}s / {remaining}s remaining",
            color=discord.Color.blue(),
        )

        total_players = len(self.available_players)
        # Team rosters with counts
        for cap in self.captains:
            team = self._get_team_players(cap["captain_id"])
            total_score = self._get_team_score(cap["captain_id"])
            names = [_display_name(self.guild, pid) for pid in team]
            expected_size = total_players // 2 + (total_players % 2 if cap["pick_order"] == 1 else 0)
            embed.add_field(
                name=f"{cap['team_name']} ({len(team)}/{expected_size}) — {total_score} pts",
                value="\n".join(names) if names else "(暂无队员 / Empty)",
                inline=True,
            )

        # Balance report
        scores = [self._get_team_score(c["captain_id"]) or 0 for c in self.captains]
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
# AssignView — 团队分配界面（选秀完成后）
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
        from cogs.tournament import get_tournament_or_none, fetch_player_tier
        await interaction.response.defer(ephemeral=True)
        with get_db_ctx() as conn:
            cur = conn.cursor()
            t = get_tournament_or_none(cur, self.tournament_id)
            if not t or t["status"] != "signup":
                return await interaction.followup.send("该锦标赛报名已关闭。", ephemeral=True)

            uid = str(interaction.user.id)

            tier_restriction = t["tier_restriction"]
            if tier_restriction:
                allowed = set(x.strip().upper() for x in tier_restriction.split(","))
                _, tier_name, _ = await fetch_player_tier(self.session, uid)
                if tier_name and tier_name.upper() not in allowed:
                    return await interaction.followup.send(
                        f"你的段位 **{tier_name}** 不符合本赛事要求（限 {', '.join(sorted(allowed))}）。",
                        ephemeral=True,
                    )

            cur.execute(
                "SELECT id FROM tournament_players WHERE tournament_id=? AND discord_id=?",
                (self.tournament_id, uid),
            )
            if cur.fetchone():
                return await interaction.followup.send("你已经报名了这个锦标赛。", ephemeral=True)

            max_p = t["max_players"] or 32
            cur.execute("SELECT COUNT(*) as cnt FROM tournament_players WHERE tournament_id=?",
                         (self.tournament_id,))
            cnt = cur.fetchone()["cnt"]
            if cnt >= max_p:
                return await interaction.followup.send(f"报名已满（{max_p}人）。", ephemeral=True)

            tier_display, tier_key, _ = await fetch_player_tier(self.session, uid)
            if tier_display is None:
                tier_display = "未关联"
                tier_key = "UNRANKED"


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
            conn.commit()

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
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT tp.discord_id, tp.seed, tp.tier, u.username "
                "FROM tournament_players tp "
                "LEFT JOIN users u ON u.discord_id = tp.discord_id "
                "WHERE tp.tournament_id=? "
                "ORDER BY tp.seed ASC",
                (self.tournament_id,),
            )
            rows = cur.fetchall()

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
        with get_db_ctx() as conn:
            cur = conn.cursor()
            t = get_tournament_or_none(cur, self.tournament_id)
            if not t:
                return await interaction.followup.send("锦标赛不存在。", ephemeral=True)

            is_admin = interaction.user.guild_permissions.administrator
            is_creator = str(interaction.user.id) == (t["created_by"] or "")
            if not is_admin and not is_creator:
                return await interaction.followup.send("仅管理员或赛事创建者可取消。", ephemeral=True)

            if t["status"] == "cancelled":
                return await interaction.followup.send("该赛事已被取消。", ephemeral=True)

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
            conn.commit()

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
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, player_a_id, player_b_id, round, match_index FROM tournament_matches "
                "WHERE tournament_id=? AND status='pending' AND (player_a_id=? OR player_b_id=?) "
                "ORDER BY round, match_index",
                (self.tournament_id, self.user_id, self.user_id),
            )
            self._matches = [dict(r) for r in cur.fetchall()]

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
        from cogs.tournament import swiss_pairing
        from cogs.economy import add_coins
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
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT player_a_id, player_b_id FROM tournament_matches WHERE id=?",
                         (self._pending_match,))
            m = cur.fetchone()
        if not m:
            return await interaction.followup.send("比赛不存在。", ephemeral=True)
        opp_id = m["player_b_id"] if m["player_a_id"] == self.user_id else m["player_a_id"]
        await self._do_report(interaction, opp_id)

    async def _do_report(self, interaction: discord.Interaction, winner_id: str):
        if not self._pending_match:
            return await interaction.response.send_message("请先选择比赛。", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            m = cur.execute("SELECT * FROM tournament_matches WHERE id=?", (self._pending_match,)).fetchone()
            if not m or m["status"] != "pending":
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

        with get_db_ctx() as conn:
            cur = conn.cursor()
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

            conn.commit()

            # Prepare available players for DraftView (exclude captains)
            captain_ids = set(self.captains.keys())

            conn = get_db(); cur = conn.cursor()
            cur.execute("SELECT captain_id, team_name, pick_order, tier_score FROM draft_captains WHERE draft_id=? ORDER BY pick_order", (draft_id,))
            captains_info = [dict(r) for r in cur.fetchall()]

        draft_pool = [(p[0], p[3], p[1], p[2]) for p in self.available_players if p[0] not in captain_ids]

        # ── Coinflip callback: called after captains decide order ──
        async def do_start_draft(final_captains):
            # Update pick_order in DB
            with get_db_ctx() as conn:
                cur = conn.cursor()
                for c in final_captains:
                    cur.execute("UPDATE draft_captains SET pick_order=? WHERE draft_id=? AND captain_id=?",
                                (c["pick_order"], draft_id, c["captain_id"]))
                conn.commit()

            view = DraftView(draft_id, final_captains, draft_pool, interaction.guild, tournament_id=self.tournament_id)
            embed = view.build_embed()
            embed.description = (
                f"队长选秀已开始！\n"
                f"轮到: **{_display_name(interaction.guild, view.current_captain['captain_id'])}**\n\n"
                f"使用下拉菜单选人 → 点击确认按钮\n"
                f"Use dropdown to pick → click Confirm"
            )

            for child in self.children:
                child.disabled = True
            view._msg_ref = await interaction.edit_original_response(embed=embed, view=view)

        # Show coinflip
        coinflip = CaptainCoinflipView(captains_info, interaction.guild, do_start_draft)
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(embed=coinflip._embed(), view=coinflip)

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
# CaptainModeView — 统一入口：模式选择（自动/手动）
# =============================================================================

class CaptainModeView(discord.ui.View):
    """Shared entry point: auto-random or manual-select captain mode.
    Used by both tournament.py /gmpt-tournament captain and dashboard.py Pick Captain button."""
    def __init__(self, all_players, tournament_id, interaction, guild, start_draft_callback):
        super().__init__(timeout=120)
        self.all_players = all_players
        self.tournament_id = tournament_id
        self.interaction = interaction
        self.guild = guild
        self.start_draft_callback = start_draft_callback

    @discord.ui.button(label="🔀 自动随机 Auto Random", style=discord.ButtonStyle.primary, row=0)
    async def auto_btn(self, btn_int: discord.Interaction, button: discord.ui.Button):
        import random as _random
        chosen = _random.sample(self.all_players, 2)
        await self.start_draft_callback(chosen[0], chosen[1], is_random=True)

    @discord.ui.button(label="👤 手动指定 Manual Select", style=discord.ButtonStyle.secondary, row=0)
    async def manual_btn(self, btn_int: discord.Interaction, button: discord.ui.Button):
        # Step 1: Select Team A Captain
        cap_a_options = []
        for p in self.all_players:
            cap_a_options.append(discord.SelectOption(
                label=p["display_name"][:100],
                value=p["discord_id"],
                description=f"Tier: {p['tier']}",
            ))

        cap_a_select = discord.ui.Select(
            placeholder="👑 选择 A 队队长 / Select Team A Captain...",
            options=cap_a_options[:25],
            max_values=1,
        )

        async def cap_a_callback(sel_int: discord.Interaction):
            cap_a_id = sel_int.data["values"][0]
            cap_a_info = next(p for p in self.all_players if p["discord_id"] == cap_a_id)

            cap_b_options = []
            for p in self.all_players:
                if p["discord_id"] == cap_a_id:
                    continue
                cap_b_options.append(discord.SelectOption(
                    label=p["display_name"][:100],
                    value=p["discord_id"],
                    description=f"Tier: {p['tier']}",
                ))

            cap_b_select = discord.ui.Select(
                placeholder="👑 选择 B 队队长 / Select Team B Captain...",
                options=cap_b_options[:25],
                max_values=1,
            )

            async def cap_b_callback(inner_int: discord.Interaction):
                cap_b_id = inner_int.data["values"][0]
                cap_b_info = next(p for p in self.all_players if p["discord_id"] == cap_b_id)

                confirm_embed = discord.Embed(
                    title="✅ 队长已选定 / Captains Selected",
                    description=(
                        f"🔵 **A 队 Team A**: {cap_a_info['display_name']}\n"
                        f"🔴 **B 队 Team B**: {cap_b_info['display_name']}"
                    ),
                    color=discord.Color.blurple(),
                )
                await inner_int.response.edit_message(embed=confirm_embed, view=None)
                await self.start_draft_callback(cap_a_info, cap_b_info, is_random=False)

            cap_b_select.callback = cap_b_callback
            cap_b_view = discord.ui.View(timeout=120)
            cap_b_view.add_item(cap_b_select)
            await sel_int.response.edit_message(
                content="👑 **选择 B 队队长 / Select Team B Captain**:",
                view=cap_b_view,
            )

        cap_a_select.callback = cap_a_callback
        cap_a_view = discord.ui.View(timeout=120)
        cap_a_view.add_item(cap_a_select)
        await btn_int.response.edit_message(
            content="👑 **选择 A 队队长 / Select Team A Captain**:",
            view=cap_a_view,
        )


# =============================================================================
# Tournament Cog
# =============================================================================


