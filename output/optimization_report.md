---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 28d8423b56aed61a59a390221b167e51_fac9aad1870c11f18766525400f8a581
    ReservedCode1: jWIKrb84ioUY8/9FiJJQMTV5vd13m54BIP6fhF1YL3kPBOYyfP7TWmxL4lVSWIc3nV1FxO071FAji/ZwVpzz/JsvvpSlX1WoAYGnV+gUvIsdmOvrR/jkCZuH/+Hg8+ju808E2Pekrzz6VXPOyiplSBAvVkSGwF6H4q6tE8bevMWTAdpzUD2GKDXUVHU=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 28d8423b56aed61a59a390221b167e51_fac9aad1870c11f18766525400f8a581
    ReservedCode2: jWIKrb84ioUY8/9FiJJQMTV5vd13m54BIP6fhF1YL3kPBOYyfP7TWmxL4lVSWIc3nV1FxO071FAji/ZwVpzz/JsvvpSlX1WoAYGnV+gUvIsdmOvrR/jkCZuH/+Hg8+ju808E2Pekrzz6VXPOyiplSBAvVkSGwF6H4q6tE8bevMWTAdpzUD2GKDXUVHU=
---

# GMPT Discord Bot — 代码审计优化报告

> 审计日期：2026-07-24
> 项目路径：`C:\Users\tanju\AppData\Roaming\Tencent\Marvis\marvis_data\temp\discord-bot\`
> 审计范围：全部 30 个 `.py` 源文件

---

## 总览

| 级别 | 数量 | 说明 |
|---|---|---|
| P0 — 致命 | 9 | 影响稳定性/安全性，需立即修复 |
| P1 — 重要 | 14 | 显著影响代码质量/可维护性 |
| P2 — 锦上添花 | 11 | 改善体验/规范 |

---

## P0 — 致命（需立即修复）

### P0-1. 数据库连接泄漏（全项目通用）

**文件/行号**：全项目 — `cogs/dashboard.py`, `cogs/daily.py`, `cogs/economy.py`, `cogs/admin_backup.py`, `cogs/lol.py`, `cogs/queue.py`, `cogs/tournament.py`, `cogs/casino.py`, `cogs/trivia.py`, `cogs/guess_champion.py`, `cogs/predict.py`, `cogs/peiwans.py`, `cogs/games.py`, `cogs/voice_tracker.py`

**问题**：全项目普遍使用 `conn = get_db(); cur = conn.cursor()` 然后手动 `conn.close()`。如果在 `cur.execute()` 和 `conn.close()` 之间抛出异常（如 Discord API 错误、网络超时），数据库连接将永久泄漏。SQLite WAL 模式下的连接泄漏累积会导致"database is locked"错误，Bot 最终不可用。

**当前代码示例** (`cogs/casino.py:18-25`):
```python
conn = get_db(); cur = conn.cursor()
cur.execute(
    "INSERT INTO users (discord_id, username) VALUES (?, 'unknown') ON CONFLICT(discord_id) DO NOTHING",
    (uid,),
)
cur.execute("SELECT score FROM users WHERE discord_id=?", (uid,))
row = cur.fetchone()
conn.close()
```

**改进方案**：引入上下文管理器或在 `database.py` 中提供 `get_db_context()`:
```python
# database.py 新增
from contextlib import contextmanager

@contextmanager
def get_db_ctx():
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()

# 调用方
with get_db_ctx() as conn:
    cur = conn.cursor()
    cur.execute("...")
    row = cur.fetchone()
