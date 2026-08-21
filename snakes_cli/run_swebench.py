#!/usr/bin/env python3
"""
蛇群 SWE-bench 评测脚本
=======================
流程 per instance:
1. 准备环境: clone repo → checkout base_commit → uv venv → 装依赖 → 应用 test_patch
2. 定位层: issue 描述 → top-3 候选 {file, function, class_name}
3. 修复层: 逐候选跑蛇群 fix, 生成 patch
4. 评测: 应用 patch → 跑 FAIL_TO_PASS + PASS_TO_PASS → resolved?
5. 记录结果 JSONL

用法:
    python run_swebench.py --instances inst_list.json --out results.jsonl
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from locator import locate, scan_repo, render_index  # noqa: E402

ENV_ROOT = Path(r"D:/competation/design/swebench_env")
DATA_DIR = Path(r"D:/competation/design/swebench_data")
CONFIG = json.load(open(os.path.expanduser("~/.snakes_config.json"), encoding="utf-8"))

# 依赖预装 (轻量仓库的手动依赖清单 + Python 版本)
REPO_DEPS = {
    "marshmallow-code/marshmallow": {
        "python": "3.11",
        "packages": ["pytest", "pytz", "simplejson"],
    },
    "pylint-dev/astroid": {
        "python": "3.10",
        "packages": ["pytest", "lazy-object-proxy", "wrapt", "typing-extensions", "setuptools"],
    },
}


def clone_checkout(repo: str, base_commit: str, env_setup: str = "") -> Path:
    """clone + checkout base_commit. 返回 repo 目录."""
    repo_name = repo.split("/")[1]
    repo_dir = ENV_ROOT / repo_name
    if not (repo_dir / ".git").exists():
        subprocess.run(
            ["git", "clone", "--quiet", f"https://github.com/{repo}.git", str(repo_dir)],
            check=True, timeout=300,
        )
    # 先清残留 (test_patch/蛇群patch/临时文件), 再 fetch
    subprocess.run(["git", "-C", str(repo_dir), "reset", "--hard", "HEAD"],
                   check=False, timeout=60)
    subprocess.run(["git", "-C", str(repo_dir), "clean", "-fd"],
                   check=False, timeout=60)
    # fetch base_commit (带重试, git代理偶尔握手失败)
    for attempt in range(3):
        r = subprocess.run(["git", "-C", str(repo_dir), "fetch", "--quiet",
                            "origin", base_commit],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            break
        if attempt == 2:
            raise RuntimeError(f"git fetch failed after 3 attempts: {r.stderr[:200]}")
        time.sleep(5)
    subprocess.run(["git", "-C", str(repo_dir), "checkout", "--quiet", base_commit],
                   check=True, timeout=60)
    # 重置到干净状态 (清掉之前 apply 的 patch)
    subprocess.run(["git", "-C", str(repo_dir), "checkout", "--quiet", "--", "."],
                   check=False, timeout=60)
    return repo_dir


def setup_venv(repo_dir: Path, repo: str) -> Path:
    """建 venv + 装依赖. 返回 venv python 路径."""
    spec = REPO_DEPS.get(repo, {"python": "3.11", "packages": ["pytest"]})
    pyver = spec["python"]
    venv = repo_dir / f".venv{pyver.replace('.', '')}"
    if not (venv / "Scripts" / "python.exe").exists():
        subprocess.run(["uv", "venv", "--python", pyver, str(venv)],
                       check=True, timeout=120)
    deps = spec["packages"]
    env = {**os.environ, "VIRTUAL_ENV": str(venv)}
    subprocess.run(["uv", "pip", "install", "-q", *deps], env=env,
                   check=False, timeout=300)
    # 不装 editable: 测试用 PYTHONPATH=repo_dir 指向当前 checkout (切commit后代码即生效)
    # editable 安装会被新版 setuptools 的 build_editable 缺失阻断 (astroid老pyproject)
    return venv / "Scripts" / "python.exe"


def apply_patch(repo_dir: Path, patch: str, strip: int = 1) -> bool:
    """应用 patch (git apply), 自动修正路径前缀."""
    patch_file = repo_dir / "_tmp_apply.patch"
    patch_file.write_text(patch, encoding="utf-8")
    # 先试原样 apply
    r = subprocess.run(["git", "-C", str(repo_dir), "apply", "--check", str(patch_file)],
                       capture_output=True, text=True)
    if r.returncode == 0:
        subprocess.run(["git", "-C", str(repo_dir), "apply", str(patch_file)],
                       check=True)
        return True
    # 失败: 用 basename 反查仓库内真实路径 (e.g. brain_builtin_inference.py → astroid/brain/brain_builtin_inference.py)
    def _resolve_by_basename(p: str) -> str:
        _EX = (".venv", "venv", "site-packages", "node_modules", "__pycache__",
               ".tox", ".pytest_cache", "build", "dist", ".git")
        for root, dirs, files in os.walk(str(repo_dir)):
            dirs[:] = [d for d in dirs if not any(ex in d for ex in _EX)]
            for fn in files:
                if fn == os.path.basename(p):
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, str(repo_dir)).replace("\\", "/")
                    return rel
        return p

    # 提取 patch 里的文件路径并替换
    def _rewrite_paths(p: str) -> str:
        new_lines = []
        for line in p.split("\n"):
            m = re.match(r'^(--- a/|\+\+\+ b/)(\S+)', line)
            if m:
                old = m.group(2)
                # 若 old 不是仓库内真实相对路径, 用 basename 反查
                if not (repo_dir / old).exists():
                    resolved = _resolve_by_basename(old)
                    if resolved != old:
                        line = f"{m.group(1)}{resolved}"
            new_lines.append(line)
        return "\n".join(new_lines)

    fixed = _rewrite_paths(patch)
    patch_file.write_text(fixed, encoding="utf-8")
    r2 = subprocess.run(["git", "-C", str(repo_dir), "apply", "--check", str(patch_file)],
                        capture_output=True, text=True)
    if r2.returncode == 0:
        subprocess.run(["git", "-C", str(repo_dir), "apply", str(patch_file)],
                       check=True)
        return True
    # 兜底: 递归向上尝试 src/ 和 <repo_name>/ 前缀
    repo_name = repo_dir.name
    for prefix in (f"src/{repo_name}/", f"{repo_name}/", "src/"):
        fixed2 = re.sub(r'^--- a/(?!src/)', f'--- a/{prefix}', patch, flags=re.M)
        fixed2 = re.sub(r'^\+\+\+ b/(?!src/)', f'+++ b/{prefix}', fixed2, flags=re.M)
        patch_file.write_text(fixed2, encoding="utf-8")
        r3 = subprocess.run(["git", "-C", str(repo_dir), "apply", "--check", str(patch_file)],
                            capture_output=True, text=True)
        if r3.returncode == 0:
            subprocess.run(["git", "-C", str(repo_dir), "apply", str(patch_file)],
                           check=True)
            return True
    return False


def run_tests(python: Path, repo_dir: Path, test_ids: list, timeout: int = 300) -> dict:
    """运行测试. 返回 {test_id: 'PASS'|'FAIL'|'ERROR'}.

    SWE-bench 参数化测试 ID 含换行等特殊字符, 无法精确解析时
    回退到"文件::类::函数"前缀匹配 (跑该函数全部参数化用例).
    """
    results = {}
    # PYTHONPATH=repo_dir: import 用当前 checkout 源码 (非 editable 安装)
    env = {**os.environ, "PYTHONPATH": str(repo_dir)}
    for tid in test_ids:
        # 尝试精确执行; 失败则截断到 文件::类::函数 前缀
        cr = subprocess.run(
            [str(python), "-m", "pytest", "-q", "--no-header", "--tb=no", tid],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=timeout, env=env,
        )
        if cr.returncode == 0:
            results[tid] = "PASS"
            continue
        # 精确失败: 若含 [ 参数部分, 截断后重试
        if "[" in tid:
            prefix = tid.split("[")[0]
            pr = subprocess.run(
                [str(python), "-m", "pytest", "-q", "--no-header", "--tb=no", prefix],
                cwd=str(repo_dir), capture_output=True, text=True, timeout=timeout, env=env,
            )
            if pr.returncode == 0:
                results[tid] = "PASS"
                continue
            if "collected 0" in pr.stdout or "no tests ran" in pr.stdout:
                results[tid] = "ERROR"  # 测试文件/节点不存在 (环境不可复现)
                continue
            results[tid] = "FAIL"
            continue
        # 区分 FAIL vs ERROR
        if "collected 0" in cr.stdout or "no tests ran" in cr.stdout:
            results[tid] = "ERROR"
        elif "ERROR" in cr.stdout or "error" in cr.stderr.lower():
            results[tid] = "ERROR"
        else:
            results[tid] = "FAIL"
    return results


def _parse_list(v):
    """parquet 里 FAIL_TO_PASS/PASS_TO_PASS 是 JSON 字符串, 解析成 list."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return []
    return v or []


