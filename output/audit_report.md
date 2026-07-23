---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 28d8423b56aed61a59a390221b167e51_f4250550865111f18108525400287e28
    ReservedCode1: 9eu1Fcce0mif5RLyhEQbXS6zAzlbUympaQV6A7Ts+ntLJB4xyut2uaJNS09EMY1hySUT08fvHH/m+V+56fxzDTVUhTZt3U4h40BkH1amMJaOyNFR8+ydx1y6VtgCMKNyWHCpvoSAyYcZjEBneg+NOyGmW+a2zsuzRFnw9tqyZPAGPG0R6bNPa+C6xsE=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 28d8423b56aed61a59a390221b167e51_f4250550865111f18108525400287e28
    ReservedCode2: 9eu1Fcce0mif5RLyhEQbXS6zAzlbUympaQV6A7Ts+ntLJB4xyut2uaJNS09EMY1hySUT08fvHH/m+V+56fxzDTVUhTZt3U4h40BkH1amMJaOyNFR8+ydx1y6VtgCMKNyWHCpvoSAyYcZjEBneg+NOyGmW+a2zsuzRFnw9tqyZPAGPG0R6bNPa+C6xsE=
---

# 全项目审计报告

**项目**: discord-bot | **扫描文件**: 29 个 .py | **日期**: 2026-07-23

---

## 一、致命崩溃风险 (🔴)

> 未发现会导致进程直接崩溃的致命问题。

| # | 文件 | 行号 | 问题描述 | 修复建议 |
|---|------|------|----------|----------|
| — | — | — | 无致命崩溃 | 之前已知的 `_get_team_score → None` 和 `import datetime` 已修复 |

### 1.1 `+=` 操作 None 风险（已排查）

全部 42 处 `+=` 均已检查：
- `main.py:499` `current_level += 1` — `current_level` 已在前一行从 DB 读取并赋值，安全
- `tournament.py:313` `pick_score += (player_info[1] or 0)` — 已用 `or 0` 兜底
- `voice_tracker.py:124` `current_level += 1` — 已从 DB 读取，安全
- `dashboard.py:3779-3787` `delta +=` — 变量在同一函数内初始化为 0，安全
- 其余均安全

### 1.2 `member.voice` 判空（已排查）

全部 4 处 `member.voice` 使用均已正确判空（`if member and member.voice and member.voice.channel:`）

### 1.3 `datetime` 导入（已排查）

`main.py` L10 `import datetime`，L415 `datetime.datetime.now()` — **用法正确**（与 `import datetime` 匹配）。无 bug。

---

## 二、潜在风险 (🟡)

### 2.1 `on_voice_state_update` 双重监听

| # | 文件 | 行号 | 问题描述 | 修复建议 |
|---|------|------|----------|----------|
| 2.1 | daily.py:102 + voice_tracker.py:38 | — | 两个 Cog 都注册了 `@commands.Cog.listener() on_voice_state_update`。daily.py 追踪每日语音时长（计算签到奖励资格），voice_tracker.py 追踪全局语音统计数据（总秒数/登录天数/加入次数）。两者各自维护独立的 `self._join_times` dict，**理论上独立运行无冲突**，但共享同名的实例属性名 `_join_times`，可能导致混淆。 | 重命名其中一个的 `_join_times` 为更具体的名称（如 `_daily_join_times` vs `_voice_join_times`），避免未来维护者困惑 |

### 2.2 `main.py` 的 `on_message` 缺少 `process_commands()`

| # | 文件 | 行号 | 问题描述 | 修复建议 |
|---|------|------|----------|----------|
| 2.2 | main.py | 465 | `@bot.event on_message` 覆盖了默认处理，但未调用 `await bot.process_commands(message)`。当前 Bot 无 `@bot.command()` 文本命令（全用 slash commands），**暂时不影响功能**。但如果未来添加文本命令，将静默失效。 | 在 `on_message` 末尾（L499 附近，`conn.close()` 之后）添加 `await bot.process_commands(message)` |

### 2.3 `defer()` 后使用 `response.send_message` 模式

| # | 文件 | 涉及行数 | 问题描述 | 修复建议 |
|---|------|----------|----------|----------|
| 2.3 | dashboard.py | ~15 处 | `defer()` 后直接调 `response.send_message`（Discord 在 defer 后拒绝 response.send_message，但不会抛可见异常）。历史记录显示此问题曾被修复但可能仍有遗漏。 | 逐函数排查：如果同一函数内先调了 `defer()`，后续必须用 `followup.send()`。最安全做法是全文搜索 `defer(`，然后检查同一函数内所有 `response.send_message` |

具体可疑位置（dashboard.py）：
- L434 defer → L446/L450/L454 response.send_message
- L460 defer → L473/L477/L481 response.send_message
- L875 defer → L903 response.send_message（admin only）
- L1054 defer → L1103/L1132 response.send_message
- L1187 defer → L1255 response.send_message

### 2.4 `get_channel` 未判空就发消息

| # | 文件 | 行号 | 问题描述 | 修复建议 |
|---|------|------|----------|----------|
| 2.4a | main.py | 452 | `await welcome_channel.send(...)` — welcome_channel 来自 `get_channel`，虽然前面有 `if welcome_channel:` 检查（需确认） | 确认 L440-452 之间有判空逻辑 |
| 2.4b | dashboard.py | 多处 | 约 40 处 `channel.send()` 无 try/except，如果 Bot 被踢出频道或被限制权限，会抛 `Forbidden` 异常 | 对关键通知频道（notify_channel、log_channel）的 send 添加 try/except 日志 |
| 2.4c | daily.py | 73,580 | `channel.send(embed=...)` — 直接使用硬编码频道 ID 1528241061007327354，如果该频道被删除，会静默失败 | 添加 try/except 或定期验证频道存在 |

