**🎮 GMPT Bot — 更新日志 & 使用指南**

> 面向社区玩家的完整参考手册 | 最后更新：2026-07-19

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**第一部分：更新日志**

按时间线排列所有已实现的功能改动。

**MMR 排位系统**
基础 MMR 1000 分，比赛结算 ±25 分（胜者+25 / 败者-25）。8 个段位覆盖 Iron（0-799）到 Challenger（2000+）：Iron / Bronze / Silver / Gold / Platinum / Diamond / Master / Challenger。支持连胜奖励、MVP 额外加分、下狗补偿（低段位击败高段位获得额外 MMR）。

**Dashboard 统一控制面板（v3.0）**
全新 Select Menu 交互面板，`/gmpt-dashboard` 一站式操作：查看个人数据、MMR 排行榜、比赛面板、背包、商店、成就、每日签到。淘汰了旧版多命令分散操作，一个面板解决所有日常需求。

**语音拉入系统（Voice Pull）**
比赛分队后，一键将 A/B 两队成员拉入各自语音频道。面板提供「拉 A 队入语音」「拉 B 队入语音」两个独立按钮，拉入结果自动通知到指定频道。

**赛事系统（Tournament）**
完整锦标赛流程：创建赛事（支持段位限制）→ 报名参赛（含替补）→ 开始比赛（自动生成对阵图）→ 上报比分 → 自动晋级。包含 Draft（队长选秀）系统，支持按钮交互式选人。

**经济系统（Economy）**
金币系统 + 每日签到（连续签到阶梯奖励）+ 赠送金币 + 交易记录查询。完整商店系统：14 种道具分 4 大类。成就系统：29 个成就（含 6 个隐藏成就），解锁可获得金币奖励。

**商店道具（14 种）**

| 分类 | 道具 | 价格 | 效果 |
|------|------|------|------|
| ⚔️ 比赛道具 | 双倍或清零 | 300 | 随机翻倍或清零余额 |
| ⚔️ 比赛道具 | 比赛复活卡 | 3000 | 淘汰后可复活一次 |
| 🛡️ 防御道具 | 隐身卡 | 1200 | 24h 排行榜隐藏名字 |
| 💰 加成道具 | MMR保护卡 | 500 | 输了不扣 MMR |
| 💰 加成道具 | 双倍MMR卡 | 600 | 赢了 MMR 翻倍 |
| 💰 加成道具 | 双倍积分卡 | 400 | 下一场积分双倍 |
| 💰 加成道具 | 偷金币卡 | 350 | 结算时偷对手 30 coins |
| 💰 加成道具 | 经验加成卡 | 800 | 下一场经验+50% |
| 🎭 社交道具 | 队长通行证 | 500 | 自定义对战担任队长 |
| 🎭 社交道具 | 个人资料头衔 | 1000 | 余额页显示自定义头衔 |
| 🎭 社交道具 | 昵称炸弹 | 1500 | 强制修改选手昵称 24h |
| 🎭 社交道具 | 自定义颜色角色 | 2000 | 获得自定义颜色专属角色 |
| 🎭 社交道具 | 改名卡 | 2500 | 修改游戏昵称 |
| 🎭 社交道具 | 全服广播喇叭 | 5000 | 全服醒目公告 |
| 🎭 社交道具 | 至尊传说称号 | 100000 | 传奇称号 + 全服广播 |

**Giveaway 抽奖系统**
完整抽奖流程：创建抽奖（指定奖品/时长/中奖人数）→ 点击按钮参赛 → 自动/手动开奖。支持重新抽奖、列出所有进行中抽奖。抽奖数据持久化，Bot 重启不丢失。

**选路比赛（Role-Pick）**
创建比赛时支持按位置报名：Top / JG / Mid / ADC / Support。系统自动验证位置不重复，分队时按位置平衡分配。支持搭配锦标赛和 Queue 排队使用。

**竞猜投票（Vote System）**
比赛面板内置投票功能：观众可对比赛结果进行竞猜投票（A 队胜 / B 队胜），结算时自动公布投票结果。

**Queue 排队匹配**
自动化匹配系统：`/gmpt-queue` 进入匹配池（按位置 Top/JG/Mid/ADC/Support/Any）→ 满 10 人自动匹配 → 自动分队（按位置平衡分配蓝红队）→ 自动创建比赛面板。`/gmpt-leave-queue` 退池，`/gmpt-queue-status` 查看当前排队人数。

**MVP 投票**
比赛结算后，参赛 10 人自动获得 MVP 投票资格。每人一票，投票结束后自动公布 MVP 获得者。MVP 获得额外 MMR 加分和成就进度。

**Betting 下注**
`/gmpt-bet` 对活跃比赛下注金币（选 A 队或 B 队），比赛结算时自动结算：猜对获得赔率奖金，猜错扣除下注金额。`/gmpt-bet-stats` 查看个人下注历史和胜率统计。

