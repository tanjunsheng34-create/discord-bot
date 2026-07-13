"""
GMPT Bot — 经济系统 (Economy) v2
图片+按钮式商店 / 成就 / 签到 / 赠送 / 交易 / 价格管理
"""
import io
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
from datetime import date, datetime
from PIL import Image, ImageDraw, ImageFont


# ---------- 常量 ----------
STREAK_REWARDS = {
    1: 50, 2: 50, 3: 50, 4: 50, 5: 50, 6: 50,
    7: 200, 14: 350, 21: 500, 30: 1000,
    60: 2000, 100: 5000,
}

DEFAULT_SHOP = [
    {"name": "Queue 队长通行证", "desc": "在自定义对战中担任队长选人", "price": 500, "type": "pass", "emoji": "🎫"},
    {"name": "双倍或清零", "desc": "下场积分翻倍或清零（随机）", "price": 300, "type": "gamble", "emoji": "🎲"},
    {"name": "双倍积分卡", "desc": "下一场比赛积分双倍", "price": 400, "type": "doubler", "emoji": "⬆️"},
    {"name": "个人资料头衔", "desc": "在余额页显示自定义头衔", "price": 1000, "type": "title", "emoji": "🏷️"},
    {"name": "昵称炸弹", "desc": "强制修改一位选手的昵称24h", "price": 1500, "type": "nickname", "emoji": "💣"},
    {"name": "自定义颜色角色", "desc": "获得自定义颜色的专属角色", "price": 2000, "type": "role_color", "emoji": "🎨"},
]

ACHIEVEMENTS = [
    ("首次参赛", "第一次报名比赛", 100, 0, "🏆"),
    ("首胜", "赢得第一场比赛", 200, 0, "👑"),
    ("MVP 选手", "获得一次 MVP", 500, 0, "⭐"),
    ("参赛达人", "参加 5 场比赛", 300, 0, "🎮"),
    ("参赛狂人", "参加 10 场比赛", 600, 0, "🔥"),
    ("参赛怪物", "参加 25 场比赛", 1000, 0, "💀"),
    ("连胜王者", "连续赢得 3 场比赛", 800, 0, "⚔️"),
    ("金币猎人", "累计获得 5000 coins", 500, 0, "💰"),
    ("金币大亨", "累计获得 15000 coins", 1000, 0, "💎"),
    ("签到新人", "连续签到 7 天", 300, 0, "📅"),
    ("签到铁粉", "连续签到 30 天", 1000, 0, "🗓️"),
    ("No Life", "连续签到 30 天", 1000, 0, "😈"),
    ("Touch Grass", "连续签到 100 天", 5000, 0, "🌿"),
    ("大慈善家", "累计赠送 1000 coins", 200, 0, "🤝"),
    ("购物狂", "在商店购买 5 次", 300, 0, "🛒"),
    ("亿万富翁", "余额达到 10000", 2000, 0, "💵"),
    ("？？？", "隐藏成就", 500, 1, "❓"),
    ("？？？", "隐藏成就", 1000, 1, "❓"),
    ("？？？", "隐藏成就", 2000, 1, "❓"),
]


# ---------- 图片生成 ----------

FONT_PATH_SANS = None
FONT_PATH_BOLD = None

