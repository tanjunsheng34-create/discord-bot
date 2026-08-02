"""
GMPT Bot — MMORPG Arena 3v3 / 3v3 竞技场
/gmpt-arena-3v3 create — 队长发起 3v3 组队
/gmpt-arena-3v3 join   — 加入队伍
/gmpt-arena-3v3 start  — 队长开战
"""
import asyncio
import datetime
import logging
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
from utils.animations import progress_bar
from cogs.economy import get_balance, add_coins
from cogs.mmorpg_skills import SKILLS

logger = logging.getLogger(__name__)

ELEMENTS = ["Fire", "Water", "Wind", "Earth"]
ELEMENT_WEAKNESS = {"Fire": "Wind", "Wind": "Earth", "Earth": "Water", "Water": "Fire"}
ARENA_LOBBY_TIMEOUT = 60  # seconds for team to fill
TURN_TIMEOUT = 45  # seconds per turn in 3v3
RANKED_POINTS_WIN = 15


def _get_user_stats(uid: str) -> dict:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT hp, max_hp, mp, max_mp, attack, defense, level, speed FROM users WHERE discord_id = ?",
            (uid,),
        )
        row = cur.fetchone()
    if row:
        d = dict(row)
        d.setdefault("speed", 10)
        return d
    return {"hp": 100, "max_hp": 100, "mp": 50, "max_mp": 50, "attack": 10, "defense": 5, "level": 1, "speed": 10}


def _save_stats(uid: str, stats: dict):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET hp = ?, mp = ? WHERE discord_id = ?",
                     (min(stats["hp"], stats["max_hp"]), max(0, stats["mp"]), uid))
        conn.commit()


def _get_player_element(uid: str) -> str:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT element FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return (row["element"] or "none") if row else "none"


def _calc_element_mult(atk_elem: str, def_elem: str) -> float:
    if atk_elem == def_elem:
        return 1.0
    if ELEMENT_WEAKNESS.get(atk_elem) == def_elem:
        return 1.3
    if ELEMENT_WEAKNESS.get(def_elem) == atk_elem:
        return 0.8
    return 1.0


