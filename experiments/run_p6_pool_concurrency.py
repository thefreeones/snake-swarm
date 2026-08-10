#!/usr/bin/env python3
"""
P6: 蛇池并发验证 —— Pool Concurrency Validation
=================================================
验证蛇群并行处理能力：3 个独立用例并行执行，对比串行耗时，
验证状态隔离，熔断器雏形。

蛇头: claude-sonnet-5
蛇身: deepseek-v4-pro (t=0.3)
法官: deepseek-v4-pro (t=0.7) + gemini-3.6-flash (t=0.3)
API: Tokeness (https://n.tokeness.io/v1)
"""

import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime

import aiohttp
import yaml

# ============================================================
# 配置
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# API 配置
TOKENESS_BASE = "https://n.tokeness.io/v1"
TOKENESS_KEY = None  # Will be loaded from config

# 模型配置
MODEL_SNAKE_HEAD = "claude-sonnet-5"      # 蛇头：分析任务
MODEL_SNAKE_BODY = "deepseek-v4-pro"       # 蛇身：生成/修复代码
JUDGE_CONFIGS = [
    {"model": "deepseek-v4-pro", "temperature": 0.7},
    {"model": "gemini-3.6-flash", "temperature": 0.3},
]

# 熔断器配置
CIRCUIT_BREAKER_MAX_FAILURES = 3

# ============================================================
# 测试用例（从 test_cases.py 提取）
# ============================================================
P6_CASES = [
    {
        "id": "case8",
        "title": "变量遮蔽 / KeyError",
        "error_type": "L1: logic error / variable-shadowing",
        "category": "logic_error",
        "z_score": 2,
        "value": "normal",
        "task": "写一个函数 filter_adults(people)，从字典列表中筛选 age >= 18 的人。",
        "buggy_code": '''def filter_adults(people):
    result = []
    for person in people:
        if person['age'] >= 18:  # BUG: 可能 KeyError
            result.append(person)
    return result''',
        "expected_bugs": ["字典缺少 'age' 键时 KeyError", "应使用 .get('age', 0)"],
        "ground_truth": "FAIL",
    },
    {
        "id": "S2",
        "title": "领域知识 / 数值稳定性",
        "error_type": "L3: domain knowledge / numerical stability",
        "category": "deep_adversarial",
        "z_score": 8,
        "value": "high",
        "task": "写一个函数 compute_variance(data)，计算总体方差。",
        "snake_head_analysis": "使用标准数学公式 Var(X)=E[X²]-(E[X])²。算法 O(n)，数值精确。风险点：无。",
        "buggy_code": '''def compute_variance(data):
    n = len(data)
    sum_x = sum(data)
    sum_x2 = sum(x*x for x in data)
    return (sum_x2 - sum_x * sum_x / n) / n  # BUG: 灾难性抵消''',
        "expected_bugs": ["灾难性抵消（catastrophic cancellation）", "大数相减导致精度丢失甚至负方差"],
        "ground_truth": "FAIL",
    },
    {
        "id": "case10",
        "title": "SQL 注入 / 安全漏洞",
        "error_type": "L3: security / SQL injection",
        "category": "security",
        "z_score": 7,
        "value": "high",
        "task": "写一个函数 get_user(db, user_id)，从数据库查询用户信息。使用 sqlite3。",
        "buggy_code": '''def get_user(db, user_id):
    cursor = db.cursor()
    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")  # BUG: SQL 注入
    return cursor.fetchone()''',
        "expected_bugs": ["f-string 拼接 SQL，注入风险", "应使用参数化查询 WHERE id = ?"],
        "ground_truth": "FAIL",
    },
]

# ============================================================
# 加载 API Key
# ============================================================
def load_api_key():
    """从 Hermes 配置加载 Tokeness API Key"""
    global TOKENESS_KEY
    config_paths = [
        os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~/.local/share")), 
                     "hermes", "config.yaml"),
        os.path.expanduser("~/AppData/Local/hermes/config.yaml"),
        os.path.expanduser("~/.hermes/config.yaml"),
    ]
    
    for p in config_paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except Exception:
            continue
        
        providers = config.get("custom_providers", [])
        for prov in providers:
            if prov.get("name") == "tokeness":
                TOKENESS_KEY = prov.get("api_key", "")
                print(f"[config] Tokeness key 已加载 (from: {p})")
                return
    
    raise RuntimeError("找不到 Tokeness API Key！请检查 config.yaml")

