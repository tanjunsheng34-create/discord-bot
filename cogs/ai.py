"""
GMPT Bot — AI 问答
支持 OpenAI 兼容 API（DeepSeek / OpenAI / 本地模型等）
"""
import os
import discord
from discord import app_commands
from discord.ext import commands
from openai import AsyncOpenAI

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "deepseek-chat")

SYSTEM_PROMPT = """你是一个在 Discord 里的 LOL 游戏助手 GMPT Bot。
回答要简洁、有用、中文优先。涉及游戏攻略、英雄、装备、版本更新时尽量给出准确信息。
如果问题与 LOL 无关，也可以正常回答，但要简短。"""


class AI(commands.Cog):
    """AI 问答"""

    def __init__(self, bot):
        self.bot = bot
        self.client = None

    async def cog_load(self):
        if OPENAI_KEY:
            self.client = AsyncOpenAI(api_key=OPENAI_KEY, base_url=OPENAI_BASE)

    # ============ AI 问答 ============
    @app_commands.command(
        name="gmpt-ask",
        description="Ask AI anything / 问 AI 任何问题",
    )
    @app_commands.describe(question="Your question / 你的问题")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()

        if not self.client:
            return await interaction.followup.send(
                "AI 功能未配置。请在 Railway 环境变量中设置：\n"
                "`OPENAI_API_KEY` — DeepSeek 或 OpenAI 的 API Key\n"
                "`OPENAI_BASE_URL` — 可选，默认 https://api.deepseek.com\n"
                "`OPENAI_MODEL` — 可选，默认 deepseek-chat"
            )

        try:
            resp = await self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                ],
                max_tokens=1000,
                temperature=0.7,
            )
            answer = resp.choices[0].message.content

            # Discord 单条消息限 2000 字符，长回答拆开发送
            if len(answer) <= 2000:
                await interaction.followup.send(answer)
            else:
                chunks = [answer[i:i+2000] for i in range(0, len(answer), 2000)]
                await interaction.followup.send(chunks[0])
                for chunk in chunks[1:]:
                    await interaction.followup.send(chunk)

        except Exception as e:
            await interaction.followup.send(f"AI 调用失败：{e}")


async def setup(bot):
    await bot.add_cog(AI(bot))
