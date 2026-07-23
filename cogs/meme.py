"""
GMPT Bot — Meme Generator
Generate image memes with top/bottom text using Pillow.
Fixed: larger fonts, clear outline, proper contrast.
"""
import asyncio
import io
import os
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
import logging
from utils.logger import log_error

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("Pillow not installed — meme features disabled")

# ── Meme template definitions ──
TEMPLATE_DEFS = {
    "drake": {"label": "Drake Hotline Bling", "bg_color": (52, 73, 94)},
    "distracted_boyfriend": {"label": "Distracted Boyfriend", "bg_color": (231, 76, 60)},
    "two_buttons": {"label": "Two Buttons", "bg_color": (46, 204, 113)},
    "change_my_mind": {"label": "Change My Mind", "bg_color": (241, 196, 15)},
    "roll_safe": {"label": "Roll Safe Think", "bg_color": (155, 89, 182)},
    "monkey_puppet": {"label": "Monkey Puppet", "bg_color": (230, 126, 34)},
    "woman_yelling": {"label": "Woman Yelling at Cat", "bg_color": (52, 152, 219)},
    "galaxy_brain": {"label": "Galaxy Brain", "bg_color": (26, 188, 156)},
}

TEMPLATE_LIST = list(TEMPLATE_DEFS.keys())

# ── Font helpers ──
FONT_PATHS = [
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/timesbd.ttf",
    "C:/Windows/Fonts/trebucbd.ttf",
    "C:/Windows/Fonts/seguibl.ttf",
    "C:/Windows/Fonts/verdanab.ttf",
    "C:/Windows/Fonts/comicbd.ttf",
]