```

**影响范围**：全项目 100+ 处手动 `conn.close()` 调用，每次都可能泄漏。

---

### P0-2. 同步阻塞在 Discord 事件循环中

**文件/行号**：`cogs/daily.py`，`_commit_minutes` 函数内

**问题**：在 Discord asyncio 事件循环中使用 `time_mod.sleep()` 进行同步阻塞。这会冻结 Bot 的整个事件循环，导致所有其他命令/事件无法响应，直到 sleep 结束。

**当前代码示例** (`cogs/daily.py` ~行 350-400):
```python
time_mod.sleep(seconds)  # 同步阻塞！
```

**改进方案**：使用 `asyncio.sleep()`:
```python
await asyncio.sleep(seconds)
```

---

### P0-3. 时区重复定义

**文件/行号**：`cogs/daily.py` 模块级

**问题**：`MYT` 和 `UTC8` 两个变量定义为完全相同的时区 `timezone(timedelta(hours=8))`，导致混淆且 code review 时容易误用。其他模块（`voice_tracker.py`）也独立定义了 `UTC8`。

**当前代码示例** (`cogs/daily.py`):
```python
MYT = timezone(timedelta(hours=8))
UTC8 = timezone(timedelta(hours=8))
```

**改进方案**：在 `config.py` 或 `utils/` 中统一定义一个时区常量，全项目引用:
```python
# config.py
from datetime import timezone, timedelta
TZ_UTC8 = timezone(timedelta(hours=8))
```

---

### P0-4. 双向循环依赖 — dashboard.py ↔ tournament.py

**文件/行号**：
- `cogs/dashboard.py`：`from cogs.tournament import TIER_SEED, ConfirmView, ...` (12 个符号)
- `cogs/tournament.py`：`from cogs.shared_views import ConfirmView`

**问题**：`dashboard.py` 从 `tournament.py` 导入 12 个符号，而 `tournament.py` 也可能间接引用 dashboard。当 Python 加载模块时可能产生部分初始化对象，导致 `AttributeError`。目前因 `shared_views.py` 作为中介暂未触发，但架构脆弱，调整导入顺序即可能崩溃。

**改进方案**：
1. 所有共享的常量（`TIER_SEED`, `TIER_SCORE`）移入 `config.py` 或新建 `utils/constants.py`
2. 所有共享的 View 类移入 `shared_views.py`
3. 两个 Cog 之间只保留"接口级别"的依赖（事件/callback）

---

### P0-5. `database.py` 迁移函数中滥用 try/except

**文件/行号**：`database.py`，`_run_migrations()` 函数内 ~10+ 处

**问题**：每个 ALTER TABLE 都用单独的 try/except 包裹，静默吞掉所有异常（包括 `OperationalError` 之外的错误）。如果某次迁移因磁盘满、权限问题失败，Bot 将静默继续运行但 schema 不一致。

**当前代码示例**:
```python
try:
    cur.execute("ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0")
except:
    pass
```

**改进方案**：至少检查具体异常类型：
```python
try:
    cur.execute("ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0")
except sqlite3.OperationalError:
    # Column already exists — expected
    pass
```

---

### P0-6. `admin_backup.py` 恢复时无事务保证

**文件/行号**：`cogs/admin_backup.py`，`restore_backup` 函数

**问题**：恢复时逐表 `DELETE` + `INSERT`，但不同表之间没有事务包裹。如果在恢复第 5 张表时崩溃，前 4 张表已被清空/替换，后 7 张表仍是旧数据，导致数据库状态不一致。

**改进方案**：整次恢复用 `conn.execute("BEGIN")` / `conn.commit()` 包裹，失败时回滚。

---

### P0-7. 语音追踪内存泄漏风险

**文件/行号**：`cogs/voice_tracker.py:45`

**问题**：`self._join_times = {}` 是内存字典。如果用户加入语音但 Bot 在用户离开前崩溃/重启，该条目永久丢失；更严重的是如果非正常断开（网络抖动导致 Discord 不触发 `on_voice_state_update` 离开事件），键会永远留在内存中。

**改进方案**：增加定期清理机制或 TTL：
```python
# 每 10 分钟清理超过 24 小时的僵尸条目
async def _cleanup_stale_joins(self):
    cutoff = datetime.now() - timedelta(hours=24)
    stale = [uid for uid, t in self._join_times.items() if t < cutoff]
    for uid in stale:
        self._join_times.pop(uid, None)