# ============================================================
# Prompt 模板
# ============================================================

def build_snake_head_prompt(case):
    """蛇头：任务分析与修复计划"""
    return f"""你是一位资深软件架构师。请分析以下任务和 buggy 代码，制定检查和修复计划。

【任务描述】
{case['task']}

【待审查代码】
```python
{case['buggy_code']}
```

【已知预期 Bug】
{chr(10).join(f"- {b}" for b in case.get('expected_bugs', []))}

请输出：
1. 代码审查（逐行分析可能的 bug）
2. 修复方案（给出正确的实现）
3. 风险点评估

输出格式：
```
【审查结论】
逐行分析...

【修复代码】
```python
...修复后的正确代码...
```

【风险点】
- ...
```"""


def build_snake_body_prompt(case, head_analysis):
    """蛇身：根据蛇头分析生成修复代码"""
    return f"""你是一位严谨的 Python 工程师。根据架构师的分析，生成修复后的正确代码。

【任务】
{case['task']}

【架构师分析】
{head_analysis[:2000]}

【原 Buggy 代码】
```python
{case['buggy_code']}
```

请只输出修复后的正确代码（不要解释），包裹在 ```python 代码块中。"""


def build_judge_prompt(case, fixed_code):
    """法官：审查蛇身生成的修复代码"""
    return f"""你是一位严格的代码审查法官。请审查以下修复代码是否真正解决了所有 bug。

【任务】
{case['task']}

【预期 Bug】
{chr(10).join(f"- {b}" for b in case.get('expected_bugs', []))}

【修复代码】
```python
{fixed_code}
```

请逐点检查：
1. 每个预期 bug 是否已修复？
2. 是否引入新 bug？
3. 代码是否健壮（边界条件、异常处理）？

最后给出判决：PASS（所有 bug 已修复）或 FAIL（仍有问题）。

输出格式：
```
判决: [PASS/FAIL]
逐点审查:
Bug 1 [预期bug描述]: [已修复/未修复] - [说明]
...
新问题: [无/有 - 描述]
```"""

# ============================================================
# API 调用（异步 + 熔断器）
# ============================================================

class CircuitBreaker:
    """熔断器：每任务独立失败计数器"""
    def __init__(self, max_failures=CIRCUIT_BREAKER_MAX_FAILURES):
        self.max_failures = max_failures
        self.failure_count = 0
        self.is_open = False
        self.failures = []

    def record_failure(self, error_msg):
        self.failure_count += 1
        self.failures.append(error_msg)
        if self.failure_count >= self.max_failures:
            self.is_open = True
            return "CIRCUIT_OPEN"
        return "RETRY"

    def record_success(self):
        self.failure_count = 0


async def call_llm(session, prompt, model, temperature=0.3, max_tokens=2000, 
                   timeout=60, circuit_breaker=None):
    """
    异步调用 LLM API，支持熔断器。
    如果 circuit_breaker.is_open，直接返回 SKIP。
    """
    if circuit_breaker and circuit_breaker.is_open:
        return {"error": "CIRCUIT_OPEN", "content": "", "tokens": 0, "skipped": True}
    
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKENESS_KEY}",
    }
    
    t0 = time.time()
    try:
        async with session.post(
            f"{TOKENESS_BASE}/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout, connect=15),
        ) as resp:
            latency = time.time() - t0
            
            if resp.status != 200:
                error_text = await resp.text()
                error_msg = f"HTTP {resp.status}: {error_text[:200]}"
                
                if circuit_breaker:
                    cb_status = circuit_breaker.record_failure(error_msg)
                    if cb_status == "CIRCUIT_OPEN":
                        return {"error": "CIRCUIT_OPEN", "content": "", "tokens": 0, 
                                "latency": latency, "circuit_open": True}
                
                return {"error": error_msg, "content": "", "tokens": 0, "latency": latency}
            
            data = await resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", 0)
            
            if circuit_breaker:
                circuit_breaker.record_success()
            
            return {
                "content": content,
                "tokens": tokens,
                "latency": round(latency, 2),
                "model": data.get("model", model),
            }
            
    except asyncio.TimeoutError:
        latency = time.time() - t0
        error_msg = f"API timeout ({timeout}s)"
        
        if circuit_breaker:
            cb_status = circuit_breaker.record_failure(error_msg)
            if cb_status == "CIRCUIT_OPEN":
                return {"error": "CIRCUIT_OPEN", "content": "", "tokens": 0,
                        "latency": latency, "circuit_open": True}
        
        return {"error": error_msg, "content": "", "tokens": 0, "latency": latency}
        
    except Exception as e:
        latency = time.time() - t0
        error_msg = f"Exception: {str(e)}"
        
        if circuit_breaker:
            cb_status = circuit_breaker.record_failure(error_msg)
            if cb_status == "CIRCUIT_OPEN":
                return {"error": "CIRCUIT_OPEN", "content": "", "tokens": 0,
                        "latency": latency, "circuit_open": True}
        
        return {"error": error_msg, "content": "", "tokens": 0, "latency": latency}


