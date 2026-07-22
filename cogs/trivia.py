"""
GMPT Bot — Trivia Quiz (LOL / Esports)
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


# ── Trivia question pool (40+ questions) ──
TRIVIA_QUESTIONS = [
    {"q": "亚索的被动技能叫什么？", "a": "A", "choices": {"A": "浪客之道", "B": "疾风斩", "C": "风之屏障", "D": "踏前斩"}},
    {"q": "2024 全球总决赛冠军是哪个队伍？", "a": "A", "choices": {"A": "T1", "B": "GEN", "C": "BLG", "D": "WBG"}},
    {"q": "以下哪个装备提供法术穿透？", "a": "A", "choices": {"A": "虚空之杖", "B": "无尽之刃", "C": "破败王者之刃", "D": "饮血剑"}},
    {"q": "李青的终极技能叫什么？", "a": "B", "choices": {"A": "天音波", "B": "猛龙摆尾", "C": "金钟罩", "D": "摧筋断骨"}},
    {"q": "峡谷中的纳什男爵在游戏开始多少分钟后刷新？", "a": "A", "choices": {"A": "20分钟", "B": "15分钟", "C": "25分钟", "D": "10分钟"}},
    {"q": "阿狸的定位是什么？", "a": "C", "choices": {"A": "辅助", "B": "坦克", "C": "法师/刺客", "D": "射手"}},
    {"q": "以下哪个是无限火力的特征？", "a": "B", "choices": {"A": "无冷却", "B": "80%冷却缩减", "C": "无限金钱", "D": "无蓝耗"}},
    {"q": "提莫的被动技能效果是什么？", "a": "D", "choices": {"A": "加速", "B": "回血", "C": "致盲", "D": "短时间不动后隐身"}},
    {"q": "MSI 的全称是什么？", "a": "A", "choices": {"A": "Mid-Season Invitational", "B": "Major Series International", "C": "Mega Season Invite", "D": "Mid-Season International"}},
    {"q": "以下哪个英雄来自艾欧尼亚？", "a": "B", "choices": {"A": "德莱厄斯", "B": "艾瑞莉娅", "C": "盖伦", "D": "瑟庄妮"}},
    {"q": "峡谷先锋在游戏内叫什么？", "a": "C", "choices": {"A": "峡谷巨兽", "B": "峡谷守护者", "C": " rift herald / 峡谷先锋", "D": "峡谷领主"}},
    {"q": "烬的被动技能会让他获得什么？", "a": "A", "choices": {"A": "第四发必暴击且加移速", "B": "无限弹药", "C": "隐身", "D": "额外生命值"}},
    {"q": "LOL 中有多少条元素龙类型？", "a": "D", "choices": {"A": "4", "B": "5", "C": "3", "D": "6"}},
    {"q": "凯特琳的称号是什么？", "a": "B", "choices": {"A": "赏金猎人", "B": "皮城女警", "C": "暗夜猎手", "D": "枪火狂徒"}},
    {"q": "2023 全球总决赛冠军是哪个队伍？", "a": "A", "choices": {"A": "T1", "B": "DRX", "C": "JDG", "D": "WBG"}},
    {"q": "以下哪个英雄的技能可以格挡飞行道具？", "a": "C", "choices": {"A": "盖伦", "B": "赵信", "C": "亚索", "D": "劫"}},
    {"q": "LPL 的下路双人组通常包括哪两个角色？", "a": "A", "choices": {"A": "ADC + 辅助", "B": "中单 + 打野", "C": "上单 + 打野", "D": "双法师"}},
    {"q": "卡莎进化技能需要的属性是什么？", "a": "B", "choices": {"A": "生命值", "B": "AD/AP/攻速", "C": "移速", "D": "暴击率"}},
    {"q": "以下哪个地图模式是轮换模式？", "a": "D", "choices": {"A": "召唤师峡谷", "B": "嚎哭深渊", "C": "扭曲丛林", "D": "无限火力"}},
    {"q": "佐伊的称号是什么？", "a": "C", "choices": {"A": "时光守护者", "B": "星界游神", "C": "暮光星灵", "D": "天启者"}},
    {"q": "大龙 Buff 持续多少秒？", "a": "B", "choices": {"A": "120秒", "B": "180秒", "C": "240秒", "D": "60秒"}},
    {"q": "以下谁不是德玛西亚的英雄？", "a": "D", "choices": {"A": "盖伦", "B": "拉克丝", "C": "嘉文四世", "D": "斯维因"}},
    {"q": "风暴之怒是谁的称号？", "a": "A", "choices": {"A": "迦娜", "B": "艾希", "C": "丽桑卓", "D": "辛德拉"}},
    {"q": "伊泽瑞尔的 Q 技能叫什么？", "a": "B", "choices": {"A": "精华跃动", "B": "秘术射击", "C": "奥术跃迁", "D": "精准弹幕"}},
    {"q": "LOL 比赛中一塔提供的金币是多少？", "a": "D", "choices": {"A": "100", "B": "200", "C": "300", "D": "镀层+一塔额外金币"}},
    {"q": "男枪的被动技能让他有什么特点？", "a": "A", "choices": {"A": "双管散弹枪装弹机制", "B": "无限弹药", "C": "穿透子弹", "D": "自动瞄准"}},
    {"q": "以下哪个是 2022 全球总决赛冠军？", "a": "C", "choices": {"A": "T1", "B": "EDG", "C": "DRX", "D": "DK"}},
    {"q": "慎的终极技能是什么？", "a": "B", "choices": {"A": "奥义！魂佑", "B": "秘奥义！慈悲度魂落", "C": "奥义！影缚", "D": "秘奥义！万雷天牢引"}},
    {"q": "德莱文的被动叫什么？", "a": "D", "choices": {"A": "旋转飞斧", "B": "血性冲刺", "C": "开道利斧", "D": "德莱文联盟"}},
    {"q": "小兵在游戏开始多少秒后刷新？", "a": "A", "choices": {"A": "1分05秒", "B": "1分30秒", "C": "0分30秒", "D": "2分钟"}},
    {"q": "以下哪个是影流之主？", "a": "C", "choices": {"A": "慎", "B": "阿卡丽", "C": "劫", "D": "凯南"}},
    {"q": "金克丝的武器不包括以下哪个？", "a": "D", "choices": {"A": "轻机枪", "B": "火箭发射器", "C": "电磁炮", "D": "狙击枪"}},
    {"q": "元素龙刷新间隔是多少？", "a": "B", "choices": {"A": "4分钟", "B": "5分钟", "C": "6分钟", "D": "3分钟"}},
    {"q": "瑞兹的称号是什么？", "a": "A", "choices": {"A": "符文法师", "B": "流浪法师", "C": "远古巫灵", "D": "邪恶小法师"}},
    {"q": "以下哪个是 2018 全球总决赛冠军？", "a": "B", "choices": {"A": "RNG", "B": "iG", "C": "FPX", "D": "G2"}},
    {"q": "艾克的被动三环效果是什么？", "a": "C", "choices": {"A": "回血", "B": "减速", "C": "额外伤害+加速", "D": "隐身"}},
    {"q": "琴女的终极技能叫什么？", "a": "A", "choices": {"A": "狂舞终乐章", "B": "英勇赞美诗", "C": "坚毅咏叹调", "D": "迅捷奏鸣曲"}},
    {"q": "以下哪个英雄的武器是锤子？", "a": "D", "choices": {"A": "菲奥娜", "B": "锐雯", "C": "盖伦", "D": "波比"}},
    {"q": "LOL 中的红 Buff 叫什么？", "a": "A", "choices": {"A": "红Buff / 余烬之冠", "B": "蓝Buff / 洞悉之冠", "C": "大龙Buff", "D": "小龙Buff"}},
    {"q": "以下哪个不是 ADC 常见出装？", "a": "D", "choices": {"A": "无尽之刃", "B": "火炮", "C": "多米尼克领主的致意", "D": "日炎斗篷"}},
    {"q": "狮子狗的称号是什么？", "a": "B", "choices": {"A": "傲之追猎者", "B": "傲之追猎者 雷恩加尔", "C": "狂野女猎手", "D": "虚空掠夺者"}},
    {"q": "亚托克斯的 Q 技能有几段？", "a": "C", "choices": {"A": "1段", "B": "2段", "C": "3段", "D": "4段"}},
    {"q": "蓝色方小龙坑在哪个半区？", "a": "A", "choices": {"A": "下半区", "B": "上半区", "C": "中路", "D": "随机"}},
    {"q": "以下哪个英雄可以复活？", "a": "D", "choices": {"A": "盖伦", "B": "泰达米尔", "C": "剑圣", "D": "基兰"}},
    {"q": "女枪的 Q 技能叫什么？", "a": "A", "choices": {"A": "一箭双雕", "B": "枪林弹雨", "C": "大步流星", "D": "弹幕时间"}},
]


class TriviaGame:
    """Manages a single trivia game session."""
    def __init__(self, channel: discord.TextChannel, questions: list, num_questions: int = 10):
        self.channel = channel
        self.questions = random.sample(questions, min(num_questions, len(questions)))
        self.current_question = 0
        self.scores: dict[str, int] = {}  # user_id -> score
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

        choices_text = "\n".join(
            f"{letter}. {text}" for letter, text in q_data["choices"].items()
        )

        embed = discord.Embed(
            title=f"❓ Trivia 第 {game.current_question + 1}/{len(game.questions)} 题",
            description=f"**{q_data['q']}**\n\n{choices_text}",
            color=discord.Color.blue(),
        )
        embed.set_footer(text="发送 A/B/C/D 作答！20秒倒计时 / 20s countdown")

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

            if answer == q_data["a"]:
                game.add_score(uid, 50)
                _add_coins(uid, 50, f"Trivia correct / 答题正确 #{game.current_question + 1}")

                new_embed = discord.Embed(
                    title=f"❓ Trivia 第 {game.current_question + 1}/{len(game.questions)} 题",
                    description=f"**{q_data['q']}**\n\n{choices_text}",
                    color=discord.Color.green(),
                )
                new_embed.add_field(
                    name="✅ 正确答案",
                    value=f"{q_data['a']}. {q_data['choices'][q_data['a']]} — {msg.author.mention} 答对了！+50 💰",
                    inline=False,
                )
                try:
                    await game.message.edit(embed=new_embed)
                except Exception:
                    await game.channel.send(embed=new_embed)
            else:
                # Wrong answer, wait for others
                await msg.add_reaction("❌")
                # Continue waiting
                try:
                    msg2 = await self.bot.wait_for("message", timeout=15.0, check=check)
                    uid2 = str(msg2.author.id)
                    answer2 = msg2.content.strip().upper()
                    game.answered_this_round.add(uid2)

                    if answer2 == q_data["a"]:
                        game.add_score(uid2, 50)
                        _add_coins(uid2, 50, f"Trivia correct / 答题正确 #{game.current_question + 1}")
                        new_embed = discord.Embed(
                            title=f"❓ Trivia 第 {game.current_question + 1}/{len(game.questions)} 题",
                            description=f"**{q_data['q']}**\n\n{choices_text}",
                            color=discord.Color.green(),
                        )
                        new_embed.add_field(
                            name="✅ 正确答案",
                            value=f"{q_data['a']}. {q_data['choices'][q_data['a']]} — {msg2.author.mention} 答对了！+50 💰",
                            inline=False,
                        )
                        try:
                            await game.message.edit(embed=new_embed)
                        except Exception:
                            await game.channel.send(embed=new_embed)
                    else:
                        # Both wrong, reveal answer
                        await self._reveal_answer(game, q_data)
                except asyncio.TimeoutError:
                    await self._reveal_answer(game, q_data)

        except asyncio.TimeoutError:
            await self._reveal_answer(game, q_data)

    async def _reveal_answer(self, game: TriviaGame, q_data: dict):
        choices_text = "\n".join(
            f"{letter}. {text}" for letter, text in q_data["choices"].items()
        )
        embed = discord.Embed(
            title=f"❓ Trivia 第 {game.current_question + 1}/{len(game.questions)} 题",
            description=f"**{q_data['q']}**\n\n{choices_text}",
            color=discord.Color.red(),
        )
        embed.add_field(
            name="⏰ 时间到！正确答案",
            value=f"{q_data['a']}. {q_data['choices'][q_data['a']]}",
            inline=False,
        )
        try:
            await game.message.edit(embed=embed)
        except Exception:
            await game.channel.send(embed=embed)

    async def _finish_game(self, game: TriviaGame):
        sorted_users = sorted(game.scores.items(), key=lambda x: x[1], reverse=True)

        # Award bonus
        bonuses = {0: 300, 1: 200, 2: 100}
        for i, (uid, pts) in enumerate(sorted_users[:3]):
            bonus = bonuses.get(i, 0)
            if bonus > 0:
                _add_coins(uid, bonus, f"Trivia top {i+1} bonus / 答题排行榜第{i+1}名奖励")

        embed = discord.Embed(
            title="🏆 Trivia 结束！最终排行榜",
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
        embed.set_footer(text=f"共 {len(game.questions)} 题 / 每题 +50 💰")

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
                f"每题答对 +50 💰，最终前三名额外奖励！"
            )

            for i in range(len(game.questions)):
                game.current_question = i
                await self._run_trivia_round(game)
                await asyncio.sleep(2)  # brief pause between questions

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
            await interaction.response.send_message("发生错误 / An error occurred.", ephemeral=True)
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(Trivia(bot))
