"""
GMPT Bot — Trivia Quiz (LOL / Esports) — Bilingual (中文 / English)
"""
import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
import logging
from utils.logger import log_error

logger = logging.getLogger(__name__)

# ── Economy helper ──
def _add_coins(uid: str, amount: int, reason: str):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (discord_id, username) VALUES (?, 'unknown') ON CONFLICT(discord_id) DO NOTHING",
        (uid,),
    )
    cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, uid))
    cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)", (uid, amount, reason))
    conn.commit(); conn.close()


# ── Trivia question pool (bilingual) ──
TRIVIA_QUESTIONS = [
    {
        "q_zh": "亚索的被动技能叫什么？",
        "q_en": "What is Yasuo's passive ability called?",
        "options_zh": ["浪客之道", "疾风斩", "风之屏障", "踏前斩"],
        "options_en": ["Way of the Wanderer", "Last Breath", "Wind Wall", "Sweeping Blade"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "2024 全球总决赛冠军是哪个队伍？",
        "q_en": "Which team won the 2024 World Championship?",
        "options_zh": ["T1", "GEN", "BLG", "WBG"],
        "options_en": ["T1", "GEN", "BLG", "WBG"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "以下哪个装备提供法术穿透？",
        "q_en": "Which item provides magic penetration?",
        "options_zh": ["虚空之杖", "无尽之刃", "破败王者之刃", "饮血剑"],
        "options_en": ["Void Staff", "Infinity Edge", "Blade of the Ruined King", "Bloodthirster"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "李青的终极技能叫什么？",
        "q_en": "What is Lee Sin's ultimate ability called?",
        "options_zh": ["天音波", "猛龙摆尾", "金钟罩", "摧筋断骨"],
        "options_en": ["Sonic Wave", "Dragon's Rage", "Safeguard", "Cripple"],
        "answer": 1,
        "reward": 50
    },
    {
        "q_zh": "峡谷中的纳什男爵在游戏开始多少分钟后刷新？",
        "q_en": "How many minutes into the game does Baron Nashor spawn?",
        "options_zh": ["20分钟", "15分钟", "25分钟", "10分钟"],
        "options_en": ["20 min", "15 min", "25 min", "10 min"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "阿狸的定位是什么？",
        "q_en": "What is Ahri's role?",
        "options_zh": ["辅助", "坦克", "法师/刺客", "射手"],
        "options_en": ["Support", "Tank", "Mage/Assassin", "Marksman"],
        "answer": 2,
        "reward": 50
    },
    {
        "q_zh": "以下哪个是无限火力的特征？",
        "q_en": "Which of these is a feature of URF (Ultra Rapid Fire)?",
        "options_zh": ["无冷却", "80%冷却缩减", "无限金钱", "无蓝耗"],
        "options_en": ["No cooldowns", "80% CDR", "Unlimited gold", "No mana cost"],
        "answer": 1,
        "reward": 50
    },
    {
        "q_zh": "提莫的被动技能效果是什么？",
        "q_en": "What is Teemo's passive ability effect?",
        "options_zh": ["加速", "回血", "致盲", "短时间不动后隐身"],
        "options_en": ["Speed boost", "Heal", "Blind", "Invisibility after standing still"],
        "answer": 3,
        "reward": 50
    },
    {
        "q_zh": "MSI 的全称是什么？",
        "q_en": "What does MSI stand for?",
        "options_zh": ["Mid-Season Invitational", "Major Series International", "Mega Season Invite", "Mid-Season International"],
        "options_en": ["Mid-Season Invitational", "Major Series International", "Mega Season Invite", "Mid-Season International"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "以下哪个英雄来自艾欧尼亚？",
        "q_en": "Which champion is from Ionia?",
        "options_zh": ["德莱厄斯", "艾瑞莉娅", "盖伦", "瑟庄妮"],
        "options_en": ["Darius", "Irelia", "Garen", "Sejuani"],
        "answer": 1,
        "reward": 50
    },
    {
        "q_zh": "峡谷先锋在游戏内叫什么？",
        "q_en": "What is the Rift Herald called in-game?",
        "options_zh": ["峡谷巨兽", "峡谷守护者", "Rift Herald / 峡谷先锋", "峡谷领主"],
        "options_en": ["Rift Beast", "Rift Guardian", "Rift Herald", "Rift Lord"],
        "answer": 2,
        "reward": 50
    },
    {
        "q_zh": "烬的被动技能会让他获得什么？",
        "q_en": "What does Jhin's passive grant him?",
        "options_zh": ["第四发必暴击且加移速", "无限弹药", "隐身", "额外生命值"],
        "options_en": ["4th shot guaranteed crit + movespeed", "Unlimited ammo", "Invisibility", "Bonus HP"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "LOL 中有多少条元素龙类型？",
        "q_en": "How many types of Elemental Drakes are there in LoL?",
        "options_zh": ["4", "5", "3", "6"],
        "options_en": ["4", "5", "3", "6"],
        "answer": 3,
        "reward": 50
    },
    {
        "q_zh": "凯特琳的称号是什么？",
        "q_en": "What is Caitlyn's title?",
        "options_zh": ["赏金猎人", "皮城女警", "暗夜猎手", "枪火狂徒"],
        "options_en": ["The Bounty Hunter", "The Sheriff of Piltover", "The Night Hunter", "The Gunslinger"],
        "answer": 1,
        "reward": 50
    },
    {
        "q_zh": "2023 全球总决赛冠军是哪个队伍？",
        "q_en": "Which team won the 2023 World Championship?",
        "options_zh": ["T1", "DRX", "JDG", "WBG"],
        "options_en": ["T1", "DRX", "JDG", "WBG"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "以下哪个英雄的技能可以格挡飞行道具？",
        "q_en": "Which champion can block projectiles with an ability?",
        "options_zh": ["盖伦", "赵信", "亚索", "劫"],
        "options_en": ["Garen", "Xin Zhao", "Yasuo", "Zed"],
        "answer": 2,
        "reward": 50
    },
    {
        "q_zh": "LPL 的下路双人组通常包括哪两个角色？",
        "q_en": "Which two roles make up the bot lane duo?",
        "options_zh": ["ADC + 辅助", "中单 + 打野", "上单 + 打野", "双法师"],
        "options_en": ["ADC + Support", "Mid + Jungle", "Top + Jungle", "Double Mage"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "卡莎进化技能需要的属性是什么？",
        "q_en": "What stats does Kai'Sa need to evolve her abilities?",
        "options_zh": ["生命值", "AD/AP/攻速", "移速", "暴击率"],
        "options_en": ["Health", "AD/AP/Attack Speed", "Move Speed", "Crit Chance"],
        "answer": 1,
        "reward": 50
    },
    {
        "q_zh": "以下哪个地图模式是轮换模式？",
        "q_en": "Which of these is a rotating game mode?",
        "options_zh": ["召唤师峡谷", "嚎哭深渊", "扭曲丛林", "无限火力"],
        "options_en": ["Summoner's Rift", "Howling Abyss", "Twisted Treeline", "URF"],
        "answer": 3,
        "reward": 50
    },
    {
        "q_zh": "佐伊的称号是什么？",
        "q_en": "What is Zoe's title?",
        "options_zh": ["时光守护者", "星界游神", "暮光星灵", "天启者"],
        "options_en": ["The Chronokeeper", "The Celestial", "The Aspect of Twilight", "The Enlightened"],
        "answer": 2,
        "reward": 50
    },
    {
        "q_zh": "大龙 Buff 持续多少秒？",
        "q_en": "How many seconds does Baron Buff last?",
        "options_zh": ["120秒", "180秒", "240秒", "60秒"],
        "options_en": ["120s", "180s", "240s", "60s"],
        "answer": 1,
        "reward": 50
    },
    {
        "q_zh": "以下谁不是德玛西亚的英雄？",
        "q_en": "Which of the following is NOT a Demacian champion?",
        "options_zh": ["盖伦", "拉克丝", "嘉文四世", "斯维因"],
        "options_en": ["Garen", "Lux", "Jarvan IV", "Swain"],
        "answer": 3,
        "reward": 50
    },
    {
        "q_zh": "风暴之怒是谁的称号？",
        "q_en": "Who is the 'Storm's Fury'?",
        "options_zh": ["迦娜", "艾希", "丽桑卓", "辛德拉"],
        "options_en": ["Janna", "Ashe", "Lissandra", "Syndra"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "伊泽瑞尔的 Q 技能叫什么？",
        "q_en": "What is Ezreal's Q ability called?",
        "options_zh": ["精华跃动", "秘术射击", "奥术跃迁", "精准弹幕"],
        "options_en": ["Essence Flux", "Mystic Shot", "Arcane Shift", "Trueshot Barrage"],
        "answer": 1,
        "reward": 50
    },
    {
        "q_zh": "LOL 比赛中一塔提供的金币是多少？",
        "q_en": "How much gold does the first turret provide in LoL?",
        "options_zh": ["100", "200", "300", "镀层+一塔额外金币"],
        "options_en": ["100", "200", "300", "Plating + First Tower bonus gold"],
        "answer": 3,
        "reward": 50
    },
    {
        "q_zh": "男枪的被动技能让他有什么特点？",
        "q_en": "What is unique about Graves' passive?",
        "options_zh": ["双管散弹枪装弹机制", "无限弹药", "穿透子弹", "自动瞄准"],
        "options_en": ["Double-barrel shotgun reload", "Unlimited ammo", "Piercing bullets", "Auto-aim"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "以下哪个是 2022 全球总决赛冠军？",
        "q_en": "Which team won the 2022 World Championship?",
        "options_zh": ["T1", "EDG", "DRX", "DK"],
        "options_en": ["T1", "EDG", "DRX", "DK"],
        "answer": 2,
        "reward": 50
    },
    {
        "q_zh": "慎的终极技能是什么？",
        "q_en": "What is Shen's ultimate ability?",
        "options_zh": ["奥义！魂佑", "秘奥义！慈悲度魂落", "奥义！影缚", "秘奥义！万雷天牢引"],
        "options_en": ["Stand United", "Shadow Dash", "Spirit's Refuge", "Twilight Assault"],
        "answer": 1,
        "reward": 50
    },
    {
        "q_zh": "德莱文的被动叫什么？",
        "q_en": "What is Draven's passive called?",
        "options_zh": ["旋转飞斧", "血性冲刺", "开道利斧", "德莱文联盟"],
        "options_en": ["Spinning Axe", "Blood Rush", "Stand Aside", "League of Draven"],
        "answer": 3,
        "reward": 50
    },
    {
        "q_zh": "小兵在游戏开始多少秒后刷新？",
        "q_en": "How many seconds into the game do minions spawn?",
        "options_zh": ["1分05秒", "1分30秒", "0分30秒", "2分钟"],
        "options_en": ["1:05", "1:30", "0:30", "2:00"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "以下哪个是影流之主？",
        "q_en": "Which champion is the Master of Shadows?",
        "options_zh": ["慎", "阿卡丽", "劫", "凯南"],
        "options_en": ["Shen", "Akali", "Zed", "Kennen"],
        "answer": 2,
        "reward": 50
    },
    {
        "q_zh": "金克丝的武器不包括以下哪个？",
        "q_en": "Which weapon is NOT part of Jinx's arsenal?",
        "options_zh": ["轻机枪", "火箭发射器", "电磁炮", "狙击枪"],
        "options_en": ["Minigun", "Rocket Launcher", "Zap Cannon", "Sniper Rifle"],
        "answer": 3,
        "reward": 50
    },
    {
        "q_zh": "元素龙刷新间隔是多少？",
        "q_en": "What is the respawn interval for Elemental Drakes?",
        "options_zh": ["4分钟", "5分钟", "6分钟", "3分钟"],
        "options_en": ["4 min", "5 min", "6 min", "3 min"],
        "answer": 1,
        "reward": 50
    },
    {
        "q_zh": "瑞兹的称号是什么？",
        "q_en": "What is Ryze's title?",
        "options_zh": ["符文法师", "流浪法师", "远古巫灵", "邪恶小法师"],
        "options_en": ["The Rune Mage", "The Rogue Mage", "The Ancient Lich", "The Tiny Master of Evil"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "以下哪个是 2018 全球总决赛冠军？",
        "q_en": "Which team won the 2018 World Championship?",
        "options_zh": ["RNG", "iG", "FPX", "G2"],
        "options_en": ["RNG", "iG", "FPX", "G2"],
        "answer": 1,
        "reward": 50
    },
    {
        "q_zh": "艾克的被动三环效果是什么？",
        "q_en": "What does Ekko's passive 3-hit proc do?",
        "options_zh": ["回血", "减速", "额外伤害+加速", "隐身"],
        "options_en": ["Heal", "Slow", "Bonus damage + speed boost", "Invisibility"],
        "answer": 2,
        "reward": 50
    },
    {
        "q_zh": "琴女的终极技能叫什么？",
        "q_en": "What is Sona's ultimate ability called?",
        "options_zh": ["狂舞终乐章", "英勇赞美诗", "坚毅咏叹调", "迅捷奏鸣曲"],
        "options_en": ["Crescendo", "Hymn of Valor", "Aria of Perseverance", "Song of Celerity"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "以下哪个英雄的武器是锤子？",
        "q_en": "Which champion wields a hammer?",
        "options_zh": ["菲奥娜", "锐雯", "盖伦", "波比"],
        "options_en": ["Fiora", "Riven", "Garen", "Poppy"],
        "answer": 3,
        "reward": 50
    },
    {
        "q_zh": "LOL 中的红 Buff 叫什么？",
        "q_en": "What is the Red Buff called in LoL?",
        "options_zh": ["红Buff / 余烬之冠", "蓝Buff / 洞悉之冠", "大龙Buff", "小龙Buff"],
        "options_en": ["Red Buff / Crest of Cinders", "Blue Buff / Crest of Insight", "Baron Buff", "Dragon Buff"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "以下哪个不是 ADC 常见出装？",
        "q_en": "Which item is NOT a common ADC purchase?",
        "options_zh": ["无尽之刃", "火炮", "多米尼克领主的致意", "日炎斗篷"],
        "options_en": ["Infinity Edge", "Rapid Firecannon", "Lord Dominik's Regards", "Sunfire Aegis"],
        "answer": 3,
        "reward": 50
    },
    {
        "q_zh": "狮子狗的称号是什么？",
        "q_en": "What is Rengar's title?",
        "options_zh": ["傲之追猎者", "傲之追猎者 雷恩加尔", "狂野女猎手", "虚空掠夺者"],
        "options_en": ["The Pridestalker", "The Pridestalker Rengar", "The Wild Huntress", "The Voidreaver"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "亚托克斯的 Q 技能有几段？",
        "q_en": "How many casts does Aatrox's Q have?",
        "options_zh": ["1段", "2段", "3段", "4段"],
        "options_en": ["1", "2", "3", "4"],
        "answer": 2,
        "reward": 50
    },
    {
        "q_zh": "蓝色方小龙坑在哪个半区？",
        "q_en": "Which side of the map is the Dragon pit on for Blue team?",
        "options_zh": ["下半区", "上半区", "中路", "随机"],
        "options_en": ["Bottom side", "Top side", "Mid lane", "Random"],
        "answer": 0,
        "reward": 50
    },
    {
        "q_zh": "以下哪个英雄可以复活？",
        "q_en": "Which champion can revive allies?",
        "options_zh": ["盖伦", "泰达米尔", "剑圣", "基兰"],
        "options_en": ["Garen", "Tryndamere", "Master Yi", "Zilean"],
        "answer": 3,
        "reward": 50
    },
    {
        "q_zh": "女枪的 Q 技能叫什么？",
        "q_en": "What is Miss Fortune's Q ability called?",
        "options_zh": ["一箭双雕", "枪林弹雨", "大步流星", "弹幕时间"],
        "options_en": ["Double Up", "Make It Rain", "Strut", "Bullet Time"],
        "answer": 0,
        "reward": 50
    }
]


def _build_question_embed(q_data: dict, index: int, total: int) -> discord.Embed:
    """Build the trivia question embed with bilingual text."""
    letters = ["A", "B", "C", "D"]
    choices_lines = []
    for i, (zh, en) in enumerate(zip(q_data["options_zh"], q_data["options_en"])):
        choices_lines.append(f"{letters[i]}. {zh} ({en})")
    choices_text = "\n".join(choices_lines)

    embed = discord.Embed(
        title=f"❓ Trivia 第 {index}/{total} 题 | Question {index}/{total}",
        description=(
            f"**{q_data['q_zh']}**\n"
            f"🌐 {q_data['q_en']}\n\n"
            f"{choices_text}"
        ),
        color=discord.Color.blue(),
    )
    embed.set_footer(text="发送 A/B/C/D 作答！20秒倒计时 / 20s countdown")
    return embed


class TriviaGame:
    """Manages a single trivia game session."""
    def __init__(self, channel: discord.TextChannel, questions: list, num_questions: int = 10):
        self.channel = channel
        self.questions = random.sample(questions, min(num_questions, len(questions)))
        self.current_question = 0
        self.scores: dict[str, int] = {}
        self.answered_this_round: set = set()
        self.running = False
        self.message: discord.Message | None = None

    def add_score(self, user_id: str, pts: int):
        self.scores[user_id] = self.scores.get(user_id, 0) + pts

    def leaderboard_str(self) -> str:
        sorted_users = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)
        lines = []
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        for i, (uid, pts) in enumerate(sorted_users[:10]):
            prefix = medals.get(i, f"{i+1}.")
            lines.append(f"{prefix} <@{uid}> — {pts} 分")
        return "\n".join(lines) if lines else "暂无得分 / No scores yet"


class Trivia(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_game: TriviaGame | None = None
        self._lock = asyncio.Lock()

    async def _run_trivia_round(self, game: TriviaGame):
        q_data = game.questions[game.current_question]
        game.answered_this_round.clear()
        embed = _build_question_embed(q_data, game.current_question + 1, len(game.questions))
        game.message = await game.channel.send(embed=embed)

        def check(m: discord.Message):
            if m.channel.id != game.channel.id:
                return False
            if m.author.bot:
                return False
            uid = str(m.author.id)
            if uid in game.answered_this_round:
                return False
            content = m.content.strip().upper()
            return content in ("A", "B", "C", "D")

        try:
            msg = await self.bot.wait_for("message", timeout=20.0, check=check)
            uid = str(msg.author.id)
            answer = msg.content.strip().upper()
            game.answered_this_round.add(uid)
            ans_idx = ord(answer) - ord("A")

            if ans_idx == q_data["answer"]:
                game.add_score(uid, 50)
                _add_coins(uid, 50, f"Trivia correct / 答题正确 #{game.current_question + 1}")
                await self._show_result(game, q_data, msg.author, True)
            else:
                await msg.add_reaction("❌")
                try:
                    msg2 = await self.bot.wait_for("message", timeout=15.0, check=check)
                    uid2 = str(msg2.author.id)
                    answer2 = msg2.content.strip().upper()
                    game.answered_this_round.add(uid2)
                    ans_idx2 = ord(answer2) - ord("A")
                    if ans_idx2 == q_data["answer"]:
                        game.add_score(uid2, 50)
                        _add_coins(uid2, 50, f"Trivia correct / 答题正确 #{game.current_question + 1}")
                        await self._show_result(game, q_data, msg2.author, True)
                    else:
                        await self._reveal_answer(game, q_data)
                except asyncio.TimeoutError:
                    await self._reveal_answer(game, q_data)

        except asyncio.TimeoutError:
            await self._reveal_answer(game, q_data)

    async def _show_result(self, game: TriviaGame, q_data: dict, winner: discord.Member | discord.User, correct: bool):
        letters = ["A", "B", "C", "D"]
        ans = q_data["answer"]
        ans_zh = q_data["options_zh"][ans]
        ans_en = q_data["options_en"][ans]
        embed = _build_question_embed(q_data, game.current_question + 1, len(game.questions))
        embed.color = discord.Color.green()
        embed.add_field(
            name="✅ 正确答案 | Correct Answer",
            value=f"{letters[ans]}. {ans_zh} ({ans_en}) — {winner.mention} 答对了！+50 💰",
            inline=False,
        )
        try:
            await game.message.edit(embed=embed)
        except Exception:
            await game.channel.send(embed=embed)

    async def _reveal_answer(self, game: TriviaGame, q_data: dict):
        letters = ["A", "B", "C", "D"]
        ans = q_data["answer"]
        ans_zh = q_data["options_zh"][ans]
        ans_en = q_data["options_en"][ans]
        embed = _build_question_embed(q_data, game.current_question + 1, len(game.questions))
        embed.color = discord.Color.red()
        embed.add_field(
            name="⏰ 时间到！正确答案 | Time's up! Correct Answer",
            value=f"{letters[ans]}. {ans_zh} ({ans_en})",
            inline=False,
        )
        try:
            await game.message.edit(embed=embed)
        except Exception:
            await game.channel.send(embed=embed)

    async def _finish_game(self, game: TriviaGame):
        sorted_users = sorted(game.scores.items(), key=lambda x: x[1], reverse=True)
        bonuses = {0: 300, 1: 200, 2: 100}
        for i, (uid, pts) in enumerate(sorted_users[:3]):
            bonus = bonuses.get(i, 0)
            if bonus > 0:
                _add_coins(uid, bonus, f"Trivia top {i+1} bonus / 答题排行榜第{i+1}名奖励")

        embed = discord.Embed(
            title="🏆 Trivia 结束！最终排行榜 | Final Leaderboard",
            description=game.leaderboard_str(),
            color=discord.Color.gold(),
        )
        if len(sorted_users) >= 3:
            embed.add_field(
                name="额外奖励 / Bonus",
                value=(
                    f"🥇 <@{sorted_users[0][0]}> +300 💰\n"
                    f"🥈 <@{sorted_users[1][0]}> +200 💰\n"
                    f"🥉 <@{sorted_users[2][0]}> +100 💰"
                ),
                inline=False,
            )
        embed.set_footer(text=f"共 {len(game.questions)} 题 / 每题 +50 💰 | {len(game.questions)} questions / +50 💰 each")
        await game.channel.send(embed=embed)
        self.active_game = None

    @app_commands.command(name="gmpt-trivia", description="Start a trivia quiz / 开始问答游戏")
    @app_commands.describe(questions="Number of questions (default 10) / 题目数量（默认10）")
    async def trivia_cmd(self, interaction: discord.Interaction, questions: int = 10):
        async with self._lock:
            if self.active_game is not None:
                return await interaction.response.send_message(
                    "已有正在进行的 Trivia！请等待结束 / A trivia is already in progress.", ephemeral=True
                )
            if questions < 1:
                questions = 10
            if questions > len(TRIVIA_QUESTIONS):
                questions = len(TRIVIA_QUESTIONS)

            game = TriviaGame(interaction.channel, TRIVIA_QUESTIONS, questions)
            self.active_game = game
            game.running = True

            await interaction.response.send_message(
                f"🎮 **Trivia 问答开始！** 共 {questions} 题，每题 20 秒，发送 A/B/C/D 作答。\n"
                f"**Trivia started!** {questions} questions, 20s each, type A/B/C/D to answer.\n"
                f"每题答对 +50 💰，最终前三名额外奖励！/ +50 💰 per correct, top 3 get bonus!"
            )

            for i in range(len(game.questions)):
                game.current_question = i
                await self._run_trivia_round(game)
                await asyncio.sleep(2)

            await self._finish_game(game)

    @app_commands.command(name="gmpt-trivia-stop", description="Stop the ongoing trivia / 提前终止问答")
    @app_commands.default_permissions(administrator=True)
    async def trivia_stop_cmd(self, interaction: discord.Interaction):
        if self.active_game is None:
            return await interaction.response.send_message("没有正在进行的 Trivia。 / No active trivia.", ephemeral=True)
        game = self.active_game
        game.running = False
        await interaction.response.send_message("⏹️ Trivia 已终止 / Trivia stopped.")
        await self._finish_game(game)

    @trivia_cmd.error
    @trivia_stop_cmd.error
    async def trivia_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        log_error("trivia", interaction.command.name if interaction.command else "unknown", error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("发生错误 / An error occurred.", ephemeral=True)
            else:
                await interaction.followup.send("发生错误 / An error occurred.", ephemeral=True)
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(Trivia(bot))
