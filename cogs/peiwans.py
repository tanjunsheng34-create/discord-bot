"""
GMPT Bot — 陪玩系统 / Companion System
/pw-apply <game> <rank> <price> <intro>   — 申请成为陪玩 | Apply as companion
/pw-profile [@user]                       — 查看陪玩主页 | View profile
/pw-online                                — 上线接单 | Go online
/pw-offline                               — 下线休息 | Go offline
/pw-list [game]                           — 浏览在线陪玩 | Browse online companions
/pw-order <@peiwans> <game>               — 下单指定陪玩 | Order companion
/pw-order-match <game>                    — 自动匹配陪玩 | Auto match
/pw-accept <order_id>                     — 接单 | Accept order
/pw-reject <order_id>                     — 拒单 | Reject order
/pw-complete <order_id>                   — 完成服务 | Complete order
/pw-cancel <order_id>                     — 取消订单 | Cancel order
/pw-rate <order_id> <rating> [comment]    — 评分 | Rate
/pw-earnings                              — 我的收益 | My earnings
/pw-orders                                — 我的订单 | My orders
"""
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db


PW_GREEN = 0x2ECC71


class Peiwan(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def init_db():
        """Create peiwans tables if not exist. Called from database.init_db()."""
        conn = get_db()
        cur = conn.cursor()

        cur.executescript("""
            CREATE TABLE IF NOT EXISTS peiwans_profiles (
                user_id INTEGER PRIMARY KEY,
                game TEXT,
                rank TEXT,
                price INTEGER,
                intro TEXT,
                status TEXT DEFAULT 'offline',
                total_orders INTEGER DEFAULT 0,
                avg_rating REAL DEFAULT 0,
                total_earnings INTEGER DEFAULT 0,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS peiwans_orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER,
                peiwans_id INTEGER,
                game TEXT,
                price INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS peiwans_reviews (
                review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                reviewer_id INTEGER,
                peiwans_id INTEGER,
                rating INTEGER,
                comment TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS peiwans_earnings (
                earning_id INTEGER PRIMARY KEY AUTOINCREMENT,
                peiwans_id INTEGER,
                order_id INTEGER,
                amount INTEGER,
                created_at TEXT
            );
        """)

        conn.commit()
        conn.close()

    # ─────────────────────────────────────────────
    # Helper: build profile embed
    # ─────────────────────────────────────────────
    def _profile_embed(self, user: discord.User, profile: dict) -> discord.Embed:
        status_map = {"online": "在线 | Online", "offline": "离线 | Offline", "busy": "忙碌 | Busy"}
        status_text = status_map.get(profile["status"], profile["status"])

        embed = discord.Embed(
            title=f"陪玩主页 | Companion Profile — {user.display_name}",
            color=PW_GREEN,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="游戏 | Game", value=profile.get("game", "未设置"), inline=True)
        embed.add_field(name="段位 | Rank", value=profile.get("rank", "未设置"), inline=True)
        embed.add_field(name="价格 | Price", value=f"{profile.get('price', 0)} 金币/局", inline=True)
        embed.add_field(name="状态 | Status", value=status_text, inline=True)
        embed.add_field(name="总单数 | Total Orders", value=str(profile.get("total_orders", 0)), inline=True)
        embed.add_field(name="评分 | Rating", value=f"{profile.get('avg_rating', 0):.1f} / 5.0", inline=True)
        embed.add_field(name="总收益 | Earnings", value=f"{profile.get('total_earnings', 0)} 金币", inline=True)

        intro = profile.get("intro", "")
        if intro:
            embed.add_field(name="简介 | Intro", value=intro, inline=False)

        return embed

    # ─────────────────────────────────────────────
    # /pw-apply
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-apply", description="申请成为陪玩 | Apply as companion")
    @app_commands.describe(
        game="游戏名称 | Game name",
        rank="段位 | Rank (e.g. Diamond, Master)",
        price="价格（金币/局）| Price per game (coins)",
        intro="自我介绍 | Self introduction",
    )
    async def apply(self, interaction: discord.Interaction, game: str, rank: str, price: int, intro: str):
        uid = interaction.user.id
        now = datetime.utcnow().isoformat()

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM peiwans_profiles WHERE user_id = ?", (uid,))
        existing = cur.fetchone()

        if existing:
            cur.execute(
                "UPDATE peiwans_profiles SET game=?, rank=?, price=?, intro=? WHERE user_id=?",
                (game, rank, price, intro, uid),
            )
            msg = "陪玩信息已更新 | Profile updated"
        else:
            cur.execute(
                "INSERT INTO peiwans_profiles (user_id, game, rank, price, intro, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'offline', ?)",
                (uid, game, rank, price, intro, now),
            )
            msg = "申请成功，默认离线状态，使用 /pw-online 上线 | Applied! Use /pw-online to go online"

        conn.commit()
        conn.close()

        await interaction.response.send_message(msg, ephemeral=True)

    # ─────────────────────────────────────────────
    # /pw-profile
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-profile", description="查看陪玩主页 | View companion profile")
    @app_commands.describe(user="要查看的用户（留空则查看自己）| User to view (leave empty for self)")
    async def profile(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        uid = target.id

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM peiwans_profiles WHERE user_id = ?", (uid,))
        row = cur.fetchone()
        conn.close()

        if row is None:
            await interaction.response.send_message(
                "该用户尚未注册陪玩 | This user hasn't registered as companion",
                ephemeral=True,
            )
            return

        embed = self._profile_embed(target, dict(row))
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────
    # /pw-online
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-online", description="上线接单 | Go online")
    async def online(self, interaction: discord.Interaction):
        uid = interaction.user.id

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM peiwans_profiles WHERE user_id = ?", (uid,))
        row = cur.fetchone()

        if row is None:
            conn.close()
            await interaction.response.send_message(
                "请先使用 /pw-apply 注册陪玩 | Register first with /pw-apply",
                ephemeral=True,
            )
            return

        cur.execute("UPDATE peiwans_profiles SET status='online' WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()

        await interaction.response.send_message("已上线，开始接单 | You are now online and accepting orders 🟢")

    # ─────────────────────────────────────────────
    # /pw-offline
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-offline", description="下线休息 | Go offline")
    async def offline(self, interaction: discord.Interaction):
        uid = interaction.user.id

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM peiwans_profiles WHERE user_id = ?", (uid,))
        row = cur.fetchone()

        if row is None:
            conn.close()
            await interaction.response.send_message(
                "请先使用 /pw-apply 注册陪玩 | Register first with /pw-apply",
                ephemeral=True,
            )
            return

        cur.execute("UPDATE peiwans_profiles SET status='offline' WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()

        await interaction.response.send_message("已下线 | You are now offline 🔴")

    # ─────────────────────────────────────────────
    # /pw-list
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-list", description="浏览在线陪玩 | Browse online companions")
    @app_commands.describe(game="按游戏筛选（可选）| Filter by game (optional)")
    async def list_companions(self, interaction: discord.Interaction, game: str = None):
        conn = get_db()
        cur = conn.cursor()

        if game:
            cur.execute(
                "SELECT * FROM peiwans_profiles WHERE status='online' AND game LIKE ? ORDER BY avg_rating DESC",
                (f"%{game}%",),
            )
        else:
            cur.execute("SELECT * FROM peiwans_profiles WHERE status='online' ORDER BY avg_rating DESC")

        rows = cur.fetchall()
        conn.close()

        if not rows:
            await interaction.response.send_message(
                f"当前没有在线陪玩 | No companions online{' for ' + game if game else ''}",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"在线陪玩 | Online Companions{' — ' + game if game else ''}",
            color=PW_GREEN,
        )

        for row in rows:
            profile = dict(row)
            user = self.bot.get_user(profile["user_id"])
            name = user.display_name if user else f"ID: {profile['user_id']}"
            value = (
                f"**{profile['game']}** | {profile['rank']} | {profile['price']} 金币/局\n"
                f"评分: {profile['avg_rating']:.1f}/5 | 总单: {profile['total_orders']}\n"
                f"{profile.get('intro', '')[:80]}"
            )
            embed.add_field(name=name, value=value, inline=False)

        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────
    # /pw-order
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-order", description="下单指定陪玩 | Order a specific companion")
    @app_commands.describe(
        peiwans="陪玩对象 | The companion to order",
        game="游戏名称 | Game name",
    )
    async def order(self, interaction: discord.Interaction, peiwans: discord.Member, game: str):
        customer_id = interaction.user.id
        pw_id = peiwans.id

        if customer_id == pw_id:
            await interaction.response.send_message("不能给自己下单 | Cannot order yourself", ephemeral=True)
            return

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM peiwans_profiles WHERE user_id = ?", (pw_id,))
        pw_row = cur.fetchone()

        if pw_row is None:
            conn.close()
            await interaction.response.send_message("该用户尚未注册陪玩 | User not registered", ephemeral=True)
            return

        profile = dict(pw_row)

        if profile["status"] != "online":
            conn.close()
            await interaction.response.send_message(
                "该陪玩当前不在线 | This companion is currently offline",
                ephemeral=True,
            )
            return

        price = profile["price"]
        now = datetime.utcnow().isoformat()

        cur.execute(
            "INSERT INTO peiwans_orders (customer_id, peiwans_id, game, price, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (customer_id, pw_id, game, price, now),
        )
        order_id = cur.lastrowid
        conn.commit()
        conn.close()

        embed = discord.Embed(
            title="订单已创建 | Order Created",
            description=f"订单 #{order_id}\n陪玩: {peiwans.mention}\n游戏: {game}\n价格: {price} 金币",
            color=PW_GREEN,
        )
        embed.set_footer(text="等待陪玩接单 | Waiting for companion to accept")

        await interaction.response.send_message(embed=embed)

        # Notify companion
        try:
            await peiwans.send(
                f"你有新订单！| You have a new order!\n"
                f"订单 #{order_id} | 客户: {interaction.user.mention} | 游戏: {game} | {price} 金币\n"
                f"使用 /pw-accept {order_id} 或 /pw-reject {order_id}"
            )
        except Exception:
            pass

    # ─────────────────────────────────────────────
    # /pw-order-match
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-order-match", description="自动匹配陪玩 | Auto match companion")
    @app_commands.describe(game="游戏名称 | Game name")
    async def order_match(self, interaction: discord.Interaction, game: str):
        customer_id = interaction.user.id

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM peiwans_profiles WHERE status='online' AND game LIKE ? ORDER BY avg_rating DESC LIMIT 1",
            (f"%{game}%",),
        )
        pw_row = cur.fetchone()

        if pw_row is None:
            conn.close()
            await interaction.response.send_message(
                f"没有在线的 {game} 陪玩 | No online companions for {game}",
                ephemeral=True,
            )
            return

        profile = dict(pw_row)
        pw_id = profile["user_id"]
        price = profile["price"]
        now = datetime.utcnow().isoformat()

        cur.execute(
            "INSERT INTO peiwans_orders (customer_id, peiwans_id, game, price, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (customer_id, pw_id, game, price, now),
        )
        order_id = cur.lastrowid
        conn.commit()
        conn.close()

        pw_user = self.bot.get_user(pw_id)

        embed = discord.Embed(
            title="自动匹配成功 | Auto Match Found",
            description=(
                f"订单 #{order_id}\n"
                f"陪玩: {pw_user.mention if pw_user else f'ID:{pw_id}'}\n"
                f"游戏: {game}\n"
                f"价格: {price} 金币"
            ),
            color=PW_GREEN,
        )
        embed.set_footer(text="等待陪玩接单 | Waiting for companion to accept")

        await interaction.response.send_message(embed=embed)

        if pw_user:
            try:
                await pw_user.send(
                    f"自动匹配订单！| Auto-matched order!\n"
                    f"订单 #{order_id} | 客户: {interaction.user.mention} | 游戏: {game} | {price} 金币\n"
                    f"使用 /pw-accept {order_id} 或 /pw-reject {order_id}"
                )
            except Exception:
                pass

    # ─────────────────────────────────────────────
    # /pw-accept
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-accept", description="接单 | Accept order")
    @app_commands.describe(order_id="订单编号 | Order ID")
    async def accept(self, interaction: discord.Interaction, order_id: int):
        uid = interaction.user.id

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM peiwans_orders WHERE order_id = ?", (order_id,))
        row = cur.fetchone()

        if row is None:
            conn.close()
            await interaction.response.send_message("订单不存在 | Order not found", ephemeral=True)
            return

        order = dict(row)

        if order["peiwans_id"] != uid:
            conn.close()
            await interaction.response.send_message("这不是你的订单 | This is not your order", ephemeral=True)
            return

        if order["status"] != "pending":
            conn.close()
            await interaction.response.send_message(
                f"订单状态为 {order['status']}，无法接单 | Order status is {order['status']}",
                ephemeral=True,
            )
            return

        cur.execute("UPDATE peiwans_orders SET status='accepted' WHERE order_id=?", (order_id,))
        cur.execute("UPDATE peiwans_profiles SET status='busy' WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"已接单 #{order_id} | Order accepted ✅")

        customer = self.bot.get_user(order["customer_id"])
        if customer:
            try:
                await customer.send(
                    f"你的订单已被接单！| Your order has been accepted!\n"
                    f"订单 #{order_id} | 陪玩: {interaction.user.mention}"
                )
            except Exception:
                pass

    # ─────────────────────────────────────────────
    # /pw-reject
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-reject", description="拒单 | Reject order")
    @app_commands.describe(order_id="订单编号 | Order ID")
    async def reject(self, interaction: discord.Interaction, order_id: int):
        uid = interaction.user.id

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM peiwans_orders WHERE order_id = ?", (order_id,))
        row = cur.fetchone()

        if row is None:
            conn.close()
            await interaction.response.send_message("订单不存在 | Order not found", ephemeral=True)
            return

        order = dict(row)

        if order["peiwans_id"] != uid:
            conn.close()
            await interaction.response.send_message("这不是你的订单 | This is not your order", ephemeral=True)
            return

        if order["status"] != "pending":
            conn.close()
            await interaction.response.send_message(
                f"订单状态为 {order['status']}，无法拒单 | Order status is {order['status']}",
                ephemeral=True,
            )
            return

        cur.execute("UPDATE peiwans_orders SET status='cancelled' WHERE order_id=?", (order_id,))
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"已拒单 #{order_id} | Order rejected ❌")

        customer = self.bot.get_user(order["customer_id"])
        if customer:
            try:
                await customer.send(
                    f"你的订单已被拒绝 | Your order was rejected\n订单 #{order_id} | by {interaction.user.mention}"
                )
            except Exception:
                pass

    # ─────────────────────────────────────────────
    # /pw-complete
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-complete", description="完成服务 | Complete order")
    @app_commands.describe(order_id="订单编号 | Order ID")
    async def complete(self, interaction: discord.Interaction, order_id: int):
        uid = interaction.user.id

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM peiwans_orders WHERE order_id = ?", (order_id,))
        row = cur.fetchone()

        if row is None:
            conn.close()
            await interaction.response.send_message("订单不存在 | Order not found", ephemeral=True)
            return

        order = dict(row)

        if order["peiwans_id"] != uid:
            conn.close()
            await interaction.response.send_message("这不是你的订单 | This is not your order", ephemeral=True)
            return

        if order["status"] != "accepted":
            conn.close()
            await interaction.response.send_message(
                f"订单状态为 {order['status']}，无法完成 | Order status is {order['status']}",
                ephemeral=True,
            )
            return

        now = datetime.utcnow().isoformat()

        cur.execute(
            "UPDATE peiwans_orders SET status='completed', completed_at=? WHERE order_id=?",
            (now, order_id),
        )

        # Record earnings
        cur.execute(
            "INSERT INTO peiwans_earnings (peiwans_id, order_id, amount, created_at) VALUES (?, ?, ?, ?)",
            (uid, order_id, order["price"], now),
        )

        # Update profile stats
        cur.execute(
            "UPDATE peiwans_profiles SET total_orders = total_orders + 1, "
            "total_earnings = total_earnings + ?, status='online' WHERE user_id = ?",
            (order["price"], uid),
        )

        conn.commit()
        conn.close()

        await interaction.response.send_message(
            f"订单 #{order_id} 已完成！| Order completed! 🎉\n收益: {order['price']} 金币"
        )

        customer = self.bot.get_user(order["customer_id"])
        if customer:
            try:
                await customer.send(
                    f"订单 #{order_id} 已完成！| Your order is complete!\n"
                    f"陪玩: {interaction.user.mention}\n"
                    f"使用 /pw-rate {order_id} <1-5> [评价] 给陪玩打分"
                )
            except Exception:
                pass

    # ─────────────────────────────────────────────
    # /pw-cancel
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-cancel", description="取消订单 | Cancel order")
    @app_commands.describe(order_id="订单编号 | Order ID")
    async def cancel(self, interaction: discord.Interaction, order_id: int):
        uid = interaction.user.id

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM peiwans_orders WHERE order_id = ?", (order_id,))
        row = cur.fetchone()

        if row is None:
            conn.close()
            await interaction.response.send_message("订单不存在 | Order not found", ephemeral=True)
            return

        order = dict(row)

        # Only customer or peiwans can cancel
        if order["customer_id"] != uid and order["peiwans_id"] != uid:
            conn.close()
            await interaction.response.send_message("这不是你的订单 | This is not your order", ephemeral=True)
            return

        if order["status"] not in ("pending", "accepted"):
            conn.close()
            await interaction.response.send_message(
                f"订单状态为 {order['status']}，无法取消 | Cannot cancel order with status {order['status']}",
                ephemeral=True,
            )
            return

        cur.execute("UPDATE peiwans_orders SET status='cancelled' WHERE order_id=?", (order_id,))

        # If peiwans was busy, set back to online
        cur.execute("SELECT status FROM peiwans_profiles WHERE user_id = ?", (order["peiwans_id"],))
        pw_row = cur.fetchone()
        if pw_row and pw_row["status"] == "busy":
            # Check if there are other accepted orders
            cur.execute(
                "SELECT COUNT(*) as cnt FROM peiwans_orders WHERE peiwans_id = ? AND status = 'accepted'",
                (order["peiwans_id"],),
            )
            other = cur.fetchone()
            if other["cnt"] == 0:
                cur.execute("UPDATE peiwans_profiles SET status='online' WHERE user_id=?", (order["peiwans_id"],))

        conn.commit()
        conn.close()

        await interaction.response.send_message(f"订单 #{order_id} 已取消 | Order cancelled")

    # ─────────────────────────────────────────────
    # /pw-rate
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-rate", description="评分 | Rate a completed order")
    @app_commands.describe(
        order_id="订单编号 | Order ID",
        rating="评分 1-5 | Rating 1-5",
        comment="评价内容（可选）| Comment (optional)",
    )
    async def rate(self, interaction: discord.Interaction, order_id: int, rating: int, comment: str = ""):
        uid = interaction.user.id

        if rating < 1 or rating > 5:
            await interaction.response.send_message("评分需在 1-5 之间 | Rating must be 1-5", ephemeral=True)
            return

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM peiwans_orders WHERE order_id = ?", (order_id,))
        row = cur.fetchone()

        if row is None:
            conn.close()
            await interaction.response.send_message("订单不存在 | Order not found", ephemeral=True)
            return

        order = dict(row)

        if order["customer_id"] != uid:
            conn.close()
            await interaction.response.send_message("只能评价自己的订单 | Can only rate your own orders", ephemeral=True)
            return

        if order["status"] != "completed":
            conn.close()
            await interaction.response.send_message(
                "只能评价已完成的订单 | Can only rate completed orders",
                ephemeral=True,
            )
            return

        # Check if already reviewed
        cur.execute("SELECT * FROM peiwans_reviews WHERE order_id = ? AND reviewer_id = ?", (order_id, uid))
        if cur.fetchone():
            conn.close()
            await interaction.response.send_message("你已经评价过此订单 | You already rated this order", ephemeral=True)
            return

        now = datetime.utcnow().isoformat()

        cur.execute(
            "INSERT INTO peiwans_reviews (order_id, reviewer_id, peiwans_id, rating, comment, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (order_id, uid, order["peiwans_id"], rating, comment, now),
        )

        # Update avg_rating
        cur.execute(
            "SELECT AVG(rating) as avg_r FROM peiwans_reviews WHERE peiwans_id = ?",
            (order["peiwans_id"],),
        )
        avg_row = cur.fetchone()
        new_avg = round(avg_row["avg_r"], 1) if avg_row["avg_r"] else rating

        cur.execute(
            "UPDATE peiwans_profiles SET avg_rating = ? WHERE user_id = ?",
            (new_avg, order["peiwans_id"]),
        )

        conn.commit()
        conn.close()

        await interaction.response.send_message(
            f"评价成功 | Rated! ⭐ {rating}/5" + (f" — {comment}" if comment else "")
        )

    # ─────────────────────────────────────────────
    # /pw-earnings
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-earnings", description="我的收益 | My earnings")
    async def earnings(self, interaction: discord.Interaction):
        uid = interaction.user.id

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT total_earnings, total_orders, avg_rating FROM peiwans_profiles WHERE user_id = ?", (uid,))
        profile = cur.fetchone()

        if profile is None:
            conn.close()
            await interaction.response.send_message(
                "请先注册陪玩 | Register first with /pw-apply",
                ephemeral=True,
            )
            return

        cur.execute(
            "SELECT * FROM peiwans_earnings WHERE peiwans_id = ? ORDER BY created_at DESC LIMIT 20",
            (uid,),
        )
        rows = cur.fetchall()
        conn.close()

        embed = discord.Embed(title="我的收益 | My Earnings", color=PW_GREEN)
        embed.add_field(name="总收益 | Total Earnings", value=f"{profile['total_earnings']} 金币", inline=True)
        embed.add_field(name="总单数 | Total Orders", value=str(profile["total_orders"]), inline=True)
        embed.add_field(name="评分 | Rating", value=f"{profile['avg_rating']:.1f} / 5.0", inline=True)

        if rows:
            recent = ""
            for r in rows[:10]:
                recent += f"#{r['order_id']}: +{r['amount']} 金币 | {r['created_at'][:10]}\n"
            embed.add_field(name="最近收益 | Recent Earnings", value=recent, inline=False)

        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────
    # /pw-orders
    # ─────────────────────────────────────────────
    @app_commands.command(name="pw-orders", description="我的订单 | My orders")
    async def orders(self, interaction: discord.Interaction):
        uid = interaction.user.id
        conn = get_db()
        cur = conn.cursor()

        # Show both as customer and as peiwans
        cur.execute(
            "SELECT * FROM peiwans_orders WHERE customer_id = ? OR peiwans_id = ? "
            "ORDER BY created_at DESC LIMIT 20",
            (uid, uid),
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            await interaction.response.send_message("暂无订单 | No orders yet", ephemeral=True)
            return

        status_map = {
            "pending": "等待接单",
            "accepted": "已接单",
            "completed": "已完成",
            "cancelled": "已取消",
        }

        embed = discord.Embed(title="我的订单 | My Orders", color=PW_GREEN)

        for row in rows:
            order = dict(row)
            is_customer = order["customer_id"] == uid
            role_label = "客户 | Customer" if is_customer else "陪玩 | Companion"
            status_label = status_map.get(order["status"], order["status"])

            value = (
                f"{role_label} | 状态: {status_label}\n"
                f"游戏: {order['game']} | {order['price']} 金币"
            )
            embed.add_field(
                name=f"#{order['order_id']} — {order.get('created_at', '')[:10]}",
                value=value,
                inline=False,
            )

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Peiwan(bot))
