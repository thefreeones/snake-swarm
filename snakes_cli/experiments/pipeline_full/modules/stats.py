"""
M3 Stats — Statistical Analysis Module
=======================================
Analyzes cleaned student data and produces aggregate statistics.

Input (from M2 Cleaner):
    students: list[dict] — each dict has {name: str, scores: {math: float, eng: float, cs: float}}
    All scores guaranteed 0–100, non-null.

Output:
    dict with keys: avg_math, avg_eng, avg_cs, top_student, top_total, pass_rate, total_students
"""

from __future__ import annotations


def run(students: list) -> dict:
    """Compute aggregate statistics from a list of student score records.

    Args:
        students: List of dicts, each with:
            - name: str
            - scores: dict with keys 'math', 'eng', 'cs' (float, 0–100)

    Returns:
        dict with:
            - avg_math: float   — mean math score (1 decimal)
            - avg_eng:  float   — mean English score (1 decimal)
            - avg_cs:   float   — mean CS score (1 decimal)
            - top_student: str  — name of student with highest total
            - top_total: float  — highest total score
            - pass_rate: float  — % of students with all three scores ≥ 60 (1 decimal)
            - total_students: int — number of valid student records
    """
    if not students:
        return {
            "avg_math": 0.0,
            "avg_eng": 0.0,
            "avg_cs": 0.0,
            "top_student": "",
            "top_total": 0.0,
            "pass_rate": 0.0,
            "total_students": 0,
        }

    total = len(students)
    sum_math = sum_eng = sum_cs = 0.0
    best_student = ""
    best_total = -1.0
    pass_count = 0

    for s in students:
        scores = s["scores"]
        m, e, c = scores["math"], scores["eng"], scores["cs"]

        sum_math += m
        sum_eng += e
        sum_cs += c

        total_score = m + e + c
        if total_score > best_total:
            best_total = total_score
            best_student = s["name"]

        if m >= 60 and e >= 60 and c >= 60:
            pass_count += 1

    return {
        "avg_math": round(sum_math / total, 1),
        "avg_eng": round(sum_eng / total, 1),
        "avg_cs": round(sum_cs / total, 1),
        "top_student": best_student,
        "top_total": round(best_total, 1),
        "pass_rate": round(pass_count / total * 100, 1),
        "total_students": total,
    }


if __name__ == "__main__":
    # Smoke test
    test_students = [
        {"name": "Alice", "scores": {"math": 85.0, "eng": 78.0, "cs": 92.0}},
        {"name": "Bob", "scores": {"math": 55.0, "eng": 62.0, "cs": 70.0}},
        {"name": "Charlie", "scores": {"math": 90.0, "eng": 88.0, "cs": 95.0}},
        {"name": "Diana", "scores": {"math": 72.0, "eng": 80.0, "cs": 68.0}},
    ]

    result = run(test_students)

    print("=== M3 Stats Smoke Test ===")
    for key, val in result.items():
        print(f"  {key}: {val}")

    # Quick assertions
    assert result["total_students"] == 4
    assert result["top_student"] == "Charlie"
    assert result["pass_rate"] == 75.0  # Alice, Charlie, Diana pass; Bob fails math
    assert result["avg_math"] == 75.5
    assert result["avg_eng"] == 77.0
    assert result["avg_cs"] == 81.2
    print("\nAll assertions passed.")

    # Empty input test
    empty_result = run([])
    assert empty_result["total_students"] == 0
    assert empty_result["top_student"] == ""
    print("Empty input test passed.")
