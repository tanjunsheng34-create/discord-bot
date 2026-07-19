# Discord 频道架构审计报告

> **仓库**: discord-bot  |  **扫描范围**: 18 个 `.py` 文件  |  **日期**: 2026-07-19

---

## 一、硬编码频道 ID 清单

Bot 代码中目前有 **3 个** 硬编码 Discord 频道 ID（数字 snowflake），全部集中在 `cogs/dashboard.py`：

| # | 频道 ID | 变量名 | 用途 | 出现位置 |
|---|---------|--------|------|----------|
| 1 | `1438050912814895186` | `VA_CHANNEL_ID` | **A 队语音频道** — 比赛时把蓝队/A 队成员移入此语音频道 | `dashboard.py:1224`（旧 View）<br>`dashboard.py:1261`（`VoicePullView` 类属性） |
| 2 | `1437626921394372658` | `VB_CHANNEL_ID` | **B 队语音频道** — 比赛时把红队/B 队成员移入此语音频道 | `dashboard.py:1245`（旧 View）<br>`dashboard.py:1262`（`VoicePullView` 类属性） |
| 3 | `1462616745197043722` | `NOTIFY_CHANNEL_ID` | **语音拉入通知频道** — 发出拉入成功/失败的消息 | `dashboard.py:1225,1246,1336,1356`<br>`dashboard.py:1263`（`VoicePullView` 类属性） |

> **风险**：这三个 ID 直接写死在 Python 代码中，更换频道必须改代码并重新部署，且无法跨服务器迁移。

---

## 二、环境变量 / 数据库中的频道配置

### 2.1 环境变量

| 变量名 | 定义位置 | 用途 | 缺失 |
|--------|----------|------|------|
| `BACKUP_CHANNEL_ID` | `config.py:10` | 自动备份目标频道，Bot 将数据库 JSON 发送到此频道 | `.env.example` 中未列出。用户创建 `.env` 时容易遗漏 |

`config.py` 还包含两个关联配置：

```python
BACKUP_INTERVAL = int(os.getenv("BACKUP_INTERVAL", "300"))  # 备份间隔（秒）
BACKUP_TABLES = ["users", "voice_tracker", "daily_checkin", "giveaway", "giveaway_entries", "user_inventory"]
```

### 2.2 数据库持久化频道

| 表名 | 字段 | 用途 |
|------|------|------|
| `mmr_board` | `channel_id`, `message_id` | MMR 排行榜频道（`/gmpt-mmr-board` 设置后持久化） |
| `giveaway` | `channel_id`, `message_id` | 每个抽奖活动的目标频道和消息 ID |
| `match_views` | `channel_id` | 比赛控制面板所在频道（`save_match_view_state`） |

### 2.3 命令参数（运行时指定，不持久化）

| 命令 | 频道参数 | 说明 |
|------|----------|------|
| `/announce` | `channel` 参数（默认当前频道） | 发送公告 |
| `/gmpt-mmr-board` | `channel` 参数 | 设置 MMR 实时排行榜 |
| `/gmpt-autozone` | 始终对当前频道生效 | 切换自动开黑检测 |
| `/gmpt-zone` | 在当前频道下创建子区 | 创建临时讨论频道 |
| Queue 匹配 | `interaction.channel` | 匹配成功通知、MatchView 发送到发起命令的频道 |

---

## 三、当前频道架构总览

```
📁 Discord Server (实际服务器)
│
├── 📁 TEMP ZONES (分类 — Bot 自动创建)
│   ├── lfg-{用户名}          (自动检测开黑时创建，5 分钟后删除)
│   └── Summoner's Rift / S/D / Flex / ARAM  (临时子区，N 分钟后删除)
│
├── 🔈 A 队语音频道  (ID: 1438050912814895186)  ─┐
├── 🔈 B 队语音频道  (ID: 1437626921394372658)  ─┤ 语音拉入系统
├── 💬 语音通知频道  (ID: 1462616745197043722)  ─┘
│
├── 💬 备份频道      (环境变量 BACKUP_CHANNEL_ID)  → 自动备份 JSON
├── 💬 MMR 排行榜频道 (DB mmr_board.channel_id)   → 实时排行榜
├── 💬 公告频道      (命令参数指定)                 → 公告 Embed
│
├── 💬 开黑大厅 / 常规聊天频道  → /gmpt-autozone 启用后自动检测 LFG
└── 💬 抽奖通道               → giveaway.channel_id（DB 记录）
```

### Bot 管理的频道类型总结