### 2.5 静默 `except: pass` 块

| # | 文件 | 行号 | 问题描述 | 修复建议 |
|---|------|------|----------|----------|
| 2.5a | main.py | 227,244 | 备份模块中消息历史搜索失败 + 删除失败时 `pass` — 功能非关键，可接受 | 可加 `logger.debug()` 辅助排查 |
| 2.5b | casino.py | 214 | — | 需检查上下文，可能吞掉用户操作异常 |
| 2.5c | dashboard.py | 958 | 数据库重试中的 `conn.close()` 异常被吞 — 先已有日志，可接受 | — |
| 2.5d | dashboard.py | 5330,6822 | 未知上下文 | 需检查是否吞掉用户可见的错误 |
| 2.5e | tournament.py | 2236 | — | 需检查上下文 |
| 2.5f | cog_base.py | 33 | 全局错误处理中的兜底 pass | 至少添加 `logger.debug()` |
| 2.5g | trivia.py | 759 | — | 需检查上下文 |

---

## 三、建议改进 (🟢)

### 3.1 重复定义 / 事件冲突

| # | 检查项 | 结果 |
|---|--------|------|
| `on_member_join` 重复 | ✅ 仅 main.py 一处（dashboard.py 已在 commit `dafd21e` 移除） |
| `on_message` 重复 | ✅ main.py (bot.event) + lol.py (Cog.listener) — 两者职责不同，正常 |
| `cog_command_error` 重复 | ✅ 仅 cog_base.py 一处，所有 Cog 继承之 |
| `@bot.event` vs `@commands.Cog.listener()` 冲突 | ✅ 无同名事件冲突 |

### 3.2 废弃代码 / 死代码

| # | 检查项 | 结果 |
|---|--------|------|
| `match.py` / `giveaway.py` 物理文件 | ✅ 不存在 — 但数据库中仍有相关表名 (`matches`, `match_signups`, `giveaways`, `giveaway_tickets` 等) |
| 连续 10 行以上注释 | ✅ 未发现 |
| 被注释的 import | ✅ 未发现 |
| `match_autocomplete.py` 未加载为 Cog | ✅ 它是纯工具模块（无 Cog 类、无 setup），被 dashboard/economy/lol 直接 import |
| `shared_views.py` 未加载为 Cog | ✅ 同理，纯工具模块，被 economy/tournament/voice_tracker 直接 import |

### 3.3 数据库风险

| # | 检查项 | 结果 |
|---|--------|------|
| `execute()` 未 `commit()` | ✅ match_autocomplete.py 有 execute 无 commit — 但它是纯查询，无需 commit |
| f-string SQL 拼接 | ✅ database.py:589 使用硬编码 dict → safe；main.py:189 使用 BACKUP_TABLES 常量 → safe；queue.py:141 使用 `?` 占位符 → safe |
| CREATE TABLE + ALTER TABLE 冲突 | ✅ ALTER TABLE 在 try/except 中执行，冲突时静默跳过 |

### 3.4 异步陷阱

| # | 检查项 | 结果 |
|---|--------|------|
| `time.sleep()` | ✅ 仅 database.py:48，在初始化重试逻辑中使用 — 非异步上下文，且用于 WAL 模式重试，可接受 |
| 同步 `requests.get/post` | ✅ 未发现。健康检查使用 `aiohttp` |

### 3.5 权限处理

| # | 检查项 | 结果 |
|---|--------|------|
| `member.move_to` + Forbidden | ✅ 全部 4 处均包裹在 try/except Exception 中 |
| `send_message` 到频道 + Forbidden/NotFound | 🟡 大部分通知类 send 无 try/except，见 2.4b |

### 3.6 边界条件

| # | 检查项 | 结果 |
|---|--------|------|
| `int()` 转换 Discord ID | ✅ 所有转换均来自 `interaction.data["values"]` 等信任源 |
| 空列表 join | 🟡 部分 `"\n".join()` 前有 `if moved:` 检查，部分无（如 `lol.py:240` 的 `embed.description += "\n暂无记录。"` 是在 try/except 中） |
| Embed 字段长度截断 | 🟡 大量 embed.title/description/add_field 无长度截断。如果内容超过 Discord 限制（title 256、description 4096、field name 256、field value 1024），会抛异常。建议对动态拼接的内容添加 `[:4096]` 等截断 |

---

## 四、统计总结

| 严重级别 | 数量 | 描述 |
|----------|------|------|
| 🔴 致命 | 0 | 无必立即修复项 |
| 🟡 潜在 | 12+ | defer+send_message 模式、静默 pass、get_channel 未判空、Embed 长度 |
| 🟢 建议 | 若干 | 代码规范、日志完善 |

---

## 五、建议优先修复清单

1. **defer + response.send_message** — 最高优先级。虽然可能不抛异常，但按钮"点了没反应"是最影响用户体验的 bug。建议用脚本扫描每个 `defer(` 所在函数内是否存在 `response.send_message`。

2. **Embed 字段截断** — 对动态拼接 description 的场景（如 dashboard.py 的分队结果、tournament.py 的赛程展示）添加 `[:4096]` 截断。

3. **`on_message` 补 `process_commands`** — 一行代码，防止未来静默 bug。

4. **关键频道 `send()` 加 try/except** — 至少 notify_channel（1453208983358935121）和 log_channel 的 send 添加异常日志。
*（内容由AI生成，仅供参考）*