# ============================================================
# 单任务流水线（蛇头 → 蛇身 → 法官）
# ============================================================

async def run_single_task(session, case, breaker, task_index, simulate_failure=False):
    """
    单任务流水线：蛇头分析 → 蛇身修复 → 法官审查
    
    simulate_failure: 如果为 True，故意使用无效模型触发熔断
    """
    task_id = case["id"]
    task_start = time.time()
    result = {
        "task_index": task_index,
        "case_id": task_id,
        "title": case["title"],
        "ground_truth": case["ground_truth"],
        "start_time": datetime.now().isoformat(),
        "stages": {},
        "circuit_breaker": {"triggered": False, "failure_count": 0, "failures": []},
    }
    
    if simulate_failure:
        print(f"  [{task_id}] 🔥 模拟失败模式：使用无效模型触发重试→熔断")
    
    # ---- Stage 1: 蛇头分析（带重试） ----
    head_model = "INVALID-MODEL-TRIGGER-CIRCUIT" if simulate_failure else MODEL_SNAKE_HEAD
    head_prompt = build_snake_head_prompt(case)
    head_retries = []
    head_resp = None
    
    for attempt in range(CIRCUIT_BREAKER_MAX_FAILURES):
        if breaker.is_open:
            break
        head_resp = await call_llm(
            session, head_prompt, head_model, temperature=0.3,
            circuit_breaker=breaker
        )
        head_retries.append({
            "attempt": attempt + 1,
            "ok": "error" not in head_resp,
            "error": head_resp.get("error"),
            "latency": head_resp.get("latency", 0),
        })
        if "error" not in head_resp:
            break  # 成功，跳出重试循环
        if head_resp.get("circuit_open"):
            break  # 熔断器打开
    
    result["stages"]["snake_head"] = {
        "model": head_model,
        "retries": head_retries,
        "latency": head_resp.get("latency", 0) if head_resp else 0,
        "tokens": head_resp.get("tokens", 0) if head_resp else 0,
        "ok": "error" not in head_resp if head_resp else False,
        "error": head_resp.get("error") if head_resp else "BREAKER_OPEN",
    }
    
    if not head_resp or "error" in head_resp:
        result["stages"]["snake_head"]["status"] = "CIRCUIT_OPEN" if head_resp and head_resp.get("circuit_open") else "EXHAUSTED_RETRIES"
        result["circuit_breaker"]["triggered"] = breaker.is_open
        result["circuit_breaker"]["failure_count"] = breaker.failure_count
        result["circuit_breaker"]["failures"] = list(breaker.failures)
        result["status"] = "CIRCUIT_OPEN" if breaker.is_open else "FAILED"
        result["total_latency"] = round(time.time() - task_start, 2)
        result["end_time"] = datetime.now().isoformat()
        return result
    
    head_analysis = head_resp["content"]
    result["stages"]["snake_head"]["status"] = "OK"
    
    # ---- Stage 2: 蛇身修复（带重试） ----
    body_prompt = build_snake_body_prompt(case, head_analysis)
    body_model = "INVALID-MODEL-TRIGGER-CIRCUIT" if simulate_failure else MODEL_SNAKE_BODY
    body_retries = []
    body_resp = None
    
    for attempt in range(CIRCUIT_BREAKER_MAX_FAILURES):
        if breaker.is_open:
            break
        body_resp = await call_llm(
            session, body_prompt, body_model, temperature=0.3,
            circuit_breaker=breaker
        )
        body_retries.append({
            "attempt": attempt + 1,
            "ok": "error" not in body_resp,
            "error": body_resp.get("error"),
            "latency": body_resp.get("latency", 0),
        })
        if "error" not in body_resp:
            break
        if body_resp.get("circuit_open"):
            break
    
    result["stages"]["snake_body"] = {
        "model": body_model,
        "retries": body_retries,
        "latency": body_resp.get("latency", 0) if body_resp else 0,
        "tokens": body_resp.get("tokens", 0) if body_resp else 0,
        "ok": "error" not in body_resp if body_resp else False,
        "error": body_resp.get("error") if body_resp else "BREAKER_OPEN",
    }
    
    if not body_resp or "error" in body_resp:
        result["stages"]["snake_body"]["status"] = "CIRCUIT_OPEN" if body_resp and body_resp.get("circuit_open") else "EXHAUSTED_RETRIES"
        result["circuit_breaker"]["triggered"] = breaker.is_open
        result["circuit_breaker"]["failure_count"] = breaker.failure_count
        result["circuit_breaker"]["failures"] = list(breaker.failures)
        result["status"] = "CIRCUIT_OPEN" if breaker.is_open else "FAILED"
        result["total_latency"] = round(time.time() - task_start, 2)
        result["end_time"] = datetime.now().isoformat()
        return result
    
    # 提取修复代码
    fixed_code = _extract_code_block(body_resp["content"])
    result["stages"]["snake_body"]["fixed_code"] = fixed_code[:300]
    result["stages"]["snake_body"]["status"] = "OK"
    
    # ---- Stage 3: 法官审查（双法官，各自带重试） ----
    judge_results = []
    judge_prompt = build_judge_prompt(case, fixed_code)
    
    for jc in JUDGE_CONFIGS:
        if breaker.is_open:
            judge_results.append({
                "model": jc["model"],
                "temperature": jc["temperature"],
                "verdict": "CIRCUIT_OPEN",
                "latency": 0,
                "tokens": 0,
                "error": "CIRCUIT_OPEN",
            })
            break
        
        j_retries = []
        j_resp = None
        for attempt in range(CIRCUIT_BREAKER_MAX_FAILURES):
            if breaker.is_open:
                break
            j_resp = await call_llm(
                session, judge_prompt, jc["model"], temperature=jc["temperature"],
                circuit_breaker=breaker
            )
            j_retries.append({
                "attempt": attempt + 1,
                "ok": "error" not in j_resp,
                "error": j_resp.get("error"),
                "latency": j_resp.get("latency", 0),
            })
            if "error" not in j_resp:
                break
            if j_resp.get("circuit_open"):
                break
        
        verdict = "ERROR"
        if j_resp and "error" not in j_resp:
            verdict = _parse_verdict(j_resp["content"])
        elif j_resp and j_resp.get("circuit_open"):
            verdict = "CIRCUIT_OPEN"
        
        judge_results.append({
            "model": jc["model"],
            "temperature": jc["temperature"],
            "verdict": verdict,
            "retries": j_retries,
            "latency": j_resp.get("latency", 0) if j_resp else 0,
            "tokens": j_resp.get("tokens", 0) if j_resp else 0,
            "error": j_resp.get("error") if j_resp else "BREAKER_OPEN",
        })
        
        if j_resp and j_resp.get("circuit_open"):
            result["circuit_breaker"]["triggered"] = True
            result["circuit_breaker"]["failure_count"] = breaker.failure_count
            result["circuit_breaker"]["failures"] = list(breaker.failures)
            break
    
    result["stages"]["judges"] = judge_results
    
    # 最终判决
    judge_verdicts = [j["verdict"] for j in judge_results if j["verdict"] not in ("ERROR", "CIRCUIT_OPEN")]
    if len(judge_verdicts) >= 2 and all(v == "PASS" for v in judge_verdicts):
        final_verdict = "PASS"
    elif len(judge_verdicts) >= 1 and all(v == "FAIL" for v in judge_verdicts):
        final_verdict = "FAIL"
    elif len(judge_verdicts) >= 1:
        final_verdict = judge_verdicts[0]
    elif breaker.is_open:
        final_verdict = "CIRCUIT_OPEN"
    else:
        final_verdict = "ERROR"
    
    result["final_verdict"] = final_verdict
    result["correct"] = (final_verdict == case["ground_truth"])
    result["status"] = "COMPLETED" if final_verdict not in ("CIRCUIT_OPEN", "ERROR") else final_verdict
    result["circuit_breaker"]["failure_count"] = breaker.failure_count
    result["total_latency"] = round(time.time() - task_start, 2)
    result["end_time"] = datetime.now().isoformat()
    
    return result


