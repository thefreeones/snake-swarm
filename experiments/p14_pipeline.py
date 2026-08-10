"""
P14: 第二代码库全优化蛇群验证 — validators v0.35.0
组合优化: P10批量法官 + P11轻量蛇头 + P12增量缓存 + P13模板匹配 + 确定性审计者

目标: 验证泛化能力 + 达到~4500t/bug成本目标 (vs P8基线8400t/bug)
"""
import json
import os
import sys
import time
import textwrap
import urllib.request
import subprocess
from dataclasses import dataclass, field
from typing import Any, Optional

WORK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "p14_work")
sys.path.insert(0, WORK_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

API_BASE = "https://n.tokeness.io/v1"
API_KEY = None

LIGHT_HEAD = "deepseek-v4-pro"
HEAVY_HEAD = "claude-sonnet-5"
FIX_SNAKE = "deepseek-v4-pro"
BATCH_JUDGE_DS = "deepseek-v4-pro"
BATCH_JUDGE_GEMINI = "gemini-3.6-flash"

def load_api_key():
    global API_KEY
    config_path = os.environ.get('HERMES_CONFIG', os.path.expanduser('~/.hermes/config.yaml'))
    with open(config_path, 'r') as f:
        content = f.read()
    for block in content.split('- name:'):
        if 'tokeness' in block.split('\n')[0]:
            for line in block.split('\n'):
                if 'api_key:' in line and 'redacted' not in line:
                    API_KEY = line.split('api_key:')[1].strip().strip('"').strip("'")
                    return
    raise RuntimeError("Could not find tokeness API key")

def call_llm(model, system_prompt, user_prompt, temperature=0.0, max_tokens=4096):
    if not API_KEY:
        load_api_key()
    url = f"{API_BASE}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    data = json.dumps(payload).encode('utf-8')
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}"
            })
            with urllib.request.urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read())
                return {
                    "success": True,
                    "content": result["choices"][0]["message"]["content"],
                    "model": result.get("model", model),
                    "usage": result.get("usage", {})
                }
        except Exception as e:
            if attempt == 2:
                return {"success": False, "error": str(e)}
            time.sleep(2 * (attempt + 1))

from deterministic_auditor import DeterministicAuditor
auditor = DeterministicAuditor()

from fix_template_cache import FixTemplateCache
template_cache = FixTemplateCache()

# ================================================================
# BUGS — validators v0.35.0 (4 bugs for efficiency)
# ================================================================

BUGS = [
    {
        "id": "vld-1-email-type",
        "title": "email validator: 非字符串输入导致未处理的AttributeError",
        "error_type": "类型检查缺失",
        "complexity": "L1",
        "file": "validators/email.py",
        "function": "email",
        "trigger_func": "email",
        "trigger_input": "12345",
        "trigger_expected_type": "value",
        "trigger_expected": False,
        "buggy_code_snippet": "第58行: if not value or value.count('@') != 1 → 当value=12345时, not 12345=False通过, value.count('@')引发未捕获的AttributeError",
        "fix_boundary": (58, 60),
        "regression_tests": [
            {"name": "正常email", "input": "someone@example.com", "expected": True},
            {"name": "整数返回False", "input": "12345", "expected": False},
        ],
        "maintainer_fix": "添加 isinstance(value, str) 检查或扩增validator装饰器捕获AttributeError",
        "maintainer_pr": "https://github.com/python-validators/validators/issues/385"
    },
    {
        "id": "vld-2-card-strip",
        "title": "card_number: 未trim输入导致带空格卡号被拒绝",
        "error_type": "边界条件缺失",
        "complexity": "L1",
        "file": "validators/card.py",
        "function": "card_number",
        "trigger_func": "card_number",
        "trigger_input": " 4242424242424242 ",
        "trigger_expected_type": "value",
        "trigger_expected": True,
        "buggy_code_snippet": "第32行: if not value: return False → 带空格字符串 ' 4242... ' 通过falsy检查但后续int转换失败",
        "fix_boundary": (32, 33),
        "regression_tests": [
            {"name": "有效卡号", "input": "4242424242424242", "expected": True},
            {"name": "空格trim后验证", "input": " 4242424242424242 ", "expected": True},
        ],
        "maintainer_fix": "添加 value = value.strip() 预处理",
        "maintainer_pr": "https://github.com/python-validators/validators/issues/377"
    },
    {
        "id": "vld-3-domain-generator",
        "title": "_IanaTLD._retrieve(): 生成器每次调用重新读取文件",
        "error_type": "性能/逻辑错误(生成器复用)",
        "complexity": "L2",
        "file": "validators/domain.py",
        "function": "domain",
        "trigger_func": "domain",
        "trigger_input": "example.com",
        "trigger_expected_type": "value",
        "trigger_expected": True,
        "buggy_code_snippet": "第36行: return tld in cls._retrieve() → _retrieve()是生成器，每次in操作重新读取_tld.txt",
        "fix_boundary": (32, 38),
        "regression_tests": [
            {"name": "有效domain", "input": "example.com", "expected": True},
            {"name": "子域名", "input": "sub.example.com", "expected": True},
        ],
        "maintainer_fix": "将生成器缓存为set避免重复IO",
        "maintainer_pr": "https://github.com/python-validators/validators/pull/365"
    },
    {
        "id": "vld-4-url-fragment",
        "title": "url: fragment正则过于严格拒绝合法fragment字符",
        "error_type": "正则表达式过度严格",
        "complexity": "L3",
        "file": "validators/url.py",
        "function": "url",
        "trigger_func": "url",
        "trigger_input": "http://example.com/page#section=1&sort=asc",
        "trigger_expected_type": "value",
        "trigger_expected": True,
        "buggy_code_snippet": "第158行: re.fullmatch fragment字符集缺失某些合法字符",
        "fix_boundary": (155, 160),
        "regression_tests": [
            {"name": "标准URL", "input": "http://example.com", "expected": True},
            {"name": "带fragment的URL", "input": "http://example.com/page#section", "expected": True},
            {"name": "fragment含参数", "input": "http://example.com/page#section=1&sort=asc", "expected": True},
        ],
        "maintainer_fix": "扩展fragment正则字符集",
        "maintainer_pr": "https://github.com/python-validators/validators/issues/403"
    },
]


