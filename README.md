# GMPT Discord Bot

## Railway Deployment — Database Persistence

Railway 免费计划每次部署会重建容器，SQLite 文件丢失。需要挂载 Volume 持久化数据库。

### 1. 添加 Railway Volume

1. 进入 Railway 项目 Dashboard → 点击你的 Service
2. 右侧面板 → **Volumes** → **Add Volume**
3. 配置：
   - **Mount Path**: `/data`
   - **Name**: `gmpt-data`（随意取名）
   - **Size**: 1 GB（免费额度内）
4. 点击 **Add Volume**，Railway 会自动重新部署

### 2. 环境变量

在 Railway 项目的 **Variables** 中确认：
- `DISCORD_TOKEN` — 已设置
- `DB_PATH` — 设为 `/data/gmpt.db`（Volume 内路径）

### 3. 验证

部署后，多次重新部署，数据应保留。如果 Volume 出问题，使用下方的备份/恢复命令：

## 备份 & 恢复 (Backup & Restore)

### `/gmpt-backup` (管理员)
导出所有数据（users / voice_tracker / daily_checkin / giveaway / user_inventory）到 JSON 文件，私聊发送。

### `/gmpt-restore` (管理员)
从 JSON 备份文件恢复数据。用法：`/gmpt-restore` 并上传 `gmpt_backup.json` 附件。

建议定期备份：每次重大改动前后手动执行 `/gmpt-backup` 保存到本地。
