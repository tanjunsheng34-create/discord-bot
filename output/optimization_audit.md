# GMPT Bot 全仓库优化审计报告

> 审计日期：2026-07-19  
> 审计范围：`cogs/*.py`（13个文件）+ `database.py` + `main.py`  
> 总代码量：~10,700 行

---

## 一、安全性

### 🔴 SEC-01 | admin_backup.py:41 | SQL 注入风险（格式化表名）

```python
cur.execute(f"SELECT * FROM {table}")
```

`table` 来自硬编码列表 `tables = ["users", "voice_tracker", ...]`，当前无直接注入风险，但该模式一旦有人扩展 `tables` 列表使用动态来源即可被注入。

**修复**：使用白名单校验
```python
ALLOWED_TABLES = {"users", "voice_tracker", "daily_checkin", "giveaway", "giveaway_entries", "user_inventory"}
if table not in ALLOWED_TABLES:
    raise ValueError(f"Invalid table: {table}")
cur.execute(f"SELECT * FROM {table}")
```

---

### 🔴 SEC-02 | lol.py:530 | 裸 except 掩盖 DB 异常

```python
except: conn.close(); return await interaction.response.send_message("已报名。", ephemeral=True)
```

该 `except:` 捕获所有异常（包括 `KeyboardInterrupt`、`SystemExit`），且将 DB 唯一约束冲突（重复报名）与真正的 DB 故障混为一谈，全部返回"已报名"——用户会误以为操作成功。

**修复**：指定具体异常
```python
except sqlite3.IntegrityError:
    conn.close()
    return await interaction.response.send_message("已报名。", ephemeral=True)
except Exception as e:
    conn.close()
    logger.error(f"join_match failed: {e}")
    return await interaction.response.send_message("报名失败，请稍后重试。", ephemeral=True)
```

---

### 🟡 SEC-03 | 多个 Admin 命令缺权限检查

以下管理命令仅靠命令名区分，无 `@app_commands.default_permissions` 或 `has_permissions` 检查：

| 文件 | 行号 | 命令 |
|------|------|------|
| economy.py | 1375 | `add_coins_cmd` |
| economy.py | 1406 | `reset_coins_cmd` |
| economy.py | 1509 | `shop_edit_cmd` |
| dashboard.py | 4732 | `gmpt_mmr_reset` |
| dashboard.py | 4774 | `gmpt_recover` |

**修复**：添加 `@app_commands.default_permissions(administrator=True)` 或 `@app_commands.checks.has_permissions(administrator=True)`

---

## 二、性能 — 缺索引

SQLite 仅在主键和显式 `CREATE INDEX` 列上有索引。以下高频查询列当前无索引：

### 🔴 PERF-01 | High Priority — 缺 `teams.tournament_id` 索引

- **引用次数**：18 次（dashboard.py + lol.py）
- **典型查询**：`SELECT id, name FROM teams WHERE tournament_id=?` / `DELETE FROM teams WHERE tournament_id=?`
- **影响**：每次 settle/reshuffle 全表扫描 teams 表

**修复**：`CREATE INDEX IF NOT EXISTS idx_teams_tournament_id ON teams(tournament_id)`

---

### 🔴 PERF-02 | High Priority — 缺 `tournament_players.tournament_id` 索引

- **引用次数**：18 次
- **典型查询**：`SELECT id FROM tournament_players WHERE tournament_id=? AND discord_id=?` / `SELECT COUNT(*) as cnt FROM tournament_players WHERE tournament_id=?`

**修复**：`CREATE INDEX IF NOT EXISTS idx_tp_tournament_id ON tournament_players(tournament_id)`

---

### 🔴 PERF-03 | High Priority — 缺 `tournament_matches.tournament_id` 索引

- **引用次数**：6 次
- **典型查询**：`SELECT * FROM tournament_matches WHERE tournament_id=? ORDER BY round, match_index`

**修复**：`CREATE INDEX IF NOT EXISTS idx_tm_tournament_id ON tournament_matches(tournament_id)`

---

### 🟡 PERF-04 | Medium Priority — 缺 `bets` 表复合索引

- `bets.discord_id`：4 次引用
- `bets.match_id`：2 次引用
- `bets.settled`：2 次引用
- **典型查询**：`SELECT id, discord_id, amount, team FROM bets WHERE match_id=? AND settled=0`

**修复**：
```sql
CREATE INDEX IF NOT EXISTS idx_bets_match_settled ON bets(match_id, settled);
CREATE INDEX IF NOT EXISTS idx_bets_discord_id ON bets(discord_id);
```

---

### 🟡 PERF-05 | Medium Priority — 缺 `registrations` 表复合索引

