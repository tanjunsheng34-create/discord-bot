
# 赌博资金流审计报告

## 执行时间
2026-07-29

## 总体结论
**所有赌博游戏资金流经逐一追踪，逻辑正确，无赢钱不加余额的 Bug。**

核心模式：每个游戏在命令入口处先扣款，开奖后赢时加回 `本金+利润`（net 利润），输时不额外操作。

---

## 各游戏资金流追踪

### 1. 轮盘 Roulette (`roulette_cmd` + `RouletteView`)

| 步骤 | 操作 | 代码位置 |
|------|------|---------|
| 下注扣款 | `add_coins(uid, -bet, "轮盘赌下注")` | gambling.py `roulette_cmd` L386 |
| 赢(颜色2x) | `add_coins(uid, profit=bet*odds)` → beta=2, adds bet*2 | `_play_round` L444 |
| 赢(数字36x) | `RouletteNumberModal`: `add_coins(uid, self._view.bet * 36)` | `NumberModal.on_submit` L492 |
| 输 | 无额外操作 | `_play_round` L473 |
| 平局(0押绿中0) | 36x payout | `_play_round` L450 |

**净结果**: 赢 → -bet + bet*2 = +bet (正确, 1:1 payout)；赢数字 → -bet + bet*36 = +bet*35 (正确)

✅ **无Bug**

---

### 2. 比大小 HighLow (`highlow_cmd` + `HighLowView`)

| 步骤 | 操作 | 代码位置 |
|------|------|---------|
| 下注扣款 | `add_coins(uid, -bet, "比大小下注")` | gambling.py L552 |
| 赢 | `profit = self.bet * 2`; `add_coins(uid, profit, ...)` | `_do_result` L930 |
| 输 | 无额外操作 | `_do_result` L948 |
| 平局 | `add_coins(uid, self.bet, "比大小平局退款")` | `_do_result` L922 |

**净结果**: 赢 → -bet + bet*2 = +bet (正确)；平局 → -bet + bet = 0 (正确)

✅ **无Bug**

---

### 3. 猜数字 NumberGuess (`guess_cmd` + `NumberGuessView`)

| 步骤 | 操作 | 代码位置 |
|------|------|---------|
| 下注扣款 | `add_coins(uid, -bet, "猜数字下注")` | gambling.py L641 |
| 完全猜中(10x) | `profit = int(bet * 10.0)`; `add_coins(uid, profit, ...)` | `NumberGuessModal.on_submit` L1040 |
| 差≤3(5x) | `profit = int(bet * 5.0)`; `add_coins(uid, profit, ...)` | 同上 |
| 差≤10(2x) | `profit = int(bet * 2.0)`; `add_coins(uid, profit, ...)` | 同上 |
| 机会用完(输) | 无额外操作 | 同上 L1055 |
| 提示(继续) | 无操作 | 同上 L1069 |

**净结果**: 10x → -bet + bet*10 = +bet*9 (正确)

✅ **无Bug**

---

### 4. 刮刮乐 Scratch (`_do_scratch` + `ScratchView`)

| 步骤 | 操作 | 代码位置 |
|------|------|---------|
| 下注扣款 | `add_coins(uid, -50, "刮刮乐购买")` (固定50) | gambling.py L675 |
| 中💎💎💎(500) | `add_coins(player_id, prize)` (prize=500) | `_calculate_prize` L780 |
| 中🍀🍀🍀(200) | `add_coins(player_id, prize)` (prize=200) | 同上 |
| 中⭐⭐⭐(100) | `add_coins(player_id, prize)` (prize=100) | 同上 |
| 未中 | 无额外操作 | 同上 |

**净结果**: -50+500=+450, -50+200=+150, -50+100=+50 (正确)

✅ **无Bug**

---

### 5. Crash 爆爆乐 (`crash_cmd` + `CrashView`)

| 步骤 | 操作 | 代码位置 |
|------|------|---------|
| 下注扣款 | `add_coins(uid, -bet, "Crash下注")` | gambling.py L842 |
| 提现 | `profit = int(bet * multiplier)`; `add_coins(player_id, profit, ...)` | `cashout_btn` L882 |
| 崩盘 | 无操作 | crash loop L873 |
| 自动100x提现 | `profit = int(bet * self.multiplier)`; `add_coins(...)` | crash loop L877 |

**净结果**: 提现 → -bet + bet*multiplier = bet*(multiplier-1) (正确)

✅ **无Bug**

---

### 6. Dice Duel 骰子对决 (`diceduel_cmd`)

| 步骤 | 操作 | 代码位置 |
|------|------|---------|
| 双方扣款 | `add_coins(uid, -bet, ...)`; `add_coins(oid, -bet, ...)` | gambling.py L120 |
| 赢者得奖 | `add_coins(winner_id, total_pot - fee, ...)` | gambling.py L170 |
| 平局退款 | `add_coins(uid, bet, ...)`; `add_coins(oid, bet, ...)` | gambling.py L178 |

