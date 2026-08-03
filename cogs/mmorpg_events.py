"""
GMPT Bot — MMORPG 限时活动Boss / Event Boss System
在活动日自动生成活动Boss，掉落限定称号+装备
"""
import asyncio
import random
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
from config import EVENT_SCHEDULE, EVENT_CHANNEL_ID, EVENT_BOSS_SURVIVAL, DOUBLE_DROP_WEEKEND_CHANCE
import logging

logger = logging.getLogger(__name__)

# Event boss room storage
_event_rooms: dict[str, dict] = {}
_event_lock = asyncio.Lock()

# Event exclusive drops
EVENT_DROPS = {
    "newyear_dragon": [
        ("新年龙鳞", "weapon", "T3", {"ATK": 55, "CRIT": 0.08}, "🐉 Dragon Set"),
        ("年兽之角", "helmet", "T3", {"DEF": 25, "HP": 200}, "🐉 Dragon Set"),
        ("新年祝福", "title", "T3", {}, "新年 Dragon 首杀"),
    ],
    "halloween_pumpkin": [
        ("南瓜魔杖", "weapon", "T3", {"ATK": 50, "CRIT": 0.10}, "🎃 Halloween Set"),
        ("鬼影斗篷", "offhand", "T3", {"DEF": 20, "HP": 150}, "🎃 Halloween Set"),
        ("万圣之王", "title", "T3", {}, "万圣 Pumpkin King 首杀"),
    ],
    "christmas_ice": [
        ("冰霜之剑", "weapon", "T3", {"ATK": 52, "CRIT": 0.07}, "❄️ Frost Set"),
        ("圣诞铃铛", "accessory", "T3", {"HP": 300, "DEF": 15}, "❄️ Frost Set"),
        ("冰雪领主", "title", "T3", {}, "圣诞 Ice Lord 首杀"),
    ],
    "summer_beach": [
        ("沙滩之矛", "weapon", "T3", {"ATK": 48, "CRIT": 0.12}, "☀️ Storm Set"),
        ("贝壳护符", "accessory", "T3", {"HP": 250, "DEF": 20}, "☀️ Storm Set"),
        ("夏日霸主", "title", "T3", {}, "暑假 Beach Boss 首杀"),
    ],
}

WEEKEND_DOUBLE_DROP_EVENT = ("weekend_double", "周末双倍掉落", "幸运女神")


class EventBossCog(CogBase):
    """限时活动Boss系统 / Event Boss System"""

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self._event_task: asyncio.Task | None = None

    async def cog_load(self):
        # Check today's events and start the loop
        self._event_task = asyncio.create_task(self._event_loop())
        logger.info("[EventBoss] 活动Boss系统已启动 / Event boss system started")

    async def cog_unload(self):
        if self._event_task:
            self._event_task.cancel()
        async with _event_lock:
            _event_rooms.clear()
        logger.info("[EventBoss] 活动Boss系统已关闭 / Event boss system stopped")

    async def _event_loop(self):
        """Main event loop — checks every hour for event matches"""
        await self.bot.wait_until_ready()
        spawned_today: set[str] = set()

        while True:
            try:
                now = datetime.datetime.now()
                month = now.month
                day = now.day
                weekday = now.weekday()  # 0=Mon ... 6=Sun

                # Reset spawned_today at midnight
                if now.hour == 0 and now.minute < 5:
                    spawned_today.clear()

                # Check event schedule
                month_events = EVENT_SCHEDULE.get(month, {})
                event_today = month_events.get(day)

                if event_today:
                    event_key, event_name, boss_name = event_today
                    if event_key not in spawned_today:
                        await self._spawn_event_boss(event_key, event_name, boss_name)
                        spawned_today.add(event_key)

                # Weekend double drop check (Sat/Sun, random chance)
                if weekday in (5, 6) and random.random() < DOUBLE_DROP_WEEKEND_CHANCE:
                    wk_key = f"weekend_{now.strftime('%Y%m%d')}"
                    if wk_key not in spawned_today:
                        await self._spawn_event_boss(
                            "weekend_double", "周末双倍掉落 / Weekend Double Drop",
                            random.choice(["幸运女神", "财宝哥布林", "黄金史莱姆"])
                        )
                        spawned_today.add(wk_key)

            except Exception as e:
                logger.error(f"[EventBoss] 事件循环错误 / Event loop error: {e}")

            await asyncio.sleep(3600)  # Check every hour

    async def _spawn_event_boss(self, event_key: str, event_name: str, boss_name: str):
        """Spawn an event boss in the event channel"""
        try:
            channel = self.bot.get_channel(EVENT_CHANNEL_ID)
            if not channel:
                logger.warning(f"[EventBoss] 频道 {EVENT_CHANNEL_ID} 未找到 / Channel not found")
                return

            boss_id = f"event_{event_key}_{int(datetime.datetime.now().timestamp())}"
            boss_hp = random.randint(8000, 15000)

            embed = discord.Embed(
                title=f"🎉 限时活动 / Limited Event: {event_name}",
                description=(
                    f"**{boss_name}** 出现了！\n"
                    f"HP: `{boss_hp}` | 存活时间: `{EVENT_BOSS_SURVIVAL // 60} 分钟`\n\n"
                    f"击败可获得限定称号和装备 / Defeat to earn exclusive titles and gear!\n"
                    f"使用 `/gmpt-boss join {boss_id}` 参战 / Use to join"
                ),
                color=discord.Color.gold(),
            )
            embed.set_footer(text=f"活动Boss ID: {boss_id} | 限时活动奖励")

            msg = await channel.send(embed=embed)

            # Register room
            async with _event_lock:
                _event_rooms[boss_id] = {
                    "event_key": event_key,
                    "event_name": event_name,
                    "boss_name": boss_name,
                    "hp": boss_hp,
                    "max_hp": boss_hp,
                    "players": {},
                    "message_id": msg.id,
                    "channel_id": channel.id,
                    "spawned_at": datetime.datetime.now(),
                    "alive": True,
                }

            # Timeout: despawn after EVENT_BOSS_SURVIVAL seconds
            await asyncio.sleep(EVENT_BOSS_SURVIVAL)

            async with _event_lock:
                room = _event_rooms.get(boss_id)
                if room and room["alive"]:
                    if not room["players"]:
                        room["alive"] = False
                        try:
                            await msg.edit(
                                embed=discord.Embed(
                                    title=f"💨 {boss_name} 逃跑了 / Escaped!",
                                    description="无人挑战，活动Boss已消失 / No one challenged the boss.",
                                    color=discord.Color.dark_grey(),
                                )
                            )
                        except discord.NotFound:
                            pass
                    del _event_rooms[boss_id]

            logger.info(f"[EventBoss] 活动Boss {boss_name} ({event_key}) 已结束 / Despawned")

        except Exception as e:
            logger.error(f"[EventBoss] 生成活动Boss失败 / Spawn failed: {e}")

    def get_event_drops(self, event_key: str) -> list:
        """Return exclusive drops for an event"""
        return EVENT_DROPS.get(event_key, [])

    def is_weekend_double(self) -> bool:
        """Check if today is weekend double drop day"""
        now = datetime.datetime.now()
        return now.weekday() in (5, 6)


async def setup(bot: commands.Bot):
    await bot.add_cog(EventBossCog(bot))
