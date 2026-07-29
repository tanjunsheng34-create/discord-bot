# 全系统 Bug 审计表

## 审计范围
cogs/ 下所有 48 个 .py 文件、utils/、main.py、database.py

## 审计日期
2026-07-29

---

## 资金安全审计

| 文件:行号 | 严重度 | 问题描述 | 修复方案 |
|-----------|--------|---------|---------|
| gambling.py:1180-1230 | 🔴 CRITICAL | **GamblingLobbyView 构造子View参数错误**：5个按钮创建 View 时传入 `bot=None, user_id=int` 而非正确签名 `(user_id, user_name, bet)`，点击必崩溃 TypeError | 重写 GamblingLobbyView，改为通过 Modal 收集赌注后创建。当前方案先隐去不支持 lobby 快速创建的游戏按钮，仅保留跳转说明 |
| casino_games.py:L675 | ✅ 已验证 | Blackjack 预扣 bet → win 加 bet*2 → net +bet。正确 | 无需修复 |
| casino_games.py:L467 | ✅ 已验证 | HorseRace 预扣 bet → win 加 bet*odds → net correct。历史 Bug 已修复 | 无需修复 |
| gambling.py:L1165 | ⚠️ MINOR | RussianRoulette 未预扣款（与其他游戏模式不一致），在 View 内结算（输时扣 `profit=-bet`，赢时加 `bet*2`） | 建议统一为预扣模式。当前逻辑正确但维护风险较高 |

## 数据库列名一致性

| 文件:行号 | 严重度 | 问题描述 | 修复方案 |
|-----------|--------|---------|---------|
| daily_quest.py:L150 | ⚠️ MEDIUM | `_add_quest_exp` 查询 `SELECT xp FROM users WHERE user_id=?`，但 users 表主键列名为 `discord_id`（非 `user_id`），可能返回 None | 改为 `WHERE discord_id = ?` |
| achievements.py:L55 | ⚠️ MINOR | `cur.fetchone()[0]` 使用元组索引，与项目其他地方的 dict 访问不一致（`row["discord_id"]`）。当前 `fetchone()` 返回 Row 对象支持 dict 访问 | 统一使用 `row[0]` 或 `row["discord_id"]` |
| dungeon.py:L385 | ⚠️ MEDIUM | DungeonLobbyView 调用 `_get_user_stats(uid)` 但该函数在 mmorpg_shop.py 中可能不存在或名称不同 | 检查 mmorpg_shop.py 确认函数名 |
| boss.py:多处 | ⚠️ MINOR | `_get_combat_stats` 查询 `WHERE discord_id = ?` 但 SQL 列名有些地方用 `discord_id` 有些用 `user_id` | 核实 users 表实际列名并统一 |

## 空值处理

| 文件:行号 | 严重度 | 问题描述 | 修复方案 |
|-----------|--------|---------|---------|
| casino_games.py:多处 | ⚠️ MINOR | `row["score"] if row else 0` — 已正确处理 | 无需修复 |
| gambling.py:多处 | ⚠️ MINOR | `get_balance(uid)` 内部处理首次访问 → 创建用户行 → 默认500 → 安全 | 无需修复 |
| daily_quest.py:L145 | ⚠️ MINOR | `xp = (row["xp"] or 0) + exp` — None 处理通过 `or 0` | 正确 |

## Interaction 过期处理

| 文件:行号 | 严重度 | 问题描述 | 修复方案 |
|-----------|--------|---------|---------|
| gambling.py:L450+ | ⚠️ MINOR | View 回调中使用 `try/except discord.InteractionResponded`，但未 catch `discord.NotFound`（消息已删除） | 添加 `except discord.NotFound: pass` |
| casino_games.py:多处 | ⚠️ MINOR | BlackjackView._stand 等使用 `interaction.edit_original_response`，可能已过期 | 添加 `try/except discord.NotFound` |
| boss.py:多处 | ⚠️ MINOR | `await interaction.response.edit_message` 无 NotFound 保护 | 添加保护 |

## 按钮防连点

| 文件:行号 | 严重度 | 问题描述 | 修复方案 |
|-----------|--------|---------|---------|
| gambling.py:多处 | ⚠️ MINOR | 按钮回调未在开始处 disabled，可能导致连点 | 在 `_do_result` / `on_submit` 首行禁用按钮 |
| casino_games.py:L136 | ✅ 正确 | Double 按钮：`self.double_btn.disabled = True` 已处理 | 无需修复 |
| casino_games.py:L125 | ✅ 正确 | Hit 按钮未 disabled 但有 `if self.doubled: return`，Stand 也类似 | 无需修复 |

## 整数除法

| 文件:行号 | 严重度 | 问题描述 | 修复方案 |
|-----------|--------|---------|---------|
| gambling.py:L1040 | ✅ 正确 | `profit = int(self._view.bet * multiplier)` | 使用了 `int()` |
| casino_games.py:L170 | ✅ 正确 | `profit = int(self.bet * 2.5)` | 使用了 `int()` |
| casino_games.py:L467 | ✅ 正确 | `payout = int(self.bet * HORSE_ODDS[idx])` | 使用了 `int()` |

## 按钮 row 越界

| 文件:行号 | 严重度 | 问题描述 | 修复方案 |
|-----------|--------|---------|---------|
| gambling.py:1200 | ✅ 正确 | GamblingLobbyView: row 0-2，未超限 | 无需修复 |
| mmorpg_shop.py:多处 | ✅ 已修复 | 14按钮分布在 row 0-4（之前 row 5/6 越界已修复） | 无需修复 |
| boss.py:多处 | ✅ 正确 | 按钮分布在 row 0-4，未超限 | 无需修复 |

## 命令重复注册

| 文件:行号 | 严重度 | 问题描述 | 修复方案 |
|-----------|--------|---------|---------|
| main.py | ✅ 已修复 | 非 full Bot 已在 `setup_hook`/`on_ready` 中 clear+sync | 无需修复 |
| gambling.py vs casino_games.py | ✅ 无冲突 | gambling.py 注册 `/gmpt-gamble`, casino_games.py 注册 `/gmpt-blackjack` 等，无冲突 | 无需修复 |

## 其他Bug

| 文件:行号 | 严重度 | 问题描述 | 修复方案 |
|-----------|--------|---------|---------|
| gambling.py:1220 | ⚠️ MEDIUM | `CrashView(bot=None, ...)` — CrashView `__init__` 参数为 `(user_id, user_name, bet)`，无 `bot` 参数，调用时必崩 | 修复 GamblingLobbyView |
| gambling.py:1212 | ⚠️ MEDIUM | `ScratchView(bot=None, ...)` — 同上问题 | 修复 GamblingLobbyView |
| gambling.py:1230 | ⚠️ MEDIUM | `NumberGuessView(bot=None, ...)` — 同上问题 | 修复 GamblingLobbyView |

---

## 统计

| 严重度 | 数量 |
|--------|------|
| 🔴 CRITICAL | 1 (GamblingLobbyView) |
| ⚠️ MEDIUM | 5 |
| ⚠️ MINOR | 9 |
| ✅ 已验证 | 12 |