| 类型 | 数量 | 创建方式 | 生命周期 |
|------|------|----------|----------|
| 固定语音频道（VA/VB） | 2 | 硬编码 ID，手动创建 | 永久 |
| 固定通知频道 | 1 | 硬编码 ID，手动创建 | 永久 |
| 备份频道 | 1 | env 变量，手动创建 | 永久 |
| MMR 排行榜频道 | 1 | 命令指定 | 永久 |
| 自动 LFG 临时文本频道 | 动态 | Bot 自动创建 | 5 分钟后自动删除 |
| `/gmpt-zone` 临时子区 | 动态 | 命令创建 | N 分钟后自动删除 |
| 抽奖频道 | 动态 | `/gmpt-giveaway` 命令 | 活动结束后归档 |

---

## 四、LoL 社区 Discord 频道架构最佳实践参考

对于 LoL 社区 / 战队服务器的典型频道结构：

### 4.1 信息区（只读/公告）
```
📌 #welcome          — 欢迎 + 规则 + 自我介绍
📌 #announcements    — 赛事公告、活动通知
📌 #patch-notes      — 版本更新 / Riot 新闻（可由 Bot 自动推送）
📌 #roles            — 身份组自选（S/D / Flex / ARAM / TFT）
```

### 4.2 社交区
```
💬 #general-chat     — 综合聊天
💬 #lfg              — 组队找人（自动检测 zone）
💬 #memes-clips      — 精彩操作 / 表情包
```

### 4.3 竞技区
```
🏆 #match-results    — 比赛结算 / 战绩推送
🏆 #tournament-info  — 锦标赛信息
📊 #mmr-leaderboard  — 实时 MMR 排行榜（Bot 维护）
🔈 Team A VC         — A 队语音（Bot 拉入）
🔈 Team B VC         — B 队语音（Bot 拉入）
```

### 4.4 Bot 管理区
```
🤖 #bot-logs         — 备份通知 / 错误日志
🤖 #temp-zones       — 临时频道根分类
```

---

## 五、优化建议

### 5.1 缺少的实用频道（建议新增）

| 建议频道 | 理由 | Bot 支持现状 |
|----------|------|-------------|
| **#announcements** | 集中公告 / 赛事通知 | `/announce` 命令已支持，只需指定频道 |
| **#lfg** | 永久开黑大厅，取代分散在多个频道的 LFG 消息 | `/gmpt-autozone` 在此频道开启即可 |
| **#match-results** | 比赛结算结果集中展示 | 目前 `VoteView` 结算后无通知，需新增 |
| **#patch-notes** | 版本更新自动推送（Riot API） | 目前无此功能，可基于 DataDragon / Riot API 添加 |
| **#welcome** | 新成员引导 + 规则 | 无内置功能，需手动或用第三方 Bot |

### 5.2 可合并 / 精简的频道

| 当前 | 建议 | 理由 |
|------|------|------|
| `NOTIFY_CHANNEL_ID`（ID 硬编码） | 合并到 `#match-results` 或 `#bot-logs` | 语音拉入通知属于比赛流程的一部分，可与比赛结果合并 |
| `BACKUP_CHANNEL_ID` + MMR 排行榜 | 保持独立，但将 BACKUP 改为 `#bot-logs` | 备份是低频操作，放入 Bot 管理频道更合理 |
| 两个独立的 VA / VB 语音频道 | 保持独立 | LoL 比赛两队必须隔离语音，不可合并 |

### 5.3 Bot 自动管理频道的优化

#### 5.3.1 硬编码 ID 迁移（P0 — 必须修复）

将 `dashboard.py` 中三个硬编码 ID 改为环境变量：

```python
# dashboard.py — VoicePullView class
VA_CHANNEL_ID = int(os.getenv("VA_CHANNEL_ID", "0"))
VB_CHANNEL_ID = int(os.getenv("VB_CHANNEL_ID", "0"))
NOTIFY_CHANNEL_ID = int(os.getenv("NOTIFY_CHANNEL_ID", "0"))
```

同时清理旧 `MatchView` 中重复硬编码的 ID（`dashboard.py:1224-1246` 行）。

#### 5.3.2 `.env.example` 完善（P0）

当前 `.env.example` 只有 3 行，缺少所有频道配置。建议补全：

```env
DISCORD_TOKEN=你的Bot_Token填这里
BACKUP_CHANNEL_ID=           # 备份频道 ID（必填）
VA_CHANNEL_ID=               # A 队语音频道 ID
VB_CHANNEL_ID=               # B 队语音频道 ID
NOTIFY_CHANNEL_ID=           # 语音拉入通知频道 ID
RIOT_API_KEY=                # Riot API Key（可选）
```

#### 5.3.3 自动 Zone 系统优化

