# Gaming Planet Bot — 全仓库深度审计报告

> **审计日期**: 2026-07-19 | **审计范围**: 15 个 .py 文件, 共 12,422 行

---

## 一、代码质量 (需修复项)

### 1.1 N+1 数据库查询 (严重 — 共 74 处)

SQLite 逐行循环内执行 INSERT/UPDATE 是最大性能瓶颈。应改用 `executemany()` 批量操作。

#### dashboard.py (37 处 — 优先级最高，5KB 文件 101 次 DB 打开)

| 行号 | 模式 | 修复建议 |
|------|------|---------|
| L439, L444 | `for uid in team_a/b: cur.execute("UPDATE registrations...")` | `executemany` 批量更新 |
| L846 | `for pid in players: cur.execute("INSERT INTO registrations...")` | `executemany` 批量插入 |
| L986, L994 | `for r in cur.fetchall(): cur.execute("UPDATE users SET score...")` | 单条 `UPDATE users SET score=score+? WHERE discord_id IN (...)` |
| L1212, L1321 | `for t in teams: cur.execute("SELECT discord_id FROM registrations WHERE team_id=?")` | 单条 `SELECT ... WHERE team_id IN (...)` |
| L1599, L1822 | 同上模式 (insert loop + team assign loop) | `executemany` |
| L2037, L3661 | `for lane in LANES: cur.execute("SELECT COUNT(*) ... WHERE lane=?")` | 单条 `SELECT lane, COUNT(*) ... GROUP BY lane` |
| L2514, L3104, L3870 | `for u in ta/tb: cur.execute("UPDATE registrations SET team_id=?...")` | `executemany` |
| L2600 | `for member in selected_members: cur.execute("SELECT id FROM registrations...")` | 批量 WHERE discord_id IN |
| L2742 | `for pid in winners: cur.execute("UPDATE users SET mmr...")` | `executemany` |
| L2822 | `for wid in winner_ids: cur.execute("UPDATE users SET score...")` | `executemany` |
| L2893, L2901 | active_effects 循环 | 批量查询 |
| L3021, L3025 | `for wid in winner_ids: cur.execute("SELECT mmr...")` | 单条 `SELECT ... WHERE discord_id IN (...)` |
| L3212 | `for r in regs: cur.execute("SELECT mmr...")` | 单条批量查询 |
| L3415 | `for wid in winners: cur.execute("UPDATE mmr SET mmr=?...")` | `executemany` |

#### 其他文件

| 文件 | 行号 | 模式 |
|------|------|------|
| lol.py | L567, L570, L618, L628, L810, L1205, L1406, L1411 | 循环内 DB 操作 |
| economy.py | L846, L1261, L1451, L1588, L1851, L1880, L2084 | 循环内 DB 查询 |
| queue.py | L150, L163, L171 | 循环内 DB 查询 |
| main.py | L108, L245, L256, L268, L278, L292, L302 | 循环内 DB 操作 |
| database.py | L36, L219, L415 | retry/get_db 循环 |

**工作量估算**: 2-3 天 (dashboard.py 为主要工作)

---

### 1.2 重复代码块 (严重 — 8 处完全一致的团队分配逻辑)

dashboard.py 中以下 8 个位置的团队分配代码完全一致 (删除旧 teams → 创建 Team A → 循环写入 → 创建 Team B → 循环写入):

| 行号 | 函数上下文 |
|------|-----------|
| L436-446 | 匿名 settle 按钮回调 |
| L846-852 | 匿名 match 创建 |
| L1321 | 内部 match 创建 |
| L1599-1607 | 匿名 settle |
| L1822-1830 | 匿名 settle |
| L2514-2518 | 匿名 shuffle settle |
| L3104-3108 | 匿名 settle |
| L3870-3874 | 匿名 settle |

**修复**: 抽取 `_assign_teams(cur, match_id, team_a_ids, team_b_ids)` 公共函数，减少 ~80 行重复代码。

**工作量估算**: 0.5 天

---

### 1.3 异常处理缺陷

#### 1.3.1 裸 except (4 处)

