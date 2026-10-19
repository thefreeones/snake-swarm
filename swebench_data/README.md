# SWE-bench 评测数据

逐实例结果（JSONL，每行一个实例），字段：`instance_id` / `repo` / `resolved` / `attempts` / `errors` / `locator` / `locator_weights` / `reproduced`。

| 文件 | 内容 | 对应 |
|------|------|------|
| `swebench_results_r4.jsonl` | R4 全量 26 例（5/26 resolved，含候选截断 bug） | 论文 §5.7 表 |
| `swebench_results_r5.jsonl` | R5 全量 26 例（7/26 resolved，修复 P1-1 多候选） | 论文 §5.7 表 / §5.8 |
| `swebench_results_bestofk.jsonl` | R5 成功实例的 2-3 次独立重跑（best-of-k 稳定性） | 论文 §5.8 |

说明：
- 数据只含实例 ID 与判定结果，不含 gold patch、test_patch 或生成代码，评测公平性不受影响。
- 判据与官方 harness 一致：FAIL_TO_PASS 全过且 PASS_TO_PASS 无回归记为 resolved。
- 评测环境为无 Docker 手动流程，见根 README「诚实边界」。
