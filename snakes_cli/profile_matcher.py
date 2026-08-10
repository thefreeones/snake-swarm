"""
蛇群任务剖面匹配器 v2.1
Z_eff 查表矩阵 + 机制去重 + 上下文兼容性 + V轴法官强制
"""
import json, os, urllib.request, yaml

PROFILES_PATH = os.path.join(os.path.dirname(__file__), "profiles.yaml")
API_BASE = "https://n.tokeness.io/v1/chat/completions"
MODEL = "claude-sonnet-5"
API_KEY = None

def _load_key():
    global API_KEY
    with open(os.path.join(os.path.dirname(__file__), "experiments", ".tokeness_key.txt")) as f:
        API_KEY = f.read().strip()

def _llm_call(prompt: str, max_tokens: int = 512) -> str:
    payload = {"model": MODEL, "messages": [
        {"role": "system", "content": "精确的任务分析器。只输出要求格式。"},
        {"role": "user", "content": prompt}
    ], "temperature": 0.2, "max_tokens": max_tokens}
    req = urllib.request.Request(API_BASE, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["choices"][0]["message"]["content"]

def load_system() -> dict:
    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def lookup_tier(z_score: float, risk_coefficient: float, routing: dict) -> dict:
    """查表矩阵: Z(行) × R(列) → 蛇配置等级"""
    matrix = routing.get("matrix", {})
    tier_names = matrix.get("tier_names", ["快速", "标准", "交叉", "回溯", "全量"])
    z_brackets = routing.get("z_brackets", [])
    r_index = routing.get("r_index", {})

    # 找Z所在行 — z_brackets每个元素: {lo, hi, row_name}
    row_name = None
    for bracket in z_brackets:
        if bracket["lo"] <= z_score < bracket["hi"]:
            row_name = bracket["row"]
            break
    if row_name is None:
        row_name = z_brackets[-1]["row"]

    # row_name是"z_low"/"z_mid"等，从matrix中取实际数组
    row = matrix.get(row_name, [])
    if not row:
        return {"heads": 1, "judges": 2, "label": "标准双审"}

    # 找R所在列
    r_keys = sorted(r_index.keys())
    closest_r = min(r_keys, key=lambda x: abs(x - risk_coefficient))
    col = r_index[closest_r]

    if col >= len(row):
        col = len(row) - 1

    tier_idx = row[col]
    config_by_tier = routing.get("config_by_tier", {})
    config = config_by_tier.get(tier_idx, {"heads": 1, "judges": 2, "label": "标准双审"})
    return config

def dedup_mechanisms(mechanisms: list, dedup_rules: dict) -> list:
    """特殊机制去重: 某些机制蕴含其他机制"""
    keep_set = set(mechanisms)
    for name in mechanisms:
        rule = dedup_rules.get(name, {})
        for remove_mech in rule.get("removes", []):
            keep_set.discard(remove_mech)
    return sorted(keep_set)

def check_context(profile: dict, task_description: str) -> dict:
    """上下文兼容性检查"""
    ctx = profile.get("context", {})
    if not ctx:
        return {"compatible": True, "warnings": [], "z_offset": 0}

    scale = ctx.get("scale_range", {})
    warnings = []
    z_offset = 0
    desc = task_description.lower()

    # 规模检查
    max_records = scale.get("max_records")
    large_kw = ["大量", "百万", "万条", "海量", "大数据", "所有记录", "全部数据"]
    if max_records and any(kw in desc for kw in large_kw):
        warnings.append(f"任务描述暗示大规模数据，剖面约束max_records={max_records}可能不足")
        z_offset += 1

    # 领域差异检查
    sig = ctx.get("input_signature", {})
    expected_op = sig.get("operation", "")
    if expected_op == "template_fill" and any(kw in desc for kw in ["分析", "计算", "聚合"]):
        warnings.append("剖面期望template_fill但任务涉及分析/计算，可能存在领域差异")
        z_offset += 1

    confidence_mod = 0.7 if warnings else 1.0
    compatible = len(warnings) <= 2
    return {"compatible": compatible, "warnings": warnings, "z_offset": z_offset, "confidence_modifier": confidence_mod}

def resolve_config(profile: dict, domain: dict, routing: dict, z_eff: float, value_level: str = "普通") -> dict:
    """维度合并: Y域底线 + Z查表 + V强制"""
    tier = lookup_tier(z_eff, domain.get("risk_coefficient", 1.0), routing)

    y_judges = domain.get("default_judges", 2)
    y_heads = 1

    final = {
        "head_model": profile.get("snake_head") or domain.get("default_head", "deepseek-v4-pro"),
        "body_model": profile.get("snake_body") or domain.get("default_body", "deepseek-v4-pro"),
        "heads": max(y_heads, tier["heads"]),
        "judges": max(y_judges, tier["judges"]),
        "judge_config": domain.get("judge_config", "standard"),
        "label": tier["label"],
        "z_raw": profile.get("z_score", "dynamic"),
        "z_eff": z_eff,
        "risk_coefficient": domain.get("risk_coefficient", 1.0),
    }

    # V轴: 高价值→至少3法官
    if value_level == "高价值" and final["judges"] < 3:
        final["judges"] = 3
        final["label"] += "+高价值增强"

    # 特殊机制: 去重
    all_special = set(domain.get("special", []))
    dedup_rules = routing.get("mechanism_dedup", {})
    final["special"] = dedup_mechanisms(list(all_special), dedup_rules)

    return final

def check_value_triggers(task_description: str, upstream_rejected: bool = False,
                         is_critical: bool = False) -> str:
    sys = load_system()
    triggers = sys.get("value_triggers", {})

    for kw in triggers.get("safety_keywords", []):
        if kw in task_description:
            return "高价值"

    if upstream_rejected:
        return "高价值"

    if is_critical:
        return "高价值"

    return "普通"

def route(user_task: str, upstream_rejected: bool = False, is_critical: bool = False) -> dict:
    if not API_KEY:
        _load_key()

    sys = load_system()
    profiles = sys.get("profiles", {})
    domains = sys.get("domains", {})
    routing = sys.get("routing", {})

    # 构建剖面摘要
    summary = []
    for name, p in profiles.items():
        if p.get("status") == "placeholder":
            continue
        summary.append(f"- {name} (Z={p.get('z_score','?')}, {p.get('domain','?')}): {p.get('description','')}")

    prompt = f"""你有以下固化好的任务剖面：
{chr(10).join(summary)}
用户任务："{user_task}"
拆解为子任务，每个匹配一个剖面。无法匹配的标记为"unmatched"。只输出JSON数组：
[{{"subtask": "...", "profile": "...", "confidence": "high|medium|low"}}]"""

    raw = _llm_call(prompt)
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        return {"error": "parse_failed", "subtasks": [], "api_used": 1}

    tasks = json.loads(raw[start:end+1])
    value_level = check_value_triggers(user_task, upstream_rejected, is_critical)

    result = {"task": user_task, "subtasks": [], "unmatched": [],
              "value_level": value_level, "api_used": 1, "warnings": []}

    for task in tasks:
        pname = task["profile"]
        if pname == "unmatched" or pname not in profiles:
            result["unmatched"].append(task["subtask"])
            continue

        profile = profiles[pname]
        domain = domains.get(profile.get("domain", ""), {})

        z = profile.get("z_score", 4)
        if z == "dynamic":
            z = profile.get("z_default", 4)

        # 上下文兼容性
        ctx = check_context(profile, task["subtask"])
        confidence = task.get("confidence", "medium")
        if ctx["z_offset"] > 0:
            z += ctx["z_offset"]
            confidence = "low"
            result["warnings"].append(f"{pname}: {ctx['warnings']}")

        # 查表+合并
        config = resolve_config(profile, domain, routing, z, value_level)

        result["subtasks"].append({
            "name": task["subtask"], "profile": pname,
            "domain": profile.get("domain"), "confidence": confidence,
            "snake_config": config,
        })

    if result["unmatched"]:
        result["warnings"].append(f"警告: {len(result['unmatched'])}个子任务无匹配剖面")

    return result


if __name__ == "__main__":
    _load_key()

    print("=" * 60)
    print("🐍 四维任务建模体系 v2.1 — 查表矩阵")
    print("=" * 60)

    tests = [
        ("管道", "做一个学生成绩分析管道：从JSON加载成绩，清洗无效记录，计算统计指标，生成Markdown报告", False, False),
        ("安全修复", "修复登录认证模块中的token泄露bug", False, True),
        ("格式化", "把统计结果格式化为HTML报告", False, False),
        ("数据域高价值", "处理支付系统中的交易数据清洗", True, False),
    ]

    for label, task, up_rej, critical in tests:
        r = route(task, up_rej, critical)
        print(f"\n📋 {label} (V={r['value_level']})")
        for s in r["subtasks"]:
            c = s["snake_config"]
            print(f"  📦 {s['name'][:30]:30s} Z_eff={c['z_eff']:.1f} | {c['heads']}头{c['judges']}法 | {c['label']} | special={c['special']}")
        if r["warnings"]:
            for w in r["warnings"]:
                print(f"  ⚡ {w}")
