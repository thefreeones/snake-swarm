"""
M4 Reporter — 报告生成模块
===========================

根据 M1/M2/M3 上游模块产出，生成格式化的 Markdown 成绩分析报告。

输入（数据契约）:
    total_loaded:    int        — 原始数据条数
    removed:         int        — 被剔除的无效记录数
    removed_records: list[str]  — 剔除记录明细
    avg_math:        float      — 数学平均分 (1 decimal)
    avg_eng:         float      — 英语平均分 (1 decimal)
    avg_cs:          float      — 计算机平均分 (1 decimal)
    top_student:     str        — 总分最高学生名
    top_total:       float      — 最高总分
    pass_rate:       float      — 三科均≥60分的学生占比 (%)
    total_students:  int        — 有效学生数

产出:
    report.md — 格式化的 Markdown 报告文件

要求: 零外部依赖
"""

from __future__ import annotations


def run(
    total_loaded: int,
    removed: int,
    removed_records: list[str],
    avg_math: float,
    avg_eng: float,
    avg_cs: float,
    top_student: str,
    top_total: float,
    pass_rate: float,
    total_students: int,
    output_path: str = "report.md",
) -> str:
    """生成学生成绩分析 Markdown 报告。

    Returns:
        生成的报告文件路径（绝对路径）。
    """
    # 剔除记录列表
    if removed_records:
        removed_lines = "\n".join(f"- {r}" for r in removed_records)
    else:
        removed_lines = "（无）"

    # 最佳表现行：空数据时优雅处理
    if total_students > 0 and top_student:
        best_line = f"🏆 **{top_student}** — 总分 {top_total}"
    else:
        best_line = "🏆 **（无有效数据）**"

    report = f"""# 学生成绩分析报告

## 数据概览
- 原始数据: {total_loaded} 条
- 无效数据: {removed} 条
- 有效数据: {total_students} 条

### 剔除记录
{removed_lines}

## 成绩统计
| 科目 | 平均分 |
|------|--------|
| 数学 | {avg_math} |
| 英语 | {avg_eng} |
| 计算机 | {avg_cs} |

## 最佳表现
{best_line}

## 及格率
三科均≥60分的学生占比: **{pass_rate}%**
"""

    import os

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    return os.path.abspath(output_path)


# ── 集成烟雾测试 ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 模拟上游 M1/M2/M3 产出
    test_total_loaded = 5
    test_removed = 2
    test_removed_records = [
        "Eve: math=null分无效",
        "Frank: eng=120分无效",
    ]
    test_avg_math = 75.5
    test_avg_eng = 77.0
    test_avg_cs = 81.2
    test_top_student = "Charlie"
    test_top_total = 273.0
    test_pass_rate = 75.0
    test_total_students = 3

    path = run(
        test_total_loaded,
        test_removed,
        test_removed_records,
        test_avg_math,
        test_avg_eng,
        test_avg_cs,
        test_top_student,
        test_top_total,
        test_pass_rate,
        test_total_students,
    )

    # 回读验证
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    print("=== M4 Reporter Smoke Test ===")
    print(f"Report saved to: {path}\n")
    print(content)

    # 断言关键内容
    assert "学生成绩分析报告" in content
    assert "原始数据: 5 条" in content
    assert "无效数据: 2 条" in content
    assert "有效数据: 3 条" in content
    assert "Eve: math=null分无效" in content
    assert "Frank: eng=120分无效" in content
    assert "| 数学 | 75.5 |" in content
    assert "| 英语 | 77.0 |" in content
    assert "| 计算机 | 81.2 |" in content
    assert "🏆 **Charlie** — 总分 273.0" in content
    assert "**75.0%**" in content
    print("\nAll assertions passed.")

    # ── 空数据边界测试 ──
    print("\n=== Boundary: Zero Students ===")
    path2 = run(
        total_loaded=0,
        removed=0,
        removed_records=[],
        avg_math=0.0,
        avg_eng=0.0,
        avg_cs=0.0,
        top_student="",
        top_total=0.0,
        pass_rate=0.0,
        total_students=0,
        output_path="report_empty.md",
    )
    with open(path2, "r", encoding="utf-8") as f:
        print(f.read())

    assert "（无）" in open(path2, encoding="utf-8").read()
    assert "（无有效数据）" in open(path2, encoding="utf-8").read()
    print("Boundary test passed.")