**优化修复**
- MMR 排行榜持久化（`mmr_board` 表 + `/gmpt-mmr-board` 实时刷新）
- MatchView 状态持久化（Bot 重启后报名按钮不失效）
- 数据库自动备份到 Discord 频道（定时 + 手动 `/gmpt-backup` / `/gmpt-restore`）
- 语音时长追踪（Voice Tracker）+ 排行榜
- Riot API 集成：查段位/战绩/当前对局（`/gmpt-profile` `/gmpt-match` `/gmpt-live`）
- 临时频道自动清理（LFG 检测 5 分钟自动删除，`/gmpt-zone` 创建临时子区）
- 锦标赛段位限制 + 替补机制
- 自定义分队（按钮拖动式交互）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**第二部分：完整命令清单**

**比赛系统**

- `/gmpt-create` — 创建新比赛（必填：`match_name` 比赛名称）
- `/gmpt-list` — 列出所有活跃比赛（分页显示）
- `/gmpt-join` — 报名参加比赛（必填：`match_id`）
- `/gmpt-players` — 查看比赛报名玩家
- `/gmpt-shuffle` — 随机分成蓝红两队
- `/gmpt-custom-team` — 自定义分队（按钮拖动式交互）
- `/gmpt-settle` — 结算比赛积分（选择获胜方 + MVP）
- `/gmpt-kick` — 踢出报名玩家
- `/gmpt-cancel` — 取消比赛
- `/gmpt-history` — 查看历史比赛记录
- `/gmpt-stream` — 分享直播链接
- `/gmpt-recover` — 恢复被误删的比赛面板

**赛事系统**

- `/gmpt-tournament create` — 创建锦标赛（设置名称/人数/段位限制）
- `/gmpt-tournament signup` — 报名参赛
- `/gmpt-tournament players` — 查看报名列表
- `/gmpt-tournament start` — 开始比赛（自动生成对阵图）
- `/gmpt-tournament bracket` — 查看对阵图
- `/gmpt-tournament report` — 上报比分（按钮交互）
- `/gmpt-tournament standings` — 查看排名
- `/gmpt-tournament list` — 赛事列表
- `/gmpt-tournament cancel` — 取消赛事
- `/gmpt-tournament draft-setup` — 队长选秀设置（管理员）
- `/gmpt-tournament draft-status` — 查看选秀状态
- `/gmpt-tournament draft-roster` — 查看选秀最终名单
- `/gmpt-tournament draft-cancel` — 取消选秀

**经济系统**

- `/gmpt-balance` — 查看金币余额
- `/gmpt-daily` — 每日签到（连续签到有阶梯奖励）
- `/gmpt-gift` — 赠送金币给其他玩家（`player` + `amount`）
- `/gmpt-transactions` — 查看交易记录（`count` 1-20）
- `/gmpt-shop` — 打开商店（按分类浏览商品）
- `/gmpt-buy` — 购买商店物品（`item_id`）
- `/gmpt-inventory` — 查看背包物品
- `/gmpt-use` — 使用背包物品（`item_id`）
- `/gmpt-achievements` — 成就列表（分页 + 筛选已解锁/未解锁）
- `/gmpt-allplayers` — 列出所有已报名玩家

**LoL 查询**

- `/gmpt-profile` — 查询召唤师段位（`summoner_name` Riot ID）
- `/gmpt-match` — 查看最近战绩（`match_id` 可选查看详情）
- `/gmpt-live` — 查看当前对局实时信息
- `/gmpt-rank` — 社区排行榜（MMR + 段位）
- `/gmpt-ranks` — 已报名玩家的 League 段位一览
- `/gmpt-link-riot` — 关联你的 Riot 账号（`name` + `tag`）
- `/gmpt-riot-status` — 检测 Riot API Key 是否有效

**语音 & LFG**

- `/gmpt-voicetime` — 查看语音时长统计
- `/gmpt-voice-leaderboard` — 语音时长排行榜
- `/gmpt-autozone` — 开启/关闭当前频道自动开黑检测（检测到找人消息自动创建临时频道）
- `/gmpt-zone` — 创建临时讨论子区（`topics` 逗号分隔，`minutes` 自动删除时间）

**Giveaway 抽奖**

- `/gmpt-giveaway create` — 创建抽奖（`prize` / `duration` / `winners`）
- `/gmpt-giveaway end` — 手动结束抽奖并开奖
- `/gmpt-giveaway reroll` — 重新抽奖（从已有参赛者中重抽）
- `/gmpt-giveaway list` — 列出所有进行中抽奖

**Queue 排队 & Betting 下注**

- `/gmpt-queue` — 进入匹配池（`position` Top/JG/Mid/ADC/Support/Any）
- `/gmpt-leave-queue` — 退出匹配池
- `/gmpt-queue-status` — 查看匹配池状态（各位置人数）
- `/gmpt-bet` — 对比赛下注（`match_id` + 选择队伍 + `amount`）
- `/gmpt-bet-stats` — 查看下注历史和胜率

**管理 & 面板**

