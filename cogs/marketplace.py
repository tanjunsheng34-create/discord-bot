"""
GMPT Bot — 玩家市场 / Player Marketplace
/gmpt-market sell / list / buy / cancel

Bilingual (中文 / English)
"""
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


def _init_market_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS marketplace (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id TEXT NOT NULL,
                item_name TEXT NOT NULL,
                price INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                listed_at TEXT DEFAULT (datetime('now')),
                active INTEGER DEFAULT 1
            )
        """)
        conn.commit()


_init_market_tables()


class Marketplace(CogBase):
    """玩家市场 / Player Marketplace."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        cmds = [cmd.qualified_name for cmd in self.get_app_commands()]
        logger.info(f"[Marketplace] cog_load — 已注册 {len(cmds)} 个命令: {', '.join(cmds)}")

    market_group = app_commands.Group(
        name="gmpt-market",
        description="🏪 玩家市场 / Player Marketplace"
    )

    @market_group.command(name="sell", description="出售物品 / List an item for sale")
    @app_commands.describe(
        item_name="物品名称 / Item name",
        price="单价 / Unit price",
        quantity="数量 / Quantity (default 1)",
    )
    async def market_sell(self, interaction: discord.Interaction, item_name: str, price: int, quantity: int = 1):
        uid = str(interaction.user.id)

        if price < 1:
            return await interaction.response.send_message("价格必须 >= 1 / Price must be >= 1.", ephemeral=True)
        if quantity < 1 or quantity > 999:
            return await interaction.response.send_message("数量需在 1-999 之间 / Quantity must be 1-999.", ephemeral=True)

        # Market listing fee: 5%
        fee = max(int(price * quantity * 0.05), 1)
        bal = get_balance(uid)
        if bal < fee:
            return await interaction.response.send_message(
                f"上架手续费不足！需要 🪙 {fee:,}，你只有 🪙 {bal:,} / "
                f"Listing fee insufficient! Need 🪙 {fee:,}.",
                ephemeral=True,
            )

        add_coins(uid, -fee, f"市场上架: {item_name} x{quantity} / Market listing fee")

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO marketplace (seller_id, item_name, price, quantity) VALUES (?, ?, ?, ?)",
                (uid, item_name, price, quantity),
            )
            listing_id = cur.lastrowid
            conn.commit()

        embed = discord.Embed(
            title="🏪 上架成功 / Listed!",
            description=f"**{item_name}** x{quantity}\n"
                        f"单价 / Unit Price: 🪙 **{price:,}**\n"
                        f"总价 / Total: 🪙 **{price * quantity:,}**\n"
                        f"手续费 / Fee: 🪙 **{fee:,}** (5%)",
            color=0x2ECC71,
        )
        embed.add_field(name="📋 物品ID / Listing ID", value=f"#{listing_id}", inline=True)
        embed.set_footer(text="使用 /gmpt-market list 查看市场")

        await interaction.response.send_message(embed=embed)

    @market_group.command(name="list", description="查看市场列表 / View marketplace listings")
    @app_commands.describe(page="页码 / Page number")
    async def market_list(self, interaction: discord.Interaction, page: int = 1):
        per_page = 10
        offset = (page - 1) * per_page

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM marketplace WHERE active=1")
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT * FROM marketplace WHERE active=1 ORDER BY listed_at DESC LIMIT ? OFFSET ?",
                (per_page, offset),
            )
            rows = cur.fetchall()

        if not rows:
            return await interaction.response.send_message("市场为空 / Marketplace is empty.", ephemeral=True)

        embed = discord.Embed(
            title="🏪 玩家市场 / Marketplace",
            description=f"共 {total} 件商品 | Page {page}/{max(1, (total + per_page - 1) // per_page)}",
            color=0x3498DB,
        )

        for r in rows:
            embed.add_field(
                name=f"#{r['id']} — {r['item_name']} x{r['quantity']}",
                value=f"💰 🪙 {r['price']:,} / 个\n"
                      f"👤 卖家 / Seller: <@{r['seller_id']}>\n"
                      f"📅 {r['listed_at'] or 'Unknown'}",
                inline=False,
            )

        embed.set_footer(text="/gmpt-market buy <ID> 购买 | /gmpt-market cancel <ID> 取消")

        await interaction.response.send_message(embed=embed)

    @market_group.command(name="buy", description="购买物品 / Buy an item from marketplace")
    @app_commands.describe(
        listing_id="物品ID / Listing ID",
        quantity="数量 / Quantity (default 1)",
    )
    async def market_buy(self, interaction: discord.Interaction, listing_id: int, quantity: int = 1):
        uid = str(interaction.user.id)

        if quantity < 1:
            return await interaction.response.send_message("数量需 >= 1 / Quantity >= 1.", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM marketplace WHERE id=? AND active=1", (listing_id,))
            row = cur.fetchone()

            if not row:
                return await interaction.response.send_message("商品不存在或已下架 / Item not found.", ephemeral=True)
            if row["seller_id"] == uid:
                return await interaction.response.send_message("不能买自己的商品 / Cannot buy your own listing.", ephemeral=True)
            if row["quantity"] < quantity:
                return await interaction.response.send_message(
                    f"库存不足！仅剩 {row['quantity']} 个 / Only {row['quantity']} left.", ephemeral=True)

            total_cost = row["price"] * quantity
            fee = max(int(total_cost * 0.05), 1)
            seller_receives = total_cost - fee

            bal = get_balance(uid)
            if bal < total_cost:
                return await interaction.response.send_message(
                    f"金币不足！需要 🪙 {total_cost:,}，你只有 🪙 {bal:,} / Insufficient balance.",
                    ephemeral=True,
                )

            # Execute transaction
            add_coins(uid, -total_cost, f"市场购买 #{listing_id}: {row['item_name']}")
            add_coins(row["seller_id"], seller_receives, f"市场售出 #{listing_id}: {row['item_name']}")

            if row["quantity"] <= quantity:
                cur.execute("UPDATE marketplace SET active=0 WHERE id=?", (listing_id,))
            else:
                cur.execute("UPDATE marketplace SET quantity=quantity-? WHERE id=?", (quantity, listing_id,))
            conn.commit()

        embed = discord.Embed(
            title="🛒 购买成功 / Purchased!",
            description=f"**{row['item_name']}** x{quantity}\n"
                        f"单价 / Unit Price: 🪙 **{row['price']:,}**\n"
                        f"总计 / Total: 🪙 **{total_cost:,}**\n"
                        f"手续费 / Fee: 🪙 **{fee:,}** (5%)",
            color=0x2ECC71,
        )
        embed.add_field(name="💰 余额 / Balance", value=_format_coins(get_balance(uid)), inline=True)

        await interaction.response.send_message(embed=embed)

    @market_group.command(name="cancel", description="取消出售 / Cancel a listing")
    @app_commands.describe(listing_id="物品ID / Listing ID")
    async def market_cancel(self, interaction: discord.Interaction, listing_id: int):
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM marketplace WHERE id=? AND active=1", (listing_id,))
            row = cur.fetchone()

            if not row:
                return await interaction.response.send_message("商品不存在或已下架 / Item not found.", ephemeral=True)
            if row["seller_id"] != uid:
                return await interaction.response.send_message("这不是你的商品 / Not your listing.", ephemeral=True)

            cur.execute("UPDATE marketplace SET active=0 WHERE id=?", (listing_id,))
            conn.commit()

        await interaction.response.send_message(
            f"✅ 已取消出售 #{listing_id} **{row['item_name']}** x{row['quantity']} / "
            f"Listing cancelled.",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Marketplace(bot))
