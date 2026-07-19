# GMPT Bot 全仓库优化审计报告

> 审计范围：`cogs/*.py`(12 文件) + `database.py` + `main.py` — 共 13 文件，约 5500+ 行  
> 审计日期：2026-07-19  
> 方法：两阶段 AST 扫描（初筛 212 条） → 逐条深挖验证 → 收敛为 16 条可操作清单

---

## 概览

| 严重度 | 数量 | 说明 |
|--------|------|------|
| 🔴 严重 | 3 | 隐性数据丢失 / 异常吞没误导用户 |
| 🟡 重要 | 10 | N+1 性能 / 异常无声吞没 / 连接复用 |
| 🟢 建议 | 3 | 代码组织 / UX 增强 |

---

## 🔴 严重（必须修复）

### 1. [lol.py:530] 裸 except 吞异常并返回误导入消息

**问题**：报名接口用 `except:` 捕获所有异常（含 `sqlite3.OperationalError`、`KeyboardInterrupt` 等），然后统一回复"已报名"。若 DB 写入失败，用户会看到"已报名"但实际未写入。

```python
# lol.py:527-531
try:
    cur.execute("INSERT INTO registrations ...")
    cur.execute("INSERT OR IGNORE INTO users ...")
    conn.commit()
except: conn.close(); return await interaction.response.send_message("已报名。", ephemeral=True)
```

**修复**：仅捕获 `sqlite3.IntegrityError`（重复报名），其他异常应向上传播让全局错误处理器通知用户。

```python
except sqlite3.IntegrityError:
    conn.close()
    return await interaction.response.send_message("你已报名该比赛。", ephemeral=True)
```

---

### 2. [economy.py:704-710] 函数写入在 caller 已 commit 之后 — 隐性数据丢失

**问题**：`check_achievement()` 调用链中，caller 在 line 704 执行 `conn.commit()` 后于 line 708 调用 `_check_completionist(cur, user_id, a["id"])`。`_check_completionist` 内部有 INSERT/UPDATE（line 741-752），但 caller 不会再 commit（line 709 直接 `conn.close()`）。

- 若运行在 Python < 3.12（无 PEP 249 autocommit），这些写入**静默丢失**，用户解锁全成就后不会获得奖励。
- 即使运行在 3.12+，依赖隐式 autocommit 不可靠。

**修复**：将 `conn.commit()` 移到 `_check_completionist()` 调用之后。

```python
# economy.py:700-709 当前顺序
cur.execute("UPDATE users SET score = score + ? ...")
cur.execute("INSERT INTO transactions ...")
conn.commit()                        # ← 太早了

_check_completionist(cur, user_id, a["id"])
conn.close()

# 修复后
_check_completionist(cur, user_id, a["id"])
conn.commit()                        # ← 移到此处
conn.close()
```

---

### 3. [database.py:21] WAL 初始化失败无声吞没

**问题**：`_ensure_wal()` 用 `except Exception: pass` 吞掉所有异常。若 WAL 模式或 busy_timeout 设置失败（磁盘满、权限不足），bot 将以非 WAL 模式运行，后续高频并发写入会触发 `database is locked`。

```python
# database.py:17-20
try:
    conn = sqlite3.connect(DATABASE, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.close()
    _WAL_INITIALIZED = True
except Exception:
    pass  # ← 无声失败
```

**修复**：记录错误日志，并在无法启用 WAL 时发出 warning。

```python
except Exception as e:
    logger = logging.getLogger(__name__)
    logger.error(f"Failed to enable WAL mode: {e}")
```

---

## 🟡 重要（强烈建议修复）

### 4. [dashboard.py:2695-2710] `_execute_settle` 结算循环内逐条写入 — N+1

**问题**：对每个 winner/loser 逐条执行 INSERT + UPDATE + INSERT 三条 SQL，10 人比赛产生 30 次 DB 往返。每天数十场比赛时开销显著。