| 文件 | 行号 | 上下文 | 风险 |
|------|------|--------|------|
| economy.py | L170 | `ImageFont.truetype(path, size)` | 吞掉所有异常包括 MemoryError，且 fallback 到 load_default |
| lol.py | L429 | `await ch.delete()` 频道删除 | 吞掉所有异常，频道未删除也静默 |
| lol.py | L532 | `conn.close()` | 连接泄露不感知 |
| lol.py | L1100 | Riot API 状态检查 | 网络异常静默丢失 |

#### 1.3.2 吞异常 pass (33 处 — 仅列严重项)

| 文件 | 行号 | 类型 | 问题 |
|------|------|------|------|
| dashboard.py | L473, L784, L813, L1635, L1859, L2542, L3377, L4689 | `except Exception: pass` | 26 处静默吞掉所有异常，调试极其困难 |
| economy.py | L883, L1109, L1970, L2226, L691 | `except Exception: pass` | 5 处，包括 DB 写入 + 成就检查 |
| economy.py | L170 | `except: pass` | 字体加载失败静默，可能导致后续 PIL 崩溃 |
| main.py | L148, L133, L367, L165, L94 | `except Exception: pass` | 5 处 Cog 加载失败静默 |
| lol.py | L429, L1100 | `except: pass` | 频道删除失败 + Riot API 失败静默 |
| giveaway.py | L395, L173 | `except Exception: pass` | 抽奖结束失败静默 |

**修复**: 最低限度加 `logger.exception()` 日志；最佳实践是仅 catch 预期异常类型。

**工作量估算**: 1 天

---

### 1.4 未使用的导入 (5 处)

| 文件 | 行号 | 导入 | 说明 |
|------|------|------|------|
| dashboard.py | L4 | `asyncio` | 仅 import 未使用 |
| dashboard.py | L15 | `DraftView`, `swiss_pairing` | 已移除的功能残留 |
| lol.py | L4 | `random` | 代码中无 `random.` 调用 |
| lol.py | L12 | `add_coins` | 代码中仅 1 处引用 (import 自身) |
| main.py | L5 | `sys` | 仅 import 未使用 |
| tournament.py | L12 | `datetime` | 仅 import 未使用 |

**工作量估算**: 0.1 天 (直接删除)

---

### 1.5 SQL 注入风险 (7 处 f-string SQL)

| 文件 | 行号 | 风险等级 |
|------|------|---------|
| dashboard.py | L2854, L2883 | 中 — 仅插入常量 `'double_mmr'`，但写法不安全 |
| main.py | L110 | 中 — 仅插入常量 `'Iron'` |
| giveaway.py | L315 | 中 — 仅插入常量标签 |
| admin_backup.py | L41 | 中 — 仅插入常量表名 |
| lol.py | L196, L653 | 中 — 仅插入常量字段名 |
| database.py | L226 | 低 — ALTER TABLE 列名来自常量列表 |

> 虽然当前均为常量注入，但 f-string SQL 是危险信号。建议全部改为参数化。

**工作量估算**: 0.2 天

---

### 1.6 超长函数 (5 处)

| 文件 | 行号 | 函数 | 行数 | 问题 |
|------|------|------|------|------|
| database.py | L68 | `init_db()` | 360 | 包含建表 + 索引 + 迁移，应拆分为 `_create_tables()` + `_create_indexes()` + `_run_migrations()` |
| economy.py | L616 | `buy_item()` | 197 | 购买逻辑 + 库存减扣 + 效果触发 + 通知全混在一起 |
| dashboard.py | L954 | `settle_btn()` | 188 | MMR 结算 + 金币结算 + 下注结算混在同一函数 |
| dashboard.py | L2176 | `settle_btn()` | 179 | 第二个 settle_btn 变体，与 L954 大量重复 |
| dashboard.py | L4021 | `_settle()` | 167 | 三个结算阶段可拆分 |

**工作量估算**: 2 天 (需回归测试)

---

### 1.7 硬编码 Discord ID (13 处)

dashboard.py 包含 13 个硬编码的 guild/channel ID:

