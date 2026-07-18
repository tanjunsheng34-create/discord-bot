"""通用工具函数。"""

import logging

logger = logging.getLogger(__name__)


def resolve_name(guild, discord_id: str) -> str:
    """根据 discord_id 获取用户显示名称，获取失败则返回 discord_id。"""
    try:
        member = guild.get_member(int(discord_id))
        return member.display_name if member else str(discord_id)
    except (ValueError, AttributeError):
        return str(discord_id)