# ================================================================
# TEST & FIX HELPERS
# ================================================================

def read_source(bug):
    file_path = os.path.join(WORK_DIR, bug["file"])
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def apply_fix(bug, fixed_code):
    file_path = os.path.join(WORK_DIR, bug["file"])
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(fixed_code)

def extract_code(output):
    text = output.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text

def quick_verify(bug, fixed_code):
    """Run trigger test via subprocess.
    trigger_expected_type:
      - "exception": original raises exception; fix should NOT raise (bug eliminated)
      - "value": compare result with trigger_expected
    """
    trigger_input = bug["trigger_input"]
    func = bug["trigger_func"]
    
    test_code = textwrap.dedent(f'''
import sys, os
sys.path.insert(0, r"{WORK_DIR}")
os.chdir(r"{WORK_DIR}")
from validators import {func}
import traceback
try:
    result = {func}({repr(trigger_input)})
    print("__RESULT__" + repr(result))
except Exception as e:
    print("__EXCEPTION__" + str(type(e).__name__) + ": " + str(e))
''')
    
    try:
        proc = subprocess.run(
            [sys.executable, "-c", test_code],
            capture_output=True, text=True, timeout=10,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        stdout = proc.stdout.strip()
        
        if "__EXCEPTION__" in stdout:
            # An exception was raised
            exc = stdout.split("__EXCEPTION__", 1)[1].split("\n")[0]
            if bug["trigger_expected_type"] == "exception":
                # Original bug = exception; fix should ELIMINATE it
                # Still getting exception → fix FAILED
                return False, f"Bug not fixed: still raises exception ({exc})"
            # For "value" bugs, exception = FAIL
            return False, f"Unexpected exception: {exc}"
        
        if "__RESULT__" in stdout:
            result_str = stdout.split("__RESULT__", 1)[1].strip()
            try:
                result = eval(result_str)
            except:
                result = result_str
            
            if bug["trigger_expected_type"] == "exception":
                # Bug was an exception; fix eliminated it → PASS
                return True, f"Bug fixed (no more exception). Result: {result}"
            
            # Value comparison (handle ValidationError's bool behavior)
            expected = bug["trigger_expected"]
            # Handle ValidationError: bool(ValidationError) == False
            actual_bool = bool(result) if hasattr(result, '__bool__') else result
            if expected is False and not actual_bool:
                return True, f"OK: {result} (falsy as expected)"
            if expected is True and actual_bool is True:
                return True, f"OK: True"
            if str(result) == str(expected):
                return True, f"OK: {result}"
            return False, f"Expected {expected}, got {result}"
        
        return False, f"Unexpected: {stdout[:200]}"
    except Exception as e:
        return False, f"Subprocess: {e}"


# ================================================================
# HEAD CACHE (P12)
# ================================================================

class HeadCache:
    def __init__(self):
        self.cached_functions = {}
        self.call_graph = {}
        self.is_cold = True
    
    def build_prompt(self, bug, source_code):
        if self.is_cold:
            self.is_cold = False
            prompt = f"""Bug Analysis — COLD START

Bug: {bug['title']} | Function: {bug['function']} | Error: {bug['error_type']}
Location: {bug['buggy_code_snippet']}

Full Source ({bug['file']}):
```python
{source_code}
```

Output JSON: {{"root_cause": "...", "fix": "exact code change", "confidence": "high/medium/low"}}"""
            return prompt, "cold"
        else:
            prompt = f"""Bug Analysis — INCREMENTAL (cache active)

Bug: {bug['title']} | Function: {bug['function']}
Error: {bug['error_type']} | Location: {bug['buggy_code_snippet']}

Target function source:
```python
{source_code}
```

Previously analyzed: {list(self.cached_functions.keys())}

Output JSON: {{"root_cause": "...", "fix": "exact code change", "confidence": "high/medium/low"}}"""
            return prompt, "warm"
    
    def register(self, filepath, func, source):
        self.cached_functions[func] = {"file": filepath, "snippet": source[:500]}


# ================================================================
# RUN BUG (P14 optimized pipeline)
# ================================================================

head_cache = HeadCache()
all_fixes = {}

def run_p14_bug(bug):
    result = {
        "bug_id": bug["id"], "title": bug["title"],
        "error_type": bug["error_type"], "complexity": bug["complexity"],
        "pipeline": "P14-optimized",
        "head_model": None, "head_cache_type": None,
        "template_hit": None,
        "head_usage": {}, "fix_usage": {},
        "verdict": None,
        "tokens_head": 0, "tokens_fix": 0, "tokens_audit": 0,
        "rounds": 0, "fix_code_preview": None,
        "maintainer_fix": bug["maintainer_fix"],
    }
    
    print(f"\n{'='*60}")
    print(f"🐍 [{bug['complexity']}] {bug['id']} — {bug['title']}")
    
    source = read_source(bug)
    print(f"   [0] 源码: {bug['file']} ({len(source)} chars)")
    
    # P13: Template match
    matched = template_cache.match(bug["title"], bug["error_type"], bug["buggy_code_snippet"])
    if matched and bug["complexity"] in ("L1", "L2"):
        best = matched[0]
        fixed = template_cache.apply_template(best, source)
        if fixed:
            ok, msg = quick_verify(bug, fixed)
            if ok:
                apply_fix(bug, fixed)
                result["template_hit"] = best.id
                result["verdict"] = "PASS_TEMPLATE"
                result["fix_code_preview"] = fixed[:300]
                all_fixes[bug["id"]] = {"code": fixed, "passed": True}
                print(f"   ✅ 模板命中: {best.name} (零token)")
                return result
    
    # P11+P12: Layered Head + Cache
    head_model = LIGHT_HEAD if bug["complexity"] in ("L1", "L2") else HEAVY_HEAD
    head_prompt, cache_type = head_cache.build_prompt(bug, source)
    result["head_model"] = head_model
    result["head_cache_type"] = cache_type
    
    print(f"   [1] 蛇头({head_model}, {cache_type}缓存)...")
    
    head_system = 'Output ONLY JSON: {"root_cause": "...", "fix": "exact code change", "confidence": "high/medium/low"}'
    
    head_resp = call_llm(head_model, head_system, head_prompt,
                         temperature=0.3 if head_model == LIGHT_HEAD else 0.0,
                         max_tokens=8192)
    
    if not head_resp["success"]:
        result["verdict"] = "HEAD_FAILED"; result["head_error"] = head_resp["error"]
        print(f"      ❌ {head_resp['error']}")
        return result
    
    result["head_usage"] = head_resp.get("usage", {})
    result["tokens_head"] = head_resp.get("usage", {}).get("total_tokens", 0)
    print(f"      ✅ {result['tokens_head']}t ({cache_type})")
    
    head_cache.register(bug["file"], bug["function"], source)
    
    # Fix Snake
    print(f"   [2] 修复蛇({FIX_SNAKE})...")
    
    fix_prompt = f"""Apply this fix plan:
{head_resp['content'][:800]}

Bug location: {bug['buggy_code_snippet']}

Full source:
```python
{source}
```

Output ONLY the complete fixed file — no markdown, no explanation."""
    
    fix_system = "Apply ONLY the specified fix. Do NOT refactor. Output ONLY the complete fixed code."
    fix_resp = call_llm(FIX_SNAKE, fix_system, fix_prompt, temperature=0.3, max_tokens=8192)
    
    if not fix_resp["success"]:
        result["verdict"] = "FIX_FAILED"; result["fix_error"] = fix_resp["error"]
        print(f"      ❌ {fix_resp['error']}")
        return result
    
    fixed_code = extract_code(fix_resp["content"])
    result["fix_usage"] = fix_resp.get("usage", {})
    result["tokens_fix"] = fix_resp.get("usage", {}).get("total_tokens", 0)
    print(f"      ✅ {result['tokens_fix']}t")
    
    # Quick Verify
    print(f"   [3] 快速验证...")
    ok, msg = quick_verify(bug, fixed_code)
    
    if ok:
        apply_fix(bug, fixed_code)
        result["verdict"] = "PASS_FIX"
        result["fix_code_preview"] = fixed_code[:300]
        result["rounds"] = 1
        all_fixes[bug["id"]] = {"code": fixed_code, "passed": True}
        print(f"      ✅ {msg}")
    else:
        print(f"      ❌ {msg}")
        # Round 2
        print(f"   [4] 第二轮修复...")
        fix2_prompt = f"""Previous fix REJECTED: {msg}

Original:
```python
{source[:2000]}
```

Failed fix:
```python
{fixed_code[:2000]}
```

Output ONLY the corrected complete file."""
        
        fix2_resp = call_llm(FIX_SNAKE, fix_system, fix2_prompt, temperature=0.3, max_tokens=8192)
        if fix2_resp["success"]:
            fixed2 = extract_code(fix2_resp["content"])
            result["fix_usage"]["total_tokens"] = result["fix_usage"].get("total_tokens", 0) + fix2_resp.get("usage", {}).get("total_tokens", 0)
            result["tokens_fix"] = result["fix_usage"]["total_tokens"]
            result["rounds"] = 2
            
            ok2, msg2 = quick_verify(bug, fixed2)
            if ok2:
                apply_fix(bug, fixed2)
                result["verdict"] = "PASS_FIX_R2"
                result["fix_code_preview"] = fixed2[:300]
                all_fixes[bug["id"]] = {"code": fixed2, "passed": True}
                print(f"      ✅ R2通过!")
            else:
                result["verdict"] = "FAIL"
                all_fixes[bug["id"]] = {"code": fixed2, "passed": False}
                print(f"      ❌ 两轮失败: {msg2}")
        else:
            result["verdict"] = "FIX2_FAILED"
    
    # Deterministic Auditor
    if result.get("verdict", "").startswith("PASS"):
        final_code = all_fixes[bug["id"]]["code"]
        audit_rep = auditor.audit(
            repair_id=bug["id"], original_code=source, fixed_code=final_code,
            fix_boundary=bug["fix_boundary"],
            trigger_input=bug.get("trigger_input"), trigger_func=bug["trigger_func"],
            trigger_expected_type=bug["trigger_expected_type"],
            trigger_expected=bug["trigger_expected"],
            regression_tests=bug.get("regression_tests"),
        )
        result["audit_verdict"] = audit_rep.verdict
        result["audit_L1"] = audit_rep.L1
        result["audit_side_effects"] = audit_rep.side_effects
        result["tokens_audit"] = 0
        print(f"   [审计] {audit_rep.verdict} (零token)")
    
    return result


# ================================================================
# BATCH JUDGE (P10)
# ================================================================

def run_batch_judge(bug_results):
    print(f"\n{'='*60}")
    print(f"⚖️  批量法官审查 (P10) — 所有修复一次C1调用")
    
    judged = [r for r in bug_results if r.get("verdict", "").startswith("PASS")]
    if not judged:
        print("   无修复需要审查")
        return {"total_tokens": 0, "judges": [], "per_bug_verdicts": {}}
    
    sections = []
    for i, br in enumerate(judged):
        sections.append(f"""--- Bug {i+1} ---
[Bug ID]: {br['bug_id']}
[Title]: {br['title']}
[Error]: {br['error_type']}
[Fix preview]: {br.get('fix_code_preview', 'N/A')[:150]}
[Rounds]: {br.get('rounds', 1)}""")
    
    batch_prompt = f"""Review {len(sections)} bug fixes from python-validators.
For each, output: [Bug ID]: <id> / [VERDICT]: PASS|FAIL / [REASONING]: brief

{chr(10).join(sections)}"""
    
    judge_system = "C1 code review judge. Review bug fixes, output verdict + reasoning per bug."
    
    results = {"total_tokens": 0, "judges": [], "per_bug_verdicts": {}}
    
    for jname, jmodel, jtemp in [
        ("DS-t0.3", BATCH_JUDGE_DS, 0.3),
        ("Gemini-t0.3", BATCH_JUDGE_GEMINI, 0.3),
    ]:
        print(f"   [{jname}] {jmodel}...")
        resp = call_llm(jmodel, judge_system, batch_prompt, temperature=jtemp, max_tokens=4096)
        if resp.get("success"):
            usage = resp.get("usage", {})
            results["total_tokens"] += usage.get("total_tokens", 0)
            results["judges"].append({"judge": jname, "tokens": usage.get("total_tokens", 0)})
            print(f"      ✅ {usage.get('total_tokens', '?')}t")
        else:
            results["judges"].append({"judge": jname, "error": resp.get("error")})
            print(f"      ❌ {resp.get('error')}")
    
    return results


# ================================================================
# MAIN
# ================================================================

def main():
    load_api_key()
    print(f"{'='*60}")
    print(f"P14: 第二代码库全优化蛇群验证")
    print(f"库: validators v0.35.0 (32个源文件)")
    print(f"优化栈: P10+P11+P12+P13+确定性审计")
    print(f"目标: ≤4,500 t/bug (P8: 8,400 t/bug)")
    print(f"{'='*60}")
    
    results = []
    template_hits = 0
    
    for bug in BUGS:
        try:
            r = run_p14_bug(bug)
            results.append(r)
            if r.get("template_hit"):
                template_hits += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            results.append({"bug_id": bug["id"], "verdict": "FATAL_ERROR", "error": str(e)})
        time.sleep(0.3)
    
    # P10: Batch Judge
    batch_judge = run_batch_judge(results)
    
    # Metrics
    head_total = sum(r.get("tokens_head", 0) for r in results)
    fix_total = sum(r.get("tokens_fix", 0) for r in results)
    audit_total = sum(r.get("tokens_audit", 0) for r in results)
    total_tokens = head_total + fix_total + audit_total
    judge_tokens = batch_judge.get("total_tokens", 0)
    total_with_judge = total_tokens + judge_tokens
    per_bug = total_with_judge / len(BUGS) if BUGS else 0
    
    passed = sum(1 for r in results if r.get("verdict", "").startswith("PASS"))
    
    output = {
        "experiment": "P14-second-library-validation",
        "library": "validators",
        "library_version": "0.35.0",
        "pipeline": "蛇群全优化 (P10-P13组合)",
        "optimizations": {
            "P10_batch_judge": "DS+Gemini, 一次C1调用审查所有修复 (节省~68%)",
            "P11_layered_head": "L1/L2→DeepSeek精简, L3→Claude完整",
            "P12_head_cache": "首bug全文件→后续仅目标函数+缓存 (节省~58%)",
            "P13_fix_templates": "6个模板优先匹配, 命中零token修复",
            "deterministic_auditor": "L1/L2零token规则引擎"
        },
        "date": time.strftime("%Y-%m-%d"),
        "api_provider": "tokeness",
        "bug_count": len(BUGS),
        "bugs": results,
        "batch_judge": batch_judge,
        "metrics": {
            "total_tokens": total_with_judge,
            "per_bug_tokens": round(per_bug, 0),
            "head_tokens": head_total,
            "fix_tokens": fix_total,
            "audit_tokens": audit_total,
            "judge_tokens": judge_tokens,
            "template_hit_count": template_hits,
            "template_hit_rate": f"{template_hits}/{len(BUGS)} ({template_hits*100//len(BUGS)}%)",
            "fix_success_rate": f"{passed}/{len(BUGS)} ({passed*100//len(BUGS)}%)",
        },
        "comparison": {
            "p8_baseline_per_bug": 8400,
            "p14_achieved_per_bug": round(per_bug, 0),
            "reduction_pct": round((8400 - per_bug) / 8400 * 100, 1),
            "target_per_bug": 4500,
            "target_achieved": per_bug <= 4500,
        }
    }
    
    os.makedirs("results", exist_ok=True)
    output_path = "results/p14_second_library.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"📊 P14 结果")
    print(f"{'='*60}")
    print(f"  修复: {passed}/{len(BUGS)} ({passed*100//len(BUGS)}%)")
    print(f"  模板: {template_hits}/{len(BUGS)} ({template_hits*100//len(BUGS)}%)")
    print(f"  Token: {per_bug:.0f}/bug (P8: 8400, -{output['comparison']['reduction_pct']}%)")
    print(f"  目标: {'✅' if per_bug <= 4500 else '❌'} (≤4500t)")
    print(f"  文件: {output_path}")
    
    return output

if __name__ == "__main__":
    main()
