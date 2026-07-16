"""
GMPT Bot — Giveaway 抽奖系统
/gmpt-giveaway create / end / reroll / list
带按钮交互：参加/退出/查看参与名单
"""
import asyncio
import random
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db


# =============================================================================
# Global bot reference (set on cog load)
# =============================================================================
_bot_ref = None


# =============================================================================
# Giveaway Modal — 创建抽奖表单
# =============================================================================
class GiveawayModal(discord.ui.Modal, title="创建抽奖 / Create Giveaway"):
    prize = discord.ui.TextInput(
        label="奖品名称 / Prize Name",
        placeholder="e.g. 1000 GMPT Coins",
        max_length=200,
        required=True,
    )
    duration = discord.ui.TextInput(
        label="时长 (分钟) / Duration (minutes)",
        placeholder="10",
        default="10",
        max_length=5,
        required=True,
    )
    winners = discord.ui.TextInput(
        label="获奖人数 / Winner Count",
        placeholder="1",
        default="1",
        max_length=3,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            duration_mins = int(self.duration.value)
            winner_count = int(self.winners.value)
        except ValueError:
            return await interaction.response.send_message(
                "时长和获奖人数必须是数字 / Duration and winner count must be numbers.",
                ephemeral=True,
            )
        if duration_mins < 1:
            return await interaction.response.send_message("时长至少 1 分钟 / Duration must be at least 1 minute.", ephemeral=True)
        if winner_count < 1:
            return await interaction.response.send_message("获奖人数至少 1 人 / Winner count must be at least 1.", ephemeral=True)

        ends_at = (datetime.now() + timedelta(minutes=duration_mins)).isoformat()

        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO giveaway (guild_id, channel_id, prize, duration_minutes, winner_count, created_by, ends_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'active')",
            (
                str(interaction.guild_id),
                str(interaction.channel_id),
                self.prize.value,
                duration_mins,
                winner_count,
                str(interaction.user.id),
                ends_at,
            ),
        )
        conn.commit()
        gid = cur.lastrowid
        conn.close()

        embed = build_giveaway_embed(gid, self.prize.value, winner_count, duration_mins, ends_at, 0)
        view = GiveawayView(gid, winner_count)
        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()

        # Save message ID
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE giveaway SET message_id=? WHERE id=?", (str(msg.id), gid))
        conn.commit(); conn.close()

        # Schedule auto-end
        asyncio.create_task(auto_end_giveaway(gid, duration_mins))


# =============================================================================
# GiveawayView — 按钮交互
# =============================================================================
class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id, winner_count, timeout=None):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self.winner_count = winner_count

    @discord.ui.button(label="参加 Enter", style=discord.ButtonStyle.success, emoji="🎉", custom_id="gw_enter")
    async def enter_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT status FROM giveaway WHERE id=?", (self.giveaway_id,))
        gw = cur.fetchone()
        if not gw or gw["status"] != "active":
            conn.close()
            return await interaction.response.send_message("该抽奖已结束 / This giveaway has ended.", ephemeral=True)

        try:
            cur.execute(
                "INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?,?)",
                (self.giveaway_id, uid),
            )
            conn.commit()
            action = "joined / 加入了"
        except Exception:
            # Already entered -> remove
            cur.execute(
                "DELETE FROM giveaway_entries WHERE giveaway_id=? AND user_id=?",
                (self.giveaway_id, uid),
            )
            conn.commit()
            action = "left / 退出了"

        cur.execute("SELECT COUNT(*) as cnt FROM giveaway_entries WHERE giveaway_id=?", (self.giveaway_id,))
        cnt = cur.fetchone()["cnt"]
        conn.close()

        await interaction.response.send_message(
            f"✅ {interaction.user.mention} {action} 抽奖！当前参与人数: **{cnt}** / "
            f"You {action} the giveaway! Current entries: **{cnt}**",
            ephemeral=True,
        )

    @discord.ui.button(label="查看参与 View Entries", style=discord.ButtonStyle.secondary, emoji="📋", custom_id="gw_view")
    async def view_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT user_id FROM giveaway_entries WHERE giveaway_id=?", (self.giveaway_id,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return await interaction.response.send_message("暂无参与者 / No entries yet.", ephemeral=True)

        entries = []
        for i, r in enumerate(rows, 1):
            entries.append(f"{i}. <@{r['user_id']}>")

        await interaction.response.send_message(
            f"**参与者 ({len(entries)} 人) / Entries:**\n" + "\n".join(entries),
            ephemeral=True,
        )