def _find_fonts():
    """查找系统字体"""
    import os
    candidates_sans = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    candidates_bold = [
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    global FONT_PATH_SANS, FONT_PATH_BOLD
    for f in candidates_sans:
        if os.path.exists(f):
            FONT_PATH_SANS = f; break
    for f in candidates_bold:
        if os.path.exists(f):
            FONT_PATH_BOLD = f; break
    if not FONT_PATH_BOLD:
        FONT_PATH_BOLD = FONT_PATH_SANS


def _get_font(size, bold=False):
    path = FONT_PATH_BOLD if bold else FONT_PATH_SANS
    if path:
        try:
            return ImageFont.truetype(path, size)
        except:
            pass
    return ImageFont.load_default()


def generate_shop_image(items, user_balance):
    """生成商店图片 800x(160 + 每行105)"""
    row_h = 105
    header_h = 180
    footer_h = 60

    w = 800
    h = header_h + len(items) * row_h + footer_h

    img = Image.new("RGBA", (w, h), (30, 30, 40, 255))
    draw = ImageDraw.Draw(img)

    # 背景渐变装饰条
    for i in range(w):
        c = int(70 + 30 * (i / w))
        draw.line([(i, 0), (i, header_h)], fill=(c, c, c + 20, 255))

    # 标题
    title_font = _get_font(32, bold=True)
    draw.text((40, 25), "GMPT COIN SHOP", fill=(255, 215, 0), font=title_font)

    # 余额
    balance_font = _get_font(18)
    draw.text((40, 70), f"YOUR BALANCE", fill=(150, 150, 160), font=balance_font)
    coin_font = _get_font(24, bold=True)
    draw.text((40, 92), f"🪙 {user_balance} GMPT Coins", fill=(255, 215, 0), font=coin_font)

    # 提示
    hint_font = _get_font(15)
    draw.text((40, 140), "Click the buttons below to purchase", fill=(120, 120, 130), font=hint_font)

    # 分隔线
    draw.line([(40, 170), (w - 40, 170)], fill=(80, 80, 100, 255), width=1)

    # 每行商品
    name_font = _get_font(20, bold=True)
    desc_font = _get_font(14)
    price_font = _get_font(18, bold=True)
    id_font = _get_font(12)

    for idx, it in enumerate(items):
        y = header_h + idx * row_h + 10

        # 左侧色条
        draw.rectangle([(30, y), (36, y + 85)], fill=(0, 180, 255, 200))

        # ID
        draw.text((48, y + 2), f"#{it['id']}", fill=(100, 100, 110), font=id_font)

        # 名称 + emoji
        draw.text((48, y + 18), f"{it.get('emoji','')}  {it['name']}", fill=(255, 255, 255), font=name_font)

        # 描述
        draw.text((48, y + 48), it['description'], fill=(160, 160, 170), font=desc_font)

        # 价格
        price_str = f"🪙 {it['price']}"
        pb = draw.textbbox((0, 0), price_str, font=price_font)
        pw = pb[2] - pb[0]
        draw.text((w - pw - 50, y + 18), price_str, fill=(255, 215, 0), font=price_font)

        # 分隔线
        if idx < len(items) - 1:
            draw.line([(40, y + row_h), (w - 40, y + row_h)], fill=(60, 60, 75, 180), width=1)

    # 底部文字
    bot_font = _get_font(14)
    draw.text((40, h - 35), "GMPT Bot • Economy System", fill=(100, 100, 110), font=bot_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def generate_ach_image(achievement_rows, unlocked_count, total_count):
    """生成成就图片 800x(160 + 每行75)"""
    row_h = 75
    header_h = 150
    footer_h = 50

    w = 800
    h = header_h + len(achievement_rows) * row_h + footer_h

    img = Image.new("RGBA", (w, h), (30, 30, 40, 255))
    draw = ImageDraw.Draw(img)

    # 标题栏
    for i in range(w):
        c = int(70 + 30 * (i / w))
        draw.line([(i, 0), (i, header_h)], fill=(c, c, c + 20, 255))

    title_font = _get_font(32, bold=True)
    draw.text((40, 25), "ACHIEVEMENTS", fill=(0, 220, 130), font=title_font)

    count_font = _get_font(20)
    draw.text((40, 70), f"{unlocked_count} / {total_count}  UNLOCKED", fill=(200, 200, 210), font=count_font)

    # 图例
    legend_font = _get_font(14)
    draw.text((40, 110), "✅ Unlocked", fill=(0, 220, 130), font=legend_font)
    draw.text((180, 110), "⬜ Locked", fill=(130, 130, 140), font=legend_font)
    draw.text((310, 110), "❓ Hidden", fill=(90, 90, 100), font=legend_font)

    draw.line([(40, 135), (w - 40, 135)], fill=(80, 80, 100, 255), width=1)

    name_font = _get_font(17, bold=True)
    desc_font = _get_font(13)
    reward_font = _get_font(14, bold=True)

    for idx, row in enumerate(achievement_rows):
        y = header_h + idx * row_h + 8

        emoji = row.get("emoji", "❓")
        unlocked = row.get("unlocked", False)
        hidden = row.get("hidden", False) and not unlocked

        if hidden:
            draw.text((48, y + 14), "❓  ？？？", fill=(80, 80, 90), font=name_font)
            draw.text((48, y + 40), "Hidden achievement", fill=(60, 60, 70), font=desc_font)
        elif unlocked:
            name_color = (0, 220, 130)
            desc_color = (160, 180, 165)
            draw.text((48, y + 14), f"✅  {row['name']}", fill=name_color, font=name_font)
            draw.text((48, y + 40), row['description'], fill=desc_color, font=desc_font)
            reward_str = f"+{row['reward']} 🪙"
            pb = draw.textbbox((0, 0), reward_str, font=reward_font)
            pw = pb[2] - pb[0]
            draw.text((w - pw - 50, y + 14), reward_str, fill=(0, 200, 100), font=reward_font)
        else:
            draw.text((48, y + 14), f"⬜  {row['name']}", fill=(140, 140, 150), font=name_font)
            draw.text((48, y + 40), row['description'], fill=(100, 100, 110), font=desc_font)
            draw.text((w - 80, y + 14), f"+{row['reward']}", fill=(100, 100, 110), font=reward_font)

        if idx < len(achievement_rows) - 1:
            draw.line([(40, y + row_h), (w - 40, y + row_h)], fill=(55, 55, 70, 150), width=1)

    bot_font = _get_font(14)
    draw.text((40, h - 30), "GMPT Bot • Economy System", fill=(100, 100, 110), font=bot_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ---------- 交互 View ----------

class ShopView(discord.ui.View):
    def __init__(self, items, timeout=120):
        super().__init__(timeout=timeout)
        for it in items[:5]:  # 最多 5 个按钮（Discord 限制）
            btn = discord.ui.Button(
                label=f"{it['name']}",
                emoji=it.get("emoji", "🛒"),
                style=discord.ButtonStyle.primary,
                custom_id=f"shop_buy_{it['id']}",
                row=0,
            )
            self.add_item(btn)
        # 第二行放余额按钮
        self.add_item(discord.ui.Button(
            label="My Balance",
            emoji="💰",
            style=discord.ButtonStyle.secondary,
            custom_id="shop_balance",
            row=1,
        ))
        self.add_item(discord.ui.Button(
            label="Inventory",
            emoji="🎒",
            style=discord.ButtonStyle.secondary,
            custom_id="shop_inv",
            row=1,
        ))


class BuyConfirmView(discord.ui.View):
    def __init__(self, item, timeout=30):
        super().__init__(timeout=timeout)
        self.item = item
        self.confirmed = False


# ---------- 工具函数 ----------

def add_coins(user_id: str, amount: int, reason: str):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING",
        (user_id,),
    )
    cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, user_id))
    cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                 (user_id, amount, reason))
    conn.commit(); conn.close()