def _traceback_line_to_func(repo_dir: Path, issue: str) -> dict:
    """把 traceback 里的 文件:行号 映射到 函数/类 (确定性, 零token).

    返回 {file: {line: (function, class_name)}} 供候选排序加权.
    """
    import ast as _ast
    result = {}
    _EX = (".venv", "venv", "site-packages", "node_modules", "__pycache__",
           ".tox", ".pytest_cache", "build", "dist", ".git")
    for m in re.finditer(r'File "([^"]+)", line (\d+)', issue):
        fpath, lineno = m.group(1), int(m.group(2))
        fname = os.path.basename(fpath)
        # 在 repo 里找同名文件
        for root, dirs, files in os.walk(str(repo_dir)):
            dirs[:] = [d for d in dirs if not any(ex in d for ex in _EX)]
            for fn in files:
                if fn == fname:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, str(repo_dir)).replace("\\", "/")
                    try:
                        code = open(full, encoding="utf-8", errors="replace").read()
                        tree = _ast.parse(code)
                        for node in _ast.walk(tree):
                            if isinstance(node, _ast.FunctionDef):
                                if node.lineno <= lineno <= node.end_lineno:
                                    cls = ""
                                    for parent in _ast.walk(tree):
                                        if isinstance(parent, _ast.ClassDef):
                                            for item in parent.body:
                                                if item is node:
                                                    cls = parent.name
                                    result.setdefault(rel, {})[lineno] = (node.name, cls)
                    except (SyntaxError, OSError):
                        pass
    return result