# =============================================================================
# Giveaway Cog
# =============================================================================

    async def on_timeout(self):
        for child in self.children:
            if hasattr(child, 'disabled'):
                child.disabled = True
        if hasattr(self, 'message') and self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

class Giveaway(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        global _bot_ref
        _bot_ref = bot

    giveaway_group = app_commands.Group(
        name="gmpt-giveaway",
        description="Giveaway system / 抽奖系统",
    )

    @giveaway_group.command(name="create", description="Create a new giveaway / 创建抽奖")
    async def create_cmd(self, interaction: discord.Interaction):
        modal = GiveawayModal()
        await interaction.response.send_modal(modal)

    @giveaway_group.command(name="end", description="Manually end a giveaway / 手动结束抽奖")
    async def end_cmd(self, interaction: discord.Interaction):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, prize, winner_count, message_id, channel_id FROM giveaway WHERE status='active' ORDER BY id DESC LIMIT 25"
        )
        active = cur.fetchall()
        conn.close()

        if not active:
            return await interaction.response.send_message("没有进行中的抽奖 / No active giveaways.", ephemeral=True)

        options = []
        for g in active:
            options.append(discord.SelectOption(
                label=f"#{g['id']} {g['prize'][:80]}",
                value=str(g["id"]),
                description=f"ID: {g['id']}",
            ))

        select = discord.ui.Select(
            placeholder="选择要结束的抽奖 / Select giveaway to end...",
            options=options[:25],
        )

        async def select_callback(sel_int: discord.Interaction):
            gid = int(sel_int.data["values"][0])
            await sel_int.response.defer(ephemeral=True)
            await end_giveaway(gid, self.bot)
            await sel_int.followup.send(f"抽奖 #{gid} 已结束 / Giveaway #{gid} ended.", ephemeral=True)

        select.callback = select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message(view=view, ephemeral=True)

    @giveaway_group.command(name="reroll", description="Re-roll winners from existing entries / 重新抽奖")
    async def reroll_cmd(self, interaction: discord.Interaction):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, prize, winner_count FROM giveaway WHERE status='ended' ORDER BY id DESC LIMIT 25"
        )
        ended = cur.fetchall()
        conn.close()

        if not ended:
            return await interaction.response.send_message("没有已结束的抽奖 / No ended giveaways to reroll.", ephemeral=True)

        options = []
        for g in ended:
            options.append(discord.SelectOption(
                label=f"#{g['id']} {g['prize'][:80]}",
                value=str(g["id"]),
                description=f"Winner count: {g['winner_count']}",
            ))

        select = discord.ui.Select(
            placeholder="选择要重抽的抽奖 / Select giveaway to reroll...",
            options=options[:25],
        )

        async def select_callback(sel_int: discord.Interaction):
            gid = int(sel_int.data["values"][0])
            conn2 = get_db(); cur2 = conn2.cursor()
            cur2.execute("SELECT prize, winner_count, message_id, channel_id, guild_id FROM giveaway WHERE id=?", (gid,))
            g = cur2.fetchone()
            if not g:
                conn2.close()
                return await sel_int.response.send_message("抽奖不存在 / Giveaway not found.", ephemeral=True)

            cur2.execute("SELECT user_id FROM giveaway_entries WHERE giveaway_id=?", (gid,))
            entries = [r["user_id"] for r in cur2.fetchall()]
            conn2.close()

            if not entries:
                return await sel_int.response.send_message("没有参与者可以重抽 / No entries to reroll.", ephemeral=True)

            wc = min(g["winner_count"], len(entries))
            winners = random.sample(entries, wc)

            embed = discord.Embed(
                title=f"🎊 抽奖重抽 / Giveaway Reroll — {g['prize']}",
                description=f"新中奖名单 / New Winners:\n" + "\n".join(f"🎉 <@{w}>" for w in winners),
                color=discord.Color.gold(),
                timestamp=datetime.now(),
            )
            embed.set_footer(text=f"Giveaway ID: {gid} | Re-rolled by {interaction.user.display_name}")

            channel = self.bot.get_channel(int(g["channel_id"])) if g["channel_id"] else interaction.channel
            if channel:
                await channel.send(embed=embed)

            await sel_int.response.send_message("重抽完成 / Reroll complete!", ephemeral=True)

        select.callback = select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message(view=view, ephemeral=True)

    @giveaway_group.command(name="list", description="List all active giveaways / 列出所有进行中抽奖")
    async def list_cmd(self, interaction: discord.Interaction):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, prize, winner_count, duration_minutes, ends_at, created_by FROM giveaway WHERE status='active' ORDER BY id DESC"
        )
        active = cur.fetchall()
        conn.close()

        if not active:
            return await interaction.response.send_message("当前没有进行中的抽奖 / No active giveaways.", ephemeral=True)

        embed = discord.Embed(
            title="🎉 进行中的抽奖 / Active Giveaways",
            color=discord.Color.gold(),
        )

        for g in active:
            cur2 = get_db().cursor()
            cur2.execute("SELECT COUNT(*) as cnt FROM giveaway_entries WHERE giveaway_id=?", (g["id"],))
            cnt = cur2.fetchone()["cnt"]
            cur2.connection.close()

            ends = g["ends_at"][:16] if g["ends_at"] else "?"
            embed.add_field(
                name=f"#{g['id']} — {g['prize']}",
                value=f"获奖数: **{g['winner_count']}** | 参与者: **{cnt}**\n"
                      f"时长: {g['duration_minutes']} min | 结束: {ends}\n"
                      f"创建者: <@{g['created_by']}>",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)