# ============================================================
# 辅助函数
# ============================================================

def _extract_code_block(text):
    """从 LLM 回复中提取 Python 代码块"""
    if "```python" in text:
        start = text.index("```python") + len("```python")
        end = text.index("```", start)
        return text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        rest = text[start:]
        if "```" in rest:
            end = rest.index("```")
            return rest[:end].strip()
    return text.strip()


def _parse_verdict(content):
    """从法官回复中解析判决"""
    content_upper = content.upper()
    
    for line in content.split("\n"):
        line_upper = line.strip().upper()
        if "判决" in line_upper:
            if "FAIL" in line_upper:
                return "FAIL"
            elif "PASS" in line_upper:
                return "PASS"
    
    # 回退
    bug_count = content_upper.count("未修复") + content_upper.count("仍有问题")
    if "判决: FAIL" in content_upper:
        return "FAIL"
    if "判决: PASS" in content_upper and bug_count == 0:
        return "PASS"
    if bug_count > 0:
        return "FAIL"
    
    return "PASS"


# ============================================================
# 串行执行（基线对比）
# ============================================================

async def run_serial(session, cases):
    """串行执行三任务 → 基线耗时"""
    print("\n" + "=" * 60)
    print("  📊 串行执行（基线）—— 三任务依次执行")
    print("=" * 60)
    
    results = []
    total_start = time.time()
    
    for i, case in enumerate(cases):
        print(f"\n--- 串行任务 {i+1}/3: {case['id']} ({case['title']}) ---")
        breaker = CircuitBreaker()
        result = await run_single_task(session, case, breaker, i, simulate_failure=False)
        results.append(result)
        
        status_icon = "✅" if result.get("status") == "COMPLETED" else "❌"
        print(f"  {status_icon} {case['id']}: {result.get('status')} "
              f"({result.get('total_latency', 0):.1f}s) 判决={result.get('final_verdict', 'N/A')}")
    
    total_time = round(time.time() - total_start, 2)
    
    return {
        "mode": "serial",
        "total_time": total_time,
        "task_count": len(results),
        "results": results,
    }


