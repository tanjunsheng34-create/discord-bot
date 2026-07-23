"""
GMPT Bot — Meme Generator
Generate animated GIF memes with top/bottom text using Pillow + imageio.
Typewriter effect with 2-3 second loop; auto fallback to static PNG if >8MB.
"""
import asyncio
import io
import os
import logging

import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
from utils.logger import log_error

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("Pillow not installed — meme features disabled")

try:
    import imageio
    IMAGEIO_AVAILABLE = True
except ImportError:
    IMAGEIO_AVAILABLE = False
    logger.warning("imageio not installed — GIF features disabled, fallback to PNG")

# Discord file size limit: 8 MB
DISCORD_MAX_SIZE = 8 * 1024 * 1024

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


def _draw_outlined_text(draw, text: str, pos: tuple, font,
                        text_color=(255, 255, 255), outline_color=(0, 0, 0),
                        outline_width: int = 4):
    """Draw white text with thick black outline for maximum readability."""
    x, y = pos
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    draw.text((x, y), text, font=font, fill=text_color)


def _make_static_frame(template: str, top_text: str, bottom_text: str) -> Image.Image:
    """Draw a single complete frame (used as first/last frame and PNG fallback)."""
    tpl = TEMPLATE_DEFS[template]
    width, height = 600, 500
    bg_color = tpl["bg_color"]

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Template label
    label_font = _get_font(36)
    _draw_outlined_text(draw, tpl["label"], (30, 30), label_font)
    tag_font = _get_font(20)
    _draw_outlined_text(draw, "<Meme Template>", (30, 78), tag_font)

    # Top text
    if top_text:
        text_upper = top_text.upper()
        max_w = width - 60
        font_size = 48
        top_font = _get_font(font_size)
        lines = _wrap_text(draw, text_upper, top_font, max_w)
        while len(lines) > 3 and font_size > 22:
            font_size -= 4
            top_font = _get_font(font_size)
            lines = _wrap_text(draw, text_upper, top_font, max_w)
        y_pos = 120
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=top_font)
            line_w = bbox[2] - bbox[0]
            x = (width - line_w) // 2
            _draw_outlined_text(draw, line, (x, y_pos), top_font)
            y_pos += top_font.size + 8

    # Bottom text
    if bottom_text:
        text_upper = bottom_text.upper()
        max_w = width - 60
        font_size = 48
        bot_font = _get_font(font_size)
        lines = _wrap_text(draw, text_upper, bot_font, max_w)
        while len(lines) > 3 and font_size > 22:
            font_size -= 4
            bot_font = _get_font(font_size)
            lines = _wrap_text(draw, text_upper, bot_font, max_w)
        y_start = height - (len(lines) * (bot_font.size + 8)) - 20
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=bot_font)
            line_w = bbox[2] - bbox[0]
            x = (width - line_w) // 2
            _draw_outlined_text(draw, line, (x, y_start), bot_font)
            y_start += bot_font.size + 8

    return img


def _generate_gif_frames(template: str, top_text: str, bottom_text: str,
                         num_frames: int = 30, duration_msec: int = 80) -> list[Image.Image]:
    """Generate frames for typewriter effect GIF.

    - Frame 0: full static (hold)
    - Frames 1..N: top text reveals char by char, bottom text reveals after
    - Final frame: full static (hold)
    """
    frames = []

    full_text_top = top_text.upper() if top_text else ""
    full_text_bottom = bottom_text.upper() if bottom_text else ""

    total_chars = len(full_text_top) + len(full_text_bottom)
    if total_chars == 0:
        # No text at all — just a static frame loop
        static = _make_static_frame(template, "", "")
        for _ in range(max(num_frames, 5)):
            frames.append(static.copy())
        return frames

    # Animate: top text types first, then bottom text
    # Split frames proportionally
    top_len = len(full_text_top)
    bottom_len = len(full_text_bottom)

    if top_len == 0:
        top_frames = 0
        bottom_frames = num_frames
    elif bottom_len == 0:
        top_frames = num_frames
        bottom_frames = 0
    else:
        top_frames = max(1, int(num_frames * 0.55))
        bottom_frames = num_frames - top_frames

    for i in range(num_frames):
        # Determine how much of top and bottom text to show
        chars_shown = int((i / max(num_frames - 1, 1)) * total_chars)

        if top_frames > 0 and i < top_frames:
            # Top text revealing
            progress = i / max(top_frames - 1, 1)
            revealed_top_chars = int(progress * top_len)
            current_top = full_text_top[:revealed_top_chars]
            current_bottom = ""
        elif top_frames > 0:
            # Bottom text revealing
            progress = (i - top_frames) / max(bottom_frames - 1, 1)
            revealed_bottom_chars = int(progress * bottom_len)
            current_top = full_text_top
            current_bottom = full_text_bottom[:revealed_bottom_chars]
        else:
            # Only bottom text
            progress = i / max(num_frames - 1, 1)
            revealed_bottom_chars = int(progress * bottom_len)
            current_top = ""
            current_bottom = full_text_bottom[:revealed_bottom_chars]

        frame = _make_static_frame(template, current_top, current_bottom)
        frames.append(frame)

    # Add hold frames at start and end
    static_full = _make_static_frame(template, top_text, bottom_text)
    hold_start = 3
    hold_end = 5
    final_frames = []
    for _ in range(hold_start):
        final_frames.append(static_full.copy())
    final_frames.extend(frames)
    for _ in range(hold_end):
        final_frames.append(static_full.copy())

    return final_frames


