"""
GMPT Bot — MMORPG Auction House / 拍卖行
/gmpt-auction — 拍卖行

浏览、上架、购买装备拍卖。上架费5%，48小时有效。
"""
import datetime
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx

logger = logging.getLogger(__name__)

AUCTION_DURATION_HOURS = 48
LISTING_FEE_RATE = 0.05
LISTING_FEE_MIN = 10
TAX_RATE = 0.05
ITEMS_PER_PAGE = 6


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


def _get_coins(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT score FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return (row["score"] or 0) if row else 0


# ══════════════════════════════════════════════════════════════
# DB Init
# ══════════════════════════════════════════════════════════════
def _init_auction_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mmorpg_auction_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id TEXT NOT NULL,
                item_name TEXT NOT NULL,
                item_type TEXT NOT NULL DEFAULT 'equipment',
                rarity TEXT NOT NULL DEFAULT 'common',
                stat_type TEXT,
                stat_value INTEGER DEFAULT 0,
                price INTEGER NOT NULL,
                listed_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                item_data TEXT
            )
        """)
        conn.commit()

_init_auction_tables()


def _get_active_listings(page: int = 0) -> tuple:
    """Return (listings, total_count) for pagination."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Expire old listings
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE mmorpg_auction_listings SET status = 'expired' WHERE status = 'active' AND expires_at < ?",
            (now,),
        )
        conn.commit()

        cur.execute(
            "SELECT COUNT(*) as cnt FROM mmorpg_auction_listings WHERE status = 'active'",
        )
        total = cur.fetchone()["cnt"]

        cur.execute(
            "SELECT * FROM mmorpg_auction_listings WHERE status = 'active' ORDER BY price ASC LIMIT ? OFFSET ?",
            (ITEMS_PER_PAGE, page * ITEMS_PER_PAGE),
        )
        listings = cur.fetchall()

    return listings, total


def _get_user_listings(uid: str) -> list:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM mmorpg_auction_listings WHERE seller_id = ? ORDER BY listed_at DESC LIMIT 20",
            (uid,),
        )
        return cur.fetchall()