```python
# dashboard.py:2695
for wid in winner_ids:
    cur.execute("INSERT INTO users ... ON CONFLICT ... DO NOTHING", (wid,))
    cur.execute("UPDATE users SET score=score+?...", (MATCH_WIN_COINS, wid))
    cur.execute("INSERT INTO transactions ...", (wid, MATCH_WIN_COINS, ...))
```

**修复**：用 `executemany` 批量写入。

```python
# 批量 INSERT users
cur.executemany(
    "INSERT INTO users (discord_id, username) VALUES (?,'unknown') ON CONFLICT(discord_id) DO NOTHING",
    [(wid,) for wid in winner_ids],
)
# 批量 UPDATE score
cur.executemany(
    "UPDATE users SET score=score+? WHERE discord_id=?",
    [(MATCH_WIN_COINS, wid) for wid in winner_ids],
)
# 批量 INSERT transactions
cur.executemany(
    "INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)",
    [(wid, MATCH_WIN_COINS, f"Match win #{match_id}") for wid in winner_ids],
)
```

---

### 5. [dashboard.py:2760-2800] 道具效果处理逐条写入 — N+1

**问题**：双倍 MMR、MMR 保护、偷金币、经验加成四种效果，每种都在循环内逐条 UPDATE/INSERT。偷金币最重：对每个赢家遍历所有输家各写 3 条。

**修复**：同样用 `executemany` 批量。

---

### 6. [dashboard.py:2686-2830] `_execute_settle` 中 3 次独立 `get_db()` — 连接未复用

**问题**：同一函数内三次 `conn = get_db()` / `conn2 = get_db()` / `conn_eff = get_db()`，每次连接新建都要走 WAL pragma + busy_timeout。合并为一次可减少连接开销。

**修复**：在函数开头获取一次连接，贯穿使用。

---

### 7. [economy.py:1155] `use_cmd` 6 次 `get_db()` — 连接碎片化

**问题**：`use_cmd` 函数在道具使用流程中调用 `get_db()` 6 次（验证库存、检查重复效果、写入效果、记录事务等），每次建立新连接。

**修复**：在函数开头获取一次连接，通过参数传递 `cur` 给子函数。

---

### 8. [main.py:108-302] `export_backup_data()` 循环内逐表 SELECT — N+1

**问题**：遍历 `BACKUP_TABLES` 列表逐表执行 `SELECT *`，每个表一次 DB 往返。

```python
# main.py:108-113
for table in BACKUP_TABLES:
    try:
        cur.execute(f"SELECT * FROM {table}")
        ...
```

**修复**：若 `BACKUP_TABLES` 过多（10+），可用 UNION ALL 合并查询或保持现状（当前表数少时影响有限）。

---

### 9. [database.py:193-224] ALTER TABLE 迁移无日志 — 排查困难

**问题**：`init_db()` 中 10+ 个 `try: ALTER TABLE ... except sqlite3.OperationalError: pass` 模式正确但未记录被忽略的异常。若某次迁移因非"列已存在"原因失败，将无声跳过。

**修复**：区分 `duplicate column` 错误与其他 OperationalError。

```python
try:
    cursor.execute(f"ALTER TABLE tournaments ADD COLUMN {col} {col_type}")
except sqlite3.OperationalError as e:
    if "duplicate column" not in str(e).lower():
        logger.warning(f"ALTER TABLE {col} failed: {e}")
```

---

### 10. [database.py:68] `init_db()` 326 行 — 单函数过长

**问题**：一个函数包含 10+ 个 CREATE TABLE + 10+ 个 ALTER TABLE，难以维护和审查。

**修复**：拆分为 `_create_tables(cursor)` + `_run_migrations(cursor)` 两个子函数。

---

### 11. [多文件] 30+ 处 `except Exception: pass` 无声吞异常

**分布**：
- `dashboard.py`：23 处（结算、报名、UI 渲染等）
- `economy.py`：6 处（商店图片生成、每日签到、语音挂机等）
- `database.py`：7 处（ALTER TABLE 迁移）
- `main.py`：5 处（备份、频道获取）
- `giveaway.py`：2 处
- `lol.py`：3 处

