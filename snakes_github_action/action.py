#!/usr/bin/env python
"""
蛇群 GitHub Action 入口
GitHub Issue → Snakes → PR

用法 (GitHub Actions workflow):
    - uses: snakes/snakes-action@v1
      with:
        api-key: ${{ secrets.SNAKES_API_KEY }}
        issue-number: ${{ github.event.issue.number }}
"""
import json
import os
import re
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from snakes_core import Snakes


def parse_issue_body(body: str) -> list[dict]:
    """从Issue正文解析bug信息"""
    bugs = []

    # 模式1: 结构化格式
    # **文件**: slugify.py
    # **函数**: smart_truncate
    # **描述**: max_length为负数时截断错误
    # **触发输入**: -1
    file_match = re.search(r'\*\*文件\*\*[:\s]*`?(\S+\.py)`?', body)
    func_match = re.search(r'\*\*函数\*\*[:\s]*`?(\w+)`?', body)
    desc_match = re.search(r'\*\*描述\*\*[:\s]*(.+?)(?:\n\n|\n\*\*|$)', body, re.DOTALL)
    trigger_match = re.search(r'\*\*触发.*?\*\*[:\s]*(.+?)(?:\n|$)', body)

    if file_match and func_match and desc_match:
        bugs.append({
            "function": func_match.group(1),
            "description": desc_match.group(1).strip()[:500],
            "error_type": "",
            "trigger": trigger_match.group(1).strip() if trigger_match else None,
        })
        return file_match.group(1), bugs

    # 模式2: 自由文本 (尝试提取)
    # "文件xxx.py的函数yyy中，当..."
    free_match = re.search(r'文件\s*`?(\S+\.py)`?\s*[的中有]\s*函数\s*`?(\w+)`?\s*[，,]\s*(.+)', body)
    if free_match:
        bugs.append({
            "function": free_match.group(2),
            "description": free_match.group(3)[:500],
            "error_type": "",
            "trigger": None,
        })
        return free_match.group(1), bugs

    return None, bugs


def get_issue_body(github_token: str, repo: str, issue_number: int) -> str:
    """通过GitHub API获取issue正文"""
    import urllib.request
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "snakes-action",
    })
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data.get("body", "")


def create_pull_request(github_token: str, repo: str, branch: str,
                        title: str, body: str, base: str = "main"):
    """通过GitHub API创建PR"""
    import urllib.request
    url = f"https://api.github.com/repos/{repo}/pulls"
    payload = {
        "title": title,
        "body": body,
        "head": branch,
        "base": base,
    }
    req = urllib.request.Request(url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
            "User-Agent": "snakes-action",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def run_git(*args):
    """执行git命令"""
    subprocess.run(["git"] + list(args), check=True, capture_output=True)


def main():
    api_key = os.environ.get("SNAKES_API_KEY", "")
    base_url = os.environ.get("SNAKES_BASE_URL", "https://n.tokeness.io/v1")
    github_token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")

    if not api_key:
        print("❌ SNAKES_API_KEY 未设置")
        sys.exit(1)

    # 获取issue信息
    issue_body = ""
    issue_number = 0

    if os.path.exists(event_path):
        with open(event_path) as f:
            event = json.load(f)
        issue = event.get("issue", {})
        issue_body = issue.get("body", "")
        issue_number = issue.get("number", 0)

    if not issue_body:
        print("❌ 无法获取issue正文")
        sys.exit(1)

    # 解析bug
    file_path, bugs = parse_issue_body(issue_body)
    if not bugs:
        print("❌ 无法从issue中解析bug信息")
        print(f"   Issue正文预览: {issue_body[:300]}...")
        print("   请使用结构化格式:")
        print("   **文件**: xxx.py")
        print("   **函数**: function_name")
        print("   **描述**: bug描述")
        sys.exit(1)

    print(f"🐍 蛇群 Action 启动")
    print(f"   仓库: {repo}")
    print(f"   Issue: #{issue_number}")
    print(f"   文件: {file_path}")
    print(f"   Bug数: {len(bugs)}")
    print()

    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        sys.exit(1)

    # 跑蛇群
    snakes = Snakes(api_key=api_key, base_url=base_url)
    result = snakes.scan(file_path=file_path, bug_candidates=bugs, use_cache=True)

    # 输出结果
    for i, r in enumerate(result.results):
        status = "✅" if r.success else "❌"
        print(f"  [{i+1}] {status} {r.bug_id}")

    print(f"\n  通过: {result.success_count}/{len(bugs)}")
    print(f"  Token: {result.total_tokens}")

    # 如果有成功修复 → 创建PR分支
    if result.success_count > 0 and github_token and repo:
        branch_name = f"snakes/fix-issue-{issue_number}"
        try:
            run_git("checkout", "-b", branch_name)
            run_git("config", "user.name", "snakes-bot")
            run_git("config", "user.email", "snakes@example.com")
            run_git("add", file_path)
            run_git("commit", "-m", f"🐍 Fix issue #{issue_number}: {result.success_count}/{len(bugs)} bugs")
            run_git("push", "origin", branch_name)

            pr = create_pull_request(
                github_token, repo, branch_name,
                title=f"🐍 蛇群自动修复: Issue #{issue_number}",
                body=f"""## 蛇群自动修复报告

基于 Issue [#{issue_number}](https://github.com/{repo}/issues/{issue_number})

| 修复 | 状态 |
|------|------|
"""
+ "\n".join(f"| {r.bug_id} | {'✅' if r.success else '❌'} |" for r in result.results)
+ f"""

**Token消耗**: {result.total_tokens}

> 此PR由蛇群(Snakes)自动生成。请人工审查后合并。
""",
            )
            print(f"\n✅ PR已创建: {pr.get('html_url', '')}")
        except Exception as e:
            print(f"\n⚠️  PR创建失败: {e}")
    else:
        action_output = {
            "success": result.success_count,
            "total": len(bugs),
            "tokens": result.total_tokens,
        }
        print(f"\n📊 结果: {json.dumps(action_output, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