def get_balance(user_id: str) -> int:
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT score FROM users WHERE discord_id=?", (user_id,))
    row = cur.fetchone(); conn.close()
    return row["score"] if row else 500


def check_achievement(user_id: str, key: str):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM achievements")
    if cur.fetchone()["cnt"] == 0:
        for a in ACHIEVEMENTS:
            cur.execute("INSERT INTO achievements (name, description, reward, hidden) VALUES (?,?,?,?)",
                        (a[0], a[1], a[2], a[3]))
        conn.commit()

    cur.execute("""
        SELECT a.id, a.name, a.description, a.reward, a.hidden
        FROM achievements a
        WHERE a.description LIKE ? AND a.id NOT IN (
            SELECT achievement_id FROM user_achievements WHERE user_id=?
        )
    """, (f"%{key}%", user_id))
    a = cur.fetchone()
    if not a:
        conn.close(); return None
    cur.execute("INSERT INTO user_achievements (user_id, achievement_id) VALUES (?,?)",
                (user_id, a["id"]))
    if a["reward"] > 0:
        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (a["reward"], user_id))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (user_id, a["reward"], f"成就: {a['name']}"))
    conn.commit(); conn.close()
    return {"name": a["name"], "desc": a["description"], "reward": a["reward"], "hidden": bool(a["hidden"])}