- `is_sub IS NULL OR is_sub=0` 过滤器使用 20 次
- `lane` 过滤 4 次
- `FROM registrations WHERE tournament_id` 出现 49 次

**修复**：
```sql
CREATE INDEX IF NOT EXISTS idx_reg_tournament_is_sub ON registrations(tournament_id, is_sub);
```

---

### 🟡 PERF-06 | Medium Priority — 缺 `tournaments.status` 索引

- **引用次数**：13 次
- **典型查询**：`SELECT id, name FROM tournaments WHERE status='open' ORDER BY id DESC`

**修复**：`CREATE INDEX IF NOT EXISTS idx_tournaments_status ON tournaments(status)`

---

### 🟢 PERF-07 | Low Priority — 其他建议索引

| 表.列 | 引用次数 | 索引建议 |
|--------|----------|----------|
| `draft_captains.draft_id` | 3 | `CREATE INDEX idx_dc_draft_id ON draft_captains(draft_id)` |
| `draft_picks.draft_id` | 2 | `CREATE INDEX idx_dp_draft_id ON draft_picks(draft_id)` |
| `giveaway.status` | 3 | `CREATE INDEX idx_giveaway_status ON giveaway(status)` |
| `user_achievements.user_id` | 3 | `CREATE INDEX idx_ua_user_id ON user_achievements(user_id)` |
| `user_inventory.user_id` | 4 | `CREATE INDEX idx_ui_user_id ON user_inventory(user_id)` |
| `votes.tournament_id` | 3 | `CREATE INDEX idx_votes_tournament_id ON votes(tournament_id)` |

---

## 三、代码质量 — 重复代码

### 🔴 QUAL-01 | dashboard.py | SwissView 与 EliminationView 存在大量重复

整个 `dashboard.py` 4837 行中，赛事管理视图被完整复制两套（Swiss/Elimination），导致大量重复函数：

| 函数 | dashboard.py 中定义次数 |
|------|------------------------|
| `confirm_teams` | 3 个类中 3 份 |
| `_get_unassigned` | 3 个类中 3 份 |
| `_rebuild_select` | 2 份 |
| `add_to_a` / `add_to_b` | 3 份 |
| `clear_teams` | 3 份 |
| `select_callback` | 2 份 |
| `settle_btn` | 2 份 |
| `signup_btn` | 2 份 |
| `reshuffle_btn` | 2 份 |
| `captain_select_callback` | 2 份 |
| `lane_callback` | 3 份 |

**影响**：每次修 bug 需改多处，极易遗漏产生不一致。

**修复**：提取公共基类 `BaseMatchView`，将共享逻辑（报名/分队/清理/按钮回调）放入基类，SwissView/EliminationView 仅覆写差异部分。预计可削减 ~30-40% 冗余行数。

---

### 🟡 QUAL-02 | economy.py | SHOP_ITEMS 初始化数据内联在代码中

`economy.py` 前 130 行是硬编码的商品列表 dict（价格/颜色/描述），导致文件臃肿（2037 行）且修改商品需改代码。

**修复**：将商品数据迁移到 `shop_items` 表（表结构已完整：name/description/price/item_type/category），运行时从 DB 加载。将 `init_shop_items()` 改为仅在表为空时插入默认数据。

---

### 🟡 QUAL-03 | 全局 | `get_db()` 直接调用 201 次 vs `db_context()` 仅 8 次

`db_context()` 提供自动 commit/rollback/close，但 96% 的数据库操作直接调用 `get_db()` + 手动 `conn.close()`，缺少错误时的自动 rollback。

**修复**：逐步迁移高频数据写入路径到 `db_context()`。优先迁移 settle/match 结算/金币交易等关键路径。

---

### 🟢 QUAL-04 | economy.py | 硬编码商品参数

`economy.py` 前 130 行包含 ~80 个硬编码数字（110, 210, 800, 255, 215 等），代表商品价格和颜色值。

**修复**：迁移到 DB 后可消除。当前可先行提取颜色常量为类属性：`COLOR_LEGENDARY = 0xFFD700` 等。

---

## 四、数据库

### 🔴 DB-01 | database.py | `dashboard_panel` 死表

`dashboard_panel` 表在 `database.py:338` 创建，但代码中已有注释标记 `[DEPRECATED: 零引用死表，待下个大版本删除]`。全仓扫描确认 0 次引用。

**修复**：在下一个大版本中删除 `CREATE TABLE IF NOT EXISTS dashboard_panel` 语句。

---

### 🟡 DB-02 | database.py | 缺事务保护的写操作

`economy.py:713` 的 `_check_completionist` 函数连续执行 8 个 INSERT 操作，若中途失败会留下不完整数据（部分成就已授予）。

