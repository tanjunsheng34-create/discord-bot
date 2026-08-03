"""
GMPT Bot — MMORPG Fishing / 钓鱼系统
/gmpt-fish — 钓鱼

4个钓鱼区域（按等级解锁），消耗体力，鱼可卖金币或收藏。
"""
import datetime
import logging
import random
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx

logger = logging.getLogger(__name__)


def _tz_now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


# ══════════════════════════════════════════════════════════════
# Fishing Areas
# ══════════════════════════════════════════════════════════════
FISHING_AREAS = {
    "novice": {
        "name": "Novice Pond / 新手池塘",
        "emoji": "🌿",
        "unlock_level": 1,
        "fish": [
            ("鲫鱼 / Crucian Carp", "common", 30, 50),
            ("鲤鱼 / Carp", "common", 40, 60),
            ("草鱼 / Grass Carp", "common", 50, 80),
        ],
    },
    "river": {
        "name": "River / 河流",
        "emoji": "🏞️",
        "unlock_level": 10,
        "fish": [
            ("鲈鱼 / Bass", "uncommon", 80, 110),
            ("鲶鱼 / Catfish", "uncommon", 90, 130),
            ("鳗鱼 / Eel", "rare", 120, 150),
        ],
    },
    "ocean": {
        "name": "Ocean / 海洋",
        "emoji": "🌊",
        "unlock_level": 25,
        "fish": [
            ("金枪鱼 / Tuna", "rare", 150, 200),
            ("三文鱼 / Salmon", "rare", 180, 250),
            ("石斑鱼 / Grouper", "epic", 250, 300),
        ],
    },
    "abyss": {
        "name": "Abyss / 深渊",
        "emoji": "🕳️",
        "unlock_level": 40,
        "fish": [
            ("龙鱼 / Dragon Fish", "epic", 300, 500),
            ("幽灵鱼 / Ghost Fish", "epic", 350, 600),
            ("远古鱼 / Ancient Fish", "legendary", 600, 800),
        ],
    },
}

AREA_KEYS = ["novice", "river", "ocean", "abyss"]

STAMINA_MAX = 100
STAMINA_REGEN_INTERVAL = 300  # 5 minutes per 5 stamina
STAMINA_PER_REGEN = 5
STAMINA_COST_PER_FISH = 10


def _add_coins(uid: str, amount: int, reason: str):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (discord_id, username) VALUES (?, '') ON CONFLICT(discord_id) DO NOTHING",
            (uid,),
        )
        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, uid))
        cur.execute(
            "INSERT INTO transactions (discord_id, amount, reason) VALUES (?, ?, ?)",
            (uid, amount, reason),
        )
        conn.commit()


def _add_xp(uid: str, xp: int):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT xp, level FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
        if not row:
            return
        new_xp = (row["xp"] or 0) + xp
        level = row["level"] or 1
        while new_xp >= level * 1000:
            new_xp -= level * 1000
            level += 1
        cur.execute("UPDATE users SET xp = ?, level = ? WHERE discord_id = ?", (new_xp, level, uid))
        conn.commit()


