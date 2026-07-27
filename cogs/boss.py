"""
GMPT Bot — Boss Dungeon / 组队副本系统
副本式Boss战 — 冷却、阶段、掉落、排行榜、数据库持久化
"""
import asyncio
import random
import time
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
from cogs.economy import get_balance, add_coins
import logging

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Boss / Dungeon definitions
# ══════════════════════════════════════════════════════════════

BOSS_TYPES = {
    "金龙": {
        "emoji": "🐉", "desc": "Gold Dragon — 喷吐金色火焰！",
        "skills": ["龙息", "龙尾扫", "金币雨"],
        "rage_skill": "🔥 龙神之怒！伤害×2",
        "loot_table": [
            (0.15, "龙鳞碎片", 300), (0.10, "金龙宝珠", 800),
            (0.05, "龙牙项链", 2000), (0.02, "金龙坐骑碎片", 5000),
        ],
        "cooldown_min": {"简单": 5, "普通": 15, "困难": 30},
    },
    "暗影领主": {
        "emoji": "👹", "desc": "Shadow Lord — 暗影之力笼罩战场！",
        "skills": ["暗影斩", "黑洞", "恐惧凝视"],
        "rage_skill": "🌑 无尽暗影！全体伤害",
        "loot_table": [
            (0.15, "暗影碎片", 350), (0.10, "暗影之心", 900),
            (0.05, "暗影披风", 2200), (0.02, "暗影王冠", 5500),
        ],
        "cooldown_min": {"简单": 5, "普通": 15, "困难": 30},
    },
    "冰霜巨人": {
        "emoji": "🧊", "desc": "Frost Giant — 冻结一切！",
        "skills": ["冰锥", "暴风雪", "永冻"],
        "rage_skill": "❄️ 绝对零度！攻击附带冰冻",
        "loot_table": [
            (0.15, "冰晶碎片", 400), (0.10, "冰霜核心", 1000),
            (0.05, "冰封之盾", 2500), (0.02, "永冻王冠", 6000),
        ],
        "cooldown_min": {"简单": 5, "普通": 15, "困难": 30},
    },
    "地狱犬": {
        "emoji": "🔥", "desc": "Hellhound — 三头地狱犬喷吐烈焰！",
        "skills": ["三重撕咬", "地狱火", "咆哮"],
        "rage_skill": "💥 地狱烈焰！全体灼烧",
        "loot_table": [
            (0.15, "地狱火碎片", 450), (0.10, "地狱核心", 1100),
            (0.05, "地狱护符", 2800), (0.02, "三头犬缰绳", 7000),
        ],
        "cooldown_min": {"简单": 5, "普通": 15, "困难": 30},
    },
}

DIFFICULTY = {
    "简单": {"label": "Easy / 简单", "hp_mult": 1.0, "atk_mult": 0.7, "reward_mult": 0.5, "color": 0x2ECC71, "stars": "⭐"},
    "普通": {"label": "Normal / 普通", "hp_mult": 2.0, "atk_mult": 1.0, "reward_mult": 1.0, "color": 0xF39C12, "stars": "⭐⭐"},
    "困难": {"label": "Hard / 困难", "hp_mult": 4.0, "atk_mult": 1.5, "reward_mult": 2.0, "color": 0xE74C3C, "stars": "⭐⭐⭐"},
}

RAGE_HP_RATIO = 0.5  # Boss enters rage at 50% HP


# ══════════════════════════════════════════════════════════════
# Boss Cog
# ══════════════════════════════════════════════════════════════

