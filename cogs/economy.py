
"""
GMPT Bot — 经济系统 (Economy) v3
图片+按钮式商店 / 分页成就 / 签到 / 赠送 / 交易 / 背包使用 / 价格管理
中英文双语支持
"""
import io
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
from datetime import date, datetime
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("[Economy] Pillow not installed — image features disabled")


# ---------- 常量 ----------
STREAK_REWARDS = {
    1: 50, 2: 50, 3: 50, 4: 50, 5: 50, 6: 50,
    7: 200, 14: 350, 21: 500, 30: 1000,
    60: 2000, 100: 5000,
}

ACH_PER_PAGE = 8

DEFAULT_SHOP = [
    {"name": "Queue 队长通行证 (Captain Pass)", "desc": "在自定义对战中担任队长选人 / Become captain in custom matches", "price": 500, "type": "pass", "emoji": "🎫"},
    {"name": "双倍或清零 (Double or Nothing)", "desc": "使用后随机翻倍或清零当前余额 / Randomly double or zero your balance", "price": 300, "type": "gamble", "emoji": "🎲"},
    {"name": "双倍积分卡 (Double Points Card)", "desc": "下一场比赛积分双倍 / Next match points doubled", "price": 400, "type": "doubler", "emoji": "⬆️"},
    {"name": "个人资料头衔 (Profile Title)", "desc": "在余额页显示自定义头衔 / Display custom title on profile", "price": 1000, "type": "title", "emoji": "🏷️"},
    {"name": "昵称炸弹 (Nickname Bomb)", "desc": "强制修改一位选手的昵称24h / Force rename a player for 24h", "price": 1500, "type": "nickname", "emoji": "💣"},
    {"name": "自定义颜色角色 (Custom Color Role)", "desc": "获得自定义颜色的专属角色 / Get a custom color role", "price": 2000, "type": "role_color", "emoji": "🎨"},
    {"name": "经验加成卡 (XP Boost Card)", "desc": "下一场比赛经验值+50% / Next match +50% XP", "price": 800, "type": "xp_boost", "emoji": "📈"},
    {"name": "隐身卡 (Invisibility Card)", "desc": "24小时内排行榜隐藏你的名字 / Hide your name on leaderboard for 24h", "price": 1200, "type": "invisibility", "emoji": "🫥"},
    {"name": "改名卡 (Name Change Card)", "desc": "修改一次你的游戏昵称 / Change your in-game nickname once", "price": 2500, "type": "name_change", "emoji": "✏️"},
    {"name": "全服广播喇叭 (Server Broadcast)", "desc": "向全服发送一条醒目公告 / Send a server-wide announcement", "price": 5000, "type": "broadcast", "emoji": "📢"},
    {"name": "比赛复活卡 (Match Revive Card)", "desc": "淘汰后可复活一次继续比赛 / Revive once after elimination", "price": 3000, "type": "revive", "emoji": "💚"},
    {"name": "至尊传说称号 (Legendary Title)", "desc": "专属传说级称号，全服广播 / Legendary title with server broadcast", "price": 100000, "type": "legendary_title", "emoji": "👑"},
]

ACHIEVEMENTS = [
    ("首次参赛 (First Match)", "第一次报名比赛 / Registered for first match", 100, 0, "🏆"),
    ("首胜 (First Win)", "赢得第一场比赛 / Won first match", 200, 0, "👑"),
    ("MVP 选手 (MVP Player)", "获得一次 MVP / Earned one MVP", 500, 0, "⭐"),
    ("参赛达人 (Match Enthusiast)", "参加 5 场比赛 / Played 5 matches", 300, 0, "🎮"),
    ("参赛狂人 (Match Maniac)", "参加 10 场比赛 / Played 10 matches", 600, 0, "🔥"),
    ("参赛怪物 (Match Monster)", "参加 25 场比赛 / Played 25 matches", 1000, 0, "💀"),
    ("参赛传奇 (Match Legend)", "参加 50 场比赛 / Played 50 matches", 1500, 0, "🏟️"),
    ("百战老兵 (Centurion)", "参加 100 场比赛 / Played 100 matches", 3000, 0, "⚡"),
    ("连胜王者 (Win Streak King)", "连续赢得 3 场比赛 / Won 3 matches in a row", 800, 0, "⚔️"),
    ("金币猎人 (Coin Hunter)", "累计获得 5000 coins / Earned 5000 coins total", 500, 0, "💰"),
    ("金币大亨 (Coin Tycoon)", "累计获得 15000 coins / Earned 15000 coins total", 1000, 0, "💎"),
    ("签到新人 (Check-in Rookie)", "连续签到 7 天 / 7-day check-in streak", 300, 0, "📅"),
    ("签到铁粉 (Check-in Fan)", "连续签到 30 天 / 30-day check-in streak", 1000, 0, "🗓️"),
    ("No Life", "连续签到 60 天 / 60-day check-in streak", 2000, 0, "😈"),
    ("Touch Grass", "连续签到 100 天 / 100-day check-in streak", 5000, 0, "🌿"),
    ("大慈善家 (Philanthropist)", "累计赠送 1000 coins / Gifted 1000 coins total", 200, 0, "🤝"),
    ("超级慈善家 (Super Philanthropist)", "累计赠送 5000 coins / Gifted 5000 coins total", 800, 0, "💝"),
    ("购物狂 (Shopaholic)", "在商店购买 5 次 / Purchased 5 times from shop", 300, 0, "🛒"),
    ("亿万富翁 (Billionaire)", "余额达到 10000 coins / Balance reached 10000", 2000, 0, "💵"),
    ("物品达人 (Item User)", "使用物品 10 次 / Used items 10 times", 500, 0, "🎒"),
    ("物品大师 (Item Master)", "使用物品 50 次 / Used items 50 times", 1500, 0, "🧰"),
    ("常胜将军 (Win Rate Master)", "胜率 >70%（至少 10 场）/ Win rate >70% (min 10 games)", 2000, 0, "🎯"),
    ("杀戮机器 (Killing Machine)", "单场最高击杀 ≥20 / Highest kills in one match ≥20", 1500, 0, "💀"),
    ("全成就解锁 (Completionist)", "解锁所有非隐藏成就 / Unlocked all non-hidden achievements", 10000, 0, "🌟"),
    ("？？？", "隐藏成就 / Hidden achievement", 800, 1, "❓"),
    ("？？？", "隐藏成就 / Hidden achievement", 1500, 1, "❓"),
    ("？？？", "隐藏成就 / Hidden achievement", 2500, 1, "❓"),
    ("？？？", "隐藏成就 / Hidden achievement", 4000, 1, "❓"),
    ("？？？", "隐藏成就 / Hidden achievement", 6000, 1, "❓"),
    ("？？？", "隐藏成就 / Hidden achievement", 10000, 1, "❓"),
]


