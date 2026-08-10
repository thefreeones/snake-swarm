#!/usr/bin/env python
"""
蛇群 CLI — Snakes Command Line Interface
用法:
    snakes fix <file> <function> <bug_description>
    snakes scan <file> --bugs bugs.json
    snakes config

示例:
    snakes fix slugify.py smart_truncate "neg max_length causes truncation"
    snakes scan slugify.py --bugs p14_bugs.json
"""
import argparse
import json
import os
import sys
from pathlib import Path

# 确保能找到核心引擎
sys.path.insert(0, os.path.dirname(__file__))
from snakes_core import Snakes, FIX_TEMPLATES

CONFIG_PATH = Path.home() / ".snakes_config.json"
DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://n.tokeness.io/v1",
    "models": {
        "heavy_head": "claude-sonnet-5",
        "light_head": "deepseek-v4-pro",
        "fix_snake": "deepseek-v4-pro",
        "rewrite_snake": "gemini-3.6-flash",
    },
}


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def get_api_key(cfg):
    key = cfg.get("api_key", "") or os.environ.get("SNAKES_API_KEY", "")
    if not key:
        print("❌ 未设置API Key。请运行: snakes config --api-key <your-key>")
        print("   或设置环境变量: SNAKES_API_KEY")
        sys.exit(1)
    return key


def cmd_fix(args):
    """修复单个bug"""
    cfg = load_config()
    api_key = get_api_key(cfg)

    snakes = Snakes(
        api_key=api_key,
        base_url=cfg.get("base_url", DEFAULT_CONFIG["base_url"]),
        models=cfg.get("models", {}),
    )

    print(f"🐍 蛇群修复模式")
    print(f"   文件: {args.file}")
    print(f"   函数: {args.function}")
    print(f"   Bug:  {args.bug_description[:80]}...")
    print()

    result = snakes.fix(
        file_path=args.file,
        function=args.function,
        bug_description=args.bug_description,
        error_type=args.error_type or "",
        trigger_test=args.trigger,
        use_cache=False,
        enable_judges=args.judges,
    )

    if result.template_hit:
        print(f"✅ 模板命中: {result.template_hit}")
        print(f"   {result.fix_description}")
        return

    if result.success:
        print("✅ 修复成功")
        if hasattr(result, 'rewrite_attempted') and result.rewrite_attempted:
            print("   ♻️  通过黑箱重写(B阶段)")
    else:
        print(f"❌ 修复失败: {result.error}")

    print(f"\n📋 根因分析:\n   {result.root_cause[:200]}...")
    print(f"\n🔧 修复方案:\n   {result.fix_description[:200]}...")
    print(f"\n📊 Token: {result.tokens}")

    # v0.7 蛇尾自述
    if hasattr(result, 'tail_report') and result.tail_report:
        t = result.tail_report
        print(f"\n🐍 蛇尾自述:")
        print(f"   事实: diff={t.fact.get('diff_lines_changed',0)}行, "
              f"测试={t.fact.get('test_passed',0)}/{t.fact.get('test_total',0)}")
        if t.inference:
            print(f"   推断: {t.inference.get('impact_scope','?')[:80]}")
        for u in t.uncertainty[:2]:
            print(f"   ⚠️  {u[:80]}")
        if t.validation_issues:
            for vi in t.validation_issues:
                print(f"   🔴 {vi}")


    # v0.7 学习层: 新提取的模式
    if hasattr(result, '_new_pattern'):
        p = result._new_pattern
        print(f"\n🧠 学习层: 新提取模式 [{p.pattern_id}]")
        print(f"   触发: {p.trigger_condition[:80]}")
        print(f"   教训: {p.lesson[:80]}")
        print(f"   策略: {p.fix_strategy[:80]}")


    if result.audit:
        print(f"\n🔍 审计: {'PASS' if result.audit['passed'] else 'FAIL'}")
        if result.audit["issues"]:
            for issue in result.audit["issues"]:
                print(f"   - {issue}")

    if result.patch:
        patch_file = f"{os.path.splitext(args.file)[0]}.patch"
        with open(patch_file, "w") as f:
            f.write(result.patch)
        print(f"\n📄 Patch已保存: {patch_file}")

    # v0.7 裁决结果显示
    if args.judges and hasattr(result, '_adjudication'):
        adj = result._adjudication
        print(f"\n⚖️  三角色裁决: {adj.final_verdict} ({adj.conflict_type or '一致'})")
        print(f"   {adj.summary}")
        for v in adj.verdicts:
            print(f"   [{v.role}] {v.verdict} (置信度{v.confidence}, {v.severity})")

    # L3 提示
    if result.audit and result.audit["passed"] and result.audit.get("issues"):
        print("\n⚠️  建议运行L3语义审计(L1通过但有P1副作用)")


