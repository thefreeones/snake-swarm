"""
M1 Loader — 数据加载模块。

从 JSON 文件加载学生成绩数据，解析并验证基本结构。
返回 {students, total_loaded}，JSON 解析失败时抛出 ValueError。
"""

from __future__ import annotations

import json
from typing import Any


def run(input_path: str) -> dict[str, Any]:
    """从指定路径加载 score_data.json，返回学生列表与总数。

    Args:
        input_path: score_data.json 的文件路径。

    Returns:
        dict: {"students": list[dict], "total_loaded": int}
              每个 student 包含 name (str) 和 scores ({math, eng, cs})。

    Raises:
        ValueError: JSON 解析失败或顶层缺少 "students" 键。
    """
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, OSError) as exc:
        raise ValueError(f"无法加载或解析数据文件: {input_path}") from exc

    if not isinstance(data, dict) or "students" not in data:
        raise ValueError(f"数据文件缺少顶层 'students' 键: {input_path}")

    students: list[dict[str, Any]] = data["students"]
    return {
        "students": students,
        "total_loaded": len(students),
    }


# ── smoketest ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    from pathlib import Path

    data_file = Path(__file__).resolve().parent.parent / "score_data.json"
    result = run(str(data_file))
    print(f"[M1 Loader] 加载完成: {result['total_loaded']} 名学生")
    for s in result["students"]:
        print(f"  {s['name']}: {s['scores']}")