# ---------- 图片生成 ----------

FONT_PATH_SANS = None
FONT_PATH_BOLD = None

def _find_fonts():
    """查找系统字体"""
    if not PIL_AVAILABLE:
        return
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
    if not PIL_AVAILABLE:
        return None
    path = FONT_PATH_BOLD if bold else FONT_PATH_SANS
    if path:
        try:
            return ImageFont.truetype(path, size)
        except:
            pass
    return ImageFont.load_default()


def generate_shop_image(items, user_balance):
    """生成商店图片，大卡片布局"""
    if not PIL_AVAILABLE:
        return None
    row_h = 110
    header_h = 210
    footer_h = 60

    w = 800
    h = header_h + len(items) * row_h + footer_h

    img = Image.new("RGBA", (w, h), (22, 22, 32, 255))
    draw = ImageDraw.Draw(img)

    # 背景渐变装饰条
    for i in range(w):
        c = int(50 + 40 * (i / w))
        draw.line([(i, 0), (i, header_h)], fill=(c, c, c + 25, 255))

    # 标题
    title_font = _get_font(30, bold=True)
    draw.text((40, 25), "GMPT COIN SHOP  /  积分商店", fill=(255, 215, 0), font=title_font)

    # 余额
    balance_font = _get_font(16)
    draw.text((40, 70), "YOUR BALANCE / 余额", fill=(150, 150, 160), font=balance_font)
    coin_font = _get_font(24, bold=True)
    draw.text((40, 93), f"🪙 {user_balance} GMPT Coins", fill=(255, 215, 0), font=coin_font)

    # 提示
    hint_font = _get_font(14)
    draw.text((40, 140), "Click buttons below to purchase / 点击下方按钮购买", fill=(120, 120, 130), font=hint_font)

    # 分隔线
    draw.line([(40, 180), (w - 40, 180)], fill=(80, 80, 100, 255), width=1)

    # 每行商品（大卡片）
    name_font = _get_font(18, bold=True)
    desc_font = _get_font(13)
    price_font = _get_font(17, bold=True)
    id_font = _get_font(11)

    for idx, it in enumerate(items):
        y = header_h + idx * row_h

        # 行背景交替
        if idx % 2 == 0:
            draw.rectangle([(0, y), (w, y + row_h)], fill=(30, 30, 42, 60))

        # 左侧色条
        if it['price'] >= 100000:
            bar_color = (255, 215, 0, 220)
        elif it['price'] >= 2000:
            bar_color = (180, 100, 255, 200)
        else:
            bar_color = (0, 180, 255, 200)
        draw.rectangle([(30, y + 10), (38, y + row_h - 10)], fill=bar_color)

        # ID
        draw.text((52, y + 10), f"#{it['id']}", fill=(100, 100, 110), font=id_font)

        # 名称 + emoji
        draw.text((52, y + 28), f"{it.get('emoji','')}  {it['name']}", fill=(255, 255, 255), font=name_font)

        # 描述
        draw.text((52, y + 56), it['description'], fill=(160, 160, 170), font=desc_font)

        # 价格徽章
        price_str = f"🪙 {it['price']}"
        pb = draw.textbbox((0, 0), price_str, font=price_font)
        pw = pb[2] - pb[0]
        badge_x = w - pw - 60
        draw.rounded_rectangle([badge_x - 6, y + 20, badge_x + pw + 6, y + 52], radius=6, fill=(50, 50, 60, 220))
        draw.text((badge_x, y + 24), price_str, fill=(255, 215, 0), font=price_font)

        if idx < len(items) - 1:
            draw.line([(40, y + row_h), (w - 40, y + row_h)], fill=(55, 55, 70, 100), width=1)

    bot_font = _get_font(13)
    draw.text((40, h - 35), "GMPT Bot  •  Economy System", fill=(100, 100, 110), font=bot_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def generate_ach_image(achievement_rows, unlocked_count, total_count, page=None, total_pages=None):
    """生成成就图片，大卡片布局，支持分页"""
    if not PIL_AVAILABLE:
        return None
    row_h = 100
    header_h = 185
    footer_h = 50

    w = 800
    h = header_h + len(achievement_rows) * row_h + footer_h

    img = Image.new("RGBA", (w, h), (22, 22, 32, 255))
    draw = ImageDraw.Draw(img)

    # 顶部渐变标题栏
    for i in range(w):
        c = int(50 + 40 * (i / w))
        draw.line([(i, 0), (i, header_h)], fill=(c, c, c + 25, 255))

    title_font = _get_font(30, bold=True)
    draw.text((40, 25), "ACHIEVEMENTS  /  成就", fill=(0, 230, 140), font=title_font)

    # 进度条背景
    bar_x, bar_y, bar_w, bar_h_val = 40, 72, w - 80, 16
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h_val], radius=8, fill=(50, 50, 60, 255))
    if total_count > 0:
        fill_w = int(bar_w * unlocked_count / total_count)
        if fill_w > 0:
            draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h_val], radius=8, fill=(0, 200, 120, 255))

    count_font = _get_font(17)
    draw.text((40, 96), f"{unlocked_count} / {total_count}  UNLOCKED", fill=(200, 200, 210), font=count_font)

    # 图例
    legend_font = _get_font(14)
    draw.text((40, 130), "✅ Unlocked / 已解锁", fill=(0, 220, 130), font=legend_font)
    draw.text((200, 130), "⬜ Locked / 未解锁", fill=(130, 130, 140), font=legend_font)
    draw.text((360, 130), "❓ Hidden / 隐藏", fill=(90, 90, 100), font=legend_font)

    draw.line([(40, 158), (w - 40, 158)], fill=(80, 80, 100, 255), width=1)

    # 成就条目（大卡片）
    name_font = _get_font(18, bold=True)
    desc_font = _get_font(13)
    reward_font = _get_font(15, bold=True)

    for idx, row in enumerate(achievement_rows):
        y = header_h + idx * row_h

        if idx % 2 == 0:
            draw.rectangle([(0, y), (w, y + row_h)], fill=(30, 30, 42, 60))

        emoji = row.get("emoji", "❓")
        unlocked = row.get("unlocked", False)
        hidden = row.get("hidden", False) and not unlocked

        if hidden:
            draw.text((52, y + 18), "❓  ？？？", fill=(80, 80, 90), font=name_font)
            draw.text((52, y + 48), "Hidden achievement / 隐藏成就", fill=(60, 60, 70), font=desc_font)
        elif unlocked:
            draw.text((52, y + 18), f"✅  {row['name']}", fill=(0, 220, 130), font=name_font)
            draw.text((52, y + 48), row['description'], fill=(180, 190, 180), font=desc_font)
            reward_str = f"+{row['reward']} 🪙"
            pb = draw.textbbox((0, 0), reward_str, font=reward_font)
            pw = pb[2] - pb[0]
            badge_x = w - pw - 60
            draw.rounded_rectangle([badge_x - 6, y + 12, badge_x + pw + 6, y + 42], radius=6, fill=(0, 160, 80, 200))
            draw.text((badge_x, y + 16), reward_str, fill=(255, 255, 255), font=reward_font)
        else:
            draw.text((52, y + 18), f"⬜  {row['name']}", fill=(140, 140, 150), font=name_font)
            draw.text((52, y + 48), row['description'], fill=(100, 100, 110), font=desc_font)
            draw.text((w - 90, y + 18), f"+{row['reward']}", fill=(100, 100, 110), font=reward_font)

        if idx < len(achievement_rows) - 1:
            draw.line([(40, y + row_h), (w - 40, y + row_h)], fill=(55, 55, 70, 100), width=1)

    bot_font = _get_font(13)
    footer_text = "GMPT Bot  •  Economy System"
    if page is not None and total_pages is not None:
        footer_text += f"     |     Page {page}/{total_pages}"
    draw.text((40, h - 30), footer_text, fill=(100, 100, 110), font=bot_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ---------- 交互 View ----------

class ShopView(discord.ui.View):
    def __init__(self, items, user_id, timeout=120):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        # 最多 12 个购买按钮，分布在三行（每行 4 个）
        for idx, it in enumerate(items[:12]):
            r = idx // 4  # 0,1,2
            btn = discord.ui.Button(
                label=f"{it['name'][:12]}",
                emoji=it.get("emoji", "🛒"),
                style=discord.ButtonStyle.primary,
                custom_id=f"shop_buy_{it['id']}",
                row=r,
            )
            btn.callback = self.make_buy_callback(it['id'])
            self.add_item(btn)

    @discord.ui.button(label="Balance", emoji="💰", style=discord.ButtonStyle.secondary, row=3)
    async def balance_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("This is not your shop. / 这不是你的商店页面。", ephemeral=True)
        bal = get_balance(str(interaction.user.id))
        await interaction.response.send_message(f"🪙 Balance / 余额: **{bal}** GMPT Coins", ephemeral=True)

    @discord.ui.button(label="Inventory", emoji="🎒", style=discord.ButtonStyle.secondary, row=3)
    async def inv_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("This is not your shop. / 这不是你的商店页面。", ephemeral=True)
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            SELECT si.name, inv.quantity
            FROM user_inventory inv
            JOIN shop_items si ON si.id = inv.item_id
            WHERE inv.user_id=?
        """, (uid,))
        rows = cur.fetchall(); conn.close()
        if not rows:
            return await interaction.response.send_message("Backpack is empty. / 背包是空的。", ephemeral=True)
        lines = [f"📦 **{r['name']}** x{r['quantity']}" for r in rows]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    def make_buy_callback(self, item_id):
        async def callback(interaction: discord.Interaction):
            if str(interaction.user.id) != self.user_id:
                return await interaction.response.send_message("This is not your shop. / 这不是你的商店页面。", ephemeral=True)
            await buy_item(interaction, str(interaction.user.id), item_id)
        return callback

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class AchFilter(discord.ui.View):
    """成就查看器：支持全部/已解锁/未解锁筛选 + 分页翻页"""
    def __init__(self, all_rows, unlocked_ct, total_ct, user_id, per_page=ACH_PER_PAGE, timeout=120):
        super().__init__(timeout=timeout)
        self.all_rows = all_rows
        self.unlocked_ct = unlocked_ct
        self.total_ct = total_ct
        self.user_id = user_id
        self.per_page = per_page
        self.current_filter = "all"  # all / unlocked / locked
        self.current_page = 0
        self._update_button_states()

    def _get_filtered_rows(self):
        if self.current_filter == "unlocked":
            return [r for r in self.all_rows if r["unlocked"]]
        elif self.current_filter == "locked":
            return [r for r in self.all_rows if not r["unlocked"]]
        return self.all_rows

    def _get_page_slice(self):
        filtered = self._get_filtered_rows()
        start = self.current_page * self.per_page
        end = start + self.per_page
        return filtered[start:end], len(filtered)

    def _update_button_states(self):
        _, total_filtered = self._get_page_slice()
        total_pages = max(1, (total_filtered + self.per_page - 1) // self.per_page)
        # 更新翻页按钮状态
        for child in self.children:
            if child.custom_id == "ach_prev":
                child.disabled = (self.current_page == 0)
            elif child.custom_id == "ach_next":
                child.disabled = (self.current_page >= total_pages - 1)

    async def _render_and_update(self, interaction: discord.Interaction):
        page_rows, total_filtered = self._get_page_slice()
        total_pages = max(1, (total_filtered + self.per_page - 1) // self.per_page)
        filtered_unlocked = sum(1 for r in page_rows if r["unlocked"])

        self._update_button_states()

        img_buf = generate_ach_image(
            page_rows,
            self.unlocked_ct if self.current_filter != "unlocked" else filtered_unlocked,
            self.total_ct,
            page=self.current_page + 1,
            total_pages=total_pages,
        )
        await interaction.response.edit_message(
            attachments=[discord.File(img_buf, filename="ach.png")],
            view=self,
        )

    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.secondary, custom_id="ach_prev", row=0)
    async def prev_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("This is not your page. / 这不是你的页面。", ephemeral=True)
        self.current_page -= 1
        await self._render_and_update(interaction)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.secondary, custom_id="ach_next", row=0)
    async def next_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("This is not your page. / 这不是你的页面。", ephemeral=True)
        self.current_page += 1
        await self._render_and_update(interaction)

    @discord.ui.button(label="All", style=discord.ButtonStyle.primary, emoji="📋", row=1)
    async def all_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("This is not your page. / 这不是你的页面。", ephemeral=True)
        self.current_filter = "all"
        self.current_page = 0
        await self._render_and_update(interaction)

    @discord.ui.button(label="Unlocked", style=discord.ButtonStyle.success, emoji="✅", row=1)
    async def unlocked_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("This is not your page. / 这不是你的页面。", ephemeral=True)
        self.current_filter = "unlocked"
        self.current_page = 0
        await self._render_and_update(interaction)

    @discord.ui.button(label="Locked", style=discord.ButtonStyle.secondary, emoji="⬜", row=1)
    async def locked_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("This is not your page. / 这不是你的页面。", ephemeral=True)
        self.current_filter = "locked"
        self.current_page = 0
        await self._render_and_update(interaction)


# ---------- 购买逻辑 ----------
async def buy_item(interaction: discord.Interaction, uid: str, item_id: int):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM shop_items WHERE id=?", (item_id,))
    item = cur.fetchone()
    if not item:
        conn.close(); return await interaction.response.send_message(
            "Item not found. / 物品不存在。", ephemeral=True
        )

    bal = get_balance(uid)
    if bal < item["price"]:
        conn.close(); return await interaction.response.send_message(
            f"Insufficient balance! Need {item['price']} coins, you have {bal}. / 余额不足！需要 {item['price']} coins，你有 {bal} coins。",
            ephemeral=True,
        )
    conn.close()

    class ConfirmBuy(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=15)

        @discord.ui.button(label="Confirm / 确认购买", style=discord.ButtonStyle.success, emoji="✅")
        async def confirm(self, btn_i: discord.Interaction, button):
            if str(btn_i.user.id) != uid:
                return await btn_i.response.send_message(
                    "This is not your order. / 这不是你的购买单。", ephemeral=True
                )

            conn2 = get_db(); cur2 = conn2.cursor()
            bal2 = get_balance(uid)
            if bal2 < item["price"]:
                conn2.close(); return await btn_i.response.send_message(
                    f"Insufficient balance! {bal2} coins. / 余额不足！{bal2} coins。", ephemeral=True
                )

            cur2.execute("UPDATE users SET score = score - ? WHERE discord_id = ?", (item["price"], uid))
            cur2.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                         (uid, -item["price"], f"Purchase: {item['name']} / 购买: {item['name']}"))
            cur2.execute(
                "INSERT INTO user_inventory (user_id, item_id, quantity) VALUES (?,?,1) "
                "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + 1",
                (uid, item_id),
            )
            conn2.commit(); conn2.close()

            for child in self.children: child.disabled = True
            await btn_i.response.edit_message(
                content=f"✅ Purchased! / 购买成功！**{item['name']}**  -{item['price']} coins", view=self
            )

            check_achievement(uid, "在商店购买")
            conn3 = get_db(); cur3 = conn3.cursor()
            cur3.execute("SELECT COUNT(*) as cnt FROM transactions WHERE discord_id=? AND (reason LIKE '%Purchase%' OR reason LIKE '%购买%')", (uid,))
            if cur3.fetchone()["cnt"] >= 5:
                check_achievement(uid, "购买 5 次")
            conn3.close()

        @discord.ui.button(label="Cancel / 取消", style=discord.ButtonStyle.secondary, emoji="❌")
        async def cancel(self, btn_i: discord.Interaction, button):
            if str(btn_i.user.id) != uid:
                return await btn_i.response.send_message(
                    "This is not your order. / 这不是你的购买单。", ephemeral=True
                )
            for child in self.children: child.disabled = True
            await btn_i.response.edit_message(content="Cancelled. / 已取消。", view=self)

    await interaction.response.send_message(
        f"Confirm purchase / 确认购买 **{item['name']}**？\n"
        f"Price / 价格: 🪙 {item['price']} | Balance / 余额: 🪙 {bal}",
        view=ConfirmBuy(),
    )


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
                     (user_id, a["reward"], f"Achievement: {a['name']} / 成就: {a['name']}"))
    conn.commit()

    # 检查全成就解锁
    _check_completionist(cur, user_id, a["id"])

    conn.close()
    return {"name": a["name"], "desc": a["description"], "reward": a["reward"], "hidden": bool(a["hidden"])}


def _check_completionist(cur, user_id: str, just_unlocked_id: int):
    """检查是否解锁了全成就（排除隐藏成就和全成就本身）"""
    # 先找出"全成就解锁"这个成就的 ID
    cur.execute("SELECT id FROM achievements WHERE description LIKE '%Unlocked all non-hidden achievements%'")
    comp_row = cur.fetchone()
    if not comp_row:
        return
    completionist_id = comp_row["id"]
    if just_unlocked_id == completionist_id:
        return  # 刚解锁的就是全成就本身，跳过

    # 检查是否已经拿到全成就
    cur.execute("SELECT COUNT(*) as cnt FROM user_achievements WHERE user_id=? AND achievement_id=?",
                (user_id, completionist_id))
    if cur.fetchone()["cnt"] > 0:
        return

    # 统计所有非隐藏成就（排除全成就本身）
    cur.execute("SELECT COUNT(*) as cnt FROM achievements WHERE hidden=0 AND id!=?", (completionist_id,))
    total_non_hidden = cur.fetchone()["cnt"]
    cur.execute(
        "SELECT COUNT(*) as cnt FROM user_achievements ua "
        "JOIN achievements a ON a.id = ua.achievement_id "
        "WHERE ua.user_id=? AND a.hidden=0 AND a.id!=?",
        (user_id, completionist_id),
    )
    unlocked_non_hidden = cur.fetchone()["cnt"]

    if unlocked_non_hidden >= total_non_hidden:
        cur.execute("INSERT INTO user_achievements (user_id, achievement_id) VALUES (?,?)",
                    (user_id, completionist_id))
        cur.execute("SELECT reward FROM achievements WHERE id=?", (completionist_id,))
        reward = cur.fetchone()["reward"]
        if reward > 0:
            cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (reward, user_id))
            cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                        (user_id, reward, "Achievement: Completionist / 成就: 全成就解锁"))
        conn = cur.connection  # need to commit on the outer connection
        # commit will be done by caller


# ---------- Cog ----------

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _find_fonts()

    # ========== 余额 ==========
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
            title=f"{interaction.user.display_name}'s Assets / 资产",
            description=f"🪙 **{bal}** GMPT Coins",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Streak / 签到连胜", value=f"🔥 {streak} days", inline=True)
        embed.add_field(name="Matches / 参赛场次", value=f"🎮 {matches}", inline=True)
        embed.add_field(name="Achievements / 成就", value=f"⭐ {ach_ct}/{len(ACHIEVEMENTS)}", inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await interaction.response.send_message(embed=embed)

        check_achievement(uid, "余额达到")
        conn2 = get_db(); cur2 = conn2.cursor()
        cur2.execute("SELECT COALESCE(SUM(amount),0) as total FROM transactions WHERE discord_id=? AND amount>0", (uid,))
        earned = cur2.fetchone()["total"]
        conn2.close()
        if earned >= 5000: check_achievement(uid, "累计获得 5000")
        if earned >= 15000: check_achievement(uid, "累计获得 15000")

    # ========== 已报名玩家 ==========
    @app_commands.command(name="gmpt-allplayers", description="List all registered players / 列出所有已报名玩家")
    async def players_cmd(self, interaction: discord.Interaction):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT DISTINCT r.discord_id, u.username FROM registrations r LEFT JOIN users u ON u.discord_id = r.discord_id ORDER BY u.username")
        rows = cur.fetchall(); conn.close()

        if not rows:
            return await interaction.response.send_message("暂无已报名玩家 / No registered players")

        lines = []
        for i, row in enumerate(rows, 1):
            name = row["username"] if row["username"] else row["discord_id"]
            lines.append(f"{i}. {name}")

        await interaction.response.send_message("\n".join(lines))

    # ========== 每日签到 ==========
    @app_commands.command(name="gmpt-daily", description="Daily check-in for coins / 每日签到")
    async def daily_cmd(self, interaction: discord.Interaction):
        # 必须进入语音频道才能领取
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                "You must join a voice channel first to claim daily coins! / "
                "请先加入语音频道才能领取每日签到金币！",
                ephemeral=True,
            )

        uid = str(interaction.user.id)
        today = date.today().isoformat()
        conn = get_db(); cur = conn.cursor()

        cur.execute("SELECT last_date, streak FROM daily_checkin WHERE discord_id=?", (uid,))
        row = cur.fetchone()

        if row and row["last_date"] == today:
            conn.close()
            return await interaction.response.send_message(
                f"Already checked in! Streak: {row['streak']} days / 你已经签到过了！连胜 {row['streak']} 天",
                ephemeral=True,
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
                     (uid, reward, f"Daily Check-in Day {new_streak} / 每日签到 Day {new_streak}"))
        conn.commit(); conn.close()

        milestone = ""
        if new_streak in STREAK_REWARDS and new_streak > 1:
            milestone = f"\n🎉 Milestone bonus! / 签到里程碑！额外获得 {STREAK_REWARDS[new_streak]} coins！"

        await interaction.response.send_message(
            f"✅ Check-in! / 签到成功！ +{reward} coins  🔥 Streak / 连胜: **{new_streak}** days{milestone}"
        )

        ach = check_achievement(uid, "连续签到")
        if ach:
            await interaction.followup.send(
                f"🏅 Achievement unlocked / 成就解锁: **{ach['name']}** — {ach['desc']} (+{ach['reward']})",
                ephemeral=True,
            )

    # ========== 赠送 ==========
    @app_commands.command(name="gmpt-gift", description="Gift coins to another player / 赠送金币")
    @app_commands.describe(player="Receiver / 接收者", amount="Amount / 数量")
    async def gift_cmd(self, interaction: discord.Interaction, player: discord.Member, amount: int):
        if amount < 1:
            return await interaction.response.send_message(
                "Amount must be > 0. / 数量必须大于 0。", ephemeral=True
            )
        uid = str(interaction.user.id)
        tid = str(player.id)
        if uid == tid:
            return await interaction.response.send_message(
                "Cannot gift yourself. / 不能送给自己。", ephemeral=True
            )

        bal = get_balance(uid)
        if bal < amount:
            return await interaction.response.send_message(
                f"Insufficient balance! You have {bal} coins. / 余额不足！你有 {bal} coins。", ephemeral=True
            )

        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE users SET score = score - ? WHERE discord_id = ?", (amount, uid))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (uid, -amount, f"Gift to {player.display_name} / 赠送 {player.display_name}"))
        cur.execute(
            "INSERT INTO users (discord_id, username) VALUES (?,?) ON CONFLICT(discord_id) DO NOTHING",
            (tid, player.name),
        )
        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, tid))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (tid, amount, f"Gift from {interaction.user.display_name} / 来自 {interaction.user.display_name} 的赠礼"))
        conn.commit(); conn.close()

        await interaction.response.send_message(
            f"{interaction.user.mention} → {player.mention} gifted **{amount}** coins! / 赠送了 **{amount}** coins！"
        )

        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(ABS(amount)),0) as total FROM transactions "
            "WHERE discord_id=? AND (reason LIKE '%Gift to%' OR reason LIKE '%赠送%')",
            (uid,),
        )
        total = cur.fetchone()["total"]
        conn.close()
        if total >= 1000: check_achievement(uid, "累计赠送 1000")
        if total >= 5000: check_achievement(uid, "累计赠送 5000")

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
            return await interaction.response.send_message(
                "No transactions yet. / 暂无交易记录。"
            )

        lines = ["**Transactions / 交易记录**\n"]
        for r in rows:
            sign = "+" if r["amount"] >= 0 else ""
            lines.append(f"`{r['created_at'][:16]}` {sign}{r['amount']} — {r['reason']}")

        await interaction.response.send_message("\n".join(lines))

    # ========== 商店 ==========
    @app_commands.command(name="gmpt-shop", description="Open the coin shop / 积分商店")
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

        for it in items:
            for d in DEFAULT_SHOP:
                if d["name"] == it["name"]:
                    it["emoji"] = d["emoji"]; break
            else:
                it["emoji"] = "🛒"

        img_buf = generate_shop_image(items, bal)
        if img_buf is None:
            embed = discord.Embed(title="🛒 GMPT COIN SHOP / 积分商店", color=0xFFD700)
            embed.add_field(name="Balance / 余额", value=f"🪙 {bal} GMPT Coins", inline=False)
            embed.add_field(name="Items / 商品", value="\n".join(
                f"**#{it['id']}** {it.get('emoji','🛒')} {it['name']} — 🪙 {it['price']}\n_{it['description']}_"
                for it in items
            ), inline=False)
            embed.set_footer(text="GMPT Bot • Economy System")
            view = ShopView(items=items, user_id=uid)
            return await interaction.response.send_message(embed=embed, view=view)

        f = discord.File(img_buf, filename="shop.png")
        view = ShopView(items=items, user_id=uid)
        await interaction.response.send_message(file=f, view=view)

    # ========== 购买 ==========
    @app_commands.command(name="gmpt-buy", description="Buy item from shop / 购买商店物品")
    @app_commands.describe(item_id="Item ID from /gmpt-shop")
    async def buy_cmd(self, interaction: discord.Interaction, item_id: int):
        await buy_item(interaction, str(interaction.user.id), item_id)

    # ========== 背包 ==========
    @app_commands.command(name="gmpt-inventory", description="View your inventory / 查看背包")
    async def inv_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            SELECT inv.item_id, si.name, si.description, si.item_type, inv.quantity
            FROM user_inventory inv
            JOIN shop_items si ON si.id = inv.item_id
            WHERE inv.user_id=?
        """, (uid,))
        rows = cur.fetchall(); conn.close()

        if not rows:
            return await interaction.response.send_message(
                "Backpack is empty. Visit `/gmpt-shop`! / 背包是空的，去 `/gmpt-shop` 逛逛吧！"
            )

        lines = ["**Backpack / 背包**\n"]
        for r in rows:
            lines.append(f"📦 `#{r['item_id']}` **{r['name']}** x{r['quantity']} — {r['description']}")
        lines.append("\n💡 Use `/gmpt-use <item_id>` to use an item / 使用 `/gmpt-use <物品ID>` 使用物品")
        await interaction.response.send_message("\n".join(lines))

    # ========== 背包使用 ==========
    @app_commands.command(name="gmpt-use", description="Use an item from inventory / 使用背包物品")
    @app_commands.describe(item_id="Item ID from /gmpt-inventory / 物品ID")
    async def use_cmd(self, interaction: discord.Interaction, item_id: int):
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()

        cur.execute("""
            SELECT inv.quantity, si.name, si.item_type, si.description
            FROM user_inventory inv
            JOIN shop_items si ON si.id = inv.item_id
            WHERE inv.user_id=? AND inv.item_id=?
        """, (uid, item_id))
        row = cur.fetchone()

        if not row:
            conn.close()
            return await interaction.response.send_message(
                "You don't have this item. / 你没有这个物品。", ephemeral=True
            )

        qty = row["quantity"]
        item_type = row["item_type"]
        item_name = row["name"]

        # 扣减数量
        if qty <= 1:
            cur.execute("DELETE FROM user_inventory WHERE user_id=? AND item_id=?", (uid, item_id))
        else:
            cur.execute("UPDATE user_inventory SET quantity = quantity - 1 WHERE user_id=? AND item_id=?",
                        (uid, item_id))

        # 记录使用
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (uid, 0, f"Used item: {item_name} / 使用物品: {item_name}"))
        conn.commit()

        # 执行效果
        effect_msg = ""
        if item_type == "doubler":
            effect_msg = (
                "✅ **Double Points Activated! / 双倍积分已激活！**\n"
                "Your next match will earn **2x points**. / 下一场比赛积分**翻倍**。"
            )
        elif item_type == "gamble":
            bal = get_balance(uid)
            if random.random() < 0.5:
                # 翻倍
                cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (bal, uid))
                cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                            (uid, bal, f"Gamble win (x2) / 赌博翻倍: {item_name}"))
                conn.commit()
                effect_msg = (
                    f"🎉 **You won! / 你赢了！**\n"
                    f"Balance doubled: 🪙 {bal} → 🪙 **{bal * 2}** / 余额翻倍！"
                )
            else:
                cur.execute("UPDATE users SET score = 0 WHERE discord_id = ?", (uid,))
                cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                            (uid, -bal, f"Gamble loss / 赌博清零: {item_name}"))
                conn.commit()
                effect_msg = (
                    f"💀 **You lost! / 你输了！**\n"
                    f"Balance wiped: 🪙 {bal} → 🪙 **0** / 余额清零！"
                )
        elif item_type == "title":
            effect_msg = (
                "✅ **Title Equipped! / 头衔已装备！**\n"
                "Your custom title will appear on your profile. / 自定义头衔将显示在你的个人资料页。"
            )
        elif item_type == "nickname":
            effect_msg = (
                "✅ **Nickname Bomb Ready! / 昵称炸弹已就绪！**\n"
                "Use `/gmpt-nickname @player <new_name>` to rename someone. / 使用 `/gmpt-nickname @玩家 <新昵称>` 来改名。"
            )
        elif item_type == "legendary_title":
            effect_msg = (
                "👑 **LEGENDARY TITLE ACTIVATED! / 至尊传说称号已激活！**\n"
                f"**{interaction.user.display_name}** has equipped the **Legendary Title**! / 已装备**至尊传说称号**！\n"
                "🌟 A legendary player walks among us... / 传说级玩家降临..."
            )
        elif item_type == "xp_boost":
            effect_msg = (
                "✅ **XP Boost Activated! / 经验加成已激活！**\n"
                "Next match: **+50% XP** / 下一场比赛**经验值 +50%**。"
            )
        elif item_type == "invisibility":
            effect_msg = (
                "✅ **Invisibility Activated! / 隐身已激活！**\n"
                "Your name is hidden on leaderboard for 24h. / 24小时内排行榜上将隐藏你的名字。"
            )
        elif item_type == "name_change":
            effect_msg = (
                "✅ **Name Change Card Used! / 改名卡已使用！**\n"
                "Use `/gmpt-rename <new_name>` to change your nickname. / 使用 `/gmpt-rename <新昵称>` 修改昵称。"
            )
        elif item_type == "broadcast":
            effect_msg = (
                "📢 **SERVER BROADCAST / 全服广播**\n"
                f"**{interaction.user.display_name}** sends a message to everyone! / 向全服发送了一条消息！\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "📣 Hear ye, hear ye! A mighty warrior speaks! / 诸位听令！一位勇士在此发声！\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
        elif item_type == "revive":
            effect_msg = (
                "✅ **Revive Card Activated! / 复活卡已激活！**\n"
                "You can revive once after elimination in the next match. / 下场比赛淘汰后可复活一次。"
            )
        else:
            effect_msg = (
                f"✅ **Used: {item_name} / 已使用: {item_name}**\n"
                "Item effect applied successfully. / 物品效果已生效。"
            )

        qty_after = qty - 1
        conn.close()

        await interaction.response.send_message(
            f"{effect_msg}\n\n"
            f"📦 Remaining / 剩余: **{qty_after}** x {item_name}"
        )

        # 检查物品使用成就
        conn2 = get_db(); cur2 = conn2.cursor()
        cur2.execute(
            "SELECT COUNT(*) as cnt FROM transactions WHERE discord_id=? AND (reason LIKE '%Used item%' OR reason LIKE '%使用物品%')",
            (uid,),
        )
        use_count = cur2.fetchone()["cnt"]
        conn2.close()
        if use_count >= 10:
            check_achievement(uid, "使用物品 10 次")
        if use_count >= 50:
            check_achievement(uid, "使用物品 50 次")

    # ========== 成就 ==========
    @app_commands.command(name="gmpt-achievements", description="View achievements / 成就列表（分页版）")
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

        # 分页：第一页
        page_rows = rows[:ACH_PER_PAGE]
        total_pages = max(1, (len(rows) + ACH_PER_PAGE - 1) // ACH_PER_PAGE)

        img_buf = generate_ach_image(page_rows, unlocked_ct, len(rows), page=1, total_pages=total_pages)

        if img_buf is None:
            embed = discord.Embed(title="🏆 ACHIEVEMENTS / 成就", color=0x00DC82)
            embed.add_field(name="Progress / 进度", value=f"{unlocked_ct} / {len(rows)} Unlocked", inline=False)
            parts = []
            for r in page_rows:
                hidden = r.get("hidden", False) and not r.get("unlocked", False)
                if hidden:
                    parts.append("❓ ？？？ — Hidden achievement / 隐藏成就")
                elif r["unlocked"]:
                    parts.append(f"✅ **{r['name']}** — {r['description']} (+{r['reward']}🪙)")
                else:
                    parts.append(f"⬜ {r['name']} — {r['description']} (+{r['reward']}🪙)")
            embed.add_field(name="", value="\n".join(parts), inline=False)
            embed.set_footer(text=f"GMPT Bot • Economy System | Page 1/{total_pages}")
            view = AchFilter(all_rows=rows, unlocked_ct=unlocked_ct, total_ct=len(rows), user_id=uid)
            return await interaction.response.send_message(embed=embed, view=view)

        f = discord.File(img_buf, filename="achievements.png")
        view = AchFilter(all_rows=rows, unlocked_ct=unlocked_ct, total_ct=len(rows), user_id=uid)
        await interaction.response.send_message(file=f, view=view)

    # ========== 管理员加钱 ==========
    @app_commands.command(name="gmpt-add-coins", description="Add/remove coins for a player / 给玩家加减金币（管理员）")
    @app_commands.describe(player="Target player / 目标玩家", amount="Amount (positive to add, negative to remove) / 数量（正加负减）")
    async def add_coins_cmd(self, interaction: discord.Interaction, player: discord.Member, amount: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Admin only. / 仅管理员可使用此命令。", ephemeral=True
            )

        uid = str(player.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (discord_id, username) VALUES (?,?) ON CONFLICT(discord_id) DO NOTHING",
            (uid, player.name),
        )
        conn.commit(); conn.close()

        reason = f"Admin adjustment by {interaction.user.display_name} / 管理员调整"
        add_coins(uid, amount, reason)
        new_balance = get_balance(uid)

        action = "Added" if amount >= 0 else "Removed"
        prep = "to" if amount >= 0 else "from"
        await interaction.response.send_message(
            f"✅ {action} {abs(amount)} coins {prep} {player.mention}. New balance: {new_balance}"
        )

    # ========== 价格管理 ==========
    @app_commands.command(name="gmpt-shop-edit", description="Edit shop item price / 修改商店价格（管理员）")
    @app_commands.describe(item_id="Item ID", new_price="New price / 新价格")
    async def shop_edit_cmd(self, interaction: discord.Interaction, item_id: int, new_price: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Admin only. / 仅管理员可使用此命令。", ephemeral=True
            )

        if new_price < 1:
            return await interaction.response.send_message(
                "Price must be > 0. / 价格必须大于 0。", ephemeral=True
            )

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM shop_items WHERE id=?", (item_id,))
        item = cur.fetchone()
        if not item:
            conn.close()
            return await interaction.response.send_message(
                "Item not found. / 物品不存在。", ephemeral=True
            )

        old_price = item["price"]
        cur.execute("UPDATE shop_items SET price=? WHERE id=?", (new_price, item_id))
        conn.commit(); conn.close()

        await interaction.response.send_message(
            f"✅ **{item['name']}** price updated / 价格已更新: 🪙 {old_price} → 🪙 {new_price}"
        )


async def setup(bot):
    await bot.add_cog(Economy(bot))
