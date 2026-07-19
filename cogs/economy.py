
"""
GMPT Bot — 经济系统 (Economy) v3
图片+按钮式商店 / 分页成就 / 签到 / 赠送 / 交易 / 背包使用 / 价格管理
中英文双语支持
"""
import asyncio
import io
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
from datetime import date, datetime
from cogs.shared_views import ConfirmView

import logging
logger = logging.getLogger(__name__)

# ---------- 频道 ID ----------
SHOP_LOG_CHANNEL_ID = 1528241284177854624
ACHIEVEMENTS_CHANNEL_ID = 1528241092640768101
ITEM_REQUESTS_CHANNEL_ID = 1528249993914220625

_bot = None  # 由 setup() 注入

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("Pillow not installed — image features disabled")


# ---------- 常量 ----------
STREAK_REWARDS = {
    1: 50, 2: 50, 3: 50, 4: 50, 5: 50, 6: 50,
    7: 200, 14: 350, 21: 500, 30: 1000,
    60: 2000, 100: 5000,
}

ACH_PER_PAGE = 8

# ── Match reward constants ──
MATCH_WIN_COINS = 150       # coins awarded to each winner
MATCH_PARTICIPATE_COINS = 50  # coins awarded to each loser / MVP

DEFAULT_SHOP = [
    # ⚔️ 赛前道具（Pre-match）
    {"name": "Ban闪现卡 (Ban Flash)", "desc": "禁止对面上单带闪现 / Ban the enemy top laner's Flash", "price": 200, "type": "ban_flash", "emoji": "🚫", "category": "⚔️ 赛前道具"},
    {"name": "冻结卡 (Freeze)", "desc": "冻结对面上单，不允许换英雄 / Freeze enemy top laner from swapping champion", "price": 300, "type": "freeze", "emoji": "❄️", "category": "⚔️ 赛前道具"},
    {"name": "沉默卡 (Silence)", "desc": "对面无法在比赛频道发言 / Silence enemy from chat during match", "price": 250, "type": "silence", "emoji": "🤫", "category": "⚔️ 赛前道具"},
    {"name": "致盲卡 (Blind)", "desc": "对方无法看到你的选人 / Enemy cannot see your champion pick", "price": 200, "type": "blind", "emoji": "👁️‍🗨️", "category": "⚔️ 赛前道具"},
    {"name": "减速卡 (Slow)", "desc": "对方加载时间+30秒 / Enemy loading time +30s (psychological)", "price": 150, "type": "slow", "emoji": "🐌", "category": "⚔️ 赛前道具"},
    {"name": "万能钥匙 (Lock Pick)", "desc": "无视对方Ban人 / Bypass one enemy ban", "price": 500, "type": "lock_pick", "emoji": "🔑", "category": "⚔️ 赛前道具"},
    {"name": "禁止双招 (No Summs)", "desc": "对方不能带召唤师技能 / Enemy cannot take summoner spells", "price": 350, "type": "no_summs", "emoji": "🚷", "category": "⚔️ 赛前道具"},
    {"name": "降级卡 (Downgrade)", "desc": "对方本场比赛MMR-10% / Enemy MMR -10% for this match", "price": 400, "type": "downgrade", "emoji": "📉", "category": "⚔️ 赛前道具"},

    # 🎮 比赛中道具（In-match）
    {"name": "暂停卡 (Timeout)", "desc": "强制暂停比赛 1 分钟 / Force a 1-minute timeout", "price": 400, "type": "timeout", "emoji": "⏸️", "category": "🎮 比赛中道具"},
    {"name": "闭麦卡 (Mute)", "desc": "对面上单全程闭麦 / Mute enemy top laner for the match", "price": 200, "type": "mute", "emoji": "🔇", "category": "🎮 比赛中道具"},
    {"name": "透视卡 (Reveal)", "desc": "比赛中可看到对面位置 / Reveal enemy positions on minimap", "price": 300, "type": "reveal", "emoji": "👁️", "category": "🎮 比赛中道具"},
    {"name": "禁止召回 (No Recall)", "desc": "对面上单不能回城 / Enemy top laner cannot recall", "price": 300, "type": "no_recall", "emoji": "🚫", "category": "🎮 比赛中道具"},
    {"name": "打散卡 (Breakup)", "desc": "解散对方当前队伍 / Disband enemy current team", "price": 250, "type": "breakup", "emoji": "💔", "category": "🎮 比赛中道具"},
    {"name": "偷Buff卡 (Steal Buff)", "desc": "开局偷对面一个Buff / Steal one buff from enemy at start", "price": 600, "type": "steal_buff", "emoji": "💨", "category": "🎮 比赛中道具"},
    {"name": "加速卡 (Sprint)", "desc": "本场比赛移速+15% / +15% movement speed for this match", "price": 250, "type": "sprint", "emoji": "💨", "category": "🎮 比赛中道具"},
    {"name": "反转卡 (Reverse)", "desc": "比赛结果反转（败→胜）/ Reverse match result (Loss→Win)", "price": 400, "type": "reverse", "emoji": "🔄", "category": "🎮 比赛中道具"},
    {"name": "自爆卡 (Kamikaze)", "desc": "自己双倍伤害但被打也双倍 / Double damage dealt & taken", "price": 350, "type": "kamikaze", "emoji": "💣", "category": "🎮 比赛中道具"},
    {"name": "投降卡 (Surrender)", "desc": "对面自动投降 / Enemy auto-surrenders at 15", "price": 800, "type": "surrender", "emoji": "🏳️", "category": "🎮 比赛中道具"},

    # 😈 坑队友道具（Troll Teammates）
    {"name": "送头卡 (Int Card)", "desc": "指定队友本场比赛送10个人头 / Teammate ints 10 kills this match", "price": 350, "type": "int_card", "emoji": "🤡", "category": "😈 坑队友道具"},
    {"name": "挂机卡 (AFK Card)", "desc": "指定队友前5分钟挂机 / Teammate AFKs for first 5 min", "price": 400, "type": "afk_card", "emoji": "💤", "category": "😈 坑队友道具"},
    {"name": "禁用装备 (No Items)", "desc": "指定队友不能买装备 / Teammate cannot buy items", "price": 300, "type": "no_items", "emoji": "🚫", "category": "😈 坑队友道具"},
    {"name": "喂养Buff (Feed Buff)", "desc": "指定队友给你送Buff / Teammate delivers buffs to you", "price": 350, "type": "feed_buff", "emoji": "🍽️", "category": "😈 坑队友道具"},

    # 💰 加成道具（金币/MMR加成）
    {"name": "MMR保护卡 (MMR Protect)", "desc": "本场比赛输了不扣MMR / Lose without MMR penalty for this match", "price": 500, "type": "mmr_protect", "emoji": "🛡️", "category": "💰 加成道具"},
    {"name": "双倍MMR卡 (Double MMR)", "desc": "本场比赛赢了MMR翻倍 / Double MMR gain if you win", "price": 600, "type": "double_mmr", "emoji": "⚡", "category": "💰 加成道具"},
    {"name": "偷金币卡 (Coin Steal)", "desc": "结算时偷对手 30 coins / Steal 30 coins from opponent on settle", "price": 350, "type": "steal_coins", "emoji": "🥷", "category": "💰 加成道具"},
    {"name": "经验加成卡 (XP Boost Card)", "desc": "下一场比赛经验值+50% / Next match +50% XP", "price": 800, "type": "xp_boost", "emoji": "📈", "category": "💰 加成道具"},
    # 🎲 随机道具
    {"name": "双倍或清零 (Double or Nothing)", "desc": "使用后随机翻倍或清零当前余额 / Randomly double or zero your balance", "price": 300, "type": "gamble", "emoji": "🎲", "category": "🎲 随机道具"},

    # 🎭 Discord道具
    {"name": "自定义身份组 (Color Role)", "desc": "兑换自定义颜色身份组 — 通知管理手动设置 / Request custom color role — admin handles manually", "price": 1000, "type": "color_role", "emoji": "🎨", "category": "🎭 Discord道具"},
    {"name": "改名卡 (Rename)", "desc": "兑换改名机会 — 通知管理手动改名 / Request nickname change — admin handles manually", "price": 800, "type": "rename", "emoji": "✏️", "category": "🎭 Discord道具"},
    {"name": "专属称号 (Title)", "desc": "兑换专属称号 — 通知管理手动授予 / Request custom title — admin handles manually", "price": 1500, "type": "title", "emoji": "🏷️", "category": "🎭 Discord道具"},
    {"name": "私人语音 (Private VC)", "desc": "Bot为你创建临时语音频道 / Bot creates a temporary voice channel for you", "price": 2000, "type": "private_vc", "emoji": "🎙️", "category": "🎭 Discord道具"},
    {"name": "全服广播 (Broadcast)", "desc": "发送消息到 @everyone / Broadcast a message to everyone", "price": 1200, "type": "broadcast", "emoji": "📢", "category": "🎭 Discord道具"},
    {"name": "抽奖券 (Giveaway Ticket)", "desc": "获得一张抽奖券参与抽奖 / Get a ticket for the giveaway", "price": 500, "type": "giveaway_ticket", "emoji": "🎟️", "category": "🎭 Discord道具"},
    {"name": "插队卡 (Queue Skip)", "desc": "下次排队时直接插到最前面 / Skip to front of queue next time", "price": 600, "type": "queue_skip", "emoji": "⏩", "category": "🎭 Discord道具"},
    {"name": "自选模式 (Mode Pick)", "desc": "自选下一场比赛模式 / Pick the game mode for next match", "price": 800, "type": "mode_pick", "emoji": "🎯", "category": "🎭 Discord道具"},
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

CATEGORY_COLORS = {
    "⚔️ 赛前道具": 0xE74C3C,
    "🎮 比赛中道具": 0x3498DB,
    "😈 坑队友道具": 0xE67E22,
    "💰 加成道具": 0x2ECC71,
    "🎲 随机道具": 0xF1C40F,
    "🎭 Discord道具": 0x9B59B6,
}


ITEM_DISPLAY = {
    # ⚔️ 赛前道具 Pre-Game
    "ban_flash":    "禁闪卡 Ban Flash — 禁用闪现30秒 Disable Flash 30s",
    "freeze":       "定身卡 Freeze — 不能离开泉水30秒 Can't leave fountain 30s",
    "silence":      "沉默卡 Silence — 不能放技能只能平A30秒 No skills AA-only 30s",
    "blind":        "致盲卡 Blind — 不能插眼30秒 No wards 30s",
    "slow":         "减速卡 Slow — 不能买鞋子30秒 Can't buy boots 30s",
    "lock_pick":    "锁英雄 Lock Pick — 指定对方英雄 Forced hero pick",
    "no_summs":     "禁召唤师 No Summs — 禁第二个召唤师技能 Second summoner disabled",
    "downgrade":    "降级卡 Downgrade — 开局少1级 Start at level 1",
    # 🎮 比赛中 Mid-Game
    "timeout":      "暂停卡 Timeout — 原地不动15秒 Frozen 15s",
    "mute":         "禁言卡 Mute — 不能打字/语音30秒 No chat/voice 30s",
    "reveal":       "暴露卡 Reveal — 发坐标 Send location in chat",
    "no_recall":    "回城禁 No Recall — 不能B回城30秒 Can't recall 30s",
    "breakup":      "分手卡 Breakup — 2人保持1000码以上 Stay 1000+ units apart 30s",
    "steal_buff":   "偷Buff Steal Buff — 下一个buff让出 Give next buff",
    "sprint":       "加速卡 Sprint — 移速翻倍15秒 Double move speed 15s",
    "reverse":      "反转卡 Reverse — 键鼠反向30秒 Reversed controls 30s",
    "kamikaze":     "自爆卡 Kamikaze — 冲塔送一次 Tower dive once",
    "surrender":    "投降卡 Surrender — 必须/ff不能拒绝 Must /ff, can't decline",
    # 😈 坑队友 Troll
    "int_card":     "送头卡 Int Card — 送对面一血 Feed first blood",
    "afk_card":     "挂机卡 AFK — 原地挂机30秒 AFK 30s",
    "no_items":     "裸奔卡 No Items — 不能买装备30秒 Can't buy items 30s",
    "feed_buff":    "送Buff Feed Buff — buff让给对面 Give buff to enemy",
    # 💰 加成 Boost
    "mmr_protect":  "MMR保护卡 MMR Protect — 输了不扣MMR No MMR loss on defeat",
    "double_mmr":   "双倍MMR卡 Double MMR — 赢了MMR翻倍 Double MMR on win",
    "steal_coins":  "偷金币卡 Steal Coins — 偷对手30 coins Steal 30 coins",
    "xp_boost":     "经验加成 XP Boost — 经验+50% XP +50%",
    # 🎲 随机 Gamble
    "gamble":       "双倍或清零 Doubler — 随机翻倍或清零 Double or nothing",
    # 🎭 Discord
    "color_role":       "自选颜色 Color Role — 自选颜色（通知管理） Custom color (admin)",
    "rename":           "改名卡 Rename — 改昵称（通知管理） Nickname change (admin)",
    "title":            "专属头衔 Title — 自定义称号（通知管理） Custom title (admin)",
    "private_vc":       "私人语音 Private VC — 创建临时语音频道 Temp voice channel",
    "broadcast":        "全服喇叭 Broadcast — 发全服消息 Server-wide message",
    "giveaway_ticket":  "抽奖券 Giveaway Ticket — 增加抽奖机会 Giveaway entries",
    "queue_skip":       "插队卡 Queue Skip — 排队优先 Priority queue",
    "mode_pick":        "自选模式 Mode Pick — 下次比赛你选模式 Pick next mode",
}


def _build_category_embed(category, items, bal):
    """Build an embed for a single category with item descriptions and effects."""
    color = CATEGORY_COLORS.get(category, 0xFFD700)
    embed = discord.Embed(title=f"{category}", color=color)
    embed.add_field(name="💰 余额 Balance", value=f"🪙 {bal} GMPT Coins", inline=False)

    lines = []
    for it in items:
        emoji = it.get("emoji", "🛒")
        item_type = it["item_type"]
        price = it["price"]
        display = ITEM_DISPLAY.get(item_type, f"{it['name']} — {it['description']}")
        lines.append(f"{emoji} {display} — {price}g")

    embed.add_field(name="道具列表 Items", value="\n".join(lines), inline=False)
    embed.set_footer(text="GMPT Bot • Economy System")
    return embed

class MainMenuView(discord.ui.View):
    """Main menu with 6 category buttons + Balance/Inventory."""
    CATEGORY_BUTTONS = [
        ("⚔️ 赛前",    "⚔️ 赛前道具",  0),
        ("🎮 比赛中",  "🎮 比赛中道具", 0),
        ("😈 坑队友",  "😈 坑队友道具", 0),
        ("💰 加成",    "💰 加成道具",   0),
        ("🎲 随机",    "🎲 随机道具",   1),
        ("🎭 Discord", "🎭 Discord道具", 1),
    ]

    def __init__(self, all_items, categories, user_id, bal):
        super().__init__(timeout=None)
        self.all_items = all_items
        self.categories = categories
        self.user_id = user_id
        self.bal = bal

        for label, cat_key, row in self.CATEGORY_BUTTONS:
            btn = discord.ui.Button(
                label=label, style=discord.ButtonStyle.primary, row=row,
                custom_id=f"shop_main_{cat_key}",
            )
            btn.callback = self.make_category_callback(cat_key)
            self.add_item(btn)

    def make_category_callback(self, category):
        async def callback(interaction: discord.Interaction):
            if str(interaction.user.id) != self.user_id:
                return await interaction.response.send_message(
                    "This is not your shop. / 这不是你的商店页面。", ephemeral=True)
            await interaction.response.defer()

            items = [it for it in self.all_items if it.get("category", "其他") == category]
            embed = _build_category_embed(category, items, self.bal)
            view = ShopView(
                items=items, category=category,
                all_items=self.all_items, categories=self.categories,
                user_id=self.user_id, bal=self.bal,
            )
            await interaction.edit_original_response(embed=embed, view=view, attachments=[])
        return callback

    @discord.ui.button(label="💰 Balance", emoji="💰", style=discord.ButtonStyle.secondary, row=2)
    async def balance_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if str(interaction.user.id) != self.user_id:
            return await interaction.followup.send("This is not your shop. / 这不是你的商店页面。", ephemeral=True)
        bal = get_balance(str(interaction.user.id))
        await interaction.followup.send(f"🪙 Balance / 余额: **{bal}** GMPT Coins", ephemeral=True)

    @discord.ui.button(label="🎒 Inventory", emoji="🎒", style=discord.ButtonStyle.secondary, row=2)
    async def inv_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if str(interaction.user.id) != self.user_id:
            return await interaction.followup.send("This is not your shop. / 这不是你的商店页面。", ephemeral=True)
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
            return await interaction.followup.send("Backpack is empty. / 背包是空的。", ephemeral=True)
        lines = [f"📦 **{r['name']}** x{r['quantity']}" for r in rows]
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class ShopView(discord.ui.View):
    """Category view with item buy buttons + Back/Categories/Balance."""

    def __init__(self, items, category, user_id,
                 all_items=None, categories=None, bal=None):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.all_items = all_items
        self.categories = categories
        self.bal = bal
        self.category = category

        # Item buy buttons (rows 0-2, max 10 items: 4+4+2)
        for idx, it in enumerate(items[:10]):
            r = idx // 4
            if r > 2:
                r = 2
            short_name = ITEM_DISPLAY.get(it["item_type"], it["name"])
            short_name = short_name.split(" — ")[0].split(" ")[-1] if " — " in short_name else short_name[:10]
            # Use item_type-based short labels for emoji-only buttons
            label_map = {
                "ban_flash": "禁闪", "freeze": "定身", "silence": "沉默", "blind": "致盲",
                "slow": "减速", "lock_pick": "锁英雄", "no_summs": "禁召唤", "downgrade": "降级",
                "timeout": "暂停", "mute": "禁言", "reveal": "暴露", "no_recall": "回城禁",
                "breakup": "分手", "steal_buff": "偷Buff", "sprint": "加速", "reverse": "反转",
                "kamikaze": "自爆", "surrender": "投降", "int_card": "送头", "afk_card": "挂机",
                "no_items": "裸奔", "feed_buff": "送Buff", "mmr_protect": "MMR保护",
                "double_mmr": "双倍MMR", "steal_coins": "偷金币", "xp_boost": "经验加成",
                "gamble": "双倍清零", "color_role": "自选颜色", "rename": "改名",
                "title": "头衔", "private_vc": "语音", "broadcast": "广播",
                "giveaway_ticket": "抽奖券", "queue_skip": "插队", "mode_pick": "自选模式",
            }
            label = label_map.get(it["item_type"], it["name"][:8])
            btn = discord.ui.Button(
                label=label,
                emoji=it.get("emoji", "🛒"),
                style=discord.ButtonStyle.primary,
                custom_id=f"shop_buy_{it['id']}",
                row=r,
            )
            btn.callback = self.make_buy_callback(it["id"])
            self.add_item(btn)

    @discord.ui.button(label="⬅ 返回", emoji="⬅️", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message(
                "This is not your shop. / 这不是你的商店页面。", ephemeral=True)
        await interaction.response.defer()

        embed = discord.Embed(
            title="🛒 积分商店 Item Shop",
            description="选择分类查看道具 Select a category to browse items",
            color=0xFFD700,
        )
        embed.set_footer(text="GMPT Bot • Economy System")
        view = MainMenuView(
            all_items=self.all_items, categories=self.categories,
            user_id=self.user_id, bal=self.bal,
        )
        await interaction.edit_original_response(embed=embed, view=view, attachments=[])

    @discord.ui.button(label="📁 分类", emoji="📁", style=discord.ButtonStyle.secondary, row=3)
    async def categories_btn(self, interaction: discord.Interaction, button):
        """Return to main menu to select another category."""
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message(
                "This is not your shop. / 这不是你的商店页面。", ephemeral=True)
        await interaction.response.defer()

        embed = discord.Embed(
            title="🛒 积分商店 Item Shop",
            description="选择分类查看道具 Select a category to browse items",
            color=0xFFD700,
        )
        embed.set_footer(text="GMPT Bot • Economy System")
        view = MainMenuView(
            all_items=self.all_items, categories=self.categories,
            user_id=self.user_id, bal=self.bal,
        )
        await interaction.edit_original_response(embed=embed, view=view, attachments=[])

    @discord.ui.button(label="💰 Balance", emoji="💰", style=discord.ButtonStyle.secondary, row=3)
    async def balance_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if str(interaction.user.id) != self.user_id:
            return await interaction.followup.send("This is not your shop. / 这不是你的商店页面。", ephemeral=True)
        bal = get_balance(str(interaction.user.id))
        await interaction.followup.send(f"🪙 Balance / 余额: **{bal}** GMPT Coins", ephemeral=True)

    def make_buy_callback(self, item_id):
        async def callback(interaction: discord.Interaction):
            if str(interaction.user.id) != self.user_id:
                return await interaction.response.send_message("This is not your shop. / 这不是你的商店页面。", ephemeral=True)
            await interaction.response.defer()
            await buy_item(interaction, str(interaction.user.id), item_id)
        return callback

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class AchFilter(discord.ui.View):
    """成就查看器：支持全部/已解锁/未解锁筛选 + 分页翻页"""
    def __init__(self, all_rows, unlocked_ct, total_ct, user_id, per_page=ACH_PER_PAGE, timeout=120):
        super().__init__(timeout=None)
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
        await interaction.response.defer(ephemeral=True)
        if str(interaction.user.id) != self.user_id:
            return await interaction.followup.send("This is not your page. / 这不是你的页面。", ephemeral=True)
        self.current_page -= 1
        await self._render_and_update(interaction)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.secondary, custom_id="ach_next", row=0)
    async def next_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if str(interaction.user.id) != self.user_id:
            return await interaction.followup.send("This is not your page. / 这不是你的页面。", ephemeral=True)
        self.current_page += 1
        await self._render_and_update(interaction)

    @discord.ui.button(label="All", style=discord.ButtonStyle.primary, emoji="📋", row=1)
    async def all_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if str(interaction.user.id) != self.user_id:
            return await interaction.followup.send("This is not your page. / 这不是你的页面。", ephemeral=True)
        self.current_filter = "all"
        self.current_page = 0
        await self._render_and_update(interaction)

    @discord.ui.button(label="Unlocked", style=discord.ButtonStyle.success, emoji="✅", row=1)
    async def unlocked_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if str(interaction.user.id) != self.user_id:
            return await interaction.followup.send("This is not your page. / 这不是你的页面。", ephemeral=True)
        self.current_filter = "unlocked"
        self.current_page = 0
        await self._render_and_update(interaction)

    @discord.ui.button(label="Locked", style=discord.ButtonStyle.secondary, emoji="⬜", row=1)
    async def locked_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if str(interaction.user.id) != self.user_id:
            return await interaction.followup.send("This is not your page. / 这不是你的页面。", ephemeral=True)
        self.current_filter = "locked"
        self.current_page = 0
        await self._render_and_update(interaction)


# ---------- 购买逻辑 ----------
async def buy_item(interaction: discord.Interaction, uid: str, item_id: int, broadcast_message: str = None):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM shop_items WHERE id=?", (item_id,))
    item = cur.fetchone()
    if not item:
        conn.close(); return await interaction.followup.send(
            "Item not found. / 物品不存在。", ephemeral=True
        )

    bal = get_balance(uid)
    if bal < item["price"]:
        conn.close(); return await interaction.followup.send(
            f"Insufficient balance! Need {item['price']} coins, you have {bal}. / 余额不足！需要 {item['price']} coins，你有 {bal} coins。",
            ephemeral=True,
        )
    conn.close()

    # broadcast 必须有消息内容
    if item["item_type"] == "broadcast" and not broadcast_message:
        return await interaction.followup.send(
            "Broadcast requires a message! Usage: `/gmpt-buy broadcast message:你的消息`",
            ephemeral=True,
        )

    # GAME_ITEMS = 放入背包的类型
    GAME_ITEMS = {
        "mmr_protect", "double_mmr", "steal_coins", "xp_boost", "gamble",
        "ban_flash", "freeze", "silence", "blind", "slow", "lock_pick", "no_summs", "downgrade",
        "timeout", "mute", "reveal", "no_recall", "breakup", "steal_buff", "sprint", "reverse", "kamikaze", "surrender",
        "int_card", "afk_card", "no_items", "feed_buff",
    }
    ADMIN_NOTIFY_TYPES = {"color_role", "rename", "title"}

    class ConfirmBuy(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(label="Confirm / 确认购买", style=discord.ButtonStyle.success, emoji="✅")
        async def confirm(self, btn_i: discord.Interaction, button):
            await btn_i.response.defer()
            if str(btn_i.user.id) != uid:
                return await btn_i.followup.send(
                    "This is not your order. / 这不是你的购买单。", ephemeral=True
                )

            conn2 = get_db(); cur2 = conn2.cursor()
            bal2 = get_balance(uid)
            if bal2 < item["price"]:
                conn2.close(); return await btn_i.followup.send(
                    f"Insufficient balance! {bal2} coins. / 余额不足！{bal2} coins。", ephemeral=True
                )

            # 扣钱 + 记录交易
            cur2.execute("UPDATE users SET score = score - ? WHERE discord_id = ?", (item["price"], uid))
            cur2.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                         (uid, -item["price"], f"Purchase: {item['name']} / 购买: {item['name']}"))

            item_type = item["item_type"]
            result_msg = f"✅ Purchased! / 购买成功！**{item['name']}**  -{item['price']} coins"

            if item_type in GAME_ITEMS:
                # 存入背包
                cur2.execute(
                    "INSERT INTO user_inventory (user_id, item_id, quantity) VALUES (?,?,1) "
                    "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + 1",
                    (uid, item_id),
                )
                conn2.commit(); conn2.close()

                # shop-log 通知
                if _bot:
                    try:
                        shop_ch = _bot.get_channel(SHOP_LOG_CHANNEL_ID)
                        if shop_ch:
                            await shop_ch.send(f"{btn_i.user.mention} 购买了 [{item['name']}] — 花费 {item['price']} coins")
                    except Exception:
                        pass

            elif item_type in ADMIN_NOTIFY_TYPES:
                conn2.commit(); conn2.close()
                # 通知管理手动处理
                if _bot:
                    try:
                        req_ch = _bot.get_channel(ITEM_REQUESTS_CHANNEL_ID)
                        if req_ch:
                            await req_ch.send(
                                f"{btn_i.user.mention} 兑换了 **[{item['name']}]** — 需要管理手动处理（价格 {item['price']} coins）"
                            )
                    except Exception:
                        pass

            elif item_type == "private_vc":
                conn2.commit(); conn2.close()
                # Bot 创建语音频道
                if _bot and interaction.guild:
                    try:
                        username = btn_i.user.display_name or btn_i.user.name
                        vc = await interaction.guild.create_voice_channel(name=f"{username}的房间")
                        result_msg += f"\n🎙️ Voice channel **{vc.name}** created! / 语音频道已创建！"
                        # shop-log 通知
                        try:
                            shop_ch = _bot.get_channel(SHOP_LOG_CHANNEL_ID)
                            if shop_ch:
                                await shop_ch.send(
                                    f"{btn_i.user.mention} 购买了 [Private VC] — 语音频道 **{vc.name}** 已创建（花费 {item['price']} coins）"
                                )
                        except Exception:
                            pass
                    except Exception as e:
                        result_msg += f"\n⚠️ Failed to create voice channel: {e}"

            elif item_type == "broadcast":
                conn2.commit(); conn2.close()
                # 广播到 economy-info 频道
                if _bot and broadcast_message:
                    try:
                        shop_ch = _bot.get_channel(SHOP_LOG_CHANNEL_ID)
                        if shop_ch:
                            await shop_ch.send(f"📢 {btn_i.user.mention} 全服广播：{broadcast_message}")
                    except Exception:
                        pass
                result_msg += f"\n📢 Broadcast sent! / 全服广播已发送！"

            elif item_type == "giveaway_ticket":
                cur2.execute(
                    "INSERT INTO giveaway_tickets (discord_id, tickets) VALUES (?,1) "
                    "ON CONFLICT(discord_id) DO UPDATE SET tickets = tickets + 1",
                    (uid,),
                )
                cur2.execute("SELECT tickets FROM giveaway_tickets WHERE discord_id=?", (uid,))
                total = cur2.fetchone()["tickets"]
                conn2.commit(); conn2.close()
                result_msg += f"\n🎟️ You now have **{total}** giveaway ticket(s)! / 你现在有 **{total}** 张抽奖券！"
                # shop-log
                if _bot:
                    try:
                        shop_ch = _bot.get_channel(SHOP_LOG_CHANNEL_ID)
                        if shop_ch:
                            await shop_ch.send(f"{btn_i.user.mention} 购买了 [Giveaway Ticket] x1 — 共持有 {total} 张（花费 {item['price']} coins）")
                    except Exception:
                        pass

            elif item_type == "queue_skip":
                cur2.execute(
                    "INSERT INTO user_flags (discord_id, queue_skip) VALUES (?,1) "
                    "ON CONFLICT(discord_id) DO UPDATE SET queue_skip = queue_skip + 1",
                    (uid,),
                )
                cur2.execute("SELECT queue_skip FROM user_flags WHERE discord_id=?", (uid,))
                skips = cur2.fetchone()["queue_skip"]
                conn2.commit(); conn2.close()
                result_msg += f"\n⏩ You have **{skips}** queue skip(s) available! / 你有 **{skips}** 次插队资格！"

            elif item_type == "mode_pick":
                cur2.execute(
                    "INSERT INTO user_flags (discord_id, mode_pick) VALUES (?, 'pending') "
                    "ON CONFLICT(discord_id) DO UPDATE SET mode_pick = 'pending'",
                    (uid,),
                )
                conn2.commit(); conn2.close()
                result_msg += f"\n🎯 Mode pick activated! Next match you can choose the game mode. / 自选模式已激活！下场比赛可选择模式。"

            else:
                # 兜底：存入背包
                cur2.execute(
                    "INSERT INTO user_inventory (user_id, item_id, quantity) VALUES (?,?,1) "
                    "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + 1",
                    (uid, item_id),
                )
                conn2.commit(); conn2.close()

            for child in self.children: child.disabled = True
            await btn_i.edit_original_response(content=result_msg, view=self)

            # 成就检查
            check_achievement(uid, "在商店购买")
            conn3 = get_db(); cur3 = conn3.cursor()
            cur3.execute("SELECT COUNT(*) as cnt FROM transactions WHERE discord_id=? AND (reason LIKE '%Purchase%' OR reason LIKE '%购买%')", (uid,))
            if cur3.fetchone()["cnt"] >= 5:
                check_achievement(uid, "购买 5 次")
            conn3.close()

        @discord.ui.button(label="Cancel / 取消", style=discord.ButtonStyle.secondary, emoji="❌")
        async def cancel(self, btn_i: discord.Interaction, button):
            await btn_i.response.defer()
            if str(btn_i.user.id) != uid:
                return await btn_i.followup.send(
                    "This is not your order. / 这不是你的购买单。", ephemeral=True
                )
            for child in self.children: child.disabled = True
            await btn_i.edit_original_response(content="Cancelled. / 已取消。", view=self)

    await interaction.followup.send(
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
    """返回用户余额。首次访问自动创建用户行（初始500），确保后续 UPDATE 能生效。"""
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (discord_id, username) VALUES (?, 'unknown') ON CONFLICT(discord_id) DO NOTHING",
        (user_id,),
    )
    conn.commit()
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
    completed = _check_completionist(cur, user_id, a["id"])

    conn.close()

    # 成就解锁通知推送到 ACHIEVEMENTS_CHANNEL
    if _bot:
        async def _send_ach():
            try:
                ach_ch = _bot.get_channel(ACHIEVEMENTS_CHANNEL_ID)
                if ach_ch:
                    await ach_ch.send(f"<@{user_id}> 解锁了成就 [{a['name']}] — +{a['reward']} coins")
                    if completed:
                        await ach_ch.send(f"<@{user_id}> 解锁了成就 [{completed['name']}] — +{completed['reward']} coins")
            except Exception:
                pass
        _bot.loop.create_task(_send_ach())

    return {"name": a["name"], "desc": a["description"], "reward": a["reward"], "hidden": bool(a["hidden"])}


def _check_completionist(cur, user_id: str, just_unlocked_id: int):
    """检查是否解锁了全成就（排除隐藏成就和全成就本身）。返回解锁信息或 None。"""
    # 先找出"全成就解锁"这个成就的 ID
    cur.execute("SELECT id, name, reward FROM achievements WHERE description LIKE '%Unlocked all non-hidden achievements%'")
    comp_row = cur.fetchone()
    if not comp_row:
        return None
    completionist_id = comp_row["id"]
    if just_unlocked_id == completionist_id:
        return None  # 刚解锁的就是全成就本身，跳过

    # 检查是否已经拿到全成就
    cur.execute("SELECT COUNT(*) as cnt FROM user_achievements WHERE user_id=? AND achievement_id=?",
                (user_id, completionist_id))
    if cur.fetchone()["cnt"] > 0:
        return None

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
        reward = comp_row["reward"]
        if reward > 0:
            cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (reward, user_id))
            cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                        (user_id, reward, "Achievement: Completionist / 成就: 全成就解锁"))
        return {"name": comp_row["name"], "reward": reward}
    return None


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

    # ========== 语音状态监听 (Voice time tracking) ==========
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Track cumulative time spent in voice channels for daily reward."""
        if member.bot:
            return

        uid = str(member.id)
        now = datetime.now().isoformat()

        # User joined a voice channel (was not in one, now is)
        if before.channel is None and after.channel is not None:
            conn = get_db(); cur = conn.cursor()
            cur.execute(
                "INSERT INTO voice_sessions (discord_id, join_time, total_seconds) VALUES (?,?,0)",
                (uid, now),
            )
            conn.commit(); conn.close()

        # User left a voice channel (was in one, now is not)
        elif before.channel is not None and after.channel is None:
            conn = get_db(); cur = conn.cursor()
            # Find the most recent open session (join_time only, no duration recorded yet)
            cur.execute(
                "SELECT join_time FROM voice_sessions "
                "WHERE discord_id=? AND total_seconds=0 "
                "ORDER BY join_time DESC LIMIT 1",
                (uid,),
            )
            row = cur.fetchone()
            if row:
                try:
                    join_dt = datetime.fromisoformat(row["join_time"])
                    duration = int((datetime.now() - join_dt).total_seconds())
                    if duration > 0:
                        cur.execute(
                            "UPDATE voice_sessions SET total_seconds=? "
                            "WHERE discord_id=? AND join_time=?",
                            (duration, uid, row["join_time"]),
                        )
                        conn.commit()
                except Exception:
                    pass
            conn.close()

        # User switched voice channels
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            conn = get_db(); cur = conn.cursor()
            # Close old session
            cur.execute(
                "SELECT join_time FROM voice_sessions "
                "WHERE discord_id=? AND total_seconds=0 "
                "ORDER BY join_time DESC LIMIT 1",
                (uid,),
            )
            row = cur.fetchone()
            if row:
                try:
                    join_dt = datetime.fromisoformat(row["join_time"])
                    duration = int((datetime.now() - join_dt).total_seconds())
                    if duration > 0:
                        cur.execute(
                            "UPDATE voice_sessions SET total_seconds=? "
                            "WHERE discord_id=? AND join_time=?",
                            (duration, uid, row["join_time"]),
                        )
                except Exception:
                    pass
            # Start new session
            cur.execute(
                "INSERT INTO voice_sessions (discord_id, join_time, total_seconds) VALUES (?,?,0)",
                (uid, now),
            )
            conn.commit(); conn.close()

    # ========== 每日签到 ==========
    @app_commands.command(name="gmpt-daily", description="Daily check-in for coins / 每日签到")
    async def daily_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        # Check voice channel presence + cumulative time >= 30 minutes
        if not interaction.user.voice or not interaction.user.voice.channel:
            conn = get_db(); cur = conn.cursor()
            cur.execute(
                "SELECT COALESCE(SUM(total_seconds), 0) as total FROM voice_sessions WHERE discord_id=?",
                (uid,),
            )
            row = cur.fetchone()
            total_secs = row["total"] if row else 0
            conn.close()
            mins = total_secs // 60
            return await interaction.response.send_message(
                f"You must join a voice channel first! "
                f"Today's accumulated voice time: **{mins}** min (need 30 min). / "
                f"请先加入语音频道！今日已累计语音时长: **{mins}** 分钟（需要 30 分钟）。",
                ephemeral=True,
            )

        # Calculate cumulative voice time including the current session
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(total_seconds), 0) as total FROM voice_sessions WHERE discord_id=?",
            (uid,),
        )
        row = cur.fetchone()
        total_secs = row["total"] if row else 0

        # Also include current session if open
        cur.execute(
            "SELECT join_time FROM voice_sessions "
            "WHERE discord_id=? AND total_seconds=0 "
            "ORDER BY join_time DESC LIMIT 1",
            (uid,),
        )
        current_row = cur.fetchone()
        if current_row:
            try:
                join_dt = datetime.fromisoformat(current_row["join_time"])
                current_secs = int((datetime.now() - join_dt).total_seconds())
                total_secs += current_secs
            except Exception:
                pass

        conn.close()

        total_minutes = total_secs // 60
        if total_secs < 1800:  # 30 minutes = 1800 seconds
            return await interaction.response.send_message(
                f"Not enough voice time! You need **30 minutes** in voice channels to claim daily coins. "
                f"Current: **{total_minutes}** min / "
                f"语音时长不足！需要在语音频道累计 **30 分钟** 才能领取每日金币。当前已累计: **{total_minutes}** 分钟。",
                ephemeral=True,
            )

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
                     (uid, reward, f"Daily Check-in Day {new_streak} / 每日签到 Day {new_streak} (Voice: {total_minutes}min)"))
        conn.commit(); conn.close()

        milestone = ""
        if new_streak in STREAK_REWARDS and new_streak > 1:
            milestone = f"\n🎉 Milestone bonus! / 签到里程碑！额外获得 {STREAK_REWARDS[new_streak]} coins！"

        await interaction.response.send_message(
            f"✅ Check-in! / 签到成功！ +{reward} coins  🔥 Streak / 连胜: **{new_streak}** days "
            f"| Voice / 语音: **{total_minutes}** min{milestone}"
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
        cur.execute("SELECT item_type FROM shop_items")
        existing_types = {r["item_type"] for r in cur.fetchall()}
        missing = [item for item in DEFAULT_SHOP if item["type"] not in existing_types]
        for item in missing:
            cur.execute(
                "INSERT INTO shop_items (name, description, price, item_type, category) VALUES (?,?,?,?,?)",
                (item["name"], item["desc"], item["price"], item["type"], item.get("category", "其他")),
            )
        if missing:
            conn.commit()

        cur.execute("SELECT id, name, description, price, item_type, category FROM shop_items ORDER BY price")
        all_items = [dict(r) for r in cur.fetchall()]
        conn.close()

        for it in all_items:
            for d in DEFAULT_SHOP:
                if d["name"] == it["name"]:
                    it["emoji"] = d["emoji"]; break
            else:
                it["emoji"] = "🛒"

        # extract unique categories
        categories = list(dict.fromkeys(it.get("category", "其他") for it in all_items))

        # main menu: welcome embed + category buttons
        embed = discord.Embed(
            title="🛒 积分商店 Item Shop",
            description="选择分类查看道具 Select a category to browse items",
            color=0xFFD700,
        )
        embed.set_footer(text="GMPT Bot • Economy System")
        view = MainMenuView(all_items=all_items, categories=categories, user_id=uid, bal=bal)
        await interaction.response.send_message(embed=embed, view=view)

    # ========== 购买 ==========
    @app_commands.command(name="gmpt-buy", description="Buy item from shop / 购买商店物品")
    @app_commands.describe(item_id="Item ID from /gmpt-shop", message="Message content (required for Broadcast)")
    async def buy_cmd(self, interaction: discord.Interaction, item_id: int, message: str = None):
        await buy_item(interaction, str(interaction.user.id), item_id, broadcast_message=message)

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
        if item_type == "gamble":
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
        elif item_type == "xp_boost":
            # 激活经验加成
            conn3 = get_db(); cur3 = conn3.cursor()
            cur3.execute("INSERT INTO active_effects (user_id, effect_type) VALUES (?,?)", (uid, "xp_boost"))
            conn3.commit(); conn3.close()
            effect_msg = (
                "✅ **XP Boost Activated! / 经验加成已激活！**\n"
                "Next match: **+50% coins** / 下一场比赛**金币 +50%**。"
            )
        elif item_type == "mmr_protect":
            conn3 = get_db(); cur3 = conn3.cursor()
            cur3.execute("INSERT INTO active_effects (user_id, effect_type) VALUES (?,?)", (uid, "mmr_protect"))
            conn3.commit(); conn3.close()
            effect_msg = (
                "🛡️ **MMR Protection Activated! / MMR保护已激活！**\n"
                "Your next loss will not reduce MMR. / 下一场输了不扣MMR。"
            )
        elif item_type == "double_mmr":
            conn3 = get_db(); cur3 = conn3.cursor()
            cur3.execute("INSERT INTO active_effects (user_id, effect_type) VALUES (?,?)", (uid, "double_mmr"))
            conn3.commit(); conn3.close()
            effect_msg = (
                "⚡ **Double MMR Activated! / 双倍MMR已激活！**\n"
                "Your next win earns **2x MMR**. / 下一场赢了MMR**翻倍**。"
            )
        elif item_type == "steal_coins":
            conn3 = get_db(); cur3 = conn3.cursor()
            cur3.execute("INSERT INTO active_effects (user_id, effect_type) VALUES (?,?)", (uid, "steal_coins"))
            conn3.commit(); conn3.close()
            effect_msg = (
                "🥷 **Coin Steal Ready! / 偷金币已就绪！**\n"
                "Will steal 30 coins from opponent on next match settle. / 下场结算时偷对手 30 coins。"
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

    # ========== 管理员重置金币 ==========
    @app_commands.command(name="gmpt-reset-coins", description="[DEPRECATED] Use /gmpt-admin-coins instead / 已弃用，请用 /gmpt-admin-coins")
    @app_commands.describe(
        target="Target player / 目标玩家（与 all 二选一）",
        all="Reset ALL existing users (True/False) / 重置所有用户（与 target 二选一）",
        amount="New coin amount (default 500) / 新金币数量（默认 500）"
    )
    async def reset_coins_cmd(
        self,
        interaction: discord.Interaction,
        target: discord.Member = None,
        all: bool = False,
        amount: int = 500,
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Admin only. / 仅管理员可使用此命令。", ephemeral=True
            )

        if target is None and not all:
            return await interaction.response.send_message(
                "请指定 @玩家 或设置 all=True / Specify @user or all=True.", ephemeral=True
            )
        if target is not None and all:
            return await interaction.response.send_message(
                "不能同时指定 target 和 all / Cannot specify both target and all.", ephemeral=True
            )

        conn = get_db()
        cur = conn.cursor()

        if target is not None:
            uid = str(target.id)
            cur.execute(
                "INSERT INTO users (discord_id, username, score) VALUES (?, ?, ?) "
                "ON CONFLICT(discord_id) DO UPDATE SET score=?",
                (uid, target.name, amount, amount),
            )
            cur.execute(
                "INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                (uid, 0, f"Admin reset coins to {amount} by {interaction.user.display_name} / 管理员重置金币"),
            )
            conn.commit()
            conn.close()

            embed = discord.Embed(
                title="金币重置 / Reset Coins",
                description=f"✅ {target.mention} 的金币已重置为 **{amount}**\n{target.mention}'s coins reset to **{amount}**.",
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed)
        else:
            # Reset all existing users
            cur.execute("SELECT discord_id, username FROM users")
            all_users = cur.fetchall()

            if not all_users:
                conn.close()
                return await interaction.response.send_message(
                    "数据库中没有用户 / No users in database.", ephemeral=True
                )

            for u in all_users:
                cur.execute(
                    "UPDATE users SET score=? WHERE discord_id=?",
                    (amount, u["discord_id"]),
                )
                cur.execute(
                    "INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                    (u["discord_id"], 0,
                     f"Admin mass reset coins to {amount} by {interaction.user.display_name} / 管理员批量重置金币"),
                )

            conn.commit()
            conn.close()

            embed = discord.Embed(
                title="金币重置 / Reset Coins",
                description=f"✅ 已将所有 **{len(all_users)}** 名用户的金币重置为 **{amount}**\nReset all **{len(all_users)}** users' coins to **{amount}**.",
                color=discord.Color.green(),
            )
            embed.set_footer(text=f"执行者 / By: {interaction.user.display_name}")
            await interaction.response.send_message(embed=embed)

    # ========== 管理员金币面板 ==========
    @app_commands.command(name="gmpt-admin-coins", description="Admin coin management panel / 管理员金币管理面板")
    async def admin_coins_cmd(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Admin only. / 仅管理员可使用此命令。", ephemeral=True
            )

        embed = discord.Embed(
            title="🪙 金币管理面板 / Coin Management Panel",
            description=(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "**重置单人 / Reset User** | **重置全部 / Reset All**\n"
                "**查看全部 / View All**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Choose an action below / 点击下方按钮操作"
            ),
            color=discord.Color.gold(),
        ).set_footer(text="GMPT Admin Coins v1.0")

        view = AdminCoinsView(guild=interaction.guild)
        await interaction.response.send_message(embed=embed, view=view)

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

    # ========== 金币下注 / Betting ==========
    @app_commands.command(name="gmpt-bet", description="对比赛下注 / Place a bet on a match")
    @app_commands.describe(
        match_id="比赛 ID / Match ID",
        amount="下注金额 / Bet amount (max 500)",
        team="下注队伍 ID / Team ID to bet on",
    )
    async def bet_cmd(
        self, interaction: discord.Interaction,
        match_id: int, amount: int, team: int,
    ):
        uid = str(interaction.user.id)

        if amount < 1 or amount > 500:
            return await interaction.response.send_message(
                "下注金额需在 1-500 之间 / Bet amount must be 1-500.", ephemeral=True,
            )

        conn = get_db(); cur = conn.cursor()

        # Check match status
        cur.execute("SELECT id, status FROM tournaments WHERE id=?", (match_id,))
        match = cur.fetchone()
        if not match:
            conn.close()
            return await interaction.response.send_message(
                "比赛不存在 / Match not found.", ephemeral=True,
            )
        if match["status"] == "finished":
            conn.close()
            return await interaction.response.send_message(
                "比赛已结算，无法下注 / Match already settled.", ephemeral=True,
            )

        # Check team exists
        cur.execute(
            "SELECT id, name FROM teams WHERE id=? AND tournament_id=?",
            (team, match_id),
        )
        team_row = cur.fetchone()
        if not team_row:
            conn.close()
            return await interaction.response.send_message(
                "队伍不存在 / Team not found.", ephemeral=True,
            )

        # Check balance
        cur.execute(
            "INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING",
            (uid,),
        )
        cur.execute("SELECT score FROM users WHERE discord_id=?", (uid,))
        user = cur.fetchone()
        balance = user["score"] if user and user["score"] is not None else 0

        if balance < amount:
            conn.close()
            return await interaction.response.send_message(
                f"金币不足 / Insufficient coins. 余额: 🪙 {balance}", ephemeral=True,
            )

        # Check if already bet on this match
        cur.execute(
            "SELECT id FROM bets WHERE match_id=? AND discord_id=?",
            (match_id, uid),
        )
        if cur.fetchone():
            conn.close()
            return await interaction.response.send_message(
                "你已在本场比赛下注 / Already placed a bet on this match.", ephemeral=True,
            )

        # Deduct coins and place bet
        cur.execute("UPDATE users SET score=score-? WHERE discord_id=?", (amount, uid))
        cur.execute(
            "INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
            (uid, -amount, f"下注比赛 #{match_id} — {team_row['name']}"),
        )
        cur.execute(
            "INSERT INTO bets (match_id, discord_id, amount, team) VALUES (?,?,?,?)",
            (match_id, uid, amount, str(team)),
        )
        conn.commit(); conn.close()

        await interaction.response.send_message(
            f"✅ {interaction.user.mention} 下注 🪙 **{amount}** → "
            f"比赛 #{match_id} **{team_row['name']}** (Team {team})\n"
            f"投对得 2x 返还 / Win = 2x payout!"
        )

    @bet_cmd.autocomplete("match_id")
    async def bet_match_id_autocomplete(self, interaction: discord.Interaction, current: str):
        from cogs.match_autocomplete import match_id_autocomplete
        return await match_id_autocomplete(interaction, current)

    @bet_cmd.autocomplete("team")
    async def bet_team_autocomplete(self, interaction: discord.Interaction, current: str):
        """Autocomplete team_id from the already selected match_id."""
        try:
            match_id_str = interaction.namespace.get("match_id")
            if not match_id_str:
                return []
            match_id = int(match_id_str)
        except (ValueError, TypeError):
            return []

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id, name FROM teams WHERE tournament_id=?", (match_id,))
        teams = cur.fetchall(); conn.close()

        return [
            app_commands.Choice(
                name=f"{t['name'][:80]} (ID:{t['id']})",
                value=t["id"],
            )
            for t in teams
            if current.lower() in str(t["id"]) or current.lower() in (t["name"] or "").lower()
        ][:25]

    @app_commands.command(name="gmpt-bet-stats", description="查看下注历史 / View bet history and stats")
    async def bet_stats_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()

        # Stats
        cur.execute("SELECT COUNT(*) as total FROM bets WHERE discord_id=?", (uid,))
        total = cur.fetchone()["total"]

        cur.execute(
            "SELECT COUNT(*) as wins FROM bets WHERE discord_id=? AND settled=1 AND won=1",
            (uid,),
        )
        wins = cur.fetchone()["wins"]
        win_pct = round(wins / total * 100, 1) if total > 0 else 0

        # Recent bets
        cur.execute(
            """SELECT b.match_id, b.amount, b.team, b.placed_at, b.settled, b.won, t.name as match_name
               FROM bets b
               LEFT JOIN tournaments t ON b.match_id = t.id
               WHERE b.discord_id=?
               ORDER BY b.placed_at DESC LIMIT 10""",
            (uid,),
        )
        recent = cur.fetchall(); conn.close()

        embed = discord.Embed(
            title="🎲 下注统计 / Betting Stats",
            color=discord.Color.orange(),
        )
        embed.add_field(name="总下注 / Total Bets", value=str(total), inline=True)
        embed.add_field(name="猜对 / Wins", value=str(wins), inline=True)
        embed.add_field(name="胜率 / Win Rate", value=f"{win_pct}%", inline=True)

        if recent:
            lines = []
            for b in recent:
                match_label = b["match_name"] or f"#{b['match_id']}"
                status = "✅" if b["settled"] and b["won"] else ("❌" if b["settled"] else "⏳")
                lines.append(
                    f"{status} {match_label} — 🪙 {b['amount']} → Team {b['team']} "
                    f"({b['placed_at'][:10] if b['placed_at'] else '?'})"
                )
            embed.add_field(
                name="最近下注 / Recent Bets",
                value="\n".join(lines),
                inline=False,
            )

        await interaction.response.send_message(embed=embed)


# ══════════ Betting Settlement / 下注结算 ══════════

def settle_bets(match_id: int, winning_team_id: int) -> list:
    """结算指定比赛的所有下注。投对的 2x 返还，投错的没收。返回结果摘要行列表。"""
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "SELECT id, discord_id, amount, team FROM bets WHERE match_id=? AND settled=0",
        (match_id,),
    )
    bets = cur.fetchall()

    settled = 0
    won = 0
    result_lines = []

    for b in bets:
        won_flag = 1 if str(b["team"]) == str(winning_team_id) else 0
        cur.execute(
            "UPDATE bets SET settled=1, won=? WHERE id=?",
            (won_flag, b["id"]),
        )
        settled += 1
        if won_flag:
            won += 1
            payout = b["amount"] * 2
            cur.execute(
                "UPDATE users SET score=score+? WHERE discord_id=?",
                (payout, b["discord_id"]),
            )
            cur.execute(
                "INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                (b["discord_id"], payout, f"下注获胜 #{match_id} — 2x 返还"),
            )

    # Check for vote bets (旧版下注系统)
    try:
        cur.execute(
            "SELECT id, discord_id, amount FROM vote_bets WHERE match_id=? AND settled=0",
            (match_id,),
        )
        vote_bets = cur.fetchall()
    except Exception:
        vote_bets = []

    for vb in vote_bets:
        try:
            cur.execute("UPDATE vote_bets SET settled=1, won=1 WHERE id=?", (vb["id"],))
        except Exception:
            pass
        settled += 1
        won += 1

    conn.commit(); conn.close()

    total = settled
    lost = total - won
    if total > 0:
        result_lines.append(
            f"🎲 下注结算 #{match_id}: {total} 注 | ✅ {won} 胜 {lost} 负"
        )
    return result_lines


# =============================================================================
# AdminCoinsView — 管理员金币管理面板 / Admin Coin Management Panel
# =============================================================================
class AdminCoinsView(discord.ui.View):
    """Admin coin management panel — reset user, reset all, view all."""
    def __init__(self, guild, timeout=None):
        super().__init__(timeout=None)
        self.guild = guild

    @discord.ui.button(label="重置单人 Reset User", style=discord.ButtonStyle.primary, emoji="👤", row=0)
    async def reset_user_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        # Build user select dropdown from guild members
        members = [m for m in self.guild.members if not m.bot][:25]
        if not members:
            return await interaction.followup.send("服务器没有可用成员 / No members found.", ephemeral=True)

        options = []
        for m in members:
            options.append(discord.SelectOption(
                label=m.display_name[:100],
                value=str(m.id),
                description=f"ID: {m.id}",
            ))

        select = discord.ui.Select(
            placeholder="选择用户 / Select a user...",
            options=options[:25],
        )

        async def user_callback(sel_int: discord.Interaction):
            uid = sel_int.data["values"][0]
            member = self.guild.get_member(int(uid))
            name = member.display_name if member else f"<@{uid}>"

            # Show amount modal
            modal = ResetUserModal(guild=self.guild, user_id=uid, user_name=name)
            await sel_int.response.send_modal(modal)

        select.callback = user_callback
        view = discord.ui.View(timeout=120)
        view.add_item(select)
        await interaction.followup.send(view=view, ephemeral=True)

    @discord.ui.button(label="重置全部 Reset All", style=discord.ButtonStyle.danger, emoji="🔥", row=1)
    async def reset_all_btn(self, interaction: discord.Interaction, button):
        modal = ResetAllModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="查看全部 View All", style=discord.ButtonStyle.secondary, emoji="📋", row=1)
    async def view_all_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT discord_id, username, score FROM users ORDER BY score DESC")
        all_users = cur.fetchall()
        conn.close()

        if not all_users:
            return await interaction.followup.send("数据库中没有用户 / No users in database.", ephemeral=True)

        view = CoinPaginationView(users_data=all_users, page=0, guild=self.guild)
        embed = view.build_embed()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def on_timeout(self):
        for child in self.children:
            if hasattr(child, 'disabled'):
                child.disabled = True
        if hasattr(self, 'message') and self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass



class ResetUserModal(discord.ui.Modal, title="重置单人金币 / Reset User Coins"):
    amount = discord.ui.TextInput(
        label="金币数量 / Coin Amount",
        placeholder="500",
        default="500",
        max_length=10,
        required=True,
    )

    def __init__(self, guild, user_id, user_name):
        super().__init__()
        self.guild = guild
        self.user_id = user_id
        self.user_name = user_name

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value)
        except ValueError:
            return await interaction.response.send_message("金币数量必须是数字 / Amount must be a number.", ephemeral=True)

        if amt < 0:
            return await interaction.response.send_message("金币数量不能为负 / Amount cannot be negative.", ephemeral=True)

        member = self.guild.get_member(int(self.user_id))
        mention = member.mention if member else f"<@{self.user_id}>"

        embed = discord.Embed(
            title="确认重置 / Confirm Reset",
            description=(
                f"目标 / Target: {mention}\n"
                f"新金币 / New Coins: **{amt}**\n\n"
                f"点击确认执行 / Click confirm to proceed"
            ),
            color=discord.Color.orange(),
        )
        confirm_view = ConfirmView(timeout=60)
        await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)
        await confirm_view.wait()

        if confirm_view.value is None or not confirm_view.value:
            return await interaction.edit_original_response(
                content="已取消 / Cancelled.", embed=None, view=None
            )

        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (discord_id, username, score) VALUES (?, ?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET score=?",
            (self.user_id, self.user_name, amt, amt),
        )
        cur.execute(
            "INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
            (self.user_id, 0, f"Admin reset coins to {amt} by {interaction.user.display_name} / 管理员重置金币"),
        )
        conn.commit(); conn.close()

        await interaction.edit_original_response(
            content=f"✅ {mention} 的金币已重置为 **{amt}** / coins reset to **{amt}**.",
            embed=None, view=None
        )


class ResetAllModal(discord.ui.Modal, title="重置全部金币 / Reset All Coins"):
    amount = discord.ui.TextInput(
        label="金币数量 / Coin Amount",
        placeholder="500",
        default="500",
        max_length=10,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value)
        except ValueError:
            return await interaction.response.send_message("金币数量必须是数字 / Amount must be a number.", ephemeral=True)

        if amt < 0:
            return await interaction.response.send_message("金币数量不能为负 / Amount cannot be negative.", ephemeral=True)

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT discord_id, username FROM users")
        all_users = cur.fetchall()
        conn.close()

        if not all_users:
            return await interaction.response.send_message("数据库中没有用户 / No users in database.", ephemeral=True)

        embed = discord.Embed(
            title="⚠️ 确认批量重置 / Confirm Mass Reset",
            description=(
                f"将重置 **{len(all_users)}** 名用户的金币为 **{amt}**\n"
                f"Will reset **{len(all_users)}** users' coins to **{amt}**\n\n"
                f"此操作不可撤销 / This action is irreversible\n"
                f"点击确认执行 / Click confirm to proceed"
            ),
            color=discord.Color.red(),
        )
        confirm_view = ConfirmView(timeout=60)
        await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)
        await confirm_view.wait()

        if confirm_view.value is None or not confirm_view.value:
            return await interaction.edit_original_response(
                content="已取消 / Cancelled.", embed=None, view=None
            )

        conn = get_db(); cur = conn.cursor()
        for u in all_users:
            cur.execute("UPDATE users SET score=? WHERE discord_id=?", (amt, u["discord_id"]))
            cur.execute(
                "INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                (u["discord_id"], 0, f"Admin mass reset coins to {amt} by {interaction.user.display_name} / 管理员批量重置金币"),
            )
        conn.commit(); conn.close()

        await interaction.edit_original_response(
            content=f"✅ 已重置 **{len(all_users)}** 名用户的金币为 **{amt}** / reset all **{len(all_users)}** users to **{amt}**.",
            embed=None, view=None
        )

    # ========== 比赛道具使用 ==========
    # 效果描述 + 持续秒数：None=全局不发结束 / 0=即时不发结束 / >0=定时发结束通知
    ITEM_EFFECTS = {
        "ban_flash":    ("禁用闪现", 30),
        "freeze":       ("不能离开泉水", 30),
        "silence":      ("不能放技能，只能平A", 30),
        "blind":        ("不能插眼", 30),
        "slow":         ("不能买鞋子", 30),
        "lock_pick":    ("只能用指定英雄", None),
        "no_summs":     ("第二个召唤师技能禁用", None),
        "downgrade":    ("开局少1级", None),
        "timeout":      ("原地不动不能操作", 15),
        "mute":         ("不能打字/语音", 30),
        "reveal":       ("必须在聊天发坐标", 0),
        "no_recall":    ("不能按B回城", 30),
        "breakup":      ("指定2人不能靠近1000码", 30),
        "steal_buff":   ("下一个buff让给你", 0),
        "sprint":       ("自己移速翻倍", 15),
        "reverse":      ("鼠标键盘反着用", 30),
        "kamikaze":     ("听到信号必须冲塔送", 0),
        "surrender":    ("必须打/ff不能拒绝", 0),
        "int_card":     ("必须送对面一血", 0),
        "afk_card":     ("原地挂机不能动", 30),
        "no_items":     ("不能买装备", 30),
        "feed_buff":    ("下一个buff让给对面", 0),
    }

    item_group = app_commands.Group(
        name="gmpt-item",
        description="Use match items from inventory / 使用比赛道具"
    )

    @item_group.command(name="use", description="Use a match item on a target / 对目标使用比赛道具")
    @app_commands.describe(
        item_type="Item type (e.g. ban_flash, silence, timeout...) / 道具类型",
        target="Target Discord member / 目标成员"
    )
    @app_commands.choices(item_type=[
        app_commands.Choice(name="Ban Flash / 禁用闪现 (30s)", value="ban_flash"),
        app_commands.Choice(name="Freeze / 泉水冻结 (30s)", value="freeze"),
        app_commands.Choice(name="Silence / 沉默 (30s)", value="silence"),
        app_commands.Choice(name="Blind / 致盲 (30s)", value="blind"),
        app_commands.Choice(name="Slow / 减速 (30s)", value="slow"),
        app_commands.Choice(name="Lock Pick / 锁定英雄 (全局)", value="lock_pick"),
        app_commands.Choice(name="No Summs / 禁用召唤师技能 (全局)", value="no_summs"),
        app_commands.Choice(name="Downgrade / 降级 (全局)", value="downgrade"),
        app_commands.Choice(name="Timeout / 暂停 (15s)", value="timeout"),
        app_commands.Choice(name="Mute / 闭麦 (30s)", value="mute"),
        app_commands.Choice(name="Reveal / 透视 (即时)", value="reveal"),
        app_commands.Choice(name="No Recall / 禁止回城 (30s)", value="no_recall"),
        app_commands.Choice(name="Breakup / 打散 (30s)", value="breakup"),
        app_commands.Choice(name="Steal Buff / 偷Buff (即时)", value="steal_buff"),
        app_commands.Choice(name="Sprint / 加速 (15s)", value="sprint"),
        app_commands.Choice(name="Reverse / 反转 (30s)", value="reverse"),
        app_commands.Choice(name="Kamikaze / 自爆 (即时)", value="kamikaze"),
        app_commands.Choice(name="Surrender / 强制投降 (即时)", value="surrender"),
        app_commands.Choice(name="Int Card / 送一血 (即时)", value="int_card"),
        app_commands.Choice(name="AFK Card / 挂机 (30s)", value="afk_card"),
        app_commands.Choice(name="No Items / 禁止装备 (30s)", value="no_items"),
        app_commands.Choice(name="Feed Buff / 送Buff (即时)", value="feed_buff"),
    ])
    async def item_use(self, interaction: discord.Interaction, item_type: str, target: discord.Member):
        uid = str(interaction.user.id)
        effect_info = self.ITEM_EFFECTS.get(item_type)
        if not effect_info:
            return await interaction.response.send_message(
                f"Unknown item type: `{item_type}`. / 未知道具类型。", ephemeral=True
            )

        effect_desc, duration = effect_info

        # 目标必须仍在服务器
        if target not in interaction.guild.members:
            return await interaction.response.send_message(
                "Target is not in the server. / 目标成员不在服务器中。", ephemeral=True
            )

        conn = get_db(); cur = conn.cursor()

        # 查找背包中该道具
        cur.execute("""
            SELECT inv.item_id, inv.quantity, si.name
            FROM user_inventory inv
            JOIN shop_items si ON si.id = inv.item_id
            WHERE inv.user_id=? AND si.item_type=?
        """, (uid, item_type))
        row = cur.fetchone()

        if not row:
            conn.close()
            return await interaction.response.send_message(
                f"You don't have `{item_type}` in your backpack. / 背包没有该道具。", ephemeral=True
            )

        item_id = row["item_id"]
        item_name = row["name"]
        qty = row["quantity"]

        # 扣减1件
        if qty <= 1:
            cur.execute("DELETE FROM user_inventory WHERE user_id=? AND item_id=?", (uid, item_id))
        else:
            cur.execute("UPDATE user_inventory SET quantity = quantity - 1 WHERE user_id=? AND item_id=?",
                        (uid, item_id))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
                     (uid, 0, f"Used item on {target.display_name}: {item_name} / 对 {target.display_name} 使用: {item_name}"))
        conn.commit(); conn.close()

        # 构建 embed 公告
        dur_str = f"{duration}秒" if duration else ("全局" if duration is None else "即时")
        embed = discord.Embed(
            title=f"⚡ 道具使用 / Item Used",
            description=(
                f"**{interaction.user.mention}** 对 **{target.mention}** 使用了 **{item_name}**\n\n"
                f"📋 **效果 / Effect:** {effect_desc}\n"
                f"⏱️ **持续 / Duration:** {dur_str}"
            ),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)

        # 定时全局效果结束通知（duration > 0 且为秒数）
        if isinstance(duration, int) and duration > 0 and _bot:
            async def end_notify():
                await asyncio.sleep(duration)
                try:
                    ch = interaction.channel
                    if ch:
                        await ch.send(f"⏰ **{item_name}** 对 {target.mention} 的效果已结束。")
                except Exception:
                    pass
            asyncio.create_task(end_notify())

    # ========== 抽奖系统 ==========
    giveaway_group = app_commands.Group(
        name="gmpt-giveaway",
        description="Giveaway system with tickets / 抽奖券抽奖系统"
    )

    @giveaway_group.command(name="create", description="Create a giveaway (Admin) / 创建抽奖（管理员）")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(prize="Prize name / 奖品名称", draw_at="Draw time (YYYY-MM-DD HH:MM format, KST) / 开奖时间")
    async def giveaway_create(self, interaction: discord.Interaction, prize: str, draw_at: str):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO giveaways (channel_id, prize, created_by, draw_at) VALUES (?,?,?,?)",
            (str(interaction.channel_id), prize, str(interaction.user.id), draw_at),
        )
        gid = cur.lastrowid
        conn.commit(); conn.close()

        await interaction.response.send_message(
            f"🎉 **Giveaway #{gid} Created! / 抽奖已创建！**\n"
            f"Prize / 奖品: **{prize}**\n"
            f"Draw time / 开奖时间: **{draw_at}**\n"
            f"Use `/gmpt-giveaway enter {gid}` to enter! / 使用 `/gmpt-giveaway enter {gid}` 参与！"
        )

    @giveaway_group.command(name="enter", description="Enter a giveaway using tickets / 用抽奖券参与抽奖")
    @app_commands.describe(giveaway_id="Giveaway ID / 抽奖编号")
    async def giveaway_enter(self, interaction: discord.Interaction, giveaway_id: int):
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()

        cur.execute("SELECT * FROM giveaways WHERE id=? AND drawn=0", (giveaway_id,))
        ga = cur.fetchone()
        if not ga:
            conn.close()
            return await interaction.response.send_message("Giveaway not found or already drawn. / 抽奖不存在或已开奖。", ephemeral=True)

        cur.execute("SELECT tickets FROM giveaway_tickets WHERE discord_id=?", (uid,))
        row = cur.fetchone()
        if not row or row["tickets"] <= 0:
            conn.close()
            return await interaction.response.send_message(
                "You have no giveaway tickets! Buy them from `/gmpt-shop`. / 你没有抽奖券！去商店购买吧。",
                ephemeral=True,
            )

        tickets = row["tickets"]

        class EnterConfirm(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=None)

            @discord.ui.button(label="Use 1 Ticket / 使用1张券", style=discord.ButtonStyle.success, emoji="🎟️")
            async def use_one(self, btn_i: discord.Interaction, button):
                await interaction.response.defer(ephemeral=True)
                if str(btn_i.user.id) != uid:
                    return await btn_i.response.send_message("Not your entry. / 不是你的参与。", ephemeral=True)
                conn2 = get_db(); cur2 = conn2.cursor()
                cur2.execute("UPDATE giveaway_tickets SET tickets = tickets - 1 WHERE discord_id=?", (uid,))
                cur2.execute("INSERT INTO giveaway_entries (giveaway_id, discord_id, tickets_used) VALUES (?,?,1)", (giveaway_id, uid))
                conn2.commit(); conn2.close()
                for child in self.children: child.disabled = True
                await btn_i.response.edit_message(
                    content=f"✅ Entered giveaway #{giveaway_id} with 1 ticket! / 已用1张券参与抽奖 #{giveaway_id}！",
                    view=self,
                )

            @discord.ui.button(label="Use ALL Tickets / 全部投入", style=discord.ButtonStyle.primary, emoji="🎰")
            async def use_all(self, btn_i: discord.Interaction, button):
                await interaction.response.defer(ephemeral=True)
                if str(btn_i.user.id) != uid:
                    return await btn_i.response.send_message("Not your entry. / 不是你的参与。", ephemeral=True)
                conn2 = get_db(); cur2 = conn2.cursor()
                cur2.execute("SELECT tickets FROM giveaway_tickets WHERE discord_id=?", (uid,))
                r = cur2.fetchone()
                tix = r["tickets"] if r else 0
                if tix <= 0:
                    conn2.close()
                    return await btn_i.response.send_message("No tickets! / 没有券了！", ephemeral=True)
                cur2.execute("UPDATE giveaway_tickets SET tickets = 0 WHERE discord_id=?", (uid,))
                cur2.execute("INSERT INTO giveaway_entries (giveaway_id, discord_id, tickets_used) VALUES (?,?,?)",
                            (giveaway_id, uid, tix))
                conn2.commit(); conn2.close()
                for child in self.children: child.disabled = True
                await btn_i.response.edit_message(
                    content=f"✅ Entered giveaway #{giveaway_id} with ALL **{tix}** tickets! / 已投入全部 **{tix}** 张券参与抽奖 #{giveaway_id}！",
                    view=self,
                )

            @discord.ui.button(label="Cancel / 取消", style=discord.ButtonStyle.secondary, emoji="❌")
            async def cancel(self, btn_i: discord.Interaction, button):
                await interaction.response.defer(ephemeral=True)
                if str(btn_i.user.id) != uid:
                    return await btn_i.response.send_message("Not your entry. / 不是你的参与。", ephemeral=True)
                for child in self.children: child.disabled = True
                await btn_i.response.edit_message(content="Cancelled. / 已取消。", view=self)

        conn.close()
        await interaction.response.send_message(
            f"🎟️ **Enter Giveaway #{giveaway_id}**\nPrize: **{ga['prize']}**\nYou have **{tickets}** ticket(s).\nHow many to use? / 使用几张券？",
            view=EnterConfirm(),
            ephemeral=True,
        )

    @giveaway_group.command(name="draw", description="Draw a winner (Admin) / 开奖（管理员）")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(giveaway_id="Giveaway ID / 抽奖编号")
    async def giveaway_draw(self, interaction: discord.Interaction, giveaway_id: int):
        conn = get_db(); cur = conn.cursor()

        cur.execute("SELECT * FROM giveaways WHERE id=? AND drawn=0", (giveaway_id,))
        ga = cur.fetchone()
        if not ga:
            conn.close()
            return await interaction.response.send_message("Giveaway not found or already drawn. / 抽奖不存在或已开奖。", ephemeral=True)

        cur.execute("SELECT discord_id FROM giveaway_entries WHERE giveaway_id=?", (giveaway_id,))
        entries = cur.fetchall()
        if not entries:
            conn.close()
            return await interaction.response.send_message("No entries for this giveaway! / 没有人参与这个抽奖！", ephemeral=True)

        # 多券 = 多条目（每张券在 entries 表中独立一条），实现加权随机
        all_entries = [e["discord_id"] for e in entries]
        winner = random.choice(all_entries)

        cur.execute("UPDATE giveaways SET drawn=1, winner_id=? WHERE id=?", (winner, giveaway_id))
        conn.commit(); conn.close()

        await interaction.response.send_message(
            f"🎉 **Giveaway #{giveaway_id} Winner! / 抽奖 #{giveaway_id} 开奖！**\n"
            f"Prize / 奖品: **{ga['prize']}**\n"
            f"Winner / 中奖者: <@{winner}> 🎊\n"
            f"Total entries / 总参与条目: **{len(entries)}**"
        )

    @giveaway_group.command(name="tickets", description="Check your giveaway tickets / 查看抽奖券数量")
    async def giveaway_tickets_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT tickets FROM giveaway_tickets WHERE discord_id=?", (uid,))
        row = cur.fetchone(); conn.close()
        tix = row["tickets"] if row else 0
        await interaction.response.send_message(
            f"🎟️ You have **{tix}** giveaway ticket(s). / 你有 **{tix}** 张抽奖券。", ephemeral=True
        )


class CoinPaginationView(discord.ui.View):
    """Paginated coin balance list — 10 per page."""
    def __init__(self, users_data, page=0, guild=None, timeout=120):
        super().__init__(timeout=None)
        self.users_data = users_data
        self.page = page
        self.per_page = 10
        self.guild = guild
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = (self.page + 1) * self.per_page >= len(self.users_data)

    def _display_name(self, discord_id):
        if self.guild:
            member = self.guild.get_member(int(discord_id))
            if member:
                return member.display_name
        return f"<@{discord_id}>"

    def build_embed(self):
        start = self.page * self.per_page
        end = min(start + self.per_page, len(self.users_data))
        page_users = self.users_data[start:end]

        embed = discord.Embed(
            title="🪙 全部用户金币 / All Users Coins",
            description=f"共 **{len(self.users_data)}** 名用户 / Total **{len(self.users_data)}** users",
            color=discord.Color.gold(),
        )

        lines = []
        for i, u in enumerate(page_users, start + 1):
            name = self._display_name(u["discord_id"])
            score = u["score"] if u["score"] is not None else 0
            lines.append(f"`#{i:>3}` {name} — 🪙 **{score}**")

        embed.add_field(
            name=f"第 {self.page + 1} 页 / Page {self.page + 1}",
            value="\n".join(lines) if lines else "(空)",
            inline=False,
        )
        embed.set_footer(text=f"GMPT Admin Coins | Page {self.page + 1}/{(len(self.users_data) + self.per_page - 1) // self.per_page}")
        return embed

    @discord.ui.button(label="上一页 Prev", emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if self.page > 0:
            self.page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="下一页 Next", emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if (self.page + 1) * self.per_page < len(self.users_data):
            self.page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)


async def setup(bot):
    global _bot
    _bot = bot
    await bot.add_cog(Economy(bot))