```
L1066: 1442412993269731452
L1264: 1438050912814895186
L1265: 1453208983358935121
L1285: 1437626921394372658
L1286: 1453208983358935121
L1301: 1438050912814895186, 1437626921394372658, 1453208983358935121
L1411: 1438050912814895186, 1437626921394372658, 1442412877301416006, 1453208983358935121
L2304: 1442412993269731452
```

应移入 `config.py` 或数据库 `guild_settings` 表。

**工作量估算**: 0.3 天

---

### 1.8 性能瓶颈

| 问题 | 位置 | 影响 |
|------|------|------|
| `init_db()` 每列逐个 ALTER TABLE (9 次) | database.py L218-260 | 启动慢，每次建表后逐列 try/except |
| cooldown 仅主 1 处 | main.py L2 | 无速率限制，所有经济命令可被洪水攻击 |
| `random.shuffle(players)` 原地修改 | dashboard.py L850 | 副作用不明显，建议用 `random.sample` |
| `discord.ui.View` 无超时清理 | 多处 | 按钮 View 可能在内存中堆积 |

---

### 1.9 死代码 (Dead Code)

| 项 | 说明 |
|----|------|
| `dashboard_panel` 表 | 代码标注 `[DEPRECATED: 零引用死表]`，待删除 |
| `gmpt-reset-coins` 命令 | 代码标注 `[DEPRECATED]`，但未用 `@app_commands.default_permissions` 禁用 |
| `cogs/shared_views.py` | 仅 51 行，几乎无实质内容 |
| `cogs/__init__.py` | 空文件 |
| `utils/__init__.py` | 空文件 |
| `utils/helpers.py` | 仅 15 行，函数未被其他模块调用 |

---

## 二、功能完整性审计

### 2.1 已计划但未实现

| 功能 | DB 表支持 | 命令支持 | 状态 |
|------|----------|---------|------|
| **Weekly Challenges** | 无 | 无 | 未实现 |
| **Season System** | 无 | 无 (仅 1 处注释提及) | 未实现 |
| **Match History** | 无专用表 | 部分 (`/gmpt-history` 仅 LOL) | 半实现 |
| **Role Queue** | 无 | 无 | 未实现 |
| **Daily Streak** | `daily_checkin.streak` 字段存在但未读取 | 无 | 仅有字段无逻辑 |
| **Player Profiles** | 无 | 无 (lol.py 有 Riot 绑定但缺综合 Profile) | 未实现 |
| **Auto Team Balance** | 无 | 无 | 未实现 |

### 2.2 DB 表完整度

| 表 | 状态 |
|----|------|
| `dashboard_panel` | **死表** — 零引用，代码已标记废弃 |
| `voice_sessions` | 仅 economy.py 引用 (非 voice_tracker) |
| `giveaway` (单数) | 与 `giveaways` (复数) 重复 — 两个 giveaway 表并存 |
| `giveaway_entries` | 同样有两个表，存在 schema 冲突风险 |

### 2.3 命令完整度

| 命令 | 功能状态 |
|------|---------|
| `/gmpt-leave-queue` | 队列离开命令 |
| `/gmpt-queue-status` | 队列状态查看 |
| `/gmpt-riot-status` | Riot 服务器状态 |
| `/gmpt-stream` | 直播状态 |
| `/gmpt-autozone` | 自动开黑检测 |
| `/gmpt-shop-edit` | 商店编辑 (管理员) |
| `/gmpt-bet-stats` | 下注统计 |

以上命令均完整可用。

---

## 三、新增功能建议 (按优先级排序)

### P0 — 立即实施 (高价值 / 低工作量)

| # | 功能 | 说明 | 工作量 | 外部依赖 |
|---|------|------|--------|---------|
| 1 | **命令冷却系统** | 全仓仅 1 处 cooldown。给 `/gmpt-daily`、`/gmpt-bet`、`/gmpt-gift` 等高频命令加冷却，防刷金币 | 0.5 天 | 无 |
| 2 | **N+1 修复** | 将 74 处循环内 DB 操作改为 `executemany`，预计 DB 性能提升 3-10x | 2 天 | 无 |
| 3 | **全局错误日志** | 33 处 `except ...: pass` 改为 `logger.exception()`，大幅提升可调试性 | 1 天 | 无 |