# ══════════════════════════════════════════════════════════════
# Arena 3v3 Lobby View
# ══════════════════════════════════════════════════════════════
class Arena3v3LobbyView(discord.ui.View):
    """3v3 lobby — leader can start, members can join/leave."""

    def __init__(self, lobby: dict):
        super().__init__(timeout=ARENA_LOBBY_TIMEOUT)
        self.lobby = lobby

    def build_embed(self) -> discord.Embed:
        team_a = [f"<@{u}>" for u in self.lobby["team_a"]]
        team_b = [f"<@{u}>" for u in self.lobby["team_b"]]

        embed = discord.Embed(
            title="🏟️ Arena 3v3 / 3v3 竞技场",
            description=f"Team A vs Team B — {len(self.lobby['team_a'])}v{len(self.lobby['team_b'])}",
            color=0x3498DB,
        )
        embed.add_field(
            name=f"🔵 Team A ({len(team_a)}/3)",
            value="\n".join(team_a) if team_a else "Empty / 空",
            inline=True,
        )
        embed.add_field(
            name=f"🔴 Team B ({len(team_b)}/3)",
            value="\n".join(team_b) if team_b else "Empty / 空",
            inline=True,
        )
        embed.set_footer(text=f"Leader / 队长: <@{self.lobby['leader']}> | Both teams need 3 players / 两队各需3人")
        return embed

    async def update_message(self):
        embed = self.build_embed()
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(embed=embed, view=self)
        except discord.NotFound:
            pass

    @discord.ui.button(label="Join A / 加入蓝队", style=discord.ButtonStyle.primary, emoji="🔵", row=0)
    async def join_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid in self.lobby["team_a"] or uid in self.lobby["team_b"]:
            await interaction.response.send_message("Already in a team! / 你已在队伍中！", ephemeral=True)
            return
        if len(self.lobby["team_a"]) >= 3:
            await interaction.response.send_message("Team A is full! / 蓝队已满！", ephemeral=True)
            return
        self.lobby["team_a"].append(uid)
        await self.update_message()
        await interaction.response.send_message(f"✅ Joined Team A! / 加入蓝队！({len(self.lobby['team_a'])}/3)", ephemeral=True)

    @discord.ui.button(label="Join B / 加入红队", style=discord.ButtonStyle.danger, emoji="🔴", row=0)
    async def join_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid in self.lobby["team_a"] or uid in self.lobby["team_b"]:
            await interaction.response.send_message("Already in a team! / 你已在队伍中！", ephemeral=True)
            return
        if len(self.lobby["team_b"]) >= 3:
            await interaction.response.send_message("Team B is full! / 红队已满！", ephemeral=True)
            return
        self.lobby["team_b"].append(uid)
        await self.update_message()
        await interaction.response.send_message(f"✅ Joined Team B! / 加入红队！({len(self.lobby['team_b'])}/3)", ephemeral=True)

    @discord.ui.button(label="Leave / 离开", style=discord.ButtonStyle.secondary, emoji="🚪", row=1)
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        for team in ("team_a", "team_b"):
            if uid in self.lobby[team]:
                self.lobby[team].remove(uid)
                await self.update_message()
                await interaction.response.send_message("Left the team / 已离开队伍", ephemeral=True)
                return
        await interaction.response.send_message("Not in any team / 不在任何队伍中", ephemeral=True)

    @discord.ui.button(label="Start / 开始战斗", style=discord.ButtonStyle.success, emoji="⚔️", row=1)
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.lobby["leader"]:
            await interaction.response.send_message("Only the leader can start! / 只有队长可以开始！", ephemeral=True)
            return
        if len(self.lobby["team_a"]) < 3 or len(self.lobby["team_b"]) < 3:
            await interaction.response.send_message("Both teams need 3 players! / 两队各需3人！", ephemeral=True)
            return

        self.lobby["status"] = "starting"
        if hasattr(self, 'message') and self.message:
            await self.message.edit(view=None)
        for child in self.children:
            child.disabled = True

        await interaction.response.send_message("⚔️ 3v3 Arena battle starting! / 3v3 战斗即将开始！")
        self.stop()


