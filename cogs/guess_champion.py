"""
GMPT Bot — Guess the Champion (猜英雄)
"""
import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db, get_db_ctx
from datetime import datetime
import logging
from utils.logger import log_error

logger = logging.getLogger(__name__)


def _add_coins(uid: str, amount: int, reason: str):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (discord_id, username) VALUES (?, 'unknown') ON CONFLICT(discord_id) DO NOTHING",
            (uid,),
        )
        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, uid))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)", (uid, amount, reason))
        conn.commit()


# ── Daily limit helper ──
def _check_daily_limit(uid: int, game_type: str) -> tuple[bool, int, int]:
    """Returns (blocked, used, remaining)."""
    today = datetime.now().strftime('%Y-%m-%d')
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO game_limits (user_id, date, game_type, play_count) VALUES (?,?,?,0)",
            (uid, today, game_type),
        )
        cur.execute(
            "SELECT play_count FROM game_limits WHERE user_id=? AND date=? AND game_type=?",
            (uid, today, game_type),
        )
        row = cur.fetchone()
        used = row["play_count"] if row else 0
        remaining = 3 - used
        blocked = used >= 3
        if not blocked:
            cur.execute(
                "UPDATE game_limits SET play_count = play_count + 1 WHERE user_id=? AND date=? AND game_type=?",
                (uid, today, game_type),
            )
            conn.commit()
    return blocked, used + (0 if blocked else 1), remaining - (0 if blocked else 1)