### P1 — 短期实施 (中价值 / 中工作量)

| # | 功能 | 说明 | 工作量 | 外部依赖 |
|---|------|------|--------|---------|
| 4 | **Daily Streak 可视化** | `daily_checkin.streak` 字段已存在，只需在 `/gmpt-daily` 中额外显示连续签到天数和奖励加成 | 0.5 天 | 无 |
| 5 | **Player Profile 面板** | 整合 MMR、金币、库存、成就、LOL 战绩到单个 `/gmpt-profile` 命令 | 2 天 | Riot API (已有) |
| 6 | **Bet 系统扩展** | 目前仅支持单场下注，增加 `/gmpt-bet-live` 可在进行中比赛动态下注 | 1.5 天 | 无 |
| 7 | **自动 Team Balance** | 基于 MMR 自动分配队伍，替代手动 shuffle | 1 天 | 无 |

### P2 — 中期规划 (高价值 / 高工作量)

| # | 功能 | 说明 | 工作量 | 外部依赖 |
|---|------|------|--------|---------|
| 8 | **Season 排位赛季** | 每 3 个月重置 MMR，保存赛季历史到 `season_history` 表，发放赛季奖励 | 3 天 | 无 |
| 9 | **Weekly Challenges** | 每周随机任务（玩 X 局 / 赢 X 局），完成后奖励金币，增加活跃度 | 2 天 | 无 |
| 10 | **Match History Hub** | 集中展示全部比赛历史（含 LOL + 自定比赛 + Swiss Tournament），支持分页 + 筛选 | 2 天 | 无 |

---

## 四、已完备 (无需改动项)

| 项 | 评估 |
|----|------|
| 50 个 Slash Command | 全部正常注册，无空白命令 |
| 经济系统 (Economy) | 商店 / 背包 / 道具使用 / 成就 / 每日签到 / 交易记录 / 金币赠送 — 完整闭环 |
| 比赛系统 (LOL) | 创建 / 报名 / 随机分队 / 结算 / 踢人 / 取消 完整 |
| 锦标赛系统 (Tournament) | Swiss + Elimination 双模式，支持 Captain Draft |
| 抽奖系统 (Giveaway) | 创建 / 参与 / 结束 / 重抽 完整 |
| 语音追踪 (Voice Tracker) | 时长统计 + 排行榜 |
| MMR 排位 | ELO 算法 + 排行榜 + Board 持久化 |
| 数据库索引 | 4 个关键索引 (registrations, giveaway_entries, transactions) 已建 |
| WAL 模式 | SQLite WAL 已启用，支持并发读写 |
| Riot API 集成 | 账号绑定 / 状态查询 / OP.GG 战绩 |

---

## 五、总结

### 风险矩阵

| 风险等级 | 数量 | 说明 |
|---------|------|------|
| 严重 | 74 处 N+1 + 8 处重复代码 | DB 性能严重退化 |
| 高 | 33 处异常吞没 + 4 处裸 except | 线上排障几乎不可能 |
| 中 | 6 处未用导入 + 7 处 f-string SQL + 13 硬编码 ID | 代码腐化信号 |
| 低 | 5 处超长函数 + 死代码 | 可维护性问题 |

### 修复优先级排序

```
1. N+1 批量化 (dashboard.py 优先) ................ 2 天
2. 全局异常日志 ................................ 1 天
3. 抽取重复的 team assign 公共函数 .............. 0.5 天
4. 命令 cooldown .............................. 0.5 天
5. Daily Streak 显示 ........................... 0.5 天
6. 删除死代码 (dashboard_panel + deprecated cmd) . 0.2 天
7. SQL 参数化 .................................. 0.2 天
8. 清理未用 import ............................. 0.1 天

总计预计: ~5 个工作日
```

### 新增功能建议总计

```
P0 (立即): 3 项, 3.5 天
P1 (短期): 4 项, 5 天
P2 (中期): 3 项, 7 天
```