# ---------- Cog ----------

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _find_fonts()

    # ========== 余额（图片版）==========
    @app_commands.command(name="gmpt-balance", description="Check your coin balance / 查看余额")
    async def balance_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        bal = get_balance(uid)

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT streak FROM daily_checkin WHERE discord_id=?", (uid,))
        d = cur.fetchone(); streak = d["streak"] if d else 0
        cur.execute("SELECT COUNT(*) as cnt FROM registrations WHERE discord_id=?", (uid,))
        matches = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM user_achievements WHERE user_id=?", (uid,))
        ach_ct = cur.fetchone()["cnt"]
        conn.close()

        embed = discord.Embed(
            title=f"{interaction.user.display_name} 的资产",
            description=f"🪙 **{bal}** GMPT Coins",
            color=discord.Color.gold(),
        )
        embed.add_field(name="签到连胜", value=f"🔥 {streak} 天", inline=True)
        embed.add_field(name="参赛场次", value=f"🎮 {matches}", inline=True)
        embed.add_field(name="成就", value=f"⭐ {ach_ct}/{len(ACHIEVEMENTS)}", inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await interaction.response.send_message(embed=embed)

        check_achievement(uid, "余额达到")
        conn2 = get_db(); cur2 = conn2.cursor()
        cur2.execute("SELECT COALESCE(SUM(amount),0) as total FROM transactions WHERE discord_id=? AND amount>0", (uid,))
        earned = cur2.fetchone()["total"]
        conn2.close()
        if earned >= 5000: check_achievement(uid, "累计获得 5000")
        if earned >= 15000: check_achievement(uid, "累计获得 15000")

    # ========== 每日签到 ==========
    @app_commands.command(name="gmpt-daily", description="Daily check-in for coins / 每日签到")
    async def daily_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        today = date.today().isoformat()
        conn = get_db(); cur = conn.cursor()

        cur.execute("SELECT last_date, streak FROM daily_checkin WHERE discord_id=?", (uid,))
        row = cur.fetchone()

        if row and row["last_date"] == today:
            conn.close()
            return await interaction.response.send_message(
                f"你已经签到过了！连胜 {row['streak']} 天", ephemeral=True
            )

        yesterday = date.today().fromordinal(date.today().toordinal() - 1).isoformat()
        if row and row["last_date"] == yesterday:
            new_streak = row["streak"] + 1
        else:
            new_streak = 1

        reward = 50
        for days, coins in sorted(STREAK_REWARDS.items(), reverse=True):
            if new_streak >= days:
                reward = coins; break

        cur.execute(
            "INSERT INTO daily_checkin (discord_id, last_date, streak) VALUES (?,?,?) "
            "ON CONFLICT(discord_id) DO UPDATE SET last_date=?, streak=?",
            (uid, today, new_streak, today, new_streak),
        )
        cur.execute(
            "INSERT INTO users (discord_id, username) VALUES (?,?) ON CONFLICT(discord_id) DO NOTHING",
            (uid, interaction.user.name),
        )
        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (reward, uid))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (uid, reward, f"每日签到 Day {new_streak}"))
        conn.commit(); conn.close()

        milestone = ""
        if new_streak in STREAK_REWARDS and new_streak > 1:
            milestone = f"\n签到里程碑！额外获得 {STREAK_REWARDS[new_streak]} coins！"

        await interaction.response.send_message(
            f"✅ 签到成功！+{reward} coins  🔥 连胜: **{new_streak}** 天{milestone}"
        )

        ach = check_achievement(uid, "连续签到")
        if ach:
            await interaction.followup.send(
                f"🏅 成就解锁: **{ach['name']}** — {ach['desc']} (+{ach['reward']})", ephemeral=True
            )

    # ========== 赠送 ==========
    @app_commands.command(name="gmpt-gift", description="Gift coins to another player / 赠送金币")
    @app_commands.describe(player="Receiver / 接收者", amount="Amount / 数量")
    async def gift_cmd(self, interaction: discord.Interaction, player: discord.Member, amount: int):
        if amount < 1:
            return await interaction.response.send_message("数量必须大于 0。", ephemeral=True)
        uid = str(interaction.user.id)
        tid = str(player.id)
        if uid == tid:
            return await interaction.response.send_message("不能送给自己。", ephemeral=True)

        bal = get_balance(uid)
        if bal < amount:
            return await interaction.response.send_message(f"余额不足！你有 {bal} coins。", ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE users SET score = score - ? WHERE discord_id = ?", (amount, uid))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (uid, -amount, f"赠送 {player.display_name}"))
        cur.execute(
            "INSERT INTO users (discord_id, username) VALUES (?,?) ON CONFLICT(discord_id) DO NOTHING",
            (tid, player.name),
        )
        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, tid))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (tid, amount, f"来自 {interaction.user.display_name} 的赠礼"))
        conn.commit(); conn.close()

        await interaction.response.send_message(
            f"{interaction.user.mention} → {player.mention} 赠送了 **{amount}** coins！"
        )

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(ABS(amount)),0) as total FROM transactions WHERE discord_id=? AND reason LIKE '%赠送%'", (uid,))
        total = cur.fetchone()["total"]
        conn.close()
        if total >= 1000: check_achievement(uid, "累计赠送")

    # ========== 交易记录 ==========
    @app_commands.command(name="gmpt-transactions", description="View transaction history / 交易记录")
    @app_commands.describe(count="Number of records (1-20) / 记录数")
    async def tx_cmd(self, interaction: discord.Interaction, count: int = 10):
        uid = str(interaction.user.id)
        count = min(count, 20)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT amount, reason, created_at FROM transactions WHERE discord_id=? ORDER BY id DESC LIMIT ?",
            (uid, count),
        )
        rows = cur.fetchall(); conn.close()

        if not rows:
            return await interaction.response.send_message("暂无交易记录。")

        lines = ["**交易记录**\n"]
        for r in rows:
            sign = "+" if r["amount"] >= 0 else ""
            lines.append(f"`{r['created_at'][:16]}` {sign}{r['amount']} — {r['reason']}")

        await interaction.response.send_message("\n".join(lines))

    # ========== 商店（图片+按钮）==========
    @app_commands.command(name="gmpt-shop", description="Open the coin shop / 积分商店（图片版）")
    async def shop_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        bal = get_balance(uid)

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM shop_items")
        if cur.fetchone()["cnt"] == 0:
            for item in DEFAULT_SHOP:
                cur.execute(
                    "INSERT INTO shop_items (name, description, price, item_type) VALUES (?,?,?,?)",
                    (item["name"], item["desc"], item["price"], item["type"]),
                )
            conn.commit()

        cur.execute("SELECT id, name, description, price, item_type FROM shop_items ORDER BY price")
        items = [dict(r) for r in cur.fetchall()]
        conn.close()

        # 匹配 emoji
        for it in items:
            for d in DEFAULT_SHOP:
                if d["name"] == it["name"]:
                    it["emoji"] = d["emoji"]; break
            else:
                it["emoji"] = "🛒"

        img_buf = generate_shop_image(items, bal)
        f = discord.File(img_buf, filename="shop.png")

        # 构建按钮
        view = ShopView(items=items)
        await interaction.response.send_message(file=f, view=view)

    # ========== 购买（图片+确认按钮）==========
    @app_commands.command(name="gmpt-buy", description="Buy item from shop / 购买商店物品")
    @app_commands.describe(item_id="Item ID from /gmpt-shop")
    async def buy_cmd(self, interaction: discord.Interaction, item_id: int):
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM shop_items WHERE id=?", (item_id,))
        item = cur.fetchone()
        if not item:
            conn.close(); return await interaction.response.send_message("物品不存在。", ephemeral=True)

        bal = get_balance(uid)
        if bal < item["price"]:
            conn.close(); return await interaction.response.send_message(
                f"余额不足！需要 {item['price']} coins，你有 {bal} coins。", ephemeral=True
            )

        # 确认按钮
        class ConfirmBuy(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=15)

            @discord.ui.button(label="确认购买", style=discord.ButtonStyle.success, emoji="✅")
            async def confirm(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                if str(btn_interaction.user.id) != uid:
                    return await btn_interaction.response.send_message("这不是你的购买单。", ephemeral=True)

                conn2 = get_db(); cur2 = conn2.cursor()
                bal2 = get_balance(uid)
                if bal2 < item["price"]:
                    conn2.close(); return await btn_interaction.response.send_message(
                        f"余额不足！需要 {item['price']} coins，你有 {bal2} coins。", ephemeral=True
                    )

                cur2.execute("UPDATE users SET score = score - ? WHERE discord_id = ?", (item["price"], uid))
                cur2.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                             (uid, -item["price"], f"购买: {item['name']}"))
                cur2.execute(
                    "INSERT INTO user_inventory (user_id, item_id, quantity) VALUES (?,?,1) "
                    "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + 1",
                    (uid, item_id),
                )
                conn2.commit(); conn2.close()

                for child in self.children: child.disabled = True
                await btn_interaction.response.edit_message(
                    content=f"✅ 购买成功！**{item['name']}**  -{item['price']} coins", view=self
                )

                check_achievement(uid, "商店购买")
                conn3 = get_db(); cur3 = conn3.cursor()
                cur3.execute("SELECT COUNT(*) as cnt FROM transactions WHERE discord_id=? AND reason LIKE '%购买%'", (uid,))
                if cur3.fetchone()["cnt"] >= 5:
                    check_achievement(uid, "购买 5 次")
                conn3.close()

            @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary, emoji="❌")
            async def cancel(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                if str(btn_interaction.user.id) != uid:
                    return await btn_interaction.response.send_message("这不是你的购买单。", ephemeral=True)
                for child in self.children: child.disabled = True
                await btn_interaction.response.edit_message(content="已取消。", view=self)

        conn.close()
        await interaction.response.send_message(
            f"确认购买 **{item['name']}**？\n价格: 🪙 {item['price']} | 余额: 🪙 {bal}",
            view=ConfirmBuy(),
        )

    # ========== 背包 ==========
    @app_commands.command(name="gmpt-inventory", description="View your inventory / 查看背包")
    async def inv_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            SELECT si.name, si.description, inv.quantity
            FROM user_inventory inv
            JOIN shop_items si ON si.id = inv.item_id
            WHERE inv.user_id=?
        """, (uid,))
        rows = cur.fetchall(); conn.close()

        if not rows:
            return await interaction.response.send_message("背包是空的，去 `/gmpt-shop` 逛逛吧！")

        lines = ["**背包**\n"]
        for r in rows:
            lines.append(f"📦 **{r['name']}** x{r['quantity']} — {r['description']}")
        await interaction.response.send_message("\n".join(lines))

    # ========== 成就（图片版）==========
    @app_commands.command(name="gmpt-achievements", description="View achievements / 成就列表（图片版）")
    async def ach_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()

        cur.execute("SELECT COUNT(*) as cnt FROM achievements")
        if cur.fetchone()["cnt"] == 0:
            for a in ACHIEVEMENTS:
                cur.execute("INSERT INTO achievements (name, description, reward, hidden) VALUES (?,?,?,?)",
                            (a[0], a[1], a[2], a[3]))
            conn.commit()

        cur.execute("""
            SELECT a.id, a.name, a.description, a.reward, a.hidden,
                   CASE WHEN ua.user_id IS NOT NULL THEN 1 ELSE 0 END as unlocked
            FROM achievements a
            LEFT JOIN user_achievements ua ON ua.achievement_id = a.id AND ua.user_id=?
            ORDER BY a.id
        """, (uid,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        for idx, r in enumerate(rows):
            if idx < len(ACHIEVEMENTS):
                r["emoji"] = ACHIEVEMENTS[idx][4]

        unlocked_ct = sum(1 for r in rows if r["unlocked"])
        img_buf = generate_ach_image(rows, unlocked_ct, len(rows))
        f = discord.File(img_buf, filename="achievements.png")

        # 筛选按钮：全部/已解锁/未解锁
        class AchFilter(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=60)

            @discord.ui.button(label="All", style=discord.ButtonStyle.primary, emoji="📋")
            async def all_btn(self, btn_i: discord.Interaction, btn):
                img2 = generate_ach_image(rows, unlocked_ct, len(rows))
                f2 = discord.File(img2, filename="ach.png")
                await btn_i.response.edit_message(attachments=[discord.File(img2, filename="ach.png")], view=self)

            @discord.ui.button(label="Unlocked", style=discord.ButtonStyle.success, emoji="✅")
            async def unlocked_btn(self, btn_i: discord.Interaction, btn):
                filtered = [r for r in rows if r["unlocked"]]
                img2 = generate_ach_image(filtered, len(filtered), len(rows))
                await btn_i.response.edit_message(attachments=[discord.File(img2, filename="ach.png")], view=self)

            @discord.ui.button(label="Locked", style=discord.ButtonStyle.secondary, emoji="⬜")
            async def locked_btn(self, btn_i: discord.Interaction, btn):
                filtered = [r for r in rows if not r["unlocked"]]
                img2 = generate_ach_image(filtered, unlocked_ct, len(rows))
                await btn_i.response.edit_message(attachments=[discord.File(img2, filename="ach.png")], view=self)

        await interaction.response.send_message(file=f, view=AchFilter())

    # ========== 价格管理 ==========
    @app_commands.command(name="gmpt-shop-edit", description="Edit shop item price / 修改商店价格（管理员）")
    @app_commands.describe(item_id="Item ID", new_price="New price")
    async def shop_edit_cmd(self, interaction: discord.Interaction, item_id: int, new_price: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("仅管理员可使用此命令。", ephemeral=True)

        if new_price < 1:
            return await interaction.response.send_message("价格必须大于 0。", ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM shop_items WHERE id=?", (item_id,))
        item = cur.fetchone()
        if not item:
            conn.close(); return await interaction.response.send_message("物品不存在。", ephemeral=True)

        old_price = item["price"]
        cur.execute("UPDATE shop_items SET price=? WHERE id=?", (new_price, item_id))
        conn.commit(); conn.close()

        await interaction.response.send_message(
            f"✅ **{item['name']}** 价格已更新: 🪙 {old_price} → 🪙 {new_price}"
        )


async def setup(bot):
    await bot.add_cog(Economy(bot))