def _get_user_equipment(uid: str) -> list:
    """Get equipment items from inventory that can be auctioned."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT item_id, item_name, quantity FROM user_inventory WHERE user_id = ? AND item_type = 'equipment' AND quantity > 0 ORDER BY item_name",
            (uid,),
        )
        return cur.fetchall()


def _remove_from_inventory(uid: str, item_id: str):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE user_inventory SET quantity = quantity - 1 WHERE user_id = ? AND item_id = ? AND quantity > 0",
            (uid, item_id),
        )
        conn.commit()


def _return_to_inventory(uid: str, item_name: str, item_data: str | None):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        item_id = f"auction_return_{item_name}_{int(datetime.datetime.now().timestamp())}"
        cur.execute(
            "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type, item_data) "
            "VALUES (?, ?, ?, 1, 'equipment', ?)",
            (uid, item_id, item_name, item_data or ""),
        )
        conn.commit()


# ══════════════════════════════════════════════════════════════
# AuctionView — Main UI
# ══════════════════════════════════════════════════════════════
class AuctionView(discord.ui.View):
    """拍卖行主面板 / Auction House main panel."""

    def __init__(self, uid: str, page: int = 0, main_view=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.page = page
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        listings, total = _get_active_listings(self.page)

        if not listings:
            embed = discord.Embed(
                title="💎 Auction House / 拍卖行",
                description="No active listings!\n暂无拍卖物品！\n\nUse `/gmpt-auction sell` to list equipment.\n使用 `/gmpt-auction sell` 上架装备。",
                color=0x607D8B,
            )
            embed.set_footer(text=f"Page {self.page + 1} | Total: 0")
            return embed

        desc_lines = []
        for item in listings:
            rarity_emoji = {"common": "⬜", "rare": "🔵", "epic": "🟣", "legendary": "🟡", "mythic": "🔴"}.get(
                item["rarity"], "⬜"
            )

            # Parse item display
            name_parts = item["item_name"].split("|||")
            display_name = name_parts[0] if name_parts else item["item_name"]

            expires = datetime.datetime.fromisoformat(item["expires_at"])
            now = datetime.datetime.now(datetime.timezone.utc)
            remaining = expires - now
            if remaining.total_seconds() < 0:
                time_str = "Expired"
            elif remaining.days > 0:
                time_str = f"{remaining.days}d {remaining.seconds // 3600}h"
            else:
                time_str = f"{remaining.seconds // 3600}h {(remaining.seconds % 3600) // 60}m"

            desc_lines.append(
                f"**#{item['id']}** {rarity_emoji} {display_name}\n"
                f"Price: 🪙 {item['price']:,} | Rarity: {item['rarity'].title()}\n"
                f"Seller: <@{item['seller_id']}> | Time left: {time_str}\n"
            )

        total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

        embed = discord.Embed(
            title="💎 Auction House / 拍卖行",
            description="\n".join(desc_lines) if desc_lines else "No items.",
            color=0x1ABC9C,
        )
        embed.set_footer(text=f"Page {self.page + 1}/{total_pages} | Total: {total} items | Use Buy button or /gmpt-auction buy <id>")
        return embed

    def _refresh_buttons(self):
        self.clear_items()
        listings, total = _get_active_listings(self.page)
        total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

        # Prev page
        self.add_item(discord.ui.Button(
            label="◀ Prev 上页", emoji="◀️",
            style=discord.ButtonStyle.secondary,
            row=0, disabled=self.page <= 0,
            custom_id=f"auction:prev:{self.page}",
        ))
        # Next page
        self.add_item(discord.ui.Button(
            label="Next 下页 ▶", emoji="▶️",
            style=discord.ButtonStyle.secondary,
            row=0, disabled=self.page >= total_pages - 1,
            custom_id=f"auction:next:{self.page}",
        ))
        # Buy
        self.add_item(discord.ui.Button(
            label="Buy 购买", emoji="💰",
            style=discord.ButtonStyle.success,
            row=0,
            custom_id=f"auction:buy",
        ))
        # My listings
        self.add_item(discord.ui.Button(
            label="My 我的", emoji="📦",
            style=discord.ButtonStyle.primary,
            row=0,
            custom_id=f"auction:my",
        ))
        # Back
        self.add_item(discord.ui.Button(
            label="Back 返回", emoji="🔙",
            style=discord.ButtonStyle.secondary,
            row=1,
            custom_id=f"auction:back",
        ))

    async def _handle_button(self, interaction: discord.Interaction, custom_id: str):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return

        if custom_id.startswith("auction:prev"):
            self.page = max(0, self.page - 1)
            embed = self.build_embed()
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)

        elif custom_id.startswith("auction:next"):
            self.page += 1
            embed = self.build_embed()
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)

        elif custom_id == "auction:my":
            listings = _get_user_listings(uid)
            if not listings:
                embed = discord.Embed(
                    title="📦 My Listings / 我的上架",
                    description="You have no listings!\n你还没有上架物品！",
                    color=0x607D8B,
                )
            else:
                lines = []
                for item in listings:
                    status_emoji = {"active": "🟢", "sold": "✅", "expired": "⏰", "cancelled": "❌"}.get(item["status"], "❓")
                    lines.append(
                        f"#{item['id']} {status_emoji} {item['item_name']} — 🪙 {item['price']:,} [{item['status']}]"
                    )
                embed = discord.Embed(
                    title="📦 My Listings / 我的上架",
                    description="\n".join(lines),
                    color=0x3498DB,
                )

            # Also handle expired returns
            expired_items = [i for i in listings if i["status"] == "expired"]
            for item in expired_items:
                _return_to_inventory(uid, item["item_name"], item.get("item_data"))
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute("UPDATE mmorpg_auction_listings SET status = 'returned' WHERE id = ?", (item["id"],))
                    conn.commit()

            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)

        elif custom_id.startswith("auction:back"):
            if self.main_view:
                from cogs.mmorpg_shop import build_main_embed
                embed = build_main_embed(self.uid, interaction.user.display_name)
                try:
                    await interaction.response.edit_message(embed=embed, view=self.main_view)
                except discord.InteractionResponded:
                    await interaction.edit_original_response(embed=embed, view=self.main_view)
            else:
                embed = discord.Embed(
                    title="💎 Auction / 拍卖行",
                    description="Use `/gmpt-mmorpg` to return.",
                    color=0x95A5A6,
                )
                try:
                    await interaction.response.edit_message(embed=embed, view=None)
                except discord.InteractionResponded:
                    await interaction.edit_original_response(embed=embed, view=None)


class AuctionBuyView(discord.ui.View):
    """购买确认面板."""

    def __init__(self, uid: str, listing: dict, main_view=None):
        super().__init__(timeout=60)
        self.uid = uid
        self.listing = listing
        self.main_view = main_view

    @discord.ui.button(label="Confirm Buy 确认购买", emoji="💰", style=discord.ButtonStyle.success, row=0)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return

        # Re-check listing is still active
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM mmorpg_auction_listings WHERE id = ? AND status = 'active'", (self.listing["id"],))
            listing = cur.fetchone()

        if not listing:
            embed = discord.Embed(
                title="💰 Buy Failed / 购买失败",
                description="This item is no longer available!\n该物品已下架或已售出！",
                color=0xE74C3C,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)
            return

        listing = dict(listing)
        coins = _get_coins(uid)
        if coins < listing["price"]:
            embed = discord.Embed(
                title="💰 Buy Failed / 购买失败",
                description=f"Need 🪙 {listing['price']:,} but you have {coins:,}.",
                color=0xE74C3C,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)
            return

        if listing["seller_id"] == uid:
            embed = discord.Embed(
                title="💰 Buy Failed",
                description="You cannot buy your own listing!",
                color=0xE74C3C,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)
            return

        tax = int(listing["price"] * TAX_RATE)
        seller_receive = listing["price"] - tax

        # Transfer
        _add_coins(uid, -listing["price"], f"Auction buy #{listing['id']}: {listing['item_name']}")
        _add_coins(listing["seller_id"], seller_receive, f"Auction sold #{listing['id']}: {listing['item_name']} (tax: {tax})")

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE mmorpg_auction_listings SET status = 'sold' WHERE id = ?", (listing["id"],))
            conn.commit()

        # Add item to buyer
        with get_db_ctx() as conn:
            cur = conn.cursor()
            item_id = f"auction_buy_{listing['id']}"
            cur.execute(
                "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) "
                "VALUES (?, ?, ?, 1, 'equipment')",
                (uid, item_id, listing["item_name"]),
            )
            conn.commit()

        embed = discord.Embed(
            title="💰 Purchase Complete! / 购买成功！",
            description=(
                f"Bought **{listing['item_name']}** for 🪙 {listing['price']:,}\n"
                f"Seller received 🪙 {seller_receive:,} (tax: 🪙 {tax:,})"
            ),
            color=0x2ECC71,
        )

        try:
            await interaction.response.edit_message(embed=embed, view=None)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="Cancel 取消", emoji="❌", style=discord.ButtonStyle.danger, row=0)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AuctionView(self.uid, main_view=self.main_view)
        embed = view.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)


class AuctionSellSelectView(discord.ui.View):
    """选择要拍卖的装备."""

    def __init__(self, uid: str, equipment: list, price: int, main_view=None):
        super().__init__(timeout=120)
        self.uid = uid
        self.price = price
        self.main_view = main_view

        if not equipment:
            self._add_label("No equipment in inventory! / 背包中没有装备！")
            return

        options = []
        for i, eq in enumerate(equipment[:25]):
            label = f"{eq['item_name'][:80]} (x{eq['quantity']})"
            options.append(discord.SelectOption(label=label[:100], value=str(i)))

        select = discord.ui.Select(
            placeholder="Select equipment to sell... / 选择要拍卖的装备...",
            options=options,
            row=0,
        )
        select.callback = self._select_callback
        self.add_item(select)
        self._equipment = equipment

    async def _select_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return

        idx = int(interaction.data["values"][0])
        item = self._equipment[idx]
        item_name = item["item_name"]
        item_id = item["item_id"]

        fee = max(LISTING_FEE_MIN, int(self.price * LISTING_FEE_RATE))
        coins = _get_coins(uid)
        if coins < fee:
            embed = discord.Embed(
                title="💎 List Failed / 上架失败",
                description=f"Listing fee: 🪙 {fee:,}. You have {coins:,}.",
                color=0xE74C3C,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)
            return

        _add_coins(uid, -fee, f"拍卖上架费 — Auction listing fee: {item_name}")

        now = datetime.datetime.now(datetime.timezone.utc)
        expires = now + datetime.timedelta(hours=AUCTION_DURATION_HOURS)

        # Parse rarity from item_name
        rarity = "common"
        for r in ["mythic", "legendary", "epic", "rare"]:
            if r in item_name.lower():
                rarity = r
                break

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO mmorpg_auction_listings (seller_id, item_name, item_type, rarity, price, listed_at, expires_at, status) "
                "VALUES (?, ?, 'equipment', ?, ?, ?, ?, 'active')",
                (uid, item_name, rarity, self.price, now.isoformat(), expires.isoformat()),
            )
            conn.commit()

        _remove_from_inventory(uid, item_id)

        embed = discord.Embed(
            title="💎 Item Listed! / 上架成功！",
            description=(
                f"**{item_name}**\n"
                f"Price: 🪙 {self.price:,}\n"
                f"Fee: 🪙 {fee:,}\n"
                f"Expires: <t:{int(expires.timestamp())}:R>"
            ),
            color=0x2ECC71,
        )

        try:
            await interaction.response.edit_message(embed=embed, view=None)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=None)

    def _add_label(self, text: str):
        label = discord.ui.Button(label=text, style=discord.ButtonStyle.secondary, disabled=True, row=1)
        self.add_item(label)


# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════

class AuctionCog(commands.Cog):
    """拍卖行系统 / Auction House System."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    auction_group = app_commands.Group(name="gmpt-auction", description="Auction House / 拍卖行")

    @auction_group.command(name="list", description="Browse auction listings")
    async def auction_list(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        view = AuctionView(uid)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)

    @auction_group.command(name="sell", description="List equipment for auction")
    @app_commands.describe(item_name="Item name to sell / 要出售的物品名称", price="Price in gold / 价格(金币)")
    async def auction_sell(self, interaction: discord.Interaction, item_name: str, price: int):
        uid = str(interaction.user.id)
        if price < 10:
            await interaction.response.send_message("Minimum price is 10G.", ephemeral=True)
            return

        equipment = _get_user_equipment(uid)
        if not equipment:
            await interaction.response.send_message("No equipment in inventory!", ephemeral=True)
            return

        # Filter by name if specified
        if item_name:
            equipment = [e for e in equipment if item_name.lower() in e["item_name"].lower()]

        if not equipment:
            await interaction.response.send_message(
                f"No matching equipment found: {item_name}\n未找到匹配的装备: {item_name}",
                ephemeral=True,
            )
            return

        if len(equipment) == 1:
            # Single match, sell directly
            item = equipment[0]
            fee = max(LISTING_FEE_MIN, int(price * LISTING_FEE_RATE))
            coins = _get_coins(uid)
            if coins < fee:
                await interaction.response.send_message(
                    f"Listing fee: 🪙 {fee:,}. You have {coins:,}.",
                    ephemeral=True,
                )
                return

            _add_coins(uid, -fee, f"拍卖上架费 — Auction listing fee: {item['item_name']}")
            now = datetime.datetime.now(datetime.timezone.utc)
            expires = now + datetime.timedelta(hours=AUCTION_DURATION_HOURS)

            rarity = "common"
            for r in ["mythic", "legendary", "epic", "rare"]:
                if r in item["item_name"].lower():
                    rarity = r
                    break

            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO mmorpg_auction_listings (seller_id, item_name, item_type, rarity, price, listed_at, expires_at, status) "
                    "VALUES (?, ?, 'equipment', ?, ?, ?, ?, 'active')",
                    (uid, item["item_name"], rarity, price, now.isoformat(), expires.isoformat()),
                )
                conn.commit()

            _remove_from_inventory(uid, item["item_id"])

            embed = discord.Embed(
                title="💎 Item Listed! / 上架成功！",
                description=f"**{item['item_name']}** — 🪙 {price:,}\nExpires: <t:{int(expires.timestamp())}:R>",
                color=0x2ECC71,
            )
            await interaction.response.send_message(embed=embed)
        else:
            # Multiple matches, let user select
            view = AuctionSellSelectView(uid, equipment, price)
            embed = discord.Embed(
                title="💎 Select Equipment / 选择装备",
                description="Choose the item to list:\n选择要上架的装备：",
                color=0x1ABC9C,
            )
            await interaction.response.send_message(embed=embed, view=view)

    @auction_group.command(name="buy", description="Buy an auction listing by ID")
    @app_commands.describe(listing_id="Listing ID / 拍卖品ID")
    async def auction_buy(self, interaction: discord.Interaction, listing_id: int):
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM mmorpg_auction_listings WHERE id = ? AND status = 'active'", (listing_id,))
            listing = cur.fetchone()

        if not listing:
            await interaction.response.send_message("Listing not found or already sold!", ephemeral=True)
            return

        listing = dict(listing)
        coins = _get_coins(uid)
        if coins < listing["price"]:
            await interaction.response.send_message(
                f"Need 🪙 {listing['price']:,} but you have {coins:,}.",
                ephemeral=True,
            )
            return

        if listing["seller_id"] == uid:
            await interaction.response.send_message("You cannot buy your own listing!", ephemeral=True)
            return

        view = AuctionBuyView(uid, listing)
        embed = discord.Embed(
            title="💰 Confirm Purchase / 确认购买",
            description=(
                f"**#{listing['id']}** {listing['item_name']}\n"
                f"Price: 🪙 {listing['price']:,}\n"
                f"Seller: <@{listing['seller_id']}>\n"
            ),
            color=0xF39C12,
        )
        await interaction.response.send_message(embed=embed, view=view)

    @auction_group.command(name="my", description="View your auction listings")
    async def auction_my(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        listings = _get_user_listings(uid)

        if not listings:
            await interaction.response.send_message("You have no listings!", ephemeral=True)
            return

        lines = []
        for item in listings:
            status_emoji = {"active": "🟢", "sold": "✅", "expired": "⏰", "cancelled": "❌"}.get(item["status"], "❓")
            lines.append(f"#{item['id']} {status_emoji} {item['item_name']} — 🪙 {item['price']:,} [{item['status']}]")

        embed = discord.Embed(
            title="📦 My Listings / 我的上架",
            description="\n".join(lines),
            color=0x3498DB,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="gmpt-auction", description="Auction House / 拍卖行 — browse and trade equipment!")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def auction_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        view = AuctionView(uid)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(AuctionCog(bot))
    logger.info("MMORPG Auction cog loaded")
