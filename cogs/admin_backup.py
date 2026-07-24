"""
Backup & Restore — Database backup/restore
"""
import json
import io
import asyncio
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db, get_db_ctx
from utils.logger import log_error
from utils.cog_base import CogBase


class AdminBackup(CogBase):
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

        with get_db_ctx() as conn:
            cur = conn.cursor()

            tables = [
                "users",
                "voice_tracker",
                "daily_checkin",
                "giveaway",
                "giveaway_entries",
                "user_inventory",
                "giveaways",
                "giveaway_tickets",
                "tournaments",
                "match_signups",
                "matches",
            ]

            data = {}
            for table in tables:
                try:
                    cur.execute(f"SELECT * FROM {table}")
                    rows = [dict(row) for row in cur.fetchall()]
                    data[table] = rows
                except Exception as e:
                    log_error("admin_backup", f"backup table {table}", e)
                    data[table] = []

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
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
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

        with get_db_ctx() as conn:
            cur = conn.cursor()
            conn.execute("BEGIN")
            try:

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

                # Restore giveaways (economy.py)
                if "giveaways" in data and data["giveaways"]:
                    cur.execute("DELETE FROM giveaways")
                    for g in data["giveaways"]:
                        cur.execute(
                            "INSERT INTO giveaways "
                            "(id, channel_id, prize, created_by, drawn, winner_id, created_at, draw_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (g.get("id"), g.get("channel_id"), g.get("prize"), g.get("created_by"),
                             g.get("drawn", 0), g.get("winner_id"), g.get("created_at"), g.get("draw_at")),
                        )
                    restored["giveaways"] = len(data["giveaways"])

                # Restore giveaway_tickets
                if "giveaway_tickets" in data and data["giveaway_tickets"]:
                    cur.execute("DELETE FROM giveaway_tickets")
                    for t in data["giveaway_tickets"]:
                        cur.execute(
                            "INSERT INTO giveaway_tickets (discord_id, tickets) "
                            "VALUES (?, ?)",
                            (t.get("discord_id"), t.get("tickets", 0)),
                        )
                    restored["giveaway_tickets"] = len(data["giveaway_tickets"])

                # Restore tournaments
                if "tournaments" in data and data["tournaments"]:
                    cur.execute("DELETE FROM tournaments")
                    for t in data["tournaments"]:
                        cur.execute(
                            "INSERT INTO tournaments "
                            "(id, name, max_teams, team_size, status, created_by, created_at, "
                            "format, max_players, rounds, tier_restriction, role_pick) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (t.get("id"), t.get("name"), t.get("max_teams"), t.get("team_size"),
                             t.get("status", "open"), t.get("created_by"), t.get("created_at"),
                             t.get("format", "swiss"), t.get("max_players", 32), t.get("rounds", 3),
                             t.get("tier_restriction"), t.get("role_pick", 0)),
                        )
                    restored["tournaments"] = len(data["tournaments"])

                # Restore match_signups
                if "match_signups" in data and data["match_signups"]:
                    cur.execute("DELETE FROM match_signups")
                    for s in data["match_signups"]:
                        cur.execute(
                            "INSERT INTO match_signups (id, match_id, discord_id, team) "
                            "VALUES (?, ?, ?, ?)",
                            (s.get("id"), s.get("match_id"), s.get("discord_id"), s.get("team")),
                        )
                    restored["match_signups"] = len(data["match_signups"])

                # Restore matches
                if "matches" in data and data["matches"]:
                    cur.execute("DELETE FROM matches")
                    for m in data["matches"]:
                        cur.execute(
                            "INSERT INTO matches "
                            "(id, name, status, created_by, channel_id, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (m.get("id"), m.get("name"), m.get("status", "pending"),
                             m.get("created_by"), m.get("channel_id"), m.get("created_at")),
                        )
                    restored["matches"] = len(data["matches"])

            except Exception:
                conn.rollback()
                raise
            # Commit with retry for database lock
            for attempt in range(3):
                try:
                    conn.commit()
                    break
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower() and attempt < 2:
                        await asyncio.sleep(0.3 * (attempt + 1))
                        continue
                    raise

        summary = ", ".join(f"{k}: {v}" for k, v in restored.items())
        await interaction.edit_original_response(
            content=f"Restored: {summary}"
        )


async def setup(bot):
    await bot.add_cog(AdminBackup(bot))
