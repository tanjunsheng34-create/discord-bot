"""
GMPT Bot — 虚拟互动动作

/gmpt-hug, /gmpt-slap, /gmpt-pat, /gmpt-kiss, /gmpt-kill
每次使用送 5💰 给目标用户，附带 Pillow 生成的渐变卡片图。
"""
import io
import os
import random
import discord
from discord import app_commands
from discord.ext import commands

from utils.cog_base import CogBase
from utils.logger import log_error
from database import get_db, get_db_ctx

# 每个动作对应的配置
ACTION_CONFIG = {
    "hug":  {"emoji": "🤗", "verb_cn": "拥抱了", "verb_en": "Hug", "color": 0xE91E63},
    "slap": {"emoji": "👋", "verb_cn": "拍打了", "verb_en": "Slap", "color": 0xE74C3C},
    "pat":  {"emoji": "✋", "verb_cn": "摸了摸", "verb_en": "Pat", "color": 0x2ECC71},
    "kiss": {"emoji": "💋", "verb_cn": "亲吻了", "verb_en": "Kiss", "color": 0x9B59B6},
    "kill": {"emoji": "💀", "verb_cn": "击杀了", "verb_en": "Kill", "color": 0x8B0000},
}

# 渐变配色方案
_GRADIENT_PRESETS = [
    ("#667eea", "#764ba2"),  # 紫蓝
    ("#f093fb", "#f5576c"),  # 粉红
    ("#4facfe", "#00f2fe"),  # 蓝青
    ("#43e97b", "#38f9d7"),  # 绿
    ("#fa709a", "#fee140"),  # 橙粉
    ("#a18cd1", "#fbc2eb"),  # 薰衣草
]


def _find_font(size: int):
    """自动搜索系统可用字体，返回 ImageFont 对象。"""
    from PIL import ImageFont

    font_paths = [
        "C:\\Windows\\Fonts\\seguiemj.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\seguisb.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\msyh.ttc",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue

    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _hex_to_rgb(hex_str: str):
    """#rrggbb → (r, g, b)"""
    h = hex_str.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _generate_action_image(action_type: str, user1: str, user2: str) -> discord.File:
    """生成 600x200 渐变动作卡片，直接返回 discord.File。"""
    from PIL import Image, ImageDraw

    W, H = 600, 200

    # 随机渐变背景
    c1_hex, c2_hex = random.choice(_GRADIENT_PRESETS)
    c1 = _hex_to_rgb(c1_hex)
    c2 = _hex_to_rgb(c2_hex)

    img = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(img)

    # 竖向渐变填充
    for y in range(H):
        ratio = y / H
        r = int(c1[0] + (c2[0] - c1[0]) * ratio)
        g = int(c1[1] + (c2[1] - c1[1]) * ratio)
        b = int(c1[2] + (c2[2] - c1[2]) * ratio)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

    cfg = ACTION_CONFIG[action_type]
    emoji_text = cfg["emoji"]
    action_label = f"{cfg['verb_cn']} {cfg['verb_en']}"
    full_text = f"{user1} {action_label} {user2}"

    # 字体
    font_emoji = _find_font(52)
    font_text = _find_font(26)

    def _draw_text_centered(text, y, font, fill=(255, 255, 255, 255)):
        """居中绘制文本，返回底部 y 坐标。"""
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (W - tw) // 2
        # 轻微阴影
        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 60))
        draw.text((x, y), text, font=font, fill=fill)
        return y + th

    # 绘制 emoji（顶部居中）
    _draw_text_centered(emoji_text, 18, font_emoji)

    # 绘制文字（底部居中）
    _draw_text_centered(full_text, 120, font_text)

    # 保存到 BytesIO
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return discord.File(buf, filename=f"{action_type}.png")


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
        with get_db_ctx() as conn:
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

        # 生成图片 (discord.File) — 全局图片模式关闭则直接文字兜底
        cfg = ACTION_CONFIG[action_name]
        if not getattr(self.bot, "IMAGE_MODE", True):
            embed = discord.Embed(
                title=f"{user1_name} {cfg['verb_cn']} {user2_name}！",
                description=f"# {cfg['emoji']}  {cfg['verb_en']}\n{user1_name} {cfg['verb_cn']} {user2_name}",
                color=cfg["color"],
            )
            embed.set_footer(text=f"+5 💰 送给了 {user2_name} | +5 💰 sent to {user2_name} | 文字模式")
            return await interaction.response.send_message(embed=embed)

        try:
            file = _generate_action_image(action_name, user1_name, user2_name)
            embed = discord.Embed(
                title=title,
                color=cfg["color"],
            )
            embed.set_image(url=f"attachment://{action_name}.png")
            embed.set_footer(text=f"+5 💰 送给了 {user2_name} | +5 💰 sent to {user2_name}")
            await interaction.response.send_message(embed=embed, file=file)
        except Exception as e:
            log_error("actions", f"_do_action:{action_name}", e)
            # 文字 fallback：大号 emoji + 动作描述
            embed = discord.Embed(
                title=f"{user1_name} {cfg['verb_cn']} {user2_name}！",
                description=f"# {cfg['emoji']}  {cfg['verb_en']}\n{user1_name} {cfg['verb_cn']} {user2_name}",
                color=cfg["color"],
            )
            embed.set_footer(text=f"+5 💰 送给了 {user2_name} | +5 💰 sent to {user2_name}")
            await interaction.response.send_message(embed=embed)

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