def _get_user_level(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT level FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return row["level"] if row else 1


# ══════════════════════════════════════════════════════════════
# DB Init
# ══════════════════════════════════════════════════════════════
def _init_fishing_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mmorpg_fishing (
                user_id TEXT PRIMARY KEY,
                stamina INTEGER NOT NULL DEFAULT 100,
                last_regen_ts TEXT,
                current_area TEXT NOT NULL DEFAULT 'novice'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mmorpg_fish_collection (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                fish_name TEXT NOT NULL,
                rarity TEXT NOT NULL,
                caught_at TEXT NOT NULL
            )
        """)
        conn.commit()

_init_fishing_tables()


def _get_fishing_data(uid: str) -> dict:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT stamina, last_regen_ts, current_area FROM mmorpg_fishing WHERE user_id = ?", (uid,))
        row = cur.fetchone()
    if not row:
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO mmorpg_fishing (user_id, stamina, current_area) VALUES (?, ?, 'novice')",
                (uid, STAMINA_MAX),
            )
            conn.commit()
        return {"stamina": STAMINA_MAX, "last_regen_ts": None, "current_area": "novice"}
    return {"stamina": row["stamina"], "last_regen_ts": row["last_regen_ts"], "current_area": row["current_area"]}


def _regen_stamina(uid: str, data: dict) -> int:
    """Regenerate stamina based on elapsed time. Returns current stamina after regen."""
    stamina = data["stamina"]
    if stamina >= STAMINA_MAX:
        return stamina

    last_ts = data["last_regen_ts"]
    now = _tz_now()
    if not last_ts:
        last_ts = now.isoformat()
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE mmorpg_fishing SET last_regen_ts = ? WHERE user_id = ?", (last_ts, uid))
            conn.commit()
        return stamina

    try:
        last_dt = datetime.datetime.fromisoformat(last_ts)
    except (ValueError, TypeError):
        last_dt = now - datetime.timedelta(minutes=10)

    elapsed = (now - last_dt).total_seconds()
    regen_count = int(elapsed / STAMINA_REGEN_INTERVAL) * STAMINA_PER_REGEN

    if regen_count > 0:
        new_stamina = min(stamina + regen_count, STAMINA_MAX)
        new_last = last_dt + datetime.timedelta(seconds=int(elapsed / STAMINA_REGEN_INTERVAL) * STAMINA_REGEN_INTERVAL)
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE mmorpg_fishing SET stamina = ?, last_regen_ts = ? WHERE user_id = ?",
                (new_stamina, new_last.isoformat(), uid),
            )
            conn.commit()
        return new_stamina
    return stamina


def _change_area(uid: str, area_key: str):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE mmorpg_fishing SET current_area = ? WHERE user_id = ?", (area_key, uid))
        conn.commit()


def _catch_fish(uid: str, area_key: str) -> dict:
    """Try to catch a fish. Returns fish info dict."""
    area = FISHING_AREAS[area_key]
    fish_list = area["fish"]

    # Special: abyss has 10% chance for Ancient Fish
    if area_key == "abyss" and random.random() < 0.10:
        fish = fish_list[-1]  # Ancient Fish
    else:
        fish = random.choice(fish_list)

    name, rarity, min_price, max_price = fish
    price = random.randint(min_price, max_price)
    now = _tz_now().isoformat()

    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO mmorpg_fish_collection (user_id, fish_name, rarity, caught_at) VALUES (?, ?, ?, ?)",
            (uid, name, rarity, now),
        )
        conn.commit()

    return {"name": name, "rarity": rarity, "price": price, "caught_at": now}


def _get_collection(uid: str) -> list:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT fish_name, rarity, caught_at FROM mmorpg_fish_collection WHERE user_id = ? ORDER BY caught_at DESC LIMIT 50", (uid,))
        return [dict(r) for r in cur.fetchall()]


def _get_collection_stats(uid: str) -> dict:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as total FROM mmorpg_fish_collection WHERE user_id = ?", (uid,))
        total = cur.fetchone()["total"]
        cur.execute("SELECT COUNT(DISTINCT fish_name) as unique_fish FROM mmorpg_fish_collection WHERE user_id = ?", (uid,))
        unique = cur.fetchone()["unique_fish"]
    return {"total": total, "unique": unique}


# ══════════════════════════════════════════════════════════════
# Views
# ══════════════════════════════════════════════════════════════

def _stamina_bar(current: int, maximum: int, length: int = 16) -> str:
    ratio = max(0, min(1, current / maximum))
    filled = int(ratio * length)
    empty = length - filled
    bar = "█" * filled + "░" * empty
    return f"`{bar}` {current}/{maximum}"


class FishingView(discord.ui.View):
    """钓鱼主面板 / Fishing main panel."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view
        self._fishing_active = False
        self._fishing_task = None

    def build_embed(self) -> discord.Embed:
        data = _get_fishing_data(self.uid)
        stamina = _regen_stamina(self.uid, data)
        area_key = data["current_area"]
        area = FISHING_AREAS[area_key]
        level = _get_user_level(self.uid)
        stats = _get_collection_stats(self.uid)

        embed = discord.Embed(
            title=f"{area['emoji']} Fishing / 钓鱼 — {area['name']}",
            description=f"**Stamina / 体力**: {_stamina_bar(stamina, STAMINA_MAX)}\n"
                        f"**Collection / 鱼缸**: {stats['total']} fish / {stats['unique']} unique species",
            color=0x3498DB,
        )

        fish_desc = []
        for name, rarity, lo, hi in area["fish"]:
            r_emoji = {"common": "⬜", "uncommon": "🟢", "rare": "🔵", "epic": "🟣", "legendary": "🟠"}
            fish_desc.append(f"{r_emoji.get(rarity, '⬜')} **{name}** — 🪙 {lo}~{hi}G")
        embed.add_field(name="Fish Available / 可钓鱼类", value="\n".join(fish_desc), inline=False)

        # Area list
        area_lines = []
        for key in AREA_KEYS:
            a = FISHING_AREAS[key]
            locked = "🔒" if level < a["unlock_level"] else ""
            active = "◀️" if key == area_key else ""
            area_lines.append(
                f"{active}{a['emoji']} {a['name']} {locked} (Lv.{a['unlock_level']})"
            )
        embed.add_field(name="Areas / 区域", value="\n".join(area_lines), inline=False)

        stamina_regen_sec = (STAMINA_MAX - stamina) / STAMINA_PER_REGEN * STAMINA_REGEN_INTERVAL
        m, s = divmod(int(stamina_regen_sec), 60)
        embed.set_footer(text=f"Costs {STAMINA_COST_PER_FISH} stamina per cast | Full stamina in {m}m{s}s | 每5分钟恢复5体力")
        return embed

    @discord.ui.button(label="Cast 抛竿", emoji="🎣", style=discord.ButtonStyle.success, row=0)
    async def cast_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return

        data = _get_fishing_data(uid)
        stamina = _regen_stamina(uid, data)
        area_key = data["current_area"]
        area = FISHING_AREAS[area_key]
        level = _get_user_level(uid)

        if level < area["unlock_level"]:
            await interaction.response.send_message(
                f"You need Level {area['unlock_level']} to fish here!\n需要 {area['unlock_level']} 级才能在此钓鱼！",
                ephemeral=True,
            )
            return

        if stamina < STAMINA_COST_PER_FISH:
            await interaction.response.send_message(
                f"Not enough stamina! ({stamina}/{STAMINA_MAX})\n体力不足！({stamina}/{STAMINA_MAX})",
                ephemeral=True,
            )
            return

        # Deduct stamina
        new_stamina = stamina - STAMINA_COST_PER_FISH
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE mmorpg_fishing SET stamina = ? WHERE user_id = ?", (new_stamina, uid))
            conn.commit()

        # Wait for "bite" (3-8 seconds)
        wait_time = random.uniform(3, 8)

        casting_embed = discord.Embed(
            title=f"🎣 Casting... / 抛竿中...",
            description=f"The float is bobbing... / 浮标在晃动...\n\n"
                        f"Wait for the bite! / 等待鱼儿上钩！\n"
                        f"({wait_time:.1f}s)",
            color=0x3498DB,
        )
        try:
            await interaction.response.edit_message(embed=casting_embed, view=FishingWaitView(self.uid, self.main_view, self, wait_time))
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=casting_embed, view=FishingWaitView(self.uid, self.main_view, self, wait_time))

    @discord.ui.button(label="Aquarium 鱼缸", emoji="🎒", style=discord.ButtonStyle.primary, row=0)
    async def aquarium_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        stats = _get_collection_stats(uid)
        collection = _get_collection(uid)

        lines = []
        for fish in collection[:20]:
            ts = fish["caught_at"][:10] if fish["caught_at"] else "?"
            r_emoji = {"common": "⬜", "uncommon": "🟢", "rare": "🔵", "epic": "🟣", "legendary": "🟠"}
            lines.append(f"{r_emoji.get(fish['rarity'], '⬜')} **{fish['fish_name']}** — {ts}")

        embed = discord.Embed(
            title="🎒 Aquarium / 鱼缸",
            description=f"**Total: {stats['total']} fish / {stats['unique']} unique species**\n\n"
                        + ("\n".join(lines) if lines else "No fish yet! Go fishing!\n还没有鱼！快去钓鱼吧！"),
            color=0x1ABC9C,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Change Area 切换区域", emoji="🌍", style=discord.ButtonStyle.secondary, row=0)
    async def area_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return

        data = _get_fishing_data(uid)
        current = data["current_area"]
        current_idx = AREA_KEYS.index(current)
        next_idx = (current_idx + 1) % len(AREA_KEYS)
        next_key = AREA_KEYS[next_idx]
        next_area = FISHING_AREAS[next_key]
        level = _get_user_level(uid)

        if level < next_area["unlock_level"]:
            # Find first unlocked area
            for key in AREA_KEYS:
                if level >= FISHING_AREAS[key]["unlock_level"] and key != current:
                    next_key = key
                    break
            else:
                await interaction.response.send_message(
                    f"No other area unlocked! / 没有其他已解锁区域！",
                    ephemeral=True,
                )
                return

        _change_area(uid, next_key)
        area = FISHING_AREAS[next_key]
        embed = discord.Embed(
            title=f"🌍 Area Changed / 区域切换",
            description=f"Now fishing at: **{area['emoji']} {area['name']}**",
            color=0x2ECC71,
        )
        # Refresh main embed
        main_embed = self.build_embed()
        try:
            await interaction.response.edit_message(embed=main_embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=main_embed, view=self)

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.danger, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(self.uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
        else:
            embed = discord.Embed(
                title="Fishing / 钓鱼",
                description="Use `/gmpt-mmorpg` to return.\n使用 `/gmpt-mmorpg` 返回。",
                color=0x95A5A6,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass



class FishingWaitView(discord.ui.View):
    """钓鱼等待面板 — 显示倒计时，到期后出现拉杆按钮 / Fishing wait panel."""

    def __init__(self, uid: str, main_view, fishing_view: FishingView, wait_time: float):
        super().__init__(timeout=wait_time + 15)
        self.uid = uid
        self.main_view = main_view
        self.fishing_view = fishing_view
        self.wait_time = wait_time
        self._bite_ready = False
        self._task_started = False
        self._bg_tasks: list = []

    def build_wait_embed(self) -> discord.Embed:
        if self._bite_ready:
            return discord.Embed(
                title="🎣 BITE! / 上钩了！",
                description="Quick! Pull the rod! / 快！拉杆！\n\n⬆️ Press **Pull 拉杆** NOW!",
                color=0xE74C3C,
            )
        return discord.Embed(
            title="🎣 Waiting for bite... / 等待上钩...",
            description="The float is still... / 浮标静止中...\n\nPull button will appear when the fish bites!",
            color=0x3498DB,
        )

    async def _schedule_bite(self, interaction: discord.Interaction):
        await asyncio.sleep(random.uniform(2, 6))
        self._bite_ready = True
        self.waiting_indicator.label = "🎣 Pull!"
        self.waiting_indicator.style = discord.ButtonStyle.danger
        embed = self.build_wait_embed()
        try:
            await interaction.edit_original_response(embed=embed, view=self)
        except Exception:
            pass

    @discord.ui.button(label="... waiting ... ", style=discord.ButtonStyle.secondary, disabled=False, row=0)
    async def waiting_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._bite_ready:
            await self._pull_callback(interaction)

    async def _pull_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your fish! / 不是你的鱼！", ephemeral=True)
            return

        data = _get_fishing_data(uid)
        area_key = data["current_area"]

        # Catch fish
        fish = _catch_fish(uid, area_key)
        _add_xp(uid, 20)

        # Sell fish for coins
        _add_coins(uid, fish["price"], f"Sold {fish['name']} — Fishing")

        r_emoji = {"common": "⬜", "uncommon": "🟢", "rare": "🔵", "epic": "🟣", "legendary": "🟠"}

        embed = discord.Embed(
            title="🎣 Fish Caught! / 钓到了！",
            description=f"{r_emoji.get(fish['rarity'], '⬜')} **{fish['name']}**\n\n"
                        f"Rarity / 稀有度: {fish['rarity'].title()}\n"
                        f"Price / 售价: 🪙 **{fish['price']:,}** G\n"
                        f"XP +20",
            color=0x2ECC71 if fish["rarity"] != "legendary" else 0xF1C40F,
        )
        embed.set_footer(text="Fish added to your aquarium! / 鱼已加入鱼缸！")

        try:
            await interaction.response.edit_message(embed=embed, view=self.fishing_view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self.fishing_view)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return False
        if not self._bite_ready and not self._task_started:
            self._task_started = True
            self._bg_tasks.append(asyncio.create_task(self._schedule_bite(interaction)))
            await interaction.response.defer()
            return False
        return True


# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass


class FishingCog(commands.Cog):
    """钓鱼系统 / Fishing system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="gmpt-fish", description="钓鱼 / Go fishing — cast your rod and catch rare fish!")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def fish_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        view = FishingView(uid)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(FishingCog(bot))
    logger.info("Fishing cog loaded")