**修复**：用 `executescript()` 或 `db_context()` 包裹：
```python
with db_context() as cur:
    for achievement in to_award:
        cur.execute("INSERT OR IGNORE INTO user_achievements ...")
```

---

## 五、错误处理

### 🟡 ERR-01 | lol.py:427, lol.py:1097 | 通道删除的裸 except

```python
except:
    pass
```

Discord API 调用可能因权限/网络等原因失败，全部静默吞掉不利于排错。

**修复**：`except (discord.Forbidden, discord.HTTPException): pass`

---

### 🟡 ERR-02 | economy.py:136 | PIL 字体加载裸 except

```python
except:
    pass
```

可能掩盖 `OSError`（文件不存在导致字体回退失败）。

**修复**：`except (OSError, IOError): pass`，并加 `logger.warning(...)`

---

### 🟢 ERR-03 | main.py | 多个 `except Exception: pass`

`main.py` 中有 4 处 `except Exception: pass`（在 backup/restore 流程中 `_find_last_backup`、`_get_backup_channel` 等），虽非关键路径但不利于排错。

**修复**：至少加 `logger.debug(...)` 日志输出。

---

## 六、UX

### 🟡 UX-01 | 42 个命令无 cooldown 保护

全仓 42 个 slash 命令无 `@app_commands.checks.cooldown`。高频命令（如 `/daily`、`/shop`、`/balance`、`/profile`）可能被恶意刷屏。

**修复**（按优先级）：
- P0 写入类：`shop_cmd`、`buy_cmd`、`use_cmd`、`daily_cmd`、`gift_cmd`、`bet_cmd` → `@app_commands.checks.cooldown(1, 5.0)`
- P1 查询类：`balance_cmd`、`inv_cmd`、`profile`、`live_game` → `@app_commands.checks.cooldown(1, 3.0)`
- P2 低频：`create_match`、`rank`、`players` → `@app_commands.checks.cooldown(1, 10.0)`

---

### 🟢 UX-02 | 15 个命令缺 autocomplete

| 文件 | 命令 | 参数 |
|------|------|------|
| economy.py | `gift_cmd` | `player` |
| economy.py | `buy_cmd` | `item_id` |
| economy.py | `use_cmd` | `item_id` |
| economy.py | `bet_cmd` | `match_id`, `team` |
| economy.py | `add_coins_cmd` | `player` |
| economy.py | `reset_coins_cmd` | `target` |
| economy.py | `shop_edit_cmd` | `item_id` |
| lol.py | `create_match` | `match_name`, `max_players` |
| lol.py | `profile` | `name`, `tag`, `region` |
| lol.py | `match_history` | `name`, `tag`, `region`, `count` |
| lol.py | `live_game` | `name`, `tag`, `region` |
| lol.py | `link_riot` | `summoner_name`, `tag_line`, `region` |
| dashboard.py | `gmpt_leaderboard_mmr` | `limit` |

**修复**：为 `player`/`target` 添加 Discord 成员 autocomplete；为 `item_id` 添加商店物品 autocomplete；为 `match_id` 添加活跃比赛 autocomplete。

---

## 七、问题汇总

| 维度 | 🔴 严重 | 🟡 中等 | 🟢 低优先级 |
|------|---------|---------|-------------|
| 安全性 | 2 | 1 | 0 |
| 性能（缺索引） | 3 | 3 | 6 |
| 代码质量（重复） | 1 | 2 | 1 |
| 数据库 | 1 | 1 | 0 |
| 错误处理 | 0 | 2 | 1 |
| UX | 0 | 1 | 2 |
| **合计** | **7** | **10** | **10** |

---

## 八、建议修复优先级

### P0（本周内）

1. **加索引**：`teams.tournament_id`、`tournament_players.tournament_id`、`tournament_matches.tournament_id` — 3 条 SQL，零风险
2. **修复 lol.py:530 裸 except** — 1 行改 4 行
3. **删除 dashboard_panel 死表** — database.py 删 5 行
4. **Admin 命令加权限检查** — 5 条装饰器

### P1（本月内）

5. **加附属索引**：`bets`、`tournaments.status`、`registrations(tournament_id, is_sub)` — 5 条 SQL
6. **Swiss/Elimination 视图提取基类** — 架构重构，预计削减 500-800 行
7. **商品数据迁移到 DB** — 消除 economy.py 前 130 行硬编码
8. **关键路径加 cooldown**（daily/shop/buy/bet/use）— 5 条装饰器

### P2（下个迭代）

9. 剩余 cooldown 和 autocomplete 补充
10. `get_db()` → `db_context()` 渐进迁移
11. 裸 except 替换为具体异常类型
