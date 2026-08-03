"""
GMPT Bot — MMORPG 交易行 / Player Market
/gmpt-market browse/list/search/buy — 玩家间装备买卖
（合并自 cogs/market.py 的浏览视图和状态追踪功能）
"""
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
import logging

logger = logging.getLogger(__name__)

MARKET_FEE = 0.05  # 5% fee


class MarketListView(discord.ui.View):
    """Market browse view with pagination (merged from market.py)."""

    def __init__(self, uid: str, page: int = 0, main_view=None):
        super().__init__(timeout=180)
        self.uid = uid
        self.page = page
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        per_page = 5
        offset = self.page * per_page
        with get_db_ctx() as cur:
            cur.execute(
                "SELECT id, seller_id, item_name, price, listed_at FROM market_listings"
                " WHERE status = 'active' ORDER BY price ASC LIMIT ? OFFSET ?",
                (per_page, offset),
            )
            rows = cur.fetchall()
            cur.execute("SELECT COUNT(*) as total FROM market_listings WHERE status = 'active'")
            total = cur.fetchone()["total"]

        embed = discord.Embed(
            title="🏪 Marketplace / 交易市场",
            description="Browse equipment listings from other players!\n浏览其他玩家的装备挂单！",
            color=0xF39C12,
        )

        if not rows:
            embed.description += "\n\n*No active listings / 暂无在售商品*"
        else:
            for row in rows:
                embed.add_field(
                    name=f"#{row['id']} | {row['item_name']}",
                    value=(
                        f"Seller / 卖家: <@{row['seller_id']}>\n"
                        f"Price / 价格: 🪙 **{row['price']:,}**\n"
                        f"Listed / 上架时间: {row['listed_at'][:10]}"
                    ),
                    inline=False,
                )

        total_pages = max(1, (total + per_page - 1) // per_page)
        embed.set_footer(text=f"Page {self.page + 1}/{total_pages} | /gmpt-market buy <id> to purchase")
        return embed

    @discord.ui.button(label="\u25c0 Prev", style=discord.ButtonStyle.secondary, row=0, custom_id="market:prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        try:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next \u25b6", style=discord.ButtonStyle.secondary, row=0, custom_id="market:next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        try:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Back \u8fd4\u56de", emoji="\U0001f519", style=discord.ButtonStyle.danger, row=1, custom_id="market:back")
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(self.uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
        else:
            await interaction.response.edit_message(content="Main panel unavailable.", view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass


class MarketCog(CogBase):
    """交易行 / Player Market"""

    def __init__(self, bot: commands.Bot):
        super().__init__()

    async def cog_load(self):
        self._ensure_tables()
        logger.info("[Market] 交易行已加载 / Market loaded")

    def _ensure_tables(self):
        with get_db_ctx() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS market_listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seller_id TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    item_type TEXT DEFAULT 'equipment',
                    tier TEXT DEFAULT 'T1',
                    enhance_level INTEGER DEFAULT 0,
                    price INTEGER NOT NULL,
                    listed_at TEXT DEFAULT (datetime('now')),
                    status TEXT DEFAULT 'active',
                    buyer_id TEXT
                )
            """)

    market = app_commands.Group(name="gmpt-market", description="交易行 / Player Market")

    @market.command(name="browse", description="\U0001f3ea 浏览交易市场 / Browse marketplace")
    async def browse(self, interaction: discord.Interaction):
        """Paginated browse view of active listings (merged from market.py)."""
        uid = str(interaction.user.id)
        view = MarketListView(uid)
        await interaction.response.send_message(embed=view.build_embed(), view=view)

    @market.command(name="list", description="上架装备 / List equipment for sale")
    @app_commands.describe(item_name="装备名称 / Item name", price="售价(金币) / Price in gold")
    async def list_item(self, interaction: discord.Interaction, item_name: str, price: int):
        if price < 100:
            await interaction.response.send_message("最低售价100金币 / Minimum price 100 gold", ephemeral=True)
            return

        user_id = str(interaction.user.id)

        with get_db_ctx() as cur:
            cur.execute(
                "SELECT id FROM user_equipment WHERE owner_id=? AND item_name=? AND equipped_slot IS NULL",
                (user_id, item_name)
            )
            eq = cur.fetchone()
            if not eq:
                await interaction.response.send_message(
                    f"你背包中没有未装备的 `{item_name}` / Item not found in your inventory",
                    ephemeral=True
                )
                return

            cur.execute("DELETE FROM user_equipment WHERE id=?", (eq[0],))
            cur.execute(
                "INSERT INTO market_listings (seller_id, item_name, price) VALUES (?,?,?)",
                (user_id, item_name, price)
            )

        embed = discord.Embed(
            title="📦 已上架 / Listed",
            description=f"**{item_name}** — 💰 `{price}G`",
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"卖家 / Seller: {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    @market.command(name="search", description="搜索交易行 / Search market listings")
    @app_commands.describe(query="装备名称关键词 / Search keyword", page="页码 / Page number")
    async def search(self, interaction: discord.Interaction, query: str = "", page: int = 1):
        with get_db_ctx() as cur:
            if query:
                cur.execute(
                    "SELECT id, seller_id, item_name, item_type, tier, enhance_level, price, listed_at "
                    "FROM market_listings WHERE status='active' AND item_name LIKE ? ORDER BY price ASC LIMIT 10 OFFSET ?",
                    (f"%{query}%", (page - 1) * 10)
                )
            else:
                cur.execute(
                    "SELECT id, seller_id, item_name, item_type, tier, enhance_level, price, listed_at "
                    "FROM market_listings WHERE status='active' ORDER BY listed_at DESC LIMIT 10 OFFSET ?",
                    ((page - 1) * 10,)
                )
            rows = cur.fetchall()

        if not rows:
            await interaction.response.send_message("没有找到上架物品 / No listings found", ephemeral=True)
            return

        embed = discord.Embed(title="🏪 交易行 / Market", color=discord.Color.blue())
        lines = []
        for row in rows:
            listing_id, seller_id, item_name, item_type, tier, enhance, price, listed_at = row
            enhance_str = f" +{enhance}" if enhance else ""
            lines.append(
                f"**#{listing_id}** `{item_name}{enhance_str}` — 💰 `{price}G`\n"
                f"　　{self.bot.get_user(int(seller_id)) or '—'} | {listed_at[:10]}"
            )

        embed.description = "\n\n".join(lines)
        embed.set_footer(text=f"第{page}页 / Page {page} | /gmpt-market buy <id> 购买")
        await interaction.response.send_message(embed=embed)

    @market.command(name="buy", description="购买交易行物品 / Buy an item from market")
    @app_commands.describe(listing_id="上架编号 / Listing ID")
    async def buy(self, interaction: discord.Interaction, listing_id: int):
        buyer_id = str(interaction.user.id)

        with get_db_ctx() as cur:
            cur.execute("SELECT seller_id, item_name, price FROM market_listings WHERE id=? AND status='active'", (listing_id,))
            listing = cur.fetchone()
            if not listing:
                await interaction.response.send_message("该上架已不存在 / Listing not found", ephemeral=True)
                return

            seller_id, item_name, price = listing

            if seller_id == buyer_id:
                await interaction.response.send_message("不能购买自己的物品 / Cannot buy your own listing", ephemeral=True)
                return

            from cogs.economy import get_balance
            bal = await get_balance(buyer_id)
            if bal < price:
                await interaction.response.send_message(
                    f"金币不足 / Not enough gold — 需要 `{price}G`，你有 `{bal}G`", ephemeral=True
                )
                return

            fee = int(price * MARKET_FEE)
            net = price - fee

            from cogs.economy import add_coins
            await add_coins(buyer_id, -price)
            await add_coins(seller_id, net)

            # Mark as sold with status tracking (merged from market.py)
            cur.execute(
                "UPDATE market_listings SET status='sold', buyer_id=? WHERE id=?",
                (buyer_id, listing_id)
            )
            cur.execute(
                "INSERT INTO user_equipment (owner_id, item_name) VALUES (?,?)",
                (buyer_id, item_name)
            )

        seller_user = self.bot.get_user(int(seller_id))
        embed = discord.Embed(
            title="✅ 购买成功 / Purchased",
            description=f"**{item_name}** — 💰 `{price}G` (手续费 `{fee}G`)",
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"卖家 / Seller: {seller_user or seller_id}")
        await interaction.response.send_message(embed=embed)

        try:
            if seller_user:
                await seller_user.send(
                    f"📬 你的 `{item_name}` 已售出！收入 `{net}G`\n"
                    f"Your item has been sold! Earned `{net}G`"
                )
        except discord.Forbidden:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(MarketCog(bot))
