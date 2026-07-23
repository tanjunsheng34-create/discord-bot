"""
GMPT Bot — 通用分页组件

替换各 cog 中重复的分页 View 实现。
用法：PageView(pages: list[discord.Embed], timeout=120, ephemeral=True)
"""
import discord


class PageView(discord.ui.View):
    """通用 embed 分页 View，自动生成上一页/下一页按钮。

    Args:
        pages: discord.Embed 列表
        timeout: 超时秒数，None 表示永不过期
        ephemeral: 翻页时使用 ephemeral 回复
    """

    def __init__(self, pages: list, timeout: int = 120, ephemeral: bool = True):
        super().__init__(timeout=timeout if timeout else None)
        self.pages = pages
        self.current = 0
        self.total = len(pages)
        self.ephemeral = ephemeral
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = (self.current == 0)
        self.next_btn.disabled = (self.current >= self.total - 1)

    @discord.ui.button(label="⬅️ 上一页", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button):
        if self.current > 0:
            self.current -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="下一页 ➡️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button):
        if self.current < self.total - 1:
            self.current += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current], view=self)
