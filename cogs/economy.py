"""
GMPT Bot — 经济系统 (Economy)
Coins / 每日签到 / 商店 / 成就 / 赠送 / 交易记录
"""
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
from datetime import date, datetime


# ---------- 签到连击奖励 ----------
STREAK_REWARDS = {
    1: 50, 2: 50, 3: 50, 4: 50, 5: 50, 6: 50,
    7: 200, 14: 350, 21: 500, 30: 1000,
    60: 2000, 100: 5000,
}

# ---------- 商店物品 ----------
DEFAULT_SHOP = [
    {"name": "Queue 队长通行证", "desc": "允许你在自定义对战中担任队长选人", "price": 500, "type": "pass"},
    {"name": "双倍或清零", "desc": "下一场比赛积分翻倍或清零（随机）", "price": 300, "type": "gamble"},
    {"name": "昵称炸弹", "desc": "强制修改一位选手的昵称 24 小时", "price": 1500, "type": "nickname"},
    {"name": "个人资料头衔", "desc": "在你的余额页显示自定义头衔", "price": 1000, "type": "title"},
    {"name": "自定义颜色角色", "desc": "获得一个自定义颜色的专属角色", "price": 2000, "type": "role_color"},
    {"name": "双倍积分卡", "desc": "下一场比赛积分双倍", "price": 400, "type": "doubler"},
]

# ---------- 成就列表 ----------
ACHIEVEMENTS = [
    ("首次参赛", "第一次报名比赛", 100, 0),
    ("首胜", "赢得第一场比赛", 200, 0),
    ("MVP 选手", "获得一次 MVP", 500, 0),
    ("参赛达人", "参加 5 场比赛", 300, 0),
    ("参赛狂人", "参加 10 场比赛", 600, 0),
    ("参赛怪物", "参加 25 场比赛", 1000, 0),
    ("连胜王者", "连续赢得 3 场比赛", 800, 0),
    ("金币猎人", "累计获得 5000 coins", 500, 0),
    ("金币大亨", "累计获得 15000 coins", 1000, 0),
    ("签到新人", "连续签到 7 天", 300, 0),
    ("签到铁粉", "连续签到 30 天", 1000, 0),
    ("No Life", "连续签到 30 天", 1000, 0),
    ("Touch Grass", "连续签到 100 天", 5000, 0),
    ("大慈善家", "累计赠送 1000 coins", 200, 0),
    ("购物狂", "在商店购买 5 次", 300, 0),
    ("亿万富翁", "余额达到 10000", 2000, 0),
    # 隐藏成就
    ("？？？", "隐藏成就", 500, 1),
    ("？？？", "隐藏成就", 1000, 1),
    ("？？？", "隐藏成就", 2000, 1),
]


# ---------- 工具函数 ----------

