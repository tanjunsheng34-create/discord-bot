"""
Backup & Restore — Database backup/restore for Railway persistence
"""
import json
import io
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db


class AdminBackup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="gmpt-backup", description="Export all data as JSON backup (admin only)")
    async def backup_cmd(self, interaction: discord.Interaction):
        """Export all user/voice/giveaway data as a JSON file."""
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Admin only.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        conn = get_db()
        cur = conn.cursor()

        tables = [
            "users",
            "voice_tracker",
            "daily_checkin",
            "giveaway",
            "giveaway_entries",
            "user_inventory",
        ]

        data = {}
        for table in tables:
            try:
                cur.execute(f"SELECT * FROM {table}")
                rows = [dict(row) for row in cur.fetchall()]
                data[table] = rows
            except Exception:
                data[table] = []

        conn.close()

        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        file = discord.File(
            io.BytesIO(json_str.encode("utf-8")),
            filename="gmpt_backup.json",
        )

        lines = [f"- {t}: {len(data[t])} records" for t in tables]
        summary = "\n".join(lines)

        await interaction.edit_original_response(
            content=f"Backup complete:\n{summary}",
            attachments=[file],
        )

    @app_commands.command(name="gmpt-restore", description="Restore data from JSON backup file (admin only)")
    @app_commands.describe(file="The gmpt_backup.json file to restore from")
    async def restore_cmd(self, interaction: discord.Interaction, file: discord.Attachment):
        """Restore data from a gmpt_backup.json file attachment."""
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Admin only.", ephemeral=True
            )

        if not file.filename.endswith(".json"):
            return await interaction.response.send_message(
                "Please attach a `.json` backup file.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        try:
            content = await file.read()
            data = json.loads(content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return await interaction.edit_original_response(
                content=f"Invalid JSON file: {e}"
            )

        conn = get_db()
        cur = conn.cursor()

        restored = {}

        # Restore users
        if "users" in data and data["users"]:
            cur.execute("DELETE FROM users")
            for u in data["users"]:
                cur.execute(
                    "INSERT INTO users (discord_id, username, score, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (u.get("discord_id"), u.get("username", ""), u.get("score", 500),
                     u.get("created_at", "")),
                )
            restored["users"] = len(data["users"])

        # Restore voice_tracker
        if "voice_tracker" in data and data["voice_tracker"]:
            cur.execute("DELETE FROM voice_tracker")
            for v in data["voice_tracker"]:
                cur.execute(
                    "INSERT INTO voice_tracker "
                    "(user_id, total_seconds, login_days, total_joins, last_join_date, last_join_time) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (v.get("user_id"), v.get("total_seconds", 0), v.get("login_days", 0),
                     v.get("total_joins", 0), v.get("last_join_date"), v.get("last_join_time")),
                )
            restored["voice_tracker"] = len(data["voice_tracker"])

        # Restore daily_checkin
        if "daily_checkin" in data and data["daily_checkin"]:
            cur.execute("DELETE FROM daily_checkin")
            for c in data["daily_checkin"]:
                cur.execute(
                    "INSERT INTO daily_checkin (discord_id, last_date, streak) "
                    "VALUES (?, ?, ?)",
                    (c.get("discord_id"), c.get("last_date", ""), c.get("streak", 0)),
                )
            restored["daily_checkin"] = len(data["daily_checkin"])

        # Restore giveaway
        if "giveaway" in data and data["giveaway"]:
            cur.execute("DELETE FROM giveaway")
            for g in data["giveaway"]:
                cur.execute(
                    "INSERT INTO giveaway "
                    "(id, guild_id, channel_id, message_id, prize, duration_minutes, "
                    "winner_count, created_by, ends_at, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (g.get("id"), g.get("guild_id"), g.get("channel_id"), g.get("message_id"),
                     g.get("prize"), g.get("duration_minutes"), g.get("winner_count"),
                     g.get("created_by"), g.get("ends_at"), g.get("status", "active")),
                )
            restored["giveaway"] = len(data["giveaway"])

        # Restore giveaway_entries
        if "giveaway_entries" in data and data["giveaway_entries"]:
            cur.execute("DELETE FROM giveaway_entries")
            for e in data["giveaway_entries"]:
                cur.execute(
                    "INSERT INTO giveaway_entries (id, giveaway_id, user_id) "
                    "VALUES (?, ?, ?)",
                    (e.get("id"), e.get("giveaway_id"), e.get("user_id")),
                )
            restored["giveaway_entries"] = len(data["giveaway_entries"])

        # Restore user_inventory
        if "user_inventory" in data and data["user_inventory"]:
            cur.execute("DELETE FROM user_inventory")
            for inv in data["user_inventory"]:
                cur.execute(
                    "INSERT INTO user_inventory (user_id, item_id, quantity) "
                    "VALUES (?, ?, ?)",
                    (inv.get("user_id"), inv.get("item_id"), inv.get("quantity", 1)),
                )
            restored["user_inventory"] = len(data["user_inventory"])

        conn.commit()
        conn.close()

        summary = ", ".join(f"{k}: {v}" for k, v in restored.items())
        await interaction.edit_original_response(
            content=f"Restored: {summary}"
        )


async def setup(bot):
    await bot.add_cog(AdminBackup(bot))
