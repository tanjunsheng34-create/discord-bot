"""
Shared match_id autocomplete for Discord slash commands.

Usage:
    from cogs.match_autocomplete import match_id_autocomplete

    @app_commands.autocomplete(match_id=match_id_autocomplete)
"""
from discord import app_commands
import discord
from database import get_db



async def match_id_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[int]]:
    """Auto-complete match_id from non-finished tournaments."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, status FROM tournaments WHERE status != 'finished' ORDER BY id DESC LIMIT 25"
    )
    rows = cur.fetchall()
    conn.close()

    current_lower = current.lower()
    return [
        app_commands.Choice(
            name=f"{row['name']} (ID:{row['id']}) - {row['status']}",
            value=row["id"],
        )
        for row in rows
        if not current or current_lower in f"{row['name']} {row['id']}".lower()
    ]
