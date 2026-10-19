# experiments/ — 历史实验脚本

这里的脚本是 P0–P14 实验阶段的运行记录，用于复现当时的实验配置，不是当前主实现（主实现在 `snakes_cli/`）。

注意：

- 脚本中的本地数据路径已替换为占位符 `<SNAKE_SWARM_DATA>`，运行前请替换为你自己的数据目录（例如 `export SNAKE_SWARM_DATA=/path/to/data` 后手动替换，或直接改脚本）。
- `results/` 下是当时的实验输出 JSON，其中的路径字段同样做了占位符处理，其余数值未改动。
- 这些脚本依赖当时的私有 API 中转配置（`~/.snakes_config.json`），没有该配置无法直接运行。

当前论文对应的实现请看 `snakes_cli/`：

| 文件 | 作用 |
|------|------|
| `snakes_core.py` | 五层核心（执行/裁决/修复/审计/学习），含黑箱重写 |
| `locator.py` | 定位层（traceback + AST 路径纠偏 + 符号兜底） |
| `run_swebench.py` | SWE-bench 端到端评测管道 |
| `profile_matcher.py` / `profiles.yaml` | 四维任务剖面路由 |
| `patterns.json` | 学习层模式库 |
| `fix_knowledge.jsonl` | 修复知识库 |
