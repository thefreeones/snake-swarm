# SWE-bench 评测数据

逐实例结果（JSONL，每行一个实例），字段：`instance_id` / `repo` / `resolved` / `attempts` / `errors` / `locator` / `locator_weights` / `reproduced`。

| 文件 | 内容 | 对应 |
|------|------|------|
| `swebench_results_r4.jsonl` | R4 全量 26 例（5/26 resolved，含候选截断 bug） | 论文 §5.7 表 |
| `swebench_results_r5.jsonl` | R5 全量 26 例（7/26 resolved，修复 P1-1 多候选） | 论文 §5.7 表 / §5.8 |
| `swebench_results_bestofk.jsonl` | R5 成功实例的 2-3 次独立重跑（best-of-k 稳定性） | 论文 §5.8 |
| `swebench_results_1903v2/1903v3/1903v4.jsonl` | astroid-1903 三次方案B 触发实验（迭代 2 轮失败→黑箱重写，记录触发/审计/范围溢出/后续 FTP） | 论文 §6.1 专项实验 |
| `swebench_results_astroid3.jsonl` | 补测 3 例（astroid-1364 / 1903 / 1962） | 论文 §5.7 失败模式 |
| `swebench_results_marsh2.jsonl` | 补测 2 例（marshmallow-1343 / 1702，含 1702 跨轮波动） | 论文 §5.8 稳定性 |

说明：
- 数据只含实例 ID 与判定结果，不含 gold patch、test_patch 或生成代码，评测公平性不受影响。
- 判据与官方 harness 一致：FAIL_TO_PASS 全过且 PASS_TO_PASS 无回归记为 resolved。
- 评测环境为无 Docker 手动流程，见根 README「诚实边界」。
