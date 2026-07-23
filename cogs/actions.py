"""
GMPT Bot — 虚拟互动动作

/gmpt-hug, /gmpt-slap, /gmpt-pat, /gmpt-kiss, /gmpt-kill
每次使用送 5💰 给目标用户，附带 Pillow 生成的 GIF 风格静态图。
"""
import os
import discord
from discord import app_commands
from discord.ext import commands

from utils.cog_base import CogBase
from database import get_db

import logging

logger = logging.getLogger(__name__)

# 每个动作对应的配置
ACTION_CONFIG = {
    "hug":  {"emoji": "🤗", "verb_cn": "拥抱了", "color": (255, 182, 193)},
    "slap": {"emoji": "👋", "verb_cn": "拍打了", "color": (255, 99, 71)},
    "pat":  {"emoji": "🫳", "verb_cn": "摸了摸", "color": (255, 215, 0)},
    "kiss": {"emoji": "💋", "verb_cn": "亲吻了", "color": (255, 105, 180)},
    "kill": {"emoji": "💀", "verb_cn": "击杀了", "color": (139, 0, 0)},
}


def _generate_action_image(emoji: str, verb_cn: str, user1: str, user2: str) -> str:
    """用 Pillow 生成一张静态动作图片（400x300），返回文件路径。"""
    from PIL import Image, ImageDraw, ImageFont

    width, height = 400, 300
    r, g, b = 40, 40, 55
    img = Image.new("RGB", (width, height), (r, g, b))

    # 画渐变高亮带
    draw = ImageDraw.Draw(img)
    for y in range(height):
        ratio = y / height
        cr = int(40 + 30 * ratio)
        cg = int(40 + 25 * ratio)
        cb = int(55 + 30 * ratio)
        draw.line([(0, y), (width, y)], fill=(cr, cg, cb))

    # 加载字体
    font_paths = [
        "C:\\Windows\\Fonts\\seguiemj.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\msgothic.ttf",
    ]
    emoji_font = None
    text_font = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                f = ImageFont.truetype(fp, 80)
                emoji_font = f
                break
            except Exception:
                pass
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                f = ImageFont.truetype(fp, 28)
                text_font = f
                break
            except Exception:
                pass
    if emoji_font is None:
        emoji_font = ImageFont.load_default()
    if text_font is None:
        text_font = ImageFont.load_default()

    # 画 emoji
    bbox = draw.textbbox((0, 0), emoji, font=emoji_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    ex = (width - tw) // 2
    ey = (height - th) // 2 - 20
    # 描边
    for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, -2), (-2, 2), (2, 2)]:
        draw.text((ex + dx, ey + dy), emoji, font=emoji_font, fill=(0, 0, 0))
    draw.text((ex, ey), emoji, font=emoji_font, fill=(255, 255, 255))

    # 画动作文字
    action_text = f"{user1} {verb_cn} {user2}"
    bbox2 = draw.textbbox((0, 0), action_text, font=text_font)
    aw = bbox2[2] - bbox2[0]
    ax = (width - aw) // 2
    ay = ey + th + 15
    # 描边
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        draw.text((ax + dx, ay + dy), action_text, font=text_font, fill=(0, 0, 0))
    draw.text((ax, ay), action_text, font=text_font, fill=(255, 255, 255))

    # 保存到 temp
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".png", prefix="gmpt_action_")
    os.close(fd)
    img.save(path, "PNG")
    return path


class ActionsCog(CogBase):
    def __init__(self, bot):
        self.bot = bot

    async def _do_action(self, interaction: discord.Interaction, target: discord.Member, action_name: str):
        """通用动作处理。"""
        if target.id == interaction.user.id and action_name != "hug":
            return await interaction.response.send_message(
                "不能对自己这么做哦 / You can't do that to yourself!",
                ephemeral=True,
            )

        cfg = ACTION_CONFIG[action_name]
        user1_name = interaction.user.display_name
        user2_name = target.display_name
        title = f"{user1_name} {cfg['verb_cn']} {user2_name}"

        # 加钱给目标
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (discord_id, username, score) VALUES (?, ?, 500) "
            "ON CONFLICT(discord_id) DO UPDATE SET username=excluded.username",
            (str(target.id), str(target)),
        )
        cur.execute(
            "UPDATE users SET score = score + 5 WHERE discord_id = ?",
            (str(target.id),),
        )
        conn.commit()
        conn.close()

        # 生成图片
        img_path = _generate_action_image(cfg["emoji"], cfg["verb_cn"], user1_name, user2_name)

        embed = discord.Embed(
            title=title,
            color=discord.Color.from_rgb(*cfg["color"]),
        )
        embed.set_image(url=f"attachment://{os.path.basename(img_path)}")
        embed.set_footer(text=f"+5 💰 送给了 {user2_name}")

        file = discord.File(img_path, filename=os.path.basename(img_path))
        await interaction.response.send_message(embed=embed, file=file)

        # 清理临时图片
        try:
            os.remove(img_path)
        except Exception:
            pass

    # ── 命令定义 ──

    @app_commands.command(name="gmpt-hug", description="拥抱一个用户 / Hug a user")
    @app_commands.describe(target="要拥抱的用户 / User to hug")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def hug_cmd(self, interaction: discord.Interaction, target: discord.Member):
        await self._do_action(interaction, target, "hug")

    @app_commands.command(name="gmpt-slap", description="拍打一个用户 / Slap a user")
    @app_commands.describe(target="要拍打的用户 / User to slap")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def slap_cmd(self, interaction: discord.Interaction, target: discord.Member):
        await self._do_action(interaction, target, "slap")

    @app_commands.command(name="gmpt-pat", description="摸头一个用户 / Pat a user")
    @app_commands.describe(target="要摸头的用户 / User to pat")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def pat_cmd(self, interaction: discord.Interaction, target: discord.Member):
        await self._do_action(interaction, target, "pat")

    @app_commands.command(name="gmpt-kiss", description="亲吻一个用户 / Kiss a user")
    @app_commands.describe(target="要亲吻的用户 / User to kiss")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def kiss_cmd(self, interaction: discord.Interaction, target: discord.Member):
        await self._do_action(interaction, target, "kiss")

    @app_commands.command(name="gmpt-kill", description="击杀一个用户 / Kill a user")
    @app_commands.describe(target="要击杀的用户 / User to kill")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def kill_cmd(self, interaction: discord.Interaction, target: discord.Member):
        await self._do_action(interaction, target, "kill")


async def setup(bot):
    await bot.add_cog(ActionsCog(bot))
