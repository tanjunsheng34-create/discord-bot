"""
GMPT Bot — Auction House / 拍卖行
"""
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from cogs.economy import get_balance, add_coins
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class AuctionSellModal(discord.ui.Modal, title="🏷️ 拍卖出售 / Auction Sell"):
    item_name = discord.ui.TextInput(label="物品名称 / Item Name", placeholder="e.g. 稀有皮肤 / Rare Skin", max_length=100, required=True)
    start_price = discord.ui.TextInput(label="起拍价 / Start Price", placeholder="100", max_length=10, required=True)
    buyout_price = discord.ui.TextInput(label="一口价(0=不设)/ Buyout (0=none)", placeholder="500", max_length=10, required=True)
    duration_hours = discord.ui.TextInput(label="持续时间(小时)/ Duration (Hours)", placeholder="24", max_length=4, required=True)

    def __init__(self, owner_id: str):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            start = int(self.start_price.value)
            buyout = int(self.buyout_price.value)
            hours = int(self.duration_hours.value)
        except ValueError:
            return await interaction.response.send_message("请输入有效数字 / Enter valid numbers.", ephemeral=True)

        if start < 1 or hours < 1 or hours > 168:
            return await interaction.response.send_message("起拍价>0, 时长1-168小时 / Start>0, duration 1-168h.", ephemeral=True)

        uid = str(interaction.user.id)
        ends_at = (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS auctions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seller_id TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    start_price INTEGER NOT NULL,
                    buyout_price INTEGER DEFAULT 0,
                    current_bid INTEGER,
                    bidder_id TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    ends_at TEXT NOT NULL,
                    status TEXT DEFAULT 'active'
                )
            """)
            conn.commit()

            cur.execute("""
                INSERT INTO auctions (seller_id, item_name, start_price, buyout_price, current_bid, ends_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (uid, self.item_name.value, start, buyout, start, ends_at))
            conn.commit()
            aid = cur.lastrowid

        await interaction.response.send_message(
            f"✅ Auction #{aid} created! / 拍卖 #{aid} 已创建！\n"
            f"Item: **{self.item_name.value}** | Start: 🪙 {start:,} | Buyout: 🪙 {buyout:,}\n"
            f"Ends: {ends_at} UTC",
            ephemeral=False,
        )


