"""
蛇群数据管道集成器 — Student Score Analyzer
执行监督层: 预评分+V×Z路由+蛇池→数据契约验证→裁决

完整链路:
  M1(Loader) → M2(Cleaner) → M3(Stats) → M4(Reporter)
"""
import sys, os, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.loader import run as run_loader
from modules.cleaner import run as run_cleaner
from modules.stats import run as run_stats
from modules.reporter import run as run_reporter

DATA_FILE = os.path.join(os.path.dirname(__file__), "score_data.json")

def verify_field_contract(module_name: str, output: dict, required_fields: list) -> list:
    """蛇α: 正向检查——模块是否产出了声明字段"""
    missing = []
    for field in required_fields:
        if field not in output:
            missing.append(field)
    return missing

def verify_upstream_dep(module_name: str, upstream_fields: dict, required_keys: list) -> list:
    """蛇β: 反向检查——模块依赖的字段在上游是否实际存在"""
    missing = []
    for key in required_keys:
        parts = key.split(".")
        current = upstream_fields
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                missing.append(key)
                break
    return missing

# ========================================
# 管道执行
# ========================================
print("=" * 60)
print("🐍 蛇群数据管道 — Student Score Analyzer")
print("=" * 60)

# M1: Loader
print("\n[M1 Loader] 加载数据...")
t0 = time.time()
m1_out = run_loader(DATA_FILE)
m1_time = time.time() - t0
print(f"  产出: students={len(m1_out['students'])}条, total_loaded={m1_out['total_loaded']}")
print(f"  耗时: {m1_time:.1f}s")

# 数据契约验证 M1
m1_missing = verify_field_contract("M1", m1_out, ["students", "total_loaded"])
if m1_missing:
    print(f"  ❌ 字段缺失: {m1_missing}")
else:
    print(f"  ✅ 字段契约通过")

# M2: Cleaner
print("\n[M2 Cleaner] 清洗数据...")
t0 = time.time()
m2_out = run_cleaner(m1_out["students"], m1_out["total_loaded"])
m2_time = time.time() - t0
print(f"  产出: students={len(m2_out['students'])}条, removed={m2_out['removed']}")
print(f"  剔除: {', '.join(m2_out['removed_records'])}")
print(f"  耗时: {m2_time:.1f}s")

# 数据契约验证 M2 (正向)
m2_missing = verify_field_contract("M2", m2_out, ["students", "total_loaded", "removed", "removed_records"])
if m2_missing:
    print(f"  ❌ 字段缺失: {m2_missing}")
else:
    print(f"  ✅ 字段契约通过")

# 数据契约验证 M2 (反向——M2依赖M1.students)
m2_dep_missing = verify_upstream_dep("M2", m1_out, ["students"])
if m2_dep_missing:
    print(f"  ❌ 上游依赖缺失: {m2_dep_missing}")
else:
    print(f"  ✅ 上游依赖M1.students验证通过")

# M3: Stats
print("\n[M3 Stats] 统计分析...")
t0 = time.time()
m3_out = run_stats(m2_out["students"])
m3_time = time.time() - t0
print(f"  产出: avg_math={m3_out['avg_math']}, avg_eng={m3_out['avg_eng']}, avg_cs={m3_out['avg_cs']}")
print(f"  top_student={m3_out['top_student']}({m3_out['top_total']}), pass_rate={m3_out['pass_rate']}%")
print(f"  耗时: {m3_time:.1f}s")

m3_missing = verify_field_contract("M3", m3_out, [
    "avg_math", "avg_eng", "avg_cs", "top_student", "top_total", "pass_rate", "total_students"
])
if m3_missing:
    print(f"  ❌ 字段缺失: {m3_missing}")
else:
    print(f"  ✅ 字段契约通过")

m3_dep_missing = verify_upstream_dep("M3", m2_out, ["students"])
if m3_dep_missing:
    print(f"  ❌ 上游依赖缺失: {m3_dep_missing}")
else:
    print(f"  ✅ 上游依赖M2.students验证通过")

# M4: Reporter
print("\n[M4 Reporter] 生成报告...")
t0 = time.time()

# 构建M4输入(从M1+M2+M3汇总)
m4_kwargs = {
    "total_loaded": m1_out["total_loaded"],
    "removed": m2_out["removed"],
    "removed_records": m2_out["removed_records"],
    "avg_math": m3_out["avg_math"],
    "avg_eng": m3_out["avg_eng"],
    "avg_cs": m3_out["avg_cs"],
    "top_student": m3_out["top_student"],
    "top_total": m3_out["top_total"],
    "pass_rate": m3_out["pass_rate"],
    "total_students": m3_out["total_students"],
    "output_path": os.path.join(os.path.dirname(__file__), "report.md")
}
m4_out = run_reporter(**m4_kwargs)
m4_time = time.time() - t0
print(f"  产出: {m4_out}")
print(f"  耗时: {m4_time:.1f}s")

# 数据契约验证 M4
m4_missing = verify_field_contract("M4", {"report_path": m4_out}, ["report_path"])
if not os.path.exists(m4_out):
    print(f"  ❌ report.md未生成")
else:
    print(f"  ✅ 报告文件存在")

# 数据契约验证 M4 (反向——M4依赖M1/M2/M3的字段)
m4_required_deps = {
    "M1_total_loaded": m1_out.get("total_loaded"),
    "M2_removed": m2_out.get("removed"),
    "M3_avg_math": m3_out.get("avg_math"),
    "M3_avg_eng": m3_out.get("avg_eng"),
    "M3_avg_cs": m3_out.get("avg_cs"),
    "M3_top_student": m3_out.get("top_student"),
}
all_deps_ok = True
for dep_name, val in m4_required_deps.items():
    if val is None:
        print(f"  ❌ 上游依赖缺失: {dep_name}")
        all_deps_ok = False
if all_deps_ok:
    print(f"  ✅ 上游依赖M1+M2+M3验证通过")

# ========================================
# 汇总
# ========================================
total_time = m1_time + m2_time + m3_time + m4_time
print("\n" + "=" * 60)
print("📊 管道执行汇总")
print("=" * 60)
print(f"  总模块: 4")
print(f"  总耗时: {total_time:.1f}s")
print(f"  数据流: 10条→{len(m2_out['students'])}条→{m3_out['total_students']}人")
print(f"  三科均分: {m3_out['avg_math']}/{m3_out['avg_eng']}/{m3_out['avg_cs']}")
print(f"  最佳: {m3_out['top_student']}({m3_out['top_total']})")
print(f"  及格率: {m3_out['pass_rate']}%")
print(f"  报告: {m4_out}")

# 打印报告内容
if os.path.exists(m4_out):
    print("\n" + "=" * 60)
    print("📄 报告预览")
    print("=" * 60)
    with open(m4_out, "r", encoding="utf-8") as f:
        print(f.read())