```

---

### P0-8. 硬编码 Discord 频道/角色 ID（全项目）

**文件/行号**：
- `config.py:14-24`：10 个频道 ID + 2 个角色 ID
- `cogs/daily.py`：`daily_reminder_loop` 中硬编码频道 `1528241061007327354`
- `cogs/dashboard.py`：硬编码 VC ID `1438050912814895186`, `1438051019605872722` 等 4 个；频道 ID `1437626921394372658`
- `cogs/queue.py`：`_create_match` 中 `str(self.bot.user.id)` 用 Bot ID 作为创建者
- `database.py`：建表默认值中硬编码频道 ID

**问题**：所有频道/角色 ID 分散硬编码在源码中，切换服务器需修改代码，极易遗漏导致功能静默失效。

**改进方案**：全部移入 `config.py` 并统一命名规范：
```python
# config.py
DAILY_REMINDER_CHANNEL_ID = os.getenv("DAILY_REMINDER_CHANNEL_ID", "1528241061007327354")
TEAM_A_VC_ID = os.getenv("TEAM_A_VC_ID", "1438050912814895186")
# ...
```

---

### P0-9. `_run_migrations` 中 `_get_env_int` 死代码

**文件/行号**：`config.py:58-65`，`database.py:_run_migrations`

**问题**：`_get_env_int` 辅助函数已定义但全项目无任何调用。同时 `_run_migrations` 中存在大量未使用的默认值硬编码频道 ID。

**改进方案**：删除 `_get_env_int`，或将其用于频道 ID 的 env 加载。

---

## P1 — 重要

### P1-1. 重复经济函数定义（5 个模块各自实现）

**文件/行号**：
- `cogs/economy.py`：`get_balance`, `add_coins`
- `cogs/casino.py`：`_get_balance`, `_add_coins`
- `cogs/trivia.py`：`_add_coins`
- `cogs/guess_champion.py`：`_add_coins`
- `cogs/predict.py`：`_get_balance`, `_add_coins`
- `cogs/games.py`：从 economy 导入 `get_balance`, `add_coins`

**问题**：同一逻辑（查询余额、增减金币、写 transactions 表）在 6 个模块中以不同函数名重复实现，修改逻辑需同步 6 处，极易产生不一致。

**当前代码示例** (5 处几乎相同的实现):
```python
def _add_coins(uid: str, amount: int, reason: str):
    conn = get_db(); cur = conn.cursor()
    cur.execute("INSERT INTO users ... ON CONFLICT...")
    cur.execute("UPDATE users SET score = score + ?...")
    cur.execute("INSERT INTO transactions ...")
    conn.commit(); conn.close()
```

**改进方案**：在 `cogs/economy.py` 中统一提供，其他模块全部导入：
```python
from cogs.economy import get_balance, add_coins
```
并确保所有模块使用同一套函数签名。

---

### P1-2. 重复每日限制函数定义（3 个模块各自实现）

**文件/行号**：
- `cogs/casino.py`：`_check_daily_limit`
- `cogs/trivia.py`：`_check_daily_limit`
- `cogs/guess_champion.py`：`_check_daily_limit`

**问题**：三个模块有字符级相同的 `_check_daily_limit` 函数 (~25 行)，完全重复。

**改进方案**：移入 `utils/game_utils.py` 或 `cogs/economy.py` 统一提供。

---

### P1-3. 字体查找逻辑重复且硬编码

**文件/行号**：
- `cogs/actions.py`：`_find_font` 函数
- `cogs/economy.py`：`_find_fonts` / `_get_font` 函数
- `cogs/meme.py`：`_get_font` 函数 + `FONT_PATHS` 常量
- `cogs/lol.py`：直接用 `arial.ttf` 硬编码

**问题**：字体查找逻辑在 4 个文件中各自实现，硬编码的字体路径互不一致（有的包含 `/usr/share/fonts`，有的只有 Windows），维护困难。

**改进方案**：创建 `utils/fonts.py`，统一字体查找+缓存逻辑：
```python
# utils/fonts.py
FONT_CANDIDATES = {
    "sans": ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf", ...],
    "bold": ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/segoeuib.ttf", ...],
    "impact": ["C:/Windows/Fonts/impact.ttf", ...],
}

def get_font(size: int, style: str = "sans") -> ImageFont.FreeTypeFont:
    ...
