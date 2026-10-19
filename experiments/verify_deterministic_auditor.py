"""
确定性的审计者验证脚本 — 用P4全部4个用例跑完整审计
"""
import json
import sys
sys.path.insert(0, '<SNAKE_SWARM_DATA>/experiments')
from deterministic_auditor import DeterministicAuditor

auditor = DeterministicAuditor()

# ================================================================
# 全部P4用例
# ================================================================
cases = [
    {
        "repair_id": "case8_get_user_info",
        "original": "def get_user_info(data, user_id):\n    for user in data:\n        if user['id'] == user_id:\n            return {'name': user['name'], 'email': user['email']}\n    return None",
        "fixed": "def get_user_info(data, user_id):\n    for user in data:\n        if user['id'] == user_id:\n            return {'name': user.get('name'), 'email': user.get('email')}\n    return None",
        "trigger_input": [{"id": 1}],
        "trigger_func": "get_user_info",
        "trigger_type": "exception",
        "regression": [
            {"name": "缺失name/email键→默认None", "input": [[{"id": 1}], 1], "expected": {"name": None, "email": None}},
            {"name": "正常数据", "input": [[{"id": 1, "name": "A", "email": "E"}], 1], "expected": {"name": "A", "email": "E"}},
            {"name": "用户不存在", "input": [[{"id": 2, "name": "B"}], 1], "expected": None},
        ],
        "token_baseline": 3224,
    },
    {
        "repair_id": "S2_compute_variance",
        "original": "def compute_variance(data):\n    n = len(data)\n    sum_x = sum(data)\n    sum_x2 = sum(x*x for x in data)\n    return (sum_x2 - sum_x*sum_x/n)/n",
        "fixed": "def compute_variance(data):\n    count = 0\n    mean = 0.0\n    M2 = 0.0\n    for x in data:\n        count += 1\n        delta = x - mean\n        mean += delta / count\n        delta2 = x - mean\n        M2 += delta * delta2\n    return M2 / count",
        "trigger_input": [1e10 + 1, 1e10 + 2, 1e10 + 3],
        "trigger_func": "compute_variance",
        "trigger_type": "exception",
        "regression": [],  # S2的检验在法官侧(数值精度),审计者只需验证函数不崩溃
        "token_baseline": 4302,
    },
    {
        "repair_id": "S6_duplicate_list",
        "original": "def duplicate_list(lst):\n    return [lst] * 2",
        "fixed": "import copy\n\ndef duplicate_list(lst):\n    return [copy.deepcopy(lst), copy.deepcopy(lst)]",
        "trigger_input": [[1, 2, [3, 4]]],
        "trigger_func": "duplicate_list",
        "trigger_type": "exception",
        "regression": [],  # S6的独立性检验需要交互式代码,审计者验证函数不崩溃
        "token_baseline": 2262,
    },
    {
        "repair_id": "case2_safe_divide",
        "original": "def safe_divide(a, b):\n    if b == 0:\n        return None\n    result = a / b\n    if result != int(result):\n        return None\n    return int(result)",
        "fixed": "def safe_divide(a, b):\n    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):\n        return None\n    if b == 0:\n        return None\n    result = a / b\n    if result != int(result):\n        return None\n    return int(result)",
        "trigger_input": ["abc", 1],
        "trigger_func": "safe_divide",
        "trigger_type": "value",
        "trigger_expected": None,
        "regression": [
            {"name": "字符串输入→None", "input": ["abc", 1], "expected": None},
            {"name": "bool输入→None(bool是int子类)", "input": [True, 1], "expected": None},
            {"name": "正常除法", "input": [10, 2], "expected": 5},
            {"name": "除零→None", "input": [5, 0], "expected": None},
        ],
        "token_baseline": 3117,
    },
]

print("=" * 66)
print("  确定性审计者 v0.4a-1 — P4全量验证")
print("=" * 66)

results = []
total_saved = 0
passed = 0
failed = 0

for c in cases:
    report = auditor.audit(
        repair_id=c["repair_id"],
        original_code=c["original"],
        fixed_code=c["fixed"],
        trigger_input=c["trigger_input"],
        trigger_func=c["trigger_func"],
        trigger_expected_type=c["trigger_type"],
        trigger_expected=c.get("trigger_expected"),
        regression_tests=c["regression"],
        token_baseline=c["token_baseline"],
    )
    results.append(report)
    total_saved += report.token_saved

    l2_pass = sum(1 for r in report.L2 if r["passed"]) if report.L2 else 0
    l2_fail = sum(1 for r in report.L2 if not r["passed"]) if report.L2 else 0

    print(f"\n[{c['repair_id']}] {report.verdict}")
    print(f"  L1 bug消除: {report.L1['bug_eliminated']}")
    print(f"  L1 副作用: {[se['pattern'] for se in report.side_effects]}")
    print(f"  L2: {l2_pass} pass / {l2_fail} fail")
    print(f"  建议: {report.recommendation or '(通过)'}")
    print(f"  Token: 节省{report.token_saved}")

    if report.verdict == "PASS":
        passed += 1
    else:
        failed += 1

print(f"\n{'='*66}")
print(f"  结果: {passed}/{passed+failed} 通过, {failed} 拒绝")
print(f"  Token节省合计: {total_saved}")
print(f"  vs P4 LLM审计: {total_saved} → 零token (L1/L2确定性)")
print(f"{'='*66}")

# 保存报告
report_data = [
    {
        "repair_id": r.repair_id,
        "verdict": r.verdict,
        "L1_bug_eliminated": r.L1["bug_eliminated"],
        "L1_side_effects": [se for se in r.side_effects],
        "L2_summary": f"{sum(1 for t in r.L2 if t['passed'])}/{len(r.L2)}" if r.L2 else "N/A",
        "recommendation": r.recommendation,
        "token_saved": r.token_saved,
    }
    for r in results
]

with open("results/deterministic_auditor_p4_validation.json", "w") as f:
    json.dump({"summary": {
        "passed": passed, "failed": failed, "total_saved": total_saved,
        "comparison": "P4 LLM审计消耗12905 token → 确定性审计零token",
    }, "reports": report_data}, f, indent=2, ensure_ascii=False)

print(f"\n报告: results/deterministic_auditor_p4_validation.json")