def add_coins(user_id: str, amount: int, reason: str):
    """给用户加 coins 并记录交易"""
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
    """检查并解锁成就，返回解锁的成就信息或 None"""
    conn = get_db(); cur = conn.cursor()
    # 确保成就已初始化
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
    """GMPT 经济系统"""

    def __init__(self, bot):
        self.bot = bot

    # ========== 余额 ==========
    @app_commands.command(name="gmpt-balance", description="Check your coin balance / 查看余额")
    async def balance_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        bal = get_balance(uid)

        conn = get_db(); cur = conn.cursor()
        # 签到信息
        cur.execute("SELECT streak FROM daily_checkin WHERE discord_id=?", (uid,))
        d = cur.fetchone()
        streak = d["streak"] if d else 0

        # 比赛统计
        cur.execute("SELECT COUNT(*) as cnt FROM registrations WHERE discord_id=?", (uid,))
        matches = cur.fetchone()["cnt"]

        cur.execute("""
            SELECT COUNT(*) as cnt FROM results r
            JOIN registrations reg ON reg.tournament_id = r.tournament_id AND reg.team_id = r.team_id AND r.rank=1
            WHERE reg.discord_id=?
        """, (uid,))
        wins = cur.fetchone()["cnt"]

        # 成就数
        cur.execute("SELECT COUNT(*) as cnt FROM user_achievements WHERE user_id=?", (uid,))
        ach_ct = cur.fetchone()["cnt"]

        # MVP 数
        cur.execute("SELECT COUNT(*) as cnt FROM results r WHERE r.rank=1 AND r.score_awarded>=150")
        mvp_ct = cur.fetchone()["cnt"]

        conn.close()

        embed = discord.Embed(
            title=f"{interaction.user.display_name} 的资产",
            description=f"🪙 **{bal}** GMPT Coins",
            color=discord.Color.gold(),
        )
        embed.add_field(name="连胜签到", value=f"🔥 {streak} 天", inline=True)
        embed.add_field(name="参赛场次", value=f"🎮 {matches}", inline=True)
        embed.add_field(name="胜场", value=f"🏆 {wins}", inline=True)
        embed.add_field(name="成就", value=f"⭐ {ach_ct}/{len(ACHIEVEMENTS)}", inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="GMPT Bot Economy")

        await interaction.response.send_message(embed=embed)

        # 检查金币成就
        check_achievement(uid, "余额达到")
        # 累计获得：统计正交易总额
        conn2 = get_db(); cur2 = conn2.cursor()
        cur2.execute("SELECT COALESCE(SUM(amount),0) as total FROM transactions WHERE discord_id=? AND amount>0", (uid,))
        earned = cur2.fetchone()["total"]
        conn2.close()
        if earned >= 5000:
            check_achievement(uid, "累计获得 5000")
        if earned >= 15000:
            check_achievement(uid, "累计获得 15000")

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
                f"你今天已经签到过了！连胜 {row['streak']} 天 🔥", ephemeral=True
            )

        # 计算连胜
        yesterday = date.today().fromordinal(date.today().toordinal() - 1).isoformat()
        if row and row["last_date"] == yesterday:
            new_streak = row["streak"] + 1
        else:
            new_streak = 1  # 断签重置

        # 计算奖励
        reward = 50
        for days, coins in sorted(STREAK_REWARDS.items(), reverse=True):
            if new_streak >= days:
                reward = coins
                break

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

        # 里程碑提示
        milestone = ""
        if new_streak in STREAK_REWARDS and new_streak > 1:
            milestone = f"\n🎉 签到里程碑！额外获得 {STREAK_REWARDS[new_streak]} coins！"

        await interaction.response.send_message(
            f"✅ 签到成功！+{reward} coins\n"
            f"🔥 连胜: **{new_streak}** 天{milestone}"
        )

        # 检查成就
        ach = check_achievement(uid, "连续签到")
        if ach:
            await interaction.followup.send(
                f"🏅 **成就解锁: {ach['name']}**\n{ach['desc']} (+{ach['reward']} coins)", ephemeral=True
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
            f"🎁 {interaction.user.mention} → {player.mention} 赠送了 **{amount}** coins！"
        )

        # 检查慈善家成就：累计赠送 >= 1000
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(ABS(amount)),0) as total FROM transactions WHERE discord_id=? AND reason LIKE '%赠送%'", (uid,))
        total = cur.fetchone()["total"]
        conn.close()
        if total >= 1000:
            check_achievement(uid, "累计赠送")

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

    # ========== 商店 ==========
    @app_commands.command(name="gmpt-shop", description="Open the coin shop / 积分商店")
    async def shop_cmd(self, interaction: discord.Interaction):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM shop_items")
        if cur.fetchone()["cnt"] == 0:
            for item in DEFAULT_SHOP:
                cur.execute(
                    "INSERT INTO shop_items (name, description, price, item_type) VALUES (?,?,?,?)",
                    (item["name"], item["desc"], item["price"], item["type"]),
                )
            conn.commit()

        cur.execute("SELECT id, name, description, price FROM shop_items ORDER BY price")
        items = cur.fetchall(); conn.close()

        embed = discord.Embed(
            title="GMPT Shop",
            description="使用 `/gmpt-buy <物品ID>` 购买\n\n",
            color=discord.Color.purple(),
        )
        for it in items:
            embed.add_field(
                name=f"#{it['id']} {it['name']} — 🪙 {it['price']}",
                value=it["description"],
                inline=False,
            )
        embed.set_footer(text="GMPT Bot Shop")
        await interaction.response.send_message(embed=embed)

    # ========== 购买 ==========
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

        cur.execute("UPDATE users SET score = score - ? WHERE discord_id = ?", (item["price"], uid))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (uid, -item["price"], f"购买: {item['name']}"))
        cur.execute(
            "INSERT INTO user_inventory (user_id, item_id, quantity) VALUES (?,?,1) "
            "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + 1",
            (uid, item_id),
        )
        conn.commit(); conn.close()

        await interaction.response.send_message(
            f"🛒 购买成功！**{item['name']}** — -{item['price']} coins\n"
            f"物品已存入背包，查看: `/gmpt-inventory`"
        )

        # 检查成就
        check_achievement(uid, "商店购买")

        # 购物狂：购买 >= 5 次
        conn2 = get_db(); cur2 = conn2.cursor()
        cur2.execute("SELECT COUNT(*) as cnt FROM transactions WHERE discord_id=? AND reason LIKE '%购买%'", (uid,))
        buy_cnt = cur2.fetchone()["cnt"]
        conn2.close()
        if buy_cnt >= 5:
            check_achievement(uid, "购买 5 次")

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

    # ========== 成就 ==========
    @app_commands.command(name="gmpt-achievements", description="View achievements / 成就列表")
    async def ach_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()

        # 初始化成就
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
        rows = cur.fetchall(); conn.close()

        unlocked = sum(1 for r in rows if r["unlocked"])
        lines = [f"**成就** ({unlocked}/{len(rows)} 已解锁)\n"]

        for r in rows:
            if r["hidden"] and not r["unlocked"]:
                lines.append("❓ ？？？ — 隐藏成就")
            elif r["unlocked"]:
                lines.append(f"✅ **{r['name']}** — {r['description']} (+{r['reward']})")
            else:
                lines.append(f"⬜ {r['name']} — {r['description']} (+{r['reward']})")

        await interaction.response.send_message("\n".join(lines))


async def setup(bot):
    await bot.add_cog(Economy(bot))