class BossCog(CogBase):
    """副本Boss战 / Dungeon Boss Battle System"""

    gmpt_boss_group = app_commands.Group(
        name="gmpt-boss",
        description="副本Boss战 / Dungeon Boss — 组队挑战"
    )

    def __init__(self, bot):
        self.bot = bot
        self.boss_sessions: dict[str, dict] = {}  # channel_id -> session
        self.boss_lock = asyncio.Lock()

    # ── helpers ──

    @staticmethod
    def _format_hp_bar(current: int, maximum: int, length: int = 20) -> str:
        ratio = max(0, current / max(1, maximum))
        filled = int(ratio * length)
        bar = "█" * filled + "░" * (length - filled)
        pct = int(ratio * 100)
        return f"[{bar}] {pct}% ({current}/{maximum})"

    @staticmethod
    def _get_cooldown_remaining(user_id: str, boss_name: str, difficulty: str) -> int:
        """Return seconds remaining, 0 if off cooldown."""
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT last_cleared_at FROM boss_dungeon_cooldowns
                WHERE user_id = ? AND boss_name = ? AND difficulty = ?
            """, (user_id, boss_name, difficulty))
            row = cur.fetchone()
        if not row:
            return 0
        cd_min = BOSS_TYPES.get(boss_name, {}).get("cooldown_min", {}).get(difficulty, 15)
        elapsed = time.time() - float(row[0])
        remaining = max(0, cd_min * 60 - int(elapsed))
        return remaining

    @staticmethod
    def _set_cooldown(user_id: str, boss_name: str, difficulty: str):
        with get_db_ctx() as conn:
            conn.cursor().execute("""
                INSERT OR REPLACE INTO boss_dungeon_cooldowns (user_id, boss_name, difficulty, last_cleared_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, boss_name, difficulty, str(time.time())))
            conn.commit()

    @staticmethod
    def _record_kill(boss_name: str, difficulty: str, user_id: str, dmg: int, duration_sec: float):
        with get_db_ctx() as conn:
            cur = conn.cursor()
            # Update global boss stats
            cur.execute("""
                INSERT INTO boss_kill_stats (boss_name, difficulty, kill_count, fastest_clear_seconds, total_damage, first_clear_by)
                VALUES (?, ?, 1, ?, ?, ?)
                ON CONFLICT(boss_name, difficulty) DO UPDATE SET
                    kill_count = kill_count + 1,
                    fastest_clear_seconds = MIN(fastest_clear_seconds, ?),
                    total_damage = total_damage + ?
            """, (boss_name, difficulty, duration_sec, user_id, duration_sec, dmg))
            # Update player kill stats
            cur.execute("""
                INSERT INTO boss_player_kills (user_id, boss_name, difficulty, kills, top_damage, last_kill_at)
                VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(user_id, boss_name, difficulty) DO UPDATE SET
                    kills = kills + 1,
                    top_damage = MAX(top_damage, ?),
                    last_kill_at = ?
            """, (user_id, boss_name, difficulty, dmg, str(time.time()), dmg, str(time.time())))
            conn.commit()

    @staticmethod
    def _get_daily_first_kill(user_id: str) -> bool:
        """Check if user has already got a daily first-kill bonus today."""
        import datetime
        today = datetime.date.today().isoformat()
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 1 FROM boss_player_kills
                WHERE user_id = ? AND date(last_kill_at) = ?
            """, (user_id, today))
            return cur.fetchone() is None

    def _roll_loot(self, boss_name: str) -> list[tuple[str, int]]:
        """Roll loot from boss loot table. Returns list of (item_name, value)."""
        loot_table = BOSS_TYPES.get(boss_name, {}).get("loot_table", [])
        drops = []
        for prob, item_name, value in loot_table:
            if random.random() < prob:
                drops.append((item_name, value))
        return drops

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss dungeon — 查看副本列表
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="dungeon",
        description="查看所有副本Boss与冷却 / View all dungeon bosses & cooldowns"
    )
    async def boss_dungeon(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        embed = discord.Embed(
            title="🏰 副本大厅 / Dungeon Hall",
            description="选择 Boss 发起挑战！所有冷却按难度独立计算",
            color=0x9B59B6,
        )

        for boss_name, boss in BOSS_TYPES.items():
            lines = []
            for diff, diff_cfg in DIFFICULTY.items():
                cd = self._get_cooldown_remaining(uid, boss_name, diff)
                if cd <= 0:
                    status = "✅ 可挑战 / Ready"
                else:
                    m, s = divmod(cd, 60)
                    status = f"⏳ {m}分{s}秒 / Cooling down"
                lines.append(f"{diff_cfg['stars']} {diff}: {status}")
            lines.append(f"掉落: {', '.join(f'{name}({val}₲)' for _, name, val in boss['loot_table'][:2])}")
            embed.add_field(
                name=f"{boss['emoji']} {boss_name}",
                value="\n".join(lines),
                inline=True,
            )

        embed.set_footer(text="使用 /gmpt-boss create <Boss> <难度> 创建副本 | Use /gmpt-boss create <boss> <difficulty>")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss leaderboard — 排行榜
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="leaderboard",
        description="Boss击杀排行榜 / Boss kill leaderboard"
    )
    @app_commands.describe(
        boss_type="Boss类型 (留空显示全部)",
        difficulty="难度 (留空显示全部)",
    )
    async def boss_leaderboard(
        self,
        interaction: discord.Interaction,
        boss_type: str = None,
        difficulty: str = None,
    ):
        embed = discord.Embed(
            title="🏆 Boss排行榜 / Boss Leaderboard",
            color=0xF1C40F,
        )

        with get_db_ctx() as conn:
            cur = conn.cursor()
            if boss_type:
                # Specific boss leaderboard
                query = """
                    SELECT user_id, boss_name, difficulty, kills, top_damage, last_kill_at
                    FROM boss_player_kills
                    WHERE boss_name = ?
                """
                params = [boss_type]
                if difficulty:
                    query += " AND difficulty = ?"
                    params.append(difficulty)
                query += " ORDER BY kills DESC, top_damage DESC LIMIT 10"
                cur.execute(query, params)
                rows = cur.fetchall()

                title_suffix = f" — {boss_type}"
                if difficulty:
                    title_suffix += f" ({difficulty})"
                embed.title += title_suffix

                if not rows:
                    embed.description = "暂无击杀记录 / No kills yet."
                else:
                    lines = []
                    for i, row in enumerate(rows, 1):
                        uid, bname, diff, kills, top_dmg, last_at = row
                        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"#{i}")
                        lines.append(
                            f"{medal} <@{uid}> — {kills}杀 {diff} | 最高{top_dmg}伤害"
                        )
                    embed.description = "\n".join(lines)
            else:
                # Overall dungeon stats
                cur.execute("""
                    SELECT boss_name, difficulty, kill_count, fastest_clear_seconds, first_clear_by
                    FROM boss_kill_stats ORDER BY kill_count DESC LIMIT 12
                """)
                rows = cur.fetchall()
                if not rows:
                    embed.description = "暂无击杀记录 / No kills yet."
                else:
                    for boss_name, diff, kills, fastest, first_clearer in rows:
                        fastest_str = f"{fastest:.0f}s" if fastest else "-"
                        embed.add_field(
                            name=f"{boss_name} {DIFFICULTY.get(diff, {}).get('stars', '')} {diff}",
                            value=f"击杀: {kills} | 最快: {fastest_str} | 首杀: <@{first_clearer}>",
                            inline=True,
                        )

        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss stats — 个人统计
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="stats",
        description="查看个人Boss统计 / Personal boss stats"
    )
    async def boss_stats(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        embed = discord.Embed(
            title=f"📊 {interaction.user.display_name} 的副本统计 / Dungeon Stats",
            color=0x3498DB,
        )

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT boss_name, difficulty, kills, top_damage, last_kill_at
                FROM boss_player_kills WHERE user_id = ?
                ORDER BY kills DESC
            """, (uid,))
            rows = cur.fetchall()

        if not rows:
            embed.description = "尚未击杀任何Boss / No boss kills yet."
        else:
            total_kills = sum(r[2] for r in rows)
            embed.description = f"总计击杀: **{total_kills}**"
            for boss_name, diff, kills, top_dmg, last_at in rows:
                embed.add_field(
                    name=f"{BOSS_TYPES.get(boss_name, {}).get('emoji', '')} {boss_name} ({diff})",
                    value=f"击杀: {kills} | 最高伤害: {top_dmg}",
                    inline=True,
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss create <type> <difficulty>
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="create",
        description="创建副本Boss房间 / Create dungeon boss room"
    )
    @app_commands.describe(
        boss_type="Boss: 金龙 / 暗影领主 / 冰霜巨人 / 地狱犬",
        difficulty="难度: 简单 / 普通 / 困难",
    )
    async def boss_create(
        self,
        interaction: discord.Interaction,
        boss_type: str = "金龙",
        difficulty: str = "普通",
    ):
        chid = str(interaction.channel_id)
        uid = str(interaction.user.id)

        if chid in self.boss_sessions and self.boss_sessions[chid].get("active"):
            return await interaction.response.send_message(
                "本频道已有进行中的 Boss 战！/ Boss battle already in progress!", ephemeral=True)

        if boss_type not in BOSS_TYPES:
            types_str = " / ".join(BOSS_TYPES.keys())
            return await interaction.response.send_message(
                f"无效Boss！可选: {types_str}\nInvalid boss! Options: {types_str}", ephemeral=True)

        if difficulty not in DIFFICULTY:
            diffs = " / ".join(DIFFICULTY.keys())
            return await interaction.response.send_message(
                f"无效难度！可选: {diffs}\nInvalid difficulty! Options: {diffs}", ephemeral=True)

        # Check personal cooldown
        cd = self._get_cooldown_remaining(uid, boss_type, difficulty)
        if cd > 0:
            m, s = divmod(cd, 60)
            return await interaction.response.send_message(
                f"⏳ 冷却中！{m}分{s}秒后可挑战 / On cooldown! {m}m{s}s remaining.\n"
                f"使用 `/gmpt-boss dungeon` 查看所有冷却状态",
                ephemeral=True,
            )

        boss = BOSS_TYPES[boss_type]
        diff = DIFFICULTY[difficulty]
        base_hp = random.randint(600, 1000)
        hp = int(base_hp * diff["hp_mult"])
        atk = int(random.randint(25, 55) * diff["atk_mult"])

        session = {
            "active": True,
            "boss_type": boss_type,
            "emoji": boss["emoji"],
            "difficulty": difficulty,
            "diff_label": diff["label"],
            "hp": hp,
            "max_hp": hp,
            "atk": atk,
            "color": diff["color"],
            "reward_mult": diff["reward_mult"],
            "skills": boss["skills"],
            "rage_skill": boss["rage_skill"],
            "in_rage": False,
            "players": {},
            "creator": uid,
            "channel_id": chid,
            "turn": 0,
            "start_time": time.time(),
            "log": [],
        }

        session["players"][uid] = {
            "name": interaction.user.display_name,
            "dmg": 0,
            "crits": 0,
            "alive": True,
            "joined_at": time.time(),
        }

        self.boss_sessions[chid] = session

        embed = self._build_boss_embed(session)
        await interaction.response.send_message(
            f"{boss['emoji']} **{interaction.user.display_name}** 创建了副本！60秒内 `/gmpt-boss join` 加入\n"
            f"Dungeon created! Use `/gmpt-boss join` within 60s",
            embed=embed,
        )

        self.bot.loop.create_task(self._boss_start_timer(interaction, chid))

    async def _boss_start_timer(self, interaction: discord.Interaction, chid: str):
        await asyncio.sleep(60)
        session = self.boss_sessions.get(chid)
        if not session or not session.get("active"):
            return
        if len(session["players"]) < 1:
            session["active"] = False
            await interaction.channel.send("⏰ 副本已取消（无玩家加入）/ Dungeon cancelled (no players).")
            return

        alive = sum(1 for p in session["players"].values() if p["alive"])
        await interaction.channel.send(
            f"⚔️ **副本开始！/ Dungeon begins!**\n"
            f"玩家数: {len(session['players'])} | 存活: {alive}\n"
            f"使用 `/gmpt-boss attack` 攻击！"
        )

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss join
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="join",
        description="加入副本 / Join dungeon"
    )
    async def boss_join(self, interaction: discord.Interaction):
        chid = str(interaction.channel_id)
        uid = str(interaction.user.id)

        session = self.boss_sessions.get(chid)
        if not session or not session.get("active"):
            return await interaction.response.send_message("本频道无进行中的副本 / No active dungeon.", ephemeral=True)

        if uid in session["players"]:
            return await interaction.response.send_message("你已经加入了！/ You already joined!", ephemeral=True)

        # Check cooldown
        cd = self._get_cooldown_remaining(uid, session["boss_type"], session["difficulty"])
        if cd > 0:
            m, s = divmod(cd, 60)
            return await interaction.response.send_message(
                f"⏳ 该Boss冷却中！{m}分{s}秒后可加入 / On cooldown!", ephemeral=True)

        session["players"][uid] = {
            "name": interaction.user.display_name,
            "dmg": 0,
            "crits": 0,
            "alive": True,
            "joined_at": time.time(),
        }

        embed = self._build_boss_embed(session)
        await interaction.response.send_message(
            f"✅ **{interaction.user.display_name}** 加入了副本！/ Joined!",
            embed=embed,
        )

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss attack
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="attack",
        description="攻击Boss / Attack boss"
    )
    @app_commands.checks.cooldown(1, 8.0, key=lambda i: i.user.id)
    async def boss_attack(self, interaction: discord.Interaction):
        chid = str(interaction.channel_id)
        uid = str(interaction.user.id)

        session = self.boss_sessions.get(chid)
        if not session or not session.get("active"):
            return await interaction.response.send_message("本频道没有进行中的副本 / No active dungeon.", ephemeral=True)

        if uid not in session["players"]:
            return await interaction.response.send_message("请先 `/gmpt-boss join` 加入 / Join first!", ephemeral=True)

        player = session["players"][uid]
        if not player["alive"]:
            return await interaction.response.send_message("你已阵亡！等待副本结束 / You are dead!", ephemeral=True)

        # Check rage phase
        rage = session["hp"] <= session["max_hp"] * RAGE_HP_RATIO
        if rage and not session.get("in_rage"):
            session["in_rage"] = True
            session["atk"] = int(session["atk"] * 2)

        # Player attack
        atk_type = random.choices(
            ["普通攻击", "普通攻击", "普通攻击", "暴击", "技能"],
            weights=[50, 50, 50, 25, 15],
            k=1,
        )[0]

        if atk_type == "暴击":
            dmg = random.randint(60, 150)
            player["crits"] += 1
            dmg_text = f"⚡ **暴击！/ CRIT!** — {dmg} 伤害"
        elif atk_type == "技能":
            dmg = random.randint(45, 100)
            dmg_text = f"✨ **技能！/ Skill!** — {dmg} 伤害"
        else:
            dmg = random.randint(20, 50)
            dmg_text = f"⚔️ 普通攻击 — {dmg} 伤害"

        session["hp"] = max(0, session["hp"] - dmg)
        player["dmg"] += dmg
        session["turn"] += 1

        # Boss counter-attack (rage = stronger)
        boss_dmg = random.randint(8 if rage else 3, session["atk"])
        boss_target = random.choice(list(session["players"].keys()))
        boss_target_player = session["players"][boss_target]
        rage_tag = " 🔥暴怒 / RAGING!" if rage else ""
        boss_dmg_text = (
            f"\n{session['emoji']} Boss{rage_tag} 反击了 **{boss_target_player['name']}** ！"
            f" — {boss_dmg} 伤害"
        )

        # Death chance (higher in rage)
        death_chance = 0.15 if rage else 0.08
        player_death = ""
        if random.random() < death_chance:
            boss_target_player["alive"] = False
            player_death = f"\n💀 **{boss_target_player['name']}** 被击倒了！/ Knocked down!"

        # Check if boss defeated
        boss_defeated = session["hp"] <= 0

        lines = [
            f"**{interaction.user.display_name}** {dmg_text}",
            f"HP: {self._format_hp_bar(session['hp'], session['max_hp'])}",
        ]
        if session.get("in_rage"):
            lines.append(f"⚠️ Boss进入暴怒阶段！攻击翻倍 / RAGE PHASE!")
        lines.append(boss_dmg_text)
        if player_death:
            lines.append(player_death)

        if boss_defeated:
            session["active"] = False
            duration = time.time() - session["start_time"]
            lines.append("")
            lines.append(f"🎉 **{session['boss_type']} 被击败！/ Defeated!** ({duration:.0f}s)")

            # MVP
            mvp_uid = max(session["players"].items(), key=lambda x: x[1]["dmg"])[0]
            mvp_name = session["players"][mvp_uid]["name"]
            lines.append(f"🏆 MVP: **{mvp_name}** ({session['players'][mvp_uid]['dmg']} 伤害)")

            # Reward pool
            reward_pool = int(session["max_hp"] * session["reward_mult"] * 0.8)
            total_dmg = sum(p["dmg"] for p in session["players"].values())
            reward_lines = []

            for pid, p in session["players"].items():
                share = int(reward_pool * p["dmg"] / max(1, total_dmg))
                # Daily first kill bonus: 2x coins
                if self._get_daily_first_kill(pid):
                    share = int(share * 2)
                    first_bonus = " (首杀双倍！/ 2x First Kill!)"
                else:
                    first_bonus = ""

                add_coins(pid, share, f"Boss副本奖励: {session['boss_type']} {session['difficulty']}")

                # Loot drops
                drops = self._roll_loot(session["boss_type"])
                loot_text = ""
                if drops:
                    for item_name, value in drops:
                        add_coins(pid, value, f"掉落: {item_name}")
                        loot_text += f" + 🎁 {item_name}({value}₲)"

                # MVP bonus
                mvp_bonus = ""
                if pid == mvp_uid:
                    mvp_bonus = f" + 🏆 MVP额外+{int(share * 0.5)}₲"
                    add_coins(pid, int(share * 0.5), "Boss MVP奖励")

                reward_lines.append(
                    f"- **{p['name']}**: {p['dmg']}伤害 → 🪙 +{share}{first_bonus}{loot_text}{mvp_bonus}"
                )

                # Set cooldown & record kill
                self._set_cooldown(pid, session["boss_type"], session["difficulty"])
                self._record_kill(session["boss_type"], session["difficulty"], pid, p["dmg"], duration)

            lines.append("\n**💰 奖励分配 / Rewards:**")
            lines.extend(reward_lines)

        await interaction.response.send_message("\n".join(lines[:25]))  # Discord limit safety

        if boss_defeated:
            embed = self._build_boss_embed(session, defeated=True)
            await interaction.channel.send(embed=embed)

    # ══════════════════════════════════════════════════════════
    # /gmpt-boss status
    # ══════════════════════════════════════════════════════════

    @gmpt_boss_group.command(
        name="status",
        description="查看副本战况 / View dungeon status"
    )
    async def boss_status(self, interaction: discord.Interaction):
        chid = str(interaction.channel_id)
        session = self.boss_sessions.get(chid)
        if not session:
            return await interaction.response.send_message("本频道无进行中的副本 / No active dungeon.", ephemeral=True)

        embed = self._build_boss_embed(session)
        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # Embed builder
    # ══════════════════════════════════════════════════════════

    def _build_boss_embed(self, session: dict, defeated: bool = False) -> discord.Embed:
        emoji = session["emoji"]
        boss_name = session["boss_type"]
        title = f"{emoji} {boss_name} 副本 / Dungeon"
        if defeated:
            title = f"{emoji} {boss_name} — 已击败！/ Defeated!"
        elif session.get("in_rage"):
            title = f"{emoji} {boss_name} — ⚠️ 暴怒阶段！/ RAGE!"

        embed = discord.Embed(title=title, color=session["color"])
        embed.add_field(name="难度 / Difficulty", value=session["diff_label"], inline=True)
        embed.add_field(
            name="Boss HP",
            value=self._format_hp_bar(session["hp"], session["max_hp"]),
            inline=False,
        )
        embed.add_field(name="攻击力 / ATK", value=str(session["atk"]), inline=True)
        embed.add_field(name="回合 / Turn", value=str(session["turn"]), inline=True)
        embed.add_field(
            name="技能 / Skills",
            value=" | ".join(session["skills"]),
            inline=False,
        )
        if session.get("in_rage"):
            embed.add_field(
                name="⚠️ 暴怒技能 / Rage Skill",
                value=session.get("rage_skill", "?"),
                inline=False,
            )

        # Player list with damage
        player_list = []
        damage_list = []
        for pid, p in session["players"].items():
            status_icon = "" if p["alive"] else "💀"
            crit_count = f" ({p.get('crits', 0)}暴击)" if p.get("crits", 0) > 0 else ""
            player_list.append(f"{status_icon} {p['name']}{crit_count}")
            damage_list.append(f"{p['dmg']} dmg")
        embed.add_field(
            name=f"玩家 / Players ({len(session['players'])})",
            value="\n".join(player_list) if player_list else "等待加入 / Waiting...",
            inline=True,
        )
        embed.add_field(
            name="伤害贡献 / Damage",
            value="\n".join(damage_list) if damage_list else "-",
            inline=True,
        )

        embed.set_footer(text="使用 /gmpt-boss attack 攻击 | Use /gmpt-boss attack to strike!")
        return embed


# ══════════════════════════════════════════════════════════════
# Cog setup
# ══════════════════════════════════════════════════════════════

async def setup(bot):
    await bot.add_cog(BossCog(bot))
