"""
P3: 数据契约+传播原型验证
蛇群依赖系统：契约破损检测 + 不确定性传播
"""
import yaml, json, time, os, requests

# --- Config ---
CONFIG_PATH = os.environ.get('HERMES_CONFIG', os.path.expanduser('~/.hermes/config.yaml'))
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

TOKENESS_BASE = "https://n.tokeness.io/v1"
TOKENESS_KEY = None
for p in config.get('custom_providers', []):
    if p.get('name') == 'tokeness':
        TOKENESS_KEY = p.get('api_key')
        break

if not TOKENESS_KEY:
    print("ERROR: Tokeness API key not found")
    exit(1)

HEADERS = {
    "Authorization": f"Bearer {TOKENESS_KEY}",
    "Content-Type": "application/json"
}

print(f"API Base: {TOKENESS_BASE}")
print(f"Key present: {bool(TOKENESS_KEY)}, length: {len(TOKENESS_KEY)}")


def call_llm(model, prompt, temperature=0.3, max_tokens=1500, timeout=120):
    """Call Tokeness LLM API."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{TOKENESS_BASE}/chat/completions",
                headers=HEADERS,
                json=payload,
                timeout=timeout
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                return {"content": content, "tokens": tokens, "model": model, "error": None}
            else:
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                else:
                    return {"content": "", "tokens": 0, "model": model,
                            "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                return {"content": "", "tokens": 0, "model": model, "error": str(e)}


# --- Test Data ---
ORDERS_CSV = """id,date,amount
1,2024-01-15,100.50
2,2024-01-20,200.00
3,2024-02-10,150.75
4,2024-02-25,300.00
5,2024-03-05,50.25
6,2024-03-18,175.00"""

STEP1_CORRECT = [
    {"id": 1, "date": "2024-01-15", "amount": 100.50},
    {"id": 2, "date": "2024-01-20", "amount": 200.00},
    {"id": 3, "date": "2024-02-10", "amount": 150.75},
    {"id": 4, "date": "2024-02-25", "amount": 300.00},
    {"id": 5, "date": "2024-03-05", "amount": 50.25},
    {"id": 6, "date": "2024-03-18", "amount": 175.00}
]

STEP1_MISSING_FIELD = [
    {"id": 1, "date": "2024-01-15"},
    {"id": 2, "date": "2024-01-20"},
    {"id": 3, "date": "2024-02-10"},
    {"id": 4, "date": "2024-02-25"},
    {"id": 5, "date": "2024-03-05"},
    {"id": 6, "date": "2024-03-18"}
]

STEP1_WRONG_TYPE = [
    {"id": 1, "date": "2024-01-15", "amount": "100.50"},
    {"id": 2, "date": "2024-01-20", "amount": "200.00"},
    {"id": 3, "date": "2024-02-10", "amount": "150.75"},
    {"id": 4, "date": "2024-02-25", "amount": "300.00"},
    {"id": 5, "date": "2024-03-05", "amount": "50.25"},
    {"id": 6, "date": "2024-03-18", "amount": "175.00"}
]

# --- Prompts stored as functions to avoid string escaping issues ---

def make_head1_prompt():
    return """你是蛇群架构的蛇头层（任务规划器）。请为任务"parse_orders"制定执行计划。

【任务】parse_orders(orders_csv: str) -> List[Order]
解析订单CSV文件，每行包含 id, date, amount 三个字段。返回订单对象列表。

请输出：
1. 任务分解（步骤）
2. 输出数据契约(Schema)：列出 expected_output_fields，每个字段注明名称和类型
3. 风险点
4. 不确定性标记

请用以下格式输出Schema契约（重要——后续验证依赖此格式）：
Schema:
expected_output_fields:
- id: int
- date: str
- amount: float"""


def make_body1_prompt(orders_csv):
    return f"""你是蛇群架构的蛇身层（执行器）。执行任务 parse_orders。