**净结果**: 赢者 → -bet + (2*bet - fee) = +bet - fee ≈ +0.9*bet (正确含手续费)

✅ **无Bug**

---

### 7. 俄罗斯轮盘 RussianRoulette (`russian_cmd`)

| 步骤 | 操作 | 代码位置 |
|------|------|---------|
| 下注扣款 | 检查后无预扣（View 内结算） | gambling.py L1165 |
| 存活(赢) | `add_coins(uid, bet*2)` (net +bet) | `RouletteView._resolve` |
| 死亡(输) | `add_coins(uid, profit=-self.bet)` (net -bet) | 同上 |

**注意**: RussianRoulette 与其他游戏模式不同——它在 View 内部结算（输时扣、赢时加），而非预扣。计算正确：赢→+bet*2 净赚bet；输→-bet 净赔bet。

✅ **无Bug**（但建议统一为预扣模式以降低复杂度）

---

### 8. Blackjack 21点 (`casino_games.py`)

| 步骤 | 操作 | 代码位置 |
|------|------|---------|
| 下注扣款 | `add_coins(uid, -bet, "21点下注")` | casino_games.py `blackjack_cmd` L675 |
| 普通赢 | `profit = self.bet * 2`; `add_coins(uid, profit, ...)` | `_stand` L175 |
| Blackjack(3:2) | `profit = int(self.bet * 2.5)`; `add_coins(uid, profit, ...)` | `_stand` L170 |
| 平局 | `add_coins(uid, self.bet, ...)` | `_stand` L179 |
| 输 | 无额外操作 | `_stand` |
| Double | `add_coins(uid, -self.bet, ...)` 二次扣款 | `double_btn` L136 |

**净结果**: 普通赢 → -bet + bet*2 = +bet (正确)；Blackjack → -bet + bet*2.5 = +bet*1.5 (正确, 3:2)

✅ **无Bug**

---

### 9. HorseRace 赛马 (`casino_games.py`)

| 步骤 | 操作 | 代码位置 |
|------|------|---------|
| 下注扣款 | `add_coins(uid, -bet, "赛马下注")` | casino_games.py `horserace_cmd` L743 |
| 赢 | `payout = int(self.bet * HORSE_ODDS[idx])`; `add_coins(uid, payout, ...)` | `_run_race` L467 |
| 输 | 无额外操作 | `_run_race` |

**净结果**: 赢 → -bet + bet*odds = bet*(odds-1) (正确)；输 → -bet (正确)

✅ **无Bug**（之前历史 Bug 已修复）

---

## 🔴 关键 Bug: GamblingLobbyView 参数错误

**文件**: `gambling.py` 行 1165-1240

**问题**: `GamblingLobbyView` 创建子游戏 View 时传入了错误的参数：

```python
view = RouletteView(bot=None, user_id=int(self.uid) if self.uid.isdigit() else 0)
view = CrashView(bot=None, user_id=int(self.uid) if self.uid.isdigit() else 0)
view = ScratchView(bot=None, user_id=int(self.uid) if self.uid.isdigit() else 0)
view = HighLowView(bot=None, user_id=int(self.uid) if self.uid.isdigit() else 0)
view = NumberGuessView(bot=None, user_id=int(self.uid) if self.uid.isdigit() else 0)
```

而这些 View 的真实 `__init__` 签名均为:

- `RouletteView.__init__(self, user_id, user_name, bet)`
- `HighLowView.__init__(self, user_id, user_name, bet)`
- `NumberGuessView.__init__(self, user_id, bet, secret)`
- `ScratchView.__init__(self, user_id, user_name)`
- `CrashView.__init__(self, user_id, user_name, bet)`

**影响**: 这些按钮点击后会 `TypeError` 崩溃，GamblingLobbyView 中的按钮全是坏的。

**修复**: 无法用错误参数直接创建 View，应通过 Modal 收集赌注后创建，或使用完整的参数调用。

---

## 结论

| 游戏 | 资金流 | 状态 |
|------|--------|------|
| 轮盘 Roulette | 预扣→赢加2x/36x→输不加 | ✅ |
| 比大小 HighLow | 预扣→赢加2x→平局退本→输不加 | ✅ |
| 猜数字 NumberGuess | 预扣→赢加Nx→输不加 | ✅ |
| 刮刮乐 Scratch | 预扣50→中加prize→未中不加 | ✅ |
| Crash 爆爆乐 | 预扣→提现加multiplier→崩盘不加 | ✅ |
| Dice Duel | 双方预扣→胜者得奖池→平局退 | ✅ |
| RussianRoulette | View内结算(赢加2x/输扣1x) | ✅⚠️ |
| Blackjack 21点 | 预扣→赢加2x/2.5x→平退本→输不加 | ✅ |
| HorseRace 赛马 | 预扣→赢加odds→输不加 | ✅ |
| GamblingLobbyView | 参数错误, 全部崩溃 | 🔴 |

**总评级**: 核心资金流无 Bug，但 GamblingLobbyView 需要重写