**评估**：大部分在 UI 渲染/字体加载/频道删除等非关键路径，为可接受的防御性编程。但以下值得加日志：
- `dashboard.py:382,409` — 报名/结算数据路径
- `database.py:193-224` — schema 迁移
- `economy.py:933` — 每日签到链

**修复**：在数据路径的 pass 处加 `logger.warning(f"Non-critical error in xxx: {e}", exc_info=True)`。

---

### 12. [dashboard.py:4837] `dashboard.py` 4837 行 — 单文件过大

**问题**：单个 cog 文件 4837 行，包含 UI 交互、结算、比赛管理、道具效果、MMR、竞猜等多个职责。

**建议**：后续可按职责拆分为 `settle.py`、`match_ui.py`、`vote.py` 等子模块。

---

### 13. [dashboard.py:2729] f-string 构建动态 IN 子句 — 安全但不够优雅

**问题**：

```python
f"SELECT ... WHERE discord_id IN ({placeholders}) GROUP BY discord_id"
```

其中 `placeholders = ",".join("?" * len(unique_pids))` 由 `len()` 生成，非用户输入，**无 SQL 注入风险**。但该模式在多处重复（line 2729, 2751）。

**建议**：抽取为工具函数 `build_in_clause(column, values)` 统一复用。

---

## 🟢 建议（可后续迭代）

### 14. [全仓库] 部分命令缺少速率限制

**问题**：`gmpt-daily`(每日签到)、`gmpt-balance`(余额)、`gmpt-shop`(商店) 等高频命令无 cooldown。虽然 Discord.py app_commands 的 cooldown 支持有限，但可通过 `@app_commands.checks.cooldown()` 或手动时间戳实现。

**建议**：对每日签到加 23h cooldown（避免跨午夜重复），商店刷新加 5s cooldown。

---

### 15. [economy.py:143-150] `_get_font()` PIL 字体加载裸 except — 可接受但影响 UX

**问题**：字体加载失败时静默回退到默认字体，中文字符可能显示为方框，用户不知道原因。

**建议**：加载失败时 `logger.warning(f"Font {path} not found, Chinese text may not render")`。

---

### 16. [main.py:367] 全局错误处理器内嵌 try/except: pass

**问题**：命令错误时尝试发 ephemeral 消息通知用户，若发送也失败则静默放弃。合理但可加日志用于监控错误通知管道是否正常。

---

## 已排除的误报

| 初筛命中 | 排除原因 |
|---------|---------|
| economy.py:1901,1439,1961,1469 f-string SQL 注入 | f-string 仅用于 VALUES 内的数据字段（事务描述），SQL 语句使用 `?` 参数化，**安全** |
| dashboard.py:2729,2751 f-string SQL 注入 | `placeholders` 是 `"?,?,?"` 由 `len()` 生成，非用户输入，**安全** |
| database.py:193 f-string ALTER TABLE | `col`/`col_type` 来自代码内硬编码元组，非用户输入，**安全** |
| admin_backup.py:39-157 全部 7 条 N+1 | 备份脚本性质为逐表导出，迭代写入是其设计意图，非性能热点 |
| dashboard.py 大量 N+1 命中（#8-#41） | 多数是 UI 交互流程中的 2-3 条查询，数据量极小（单场比赛），优化 ROI 低 |
| database.py:84-86 N+1 | `init_db()` 仅启动执行一次，N 极小（约 10 条 ALTER TABLE） |

---

## 修复优先级建议

| 优先级 | 编号 | 影响 |
|--------|------|------|
| P0 - 本周 | #1 报名异常吞没、#2 成就奖励丢失、#3 WAL 无声失败 | 数据正确性与可用性 |
| P1 - 本月 | #4 结算 N+1、#5 道具 N+1、#6 连接复用 | 高频路径性能 |
| P2 - 下月 | #7-#13 代码质量与可维护性 | 长期健康度 |
| P3 - 后续 | #14-#16 UX 增强 | 用户体验 |
