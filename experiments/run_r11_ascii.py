#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
R11 Structured Deviation Log Validation Experiment
Compares structured template + anti-gullibility vs P2 baseline
All Chinese text loaded from JSON, source file is ASCII-only
"""
import json
import time
import os
import sys
import requests
import yaml
import re

# ============================================================
# API Config
# ============================================================
def load_api_key():
    with open(r'C:/Users/GOD/AppData/Local/hermes/config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    tokeness_provider = [x for x in config['custom_providers'] if x['name'] == 'tokeness'][0]
    return tokeness_provider['api_key']

API_KEY = load_api_key()
BASE_URL = "https://n.tokeness.io/v1/chat/completions"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

def call_llm(model, messages, temperature=0.3, max_tokens=4000, max_retries=3):
    payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    for attempt in range(max_retries):
        try:
            resp = requests.post(BASE_URL, headers=HEADERS, json=payload, timeout=180)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                return content, usage
            else:
                print(f"  [WARN] API {resp.status_code}: {resp.text[:200]}")
                if attempt < max_retries - 1:
                    time.sleep(3 * (attempt + 1))
        except Exception as e:
            print(f"  [WARN] API error: {e}")
            if attempt < max_retries - 1:
                time.sleep(3 * (attempt + 1))
    return None, {"total_tokens": 0}

# ============================================================
# Prompt Builders (templates loaded from JSON)
# ============================================================

PROMPT_TEMPLATES = None

def build_prompt_a(label, task, plan, code):
    """Group A: code + plan only"""
    tpl = PROMPT_TEMPLATES["judge_prompt_a_template"]
    return tpl.format(label=label, task=task, plan=plan, code=code)

def build_prompt_b(label, task, plan, code, devlog):
    """Group B: code + structured devlog + anti-gullibility"""
    tpl = PROMPT_TEMPLATES["judge_prompt_b_template"]
    anti = PROMPT_TEMPLATES["anti_gullibility"]
    return tpl.format(label=label, task=task, plan=plan, code=code, devlog=devlog) + anti

# ============================================================
# Result Parser
# ============================================================

def parse_judge_output(content):
    """Parse judge output to extract deviation count and key info"""
    if not content:
        return {"total_deviations": 0, "deviations_found": [], "summary": "ERROR: No response", "log_audit": None}

    total = 0
    # Try to find explicit count
    patterns = [
        r'pian li zong shu[：:\s]*(\d+)',
        r'Pian Li Zong Shu[：:\s]*(\d+)',
        r'total_deviations[：:\s]*(\d+)',
    ]
    for p in patterns:
        m = re.search(p, content, re.IGNORECASE)
        if m:
            total = int(m.group(1))
            break

    # Count Chinese deviation markers if no explicit count
    if total == 0:
        count = 0
        for marker in ['关键偏离', '次要偏离', '无影响偏离']:
            count += content.count(marker)
        total = count if count > 0 else 0

    # Extract deviations
    deviations = []
    lines = content.split('\n')
    current_dev = None
    for line in lines:
        ls = line.strip()
        if any(m in ls for m in ['关键偏离', '次要偏离', '无影响偏离']):
            if current_dev:
                deviations.append(current_dev)
            current_dev = {'description': ls[:200]}
        elif current_dev and ls:
            current_dev['description'] = current_dev.get('description', '') + ' ' + ls[:100]
    if current_dev:
        deviations.append(current_dev)

    # Extract log audit section
    log_audit = None
    if '[执行日志审查结果]' in content:
        idx = content.find('[执行日志审查结果]')
        log_audit = content[idx:idx+1000]

    summary = content[-500:] if len(content) > 500 else content
    return {
        "total_deviations": total,
        "deviations_found": deviations,
        "summary": summary,
        "log_audit": log_audit
    }

# ============================================================
# Main Experiment
# ============================================================

def main():
    global PROMPT_TEMPLATES

    # Load scenarios with prompt templates
    with open("D:/competation/design/experiments/r11_scenarios.json", 'r', encoding='utf-8') as f:
        all_data = json.load(f)

    PROMPT_TEMPLATES = all_data["_prompts"]
    scenarios = {k: v for k, v in all_data.items() if not k.startswith('_')}

    # Load P2 baseline
    with open("D:/competation/design/experiments/results/p2_deviation_log.json", 'r', encoding='utf-8') as f:
        p2 = json.load(f)
    p2_data = {}
    for je in p2['judge_evaluations']:
        p2_data[je['tag']] = je['parsed']['total_deviations']

    print("=" * 70)
    print("  R11 Structured Template + Anti-Gullibility Validation")
    print("=" * 70)
    print(f"\nP2 baseline deviations: {p2_data}")
    print(f"Will run 2 scenarios x 2 groups x 2 models = 8 API calls\n")

    judge_configs = [
        {"model": "deepseek-v4-pro", "temperature": 0.7, "tag_suffix": "DSV"},
        {"model": "gemini-3.6-flash", "temperature": 0.3, "tag_suffix": "GEM"},
    ]

    all_results = []

    for sid in ['S1', 'S2']:
        sc = scenarios[sid]
        print(f"\n{'='*70}")
        print(f"  {sc['label']}")
        print(f"{'='*70}")

        # Group A: Code only
        print(f"\n  [Group A] Code only...")
        for jc in judge_configs:
            tag = f"{sid}-A-{jc['tag_suffix']}"
            print(f"    -> {tag} ({jc['model']}, t={jc['temperature']})...", end=" ", flush=True)

            prompt = build_prompt_a(sc['label'], sc['task'], sc['plan'], sc['code'])
            content, usage = call_llm(
                jc['model'],
                [{"role": "user", "content": prompt}],
                temperature=jc['temperature'],
                max_tokens=4000
            )

            parsed = parse_judge_output(content)
            result = {
                "tag": tag,
                "scenario": sid,
                "group": "A",
                "group_desc": "Code only",
                "model": jc['model'],
                "temperature": jc['temperature'],
                "parsed": parsed,
                "usage": usage,
            }
            all_results.append(result)
            print(f"{parsed['total_deviations']} deviations, {usage.get('total_tokens', 0)} tokens")
            time.sleep(1)

        # Group B: Code + structured devlog + anti-gullibility
        print(f"\n  [Group B] Code + structured devlog + anti-gullibility...")
        for jc in judge_configs:
            tag = f"{sid}-B-{jc['tag_suffix']}"
            print(f"    -> {tag} ({jc['model']}, t={jc['temperature']})...", end=" ", flush=True)

            prompt = build_prompt_b(sc['label'], sc['task'], sc['plan'], sc['code'], sc['devlog'])
            content, usage = call_llm(
                jc['model'],
                [{"role": "user", "content": prompt}],
                temperature=jc['temperature'],
                max_tokens=4000
            )

            parsed = parse_judge_output(content)
            result = {
                "tag": tag,
                "scenario": sid,
                "group": "B",
                "group_desc": "Code + structured devlog + anti-gullibility",
                "model": jc['model'],
                "temperature": jc['temperature'],
                "parsed": parsed,
                "usage": usage,
            }
            all_results.append(result)
            print(f"{parsed['total_deviations']} deviations, {usage.get('total_tokens', 0)} tokens")
            has_audit = "Yes" if parsed.get('log_audit') else "No"
            print(f"       Log audit response: {has_audit}")
            time.sleep(1)

    # ============================================================
    # Analysis and Comparison
    # ============================================================
    r11_data = {}
    for r in all_results:
        r11_data[r['tag']] = r['parsed']['total_deviations']

    # Build comparison
    comparison = {
        "experiment": "R11_structured_devlog_validation",
        "timestamp": "2026-08-04",
        "hypotheses": {
            "H1": "Structured template reduces deviation_log omissions and false positives",
            "H2": "Anti-gullibility instruction eliminates judge log-hypnosis effect"
        },
        "methods": {
            "S1": "compute_variance (no deviation), snake body follows snake head plan",
            "S2": "process_sales_csv (active deviation), snake body uses csv instead of pandas",
            "R11_changes": [
                "deviation_log uses structured template (step ID / deviation? / executed ops / reason / risks avoided / unhandled / cannot confirm)",
                "Group B judge prompts appended with anti-gullibility instruction (4 mandatory checks)",
                "Group B judges asked to distinguish devlog-recorded / omitted / false-positive"
            ]
        },
        "per_judge_comparison": {},
        "scenario_analysis": {},
        "log_hypnosis_analysis": {},
        "anti_gullibility_effect": {},
        "chinese_analysis": ""
    }

    # Per-judge comparison
    for tag in sorted(set(list(p2_data.keys()) + list(r11_data.keys()))):
        p2_val = p2_data.get(tag, None)
        r11_val = r11_data.get(tag, None)
        comparison["per_judge_comparison"][tag] = {
            "P2_baseline": p2_val,
            "R11_structured": r11_val,
            "delta": (r11_val - p2_val) if (p2_val is not None and r11_val is not None) else None
        }

    # Scenario analysis
    for sid in ['S1', 'S2']:
        sa = {"A_CodeOnly": {}, "B_CodeDevlogAntiGullibility": {}}

        for group, gk in [('A', 'A_CodeOnly'), ('B', 'B_CodeDevlogAntiGullibility')]:
            for model_tag in ['DSV', 'GEM']:
                tag = f"{sid}-{group}-{model_tag}"
                p2_val = p2_data.get(tag, None)
                r11_val = r11_data.get(tag, None)
                sa[gk][model_tag] = {
                    "P2": p2_val,
                    "R11": r11_val,
                    "delta": (r11_val - p2_val) if (p2_val is not None and r11_val is not None) else None
                }

        for gk, gv in sa.items():
            p2_vals = [v['P2'] for v in gv.values() if v['P2'] is not None]
            r11_vals = [v['R11'] for v in gv.values() if v['R11'] is not None]
            gv['avg_P2'] = sum(p2_vals) / len(p2_vals) if p2_vals else None
            gv['avg_R11'] = sum(r11_vals) / len(r11_vals) if r11_vals else None

        comparison["scenario_analysis"][sid] = sa

    # Log hypnosis analysis
    for sid in ['S1', 'S2']:
        a_delta = []
        b_delta = []
        for model_tag in ['DSV', 'GEM']:
            a_tag = f"{sid}-A-{model_tag}"
            b_tag = f"{sid}-B-{model_tag}"
            if a_tag in r11_data and a_tag in p2_data:
                a_delta.append(r11_data[a_tag] - p2_data[a_tag])
            if b_tag in r11_data and b_tag in p2_data:
                b_delta.append(r11_data[b_tag] - p2_data[b_tag])

        a_avg = sum(a_delta) / len(a_delta) if a_delta else None
        b_avg = sum(b_delta) / len(b_delta) if b_delta else None

        if a_avg is not None and b_avg is not None:
            if b_avg > a_avg and b_avg > 0:
                interp = "Group B (code+devlog) deviation findings increased more, anti-gullibility may have improved scrutiny"
            elif b_avg < a_avg:
                interp = "Group B deviation findings changed less than Group A, need further analysis"
            else:
                interp = "Both groups changed similarly, no significant difference"
        else:
            interp = "Insufficient data"

        comparison["log_hypnosis_analysis"][sid] = {
            "A_avg_change": a_avg,
            "B_avg_change": b_avg,
            "interpretation": interp
        }

    # Anti-gullibility effect
    b_judge_log_audits = []
    for r in all_results:
        if r['group'] == 'B' and r['parsed'].get('log_audit'):
            b_judge_log_audits.append({
                'tag': r['tag'],
                'has_log_audit': True,
                'audit_preview': r['parsed']['log_audit'][:300]
            })

    comparison["anti_gullibility_effect"] = {
        "B_judges_responding_to_anti_gullibility": len(b_judge_log_audits),
        "details": b_judge_log_audits
    }

    # ============================================================
    # Chinese Analysis
    # ============================================================
    lines = []
    lines.append("=== R11 Jie Gou Hua Mo Ban + Fan Qing Xin Zhi Ling Yan Zheng Jie Lun ===\n")

    lines.append("## 1. Jie Gou Hua Mo Ban Dui deviation_log Zhi Liang De Ying Xiang\n")

    for sid in ['S1', 'S2']:
        sa = comparison['scenario_analysis'][sid]
        sc = scenarios[sid]
        lines.append(f"### Chang Jing {sid}: {sc['label']}")

        for gk in ['A_CodeOnly', 'B_CodeDevlogAntiGullibility']:
            gv = sa[gk]
            gk_cn = "A Zu (Chun Dai Ma)" if gk == 'A_CodeOnly' else "B Zu (Dai Ma + Jie Gou Hua Devlog + Fan Qing Xin)"
            lines.append(f"  {gk_cn}: P2 avg={gv.get('avg_P2')}, R11 avg={gv.get('avg_R11')}")

        if sid == 'S1':
            lines.append("  Fen Xi: S1 wei wu pian li chang jing, li xiang qing kuang xia fa guan ying fa xian 0 ge pian li.")
            s1_a_r11 = sa['A_CodeOnly'].get('avg_R11', 0)
            s1_a_p2 = sa['A_CodeOnly'].get('avg_P2', 0)
            if s1_a_r11 is not None and s1_a_p2 is not None and s1_a_r11 <= s1_a_p2:
                lines.append("  -> A Zu pian li fa xian shu chi ping huo jian shao, jie gou hua devlog wei yin ru gan rao")
            s1_b_r11 = sa['B_CodeDevlogAntiGullibility'].get('avg_R11', 0)
            s1_b_p2 = sa['B_CodeDevlogAntiGullibility'].get('avg_P2', 0)
            if s1_b_r11 is not None and s1_b_p2 is not None and s1_b_r11 <= s1_b_p2:
                lines.append("  -> B Zu pian li fa xian shu chi ping huo jian shao, jie gou hua devlog + 'Wo Wu Fa Que Ren' zi duan ke neng bang zhu fa guan geng zhun que pan duan")
        elif sid == 'S2':
            lines.append("  Fen Xi: S2 wei you pian li chang jing, li xiang qing kuang xia fa guan ying fa xian suo you zhen shi pian li.")
            lines.append("  Yi Zhi zhen shi pian li: pandas->csv qie huan, .xlsx jiang ji, ri zhi que yuan shi nei rong, wei sheng cheng yi chang shu ju wen jian, ri qi jie xi fang shi bian geng, bian ma hui tui wei shi xian")
            lines.append("  Gong yue 5-6 ge zhen shi pian li dian")
            s2_a_r11 = sa['A_CodeOnly'].get('avg_R11', 0)
            s2_b_r11 = sa['B_CodeDevlogAntiGullibility'].get('avg_R11', 0)
            if s2_b_r11 is not None and s2_a_r11 is not None:
                if s2_b_r11 > s2_a_r11:
                    lines.append("  -> B Zu pian li fa xian shu > A Zu, jie gou hua devlog bang zhu fa guan fa xian geng duo pian li")
                elif s2_b_r11 < s2_a_r11:
                    lines.append("  -> B Zu pian li fa xian shu < A Zu, jing ti: ji bian jie gou hua devlog reng ke neng cun zai cui mian xiao ying")
        lines.append("")

    lines.append("## 2. Fan Qing Xin Zhi Ling Xiao Guo\n")
    lines.append(f"  B Zu fa guan zhong {comparison['anti_gullibility_effect']['B_judges_responding_to_anti_gullibility']} wei ming que shu chu le [Zhi Xing Ri Zhi Shen Cha Jie Guo]")

    for detail in comparison['anti_gullibility_effect']['details']:
        lines.append(f"  - {detail['tag']}: {detail['audit_preview'][:150]}...")

    # Count B judges who found devlog issues
    b_judges_with_findings = 0
    for r in all_results:
        if r['group'] == 'B':
            raw = r.get('raw_content', '')
            if raw and ('devlog' in raw.lower() and ('yi lou' in raw or 'wu bao' in raw or 'bu wan zheng' in raw or 'bu wanzheng' in raw)):
                b_judges_with_findings += 1

    lines.append(f"\n  B Zu fa guan zhong zhi chu devlog wen ti de: {b_judges_with_findings}/4 wei")
    lines.append("")

    lines.append("## 3. Log Cui Mian Xiao Ying Fen Xi\n")
    for sid in ['S1', 'S2']:
        la = comparison['log_hypnosis_analysis'][sid]
        lines.append(f"  {sid}: A Zu ping jun bian hua={la['A_avg_change']}, B Zu ping jun bian hua={la['B_avg_change']}")
        lines.append(f"  -> {la['interpretation']}")
    lines.append("")

    lines.append("## 4. Zong Ti Jie Lun\n")

    p2_total = sum(comparison['per_judge_comparison'][tag]['P2_baseline']
                   for tag in comparison['per_judge_comparison']
                   if comparison['per_judge_comparison'][tag]['P2_baseline'] is not None)
    r11_total = sum(comparison['per_judge_comparison'][tag]['R11_structured']
                    for tag in comparison['per_judge_comparison']
                    if comparison['per_judge_comparison'][tag]['R11_structured'] is not None)

    lines.append(f"  P2 ji xian zong pian li fa xian shu: {p2_total}")
    lines.append(f"  R11 jie gou mo ban zong pian li fa xian shu: {r11_total}")
    delta_total = r11_total - p2_total
    lines.append(f"  Bian hua: {'+' if delta_total >= 0 else ''}{delta_total}")

    s2_a_p2 = comparison['scenario_analysis']['S2']['A_CodeOnly'].get('avg_P2', 0)
    s2_a_r11 = comparison['scenario_analysis']['S2']['A_CodeOnly'].get('avg_R11', 0)
    s2_b_p2 = comparison['scenario_analysis']['S2']['B_CodeDevlogAntiGullibility'].get('avg_P2', 0)
    s2_b_r11 = comparison['scenario_analysis']['S2']['B_CodeDevlogAntiGullibility'].get('avg_R11', 0)

    lines.append(f"\n  Guan jian dui bi (S2 you pian li chang jing):")
    lines.append(f"    A Zu (chun dai ma): P2={s2_a_p2} -> R11={s2_a_r11}")
    lines.append(f"    B Zu (dai ma + devlog): P2={s2_b_p2} -> R11={s2_b_r11}")

    if s2_b_r11 is not None and s2_b_p2 is not None:
        lines.append(f"    S2 B Zu bian hua: {'+' if s2_b_r11 >= s2_b_p2 else ''}{s2_b_r11 - s2_b_p2}")

    lines.append(f"\n  R11 you hua xiao guo pan ding:")
    if s2_b_r11 is not None and s2_b_p2 is not None and s2_b_r11 > s2_b_p2:
        lines.append("  [OK] Jie gou hua mo ban + fan qing xin zhi ling shi B zu fa guan pian li fa xian shu zeng jia, log cui mian xiao ying jian ruo")
    elif s2_b_r11 is not None and s2_b_r11 == s2_b_p2:
        lines.append("  [~] Xiao guo bu xian zhu, pian li fa xian shu wei bian")
    else:
        lines.append("  [WARN] Xiao guo bu xian zhu huo xu yao geng duo shu ju yan zheng")

    comparison["chinese_analysis"] = "\n".join(lines)

    # ============================================================
    # Save results
    # ============================================================
    full_output = dict(comparison)
    full_output["r11_raw_results"] = all_results

    output_path = "D:/competation/design/experiments/results/p2_structured_validation.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(full_output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*70}")
    print(f"  Experiment complete! Results saved to: {output_path}")
    print(f"{'='*70}")
    print(f"\n{comparison['chinese_analysis']}")

    # Summary table
    print(f"\n{'='*70}")
    print(f"  Deviation Count Comparison")
    print(f"{'='*70}")
    print(f"{'Tag':<15} {'P2 Base':>8} {'R11 Struct':>8} {'Delta':>8}")
    print(f"{'-'*45}")
    for tag in sorted(comparison['per_judge_comparison'].keys()):
        c = comparison['per_judge_comparison'][tag]
        p2_v = c['P2_baseline']
        r11_v = c['R11_structured']
        delta = c['delta']
        delta_str = f"{'+' if delta and delta > 0 else ''}{delta}" if delta is not None else "N/A"
        print(f"{tag:<15} {str(p2_v):>8} {str(r11_v):>8} {delta_str:>8}")

if __name__ == "__main__":
    main()
