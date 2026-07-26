"""
GMPT Bot — 基础赚钱5大件 / Basic Income Jobs
/gmpt-work  打工赚钱 / Work
/gmpt-rob   打劫其他用户 / Rob
/gmpt-beg   乞讨 / Beg
/gmpt-fish  钓鱼 / Fish
/gmpt-hunt  狩猎 / Hunt

Bilingual (中文 / English)
"""
import asyncio
import random
import time
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db, get_db_ctx
from utils.cog_base import CogBase
from cogs.economy import get_balance, add_coins

logger = logging.getLogger(__name__)


def _format_coins(amount: int) -> str:
    return f"🪙 {amount:,}"


# ══════════════════════════════════════════════════════════════
# EconomyJobsView — 打工按钮面板 / Job Button Panel
# ══════════════════════════════════════════════════════════════

class EconomyJobsView(discord.ui.View):
    """打工赚钱按钮面板 — 点击按钮即可打工，无需打指令。"""

    COOLDOWNS = {
        "work": 3600,    # 1 hour
        "rob": 7200,     # 2 hours
        "beg": 300,      # 5 min
        "fish": 180,     # 3 min
        "hunt": 300,     # 5 min
    }

    COOLDOWN_LABELS = {
        "work": "1小时 / 1h",
        "rob": "2小时 / 2h",
        "beg": "5分钟 / 5min",
        "fish": "3分钟 / 3min",
        "hunt": "5分钟 / 5min",
    }

    JOB_LABELS = {
        "work":  "🏭 打工 Work",
        "rob":   "🥷 打劫 Rob",
        "beg":   "🥺 乞讨 Beg",
        "fish":  "🎣 钓鱼 Fish",
        "hunt":  "🏹 狩猎 Hunt",
    }

    JOB_EMOJIS = {
        "work":  "🏭",
        "rob":   "🥷",
        "beg":   "🥺",
        "fish":  "🎣",
        "hunt":  "🏹",
    }

    def __init__(self, guild=None, dashboard_view=None):
        super().__init__(timeout=300)
        self.guild = guild
        self.dashboard_view = dashboard_view  # optional ref for back-to-dashboard
        self._build_buttons()

    def _get_cd_remaining(self, user_id: str, job: str) -> int:
        """Return remaining cooldown seconds (0 = ready)."""
        cd_sec = self.COOLDOWNS.get(job, 0)
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT last_used FROM job_cooldowns WHERE user_id=? AND job_type=?",
                (user_id, job),
            )
            row = cur.fetchone()
        if not row:
            return 0
        elapsed = time.time() - row["last_used"]
        remaining = int(cd_sec - elapsed)
        return max(0, remaining)

    def _update_cd(self, user_id: str, job: str):
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO job_cooldowns (user_id, job_type, last_used) VALUES (?,?,?)",
                (user_id, job, time.time()),
            )
            conn.commit()

    def _format_cd(self, seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m{seconds % 60}s"
        else:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            return f"{h}h{m}m"

    def _build_buttons(self):
        self.clear_items()

        for i, job in enumerate(["work", "rob", "beg", "fish", "hunt"]):
            btn = discord.ui.Button(
                label=self.JOB_LABELS[job],
                style=discord.ButtonStyle.primary,
                row=0,
                custom_id=f"ejob_{job}",
            )
            btn.callback = self._make_job_callback(job)
            self.add_item(btn)

        # Back button
        back_btn = discord.ui.Button(
            label="返回主菜单 | Back to Main",
            style=discord.ButtonStyle.danger,
            row=1,
            custom_id="ejob_back",
        )
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    def _make_job_callback(self, job: str):
        async def cb(interaction: discord.Interaction):
            uid = str(interaction.user.id)
            remaining = self._get_cd_remaining(uid, job)
            if remaining > 0:
                cd_label = self.COOLDOWN_LABELS.get(job, "?")
                return await interaction.response.send_message(
                    f"⏳ **{self.JOB_LABELS[job]}** 冷却中！\n"
                    f"剩余 / Remaining: **{self._format_cd(remaining)}**\n"
                    f"冷却时间 / Cooldown: {cd_label}",
                    ephemeral=True,
                )

            await interaction.response.defer()

            if job == "rob":
                # Rob needs target - show target selection
                await self._handle_rob(interaction, uid)
            else:
                await self._handle_job(interaction, uid, job)

        return cb

    async def _back_callback(self, interaction: discord.Interaction):
        if self.dashboard_view:
            self.dashboard_view.category = 0
            self.dashboard_view.build_page_buttons()
            embed = self.dashboard_view._build_page_embed()
            await interaction.response.edit_message(embed=embed, view=self.dashboard_view)
        else:
            await interaction.response.edit_message(
                content="使用 `/gmpt-dashboard` 返回主菜单 / Use `/gmpt-dashboard` to go back.",
                embed=None,
                view=None,
            )

    # ═══════════════════ Job Handlers ═══════════════════

    async def _handle_job(self, interaction: discord.Interaction, uid: str, job: str):
        uname = interaction.user.display_name

        if job == "work":
            base = random.randint(50, 200)
            bonus = 0
            bonus_msg = ""
            if random.random() < 0.10:
                bonus = random.randint(100, 300)
                base += bonus
                bonus_msg = f"\n🔥 **加班事件 / Overtime Bonus!** +{bonus:,}"
            add_coins(uid, base, "打工收入 / Work income")
            bal = get_balance(uid)
            embed = discord.Embed(
                title="🏭 打工 / Work",
                description=f"辛苦搬砖，赚了 🪙 **{base:,}** 金币！{bonus_msg}\n\nHard work paid off! Earned 🪙 **{base:,}** coins!",
                color=0x3498DB,
            )
            embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            embed.set_footer(text="每小时可打工一次 / Work once per hour")
            self._update_cd(uid, job)
            await interaction.followup.send(embed=embed)

        elif job == "beg":
            roll = random.random()
            if roll < 0.60:
                earned = random.randint(10, 80)
                add_coins(uid, earned, "乞讨收入 / Begging income")
                bal = get_balance(uid)
                embed = discord.Embed(
                    title="🥺 乞讨 / Begging",
                    description=f"好心人给了 {uname} 🪙 **{earned:,}** 金币！\nA kind stranger gave you 🪙 **{earned:,}** coins!",
                    color=0x2ECC71,
                )
                embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            elif roll < 0.90:
                bal = get_balance(uid)
                embed = discord.Embed(
                    title="🥺 乞讨 / Begging",
                    description=f"没人理 {uname}... 被无视了。\nNobody noticed... Ignored.",
                    color=0x95A5A6,
                )
                embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            else:
                earned = random.randint(200, 500)
                add_coins(uid, earned, "好心人打赏 / Generous donation")
                bal = get_balance(uid)
                embed = discord.Embed(
                    title="🥺 乞讨 / Begging",
                    description=f"🎉 超级好心人给了 {uname} 🪙 **{earned:,}** 金币！！\nA generous soul gave you 🪙 **{earned:,}** coins!!",
                    color=0xF1C40F,
                )
                embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            embed.set_footer(text="乞讨冷却 5 分钟 / Beg cooldown: 5 min")
            self._update_cd(uid, job)
            await interaction.followup.send(embed=embed)

        elif job == "fish":
            roll = random.random()
            if roll < 0.05:
                fish_name = "传说鱼 / Legendary Fish"
                fish_emoji = "🐋"
                earned = random.randint(500, 2000)
                color = 0xF1C40F
            elif roll < 0.25:
                fish_name = "金鱼 / Goldfish"
                fish_emoji = "🐠"
                earned = random.randint(100, 200)
                color = 0xE67E22
            elif roll < 0.55:
                fish_name = "鲈鱼 / Bass"
                fish_emoji = "🐟"
                earned = random.randint(30, 60)
                color = 0x3498DB
            elif roll < 0.85:
                fish_name = "鲱鱼 / Herring"
                fish_emoji = "🐡"
                earned = random.randint(5, 20)
                color = 0x95A5A6
            else:
                fish_name = "垃圾 / Trash"
                fish_emoji = "👢"
                earned = 0
                color = 0x7F8C8D

            if earned > 0:
                add_coins(uid, earned, f"钓鱼: {fish_name} / Fishing: {fish_name}")
            bal = get_balance(uid)
            if earned > 0:
                desc = f"{uname} 钓到了 {fish_emoji} **{fish_name}**！卖得 🪙 **{earned:,}** 金币！\nCaught {fish_emoji} **{fish_name}**! Sold for 🪙 **{earned:,}** coins!"
            else:
                desc = f"{uname} 钓到了 {fish_emoji} **垃圾**... 一文不值。\nCaught {fish_emoji} **trash**... Worthless."
            embed = discord.Embed(title=f"🎣 {uname} 钓鱼 / Fishing", description=desc, color=color)
            embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            embed.set_footer(text="钓鱼冷却 3 分钟 / Fish cooldown: 3 min")
            self._update_cd(uid, job)
            await interaction.followup.send(embed=embed)

        elif job == "hunt":
            roll = random.random()
            injured = random.random() < 0.15
            if roll < 0.03:
                prey_name = "传说猎物 / Legendary Prey"
                prey_emoji = "🐉"
                earned = random.randint(1000, 3000)
                color = 0xF1C40F
            elif roll < 0.20:
                prey_name = "野猪 / Wild Boar"
                prey_emoji = "🐗"
                earned = random.randint(200, 400)
                color = 0xE74C3C
            elif roll < 0.50:
                prey_name = "鹿 / Deer"
                prey_emoji = "🦌"
                earned = random.randint(80, 150)
                color = 0xE67E22
            elif roll < 0.80:
                prey_name = "兔子 / Rabbit"
                prey_emoji = "🐇"
                earned = random.randint(20, 50)
                color = 0x2ECC71
            else:
                prey_name = "空手而归 / Empty-handed"
                prey_emoji = "🌿"
                earned = 0
                color = 0x95A5A6

            if earned > 0:
                add_coins(uid, earned, f"狩猎: {prey_name} / Hunting: {prey_name}")
            bal = get_balance(uid)
            if earned > 0:
                desc = f"{uname} 猎到了 {prey_emoji} **{prey_name}**！卖得 🪙 **{earned:,}** 金币！\nHunted {prey_emoji} **{prey_name}**! Sold for 🪙 **{earned:,}** coins!"
            else:
                desc = f"{uname} 在森林里转了一圈，什么都没找到...\nWandered the forest, found nothing..."
            if injured:
                desc += "\n\n🤕 **受伤了！** 狩猎冷却延长 10 分钟。\n**Injured!** Hunt cooldown extended by 10 min."
                color = 0xE74C3C
            embed = discord.Embed(title=f"🏹 {uname} 狩猎 / Hunting", description=desc, color=color)
            embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            embed.set_footer(text="狩猎冷却 5 分钟 / Hunt cooldown: 5 min")
            self._update_cd(uid, job)
            await interaction.followup.send(embed=embed)

    async def _handle_rob(self, interaction: discord.Interaction, uid: str):
        """Rob requires a target — show a select dropdown with eligible targets."""
        if not self.guild:
            return await interaction.followup.send(
                "无法获取服务器信息 / Cannot get guild info.", ephemeral=True
            )

        members = [m for m in self.guild.members if not m.bot and str(m.id) != uid][:25]
        if not members:
            return await interaction.followup.send(
                "没有可打劫的玩家 / No players to rob.", ephemeral=True
            )

        options = []
        for m in members:
            try:
                bal = get_balance(str(m.id))
            except Exception:
                bal = 0
            label = f"{m.display_name[:50]} — 🪙{bal}"
            if bal < 100:
                label += " (余额不足)"
            options.append(discord.SelectOption(
                label=label[:100],
                value=str(m.id),
                description=f"ID: {m.id}",
            ))

        select = discord.ui.Select(
            placeholder="选择打劫目标 / Select a target...",
            options=options[:25],
        )

        async def rob_select_callback(sel_int: discord.Interaction):
            tid = sel_int.data["values"][0]
            target = self.guild.get_member(int(tid))
            if not target:
                return await sel_int.response.send_message("目标不在服务器 / Target not found.", ephemeral=True)

            tname = target.display_name
            uname = interaction.user.display_name
            target_bal = get_balance(tid)

            if target_bal < 100:
                return await sel_int.response.send_message(
                    f"{tname} 余额不足 100 金币，无法打劫 / Balance < 100.", ephemeral=True
                )

            success = random.random() < 0.60
            if success:
                pct = random.uniform(0.10, 0.30)
                stolen = min(int(target_bal * pct), 5000)
                stolen = max(stolen, 1)
                add_coins(tid, -stolen, f"被 {uname} 打劫 / Robbed by {uname}")
                add_coins(uid, stolen, f"打劫 {tname} / Robbed {tname}")
                robber_bal = get_balance(uid)
                embed = discord.Embed(
                    title="🥷 打劫成功！/ Robbery Success!",
                    description=f"{uname} 成功打劫了 {tname}！",
                    color=0xE74C3C,
                )
                embed.add_field(name="💰 抢走 / Stolen", value=_format_coins(stolen), inline=True)
                embed.add_field(name="💰 你的余额 / Your Balance", value=_format_coins(robber_bal), inline=True)
            else:
                penalty_pct = 0.20
                my_bal = get_balance(uid)
                penalty = max(int(my_bal * penalty_pct), 1)
                add_coins(uid, -penalty, "打劫失败罚款 / Failed robbery penalty")
                add_coins(tid, penalty, f"{uname} 打劫失败赔偿 / Compensation from failed robbery")
                robber_bal = get_balance(uid)
                embed = discord.Embed(
                    title="🚔 打劫失败！/ Robbery Failed!",
                    description=f"{uname} 打劫 {tname} 被抓，罚款赔偿！\nCaught! Penalty paid to victim.",
                    color=0xF1C40F,
                )
                embed.add_field(name="💸 罚款 / Penalty", value=_format_coins(penalty), inline=True)
                embed.add_field(name="💰 你的余额 / Your Balance", value=_format_coins(robber_bal), inline=True)

            embed.set_footer(text="打劫冷却 2 小时 / Rob cooldown: 2 hours")
            self._update_cd(uid, "rob")
            await sel_int.response.send_message(embed=embed)

        select.callback = rob_select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.followup.send("🥷 选择打劫目标 / Select a target:", view=view, ephemeral=True)


class EconomyJobs(CogBase):
    """基础赚钱命令 / Basic income commands."""

    def __init__(self, bot):
        self.bot = bot

    gmpt_job_group = app_commands.Group(
        name="gmpt-job",
        description="Economy jobs to earn coins / 打工赚钱"
    )

    async def cog_load(self):
        cmds = [cmd.qualified_name for cmd in self.get_app_commands()]
        logger.info(f"[EconomyJobs] cog_load — 已注册 {len(cmds)} 个命令: {', '.join(cmds)}")

    # ══════════════════════════════════════════════════════════
    # /gmpt-work — 打工赚钱
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="work", description="💼 打工赚钱 / Work to earn coins (1h cooldown)")
    @app_commands.checks.cooldown(1, 3600, key=lambda i: (i.guild_id, i.user.id))
    async def work_cmd(self, interaction: discord.Interaction):
        """打工赚钱，每小时一次."""
        try:
            uid = str(interaction.user.id)
            uname = interaction.user.display_name

            base = random.randint(50, 200)
            bonus = 0
            bonus_msg = ""

            if random.random() < 0.10:
                bonus = random.randint(100, 300)
                base += bonus
                bonus_msg = f"\n🔥 **加班事件 / Overtime Bonus!** 🪙 +{bonus:,}"

            add_coins(uid, base, "打工收入 / Work income")
            bal = get_balance(uid)

            embed = discord.Embed(
                title=f"💼 {uname} 打工 / Work",
                description=f"辛苦搬砖，赚了 🪙 **{base:,}** 金币！{bonus_msg}\n\nHard work paid off! Earned 🪙 **{base:,}** coins!",
                color=0x3498DB,
            )
            embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            embed.set_footer(text="每小时可打工一次 / Work once per hour")

            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"[work_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 打工命令出错，请重试 / Work error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 打工命令出错，请重试 / Work error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-rob — 打劫其他用户
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="rob", description="🥷 打劫其他用户 / Rob another user (2h cooldown)")
    @app_commands.describe(target="打劫目标 / Target user")
    @app_commands.checks.cooldown(1, 7200, key=lambda i: (i.guild_id, i.user.id))
    async def rob_cmd(self, interaction: discord.Interaction, target: discord.Member):
        """打劫目标用户."""
        try:
            uid = str(interaction.user.id)
            tid = str(target.id)
            uname = interaction.user.display_name
            tname = target.display_name

            if target.id == interaction.user.id:
                return await interaction.response.send_message(
                    "不能打劫自己 / Cannot rob yourself!", ephemeral=True)
            if target.bot:
                return await interaction.response.send_message(
                    "不能打劫机器人 / Cannot rob bots!", ephemeral=True)

            target_bal = get_balance(tid)
            if target_bal < 100:
                return await interaction.response.send_message(
                    f"{tname} 余额不足 100 金币，无法打劫 / Balance < 100, cannot rob.",
                    ephemeral=True,
                )

            success = random.random() < 0.60

            if success:
                pct = random.uniform(0.10, 0.30)
                stolen = min(int(target_bal * pct), 5000)
                stolen = max(stolen, 1)

                add_coins(tid, -stolen, f"被 {uname} 打劫 / Robbed by {uname}")
                add_coins(uid, stolen, f"打劫 {tname} / Robbed {tname}")
                robber_bal = get_balance(uid)

                embed = discord.Embed(
                    title="🥷 打劫成功！/ Robbery Success!",
                    description=f"{uname} 成功打劫了 {tname}！\n{{Robbed successfully!}}",
                    color=0xE74C3C,
                )
                embed.add_field(name="💰 抢走 / Stolen", value=_format_coins(stolen), inline=True)
                embed.add_field(name="💰 你的余额 / Your Balance", value=_format_coins(robber_bal), inline=True)
            else:
                penalty_pct = 0.20
                my_bal = get_balance(uid)
                penalty = max(int(my_bal * penalty_pct), 1)

                add_coins(uid, -penalty, f"打劫失败罚款 / Failed robbery penalty")
                add_coins(tid, penalty, f"{uname} 打劫失败赔偿 / Compensation from failed robbery")
                robber_bal = get_balance(uid)

                embed = discord.Embed(
                    title="🚔 打劫失败！/ Robbery Failed!",
                    description=f"{uname} 打劫 {tname} 被抓，罚款赔偿！\nCaught! Penalty paid to victim.",
                    color=0xF1C40F,
                )
                embed.add_field(name="💸 罚款 / Penalty", value=_format_coins(penalty), inline=True)
                embed.add_field(name="💰 你的余额 / Your Balance", value=_format_coins(robber_bal), inline=True)

            embed.set_footer(text="打劫冷却 2 小时 / Rob cooldown: 2 hours")
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"[rob_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 打劫命令出错，请重试 / Rob error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 打劫命令出错，请重试 / Rob error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-beg — 乞讨
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="beg", description="🙏 乞讨 / Beg for coins (5 min cooldown)")
    @app_commands.checks.cooldown(1, 300, key=lambda i: (i.guild_id, i.user.id))
    async def beg_cmd(self, interaction: discord.Interaction):
        """乞讨."""
        try:
            uid = str(interaction.user.id)
            uname = interaction.user.display_name

            roll = random.random()

            if roll < 0.60:
                earned = random.randint(10, 80)
                add_coins(uid, earned, "乞讨收入 / Begging income")
                bal = get_balance(uid)
                embed = discord.Embed(
                    title="🙏 乞讨 / Begging",
                    description=f"好心人给了 {uname} 🪙 **{earned:,}** 金币！\nA kind stranger gave you 🪙 **{earned:,}** coins!",
                    color=0x2ECC71,
                )
                embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            elif roll < 0.90:
                bal = get_balance(uid)
                embed = discord.Embed(
                    title="🙏 乞讨 / Begging",
                    description=f"没人理 {uname}... 被无视了。\nNobody noticed... Ignored.",
                    color=0x95A5A6,
                )
                embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            else:
                earned = random.randint(200, 500)
                add_coins(uid, earned, "好心人打赏 / Generous donation")
                bal = get_balance(uid)
                embed = discord.Embed(
                    title="🙏 乞讨 / Begging",
                    description=f"🎉 超级好心人给了 {uname} 🪙 **{earned:,}** 金币！！\nA generous soul gave you 🪙 **{earned:,}** coins!!",
                    color=0xF1C40F,
                )
                embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)

            embed.set_footer(text="乞讨冷却 5 分钟 / Beg cooldown: 5 min")
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"[beg_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 乞讨命令出错，请重试 / Beg error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 乞讨命令出错，请重试 / Beg error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-fish — 钓鱼
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="fish", description="🎣 钓鱼 / Go fishing (3 min cooldown)")
    @app_commands.checks.cooldown(1, 180, key=lambda i: (i.guild_id, i.user.id))
    async def fish_cmd(self, interaction: discord.Interaction):
        """钓鱼."""
        try:
            uid = str(interaction.user.id)
            uname = interaction.user.display_name

            roll = random.random()

            if roll < 0.05:
                fish_name = "传说鱼 / Legendary Fish"
                fish_emoji = "🐋"
                earned = random.randint(500, 2000)
                color = 0xF1C40F
            elif roll < 0.25:
                fish_name = "金鱼 / Goldfish"
                fish_emoji = "🐠"
                earned = random.randint(100, 200)
                color = 0xE67E22
            elif roll < 0.55:
                fish_name = "鲈鱼 / Bass"
                fish_emoji = "🐟"
                earned = random.randint(30, 60)
                color = 0x3498DB
            elif roll < 0.85:
                fish_name = "鲱鱼 / Herring"
                fish_emoji = "🐡"
                earned = random.randint(5, 20)
                color = 0x95A5A6
            else:
                fish_name = "垃圾 / Trash"
                fish_emoji = "👢"
                earned = 0
                color = 0x7F8C8D

            if earned > 0:
                add_coins(uid, earned, f"钓鱼: {fish_name} / Fishing: {fish_name}")

            bal = get_balance(uid)

            if earned > 0:
                desc = f"{uname} 钓到了 {fish_emoji} **{fish_name}**！卖得 🪙 **{earned:,}** 金币！\nCaught {fish_emoji} **{fish_name}**! Sold for 🪙 **{earned:,}** coins!"
            else:
                desc = f"{uname} 钓到了 {fish_emoji} **垃圾**... 一文不值。\nCaught {fish_emoji} **trash**... Worthless."

            embed = discord.Embed(
                title=f"🎣 {uname} 钓鱼 / Fishing",
                description=desc,
                color=color,
            )
            embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            embed.set_footer(text="钓鱼冷却 3 分钟 / Fish cooldown: 3 min")
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"[fish_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 钓鱼命令出错，请重试 / Fish error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 钓鱼命令出错，请重试 / Fish error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-hunt — 狩猎
    # ══════════════════════════════════════════════════════════
    @gmpt_job_group.command(name="hunt", description="🏹 狩猎 / Go hunting (5 min cooldown)")
    @app_commands.checks.cooldown(1, 300, key=lambda i: (i.guild_id, i.user.id))
    async def hunt_cmd(self, interaction: discord.Interaction):
        """狩猎."""
        try:
            uid = str(interaction.user.id)
            uname = interaction.user.display_name

            roll = random.random()
            injured = random.random() < 0.15

            if roll < 0.03:
                prey_name = "传说猎物 / Legendary Prey"
                prey_emoji = "🐉"
                earned = random.randint(1000, 3000)
                color = 0xF1C40F
            elif roll < 0.20:
                prey_name = "野猪 / Wild Boar"
                prey_emoji = "🐗"
                earned = random.randint(200, 400)
                color = 0xE74C3C
            elif roll < 0.50:
                prey_name = "鹿 / Deer"
                prey_emoji = "🦌"
                earned = random.randint(80, 150)
                color = 0xE67E22
            elif roll < 0.80:
                prey_name = "兔子 / Rabbit"
                prey_emoji = "🐇"
                earned = random.randint(20, 50)
                color = 0x2ECC71
            else:
                prey_name = "空手而归 / Empty-handed"
                prey_emoji = "🌿"
                earned = 0
                color = 0x95A5A6

            if earned > 0:
                add_coins(uid, earned, f"狩猎: {prey_name} / Hunting: {prey_name}")

            bal = get_balance(uid)

            if earned > 0:
                desc = f"{uname} 猎到了 {prey_emoji} **{prey_name}**！卖得 🪙 **{earned:,}** 金币！\nHunted {prey_emoji} **{prey_name}**! Sold for 🪙 **{earned:,}** coins!"
            else:
                desc = f"{uname} 在森林里转了一圈，什么都没找到...\nWandered the forest, found nothing..."

            if injured:
                desc += "\n\n🤕 **受伤了！** 狩猎冷却延长 10 分钟。\n**Injured!** Hunt cooldown extended by 10 min."
                color = 0xE74C3C

            embed = discord.Embed(
                title=f"🏹 {uname} 狩猎 / Hunting",
                description=desc,
                color=color,
            )
            embed.add_field(name="💰 余额 / Balance", value=_format_coins(bal), inline=False)
            embed.set_footer(text="狩猎冷却 5 分钟 / Hunt cooldown: 5 min")
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"[hunt_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 狩猎命令出错，请重试 / Hunt error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 狩猎命令出错，请重试 / Hunt error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-jobs — 打工按钮面板 / Job Button Panel
    # ══════════════════════════════════════════════════════════
    @app_commands.command(name="gmpt-jobs", description="💼 打工赚钱面板 / Economy jobs button panel")
    async def jobs_panel(self, interaction: discord.Interaction):
        """显示打工按钮面板."""
        view = EconomyJobsView(guild=interaction.guild)
        embed = discord.Embed(
            title="💼 打工赚钱 | Economy Jobs",
            description="点击下方按钮即可打工赚钱，无需打指令！\nClick a button below to earn coins — no commands needed!",
            color=0xF39C12,
        )
        embed.add_field(
            name="可用工作 / Available Jobs",
            value=(
                "🏭 **打工** — 1小时 CD / 1h cooldown\n"
                "🥷 **打劫** — 2小时 CD / 2h cooldown\n"
                "🥺 **乞讨** — 5分钟 CD / 5min cooldown\n"
                "🎣 **钓鱼** — 3分钟 CD / 3min cooldown\n"
                "🏹 **狩猎** — 5分钟 CD / 5min cooldown"
            ),
            inline=False,
        )
        embed.set_footer(text="每种工作有独立的冷却时间 | Each job has its own cooldown")
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(EconomyJobs(bot))
