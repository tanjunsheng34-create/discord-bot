"""
GMPT Bot — 宠物系统 / Pet System
/gmpt-pet adopt / feed / play / status / rename

Bilingual (中文 / English)
"""
import random
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
from cogs.economy import get_balance, add_coins
from datetime import datetime

logger = logging.getLogger(__name__)


def _format_coins(amount: int) -> str:
    return f"🪙 {amount:,}"


PET_TYPES = {
    "狗": {"emoji": "🐕", "price": 500, "en": "Dog"},
    "dog": {"emoji": "🐕", "price": 500, "zh": "狗"},
    "猫": {"emoji": "🐈", "price": 500, "en": "Cat"},
    "cat": {"emoji": "🐈", "price": 500, "zh": "猫"},
    "龙": {"emoji": "🐉", "price": 2000, "en": "Dragon"},
    "dragon": {"emoji": "🐉", "price": 2000, "zh": "龙"},
    "独角兽": {"emoji": "🦄", "price": 5000, "en": "Unicorn"},
    "unicorn": {"emoji": "🦄", "price": 5000, "zh": "独角兽"},
}


def _init_pet_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL,
                pet_name TEXT NOT NULL,
                pet_type TEXT NOT NULL,
                happiness INTEGER DEFAULT 50,
                adopted_at TEXT DEFAULT (datetime('now')),
                last_fed TEXT,
                last_played TEXT
            )
        """)
        conn.commit()


_init_pet_tables()


class Pets(CogBase):
    """宠物系统 / Pet System."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        cmds = [cmd.qualified_name for cmd in self.get_app_commands()]
        logger.info(f"[Pets] cog_load — 已注册 {len(cmds)} 个命令: {', '.join(cmds)}")

    pet_group = app_commands.Group(
        name="gmpt-pet",
        description="🐾 宠物系统 / Pet System"
    )

    @pet_group.command(name="adopt", description="领养宠物 / Adopt a pet")
    @app_commands.describe(pet_type="宠物类型: 狗/猫/龙/独角兽 / Pet type: dog/cat/dragon/unicorn")
    async def pet_adopt(self, interaction: discord.Interaction, pet_type: str):
        uid = str(interaction.user.id)
        pet_type_lower = pet_type.lower()

        info = PET_TYPES.get(pet_type_lower) or PET_TYPES.get(pet_type)
        if not info:
            return await interaction.response.send_message(
                "可选宠物: 狗(dog) 🪙500 / 猫(cat) 🪙500 / 龙(dragon) 🪙2000 / 独角兽(unicorn) 🪙5000",
                ephemeral=True,
            )

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM pets WHERE owner_id=?", (uid,))
            if cur.fetchone():
                return await interaction.response.send_message(
                    "你已经有一只宠物了！/ You already have a pet!", ephemeral=True)

        bal = get_balance(uid)
        if bal < info["price"]:
            return await interaction.response.send_message(
                f"金币不足！需要 🪙 {info['price']:,}，你只有 🪙 {bal:,} / Not enough coins.",
                ephemeral=True,
            )

        add_coins(uid, -info["price"], f"领养宠物: {pet_type_lower} / Adopted pet")

        display_name = info.get("zh", pet_type)
        display_type = info.get("zh", pet_type)
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO pets (owner_id, pet_name, pet_type) VALUES (?, ?, ?)",
                (uid, display_name, display_type),
            )
            conn.commit()

        embed = discord.Embed(
            title=f"{info['emoji']} 领养成功！/ Adopted!",
            description=f"你领养了一只 **{display_name}**！\nYou adopted a **{info.get('en', display_name)}**!",
            color=0x2ECC71,
        )
        embed.add_field(name="💰 花费 / Cost", value=_format_coins(info["price"]), inline=True)
        embed.add_field(name="❤️ 心情 / Happiness", value="50/100", inline=True)
        embed.set_footer(text="使用 /gmpt-pet status 查看 | /gmpt-pet feed 喂食 | /gmpt-pet play 玩耍")

        await interaction.response.send_message(embed=embed)

    @pet_group.command(name="status", description="查看宠物状态 / View pet status")
    async def pet_status(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM pets WHERE owner_id=?", (uid,))
            row = cur.fetchone()

        if not row:
            return await interaction.response.send_message(
                "你还没有宠物！使用 /gmpt-pet adopt 领养一只 / No pet yet! Use /gmpt-pet adopt.",
                ephemeral=True,
            )

        info = PET_TYPES.get(row["pet_type"].lower(), {"emoji": "🐾"})
        adopted_date = row["adopted_at"][:10] if row["adopted_at"] else "Unknown"
        days_old = "N/A"
        try:
            if row["adopted_at"]:
                dt = datetime.strptime(row["adopted_at"][:10], "%Y-%m-%d")
                days_old = str((datetime.now() - dt).days)
        except Exception:
            pass

        embed = discord.Embed(
            title=f"{info['emoji']} {row['pet_name']}",
            description=f"类型 / Type: **{row['pet_type']}**\n"
                        f"年龄 / Age: **{days_old} 天 / days**",
            color=0xE67E22,
        )
        embed.add_field(name="❤️ 心情 / Happiness", value=f"{row['happiness']}/100", inline=True)
        embed.add_field(name="📅 领养日期 / Adopted", value=adopted_date, inline=True)
        embed.set_footer(text="/gmpt-pet feed | /gmpt-pet play | /gmpt-pet rename")

        await interaction.response.send_message(embed=embed)

    @pet_group.command(name="feed", description="喂食宠物 / Feed your pet (once per day)")
    async def pet_feed(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM pets WHERE owner_id=?", (uid,))
            row = cur.fetchone()

            if not row:
                return await interaction.response.send_message(
                    "你还没有宠物！/ No pet yet!", ephemeral=True)

            # Check daily limit
            today = datetime.now().strftime("%Y-%m-%d")
            if row["last_fed"] and row["last_fed"][:10] == today:
                return await interaction.response.send_message(
                    "今天已经喂过了！明天再来吧 / Already fed today! Come back tomorrow.",
                    ephemeral=True,
                )

            boost = random.randint(1, 5)
            new_happiness = min(row["happiness"] + boost, 100)

            cur.execute(
                "UPDATE pets SET happiness=?, last_fed=? WHERE id=?",
                (new_happiness, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row["id"]),
            )
            conn.commit()

        info = PET_TYPES.get(row["pet_type"].lower(), {"emoji": "🐾"})
        embed = discord.Embed(
            title=f"{info['emoji']} 喂食 / Fed!",
            description=f"{row['pet_name']} 吃饱了！心情 +{boost}\n{row['pet_name']} is full! Happiness +{boost}",
            color=0x2ECC71,
        )
        embed.add_field(name="❤️ 心情 / Happiness", value=f"{new_happiness}/100", inline=True)

        await interaction.response.send_message(embed=embed)

    @pet_group.command(name="play", description="和宠物玩耍 / Play with your pet (once per day, costs 50 coins)")
    async def pet_play(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        bal = get_balance(uid)
        if bal < 50:
            return await interaction.response.send_message(
                f"金币不足！需要 🪙 50 / Need 🪙 50.", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM pets WHERE owner_id=?", (uid,))
            row = cur.fetchone()

            if not row:
                return await interaction.response.send_message(
                    "你还没有宠物！/ No pet yet!", ephemeral=True)

            today = datetime.now().strftime("%Y-%m-%d")
            if row["last_played"] and row["last_played"][:10] == today:
                return await interaction.response.send_message(
                    "今天已经玩过了！明天再来吧 / Already played today!",
                    ephemeral=True,
                )

            add_coins(uid, -50, f"宠物玩耍 / Pet play: {row['pet_name']}")

            boost = random.randint(1, 5)
            new_happiness = min(row["happiness"] + boost, 100)

            cur.execute(
                "UPDATE pets SET happiness=?, last_played=? WHERE id=?",
                (new_happiness, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row["id"]),
            )
            conn.commit()

        info = PET_TYPES.get(row["pet_type"].lower(), {"emoji": "🐾"})
        embed = discord.Embed(
            title=f"{info['emoji']} 玩耍 / Play!",
            description=f"和 {row['pet_name']} 玩得很开心！心情 +{boost}\n"
                        f"Played with {row['pet_name']}! Happiness +{boost}\n"
                        f"花费 / Cost: 🪙 50",
            color=0x3498DB,
        )
        embed.add_field(name="❤️ 心情 / Happiness", value=f"{new_happiness}/100", inline=True)

        await interaction.response.send_message(embed=embed)

    @pet_group.command(name="rename", description="给宠物改名 / Rename your pet")
    @app_commands.describe(new_name="新名字 / New name")
    async def pet_rename(self, interaction: discord.Interaction, new_name: str):
        uid = str(interaction.user.id)

        if len(new_name) > 30:
            return await interaction.response.send_message("名字最多 30 字 / Max 30 characters.", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM pets WHERE owner_id=?", (uid,))
            row = cur.fetchone()
            if not row:
                return await interaction.response.send_message("你还没有宠物！/ No pet yet!", ephemeral=True)

            old_name = row["pet_name"]
            cur.execute("UPDATE pets SET pet_name=? WHERE id=?", (new_name, row["id"]))
            conn.commit()

        await interaction.response.send_message(
            f"✅ 改名成功！**{old_name}** → **{new_name}** / Renamed!",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Pets(bot))