class AuctionBidModal(discord.ui.Modal, title="💰 拍卖出价 / Auction Bid"):
    bid_amount = discord.ui.TextInput(label="出价金额 / Bid Amount", placeholder="Must be higher than current bid", max_length=12, required=True)

    def __init__(self, auction_id: int, current_bid: int, bidder_id: str):
        super().__init__()
        self.auction_id = auction_id
        self.current_bid = current_bid
        self.bidder_id = bidder_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.bid_amount.value)
        except ValueError:
            return await interaction.response.send_message("请输入有效数字 / Enter a valid number.", ephemeral=True)

        uid = str(interaction.user.id)
        if amount <= self.current_bid:
            return await interaction.response.send_message(
                f"出价必须高于当前价 🪙 {self.current_bid:,}! / Bid must exceed current bid.", ephemeral=True)

        bal = get_balance(uid)
        if bal < amount:
            return await interaction.response.send_message(f"金币不足！/ Not enough coins! You have 🪙 {bal:,}.", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM auctions WHERE id=? AND status='active'", (self.auction_id,))
            auction = cur.fetchone()
            if not auction:
                return await interaction.response.send_message("拍卖不存在或已结束 / Auction not found or ended.", ephemeral=True)

            if amount < auction["current_bid"]:
                return await interaction.response.send_message("当前价格已变化，请刷新 / Price changed, please refresh.", ephemeral=True)

            buyout = auction["buyout_price"]
            if buyout > 0 and amount >= buyout:
                amount = buyout
                # Instant buyout
                add_coins(uid, -amount, f"Auction buyout #{self.auction_id}")
                add_coins(auction["seller_id"], amount, f"Auction #{self.auction_id} sold (buyout)")
                cur.execute("UPDATE auctions SET status='sold', bidder_id=?, current_bid=? WHERE id=?",
                            (uid, amount, self.auction_id))
                conn.commit()
                return await interaction.response.send_message(
                    f"🎉 **一口价成交! / Buyout success!**\n"
                    f"Item: **{auction['item_name']}** | Price: 🪙 {amount:,}\n"
                    f"卖家 / Seller: <@{auction['seller_id']}> | 买家 / Buyer: <@{uid}>",
                )

            # Refund previous bidder
            old_bidder = auction["bidder_id"]
            if old_bidder and old_bidder != uid:
                add_coins(old_bidder, auction["current_bid"], f"Auction #{self.auction_id} outbid refund")

            add_coins(uid, -amount, f"Auction bid #{self.auction_id}")
            cur.execute("UPDATE auctions SET current_bid=?, bidder_id=? WHERE id=?", (amount, uid, self.auction_id))
            conn.commit()

        await interaction.response.send_message(
            f"✅ 出价成功 / Bid placed! 🪙 **{amount:,}** on **{auction['item_name']}** (Auction #{self.auction_id})",
        )


class AuctionView(discord.ui.View):
    """拍卖行按钮面板 / Auction house button panel."""

    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="🏷️ 出售 / Sell", style=discord.ButtonStyle.primary, row=0)
    async def sell_btn(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(AuctionSellModal(str(interaction.user.id)))

    @discord.ui.button(label="📋 浏览 / Browse", style=discord.ButtonStyle.primary, row=0)
    async def browse_btn(self, interaction: discord.Interaction, button):
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM auctions WHERE status='active' ORDER BY ends_at ASC LIMIT 10")
            rows = cur.fetchall()

        if not rows:
            embed = discord.Embed(title="🏷️ 拍卖行 / Auction House", description="暂无活跃拍卖 / No active auctions.", color=0xE67E22)
            return await interaction.response.edit_message(embed=embed, view=self)

        embed = discord.Embed(title="🏷️ 拍卖行 / Auction House", color=0xE67E22)
        for r in rows:
            bidder_text = f"<@{r['bidder_id']}>" if r["bidder_id"] else "无 / None"
            embed.add_field(
                name=f"#{r['id']} — {r['item_name']}",
                value=f"当前 / Current: 🪙 {r['current_bid']:,}\n"
                      f"一口价 / Buyout: 🪙 {r['buyout_price']:,}\n"
                      f"出价者 / Bidder: {bidder_text}\n"
                      f"结束 / Ends: {r['ends_at']}",
                inline=False,
            )
        embed.set_footer(text="点击「出价」按钮参与竞拍 / Click Bid to participate")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="💰 出价 / Bid", style=discord.ButtonStyle.success, row=0)
    async def bid_btn(self, interaction: discord.Interaction, button):
        class AuctionSelectModal(discord.ui.Modal, title="选择拍卖 / Select Auction"):
            auction_id_input = discord.ui.TextInput(label="拍卖编号 / Auction ID", placeholder="输入要出价的拍卖编号", max_length=10, required=True)

            async def on_submit(self2, sub_interaction: discord.Interaction):
                try:
                    aid = int(self2.auction_id_input.value)
                except ValueError:
                    return await sub_interaction.response.send_message("无效ID / Invalid ID.", ephemeral=True)

                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM auctions WHERE id=? AND status='active'", (aid,))
                    auction = cur.fetchone()
                if not auction:
                    return await sub_interaction.response.send_message("拍卖不存在 / Auction not found.", ephemeral=True)

                await sub_interaction.response.send_modal(
                    AuctionBidModal(aid, auction["current_bid"], str(sub_interaction.user.id))
                )

        await interaction.response.send_modal(AuctionSelectModal())

    @discord.ui.button(label="📦 我的 / My Items", style=discord.ButtonStyle.secondary, row=0)
    async def my_auctions_btn(self, interaction: discord.Interaction, button):
        uid = str(interaction.user.id)
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM auctions WHERE seller_id=? OR bidder_id=? ORDER BY id DESC LIMIT 10", (uid, uid))
            rows = cur.fetchall()

        if not rows:
            embed = discord.Embed(title="📦 我的拍卖 / My Auctions", description="暂无记录 / No auctions.", color=0xE67E22)
            return await interaction.response.edit_message(embed=embed, view=self)

        embed = discord.Embed(title="📦 我的拍卖 / My Auctions", color=0xE67E22)
        for r in rows:
            status_emoji = {"active": "🟢", "sold": "✅", "ended": "🔴"}.get(r["status"], "⚪")
            embed.add_field(
                name=f"{status_emoji} #{r['id']} — {r['item_name']}",
                value=f"状态 / Status: {r['status']} | 当前 / Current: 🪙 {r['current_bid']:,}",
                inline=False,
            )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀ 返回 / Back", style=discord.ButtonStyle.danger, row=1)
    async def back_btn(self, interaction: discord.Interaction, button):
        try:
            from cogs.dashboard import DashboardView
        except ImportError:
            from cogs.dashboard import DashboardView
        view = DashboardView(guild=interaction.guild, bot=None)
        view.category = 0
        view.build_page_buttons()
        embed = view._build_page_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class Auction(commands.Cog):
    """拍卖行系统 / Auction house system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="gmpt-auction", description="打开拍卖行 / Open auction house")
    async def auction_cmd(self, interaction: discord.Interaction):
        view = AuctionView()
        embed = discord.Embed(
            title="🏷️ 拍卖行 / Auction House",
            description="买卖稀有物品的拍卖行 / Buy and sell rare items!\n\n选择操作 / Choose an action:",
            color=0xE67E22,
        )
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Auction(bot))
    logger.info("Auction cog loaded")
