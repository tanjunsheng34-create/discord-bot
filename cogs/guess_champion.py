"""
GMPT Bot — Guess the Champion (猜英雄)
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


def _add_coins(uid: str, amount: int, reason: str):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (discord_id, username) VALUES (?, 'unknown') ON CONFLICT(discord_id) DO NOTHING",
        (uid,),
    )
    cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, uid))
    cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)", (uid, amount, reason))
    conn.commit(); conn.close()


# ── Champion data (60+ champions) ──
CHAMPIONS = [
    {"name": "安妮", "emoji": "🔥👧🐻🧸", "title": "黑暗之女", "quote": "你看见我的小熊了吗？", "region": "诺克萨斯"},
    {"name": "亚索", "emoji": "💨🗡️😈", "title": "疾风剑豪", "quote": "死亡如风，常伴吾身", "region": "艾欧尼亚"},
    {"name": "艾希", "emoji": "🏹❄️👸", "title": "寒冰射手", "quote": "你要来几发吗？", "region": "弗雷尔卓德"},
    {"name": "盖伦", "emoji": "⚔️🛡️💪", "title": "德玛西亚之力", "quote": "德玛西亚！", "region": "德玛西亚"},
    {"name": "劫", "emoji": "🌑🗡️💨", "title": "影流之主", "quote": "无形之刃，最为致命", "region": "艾欧尼亚"},
    {"name": "锐雯", "emoji": "⚔️💨💚", "title": "放逐之刃", "quote": "断剑重铸之日，骑士归来之时", "region": "诺克萨斯"},
    {"name": "阿狸", "emoji": "🦊💙🔥", "title": "九尾妖狐", "quote": "我们来玩吧~", "region": "艾欧尼亚"},
    {"name": "盲僧", "emoji": "👁️‍🗨️👊🦵", "title": "盲僧", "quote": "双眼失明丝毫不影响我追捕敌人", "region": "艾欧尼亚"},
    {"name": "提莫", "emoji": "🐹🍄💨", "title": "迅捷斥候", "quote": "我去前面探探路", "region": "班德尔城"},
    {"name": "金克丝", "emoji": "💣🔫😈", "title": "暴走萝莉", "quote": "规则就是用来打破的！", "region": "祖安"},
    {"name": "德莱厄斯", "emoji": "🪓🩸💪", "title": "诺克萨斯之手", "quote": "诺克萨斯即将崛起", "region": "诺克萨斯"},
    {"name": "伊泽瑞尔", "emoji": "✨🏹💛", "title": "探险家", "quote": "是时候表演真正的技术了", "region": "皮尔特沃夫"},
    {"name": "拉克丝", "emoji": "💡✨👧", "title": "光辉女郎", "quote": "照亮前进的道路", "region": "德玛西亚"},
    {"name": "菲奥娜", "emoji": "🤺👩💙", "title": "无双剑姬", "quote": "我渴望有价值的对手", "region": "德玛西亚"},
    {"name": "卡莎", "emoji": "🦋💜🏹", "title": "虚空之女", "quote": "我的外表下藏着什么？", "region": "虚空"},
    {"name": "永恩", "emoji": "🗡️😈💀", "title": "封魔剑魂", "quote": "两条道路，一把剑", "region": "艾欧尼亚"},
    {"name": "塞纳", "emoji": "🔫💡👻", "title": "涤魂圣枪", "quote": "我从死亡中归来", "region": "暗影岛"},
    {"name": "艾克", "emoji": "⏰💚🔧", "title": "时间刺客", "quote": "时间不站在你那边", "region": "祖安"},
    {"name": "瑟提", "emoji": "👊💪🔥", "title": "腕豪", "quote": "我妈说我打得不错", "region": "艾欧尼亚"},
    {"name": "烬", "emoji": "🎭🔫🎨", "title": "戏命师", "quote": "艺术，应当震慑人心", "region": "艾欧尼亚"},
    {"name": "阿卡丽", "emoji": "🗡️💨💚", "title": "离群之刺", "quote": "均衡，脆弱无比", "region": "艾欧尼亚"},
    {"name": "莫甘娜", "emoji": "😇😈🪶", "title": "堕落天使", "quote": "我会叫他们忏悔", "region": "德玛西亚"},
    {"name": "凯尔", "emoji": "😇⚔️🔥", "title": "正义天使", "quote": "审判将至", "region": "德玛西亚"},
    {"name": "派克", "emoji": "🦈🔪💀", "title": "血港鬼影", "quote": "死人的名单上又多了一个名字", "region": "比尔吉沃特"},
    {"name": "俄洛伊", "emoji": "🐙💪🌊", "title": "海兽祭司", "quote": "运动就是生命", "region": "比尔吉沃特"},
    {"name": "塞拉斯", "emoji": "⛓️💪🔥", "title": "解脱者", "quote": "德玛西亚必将灭亡", "region": "德玛西亚"},
    {"name": "卡莎碧亚", "emoji": "🐍💚👩", "title": "魔蛇之拥", "quote": "别那么快嘛~", "region": "诺克萨斯"},
    {"name": "卡特琳娜", "emoji": "🗡️💃🔴", "title": "不祥之刃", "quote": "暴力可以解决一切", "region": "诺克萨斯"},
    {"name": "薇恩", "emoji": "🏹🌙🦇", "title": "暗夜猎手", "quote": "净化元素，圣银", "region": "德玛西亚"},
    {"name": "泰达米尔", "emoji": "⚔️😡💪", "title": "蛮族之王", "quote": "我的大刀早已饥渴难耐", "region": "弗雷尔卓德"},
    {"name": "奥拉夫", "emoji": "🪓😡⚡", "title": "狂战士", "quote": "所到之处，寸草不生", "region": "弗雷尔卓德"},
    {"name": "瑟庄妮", "emoji": "🐗❄️🛡️", "title": "凛冬之怒", "quote": "弗雷尔卓德，永不屈服", "region": "弗雷尔卓德"},
    {"name": "布隆", "emoji": "🛡️💪❄️", "title": "弗雷尔卓德之心", "quote": "站在布隆后面！", "region": "弗雷尔卓德"},
    {"name": "锤石", "emoji": "⛓️💀🔗", "title": "魂锁典狱长", "quote": "你的灵魂将受折磨", "region": "暗影岛"},
    {"name": "赫卡里姆", "emoji": "🐴💀🔥", "title": "战争之影", "quote": "粉碎他们的防线", "region": "暗影岛"},
    {"name": "卡尔萨斯", "emoji": "💀🎵👻", "title": "死亡颂唱者", "quote": "安息吧", "region": "暗影岛"},
    {"name": "弗拉基米尔", "emoji": "🩸🧛🦇", "title": "猩红收割者", "quote": "血流成河", "region": "诺克萨斯"},
    {"name": "伊莉丝", "emoji": "🕷️🕸️👩", "title": "蜘蛛女皇", "quote": "只有弱者才畏惧黑暗", "region": "暗影岛"},
    {"name": "凯隐", "emoji": "🗡️😈💙", "title": "影流之镰", "quote": "暗裔还是刺客，这是个问题", "region": "艾欧尼亚"},
    {"name": "千珏", "emoji": "🐑🐺🏹", "title": "永猎双子", "quote": "所有人，终有一死", "region": "符文之地"},
    {"name": "巴德", "emoji": "🎵🌟🛸", "title": "星界游神", "quote": "*~音效~*", "region": "宇宙"},
    {"name": "奥恩", "emoji": "🔨🔥🐏", "title": "山隐之焰", "quote": "一切都可以打造", "region": "弗雷尔卓德"},
    {"name": "潘森", "emoji": "🛡️🗡️⭐", "title": "不屈之枪", "quote": "天神已死，凡人永存", "region": "巨神峰"},
    {"name": "蕾欧娜", "emoji": "☀️🛡️⚔️", "title": "曙光女神", "quote": "黎明就在眼前", "region": "巨神峰"},
    {"name": "佐伊", "emoji": "🌟😴💜", "title": "暮光星灵", "quote": "你看起来很好吃！", "region": "巨神峰"},
    {"name": "娑娜", "emoji": "🎵🎻💙", "title": "琴瑟仙女", "quote": "*无声的旋律*", "region": "德玛西亚"},
    {"name": "莫德凯撒", "emoji": "👑💀🔥", "title": "铁铠冥魂", "quote": "我即是死亡", "region": "暗影岛"},
    {"name": "维克托", "emoji": "🤖🔧⚡", "title": "机械先驱", "quote": "光荣的进化", "region": "祖安"},
    {"name": "蒙多", "emoji": "💉💪🟣", "title": "祖安狂人", "quote": "蒙多觉得你是个大娘们！", "region": "祖安"},
    {"name": "扎克", "emoji": "🟢💧💪", "title": "生化魔人", "quote": "我不是史莱姆！", "region": "祖安"},
    {"name": "厄加特", "emoji": "🦀🔫🤖", "title": "无畏战车", "quote": "你不过是一堆零件", "region": "祖安"},
    {"name": "吉格斯", "emoji": "💣😈🔥", "title": "爆破鬼才", "quote": "来，炸个痛快！", "region": "祖安"},
    {"name": "塔姆", "emoji": "🐸👅🐟", "title": "河流之王", "quote": "叫我国王，叫我恶魔", "region": "比尔吉沃特"},
    {"name": "崔丝塔娜", "emoji": "🔫🐹💥", "title": "麦林炮手", "quote": "我看见你了！", "region": "班德尔城"},
    {"name": "璐璐", "emoji": "🧚💜✨", "title": "仙灵女巫", "quote": "那东西尝起来像紫色", "region": "班德尔城"},
    {"name": "维迦", "emoji": "🧙⚫😈", "title": "邪恶小法师", "quote": "我是魔鬼！不许笑！", "region": "班德尔城"},
    {"name": "纳尔", "emoji": "🦖😡❄️", "title": "迷失之牙", "quote": "纳尔，生气了！", "region": "弗雷尔卓德"},
    {"name": "克烈", "emoji": "🦎😡🔫", "title": "暴怒骑士", "quote": "冲啊啊啊啊！", "region": "诺克萨斯"},
    {"name": "德莱文", "emoji": "🪓🪓🧔", "title": "荣耀行刑官", "quote": "欢迎来到德莱联盟", "region": "诺克萨斯"},
    {"name": "慎", "emoji": "⚔️⚡🤖", "title": "暮光之眼", "quote": "均衡存乎万物之间", "region": "艾欧尼亚"},
    {"name": "凯南", "emoji": "⚡🐹🗡️", "title": "狂暴之心", "quote": "均衡，不容破坏", "region": "艾欧尼亚"},
    {"name": "辛德拉", "emoji": "⚫🌀👑", "title": "暗黑元首", "quote": "我的潜能，无穷无尽", "region": "艾欧尼亚"},
    {"name": "卢锡安", "emoji": "🔫🔫🖤", "title": "圣枪游侠", "quote": "净化她！", "region": "暗影岛"},
    {"name": "格雷福斯", "emoji": "🔫💨🧔", "title": "法外狂徒", "quote": "死路一条", "region": "比尔吉沃特"},
    {"name": "崔斯特", "emoji": "🃏🎩🔮", "title": "卡牌大师", "quote": "幸运女神在微笑", "region": "比尔吉沃特"},
    {"name": "萨科", "emoji": "🤡🔪🎭", "title": "恶魔小丑", "quote": "来次魔术戏法，怎么样？", "region": "符文之地"},
    {"name": "亚托克斯", "emoji": "🗡️😈🩸", "title": "暗裔剑魔", "quote": "我曾经是神", "region": "恕瑞玛"},
    {"name": "内瑟斯", "emoji": "🐶📖⚡", "title": "沙漠死神", "quote": "生与死，轮回不止", "region": "恕瑞玛"},
    {"name": "阿兹尔", "emoji": "🦅🏜️👑", "title": "沙漠皇帝", "quote": "恕瑞玛，你的皇帝回来了", "region": "恕瑞玛"},
]


class GuessChampion(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_game: dict[int, dict] = {}  # channel_id -> game_state

    @app_commands.command(name="gmpt-guess-champion", description="猜英雄！根据提示猜 LOL 英雄 / Guess the champion")
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def guess_champ_cmd(self, interaction: discord.Interaction):
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
            f"🎮 **猜英雄开始！**\n"
            f"我会依次给出 3 个提示，每个提示间隔 10 秒\n"
            f"提示 1 猜对 = 200 💰 | 提示 2 = 100 💰 | 提示 3 = 50 💰\n"
            f"直接发送英雄名字即可！"
        )

        hints = [
            f"💡 **提示 1（emoji）：** {champion['emoji']}（200 💰）",
            f"💡 **提示 2（称号/台词）：** 「{champion['title']}」— \"{champion['quote']}\"（100 💰）",
            f"💡 **提示 3（地区）：** 来自 **{champion['region']}**（50 💰）",
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

                if msg.content.strip() == champion["name"]:
                    reward = rewards[round_num]
                    _add_coins(uid, reward, f"Guess Champion / 猜英雄正确 — {champion['name']}")
                    await interaction.channel.send(
                        f"✅ **{msg.author.mention} 猜对了！答案是 {champion['name']}，+{reward} 💰**"
                    )
                    state["solved"] = True
                else:
                    await msg.add_reaction("❌")
            except asyncio.TimeoutError:
                continue

        if not state["solved"]:
            await interaction.channel.send(
                f"⏰ 时间到！答案是 **{champion['name']}**（{champion['title']}），无人得奖。"
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
