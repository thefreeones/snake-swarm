"""知识库扩充 v2: 用 curl (直连可用) 拉 GitHub PR, 排除测试实例, 提取经验入库.

用法: python expand_kb_curl.py <repo> <max_pr>
"""
import json, os, sys, subprocess, re, time

KB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "swebench_data", "fix_knowledge.jsonl")
EXCLUDE = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "swebench_data", "_exclude_issues.json"), encoding="utf-8"))

def curl(url, accept="application/vnd.github+json"):
    r = subprocess.run(
        ["curl", "-s", "--max-time", "30", "-L", "-H", f"Accept: {accept}",
         "-H", "User-Agent: baize-kb-expand", url],
        capture_output=True, text=True, timeout=40)
    return r.stdout

def save_kb(entry):
    os.makedirs(os.path.dirname(KB_PATH), exist_ok=True)
    with open(KB_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def main():
    repo = sys.argv[1]
    max_pr = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    exclude = set(EXCLUDE.get(repo.split("/")[-1], []))
    print(f"仓库 {repo}, 排除 {len(exclude)} 个测试issue")

    added = 0
    page = 1
    while added < max_pr and page <= 6:
        url = (f"https://api.github.com/repos/{repo}/pulls?state=closed"
               f"&sort=updated&direction=desc&per_page=100&page={page}")
        out = curl(url)
        try:
            prs = json.loads(out)
        except Exception:
            print(f"  页{page} 解析失败, 跳过")
            page += 1
            continue
        if not isinstance(prs, list) or not prs:
            break
        for pr in prs:
            if added >= max_pr:
                break
            num = pr["number"]
            title = pr.get("title", "") or ""
            body = pr.get("body", "") or ""
            if "fix" not in (title + body).lower():
                continue
            mentioned = set(int(m) for m in re.findall(r"#(\d+)", title + body))
            if mentioned & exclude:
                continue
            diff = curl(pr["diff_url"], accept="application/vnd.github.v3.diff")
            if not diff or len(diff) < 50:
                continue
            files = re.findall(r"diff --git a/(\S+)", diff)
            src_files = [f for f in files
                         if f.endswith(".py")
                         and "/test" not in f
                         and not f.endswith("_test.py")
                         and "tests/" not in f
                         and "ChangeLog" not in f
                         and "CONTRIBUTORS" not in f
                         and "requirements" not in f
                         and "pyproject" not in f
                         and ".github" not in f]
            if not src_files:
                continue
            entry = {
                "instance_id": f"github:{repo}-{num}",
                "repo": repo,
                "file": src_files[0],
                "function": "",
                "class_name": "",
                "issue": f"PR #{num}: {title}\n{body[:400]}",
                "patch": diff[:1500],
                "source": "github",
                "resolved_at": "2026-08-29",
            }
            save_kb(entry)
            added += 1
            print(f"  ✅ #{num}: {title[:50]} -> {src_files[0]}", flush=True)
            time.sleep(0.2)
        page += 1
    print(f"\n完成: 新增 {added} 条 (repo={repo})")

if __name__ == "__main__":
    main()
