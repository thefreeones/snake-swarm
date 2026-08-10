# 蛇群项目构建实验 #1 — matchlog CLI

## 项目定义
一个比赛记录追踪CLI工具，记录游戏胜负、查看统计、头对头对战记录。

## 蛇头拆解 → 任务单元

| 单元 | 职责 | 依赖 | 复杂度 |
|------|------|------|--------|
| U1: models | 数据模型(data class) | 无 | L1 |
| U2: store | JSON文件读写+原子写入 | U1 | L2 |
| U3: commands/add | 添加比赛记录 | U2 | L2 |
| U4: commands/stats | 统计(胜率/连胜/连败) | ...[truncated]