def cmd_scan(args):
    """批量扫描+修复"""
    cfg = load_config()
    api_key = get_api_key(cfg)

    if not os.path.exists(args.bugs):
        print(f"❌ Bug配置文件不存在: {args.bugs}")
        sys.exit(1)

    with open(args.bugs) as f:
        bugs_data = json.load(f)

    bugs = bugs_data if isinstance(bugs_data, list) else bugs_data.get("bugs", [])

    snakes = Snakes(
        api_key=api_key,
        base_url=cfg.get("base_url", DEFAULT_CONFIG["base_url"]),
        models=cfg.get("models", {}),
    )

    print(f"🐍🐍🐍 蛇群批量扫描模式")
    print(f"   文件: {args.file}")
    print(f"   Bugs: {len(bugs)}")
    print()

    result = snakes.scan(file_path=args.file, bug_candidates=bugs)

    for i, r in enumerate(result.results):
        status = "✅" if r.success else "❌"
        hit = f" [模板:{r.template_hit}]" if r.template_hit else ""
        print(f"  [{i+1}] {status} {r.bug_id}{hit}")

    print(f"\n{'='*50}")
    print(f"  通过: {result.success_count}/{len(bugs)} ({result.success_count/len(bugs)*100:.0f}%)")
    print(f"  失败: {result.fail_count}")
    print(f"  模板: {result.template_hits}")
    print(f"  Token: {result.total_tokens}")
    print(f"{'='*50}")

    # 保存报告
    report = {
        "file": args.file,
        "bug_count": len(bugs),
        "success": result.success_count,
        "fail": result.fail_count,
        "template_hits": result.template_hits,
        "total_tokens": result.total_tokens,
        "results": [
            {
                "bug_id": r.bug_id,
                "success": r.success,
                "root_cause": r.root_cause[:200],
                "tokens": r.tokens,
                "audit_passed": r.audit.get("passed", False) if r.audit else False,
            }
            for r in result.results
        ],
    }
    report_path = f"{os.path.splitext(args.file)[0]}_snakes_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n📊 报告: {report_path}")


def cmd_config(args):
    """配置管理"""
    cfg = load_config()

    if args.show:
        print("当前配置:")
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
        return

    if args.api_key:
        cfg["api_key"] = args.api_key
        save_config(cfg)
        print("✅ API Key已保存")
        return

    if args.init:
        cfg = {**DEFAULT_CONFIG, **cfg}
        save_config(cfg)
        print("✅ 配置已初始化")
        print(f"   配置文件: {CONFIG_PATH}")
        print(f"   请设置API Key: snakes config --api-key <your-key>")
        return

    print("蛇群配置:")
    print(f"   API Key: {'已设置' if cfg.get('api_key') else '❌ 未设置'}")
    print(f"   Base URL: {cfg.get('base_url', DEFAULT_CONFIG['base_url'])}")
    print(f"   模板数: {len(FIX_TEMPLATES)}")