```

---

### P1-4. `CogBase` 未被一致继承

**文件/行号**：
- 已继承 `CogBase`：`actions.py`, `admin_backup.py`, `announce.py`, `daily.py`, `economy.py`, `games.py`, `help.py`, `lol.py`, `peiwans.py`, `queue.py`, `voice_tracker.py`
- **未继承 `CogBase`**：`casino.py` (`commands.Cog`), `trivia.py` (`commands.Cog`), `guess_champion.py` (继承了 CogBase), `predict.py` (`commands.Cog`), `meme.py` (需确认), `tournament.py` (需确认)

**问题**：`CogBase` 提供统一的 `cog_command_error` 错误处理，但 `casino.py` 和 `trivia.py` 各自手动实现 `@command.error` 处理，`predict.py` 完全没有错误处理。

**改进方案**：所有 Cog 统一继承 `CogBase`，移除各模块的手动 error handler。

---

### P1-5. `dashboard.py` 单体文件过大（8092 行）

**文件/行号**：`cogs/dashboard.py` (8092 行)

**问题**：单个文件承担了创建比赛、分队、结算、报名管理、队长系统、语音拉人、重分队、轮盘模式等十几个职责。任何修改都需在 8000+ 行中定位，测试困难，合并冲突风险极高。

**改进方案**：拆分：
- `cogs/match_create.py` — 比赛创建 + 报名
- `cogs/match_team.py` — 分队/重分队/队长
- `cogs/match_settle.py` — 结算
- `cogs/match_voice.py` — 语音拉人
- `cogs/match_views.py` — 共享 View/Modal 组件
- 保留 `dashboard.py` 作为协调层

---

### P1-6. `daily.py` 提醒循环每分钟检查 + 硬编码频道

**文件/行号**：`cogs/daily.py`，`daily_reminder_loop`

**问题**：`tasks.loop(minutes=1)` 每分钟都执行 DB 查询检查所有用户是否需要提醒。随着用户增长，这会造成大量无意义的 DB 查询。且频道 ID 硬编码。

**改进方案**：改为在用户签到时计算下次提醒时间，存入内存 `sortedcontainers` 或简单的下次提醒时间戳字典，循环体内仅检查到期用户。

---

### P1-7. `admin_backup.py` 11 张表恢复代码高度重复

**文件/行号**：`cogs/admin_backup.py`，每张表 ~20 行几乎相同的代码

**问题**：11 张表各自一份 `DELETE` + `INSERT` + `3 次重试锁` 的重复代码，总计 ~200 行。

**当前代码示例** (每张表重复):
```python
for attempt in range(3):
    try:
        cur.execute("DELETE FROM achievements")
        for row in data.get("achievements", []):
            cur.execute("INSERT INTO achievements (...) VALUES (...)", ...)
        break
    except sqlite3.OperationalError:
        if attempt < 2:
            time.sleep(0.3)
        else:
            raise
```

**改进方案**：提取通用函数：
```python
def _restore_table(cur, table_name, data, columns):
    for attempt in range(3):
        try:
            cur.execute(f"DELETE FROM {table_name}")
            placeholders = ",".join("?" * len(columns))
            cur.executemany(
                f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({placeholders})",
                [tuple(row[col] for col in columns) for row in data]
            )
            break
        except sqlite3.OperationalError:
            if attempt >= 2: raise
            time.sleep(0.3)
