"""
M2 Cleaner — 数据清洗模块。

清洗 M1 Loader 产出的学生数据，剔除无效记录。
清洗规则：
  1. 任一模考分数为 null        → 剔除
  2. 任一模考分数 < 0 或 > 100   → 剔除
  3. 保留通过验证的记录

产出字段: {students, total_loaded, removed, removed_records}
"""

from __future__ import annotations

from typing import Any

# ── 科目白名单（与 M1 数据契约一致）───────────────────────────────────────
SUBJECTS = ("math", "eng", "cs")


def _validate(entry: dict[str, Any]) -> str | None:
    """逐字段校验一个学生的三科成绩。

    Returns:
        第一个无效原因字符串；全部合法时返回 None。
    """
    name = entry["name"]
    scores = entry["scores"]
    for subj in SUBJECTS:
        val: Any = scores[subj]
        if val is None:
            return f"{name}: {subj}=null分无效"
        if not isinstance(val, (int, float)):
            return f"{name}: {subj}类型非数值无效"
        if val < 0:
            return f"{name}: {subj}={val}分无效"  # 负数
        if val > 100:
            return f"{name}: {subj}={val}分无效"  # 超上限
    return None


# ── 主入口 ────────────────────────────────────────────────────────────────
def run(students: list[dict[str, Any]], total_loaded: int) -> dict[str, Any]:
    """清洗学生数据，返回有效记录与剔除明细。

    Args:
        students:     M1 产出的学生列表，每项含 {name, scores: {math, eng, cs}}。
        total_loaded: 传入的总记录数。

    Returns:
        dict: {
            "students":        list[dict] — 仅有效记录,
            "total_loaded":    int       — 传入的总记录数,
            "removed":         int       — 被剔除的记录数,
            "removed_records": list[str] — 剔除的学生名 + 简要原因,
        }
    """
    kept: list[dict[str, Any]] = []
    removed_records: list[str] = []

    for entry in students:
        reason = _validate(entry)
        if reason is None:
            kept.append(entry)
        else:
            removed_records.append(reason)

    return {
        "students": kept,
        "total_loaded": total_loaded,
        "removed": len(removed_records),
        "removed_records": removed_records,
    }


# ── 集成测试 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from pathlib import Path

    # 导入 M1 Loader
    from modules.loader import run as load

    data_file = Path(__file__).resolve().parent.parent / "score_data.json"
    m1_result = load(str(data_file))

    print(f"[M2 Cleaner] 收到 {m1_result['total_loaded']} 条记录，开始清洗...\n")
    m2_result = run(m1_result["students"], m1_result["total_loaded"])

    print(f"  有效记录: {len(m2_result['students'])} 人")
    for s in m2_result["students"]:
        print(f"    {s['name']}: {s['scores']}")

    print(f"\n  剔除: {m2_result['removed']} 人")
    for r in m2_result["removed_records"]:
        print(f"    ✗ {r}")

    print(f"\n  total_loaded = {m2_result['total_loaded']}")
    print(f"  removed       = {m2_result['removed']}")
    print(f"  验证: {len(m2_result['students']) + m2_result['removed']} == {m2_result['total_loaded']}")