【任务】parse_orders(orders_csv)
解析以下订单CSV数据，返回订单对象列表(JSON数组)。

【输入数据】
{orders_csv}

【蛇头规划的Schema】
expected_output_fields:
- id: int
- date: str
- amount: float

【要求】
1. 严格按Schema输出
2. 每行为一个订单对象
3. 输出纯JSON数组（不要markdown代码块标记）

输出格式示例：
[{{"id": 1, "date": "2024-01-15", "amount": 100.5}}, ...]"""


def make_verify1_prompt(step1_output):
    return f"""你是蛇群架构的验证蛇（数据契约校验器）。请验证蛇身输出是否符合蛇头规划的Schema契约。

【蛇头规划的Schema契约】
expected_output_fields:
- id: int
- date: str
- amount: float

【蛇身实际输出】
{step1_output}

请逐字段检查：
1. 所有required字段是否都存在？
2. 每个字段的类型是否正确？
3. 是否有额外未声明的字段？

对每个违反契约的项给出：
- 违反类型: [字段缺失/类型错误/额外字段]
- 具体违反内容
- 建议处理

最后给出契约验证结论，格式：
契约验证: [PASS/FAIL/UNCERTAIN]
违反项数: N
违反详情:
1. ...
不确定性评估: [LOW/MEDIUM/HIGH]
不确定性原因: ...
传播建议: [可传播/标记传播/阻断]"""


def make_head2_prompt(contract_result):
    return f"""你是蛇群架构的蛇头层（任务规划器）。请为任务"compute_monthly_total"制定执行计划。

【任务】compute_monthly_total(orders: List[Order]) -> Dict[str, float]
输入步骤1(parse_orders)的输出——订单列表，按月汇总amount字段。
正确结果应为：
- 2024-01: 300.50 (100.50 + 200.00)
- 2024-02: 450.75 (150.75 + 300.00)
- 2024-03: 225.25 (50.25 + 175.00)

【上游数据契约验证结果（重要！）】
{contract_result}

请基于契约验证结果规划执行策略：
- 如果上游PASS：正常规划按月汇总逻辑
- 如果上游FAIL：规划防御性执行——检查必要字段是否存在、类型是否正确，标记不确定性
- 如果上游UNCERTAIN：规划保守策略——在输出中显式标注不确定性

请输出：
1. 执行计划（根据上游状态调整）
2. 输入防御策略（是否需要前置字段检查）
3. 不确定性传播计划（如果上游有不确定性，输出中如何标记）
4. 输出Schema: expected_output_fields"""


def make_body2_prompt(snake_head_plan, contract_result, step1_output):
    return f"""你是蛇群架构的蛇身层（执行器）。执行任务 compute_monthly_total。

【任务】compute_monthly_total(orders)
按月汇总订单amount字段。
正确结果应为：2024-01:300.50, 2024-02:450.75, 2024-03:225.25

【蛇头规划】
{snake_head_plan}

【上游数据契约验证结果】
{contract_result}

【输入数据——步骤1输出】
{step1_output}

【要求】
1. 如果蛇头规划要求防御性检查，先验证输入字段
2. 按月汇总amount字段
3. 如果上游有不确定性，在输出中标注
4. 输出格式：JSON对象。如果有不确定性，添加 _uncertainty 字段说明

输出："""


def make_output_verify_prompt(contract_result, step1_output, step2_output):
    return f"""你是蛇群架构的验证蛇。请评估步骤2的输出质量，重点关注不确定性传播。

【原始任务】compute_monthly_total——按月汇总订单amount字段

【上游契约验证结果】
{contract_result}

【步骤1输出（上游数据）】
{step1_output}

【步骤2输出（下游计算结果）】
{step2_output}

【正确参考值（手工计算）】
2024-01: 300.50 (100.50 + 200.00)
2024-02: 450.75 (150.75 + 300.00)
2024-03: 225.25 (50.25 + 175.00)