async def _run_3v3_battle(lobby: dict, channel, ranked_cog=None):
    """Execute 3v3 battle."""
    team_a = {}
    team_b = {}
    for uid in lobby["team_a"]:
        stats = _get_user_stats(uid)
        elem = _get_player_element(uid)
        team_a[uid] = {
            "id": uid, "username": f"Player_{uid[-4:]}",
            "hp": stats["hp"], "max_hp": stats["max_hp"],
            "mp": stats.get("mp", 50), "max_mp": stats.get("max_mp", 50),
            "atk": stats["attack"], "def": stats["defense"],
            "speed": stats.get("speed", 10), "element": elem, "alive": True,
            "total_dmg": 0, "skills_used": 0,
        }
    for uid in lobby["team_b"]:
        stats = _get_user_stats(uid)
        elem = _get_player_element(uid)
        team_b[uid] = {
            "id": uid, "username": f"Player_{uid[-4:]}",
            "hp": stats["hp"], "max_hp": stats["max_hp"],
            "mp": stats.get("mp", 50), "max_mp": stats.get("max_mp", 50),
            "atk": stats["attack"], "def": stats["defense"],
            "speed": stats.get("speed", 10), "element": elem, "alive": True,
            "total_dmg": 0, "skills_used": 0,
        }

    round_num = 0

    embed = discord.Embed(
        title="🏟️ 3v3 Arena Battle! / 3v3 竞技场战斗！",
        color=0x3498DB,
    )
    msg = await channel.send(embed=embed)

    while True:
        alive_a = [p for p in team_a.values() if p["alive"]]
        alive_b = [p for p in team_b.values() if p["alive"]]

        if not alive_a or not alive_b:
            break

        round_num += 1
        # Sort all alive by speed
        all_alive = sorted(alive_a + alive_b, key=lambda p: p["speed"], reverse=True)

        round_log = [f"**Round {round_num}**"]
        for attacker in all_alive:
            if not attacker["alive"]:
                continue

            # Determine which team is the enemy
            enemy_team = team_a if attacker["id"] in [p["id"] for p in team_b.values()] else team_b
            if attacker["id"] in team_a:
                enemy_team = team_b

            # Pick a target randomly from alive enemies
            enemy_alive = [e for e in enemy_team.values() if e["alive"]]
            if not enemy_alive:
                break
            target = random.choice(enemy_alive)

            # Calculate damage
            base_dmg = max(1, attacker["atk"] - target["def"] // 2)
            elem_mult = _calc_element_mult(attacker.get("element"), target.get("element"))
            crit_mult = 2.0 if random.random() < 0.15 else 1.0
            variation = random.uniform(0.8, 1.2)
            dmg = int(base_dmg * elem_mult * crit_mult * variation)

            target["hp"] = max(0, target["hp"] - dmg)
            attacker["total_dmg"] += dmg

            crit_str = "💥 CRIT! " if crit_mult > 1.0 else ""
            elem_str = f" [元素优势]" if elem_mult > 1.0 else (f" [元素劣势]" if elem_mult < 1.0 else "")
            round_log.append(
                f"{crit_str}<@{attacker['id']}> → <@{target['id']}>: **{dmg} DMG**{elem_str}"
            )

            if target["hp"] <= 0:
                target["alive"] = False
                round_log.append(f"☠️ <@{target['id']}> 阵亡 / Defeated!")

        # Update embed
        embed.description = "\n".join(round_log[-20:])
        embed.clear_fields()

        # Team A status
        a_hp_lines = []
        for p in team_a.values():
            icon = "☠️" if not p["alive"] else "❤️"
            hp_bar = progress_bar(max(0, p["hp"]), p["max_hp"], 8)
            a_hp_lines.append(f"{icon} <@{p['id']}> {hp_bar} {p['hp']}/{p['max_hp']} | DMG:{p['total_dmg']}")
        embed.add_field(name=f"🔵 Team A ({len(alive_a)} alive)", value="\n".join(a_hp_lines), inline=True)

        b_hp_lines = []
        for p in team_b.values():
            icon = "☠️" if not p["alive"] else "❤️"
            hp_bar = progress_bar(max(0, p["hp"]), p["max_hp"], 8)
            b_hp_lines.append(f"{icon} <@{p['id']}> {hp_bar} {p['hp']}/{p['max_hp']} | DMG:{p['total_dmg']}")
        embed.add_field(name=f"🔴 Team B ({len(alive_b)} alive)", value="\n".join(b_hp_lines), inline=True)

        try:
            await msg.edit(embed=embed)
        except (discord.NotFound, discord.HTTPException):
            pass

        await asyncio.sleep(1.5)

    # Determine winner
    alive_a_count = len([p for p in team_a.values() if p["alive"]])
    alive_b_count = len([p for p in team_b.values() if p["alive"]])
    if alive_a_count > alive_b_count:
        winner_team = "A"
        winner_ids = lobby["team_a"]
    elif alive_b_count > alive_a_count:
        winner_team = "B"
        winner_ids = lobby["team_b"]
    else:
        winner_team = None
        winner_ids = []

    if winner_ids:
        for uid in winner_ids:
            add_coins(uid, 300, "3v3 Arena win / 3v3竞技场获胜")
            # Award ranked points if ranked_cog available
            if ranked_cog:
                try:
                    ranked_cog.add_ranked_points(uid, True)
                except Exception:
                    pass

    # Final embed
    embed.description = f"**Battle Over! / 战斗结束！**\n{'🔵 Team A' if winner_team == 'A' else '🔴 Team B' if winner_team == 'B' else '🤝 Draw / 平局!'} wins! / 获胜！每名胜者获得 300₲ + 15排位分"
    embed.color = 0xF1C40F if winner_team else 0x95A5A6
    embed.set_footer(text="3v3 Arena / 3v3竞技场")
    try:
        await msg.edit(embed=embed)
    except (discord.NotFound, discord.HTTPException):
        await channel.send(embed=embed)

    # Save stats
    for uid in lobby["team_a"] + lobby["team_b"]:
        stats = _get_user_stats(uid)
        _save_stats(uid, stats)


# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════
class Arena3v3Cog(commands.Cog):
    """3v3 Arena system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lobbies: dict = {}  # channel_id -> lobby dict

    @app_commands.command(
        name="gmpt-arena-3v3",
        description="3v3 Arena / 3v3竞技场 — create, join, start"
    )
    @app_commands.describe(action="create=创建房间 / join=加入 / start=开始")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
    async def arena_3v3(self, interaction: discord.Interaction, action: str):
        uid = str(interaction.user.id)
        channel_id = interaction.channel_id

        if action.lower() == "create":
            if channel_id in self.lobbies:
                await interaction.response.send_message(
                    "Arena lobby already exists! / 本频道已有竞技场房间！", ephemeral=True)
                return

            lobby = {
                "leader": uid,
                "team_a": [uid],  # leader is in team A by default
                "team_b": [],
                "status": "lobby",
                "channel_id": channel_id,
                "started_at": datetime.datetime.now().isoformat(),
            }
            self.lobbies[channel_id] = lobby
            view = Arena3v3LobbyView(lobby)
            embed = view.build_embed()
            await interaction.response.send_message(embed=embed, view=view)
            view.message = await interaction.original_response()

        elif action.lower() == "join":
            lobby = self.lobbies.get(channel_id)
            if not lobby:
                await interaction.response.send_message(
                    "No active lobby! Use `/gmpt-arena-3v3 create` first / 没有活跃的房间！", ephemeral=True)
                return
            await interaction.response.send_message(
                "Click Join A or Join B in the lobby message / 在上方消息中点击加入蓝队或红队", ephemeral=True)

        elif action.lower() == "start":
            lobby = self.lobbies.get(channel_id)
            if not lobby:
                await interaction.response.send_message(
                    "No active lobby! / 没有活跃的房间！", ephemeral=True)
                return
            if uid != lobby["leader"]:
                await interaction.response.send_message(
                    "Only the lobby leader can start! / 只有房主可以开始！", ephemeral=True)
                return
            if len(lobby["team_a"]) < 3 or len(lobby["team_b"]) < 3:
                await interaction.response.send_message(
                    f"Need 3 players per team! A:{len(lobby['team_a'])}/3 B:{len(lobby['team_b'])}/3 / 两队各需3人！",
                    ephemeral=True)
                return

            lobby["status"] = "fighting"
            self.lobbies.pop(channel_id, None)

            # Get ranked cog reference if available
            ranked_cog = None
            try:
                ranked_cog = self.bot.get_cog("RankedCog")
            except Exception:
                pass

            await interaction.response.send_message("⚔️ 3v3 Arena starting! / 3v3竞技场开始！")
            await _run_3v3_battle(lobby, interaction.channel, ranked_cog)

        else:
            await interaction.response.send_message(
                "Usage: `/gmpt-arena-3v3 create|join|start`", ephemeral=True)

    @arena_3v3.autocomplete("action")
    async def arena_action_autocomplete(self, interaction: discord.Interaction, current: str):
        options = ["create", "join", "start"]
        return [
            app_commands.Choice(name=o, value=o)
            for o in options if current.lower() in o.lower()
        ]


async def setup(bot: commands.Bot):
    await bot.add_cog(Arena3v3Cog(bot))
    logger.info("MMORPG Arena 3v3 cog loaded")