def generate_meme(template: str, top_text: str, bottom_text: str, output_path: str):
    """Generate a meme — animated GIF if imageio available, else static PNG.

    Output path should end in .gif (animation) — the caller handles PNG fallback.
    """
    tpl = TEMPLATE_DEFS[template]

    if not IMAGEIO_AVAILABLE:
        # Fallback: static PNG
        png_path = output_path.replace(".gif", ".png")
        os.makedirs(os.path.dirname(png_path), exist_ok=True)
        img = _make_static_frame(template, top_text, bottom_text)
        img.save(png_path, "PNG")
        return png_path, False  # (path, is_gif)

    # Generate GIF frames
    frames = _generate_gif_frames(template, top_text, bottom_text,
                                  num_frames=30, duration_msec=80)

    try:
        # Write GIF via imageio
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        imageio.mimsave(
            output_path,
            [frame.convert("P", palette=Image.ADAPTIVE) for frame in frames],
            duration=[80] * len(frames),
            loop=0,
        )

        # Check file size — if >8MB, fallback to PNG
        file_size = os.path.getsize(output_path)
        if file_size > DISCORD_MAX_SIZE:
            logger.warning(f"GIF too large ({file_size}B), falling back to PNG")
            os.remove(output_path)
            png_path = output_path.replace(".gif", ".png")
            os.makedirs(os.path.dirname(png_path), exist_ok=True)
            static = _make_static_frame(template, top_text, bottom_text)
            static.save(png_path, "PNG")
            return png_path, False

        return output_path, True

    except Exception as e:
        logger.error(f"GIF generation failed: {e}, falling back to PNG")
        png_path = output_path.replace(".gif", ".png")
        if os.path.exists(output_path):
            os.remove(output_path)
        os.makedirs(os.path.dirname(png_path), exist_ok=True)
        static = _make_static_frame(template, top_text, bottom_text)
        static.save(png_path, "PNG")
        return png_path, False


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
        suffix = f"_{interaction.user.id}_{os.urandom(4).hex()}"
        gif_path = os.path.join(tmp_dir, f"meme{suffix}.gif")
        png_path = os.path.join(tmp_dir, f"meme{suffix}.png")
        output_path = gif_path  # primary target
        cleanup_paths = [gif_path, png_path]

        try:
            loop = asyncio.get_event_loop()
            result_path, is_gif = await loop.run_in_executor(
                None, generate_meme, template, top_text, bottom_text, output_path
            )

            filename = "meme.gif" if is_gif else "meme.png"
            file = discord.File(result_path, filename=filename)

            tpl = TEMPLATE_DEFS[template]
            embed = discord.Embed(
                title=f"📸 Meme — {tpl['label']}{' [GIF]' if is_gif else ''}",
                color=discord.Color.from_rgb(*tpl["bg_color"]),
            )
            embed.set_image(url=f"attachment://{filename}")
            embed.set_footer(text=f"模板: {template} | by {interaction.user.display_name}")

            await interaction.followup.send(embed=embed, file=file)

        except Exception as e:
            log_error("meme", "meme_cmd", e)
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
            for path in cleanup_paths:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass

    @app_commands.command(name="gmpt-meme-templates", description="List available meme templates / 列出可用模板")
    async def meme_templates_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎨 Meme 模板列表 / Meme Templates",
            description="使用 `/gmpt-meme <template> <top_text> <bottom_text>` 生成表情包\n"
                        "Now with animated GIF! / 现已支持 GIF 动画！",
            color=discord.Color.purple(),
        )

        for i, (key, tpl) in enumerate(TEMPLATE_DEFS.items(), 1):
            embed.add_field(
                name=f"{i}. {key}",
                value=tpl["label"],
                inline=True,
            )

        embed.set_footer(text=f"共 {len(TEMPLATE_DEFS)} 个模板 | GIF mode available")
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