请评估：
1. 步骤2输出是否正确？
2. 步骤2是否检测到了上游的数据问题？
3. 如果上游有数据问题，不确定性是否正确地传播到了步骤2输出中？
4. 步骤2是否采取了防御性措施（如字段检查、类型转换）？

输出格式（每行一个判定）：
正确性: [正确/部分正确/错误/无法判断]
不确定性传播: [正确传播/未传播/部分传播/无需传播]
防御措施: [有/无]
详细评估: (自由文本)"""


def parse_contract_verdict(content):
    """Extract PASS/FAIL/UNCERTAIN from contract verification output."""
    for prefix in ["契约验证: ", "契约验证："]:
        if prefix in content:
            after = content.split(prefix, 1)[1].split("\n")[0].strip()
            if "PASS" in after.upper():
                return "PASS"
            if "FAIL" in after.upper():
                return "FAIL"
            return "UNCERTAIN"
    return "UNCERTAIN"


def parse_output_metrics(content):
    """Extract metrics from output verification."""
    metrics = {"correctness": "未知", "uncertainty_prop": "未知", "defense": "未知"}
    for line in content.split("\n"):
        line_s = line.strip()
        for key, zh_keys in [("correctness", ["正确性:", "正确性："]),
                               ("uncertainty_prop", ["不确定性传播:", "不确定性传播："]),
                               ("defense", ["防御措施:", "防御措施："])]:
            for k in zh_keys:
                if k in line_s:
                    val = line_s.split(k, 1)[1].strip() if k in line_s else ""
                    if val:
                        metrics[key] = val
    return metrics


# ==========================================================
# MAIN EXPERIMENT
# ==========================================================
conditions = [
    {"id": "control", "name": "对照组(正常数据)", "step1_data": STEP1_CORRECT,
     "expected_contract": "PASS", "expected_correct": "正确"},
    {"id": "violation_a", "name": "破损A(字段缺失: amount缺失)", "step1_data": STEP1_MISSING_FIELD,
     "expected_contract": "FAIL", "expected_correct": "错误"},
    {"id": "violation_b", "name": "破损B(类型错误: amount为字符串)", "step1_data": STEP1_WRONG_TYPE,
     "expected_contract": "FAIL", "expected_correct": "部分正确"},
]

all_results = []
total_tokens = 0

print("P3 实验开始")
print(f"{'='*70}")
print(f"3个条件 x 6个API调用 = 18次API调用")
print(f"模型: 蛇头=claude-sonnet-5, 蛇身=deepseek-v4-pro(t=0.3), 验证蛇=gemini-3.6-flash(t=0.3)")
print(f"{'='*70}\n")

for cond in conditions:
    cid = cond["id"]
    print(f"\n{'='*70}")
    print(f"[{cid}] {cond['name']}")
    print(f"  预期契约验证: {cond['expected_contract']}, 预期最终正确性: {cond['expected_correct']}")
    print(f"{'='*70}")

    cr = {"condition_id": cid, "condition_name": cond["name"], "stages": {}}
    ct = 0

    # Stage 1: Snake Head plans step 1
    print("  [1/6] 蛇头规划 parse_orders (claude-sonnet-5)...", end=" ", flush=True)
    r = call_llm("claude-sonnet-5", make_head1_prompt(), temperature=0.3, max_tokens=800)
    ct += r["tokens"]
    cr["stages"]["snake_head_step1"] = {"model": r["model"], "tokens": r["tokens"], "content": r["content"]}
    ok = "ERR" if r["error"] else f"OK ({r['tokens']}t)"
    print(ok)
    if r["error"]:
        print(f"    错误: {r['error']}")

    # Stage 2: Snake Body executes step 1 (LLM generates output for comparison)
    print("  [2/6] 蛇身执行 parse_orders (deepseek-v4-pro)...", end=" ", flush=True)
    r = call_llm("deepseek-v4-pro", make_body1_prompt(ORDERS_CSV), temperature=0.3, max_tokens=800)
    ct += r["tokens"]
    cr["stages"]["snake_body_step1_llm"] = {"model": r["model"], "tokens": r["tokens"], "content": r["content"]}
    print(f"OK ({r['tokens']}t)" if not r["error"] else f"ERR: {r['error']}")

    # Use INJECTED (potentially broken) data as step1 output
    step1_json = json.dumps(cond["step1_data"], ensure_ascii=False, indent=2)

    # Stage 3: Contract Verification
    print("  [3/6] 验证蛇检查契约 (gemini-3.6-flash)...", end=" ", flush=True)
    r = call_llm("gemini-3.6-flash", make_verify1_prompt(step1_json), temperature=0.3, max_tokens=1000)
    ct += r["tokens"]
    cr["stages"]["contract_verification"] = {"model": r["model"], "tokens": r["tokens"], "content": r["content"]}
    print(f"OK ({r['tokens']}t)" if not r["error"] else f"ERR: {r['error']}")

    contract_verdict = parse_contract_verdict(r["content"])
    cr["contract_verdict"] = contract_verdict
    contract_result_text = r["content"]

    # Stage 4: Snake Head plans step 2
    print("  [4/6] 蛇头规划 compute_monthly_total (claude-sonnet-5)...", end=" ", flush=True)
    r = call_llm("claude-sonnet-5", make_head2_prompt(contract_result_text), temperature=0.3, max_tokens=800)
    ct += r["tokens"]
    cr["stages"]["snake_head_step2"] = {"model": r["model"], "tokens": r["tokens"], "content": r["content"]}
    print(f"OK ({r['tokens']}t)" if not r["error"] else f"ERR: {r['error']}")
    snake_head_step2 = r["content"]

    # Stage 5: Snake Body executes step 2
    print("  [5/6] 蛇身执行 compute_monthly_total (deepseek-v4-pro)...", end=" ", flush=True)
    r = call_llm("deepseek-v4-pro",
                 make_body2_prompt(snake_head_step2, contract_result_text, step1_json),
                 temperature=0.3, max_tokens=800)
    ct += r["tokens"]
    cr["stages"]["snake_body_step2"] = {"model": r["model"], "tokens": r["tokens"], "content": r["content"]}
    print(f"OK ({r['tokens']}t)" if not r["error"] else f"ERR: {r['error']}")
    step2_output = r["content"]

    # Stage 6: Output Verification
    print("  [6/6] 验证蛇评估步骤2 (gemini-3.6-flash)...", end=" ", flush=True)
    r = call_llm("gemini-3.6-flash",
                 make_output_verify_prompt(contract_result_text, step1_json, step2_output),
                 temperature=0.3, max_tokens=1000)
    ct += r["tokens"]
    cr["stages"]["output_verification"] = {"model": r["model"], "tokens": r["tokens"], "content": r["content"]}
    print(f"OK ({r['tokens']}t)" if not r["error"] else f"ERR: {r['error']}")

    # Parse output metrics
    metrics = parse_output_metrics(r["content"])
    cr["output_metrics"] = metrics

    cr["total_tokens"] = ct
    total_tokens += ct
    all_results.append(cr)

    print(f"\n  契约验证: {contract_verdict} (预期: {cond['expected_contract']})")
    print(f"  正确性: {metrics['correctness']}")
    print(f"  不确定性传播: {metrics['uncertainty_prop']}")
    print(f"  防御措施: {metrics['defense']}")
    print(f"  本条件Token: {ct}")

    time.sleep(2)

# ==========================================================
# Analysis & Report
# ==========================================================
print(f"\n\n{'='*70}")
print(f"实验完成! 总Token: {total_tokens}")
print(f"{'='*70}")

print("\n=== 汇总报告 ===")
for cr in all_results:
    cv = cr["contract_verdict"]
    m = cr["output_metrics"]
    print(f"\n[{cr['condition_id']}] {cr['condition_name']}")
    print(f"  契约检测: {cv}")
    print(f"  步骤2正确性: {m['correctness']}")
    print(f"  不确定性传播: {m['uncertainty_prop']}")
    print(f"  防御措施: {m['defense']}")

# Contract detection rate
detected = sum(1 for cr in all_results if cr["contract_verdict"] == cr.get("expected_contract", "PASS"))
print(f"\n契约检测率: {detected}/{len(all_results)}")

# Save
results_dir = "<SNAKE_SWARM_DATA>/experiments/results"
os.makedirs(results_dir, exist_ok=True)

final_report = {
    "experiment": "蛇群P3实验：数据契约+传播原型验证",
    "description": "验证依赖链中契约破损能否被检测，不确定性是否正确传播",
    "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "hypothesis": "蛇群的依赖系统能否检测到契约破损？当任务A的输出是任务B的输入时，如果A的输出字段缺失/类型错误，B能否在接收前检测到并正确传播不确定性？",
    "api": {
        "base": TOKENESS_BASE,
        "models": {
            "snake_head": "claude-sonnet-5",
            "snake_body": "deepseek-v4-pro (t=0.3)",
            "verification_snake": "gemini-3.6-flash (t=0.3)"
        }
    },
    "total_tokens": total_tokens,
    "conditions": all_results,
    "analysis": {}
}

# Compute analysis
analysis = {
    "契约检测": {},
    "不确定性传播": {},
    "破损恢复能力": {}
}

for cr in all_results:
    cid = cr["condition_id"]
    cv = cr["contract_verdict"]
    m = cr["output_metrics"]
    analysis["契约检测"][cid] = {
        "条件": cr["condition_name"],
        "检测结论": cv,
        "检测详情": cr["stages"].get("contract_verification", {}).get("content", "")[:300]
    }
    analysis["不确定性传播"][cid] = {
        "条件": cr["condition_name"],
        "传播评估": m["uncertainty_prop"],
        "正确性": m["correctness"],
        "防御措施": m["defense"]
    }

# Contract detection rate  
detected_ok = sum(1 for cr in all_results
                  if (cr["contract_verdict"] == "PASS") == (cr["condition_id"] == "control"))
analysis["契约检测"]["检测率"] = f"契约验证正确率: {detected_ok}/{len(all_results)}（控制组应PASS，破损组应FAIL）"

# Propagation correctness
prop_correct = sum(1 for cr in all_results
                   if cr["output_metrics"]["uncertainty_prop"] in ["正确传播", "无需传播"])
analysis["不确定性传播"]["传播正确性"] = f"传播正确性: {prop_correct}/{len(all_results)}"

# Recovery ability  
analysis["破损恢复能力"] = {
    "说明": "评估蛇群在检测到契约破损后的行为——是否待定、是否继续执行、是否防御性处理",
}

final_report["analysis"] = analysis

output_path = f"{results_dir}/p3_contract_propagation.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(final_report, f, ensure_ascii=False, indent=2)

print(f"\n结果已保存: {output_path}")

# Print Chinese summary
print("\n" + "="*70)
print("  P3 实验结论（中文）")
print("="*70)
print(f"\n契约检测率: {analysis['契约检测']['检测率']}")
print(f"传播正确性: {analysis['不确定性传播']['传播正确性']}")
for cr in all_results:
    m = cr["output_metrics"]
    cv = cr["contract_verdict"]
    print(f"\n{cr['condition_name']}:")
    print(f"  - 契约检测: {cv}")
    print(f"  - 步骤2正确性: {m['correctness']}")
    print(f"  - 不确定性传播: {m['uncertainty_prop']}")
    print(f"  - 防御措施: {m['defense']}")

print("\nDONE")
