"""
GMPT Bot — 交易市场 / Trading Marketplace
/gmpt-market sell — list equipment for sale
/gmpt-market buy  — purchase a listing
/gmpt-market list — browse active listings
"""
import logging
import discord
from discord import app_commands
from database import get_db_ctx
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)


def _init_market_db():
    with get_db_ctx() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_listings (
                listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                item_name TEXT NOT NULL,
                item_type TEXT DEFAULT 'equipment',
                price INTEGER NOT NULL,
                listed_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                status TEXT DEFAULT 'active',
                buyer_id TEXT
            )
        """)
        conn.commit()


class MarketListView(discord.ui.View):
    """Market browse view with pagination."""

    def __init__(self, uid: str, page: int = 0, main_view=None):
        super().__init__(timeout=180)
        self.uid = uid
        self.page = page
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        per_page = 5
        offset = self.page * per_page
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT listing_id, seller_id, item_name, price, listed_at FROM market_listings"
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
                    name=f"#{row['listing_id']} | {row['item_name']}",
                    value=(
                        f"Seller / 卖家: <@{row['seller_id']}>\n"
                        f"Price / 价格: 🪙 **{row['price']:,}**\n"
                        f"Listed / 上架时间: <t:{row['listed_at']}:R>"
                    ),
                    inline=False,
                )

        total_pages = max(1, (total + per_page - 1) // per_page)
        embed.set_footer(text=f"Page {self.page + 1}/{total_pages} | /gmpt-market buy <id> to purchase")
        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=0, custom_id="market:prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        try:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=0, custom_id="market:next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        try:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.danger, row=1, custom_id="market:back")
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


class MarketCog(CogBase):
    """Trading marketplace with slash commands."""

    def __init__(self, bot):
        super().__init__()
        _init_market_db()

    @app_commands.command(name="gmpt-market", description="🏪 Browse the marketplace / 浏览交易市场")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def market_list_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        view = MarketListView(uid)
        await interaction.response.send_message(embed=view.build_embed(), view=view)

    @app_commands.command(name="gmpt-market-sell", description="📤 List an equipment item for sale / 挂单出售装备")
    @app_commands.describe(
        item_name="Name of equipment in your inventory / 背包中装备名称",
        price="Selling price in coins / 售价（金币）",
    )
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
    async def sell_cmd(self, interaction: discord.Interaction, item_name: str, price: int):
        uid = str(interaction.user.id)
        if price < 1:
            return await interaction.response.send_message("❌ Price must be at least 1 coin / 价格至少为1金币", ephemeral=True)

        try:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                # Find the equipment item in inventory
                cur.execute(
                    "SELECT item_id, item_name, quantity FROM user_inventory"
                    " WHERE user_id = ? AND item_name LIKE ? AND item_type = 'equipment' AND quantity > 0",
                    (uid, f"%{item_name}%"),
                )
                rows = cur.fetchall()
                if not rows:
                    return await interaction.response.send_message(
                        "❌ Equipment not found in inventory / 背包中未找到该装备", ephemeral=True
                    )

                # Use first match
                item = rows[0]
                # Remove 1 from inventory
                if item["quantity"] <= 1:
                    cur.execute("DELETE FROM user_inventory WHERE user_id = ? AND item_id = ?", (uid, item["item_id"]))
                else:
                    cur.execute("UPDATE user_inventory SET quantity = quantity - 1 WHERE user_id = ? AND item_id = ?",
                                (uid, item["item_id"]))

                # Create listing
                cur.execute(
                    "INSERT INTO market_listings (seller_id, item_id, item_name, item_type, price) VALUES (?, ?, ?, 'equipment', ?)",
                    (uid, item["item_id"], item["item_name"], price),
                )
                listing_id = cur.lastrowid
                conn.commit()

            await interaction.response.send_message(
                f"✅ Listed for sale / 已上架: **{item['item_name']}**\n"
                f"Listing ID: **#{listing_id}** | Price: 🪙 **{price:,}**\n"
                f"Use `/gmpt-market` to browse all listings.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Market sell error: {e}", exc_info=True)
            await interaction.response.send_message(f"❌ Failed to list item / 上架失败: {e}", ephemeral=True)

    @app_commands.command(name="gmpt-market-buy", description="🛒 Buy a listing from the market / 购买市场挂单")
    @app_commands.describe(listing_id="The listing ID to purchase / 要购买的挂单ID")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
    async def buy_cmd(self, interaction: discord.Interaction, listing_id: int):
        uid = str(interaction.user.id)

        try:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                # Get listing
                cur.execute(
                    "SELECT * FROM market_listings WHERE listing_id = ? AND status = 'active'",
                    (listing_id,),
                )
                listing = cur.fetchone()
                if not listing:
                    return await interaction.response.send_message(
                        "❌ Listing not found or already sold / 挂单不存在或已售出", ephemeral=True
                    )
                if listing["seller_id"] == uid:
                    return await interaction.response.send_message(
                        "❌ You cannot buy your own listing / 不能购买自己的挂单", ephemeral=True
                    )

                price = listing["price"]
                # Check buyer balance
                cur.execute("SELECT score FROM users WHERE discord_id = ?", (uid,))
                bal_row = cur.fetchone()
                bal = bal_row["score"] if bal_row else 0
                if bal < price:
                    return await interaction.response.send_message(
                        f"❌ Insufficient coins! Need 🪙 {price:,}, you have 🪙 {bal:,}\n金币不足！", ephemeral=True
                    )

                # Deduct buyer coins
                from cogs.economy import add_coins
                add_coins(uid, -price, f"Market buy #{listing_id}: {listing['item_name']}")

                # Credit seller
                add_coins(listing["seller_id"], price, f"Market sold #{listing_id}: {listing['item_name']}")

                # Transfer item to buyer
                cur.execute(
                    "SELECT quantity FROM user_inventory WHERE user_id = ? AND item_id = ?",
                    (uid, listing["item_id"]),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        "UPDATE user_inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_id = ?",
                        (uid, listing["item_id"]),
                    )
                else:
                    cur.execute(
                        "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) VALUES (?, ?, ?, 1, 'equipment') "
                        "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + 1",
                        (uid, listing["item_id"], listing["item_name"]),
                    )

                # Mark listing as sold
                cur.execute(
                    "UPDATE market_listings SET status = 'sold', buyer_id = ? WHERE listing_id = ?",
                    (uid, listing_id),
                )
                conn.commit()

            await interaction.response.send_message(
                f"✅ Purchased / 已购买: **{listing['item_name']}**\n"
                f"From: <@{listing['seller_id']}> | Price: 🪙 **{price:,}**\n"
                f"Check `/gmpt-equip` to equip your new gear!",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Market buy error: {e}", exc_info=True)
            await interaction.response.send_message(f"❌ Purchase failed / 购买失败: {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(MarketCog(bot))
