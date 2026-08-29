"""修复知识库 (方向A): 成功修复自动入库, 相似场景检索注入.

存储: swebench_data/fix_knowledge.jsonl
每条: {instance_id, repo, file, function, class_name, issue, patch, resolved_at}
检索: 按 (repo, file, function) 精确匹配优先, 其次 (file, function) 符号重叠.
"""
import json, os, time

KB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "swebench_data", "fix_knowledge.jsonl")


def _load():
    rows = []
    if os.path.exists(KB_PATH):
        with open(KB_PATH, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return rows


def save_fix(instance_id: str, repo: str, file: str, function: str,
             class_name: str, issue: str, patch: str) -> None:
    """成功修复后入库 (去重: 同 instance 只存一次)."""
    rows = _load()
    if any(r.get("instance_id") == instance_id for r in rows):
        return
    entry = {
        "instance_id": instance_id,
        "repo": repo,
        "file": file,
        "function": function,
        "class_name": class_name,
        "issue": issue[:2000],
        "patch": patch,
        "resolved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    os.makedirs(os.path.dirname(KB_PATH), exist_ok=True)
    with open(KB_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def search_fix(file: str, function: str, class_name: str = "",
               repo: str = "", top_k: int = 2) -> list:
    """检索相似历史修复. 返回 [{file, function, class_name, issue, patch}, ...]
    (按相关度降序, 调用方直接取字段, 无需解包元组)
    匹配优先级: 同 repo+file+function > 同 file+function > 同 function.
    """
    rows = _load()
    if not rows:
        return []
    scored = []
    for r in rows:
        score = 0
        if repo and r.get("repo") == repo:
            score += 1
        if r.get("file") == file:
            score += 2
        if r.get("function") == function and function:
            score += 3
        if r.get("class_name") == class_name and class_name:
            score += 1
        if score >= 3:  # 至少 function 命中或 file+repo
            scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:top_k]]


def kb_stats() -> dict:
    rows = _load()
    return {"entries": len(rows),
            "instances": sorted({r.get("instance_id", "") for r in rows})}


if __name__ == "__main__":
    print(json.dumps(kb_stats(), ensure_ascii=False, indent=2))
