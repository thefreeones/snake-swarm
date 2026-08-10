# MatchLog CLI — 完整模块契约

## 项目概述
Python CLI工具，追踪1v1比赛记录。JSON存储，命令行交互。

## U1: models.py — 数据模型
```python
from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class Match:
    opponent: str       # 对手名
    result: str         # "win"|"loss"|"draw"|"draw(win)"
    played_at: str      # ISO datetime (如"2026-08-06T14:30:00")
    notes: str = ""     # 可选备注

@dataclass
class Stats:
    total: int
    wins: int
    losses: int
    draws: int
    win_rate: float         # 0.0-100.0
    current_streak: int     # 正=连胜,负=连败,0=无
    streak_type: str        # "win"|"loss"|"none"
    longest_win_streak: int
    longest_loss_streak: int
    h2h: Dict[str, dict]    # {opponent: {wins, losses, draws}}

@dataclass  
class MatchLog:
    matches: List[Match] = field(default_factory=list)
```

## U2: store.py — JSON 持久化
```python
class Store:
    def __init__(self, path: str = "matchlog.json")
    def load(self) -> MatchLog          # 文件不存在返回空MatchLog
    def save(self, log: MatchLog)        # 原子写入(先写.tmp再rename)
    def add_match(self, match: Match)    # load→append→save
```

## U3: commands/add.py — 添加记录
```python
def add_match(store: Store, opponent: str, result: str, notes: str = "") -> Match
```
- result必须是"win"|"loss"|"draw"|"draw(win)"，否则raise ValueError
- 调用store.add_match()
- 返回创建的Match对象

## U4: commands/stats.py — 统计分析
```python
def compute_stats(matches: List[Match]) -> Stats
```
- 计算所有统计指标
- 连胜/连败从最近开始往前数
- 最长连胜/连败扫描全部历史
- win_rate = wins/(wins+losses)*100，不计draw
- h2h按对手分组统计

## U5: cli.py — 命令行入口
```python
# 命令:
matchlog add <opponent> --result <win|loss|draw|draw(win)> [--notes ...]
matchlog stats
matchlog stats <opponent>    # 指定对手h2h
matchlog list [--limit 10]   # 最近N条记录
```
- 使用argparse + subcommands
- Store路径默认./matchlog.json，可通过环境变量MATCHLOG_PATH覆盖

## 验证标准
1. `python -m matchlog add Alice --result win` → 不报错
2. `python -m matchlog add Bob --result loss` → 不报错
3. `python -m matchlog stats` → 显示1胜1负,胜率50%,1连败
4. `python -m matchlog list` → 显示2条记录
5. matchlog.json文件存在且格式正确