# =============================================================================
# Helper functions
# =============================================================================
def build_giveaway_embed(gid, prize, winner_count, duration_mins, ends_at, entry_count):
    ends_dt = datetime.fromisoformat(ends_at) if ends_at else datetime.now()
    embed = discord.Embed(
        title=f"🎉 GIVEAWAY — {prize}",
        description=(
            f"点击下方按钮参加抽奖！\nClick the button below to enter!\n\n"
            f"🎁 奖品 / Prize: **{prize}**\n"
            f"👥 获奖人数 / Winners: **{winner_count}**\n"
            f"⏰ 结束时间 / Ends: <t:{int(ends_dt.timestamp())}:R>\n"
            f"📊 参与者 / Entries: **{entry_count}**"
        ),
        color=discord.Color.gold(),
    )
    embed.set_footer(text=f"Giveaway ID: {gid}")
    return embed


async def end_giveaway(gid, bot):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT prize, winner_count, message_id, channel_id FROM giveaway WHERE id=?", (gid,))
    g = cur.fetchone()
    if not g:
        conn.close()
        return

    cur.execute("UPDATE giveaway SET status='ended' WHERE id=?", (gid,))

    cur.execute("SELECT user_id FROM giveaway_entries WHERE giveaway_id=?", (gid,))
    entries = [r["user_id"] for r in cur.fetchall()]
    conn.commit()
    conn.close()

    wc = min(g["winner_count"], len(entries))
    if wc == 0:
        embed = discord.Embed(
            title=f"🎉 GIVEAWAY ENDED — {g['prize']}",
            description="无人参加 / No entries!",
            color=discord.Color.red(),
        )
    else:
        winners = random.sample(entries, wc)
        embed = discord.Embed(
            title=f"🎉 GIVEAWAY ENDED — {g['prize']}",
            description="恭喜中奖 / Congratulations!\n\n" + "\n".join(f"🎊 <@{w}>" for w in winners),
            color=discord.Color.gold(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="参与人数 / Total Entries", value=str(len(entries)), inline=True)

    embed.set_footer(text=f"Giveaway ID: {gid}")

    if bot and g["message_id"] and g["channel_id"]:
        try:
            channel = bot.get_channel(int(g["channel_id"]))
            if channel:
                await channel.send(embed=embed)
        except Exception:
            pass


async def auto_end_giveaway(gid, duration_mins):
    """Non-blocking auto-end task."""
    await asyncio.sleep(duration_mins * 60)

    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT status FROM giveaway WHERE id=?", (gid,))
    g = cur.fetchone()
    conn.close()

    if g and g["status"] == "active":
        await end_giveaway(gid, _bot_ref)


async def setup(bot):
    await bot.add_cog(Giveaway(bot))