| 问题 | 当前状态 | 建议 |
|------|----------|------|
| `watch_channels` 掉电丢失 | 内存 `set()`，重启后清空 | 持久化到 DB 表（如 `auto_zone_channels`），启动时加载 |
| 5 分钟删除太短 | 固定 300s 硬编码 | 改为可配置（环境变量 `LFG_CHANNEL_TTL`，默认 600s） |
| 频道名特殊字符处理不完整 | 仅替换单引号 `'` | 用正则替换所有 Discord 非法字符 `[^a-z0-9\-_]` |
| 重名冲突 | 无处理 | 加数字后缀：`lfg-username-2` |
| TEMP ZONES 空分类残留 | 不清理 | 日活低时定期检查并删除空分类 |
| 无「延长」功能 | 无 | 添加 `/gmpt-zone-extend` 命令刷新倒计时 |

#### 5.3.4 Voice Pull（语音拉入）优化

| 问题 | 建议 |
|------|------|
| 两队语音频道 ID 与通知频道 ID 混在同一个 View 类 | 提取到 `config.py` 统一管理 |
| 通知消息写到 NOTIFY_CHANNEL，但比赛交互在另一个频道 | 通知中附带原比赛频道跳转链接，方便用户定位 |
| 无权限回退 | 当 VA/VB 频道不存在或被删除时，按钮无反馈 → 已处理（返回错误行）但可以改为自动创建频道 |

#### 5.3.5 新增功能建议

| 建议 | 说明 |
|------|------|
| **赛后自动通知** | `VoteView` 结算完成后，自动发送结果到 `#match-results` |
| **补位提醒** | 当 LFG 频道有人发消息但 2 分钟内无人回应，Bot 可 @对应模式身份组 |
| **频道清理定时任务** | 每日凌晨检查 TEMP ZONES 下是否有遗留未删除的临时频道 |
| **语音频道自动创建** | 当 VA/VB 频道不存在时，`VoicePullView` 自动创建（而非报错） |

---

## 六、优先级排序

| 优先级 | 条目 | 影响 |
|--------|------|------|
| **P0** | 硬编码 ID → 环境变量 | 跨服移植、配置变更不重启 |
| **P0** | `.env.example` 补全 | 新用户上手 |
| **P0** | `watch_channels` 持久化 | 重启不丢失自动检测配置 |
| **P1** | 临时频道特殊字符 + 重名处理 | 避免创建失败 |
| **P1** | LFG 频道 TTL 可配置 | 灵活性 |
| **P2** | 赛后自动通知 `#match-results` | 社区体验 |
| **P2** | 补位提醒 | 活跃度 |
| **P3** | 版本更新推送 `#patch-notes` | 社区价值 |
| **P3** | 空分类清理定时任务 | 运维卫生 |

---

## 七、附录：完整频道引用索引

| 文件 | 行号 | 引用类型 | 详情 |
|------|------|----------|------|
| `config.py` | 10 | env 变量 | `BACKUP_CHANNEL_ID` |
| `main.py` | 120-155 | 函数 | `_get_backup_channel()` — 解析并验证备份频道 |
| `main.py` | 185-212 | 函数 | 自动备份/恢复流程 |
| `dashboard.py` | 1224 | 硬编码 | `1438050912814895186` — 旧 View 中 VA |
| `dashboard.py` | 1245 | 硬编码 | `1437626921394372658` — 旧 View 中 VB |
| `dashboard.py` | 1225,1246 | 硬编码 | `1462616745197043722` — 旧 View 中通知频道 |
| `dashboard.py` | 1261-1263 | 类属性 | `VoicePullView` 的三个硬编码 ID |
| `dashboard.py` | 1336,1356 | 使用 | `VoicePullView` 通知频道发送 |
| `dashboard.py` | 3356 | DB 读取 | `mmr_board` 排行榜刷新 |
| `dashboard.py` | 4697 | DB 读取 | MMR board 旧消息清理 |
| `lol.py` | 346,378 | 内存 set | `watch_channels` 自动检测开关 |
| `lol.py` | 401-429 | 动态创建 | 自动 LFG 临时频道 `lfg-{name}` |
| `lol.py` | 432-443 | 命令 | `/gmpt-autozone` 切换自动检测 |
| `lol.py` | 1048-1098 | 命令 | `/gmpt-zone` 创建临时子区 |
| `giveaway.py` | 64,68 | DB 写入 | 抽奖创建时记录 `channel_id` |
| `giveaway.py` | 283,392 | DB 读取 | 抽奖结束时获取频道 |
| `queue.py` | 207 | DB 写入 | 匹配成功写入 `channel_id` |
| `announce.py` | 18-25 | 参数 | 公告目标频道 |