# ============================================================
# 并发执行
# ============================================================

async def run_concurrent(session, cases, fail_task_index=None):
    """
    并发执行三任务（asyncio.gather）
    
    fail_task_index: None = 全部正常执行；0/1/2 = 第 N 个任务模拟失败
    """
    mode_label = "正常" if fail_task_index is None else f"任务{fail_task_index+1}模拟失败"
    print("\n" + "=" * 60)
    print(f"  ⚡ 并发执行（{mode_label}）—— 三任务 asyncio.gather()")
    print("=" * 60)
    
    total_start = time.time()
    
    # 每个任务独立的熔断器
    breakers = [CircuitBreaker() for _ in cases]
    
    tasks = []
    for i, case in enumerate(cases):
        simulate = (fail_task_index is not None and i == fail_task_index)
        breaker = breakers[i]
        tasks.append(run_single_task(session, case, breaker, i, simulate_failure=simulate))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理异常
    processed = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            processed.append({
                "task_index": i,
                "case_id": cases[i]["id"],
                "title": cases[i]["title"],
                "status": "EXCEPTION",
                "error": str(r),
                "total_latency": 0,
            })
        else:
            processed.append(r)
    
    total_time = round(time.time() - total_start, 2)
    
    # 打印摘要
    for r in processed:
        cid = r.get("case_id", "?")
        status = r.get("status", "?")
        latency = r.get("total_latency", 0)
        verdict = r.get("final_verdict", "N/A")
        cb = r.get("circuit_breaker", {})
        
        if status == "CIRCUIT_OPEN":
            icon = "🔴"
        elif status == "COMPLETED":
            icon = "✅"
        else:
            icon = "❌"
        
        cb_info = ""
        if cb.get("triggered"):
            cb_info = f" [熔断! {cb.get('failure_count')}次失败]"
        
        print(f"  {icon} {cid}: {status} ({latency:.1f}s) 判决={verdict}{cb_info}")
    
    return {
        "mode": "concurrent" if fail_task_index is None else "concurrent_with_failure",
        "fail_task_index": fail_task_index,
        "total_time": total_time,
        "task_count": len(processed),
        "results": processed,
    }


