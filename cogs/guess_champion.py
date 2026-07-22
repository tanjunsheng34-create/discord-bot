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


# ── Champion data (69 champions) with aliases ──
CHAMPIONS = [
    {"name": "安妮", "emoji": "🔥👧🐻🧸", "title": "黑暗之女", "quote": "你看见我的小熊了吗？", "region": "诺克萨斯",
     "aliases": ["annie", "an ni", "安妮"]},
    {"name": "亚索", "emoji": "💨🗡️😈", "title": "疾风剑豪", "quote": "死亡如风，常伴吾身", "region": "艾欧尼亚",
     "aliases": ["yasuo", "ya suo", "亚索", "压缩", "托儿索"]},
    {"name": "艾希", "emoji": "🏹❄️👸", "title": "寒冰射手", "quote": "你要来几发吗？", "region": "弗雷尔卓德",
     "aliases": ["ashe", "a she", "艾希", "艾师傅"]},
    {"name": "盖伦", "emoji": "⚔️🛡️💪", "title": "德玛西亚之力", "quote": "德玛西亚！", "region": "德玛西亚",
     "aliases": ["garen", "ga len", "盖伦", "德玛", "德玛西亚", "德玛西亚之力"]},
    {"name": "劫", "emoji": "🌑🗡️💨", "title": "影流之主", "quote": "无形之刃，最为致命", "region": "艾欧尼亚",
     "aliases": ["zed", "ze d", "劫", "火影劫", "儿童劫", "kid"]},
    {"name": "锐雯", "emoji": "⚔️💨💚", "title": "放逐之刃", "quote": "断剑重铸之日，骑士归来之时", "region": "诺克萨斯",
     "aliases": ["riven", "rui wen", "锐雯", "瑞文", "放逐之刃"]},
    {"name": "阿狸", "emoji": "🦊💙🔥", "title": "九尾妖狐", "quote": "我们来玩吧~", "region": "艾欧尼亚",
     "aliases": ["ahri", "a li", "阿狸", "九尾妖狐", "狐狸"]},
    {"name": "盲僧", "emoji": "👁️‍🗨️👊🦵", "title": "盲僧", "quote": "双眼失明丝毫不影响我追捕敌人", "region": "艾欧尼亚",
     "aliases": ["lee sin", "lee", "leesin", "盲僧", "李青", "瞎子", "li qing"]},
    {"name": "提莫", "emoji": "🐹🍄💨", "title": "迅捷斥候", "quote": "我去前面探探路", "region": "班德尔城",
     "aliases": ["teemo", "ti mo", "提莫"]},
    {"name": "金克丝", "emoji": "💣🔫😈", "title": "暴走萝莉", "quote": "规则就是用来打破的！", "region": "祖安",
     "aliases": ["jinx", "jin ke si", "金克丝", "金克斯"]},
    {"name": "德莱厄斯", "emoji": "🪓🩸💪", "title": "诺克萨斯之手", "quote": "诺克萨斯即将崛起", "region": "诺克萨斯",
     "aliases": ["darius", "da rui si", "德莱厄斯", "诺手", "诺克萨斯之手"]},
    {"name": "伊泽瑞尔", "emoji": "✨🏹💛", "title": "探险家", "quote": "是时候表演真正的技术了", "region": "皮尔特沃夫",
     "aliases": ["ezreal", "ez", "e z", "伊泽瑞尔", "ezreal"]},
    {"name": "拉克丝", "emoji": "💡✨👧", "title": "光辉女郎", "quote": "照亮前进的道路", "region": "德玛西亚",
     "aliases": ["lux", "la ke si", "拉克丝", "光辉"]},
    {"name": "菲奥娜", "emoji": "🤺👩💙", "title": "无双剑姬", "quote": "我渴望有价值的对手", "region": "德玛西亚",
     "aliases": ["fiora", "fei ao na", "菲奥娜", "剑姬", "jj"]},
    {"name": "卡莎", "emoji": "🦋💜🏹", "title": "虚空之女", "quote": "我的外表下藏着什么？", "region": "虚空",
     "aliases": ["kaisa", "kai sa", "卡莎", "kasha", "ks"]},
    {"name": "永恩", "emoji": "🗡️😈💀", "title": "封魔剑魂", "quote": "两条道路，一把剑", "region": "艾欧尼亚",
     "aliases": ["yone", "yong en", "永恩"]},
    {"name": "塞纳", "emoji": "🔫💡👻", "title": "涤魂圣枪", "quote": "我从死亡中归来", "region": "暗影岛",
     "aliases": ["senna", "sai na", "塞纳"]},
    {"name": "艾克", "emoji": "⏰💚🔧", "title": "时间刺客", "quote": "时间不站在你那边", "region": "祖安",
     "aliases": ["ekko", "ai ke", "艾克"]},
    {"name": "瑟提", "emoji": "👊💪🔥", "title": "腕豪", "quote": "我妈说我打得不错", "region": "艾欧尼亚",
     "aliases": ["sett", "se ti", "瑟提", "腕豪"]},
    {"name": "烬", "emoji": "🎭🔫🎨", "title": "戏命师", "quote": "艺术，应当震慑人心", "region": "艾欧尼亚",
     "aliases": ["jhin", "jin", "烬"]},
    {"name": "阿卡丽", "emoji": "🗡️💨💚", "title": "离群之刺", "quote": "均衡，脆弱无比", "region": "艾欧尼亚",
     "aliases": ["akali", "a ka li", "阿卡丽"]},
    {"name": "莫甘娜", "emoji": "😇😈🪶", "title": "堕落天使", "quote": "我会叫他们忏悔", "region": "德玛西亚",
     "aliases": ["morgana", "mo gan na", "莫甘娜"]},
    {"name": "凯尔", "emoji": "😇⚔️🔥", "title": "正义天使", "quote": "审判将至", "region": "德玛西亚",
     "aliases": ["kayle", "kai er", "凯尔"]},
    {"name": "派克", "emoji": "🦈🔪💀", "title": "血港鬼影", "quote": "死人的名单上又多了一个名字", "region": "比尔吉沃特",
     "aliases": ["pyke", "pai ke", "派克"]},
    {"name": "俄洛伊", "emoji": "🐙💪🌊", "title": "海兽祭司", "quote": "运动就是生命", "region": "比尔吉沃特",
     "aliases": ["illaoi", "俄洛伊"]},
    {"name": "塞拉斯", "emoji": "⛓️💪🔥", "title": "解脱者", "quote": "德玛西亚必将灭亡", "region": "德玛西亚",
     "aliases": ["sylas", "sai la si", "塞拉斯"]},
    {"name": "卡莎碧亚", "emoji": "🐍💚👩", "title": "魔蛇之拥", "quote": "别那么快嘛~", "region": "诺克萨斯",
     "aliases": ["cassiopeia", "ka sha bi ya", "卡莎碧亚", "蛇女"]},
    {"name": "卡特琳娜", "emoji": "🗡️💃🔴", "title": "不祥之刃", "quote": "暴力可以解决一切", "region": "诺克萨斯",
     "aliases": ["katarina", "ka te lin na", "卡特琳娜", "卡特"]},
    {"name": "薇恩", "emoji": "🏹🌙🦇", "title": "暗夜猎手", "quote": "净化元素，圣银", "region": "德玛西亚",
     "aliases": ["vayne", "vn", "wei en", "薇恩"]},
    {"name": "泰达米尔", "emoji": "⚔️😡💪", "title": "蛮族之王", "quote": "我的大刀早已饥渴难耐", "region": "弗雷尔卓德",
     "aliases": ["tryndamere", "tai da mi er", "泰达米尔", "蛮王"]},
    {"name": "奥拉夫", "emoji": "🪓😡⚡", "title": "狂战士", "quote": "所到之处，寸草不生", "region": "弗雷尔卓德",
     "aliases": ["olaf", "ao la fu", "奥拉夫"]},
    {"name": "瑟庄妮", "emoji": "🐗❄️🛡️", "title": "凛冬之怒", "quote": "弗雷尔卓德，永不屈服", "region": "弗雷尔卓德",
     "aliases": ["sejuani", "se zhuang ni", "瑟庄妮", "猪妹"]},
    {"name": "布隆", "emoji": "🛡️💪❄️", "title": "弗雷尔卓德之心", "quote": "站在布隆后面！", "region": "弗雷尔卓德",
     "aliases": ["braum", "bu long", "布隆"]},
    {"name": "锤石", "emoji": "⛓️💀🔗", "title": "魂锁典狱长", "quote": "你的灵魂将受折磨", "region": "暗影岛",
     "aliases": ["thresh", "chui shi", "锤石"]},
    {"name": "赫卡里姆", "emoji": "🐴💀🔥", "title": "战争之影", "quote": "粉碎他们的防线", "region": "暗影岛",
     "aliases": ["hecarim", "he ka li mu", "赫卡里姆", "人马"]},
    {"name": "卡尔萨斯", "emoji": "💀🎵👻", "title": "死亡颂唱者", "quote": "安息吧", "region": "暗影岛",
     "aliases": ["karthus", "ka er sa si", "卡尔萨斯", "死歌"]},
    {"name": "弗拉基米尔", "emoji": "🩸🧛🦇", "title": "猩红收割者", "quote": "血流成河", "region": "诺克萨斯",
     "aliases": ["vladimir", "fu la ji mi er", "弗拉基米尔", "吸血鬼"]},
    {"name": "伊莉丝", "emoji": "🕷️🕸️👩", "title": "蜘蛛女皇", "quote": "只有弱者才畏惧黑暗", "region": "暗影岛",
     "aliases": ["elise", "yi li si", "伊莉丝", "蜘蛛"]},
    {"name": "凯隐", "emoji": "🗡️😈💙", "title": "影流之镰", "quote": "暗裔还是刺客，这是个问题", "region": "艾欧尼亚",
     "aliases": ["kayn", "kai yin", "凯隐"]},
    {"name": "千珏", "emoji": "🐑🐺🏹", "title": "永猎双子", "quote": "所有人，终有一死", "region": "符文之地",
     "aliases": ["kindred", "qian jue", "千珏"]},
    {"name": "巴德", "emoji": "🎵🌟🛸", "title": "星界游神", "quote": "*~音效~*", "region": "宇宙",
     "aliases": ["bard", "ba de", "巴德"]},
    {"name": "奥恩", "emoji": "🔨🔥🐏", "title": "山隐之焰", "quote": "一切都可以打造", "region": "弗雷尔卓德",
     "aliases": ["ornn", "ao en", "奥恩"]},
    {"name": "潘森", "emoji": "🛡️🗡️⭐", "title": "不屈之枪", "quote": "天神已死，凡人永存", "region": "巨神峰",
     "aliases": ["pantheon", "pan sen", "潘森"]},
    {"name": "蕾欧娜", "emoji": "☀️🛡️⚔️", "title": "曙光女神", "quote": "黎明就在眼前", "region": "巨神峰",
     "aliases": ["leona", "lei ou na", "蕾欧娜", "日女"]},
    {"name": "佐伊", "emoji": "🌟😴💜", "title": "暮光星灵", "quote": "你看起来很好吃！", "region": "巨神峰",
     "aliases": ["zoe", "zuo yi", "佐伊"]},
    {"name": "娑娜", "emoji": "🎵🎻💙", "title": "琴瑟仙女", "quote": "*无声的旋律*", "region": "德玛西亚",
     "aliases": ["sona", "suo na", "娑娜", "琴女"]},
    {"name": "莫德凯撒", "emoji": "👑💀🔥", "title": "铁铠冥魂", "quote": "我即是死亡", "region": "暗影岛",
     "aliases": ["mordekaiser", "mo de kai sa", "莫德凯撒", "铁男"]},
    {"name": "维克托", "emoji": "🤖🔧⚡", "title": "机械先驱", "quote": "光荣的进化", "region": "祖安",
     "aliases": ["viktor", "wei ke tuo", "维克托"]},
    {"name": "蒙多", "emoji": "💉💪🟣", "title": "祖安狂人", "quote": "蒙多觉得你是个大娘们！", "region": "祖安",
     "aliases": ["mundo", "meng duo", "蒙多"]},
    {"name": "扎克", "emoji": "🟢💧💪", "title": "生化魔人", "quote": "我不是史莱姆！", "region": "祖安",
     "aliases": ["zac", "za ke", "扎克"]},
    {"name": "厄加特", "emoji": "🦀🔫🤖", "title": "无畏战车", "quote": "你不过是一堆零件", "region": "祖安",
     "aliases": ["urgot", "e jia te", "厄加特", "螃蟹"]},
    {"name": "吉格斯", "emoji": "💣😈🔥", "title": "爆破鬼才", "quote": "来，炸个痛快！", "region": "祖安",
     "aliases": ["ziggs", "ji ge si", "吉格斯", "炸弹人"]},
    {"name": "塔姆", "emoji": "🐸👅🐟", "title": "河流之王", "quote": "叫我国王，叫我恶魔", "region": "比尔吉沃特",
     "aliases": ["tahm kench", "tahm", "ta mu", "塔姆", "蛤蟆"]},
    {"name": "崔丝塔娜", "emoji": "🔫🐹💥", "title": "麦林炮手", "quote": "我看见你了！", "region": "班德尔城",
     "aliases": ["tristana", "cui si ta na", "崔丝塔娜", "小炮"]},
    {"name": "璐璐", "emoji": "🧚💜✨", "title": "仙灵女巫", "quote": "那东西尝起来像紫色", "region": "班德尔城",
     "aliases": ["lulu", "lu lu", "璐璐"]},
    {"name": "维迦", "emoji": "🧙⚫😈", "title": "邪恶小法师", "quote": "我是魔鬼！不许笑！", "region": "班德尔城",
     "aliases": ["veigar", "wei jia", "维迦", "小法师", "邪恶小法师"]},
    {"name": "纳尔", "emoji": "🦖😡❄️", "title": "迷失之牙", "quote": "纳尔，生气了！", "region": "弗雷尔卓德",
     "aliases": ["gnar", "na er", "纳尔", "小纳尔", "monster"]},
    {"name": "克烈", "emoji": "🦎😡🔫", "title": "暴怒骑士", "quote": "冲啊啊啊啊！", "region": "诺克萨斯",
     "aliases": ["kled", "ke lie", "克烈"]},
    {"name": "德莱文", "emoji": "🪓🪓🧔", "title": "荣耀行刑官", "quote": "欢迎来到德莱联盟", "region": "诺克萨斯",
     "aliases": ["draven", "de lai wen", "德莱文"]},
    {"name": "慎", "emoji": "⚔️⚡🤖", "title": "暮光之眼", "quote": "均衡存乎万物之间", "region": "艾欧尼亚",
     "aliases": ["shen", "shen", "慎"]},
    {"name": "凯南", "emoji": "⚡🐹🗡️", "title": "狂暴之心", "quote": "均衡，不容破坏", "region": "艾欧尼亚",
     "aliases": ["kennen", "kai nan", "凯南"]},
    {"name": "辛德拉", "emoji": "⚫🌀👑", "title": "暗黑元首", "quote": "我的潜能，无穷无尽", "region": "艾欧尼亚",
     "aliases": ["syndra", "xin de la", "辛德拉"]},
    {"name": "卢锡安", "emoji": "🔫🔫🖤", "title": "圣枪游侠", "quote": "净化她！", "region": "暗影岛",
     "aliases": ["lucian", "lu xi an", "卢锡安", "奥巴马"]},
    {"name": "格雷福斯", "emoji": "🔫💨🧔", "title": "法外狂徒", "quote": "死路一条", "region": "比尔吉沃特",
     "aliases": ["graves", "ge lei fu si", "格雷福斯", "男枪"]},
    {"name": "崔斯特", "emoji": "🃏🎩🔮", "title": "卡牌大师", "quote": "幸运女神在微笑", "region": "比尔吉沃特",
     "aliases": ["twisted fate", "tf", "cui si te", "崔斯特", "卡牌"]},
    {"name": "萨科", "emoji": "🤡🔪🎭", "title": "恶魔小丑", "quote": "来次魔术戏法，怎么样？", "region": "符文之地",
     "aliases": ["shaco", "sa ke", "萨科", "小丑"]},
    {"name": "亚托克斯", "emoji": "🗡️😈🩸", "title": "暗裔剑魔", "quote": "我曾经是神", "region": "恕瑞玛",
     "aliases": ["aatrox", "ya tuo ke si", "亚托克斯", "剑魔", "暗裔剑魔"]},
    {"name": "内瑟斯", "emoji": "🐶📖⚡", "title": "沙漠死神", "quote": "生与死，轮回不止", "region": "恕瑞玛",
     "aliases": ["nasus", "nei se si", "内瑟斯", "狗头"]},
    {"name": "阿兹尔", "emoji": "🦅🏜️👑", "title": "沙漠皇帝", "quote": "恕瑞玛，你的皇帝回来了", "region": "恕瑞玛",
     "aliases": ["azir", "a zi er", "阿兹尔", "沙皇"]},
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
            f"直接发送英雄名字/英文名/花名即可！"
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

                guess = msg.content.strip().lower()
                champ_aliases = [a.lower() for a in champion["aliases"]]

                if guess in champ_aliases:
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