```

---

### P1-8. `main.py` 事件回调中同步 DB 操作阻塞

**文件/行号**：`main.py`，`on_member_join`, `on_message`, `on_reaction_add` 事件处理器

**问题**：这些事件处理器直接调用 DB（通过 get_db），虽然是异步函数但 DB 操作实质上是同步的（SQLite）。在高频场景下（如大量 reaction 事件），可能堆积阻塞事件循环。

**改进方案**：使用 `asyncio.to_thread()` 将 DB 操作卸载到线程池，或使用 `aiohttp` 风格的线程执行器。

---

### P1-9. 缺少命令 cooldown

**文件/行号**：多个文件

**问题**：只有少数命令有 cooldown（trivia、queue status、peiwans list），大量经济/游戏命令（slots、coinflip、shop、buy）无任何频率限制。恶意用户可以快速调用数百次造成经济系统崩溃。

**改进方案**：所有涉及金币增减的命令添加 cooldown：
```python
@app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
```

---

### P1-10. `daily.py` set_cmd 管理员权限检查不充分

**文件/行号**：`cogs/daily.py`，set_cmd 函数

**问题**：手动检查 `interaction.user.guild_permissions.administrator` 而非使用 `@app_commands.default_permissions(administrator=True)` 装饰器。手动检查无法阻止非管理员在 Discord UI 中看到该命令。

**改进方案**：添加装饰器：
```python
@app_commands.default_permissions(administrator=True)
async def set_cmd(self, interaction, ...):
```

---

### P1-11. `main.py` ensure_deps 自动安装依赖

**文件/行号**：`main.py`，`ensure_deps` 函数

**问题**：Bot 启动时自动 `pip install` 缺失的包。这在生产环境中有安全风险（可能安装了恶意包或被篡改的包）。且 pip install 可能因网络问题失败导致 Bot 无法启动。

**改进方案**：改为启动时仅检查并打印缺失包列表，由运维手动安装；或在 `requirements.txt` 中锁定版本。

---

### P1-12. `_GRADIENT_PRESETS` 和 `ACTION_CONFIG` 模块级大常量

**文件/行号**：`cogs/actions.py`

**问题**：`_GRADIENT_PRESETS` 中每个预设包含 256 行的 RGB 渐变值，加上 `ACTION_CONFIG` 等，~100 行纯常量数据混在业务逻辑文件中。

**改进方案**：移入单独的 `cogs/actions_data.py` 或 `data/actions.json`。

---

### P1-13. `economy.py` 中 `ITEM_DISPLAY` 和 `DEFAULT_SHOP` 数据与逻辑混合

**文件/行号**：`cogs/economy.py`，~300 行常量定义

**问题**：~40 个商店物品定义、~30 条 ITEM_DISPLAY 映射、30 条 ACHIEVEMENTS 定义全部硬编码在 Cog 文件中。修改物品价格/描述需改源码。

**改进方案**：移入数据库 `shop_items` 表或至少分离到 `data/shop.json`。

---

### P1-14. `lol.py` 自动创建频道无权限限制

**文件/行号**：`cogs/lol.py`，`on_message` 事件中的 `_create_temp_channel` 逻辑

**问题**：任何在监控频道中发消息包含关键词的用户，Bot 都会自动创建临时频道并 `@` 身份组。无 cooldown，无黑名单，无权限控制，可能被滥用刷屏。

**改进方案**：添加每用户 cooldown（如 5 分钟只能触发一次）、管理员可配置的黑名单。

---

## P2 — 锦上添花

### P2-1. Python 3.10+ 类型注解未统一使用新语法

**文件/行号**：全项目多处

**问题**：部分代码使用 `Optional[str]`，部分使用 `str | None`；部分使用 `List[dict]`，部分使用 `list[dict]`。风格不一致。

**改进方案**：统一使用 Python 3.10+ 的 `X | None` 语法和内置泛型。

---

### P2-2. `config.py` 缺少 `.env.example`

**问题**：项目无 `.env.example` 文件，新开发者不清楚需要配置哪些环境变量。

**改进方案**：创建 `.env.example`：
```ini
DISCORD_BOT_TOKEN=
RIOT_API_KEY=
WHISPER_CHANNEL_ID=
SHOP_LOG_CHANNEL_ID=
ACHIEVEMENTS_CHANNEL_ID=
# ... 所有配置项
```

---

### P2-3. 缺少日志级别控制

**文件/行号**：`utils/logger.py`，`main.py`

**问题**：所有日志写死 `logging.INFO` 级别，无环境变量控制。调试时需要修改代码。

**改进方案**：
```python
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(level=getattr(logging, LOG_LEVEL))
```

---

### P2-4. `shared_views.py` 中 `ConfirmView` 缺少 `on_timeout`

**文件/行号**：`cogs/shared_views.py:8-51`

**问题**：`ConfirmView` 有 `timeout` 参数但无 `on_timeout` 方法。超时后按钮仍可点击但 `view.wait()` 返回 `False`，调用方如果未检查 `value is None` 可能误判。

**改进方案**：添加 `on_timeout` 禁用按钮并设置 `self.value = None`。

---

### P2-5. `trivia.py` 题目数据硬编码

**文件/行号**：`cogs/trivia.py:61-565`（~500 行纯数据）

**问题**：55 道题目硬编码在源码中，占用 ~500 行且不可热更新。

**改进方案**：移入 `data/trivia.json`，启动时加载。

---

### P2-6. `guess_champion.py` 英雄数据硬编码

**文件/行号**：`cogs/guess_champion.py`（69 个英雄，~500+ 行数据）

**问题**：69 个英雄的完整数据（name/emoji/title/quote/region/aliases/skills）硬编码在源码中。

**改进方案**：移入 `data/champions.json`。

---

### P2-7. `help.py` 命令列表手动维护

**文件/行号**：`cogs/help.py`

**问题**：help 命令的所有子命令列表手动硬编码，新增命令时常忘记同步更新。

**改进方案**：通过 `self.bot.tree.get_commands()` 动态生成命令列表。

---

### P2-8. `meme.py` 和 `actions.py` 使用 PIL 但未统一异常处理

**文件/行号**：`cogs/meme.py`, `cogs/actions.py`, `cogs/economy.py`

**问题**：三处都有 `try: from PIL import ... except: PIL_AVAILABLE=False`，且各自处理 PIL 缺失的方式不同（有的静默降级，有的打印 warning）。

**改进方案**：统一到 `utils/pil_utils.py`。

---

### P2-9. 缺少完整的 Docstring 覆盖率

**问题**：部分函数（如 `generate_ach_image`、`_generate_battle_image`、`swiss_pairing`）有 docstring，但大量内部辅助函数、View 类方法完全没有文档。

**改进方案**：逐步为公开 API 补充 docstring，优先覆盖 Cog 中的 command 函数。

---

### P2-10. 错误消息模版化不足

**问题**：错误消息多为直接字符串（如"金币不足 / Insufficient coins. 余额: 🪙 {balance}"），散布在各文件中。后续若需统一调整措辞或添加多语言，修改成本极高。

**改进方案**：集中到 `utils/messages.py`：
```python
INSUFFICIENT_COINS = "金币不足 / Insufficient coins. 余额: 🪙 {balance}"
```

---

### P2-11. `database.py` 缺少连接池

**问题**：每次操作创建新连接，虽然 SQLite 开销不大，但在 WAL 模式下频繁创建/关闭连接会产生不必要的 fsync 调用。

**改进方案**：使用 `sqlite3.connect` 的 `check_same_thread=False` + 单例连接 + 线程锁，或使用 `aiosqlite`。

---

## 附录：文件规模统计

| 文件 | 行数 | 评级 |
|---|---|---|
| `cogs/dashboard.py` | 8092 | 🔴 需拆分 |
| `cogs/economy.py` | 2913+ | 🟡 偏大 |
| `cogs/tournament.py` | 2445 | 🟡 偏大 |
| `cogs/lol.py` | 1580 | 🟢 可接受 |
| `cogs/daily.py` | 611 | 🟢 可接受 |
| `database.py` | 749 | 🟡 需重构 |
| `cogs/peiwans.py` | 806 | 🟢 可接受 |
| `cogs/trivia.py` | 765 | 🟢 可接受 |
| `cogs/guess_champion.py` | 723 | 🟡 数据占比过高 |
| `main.py` | 618 | 🟢 可接受 |
| `cogs/games.py` | 565 | 🟢 可接受 |
| `cogs/voice_tracker.py` | 513 | 🟢 可接受 |
| `cogs/meme.py` | 450 | 🟢 可接受 |
| `cogs/predict.py` | 376 | 🟢 可接受 |
| `cogs/admin_backup.py` | 260 | 🟢 可接受 |
| `cogs/queue.py` | 244 | 🟢 可接受 |
| `cogs/actions.py` | 226 | 🟢 可接受 |
| `cogs/casino.py` | 220 | 🟢 可接受 |
| `cogs/help.py` | 124 | 🟢 良好 |
| 其余 | <100 | 🟢 良好 |

---

*报告结束 — 共 9 项 P0、14 项 P1、11 项 P2 建议*
*（内容由AI生成，仅供参考）*
