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
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
from cogs.economy import get_balance, add_coins

logger = logging.getLogger(__name__)


def _format_coins(amount: int) -> str:
    return f"🪙 {amount:,}"


class EconomyJobs(CogBase):
    """基础赚钱命令 / Basic income commands."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        cmds = [cmd.qualified_name for cmd in self.get_app_commands()]
        logger.info(f"[EconomyJobs] cog_load — 已注册 {len(cmds)} 个命令: {', '.join(cmds)}")

    # ══════════════════════════════════════════════════════════
    # /gmpt-work — 打工赚钱
    # ══════════════════════════════════════════════════════════
    @app_commands.command(name="gmpt-work", description="💼 打工赚钱 / Work to earn coins (1h cooldown)")
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
    @app_commands.command(name="gmpt-rob", description="🥷 打劫其他用户 / Rob another user (2h cooldown)")
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
    @app_commands.command(name="gmpt-beg", description="🙏 乞讨 / Beg for coins (5 min cooldown)")
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
    @app_commands.command(name="gmpt-fish", description="🎣 钓鱼 / Go fishing (3 min cooldown)")
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
    @app_commands.command(name="gmpt-hunt", description="🏹 狩猎 / Go hunting (5 min cooldown)")
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


async def setup(bot):
    await bot.add_cog(EconomyJobs(bot))
