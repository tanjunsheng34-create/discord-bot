"""
GMPT Bot — MMORPG 交易行 / Player Market
/gmpt-market list/search/buy — 玩家间装备买卖
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


class MarketCog(CogBase):
    """交易行 / Player Market"""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)

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
                    listed_at TEXT DEFAULT (datetime('now'))
                )
            """)

    market = app_commands.Group(name="gmpt-market", description="交易行 / Player Market")

    @market.command(name="list", description="上架装备 / List equipment for sale")
    @app_commands.describe(item_name="装备名称 / Item name", price="售价(金币) / Price in gold")
    async def list_item(self, interaction: discord.Interaction, item_name: str, price: int):
        if price < 100:
            await interaction.response.send_message("最低售价100金币 / Minimum price 100 gold", ephemeral=True)
            return

        user_id = str(interaction.user.id)

        # Check if user owns this equipment
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

            # Remove from inventory and add to market
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
                    "FROM market_listings WHERE item_name LIKE ? ORDER BY price ASC LIMIT 10 OFFSET ?",
                    (f"%{query}%", (page - 1) * 10)
                )
            else:
                cur.execute(
                    "SELECT id, seller_id, item_name, item_type, tier, enhance_level, price, listed_at "
                    "FROM market_listings ORDER BY listed_at DESC LIMIT 10 OFFSET ?",
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
            cur.execute("SELECT seller_id, item_name, price FROM market_listings WHERE id=?", (listing_id,))
            listing = cur.fetchone()
            if not listing:
                await interaction.response.send_message("该上架已不存在 / Listing not found", ephemeral=True)
                return

            seller_id, item_name, price = listing

            if seller_id == buyer_id:
                await interaction.response.send_message("不能购买自己的物品 / Cannot buy your own listing", ephemeral=True)
                return

            # Check buyer balance
            from cogs.economy import get_balance
            bal = await get_balance(buyer_id)
            if bal < price:
                await interaction.response.send_message(
                    f"金币不足 / Not enough gold — 需要 `{price}G`，你有 `{bal}G`", ephemeral=True
                )
                return

            # Execute trade
            fee = int(price * MARKET_FEE)
            net = price - fee

            from cogs.economy import add_coins
            await add_coins(buyer_id, -price)
            await add_coins(seller_id, net)

            # Remove listing and give item to buyer
            cur.execute("DELETE FROM market_listings WHERE id=?", (listing_id,))
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

        # Notify seller
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