# ── Champion data (69 champions) with aliases ──
CHAMPIONS = [
    {"name": "安妮", "emoji": "🔥👧🐻🧸", "title": "黑暗之女", "quote": "你看见我的小熊了吗？", "region": "诺克萨斯",
     "aliases": ["annie", "an ni", "安妮"],
     "name_en": "Annie",
     "title_en": "the Dark Child",
     "quote_en": "Have you seen my bear Tibbers?",
     "region_en": "Noxus",
     "skill_q": "碎裂之火",
     "skill_q_en": "Disintegrate"},
    {"name": "亚索", "emoji": "💨🗡️😈", "title": "疾风剑豪", "quote": "死亡如风，常伴吾身", "region": "艾欧尼亚",
     "aliases": ["yasuo", "ya suo", "亚索", "压缩", "托儿索"],
     "name_en": "Yasuo",
     "title_en": "the Unforgiven",
     "quote_en": "Death is like the wind; always by my side.",
     "region_en": "Ionia",
     "skill_q": "斩钢闪",
     "skill_q_en": "Steel Tempest"},
    {"name": "艾希", "emoji": "🏹❄️👸", "title": "寒冰射手", "quote": "你要来几发吗？", "region": "弗雷尔卓德",
     "aliases": ["ashe", "a she", "艾希", "艾师傅"],
     "name_en": "Ashe",
     "title_en": "the Frost Archer",
     "quote_en": "How about a few arrows?",
     "region_en": "Freljord",
     "skill_q": "冰霜射击",
     "skill_q_en": "Frost Shot"},
    {"name": "盖伦", "emoji": "⚔️🛡️💪", "title": "德玛西亚之力", "quote": "德玛西亚！", "region": "德玛西亚",
     "aliases": ["garen", "ga len", "盖伦", "德玛", "德玛西亚", "德玛西亚之力"],
     "name_en": "Garen",
     "title_en": "the Might of Demacia",
     "quote_en": "Demacia!",
     "region_en": "Demacia",
     "skill_q": "致命打击",
     "skill_q_en": "Decisive Strike"},
    {"name": "劫", "emoji": "🌑🗡️💨", "title": "影流之主", "quote": "无形之刃，最为致命", "region": "艾欧尼亚",
     "aliases": ["zed", "ze d", "劫", "火影劫", "儿童劫", "kid"],
     "name_en": "Zed",
     "title_en": "the Master of Shadows",
     "quote_en": "The unseen blade is the deadliest.",
     "region_en": "Ionia",
     "skill_q": "影奥义！诸刃",
     "skill_q_en": "Razor Shuriken"},
    {"name": "锐雯", "emoji": "⚔️💨💚", "title": "放逐之刃", "quote": "断剑重铸之日，骑士归来之时", "region": "诺克萨斯",
     "aliases": ["riven", "rui wen", "锐雯", "瑞文", "放逐之刃"],
     "name_en": "Riven",
     "title_en": "the Exile",
     "quote_en": "A broken blade is more than enough for you.",
     "region_en": "Noxus",
     "skill_q": "折翼之舞",
     "skill_q_en": "Broken Wings"},
    {"name": "阿狸", "emoji": "🦊💙🔥", "title": "九尾妖狐", "quote": "我们来玩吧~", "region": "艾欧尼亚",
     "aliases": ["ahri", "a li", "阿狸", "九尾妖狐", "狐狸"],
     "name_en": "Ahri",
     "title_en": "the Nine-Tailed Fox",
     "quote_en": "Let's play!",
     "region_en": "Ionia",
     "skill_q": "欺诈宝珠",
     "skill_q_en": "Orb of Deception"},
    {"name": "盲僧", "emoji": "👁️‍🗨️👊🦵", "title": "盲僧", "quote": "双眼失明丝毫不影响我追捕敌人", "region": "艾欧尼亚",
     "aliases": ["lee sin", "lee", "leesin", "盲僧", "李青", "瞎子", "li qing"],
     "name_en": "Lee Sin",
     "title_en": "the Blind Monk",
     "quote_en": "Blindness is no impairment against a smelly enemy.",
     "region_en": "Ionia",
     "skill_q": "天音波",
     "skill_q_en": "Sonic Wave"},
    {"name": "提莫", "emoji": "🐹🍄💨", "title": "迅捷斥候", "quote": "我去前面探探路", "region": "班德尔城",
     "aliases": ["teemo", "ti mo", "提莫"],
     "name_en": "Teemo",
     "title_en": "the Swift Scout",
     "quote_en": "I'll scout ahead!",
     "region_en": "Bandle City",
     "skill_q": "致盲吹箭",
     "skill_q_en": "Blinding Dart"},
    {"name": "金克丝", "emoji": "💣🔫😈", "title": "暴走萝莉", "quote": "规则就是用来打破的！", "region": "祖安",
     "aliases": ["jinx", "jin ke si", "金克丝", "金克斯"],
     "name_en": "Jinx",
     "title_en": "the Loose Cannon",
     "quote_en": "Rules are meant to be broken!",
     "region_en": "Zaun",
     "skill_q": "枪炮交响曲",
     "skill_q_en": "Switcheroo!"},
    {"name": "德莱厄斯", "emoji": "🪓🩸💪", "title": "诺克萨斯之手", "quote": "诺克萨斯即将崛起", "region": "诺克萨斯",
     "aliases": ["darius", "da rui si", "德莱厄斯", "诺手", "诺克萨斯之手"],
     "name_en": "Darius",
     "title_en": "the Hand of Noxus",
     "quote_en": "Noxus will rise!",
     "region_en": "Noxus",
     "skill_q": "大杀四方",
     "skill_q_en": "Decimate"},
    {"name": "伊泽瑞尔", "emoji": "✨🏹💛", "title": "探险家", "quote": "是时候表演真正的技术了", "region": "皮尔特沃夫",
     "aliases": ["ezreal", "ez", "e z", "伊泽瑞尔", "ezreal"],
     "name_en": "Ezreal",
     "title_en": "the Prodigal Explorer",
     "quote_en": "Time for a true display of skill!",
     "region_en": "Piltover",
     "skill_q": "秘术射击",
     "skill_q_en": "Mystic Shot"},
    {"name": "拉克丝", "emoji": "💡✨👧", "title": "光辉女郎", "quote": "照亮前进的道路", "region": "德玛西亚",
     "aliases": ["lux", "la ke si", "拉克丝", "光辉"],
     "name_en": "Lux",
     "title_en": "the Lady of Luminosity",
     "quote_en": "Light up the path ahead.",
     "region_en": "Demacia",
     "skill_q": "光之束缚",
     "skill_q_en": "Light Binding"},
    {"name": "菲奥娜", "emoji": "🤺👩💙", "title": "无双剑姬", "quote": "我渴望有价值的对手", "region": "德玛西亚",
     "aliases": ["fiora", "fei ao na", "菲奥娜", "剑姬", "jj"],
     "name_en": "Fiora",
     "title_en": "the Grand Duelist",
     "quote_en": "I long for a worthy opponent.",
     "region_en": "Demacia",
     "skill_q": "破空斩",
     "skill_q_en": "Lunge"},
    {"name": "卡莎", "emoji": "🦋💜🏹", "title": "虚空之女", "quote": "我的外表下藏着什么？", "region": "虚空",
     "aliases": ["kaisa", "kai sa", "卡莎", "kasha", "ks"],
     "name_en": "Kai'Sa",
     "title_en": "Daughter of the Void",
     "quote_en": "What lies beneath my surface?",
     "region_en": "The Void",
     "skill_q": "艾卡西亚暴雨",
     "skill_q_en": "Icathian Rain"},
    {"name": "永恩", "emoji": "🗡️😈💀", "title": "封魔剑魂", "quote": "两条道路，一把剑", "region": "艾欧尼亚",
     "aliases": ["yone", "yong en", "永恩"],
     "name_en": "Yone",
     "title_en": "the Unforgotten",
     "quote_en": "Two paths, one blade.",
     "region_en": "Ionia",
     "skill_q": "错玉切",
     "skill_q_en": "Mortal Steel"},
    {"name": "塞纳", "emoji": "🔫💡👻", "title": "涤魂圣枪", "quote": "我从死亡中归来", "region": "暗影岛",
     "aliases": ["senna", "sai na", "塞纳"],
     "name_en": "Senna",
     "title_en": "the Redeemer",
     "quote_en": "I returned from death.",
     "region_en": "Shadow Isles",
     "skill_q": "黑暗洞灭",
     "skill_q_en": "Piercing Darkness"},
    {"name": "艾克", "emoji": "⏰💚🔧", "title": "时间刺客", "quote": "时间不站在你那边", "region": "祖安",
     "aliases": ["ekko", "ai ke", "艾克"],
     "name_en": "Ekko",
     "title_en": "the Boy Who Shattered Time",
     "quote_en": "Time is not on your side.",
     "region_en": "Zaun",
     "skill_q": "时间卷曲器",
     "skill_q_en": "Timewinder"},
    {"name": "瑟提", "emoji": "👊💪🔥", "title": "腕豪", "quote": "我妈说我打得不错", "region": "艾欧尼亚",
     "aliases": ["sett", "se ti", "瑟提", "腕豪"],
     "name_en": "Sett",
     "title_en": "the Boss",
     "quote_en": "My mom says I'm the best.",
     "region_en": "Ionia",
     "skill_q": "屈人之威",
     "skill_q_en": "Knuckle Down"},
    {"name": "烬", "emoji": "🎭🔫🎨", "title": "戏命师", "quote": "艺术，应当震慑人心", "region": "艾欧尼亚",
     "aliases": ["jhin", "jin", "烬"],
     "name_en": "Jhin",
     "title_en": "the Virtuoso",
     "quote_en": "Art should terrify.",
     "region_en": "Ionia",
     "skill_q": "低语",
     "skill_q_en": "Dancing Grenade"},
    {"name": "阿卡丽", "emoji": "🗡️💨💚", "title": "离群之刺", "quote": "均衡，脆弱无比", "region": "艾欧尼亚",
     "aliases": ["akali", "a ka li", "阿卡丽"],
     "name_en": "Akali",
     "title_en": "the Rogue Assassin",
     "quote_en": "Balance is fragile.",
     "region_en": "Ionia",
     "skill_q": "我流奥义！寒影",
     "skill_q_en": "Five Point Strike"},
    {"name": "莫甘娜", "emoji": "😇😈🪶", "title": "堕落天使", "quote": "我会叫他们忏悔", "region": "德玛西亚",
     "aliases": ["morgana", "mo gan na", "莫甘娜"],
     "name_en": "Morgana",
     "title_en": "the Fallen",
     "quote_en": "I will make them repent.",
     "region_en": "Demacia",
     "skill_q": "暗之禁锢",
     "skill_q_en": "Dark Binding"},
    {"name": "凯尔", "emoji": "😇⚔️🔥", "title": "正义天使", "quote": "审判将至", "region": "德玛西亚",
     "aliases": ["kayle", "kai er", "凯尔"],
     "name_en": "Kayle",
     "title_en": "the Righteous",
     "quote_en": "Judgment is coming.",
     "region_en": "Demacia",
     "skill_q": "耀焰冲击",
     "skill_q_en": "Radiant Blast"},
    {"name": "派克", "emoji": "🦈🔪💀", "title": "血港鬼影", "quote": "死人的名单上又多了一个名字", "region": "比尔吉沃特",
     "aliases": ["pyke", "pai ke", "派克"],
     "name_en": "Pyke",
     "title_en": "the Bloodharbor Ripper",
     "quote_en": "Another name on the dead man's list.",
     "region_en": "Bilgewater",
     "skill_q": "透骨尖钉",
     "skill_q_en": "Bone Skewer"},
    {"name": "俄洛伊", "emoji": "🐙💪🌊", "title": "海兽祭司", "quote": "运动就是生命", "region": "比尔吉沃特",
     "aliases": ["illaoi", "俄洛伊"],
     "name_en": "Illaoi",
     "title_en": "the Kraken Priestess",
     "quote_en": "Motion is life.",
     "region_en": "Bilgewater",
     "skill_q": "触手猛击",
     "skill_q_en": "Tentacle Smash"},
    {"name": "塞拉斯", "emoji": "⛓️💪🔥", "title": "解脱者", "quote": "德玛西亚必将灭亡", "region": "德玛西亚",
     "aliases": ["sylas", "sai la si", "塞拉斯"],
     "name_en": "Sylas",
     "title_en": "the Unshackled",
     "quote_en": "Demacia must fall!",
     "region_en": "Demacia",
     "skill_q": "锁链鞭击",
     "skill_q_en": "Chain Lash"},
    {"name": "卡莎碧亚", "emoji": "🐍💚👩", "title": "魔蛇之拥", "quote": "别那么快嘛~", "region": "诺克萨斯",
     "aliases": ["cassiopeia", "ka sha bi ya", "卡莎碧亚", "蛇女"],
     "name_en": "Cassiopeia",
     "title_en": "the Serpent's Embrace",
     "quote_en": "Don't be so fast.",
     "region_en": "Noxus",
     "skill_q": "瘟毒爆炸",
     "skill_q_en": "Noxious Blast"},
    {"name": "卡特琳娜", "emoji": "🗡️💃🔴", "title": "不祥之刃", "quote": "暴力可以解决一切", "region": "诺克萨斯",
     "aliases": ["katarina", "ka te lin na", "卡特琳娜", "卡特"],
     "name_en": "Katarina",
     "title_en": "the Sinister Blade",
     "quote_en": "Violence solves everything.",
     "region_en": "Noxus",
     "skill_q": "弹射之刃",
     "skill_q_en": "Bouncing Blade"},
    {"name": "薇恩", "emoji": "🏹🌙🦇", "title": "暗夜猎手", "quote": "净化元素，圣银", "region": "德玛西亚",
     "aliases": ["vayne", "vn", "wei en", "薇恩"],
     "name_en": "Vayne",
     "title_en": "the Night Hunter",
     "quote_en": "Purge with silver.",
     "region_en": "Demacia",
     "skill_q": "闪避突袭",
     "skill_q_en": "Tumble"},
    {"name": "泰达米尔", "emoji": "⚔️😡💪", "title": "蛮族之王", "quote": "我的大刀早已饥渴难耐", "region": "弗雷尔卓德",
     "aliases": ["tryndamere", "tai da mi er", "泰达米尔", "蛮王"],
     "name_en": "Tryndamere",
     "title_en": "the Barbarian King",
     "quote_en": "My blade thirsts.",
     "region_en": "Freljord",
     "skill_q": "嗜血杀戮",
     "skill_q_en": "Bloodlust"},
    {"name": "奥拉夫", "emoji": "🪓😡⚡", "title": "狂战士", "quote": "所到之处，寸草不生", "region": "弗雷尔卓德",
     "aliases": ["olaf", "ao la fu", "奥拉夫"],
     "name_en": "Olaf",
     "title_en": "the Berserker",
     "quote_en": "Leave nothing behind.",
     "region_en": "Freljord",
     "skill_q": "逆流投掷",
     "skill_q_en": "Undertow"},
    {"name": "瑟庄妮", "emoji": "🐗❄️🛡️", "title": "凛冬之怒", "quote": "弗雷尔卓德，永不屈服", "region": "弗雷尔卓德",
     "aliases": ["sejuani", "se zhuang ni", "瑟庄妮", "猪妹"],
     "name_en": "Sejuani",
     "title_en": "Fury of the North",
     "quote_en": "The Freljord will never yield.",
     "region_en": "Freljord",
     "skill_q": "极寒突袭",
     "skill_q_en": "Arctic Assault"},
    {"name": "布隆", "emoji": "🛡️💪❄️", "title": "弗雷尔卓德之心", "quote": "站在布隆后面！", "region": "弗雷尔卓德",
     "aliases": ["braum", "bu long", "布隆"],
     "name_en": "Braum",
     "title_en": "the Heart of the Freljord",
     "quote_en": "Stand behind Braum!",
     "region_en": "Freljord",
     "skill_q": "寒冬之咬",
     "skill_q_en": "Winter's Bite"},
    {"name": "锤石", "emoji": "⛓️💀🔗", "title": "魂锁典狱长", "quote": "你的灵魂将受折磨", "region": "暗影岛",
     "aliases": ["thresh", "chui shi", "锤石"],
     "name_en": "Thresh",
     "title_en": "the Chain Warden",
     "quote_en": "Your soul will be tormented.",
     "region_en": "Shadow Isles",
     "skill_q": "死亡判决",
     "skill_q_en": "Death Sentence"},
    {"name": "赫卡里姆", "emoji": "🐴💀🔥", "title": "战争之影", "quote": "粉碎他们的防线", "region": "暗影岛",
     "aliases": ["hecarim", "he ka li mu", "赫卡里姆", "人马"],
     "name_en": "Hecarim",
     "title_en": "the Shadow of War",
     "quote_en": "Shatter their lines!",
     "region_en": "Shadow Isles",
     "skill_q": "暴走",
     "skill_q_en": "Rampage"},
    {"name": "卡尔萨斯", "emoji": "💀🎵👻", "title": "死亡颂唱者", "quote": "安息吧", "region": "暗影岛",
     "aliases": ["karthus", "ka er sa si", "卡尔萨斯", "死歌"],
     "name_en": "Karthus",
     "title_en": "the Deathsinger",
     "quote_en": "Rest in peace.",
     "region_en": "Shadow Isles",
     "skill_q": "荒芜",
     "skill_q_en": "Lay Waste"},
    {"name": "弗拉基米尔", "emoji": "🩸🧛🦇", "title": "猩红收割者", "quote": "血流成河", "region": "诺克萨斯",
     "aliases": ["vladimir", "fu la ji mi er", "弗拉基米尔", "吸血鬼"],
     "name_en": "Vladimir",
     "title_en": "the Crimson Reaper",
     "quote_en": "The rivers will run red.",
     "region_en": "Noxus",
     "skill_q": "鲜血转换",
     "skill_q_en": "Transfusion"},
    {"name": "伊莉丝", "emoji": "🕷️🕸️👩", "title": "蜘蛛女皇", "quote": "只有弱者才畏惧黑暗", "region": "暗影岛",
     "aliases": ["elise", "yi li si", "伊莉丝", "蜘蛛"],
     "name_en": "Elise",
     "title_en": "the Spider Queen",
     "quote_en": "Only the weak fear the dark.",
     "region_en": "Shadow Isles",
     "skill_q": "神经毒素",
     "skill_q_en": "Neurotoxin"},
    {"name": "凯隐", "emoji": "🗡️😈💙", "title": "影流之镰", "quote": "暗裔还是刺客，这是个问题", "region": "艾欧尼亚",
     "aliases": ["kayn", "kai yin", "凯隐"],
     "name_en": "Kayn",
     "title_en": "the Shadow Reaper",
     "quote_en": "Darkin or assassin, that is the question.",
     "region_en": "Ionia",
     "skill_q": "巨镰横扫",
     "skill_q_en": "Reaping Slash"},
    {"name": "千珏", "emoji": "🐑🐺🏹", "title": "永猎双子", "quote": "所有人，终有一死", "region": "符文之地",
     "aliases": ["kindred", "qian jue", "千珏"],
     "name_en": "Kindred",
     "title_en": "the Eternal Hunters",
     "quote_en": "All must die.",
     "region_en": "Runeterra",
     "skill_q": "乱箭之舞",
     "skill_q_en": "Dance of Arrows"},
    {"name": "巴德", "emoji": "🎵🌟🛸", "title": "星界游神", "quote": "*~音效~*", "region": "宇宙",
     "aliases": ["bard", "ba de", "巴德"],
     "name_en": "Bard",
     "title_en": "the Wandering Caretaker",
     "quote_en": "*~chimes~*",
     "region_en": "The Cosmos",
     "skill_q": "星体束缚",
     "skill_q_en": "Cosmic Binding"},
    {"name": "奥恩", "emoji": "🔨🔥🐏", "title": "山隐之焰", "quote": "一切都可以打造", "region": "弗雷尔卓德",
     "aliases": ["ornn", "ao en", "奥恩"],
     "name_en": "Ornn",
     "title_en": "the Fire Below the Mountain",
     "quote_en": "Everything can be forged.",
     "region_en": "Freljord",
     "skill_q": "火山突堑",
     "skill_q_en": "Volcanic Rupture"},
    {"name": "潘森", "emoji": "🛡️🗡️⭐", "title": "不屈之枪", "quote": "天神已死，凡人永存", "region": "巨神峰",
     "aliases": ["pantheon", "pan sen", "潘森"],
     "name_en": "Pantheon",
     "title_en": "the Unbreakable Spear",
     "quote_en": "The gods are dead; mortals live on.",
     "region_en": "Mount Targon",
     "skill_q": "贯星长枪",
     "skill_q_en": "Comet Spear"},
    {"name": "蕾欧娜", "emoji": "☀️🛡️⚔️", "title": "曙光女神", "quote": "黎明就在眼前", "region": "巨神峰",
     "aliases": ["leona", "lei ou na", "蕾欧娜", "日女"],
     "name_en": "Leona",
     "title_en": "the Radiant Dawn",
     "quote_en": "Dawn is upon us.",
     "region_en": "Mount Targon",
     "skill_q": "破晓之盾",
     "skill_q_en": "Shield of Daybreak"},
    {"name": "佐伊", "emoji": "🌟😴💜", "title": "暮光星灵", "quote": "你看起来很好吃！", "region": "巨神峰",
     "aliases": ["zoe", "zuo yi", "佐伊"],
     "name_en": "Zoe",
     "title_en": "the Aspect of Twilight",
     "quote_en": "You look delicious!",
     "region_en": "Mount Targon",
     "skill_q": "飞星乱入",
     "skill_q_en": "Paddle Star"},
    {"name": "娑娜", "emoji": "🎵🎻💙", "title": "琴瑟仙女", "quote": "*无声的旋律*", "region": "德玛西亚",
     "aliases": ["sona", "suo na", "娑娜", "琴女"],
     "name_en": "Sona",
     "title_en": "Maven of the Strings",
     "quote_en": "*silent melody*",
     "region_en": "Demacia",
     "skill_q": "英勇赞美诗",
     "skill_q_en": "Hymn of Valor"},
    {"name": "莫德凯撒", "emoji": "👑💀🔥", "title": "铁铠冥魂", "quote": "我即是死亡", "region": "暗影岛",
     "aliases": ["mordekaiser", "mo de kai sa", "莫德凯撒", "铁男"],
     "name_en": "Mordekaiser",
     "title_en": "the Iron Revenant",
     "quote_en": "I am death itself.",
     "region_en": "Shadow Isles",
     "skill_q": "破灭之锤",
     "skill_q_en": "Obliterate"},
    {"name": "维克托", "emoji": "🤖🔧⚡", "title": "机械先驱", "quote": "光荣的进化", "region": "祖安",
     "aliases": ["viktor", "wei ke tuo", "维克托"],
     "name_en": "Viktor",
     "title_en": "the Machine Herald",
     "quote_en": "Glorious evolution.",
     "region_en": "Zaun",
     "skill_q": "虹吸能量",
     "skill_q_en": "Siphon Power"},
    {"name": "蒙多", "emoji": "💉💪🟣", "title": "祖安狂人", "quote": "蒙多觉得你是个大娘们！", "region": "祖安",
     "aliases": ["mundo", "meng duo", "蒙多"],
     "name_en": "Dr. Mundo",
     "title_en": "the Madman of Zaun",
     "quote_en": "Mundo thinks you're a big sissy!",
     "region_en": "Zaun",
     "skill_q": "病毒屠刀",
     "skill_q_en": "Infected Bonesaw"},
    {"name": "扎克", "emoji": "🟢💧💪", "title": "生化魔人", "quote": "我不是史莱姆！", "region": "祖安",
     "aliases": ["zac", "za ke", "扎克"],
     "name_en": "Zac",
     "title_en": "the Secret Weapon",
     "quote_en": "I'm not a slime!",
     "region_en": "Zaun",
     "skill_q": "延伸打击",
     "skill_q_en": "Stretching Strike"},
    {"name": "厄加特", "emoji": "🦀🔫🤖", "title": "无畏战车", "quote": "你不过是一堆零件", "region": "祖安",
     "aliases": ["urgot", "e jia te", "厄加特", "螃蟹"],
     "name_en": "Urgot",
     "title_en": "the Dreadnought",
     "quote_en": "You're nothing but scrap.",
     "region_en": "Zaun",
     "skill_q": "腐蚀电荷",
     "skill_q_en": "Corrosive Charge"},
    {"name": "吉格斯", "emoji": "💣😈🔥", "title": "爆破鬼才", "quote": "来，炸个痛快！", "region": "祖安",
     "aliases": ["ziggs", "ji ge si", "吉格斯", "炸弹人"],
     "name_en": "Ziggs",
     "title_en": "the Hexplosives Expert",
     "quote_en": "Come on, blow something up!",
     "region_en": "Zaun",
     "skill_q": "弹跳炸弹",
     "skill_q_en": "Bouncing Bomb"},
    {"name": "塔姆", "emoji": "🐸👅🐟", "title": "河流之王", "quote": "叫我国王，叫我恶魔", "region": "比尔吉沃特",
     "aliases": ["tahm kench", "tahm", "ta mu", "塔姆", "蛤蟆"],
     "name_en": "Tahm Kench",
     "title_en": "the River King",
     "quote_en": "Call me king, call me demon.",
     "region_en": "Bilgewater",
     "skill_q": "巨舌鞭笞",
     "skill_q_en": "Tongue Lash"},
    {"name": "崔丝塔娜", "emoji": "🔫🐹💥", "title": "麦林炮手", "quote": "我看见你了！", "region": "班德尔城",
     "aliases": ["tristana", "cui si ta na", "崔丝塔娜", "小炮"],
     "name_en": "Tristana",
     "title_en": "the Yordle Gunner",
     "quote_en": "I see you!",
     "region_en": "Bandle City",
     "skill_q": "急速射击",
     "skill_q_en": "Rapid Fire"},
    {"name": "璐璐", "emoji": "🧚💜✨", "title": "仙灵女巫", "quote": "那东西尝起来像紫色", "region": "班德尔城",
     "aliases": ["lulu", "lu lu", "璐璐"],
     "name_en": "Lulu",
     "title_en": "the Fae Sorceress",
     "quote_en": "That tasted purple!",
     "region_en": "Bandle City",
     "skill_q": "闪耀长枪",
     "skill_q_en": "Glitterlance"},
    {"name": "维迦", "emoji": "🧙⚫😈", "title": "邪恶小法师", "quote": "我是魔鬼！不许笑！", "region": "班德尔城",
     "aliases": ["veigar", "wei jia", "维迦", "小法师", "邪恶小法师"],
     "name_en": "Veigar",
     "title_en": "the Tiny Master of Evil",
     "quote_en": "I am evil! Stop laughing!",
     "region_en": "Bandle City",
     "skill_q": "黑暗祭祀",
     "skill_q_en": "Baleful Strike"},
    {"name": "纳尔", "emoji": "🦖😡❄️", "title": "迷失之牙", "quote": "纳尔，生气了！", "region": "弗雷尔卓德",
     "aliases": ["gnar", "na er", "纳尔", "小纳尔", "monster"],
     "name_en": "Gnar",
     "title_en": "the Missing Link",
     "quote_en": "Gnar, angry!",
     "region_en": "Freljord",
     "skill_q": "投掷回力标",
     "skill_q_en": "Boomerang Throw"},
    {"name": "克烈", "emoji": "🦎😡🔫", "title": "暴怒骑士", "quote": "冲啊啊啊啊！", "region": "诺克萨斯",
     "aliases": ["kled", "ke lie", "克烈"],
     "name_en": "Kled",
     "title_en": "the Cantankerous Cavalier",
     "quote_en": "Chaaaaaarge!",
     "region_en": "Noxus",
     "skill_q": "飞索捕熊器",
     "skill_q_en": "Bear Trap on a Rope"},
    {"name": "德莱文", "emoji": "🪓🪓🧔", "title": "荣耀行刑官", "quote": "欢迎来到德莱联盟", "region": "诺克萨斯",
     "aliases": ["draven", "de lai wen", "德莱文"],
     "name_en": "Draven",
     "title_en": "the Glorious Executioner",
     "quote_en": "Welcome to the League of Draven.",
     "region_en": "Noxus",
     "skill_q": "旋转飞斧",
     "skill_q_en": "Spinning Axe"},
    {"name": "慎", "emoji": "⚔️⚡🤖", "title": "暮光之眼", "quote": "均衡存乎万物之间", "region": "艾欧尼亚",
     "aliases": ["shen", "shen", "慎"],
     "name_en": "Shen",
     "title_en": "the Eye of Twilight",
     "quote_en": "Balance in all things.",
     "region_en": "Ionia",
     "skill_q": "奥义！却邪",
     "skill_q_en": "Twilight Assault"},
    {"name": "凯南", "emoji": "⚡🐹🗡️", "title": "狂暴之心", "quote": "均衡，不容破坏", "region": "艾欧尼亚",
     "aliases": ["kennen", "kai nan", "凯南"],
     "name_en": "Kennen",
     "title_en": "the Heart of the Tempest",
     "quote_en": "Balance must not be broken.",
     "region_en": "Ionia",
     "skill_q": "雷电手里剑",
     "skill_q_en": "Thundering Shuriken"},
    {"name": "辛德拉", "emoji": "⚫🌀👑", "title": "暗黑元首", "quote": "我的潜能，无穷无尽", "region": "艾欧尼亚",
     "aliases": ["syndra", "xin de la", "辛德拉"],
     "name_en": "Syndra",
     "title_en": "the Dark Sovereign",
     "quote_en": "My potential is limitless.",
     "region_en": "Ionia",
     "skill_q": "暗黑法球",
     "skill_q_en": "Dark Sphere"},
    {"name": "卢锡安", "emoji": "🔫🔫🖤", "title": "圣枪游侠", "quote": "净化她！", "region": "暗影岛",
     "aliases": ["lucian", "lu xi an", "卢锡安", "奥巴马"],
     "name_en": "Lucian",
     "title_en": "the Purifier",
     "quote_en": "Purge her!",
     "region_en": "Shadow Isles",
     "skill_q": "透体圣光",
     "skill_q_en": "Piercing Light"},
    {"name": "格雷福斯", "emoji": "🔫💨🧔", "title": "法外狂徒", "quote": "死路一条", "region": "比尔吉沃特",
     "aliases": ["graves", "ge lei fu si", "格雷福斯", "男枪"],
     "name_en": "Graves",
     "title_en": "the Outlaw",
     "quote_en": "Dead man walking.",
     "region_en": "Bilgewater",
     "skill_q": "穷途末路",
     "skill_q_en": "End of the Line"},
    {"name": "崔斯特", "emoji": "🃏🎩🔮", "title": "卡牌大师", "quote": "幸运女神在微笑", "region": "比尔吉沃特",
     "aliases": ["twisted fate", "tf", "cui si te", "崔斯特", "卡牌"],
     "name_en": "Twisted Fate",
     "title_en": "the Card Master",
     "quote_en": "Lady Luck is smilin'.",
     "region_en": "Bilgewater",
     "skill_q": "万能牌",
     "skill_q_en": "Wild Cards"},
    {"name": "萨科", "emoji": "🤡🔪🎭", "title": "恶魔小丑", "quote": "来次魔术戏法，怎么样？", "region": "符文之地",
     "aliases": ["shaco", "sa ke", "萨科", "小丑"],
     "name_en": "Shaco",
     "title_en": "the Demon Jester",
     "quote_en": "How about a magic trick?",
     "region_en": "Runeterra",
     "skill_q": "欺诈魔术",
     "skill_q_en": "Deceive"},
    {"name": "亚托克斯", "emoji": "🗡️😈🩸", "title": "暗裔剑魔", "quote": "我曾经是神", "region": "恕瑞玛",
     "aliases": ["aatrox", "ya tuo ke si", "亚托克斯", "剑魔", "暗裔剑魔"],
     "name_en": "Aatrox",
     "title_en": "the Darkin Blade",
     "quote_en": "I was once a god.",
     "region_en": "Shurima",
     "skill_q": "暗裔利刃",
     "skill_q_en": "The Darkin Blade"},
    {"name": "内瑟斯", "emoji": "🐶📖⚡", "title": "沙漠死神", "quote": "生与死，轮回不止", "region": "恕瑞玛",
     "aliases": ["nasus", "nei se si", "内瑟斯", "狗头"],
     "name_en": "Nasus",
     "title_en": "the Curator of the Sands",
     "quote_en": "Life and death, in an endless cycle.",
     "region_en": "Shurima",
     "skill_q": "汲魂痛击",
     "skill_q_en": "Siphoning Strike"},
    {"name": "阿兹尔", "emoji": "🦅🏜️👑", "title": "沙漠皇帝", "quote": "恕瑞玛，你的皇帝回来了", "region": "恕瑞玛",
     "aliases": ["azir", "a zi er", "阿兹尔", "沙皇"],
     "name_en": "Azir",
     "title_en": "the Emperor of the Sands",
     "quote_en": "Shurima, your emperor has returned.",
     "region_en": "Shurima",
     "skill_q": "征服者",
     "skill_q_en": "Conquering Sands"},
]


