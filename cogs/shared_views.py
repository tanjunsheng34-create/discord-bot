"""
Shared Discord UI Views — imported by multiple cogs to avoid circular imports.
"""
import discord

logger = logging.getLogger(__name__)



class ConfirmView(discord.ui.View):
    """Two-button confirmation dialog (Confirm / Cancel).

    Usage:
        view = ConfirmView(timeout=60)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if view.value:
            ...  # user confirmed
    """

    def __init__(self, timeout=60):
        super().__init__(timeout=timeout)
        self.value = None  # True / False after user clicks

    @discord.ui.button(label="确认 / Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button):
        try:
            await interaction.response.defer(ephemeral=True)
            self.value = True
            for child in self.children:
                child.disabled = True
            await interaction.edit_original_response(view=self)
        except Exception as e:
            logger.error(f"confirm error: {e}")
        finally:
            self.stop()

    @discord.ui.button(label="取消 / Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button):
        try:
            await interaction.response.defer(ephemeral=True)
            self.value = False
            for child in self.children:
                child.disabled = True
            await interaction.edit_original_response(view=self)
        except Exception as e:
            logger.error(f"cancel error: {e}")
        finally:
            self.stop()