- `/gmpt-dashboard` — 打开统一控制面板（推荐！一个面板搞定日常操作）
- `/gmpt-stats` — 查看玩家 MMR/段位/胜负统计
- `/gmpt-leaderboard-mmr` — 查看 MMR 排行榜
- `/gmpt-mmr-board` — 发送实时 MMR 排行榜到频道（自动刷新）
- `/gmpt-mmr-reset` — 重置 MMR（管理员，可选 @玩家 或 全部重置）
- `/gmpt-backup` — 手动导出全量数据库备份（管理员）
- `/gmpt-restore` — 从备份文件恢复数据（管理员）
- `/gmpt-add-coins` — 给玩家加减金币（管理员）
- `/gmpt-admin-coins` — 管理员金币管理面板
- `/gmpt-shop-edit` — 修改商店道具价格（管理员）
- `/announce` — 发送公告 Embed（`title` + `content`，可指定频道）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**第三部分：常用流程教学**

**如何创建一场比赛并结算**

1. 在任意文字频道输入 `/gmpt-create`，填写比赛名称（如 "周五内战局"）
2. Bot 会发送比赛面板到当前频道，包含报名/分队/结算按钮
3. 参赛玩家点击「报名」按钮加入比赛
4. 人满后，管理员点击「分队」→ 系统自动按 MMR 平衡分出蓝队 🔵 和红队 🔴
5. 点击「拉 A 队入语音」和「拉 B 队入语音」，Bot 自动将两队移入各自语音频道
6. 比赛结束后，管理员点击「结算」→ 选择获胜方 → 选择 MVP → 系统自动计算 MMR ±25 分
7. Bot 同时结算所有下注（Betting）、成就进度、MMR 排行榜更新

**如何使用排队匹配（Queue）**

1. 输入 `/gmpt-queue` 选择你的位置（Top / JG / Mid / ADC / Support / Any）
2. 等待其他玩家加入匹配池，用 `/gmpt-queue-status` 可随时查看各位置人数
3. 满 10 人后系统自动匹配，按位置平衡分蓝红两队
4. Bot 自动创建比赛面板，无需手动 `/gmpt-create`
5. 想退出排队：`/gmpt-leave-queue`

**如何创建锦标赛**

1. 管理员输入 `/gmpt-tournament create`，设置名称、最大人数、段位限制（可选）
2. 玩家用 `/gmpt-tournament signup` 报名（可选填 `is_sub` 作为替补）
3. 管理员 `/gmpt-tournament start` 开始比赛，系统自动生成对阵图
4. `/gmpt-tournament bracket` 查看对阵图
5. 每轮结束后，参赛者用 `/gmpt-tournament report` 上报比分
6. 系统自动晋级胜者，`/gmpt-tournament standings` 查看实时排名
7. 可选：`/gmpt-tournament draft-setup` 开启队长选秀模式

**如何使用商店和背包**

1. 输入 `/gmpt-dashboard` 打开控制面板，点击「商店」按钮 — 或直接 `/gmpt-shop`
2. 商店按分类展示所有道具：⚔️比赛道具 / 🛡️防御道具 / 💰加成道具 / 🎭社交道具
3. 记住想买的道具 ID，用 `/gmpt-buy item_id:<ID>` 购买
4. `/gmpt-inventory` 查看背包中的道具
5. 使用道具：`/gmpt-use item_id:<ID>`（MMR保护卡、双倍MMR卡等自动在下一场比赛生效）
6. 赚金币方式：比赛获胜 +150 / 参赛 +50 / 每日签到 / 成就奖励 / 他人赠送

**如何下注**

1. 先确认比赛 ID：`/gmpt-list` 查看活跃比赛，记住 `match_id`
2. 输入 `/gmpt-bet match_id:<ID>`，选择下注 A 队 🔵 或 B 队 🔴，填写金额
3. 比赛结算时自动判定：猜对 → 按赔率赢取金币；猜错 → 扣除下注金额
4. `/gmpt-bet-stats` 查看你的下注战绩和胜率

**如何使用 Dashboard 面板（推荐）**

1. 输入 `/gmpt-dashboard`，Bot 在当前频道发送统一控制面板
2. 面板提供下拉菜单（Select Menu）选择操作：
   - **📊 My Stats** — 个人战绩/MMR/段位
   - **🏆 Leaderboard** — MMR 排行榜
   - **⚔️ Matches** — 活跃比赛列表
   - **🎒 Inventory** — 背包物品
   - **🛒 Shop** — 商店
   - **⭐ Achievements** — 成就进度
   - **📅 Daily** — 每日签到
3. 一个面板覆盖 90% 日常需求，无需记忆多条命令

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**快速参考卡**

| 我想…… | 命令 |
|--------|------|
| 创建比赛 | `/gmpt-create` |
| 报名比赛 | `/gmpt-join` 或点击面板按钮 |
| 自动匹配 | `/gmpt-queue position:Any` |
| 查看排行 | `/gmpt-leaderboard-mmr` |
| 每日签到 | `/gmpt-daily` |
| 逛商店 | `/gmpt-shop` |
| 送金币 | `/gmpt-gift player:@朋友 amount:100` |
| 查段位 | `/gmpt-profile summoner_name:Hide on bush` |
| 下注 | `/gmpt-bet` |
| 抽奖 | `/gmpt-giveaway create` |
| 一键面板 | `/gmpt-dashboard` |
