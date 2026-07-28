# GMPT Bot — 多实例共享数据库部署指南

## 架构概述

5 个 Bot 角色（full / economy / community / arena / gambling）运行在**同一个容器**中，通过 SQLite WAL 模式共享一个 `data.db`，实现金币统一。

```
┌──────────────────────────────┐
│      Pterodactyl 容器        │
│                              │
│  main.py                     │
│    ├─ GMPTBot(full)          │
│    ├─ GMPTBot(economy) ─┐    │
│    ├─ GMPTBot(community) │    │
│    ├─ GMPTBot(arena)    ├── data.db (WAL mode)
│    └─ GMPTBot(gambling) ─┘    │
│                              │
└──────────────────────────────┘
```

## 部署步骤

### 1. 创建 5 个 Discord Bot Application

在 [Discord Developer Portal](https://discord.com/developers/applications) 创建 5 个 Application，每个获取一个 Bot Token。

### 2. 设置环境变量

在 Pterodactyl 面板中设置以下环境变量：

| 环境变量 | 说明 |
|---|---|
| `TOKEN_FULL` | Full 角色 Bot Token |
| `TOKEN_ECONOMY` | Economy 角色 Bot Token |
| `TOKEN_COMMUNITY` | Community 角色 Bot Token |
| `TOKEN_ARENA` | Arena 角色 Bot Token |
| `TOKEN_GAMBLING` | Gambling 角色 Bot Token |
| `DB_PATH` | 数据库路径（默认 `data.db`） |
| `BACKUP_CHANNEL_ID` | 备份频道 ID |
| `BACKUP_INTERVAL` | 备份间隔（秒，默认 300） |
| `AUTO_RESTORE` | 启动时自动恢复（`1` 开启） |
| `PORT` | 健康检查端口（默认 8080） |

**注意**：不要设置 `BOT_ROLE` 环境变量，留空则为多实例模式。

### 3. 启动命令

保持与单实例模式相同：

```
python main.py
```

### 4. 首次启动：数据库合并

首次启动时，如果检测到 `data_full.db`、`data_economy.db` 等同目录下的旧数据库文件，会自动合并到 `data.db`：

- `users.score`（余额）：同一用户累加
- `user_inventory.quantity`（背包物品）：同一用户+物品累加
- `player_skills`（技能）：同一用户+技能保留最高等级
- 其他表（transactions、voice_tracker 等）：INSERT OR IGNORE 合并

合并完成后，旧 `data*.db` 文件自动重命名为 `.bak` 后缀。

### 5. 验证

启动后日志应显示：

```
多实例模式启动中...
启动 full 实例...
启动 economy 实例...
...
Bot online: GMPT Bot#xxxx (role=full)
Bot online: GMPT Bot#xxxx (role=economy)
Synced N commands to GuildName (id)
```

## 向后兼容

设置 `BOT_ROLE=full` + `DISCORD_TOKEN=xxx` 可回退到单实例模式，与旧部署完全一致。

## 注意事项

- SQLite WAL 模式下写入是串行的，但对于 Discord Bot 的命令频率（非高频交易系统）完全足够
- 内存占用约为单实例的 5 倍，建议容器分配至少 512MB RAM
- 5 个 Bot 邀请到同一个 Discord 服务器时，请确保不会出现重复响应（每个角色只加载自己负责的 Cog）
- 每个 Bot 需要一个独立的 Token，不能共用