class GuessChampion(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_game: dict[int, dict] = {}  # channel_id -> game_state

    @app_commands.command(name="gmpt-guess-champion", description="猜英雄！根据提示猜 LOL 英雄 / Guess the champion")
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def guess_champ_cmd(self, interaction: discord.Interaction):
        uid = interaction.user.id
        blocked, used, remaining = _check_daily_limit(uid, 'guess_champion')
        if blocked:
            return await interaction.response.send_message(
                "你今天已玩了 3 次猜英雄，明天再来！\nYou've played 3 times today, come back tomorrow!",
                ephemeral=True,
            )

        cid = interaction.channel_id
        if cid in self.active_game:
            return await interaction.response.send_message(
                "当前频道已经有进行中的猜英雄！请稍等 / A champion guessing game is already in progress.", ephemeral=True
            )

        champion = random.choice(CHAMPIONS)
        state = {
            "champion": champion,
            "guessed": set(),
            "round": 0,
            "solved": False,
        }
        self.active_game[cid] = state

        await interaction.response.send_message(
            "🕵️‍♂️ **猜英雄 Guess the Champion！**\n"
            "🎮 我将给出 3 个提示，难度依次降低\n"
            "🌐 I'll give 3 hints, difficulty decreases each time\n"
            f"💎 提示 1 猜对 = 200💰 | 提示 2 = 100💰 | 提示 3 = 50💰\n"
            f"💰 Hint 1 correct = 200 | Hint 2 = 100 | Hint 3 = 50\n"
            f"📊 剩余次数 / Remaining: {remaining}/3"
        )

        hints = [
            f"🔍 **提示 1 / Hint 1:** {champion['emoji']}\n💎 +200💰",
            f"🔍 **提示 2 / Hint 2:**\n称号: {champion['title']} | Title: {champion.get('title_en', champion['title'])}\n台词: \"{champion['quote']}\" | Quote: \"{champion.get('quote_en', champion['quote'])}\"\n💎 +100💰",
            f"🔍 **提示 3 / Hint 3:**\n地区: {champion['region']} | Region: {champion.get('region_en', champion['region'])}\nQ技能: {champion.get('skill_q', '???')} | Q: {champion.get('skill_q_en', '???')}\n💎 +50💰",
        ]

        rewards = [200, 100, 50]

        for round_num in range(3):
            if state["solved"]:
                break
            state["round"] = round_num
            await interaction.channel.send(hints[round_num])

            try:
                def check(m: discord.Message):
                    if m.channel.id != cid or m.author.bot:
                        return False
                    return str(m.author.id) not in state["guessed"]

                msg = await self.bot.wait_for("message", timeout=10.0, check=check)
                uid = str(msg.author.id)
                state["guessed"].add(uid)

                guess = msg.content.strip().lower()
                champ_aliases = [a.lower() for a in champion["aliases"]]

                if guess in champ_aliases:
                    reward = rewards[round_num]
                    _add_coins(uid, reward, f"Guess Champion / 猜英雄正确 — {champion['name']}")
                    await interaction.channel.send(
                        f"✅ **{msg.author.mention} 猜对了！**\n"
                        f"🎯 答案: **{champion['name']}** ({champion.get('name_en', '')})\n"
                        f"🏷️ {champion['title']} | {champion.get('title_en', champion['title'])}\n"
                        f"💰 +{reward}💰"
                    )
                    state["solved"] = True
                else:
                    await msg.add_reaction("❌")
            except asyncio.TimeoutError:
                continue

        if not state["solved"]:
            await interaction.channel.send(
                f"⏰ 时间到！答案是 **{champion['name']}** ({champion.get('name_en', '')}) — {champion['title']} | {champion.get('title_en', champion['title'])}，无人得奖 / No one guessed correctly."
            )

        self.active_game.pop(cid, None)

    @guess_champ_cmd.error
    async def guess_champ_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            remaining = int(error.retry_after)
            msg = f"⏳ 冷却中，请等 {remaining} 秒 / Cooldown, wait {remaining}s."
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
        else:
            log_error("guess_champion", interaction.command.name if interaction.command else "unknown", error)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("发生错误 / An error occurred.", ephemeral=True)
                else:
                    await interaction.followup.send("发生错误 / An error occurred.", ephemeral=True)
            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(GuessChampion(bot))