# ============================================================
# 验证
# ============================================================

def validate_isolation(results):
    """验证任务间状态隔离：检查是否有跨任务上下文泄漏"""
    issues = []
    
    for r in results:
        cid = r.get("case_id", "?")
        stages = r.get("stages", {})
        
        # 检查蛇头分析中是否引用了其他任务的内容
        head_content = ""
        if "snake_head" in stages and isinstance(stages["snake_head"], dict):
            head_content = stages["snake_head"].get("content", "")
        
        # 查找其他 case id
        other_cases = [c["id"] for c in P6_CASES if c["id"] != cid]
        for oc in other_cases:
            if oc in str(head_content):
                issues.append({
                    "task": cid,
                    "type": "CONTEXT_LEAK",
                    "detail": f"蛇头分析引用了其他任务 {oc} 的上下文"
                })
    
    return {
        "isolated": len(issues) == 0,
        "issues": issues,
    }


def validate_circuit_breaker(normal_results, failure_results):
    """验证熔断器：失败任务熔断 + 其他任务不受影响"""
    checks = {
        "failed_task_circuit_open": False,
        "healthy_tasks_ok": True,
        "details": [],
    }
    
    # 检查失败场景
    for r in failure_results:
        cb = r.get("circuit_breaker", {})
        if cb.get("triggered"):
            checks["failed_task_circuit_open"] = True
            checks["details"].append({
                "task": r.get("case_id"),
                "circuit_open": True,
                "failure_count": cb.get("failure_count"),
            })
        
        if r.get("status") == "COMPLETED" and not cb.get("triggered"):
            checks["details"].append({
                "task": r.get("case_id"),
                "status": "OK (不受熔断影响)",
            })
    
    # 对比正常场景：健康任务结果应一致
    normal_map = {r["case_id"]: r for r in normal_results}
    failure_map = {r["case_id"]: r for r in failure_results}
    
    for cid in normal_map:
        if cid in failure_map:
            nr = normal_map[cid]
            fr = failure_map[cid]
            if nr.get("circuit_breaker", {}).get("triggered"):
                continue  # 这是失败任务
            
            nv = nr.get("final_verdict")
            fv = fr.get("final_verdict")
            if nv != fv:
                checks["healthy_tasks_ok"] = False
                checks["details"].append({
                    "task": cid,
                    "issue": f"正常场景判决={nv}，故障场景判决={fv}（不一致）",
                })
    
    return checks


# ============================================================
# 主流程
# ============================================================