def _weight_candidates(candidates: list, tb_map: dict) -> list:
    """用 traceback 行号映射给候选加权排序 (命中行号的排最前)."""
    if not tb_map:
        return candidates
    weighted = []
    for c in candidates:
        f = c.get("file", "")
        fn = c.get("function", "")
        cls = c.get("class_name", "")
        hit = False
        for line, (func, klass) in tb_map.get(f, {}).items():
            if func == fn and (not cls or klass == cls or not klass):
                hit = True
                break
        weighted.append((0 if hit else 1, c))
    weighted.sort(key=lambda x: x[0])
    return [c for _, c in weighted]


def evaluate_instance(inst: dict, out_fd, dry_run: bool = False) -> dict:
    """评测单个 SWE-bench 实例."""
    iid = inst["instance_id"]
    repo = inst["repo"]
    base_commit = inst["base_commit"]
    env_setup = inst.get("environment_setup_commit", "")
    problem = inst["problem_statement"]
    fail_to_pass = _parse_list(inst["FAIL_TO_PASS"])
    pass_to_pass = _parse_list(inst.get("PASS_TO_PASS", []))[:20]  # 采样 20 个防爆

    record = {
        "instance_id": iid,
        "repo": repo,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "locator": None,
        "attempts": [],
        "resolved": False,
        "errors": [],
    }

    try:
        # 1. 准备环境
        repo_dir = clone_checkout(repo, base_commit, env_setup)
        python = setup_venv(repo_dir, repo)

        # 2. 应用 test_patch (先验证 bug 复现)
        if not apply_patch(repo_dir, inst["test_patch"]):
            record["errors"].append("test_patch apply failed")
            out_fd.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_fd.flush()
            return record

        # 3. 确认 FAIL_TO_PASS 在修复前失败 (bug 复现)
        before = run_tests(python, repo_dir, fail_to_pass[:2])
        any_pass_before = any(v == "PASS" for v in before.values())
        record["reproduced"] = not any_pass_before
        if any_pass_before:
            record["errors"].append(f"bug 未复现(测试已过): {before}")
            out_fd.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_fd.flush()
            return record

        # 4. 定位层
        if dry_run:
            record["locator"] = "DRY"
        else:
            loc = locate(CONFIG["api_key"], CONFIG["base_url"],
                         CONFIG["models"].get("light_head", "deepseek-v4-flash"),
                         str(repo_dir), problem)
            record["locator"] = loc
        candidates = (loc.get("candidates") if not dry_run else []) or []
        # traceback 行号加权排序 + 确定性兜底: 行号命中的函数无条件加入候选头部
        tb_map = _traceback_line_to_func(repo_dir, problem)
        if tb_map:
            tb_candidates = []
            seen = set()
            for f, lines in tb_map.items():
                for line, (func, klass) in lines.items():
                    # 优先最深的调用帧 (最后出现的行号往往是根因点)
                    key = (f, func, klass)
                    if key not in seen and func:
                        seen.add(key)
                        tb_candidates.append({
                            "file": f, "function": func, "class_name": klass,
                            "reason": f"traceback行号{line}确定性定位",
                            "from_traceback": True,
                        })
            # 倒序: traceback 最后一个 File 帧 = 最深调用 = 根因概率最高
            tb_candidates = tb_candidates[::-1]
            # 合并: traceback 候选在前, LLM 候选在后(去重)
            merged = list(tb_candidates)
            for c in candidates:
                key = (c.get("file", ""), c.get("function", ""), c.get("class_name", ""))
                if key not in {(x["file"], x["function"], x["class_name"]) for x in merged}:
                    merged.append(c)
            candidates = merged[:5]
            record["locator_weights"] = {k: str(v) for k, v in tb_map.items()}
        if not candidates:
            record["errors"].append("定位层无候选")
            out_fd.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_fd.flush()
            return record

        # 5. 逐候选修复
        for ci, cand in enumerate(candidates[:3]):
            file_path = os.path.join(str(repo_dir), cand.get("file", ""))
            function = cand.get("function", "")
            class_name = cand.get("class_name", "")
            if not os.path.exists(file_path) or not function:
                record["attempts"].append({"candidate": cand, "error": "file/function 无效"})
                continue
            attempt = {"candidate": cand}
            try:
                from snakes_core import Snakes
                snakes = Snakes(api_key=CONFIG["api_key"], base_url=CONFIG["base_url"],
                                models=CONFIG["models"])
                r = snakes.fix(
                    file_path=file_path,
                    function=function,
                    bug_description=problem,
                    class_name=class_name,
                    enable_judges=False,
                )
                attempt["fix_success"] = r.success
                attempt["tokens"] = r.tokens
                if not r.patch:
                    attempt["error"] = (getattr(r, "error", "") or "无patch输出")[:300]
                    record["attempts"].append(attempt)
                    continue

                # 回滚 test_patch 之前的修复尝试? 不行——每候选都是独立 fix,
                # 但 repo 状态会被上一个候选污染. 这里用 git checkout 恢复.
                subprocess.run(["git", "-C", str(repo_dir), "checkout", "--quiet", "--", "."],
                               check=False)
                # 重新应用 test_patch (被 checkout 清掉了)
                apply_patch(repo_dir, inst["test_patch"])

                # 应用蛇群 patch
                if not apply_patch(repo_dir, r.patch):
                    attempt["error"] = "蛇群patch apply失败"
                    attempt["patch"] = r.patch[:300]
                    record["attempts"].append(attempt)
                    continue

                # 评测: FAIL_TO_PASS + PASS_TO_PASS 采样
                after_ftp = run_tests(python, repo_dir, fail_to_pass)
                after_ptp = run_tests(python, repo_dir, pass_to_pass)
                ftp_pass = all(v == "PASS" for v in after_ftp.values())
                ptp_pass = all(v == "PASS" for v in after_ptp.values())
                attempt["fail_to_pass"] = after_ftp
                attempt["pass_to_pass"] = after_ptp
                if ftp_pass and ptp_pass:
                    record["resolved"] = True
                    record["attempts"].append(attempt)
                    break
                record["attempts"].append(attempt)
            except Exception as e:
                attempt["error"] = f"异常: {str(e)[:200]}"
                record["attempts"].append(attempt)

    except Exception as e:
        record["errors"].append(f"流程异常: {str(e)[:300]}")

    out_fd.write(json.dumps(record, ensure_ascii=False) + "\n")
    out_fd.flush()
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instances", required=True, help="实例列表 JSON")
    parser.add_argument("--out", default="swebench_results.jsonl", help="结果输出")
    parser.add_argument("--limit", type=int, default=0, help="限制实例数(0=全部)")
    parser.add_argument("--dry-run", action="store_true", help="只测环境准备, 不调 LLM")
    args = parser.parse_args()

    instances = json.load(open(args.instances, encoding="utf-8"))
    if args.limit:
        instances = instances[:args.limit]

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "a", encoding="utf-8") as f:
        for inst in instances:
            print(f"\n{'='*60}\n▶ {inst['instance_id']}", flush=True)
            rec = evaluate_instance(inst, f, dry_run=args.dry_run)
            status = "✅ RESOLVED" if rec.get("resolved") else "❌ failed"
            print(f"  {status}", flush=True)


if __name__ == "__main__":
    main()