_cached_fonts: dict[int, ImageFont.FreeTypeFont] = {}


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Find a large, bold, highly legible font, with per-size caching."""
    if size in _cached_fonts:
        return _cached_fonts[size]
    for path in FONT_PATHS:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                _cached_fonts[size] = font
                return font
            except Exception:
                continue
    font = ImageFont.load_default()
    _cached_fonts[size] = font
    return font


def _wrap_text(draw, text: str, font, max_width: int) -> list[str]:
    """Wrap text to fit within max_width."""
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)
    if not lines and text:
        lines = [text]
    return lines


def _draw_outlined_text(draw, text: str, pos: tuple, font, text_color=(255, 255, 255), outline_color=(0, 0, 0), outline_width: int = 4):
    """Draw white text with thick black outline for maximum readability."""
    x, y = pos
    # Draw outline in all directions
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    # Main text on top
    draw.text((x, y), text, font=font, fill=text_color)


def generate_meme(template: str, top_text: str, bottom_text: str, output_path: str):
    """Generate a clear, readable meme image."""
    tpl = TEMPLATE_DEFS[template]
    width, height = 600, 500
    bg_color = tpl["bg_color"]

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # ── Draw template label at center ──
    label_font = _get_font(36)
    _draw_outlined_text(draw, tpl["label"], (30, 30), label_font)

    tag_font = _get_font(20)
    _draw_outlined_text(draw, "<Meme Template>", (30, 78), tag_font)

    # ── Draw top text ──
    if top_text:
        top_text = top_text.upper()
        max_w = width - 60
        font_size = 48
        top_font = _get_font(font_size)
        lines = _wrap_text(draw, top_text, top_font, max_w)

        # Shrink font if too many lines
        while len(lines) > 3 and font_size > 22:
            font_size -= 4
            top_font = _get_font(font_size)
            lines = _wrap_text(draw, top_text, top_font, max_w)

        y_pos = 120
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=top_font)
            line_w = bbox[2] - bbox[0]
            x = (width - line_w) // 2
            _draw_outlined_text(draw, line, (x, y_pos), top_font)
            y_pos += top_font.size + 8

    # ── Draw bottom text ──
    if bottom_text:
        bottom_text = bottom_text.upper()
        max_w = width - 60
        font_size = 48
        bot_font = _get_font(font_size)
        lines = _wrap_text(draw, bottom_text, bot_font, max_w)

        while len(lines) > 3 and font_size > 22:
            font_size -= 4
            bot_font = _get_font(font_size)
            lines = _wrap_text(draw, bottom_text, bot_font, max_w)

        y_start = height - (len(lines) * (bot_font.size + 8)) - 20
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=bot_font)
            line_w = bbox[2] - bbox[0]
            x = (width - line_w) // 2
            _draw_outlined_text(draw, line, (x, y_start), bot_font)
            y_start += bot_font.size + 8

    img.save(output_path, "PNG")


class Meme(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="gmpt-meme", description="Generate a meme image / 生成表情包")
    @app_commands.describe(
        template="Meme template / 模板名称",
        top_text="Top text / 顶部文字",
        bottom_text="Bottom text / 底部文字",
    )
    @app_commands.choices(template=[
        app_commands.Choice(name=f"{k} — {v['label']}", value=k)
        for k, v in TEMPLATE_DEFS.items()
    ])
    async def meme_cmd(
        self,
        interaction: discord.Interaction,
        template: str,
        top_text: str = "",
        bottom_text: str = "",
    ):
        if not PIL_AVAILABLE:
            return await interaction.response.send_message(
                "Pillow 未安装，无法生成 Meme / Pillow not installed.", ephemeral=True
            )

        if template not in TEMPLATE_DEFS:
            return await interaction.response.send_message(
                f"未知模板 / Unknown template. 可用: {', '.join(TEMPLATE_LIST)}",
                ephemeral=True,
            )

        if not top_text and not bottom_text:
            return await interaction.response.send_message(
                "请至少提供 top_text 或 bottom_text / Please provide at least one text.",
                ephemeral=True,
            )

        await interaction.response.defer()

        import tempfile
        tmp_dir = tempfile.gettempdir()
        output_path = os.path.join(tmp_dir, f"meme_{interaction.user.id}_{os.urandom(4).hex()}.png")

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, generate_meme, template, top_text, bottom_text, output_path
            )

            file = discord.File(output_path, filename="meme.png")
            embed = discord.Embed(
                title=f"📸 Meme — {TEMPLATE_DEFS[template]['label']}",
                color=discord.Color.from_rgb(*TEMPLATE_DEFS[template]["bg_color"]),
            )
            embed.set_image(url="attachment://meme.png")
            embed.set_footer(text=f"模板: {template} | by {interaction.user.display_name}")

            await interaction.followup.send(embed=embed, file=file)

        except Exception as e:
            log_error("meme", "meme_cmd", e)
            # Fallback: text-only embed with large styled text
            tpl = TEMPLATE_DEFS[template]
            embed = discord.Embed(
                title=f"📸 Meme — {tpl['label']}",
                description=(
                    f"*(图片生成失败，以下是文字版 / Image failed, text fallback)*\n\n"
                    f"**⬆️ {top_text.upper() if top_text else '...'}**\n"
                    f"**⬇️ {bottom_text.upper() if bottom_text else '...'}**"
                ),
                color=discord.Color.from_rgb(*tpl["bg_color"]),
            )
            embed.set_footer(text=f"模板: {template} | by {interaction.user.display_name}")
            await interaction.followup.send(embed=embed, ephemeral=False)
        finally:
            try:
                if os.path.exists(output_path):
                    os.remove(output_path)
            except Exception:
                pass

    @app_commands.command(name="gmpt-meme-templates", description="List available meme templates / 列出可用模板")
    async def meme_templates_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎨 Meme 模板列表 / Meme Templates",
            description="使用 `/gmpt-meme <template> <top_text> <bottom_text>` 生成表情包",
            color=discord.Color.purple(),
        )

        for i, (key, tpl) in enumerate(TEMPLATE_DEFS.items(), 1):
            embed.add_field(
                name=f"{i}. {key}",
                value=tpl["label"],
                inline=True,
            )

        embed.set_footer(text=f"共 {len(TEMPLATE_DEFS)} 个模板")
        await interaction.response.send_message(embed=embed)

    @meme_cmd.error
    @meme_templates_cmd.error
    async def meme_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        log_error("meme", interaction.command.name if interaction.command else "unknown", error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("发生错误 / An error occurred.", ephemeral=True)
            else:
                await interaction.followup.send("发生错误 / An error occurred.", ephemeral=True)
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(Meme(bot))