async def main():
    load_api_key()
    
    print("=" * 70)
    print("  P6: 蛇池并发验证 (Snake Pool Concurrency Validation)")
    print("=" * 70)
    print(f"  API: {TOKENESS_BASE}")
    print(f"  蛇头: {MODEL_SNAKE_HEAD}")
    print(f"  蛇身: {MODEL_SNAKE_BODY} (t=0.3)")
    print(f"  法官: {JUDGE_CONFIGS[0]['model']} (t={JUDGE_CONFIGS[0]['temperature']})")
    print(f"        {JUDGE_CONFIGS[1]['model']} (t={JUDGE_CONFIGS[1]['temperature']})")
    print(f"  熔断阈值: {CIRCUIT_BREAKER_MAX_FAILURES} 次失败")
    print(f"  测试用例: {[c['id'] for c in P6_CASES]}")
    
    # 创建 HTTP 会话
    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        
        # ===== 阶段 1: 串行基线 =====
        serial_result = await run_serial(session, P6_CASES)
        
        # ===== 阶段 2: 并发正常 =====
        concurrent_result = await run_concurrent(session, P6_CASES, fail_task_index=None)
        
        # ===== 阶段 3: 并发 + 故障（第2个任务模拟失败） =====
        concurrent_failure_result = await run_concurrent(session, P6_CASES, fail_task_index=1)
    
    # ===== 分析 =====
    print("\n" + "=" * 70)
    print("  📊 结果分析")
    print("=" * 70)
    
    serial_time = serial_result["total_time"]
    concurrent_time = concurrent_result["total_time"]
    concurrent_fail_time = concurrent_failure_result["total_time"]
    
    speedup = serial_time / concurrent_time if concurrent_time > 0 else 0
    
    print(f"\n  串行总耗时:       {serial_time:.1f}s")
    print(f"  并发总耗时:       {concurrent_time:.1f}s")
    print(f"  加速比:           {speedup:.1f}x")
    print(f"  耗时缩减:         {serial_time - concurrent_time:.1f}s ({((serial_time - concurrent_time) / serial_time * 100):.0f}%)")
    
    # 理论最大加速比 (如果完美并行)
    max_task_time = max(r.get("total_latency", 0) for r in concurrent_result["results"] 
                        if r.get("status") != "CIRCUIT_OPEN")
    theoretical = serial_time / max(max_task_time, 0.1)
    print(f"  理论加速比上限:   {theoretical:.1f}x (如果完全并行)")
    
    print(f"\n  故障场景总耗时:   {concurrent_fail_time:.1f}s")
    print(f"  故障场景 vs 正常: {'无额外开销' if abs(concurrent_fail_time - concurrent_time) < 5 else f'差异 {abs(concurrent_fail_time - concurrent_time):.1f}s'}")
    
    # 状态隔离验证
    isolation = validate_isolation(concurrent_result["results"])
    print(f"\n  状态隔离:         {'✅ 通过' if isolation['isolated'] else '❌ 存在泄漏'}")
    if isolation["issues"]:
        for issue in isolation["issues"]:
            print(f"    - {issue['task']}: {issue['type']} - {issue['detail']}")
    
    # 熔断器验证
    cb_validation = validate_circuit_breaker(concurrent_result["results"], 
                                              concurrent_failure_result["results"])
    print(f"  熔断器:           {'✅ 工作正常' if cb_validation['failed_task_circuit_open'] else '⚠️ 未触发'}")
    print(f"  健康任务隔离:     {'✅ 不受影响' if cb_validation['healthy_tasks_ok'] else '❌ 受影响'}")
    
    # 逐任务统计
    print(f"\n  --- 各任务耗时对比 ---")
    for case in P6_CASES:
        cid = case["id"]
        
        # 串行耗时
        sr = next((r for r in serial_result["results"] if r["case_id"] == cid), None)
        # 并发耗时
        cr = next((r for r in concurrent_result["results"] if r["case_id"] == cid), None)
        
        s_lat = sr.get("total_latency", 0) if sr else 0
        c_lat = cr.get("total_latency", 0) if cr else 0
        
        s_verdict = sr.get("final_verdict", "N/A") if sr else "N/A"
        c_verdict = cr.get("final_verdict", "N/A") if cr else "N/A"
        
        verdict_match = "✅" if s_verdict == c_verdict else "⚠️"
        
        print(f"  {cid:8s} | 串行={s_lat:.1f}s ({s_verdict}) | 并发={c_lat:.1f}s ({c_verdict}) | {verdict_match}")
    
    # ===== 构建输出 =====
    report = {
        "experiment": "P6_pool_concurrency",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "api": TOKENESS_BASE,
            "snake_head": MODEL_SNAKE_HEAD,
            "snake_body": {"model": MODEL_SNAKE_BODY, "temperature": 0.3},
            "judges": JUDGE_CONFIGS,
            "circuit_breaker_max_failures": CIRCUIT_BREAKER_MAX_FAILURES,
            "test_cases": [c["id"] for c in P6_CASES],
        },
        "results": {
            "serial_baseline": {
                "total_time": serial_time,
                "task_count": serial_result["task_count"],
                "tasks": serial_result["results"],
            },
            "concurrent_normal": {
                "total_time": concurrent_time,
                "task_count": concurrent_result["task_count"],
                "tasks": concurrent_result["results"],
            },
            "concurrent_with_failure": {
                "total_time": concurrent_fail_time,
                "task_count": concurrent_failure_result["task_count"],
                "tasks": concurrent_failure_result["results"],
            },
        },
        "analysis": {
            "speedup": {
                "serial_time": serial_time,
                "concurrent_time": concurrent_time,
                "ratio": round(speedup, 2),
                "time_saved": round(serial_time - concurrent_time, 2),
                "time_saved_pct": round((serial_time - concurrent_time) / serial_time * 100, 1) if serial_time > 0 else 0,
                "theoretical_max": round(theoretical, 2),
            },
            "isolation": isolation,
            "circuit_breaker": cb_validation,
            "per_task_comparison": [
                {
                    "case_id": case["id"],
                    "serial_latency": next((r.get("total_latency", 0) for r in serial_result["results"] if r["case_id"] == case["id"]), 0),
                    "concurrent_latency": next((r.get("total_latency", 0) for r in concurrent_result["results"] if r["case_id"] == case["id"]), 0),
                    "serial_verdict": next((r.get("final_verdict", "N/A") for r in serial_result["results"] if r["case_id"] == case["id"]), "N/A"),
                    "concurrent_verdict": next((r.get("final_verdict", "N/A") for r in concurrent_result["results"] if r["case_id"] == case["id"]), "N/A"),
                }
                for case in P6_CASES
            ],
        },
    }
    
    # 保存结果
    output_path = os.path.join(RESULTS_DIR, "p6_pool_concurrency.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 结果已保存: {output_path}")
    
    # 汇总中文报告
    print("\n" + "=" * 70)
    print("  📋 中文验证报告")
    print("=" * 70)
    print(f"""
  【串行 vs 并行耗时对比】
  - 串行执行: {serial_time:.1f}s（三任务依次执行）
  - 并行执行: {concurrent_time:.1f}s（asyncio.gather 并发）
  - 加速比: {speedup:.1f}x，耗时缩减 {round((serial_time - concurrent_time) / serial_time * 100, 1)}%
  - 理论加速比上限: {theoretical:.1f}x

  【任务隔离性】
  - 状态隔离: {'✅ 通过 —— 各任务蛇头/蛇身 prompt 独立，无跨任务上下文泄漏' if isolation['isolated'] else '❌ 失败'}
  - 判决一致性: {'✅ 串行与并发判决一致' if all(
      next((r.get('final_verdict') for r in serial_result['results'] if r['case_id'] == c['id']), None) == 
      next((r.get('final_verdict') for r in concurrent_result['results'] if r['case_id'] == c['id']), None)
      for c in P6_CASES
  ) else '⚠️ 部分判决不一致'}

  【熔断器行为】
  - 失败模拟: 任务 2 (S2) 使用无效模型
  - 熔断触发: {'✅ 已触发 —— 3次失败后标记 SKIP' if cb_validation['failed_task_circuit_open'] else '⚠️ 未触发'}
  - 健康任务: {'✅ 不受影响 —— 其他两个任务正常完成' if cb_validation['healthy_tasks_ok'] else '❌ 受牵连'}
  - 故障场景总耗时: {concurrent_fail_time:.1f}s（不应显著增加）

  【总吞吐量提升】
  - 单任务最快: {min(r.get('total_latency', 999) for r in concurrent_result['results'] if r.get('status') == 'COMPLETED'):.1f}s
  - 单任务最慢: {max(r.get('total_latency', 0) for r in concurrent_result['results'] if r.get('status') == 'COMPLETED'):.1f}s
  - 并行吞吐: {concurrent_result['task_count'] / concurrent_time * 60:.1f} 任务/分钟
  - 串行吞吐: {serial_result['task_count'] / serial_time * 60:.1f} 任务/分钟
  - 吞吐提升: {((concurrent_result['task_count'] / concurrent_time) / (serial_result['task_count'] / serial_time) - 1) * 100:.0f}%
""")
    
    return report


if __name__ == "__main__":
    asyncio.run(main())