def cmd_templates(args):
    """列出可用模板+学习模式"""
    print("修复模板缓存 (P13):")
    for tid, tpl in FIX_TEMPLATES.items():
        print(f"  [{tid}] {tpl['name']}")
        print(f"       检测: {', '.join(tpl['detect'][:3])}")
        print(f"       修复: {tpl['fix'][:60]}...")
        print()

    # v0.7 学习层模式
    from snakes_core import PatternStore
    ps = PatternStore()
    stats = ps.get_stats()
    if stats["total"] > 0:
        print(f"学习层模式库: {stats['total']}条 "
              f"(active={stats['active']}, candidate={stats['candidate']}, "
              f"deprecated={stats['deprecated']})")
        active = [p for p in ps.patterns.values() if p.status == "active"]
        for p in active[:5]:
            print(f"  [{p.pattern_id}] {p.trigger_condition[:60]}")
            print(f"       → {p.lesson[:60]} (置信度{p.confidence:.2f})")


def main():
    parser = argparse.ArgumentParser(
        description="🐍 蛇群 — 多智能体代码审查与修复系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  snakes fix slugify.py smart_truncate "negative max_length causes truncation"
  snakes scan slugify.py --bugs bugs.json
  snakes config --init
  snakes templates
        """,
    )
    sub = parser.add_subparsers(dest="command")

    # fix
    p_fix = sub.add_parser("fix", help="修复单个bug")
    p_fix.add_argument("file", help="源代码文件")
    p_fix.add_argument("function", help="目标函数名")
    p_fix.add_argument("bug_description", help="Bug描述")
    p_fix.add_argument("--error-type", help="错误类型")
    p_fix.add_argument("--trigger", help="快速验证输入,如 \"'abc', 1\"")
    p_fix.add_argument("--judges", action="store_true", help="启用三角色裁决(v0.7)")

    # scan
    p_scan = sub.add_parser("scan", help="批量扫描+修复")
    p_scan.add_argument("file", help="源代码文件")
    p_scan.add_argument("--bugs", required=True, help="Bug配置文件(JSON)")

    # config
    p_cfg = sub.add_parser("config", help="配置管理")
    p_cfg.add_argument("--init", action="store_true", help="初始化配置")
    p_cfg.add_argument("--api-key", help="设置API Key")
    p_cfg.add_argument("--show", action="store_true", help="显示当前配置")

    # templates
    sub.add_parser("templates", help="列出修复模板")

    # build (v0.7 模式B)
    p_build = sub.add_parser("build", help="从需求文档构建项目")
    p_build.add_argument("--spec", required=True, help="需求文档路径(.md)")
    p_build.add_argument("--output", default="./output", help="输出目录")

    args = parser.parse_args()

    if args.command == "fix":
        cmd_fix(args)
    elif args.command == "scan":
        cmd_scan(args)
    elif args.command == "config":
        cmd_config(args)
    elif args.command == "templates":
        cmd_templates(args)
    elif args.command == "build":
        cmd_build(args)
    else:
        parser.print_help()


def cmd_build(args):
    """模式B: 需求→项目"""
    cfg = load_config()
    api_key = get_api_key(cfg)

    from snakes_core import Snakes
    snakes = Snakes(
        api_key=api_key,
        base_url=cfg.get("base_url", "https://n.tokeness.io/v1"),
        models=cfg.get("models", {}),
    )

    print(f"🐍🐍 蛇群模式B — 项目构建")
    print(f"   需求: {args.spec}")
    print(f"   输出: {args.output}")
    print()

    result = snakes.build(spec_path=args.spec, output_dir=args.output)

    if result.success:
        print(f"✅ 构建成功: {result.project_name}")
        print(f"   模块: {len(result.modules)}个")
        for m in result.modules:
            print(f"     [{m.status}] {m.name}: {m.description[:50]}")
        print(f"   集成测试: {'PASS' if result.integration_test_passed else 'FAIL'}")
        print(f"   Token: ~{result.total_tokens}")
    else:
        print(f"❌ 构建失败: {result.error}")


if __name__ == "__main__":
    main()
