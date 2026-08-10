"""
蛇群 v0.3 P0 实验 — 测试用例定义
来源：v0.2 实验验证数据，17 个用例
"""

# ============================================================
# 第一阶段：广度验证（10 用例）
# ============================================================

TEST_CASES = [
    {
        "id": "case1",
        "title": "off-by-one + 越界",
        "error_type": "L1: logic error / off-by-one",
        "category": "logic_error",
        "z_score": 2,  # Z ∈ [0,3)
        "value": "normal",
        "task": "写一个函数 get_middle_elements(lst)，返回列表的中间元素。偶数长度返回中间两个，奇数长度返回中间一个。",
        "buggy_code": '''def get_middle_elements(lst):
    n = len(lst)
    if n % 2 == 0:
        return [lst[n//2 - 1], lst[n//2]]
    else:
        return [lst[n//2 + 1]]  # BUG: +1 越界，应为 n//2''',
        "expected_bugs": ["奇数长度用 n//2+1 取到中间偏右", "单元素列表时 n//2+1=1 导致 IndexError"],
        "ground_truth": "FAIL",
    },
    {
        "id": "case2",
        "title": "边界条件 / 非数字输入",
        "error_type": "L1: boundary / missing-edge-case",
        "category": "boundary",
        "z_score": 2,
        "value": "normal",
        "task": "写一个函数 safe_divide(a, b)，安全地执行除法。如果除数为 0 返回 None。",
        "buggy_code": '''def safe_divide(a, b):
    if b == 0:
        return None
    return a / b  # BUG: 非数字输入（如字符串）会导致 TypeError''',
        "expected_bugs": ["仅处理除零，未处理非数字输入 TypeError", "字符串 '0' 通过 b==0 检查但除法报错"],
        "ground_truth": "FAIL",
    },
    {
        "id": "case3",
        "title": "算法选择 / O(n²)",
        "error_type": "L3: algorithm / inefficient",
        "category": "algorithm",
        "z_score": 2,
        "value": "normal",
        "task": "写一个函数 has_duplicate(lst)，判断列表中是否有重复元素。",
        "buggy_code": '''def has_duplicate(lst):
    for i in range(len(lst)):
        for j in range(i+1, len(lst)):
            if lst[i] == lst[j]:
                return True
    return False  # BUG: O(n²)，大数据量不可用''',
        "expected_bugs": ["O(n²) 双重循环，大数据量性能不可接受", "应使用 set 实现 O(n)"],
        "ground_truth": "PASS",  # 功能正确，但质量差——属于主观评判
    },
    {
        "id": "case4",
        "title": "类型错误 / 字符串混入",
        "error_type": "L1: type error / type-confusion",
        "category": "logic_error",
        "z_score": 2,
        "value": "normal",
        "task": "写一个函数 sum_numbers(items)，对列表中的所有数字求和。",
        "buggy_code": '''def sum_numbers(items):
    total = 0
    for x in items:
        total += x  # BUG: 如果 items 包含字符串，会 TypeError: int+str
    return total''',
        "expected_bugs": ["字符串混入导致 TypeError", "应使用 isinstance 过滤非数字"],
        "ground_truth": "FAIL",
    },
    {
        "id": "case5",
        "title": "索引越界 / 回文判断",
        "error_type": "L1: index error / wrong-condition",
        "category": "logic_error",
        "z_score": 2,
        "value": "normal",
        "task": "写一个函数 is_palindrome(s)，判断字符串是否是回文。",
        "buggy_code": '''def is_palindrome(s):
    n = len(s)
    for i in range(n):
        if s[i] != s[n - i]:  # BUG: i=0 时访问 s[n] 越界
            return False
    return True''',
        "expected_bugs": ["i=0 时 s[n-i] = s[n] 越界", "应为 s[n-1-i]，且循环只需到 n//2"],
        "ground_truth": "FAIL",
    },
    {
        "id": "case6",
        "title": "空列表 / 边界条件",
        "error_type": "L1: boundary / empty-input",
        "category": "boundary",
        "z_score": 2,
        "value": "normal",
        "task": "写一个函数 find_max(lst)，返回列表中的最大值。",
        "buggy_code": '''def find_max(lst):
    max_val = lst[0]  # BUG: 空列表 IndexError
    for x in lst[1:]:
        if x > max_val:
            max_val = x
    return max_val''',
        "expected_bugs": ["空列表 lst[0] IndexError", "需前置 if not lst: return None"],
        "ground_truth": "FAIL",
    },
    {
        "id": "case7",
        "title": "资源泄露 / 文件未关闭",
        "error_type": "L2: resource leak / missing-cleanup",
        "category": "security",
        "z_score": 4,
        "value": "normal",
        "task": "写一个函数 count_lines(filename)，返回文件的行数。",
        "buggy_code": '''def count_lines(filename):
    f = open(filename)  # BUG: 未用 with，文件可能不关闭
    lines = f.readlines()
    return len(lines)  # BUG: 未处理 FileNotFoundError''',
        "expected_bugs": ["文件未关闭（资源泄露）", "FileNotFoundError 未处理"],
        "ground_truth": "FAIL",
    },
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
        "id": "case9",
        "title": "负数输入 / 斐波那契",
        "error_type": "L2: boundary / negative input",
        "category": "boundary",
        "z_score": 4,
        "value": "normal",
        "task": "写一个函数 fibonacci(n)，返回第 n 个斐波那契数（0-indexed：fib(0)=0, fib(1)=1）。",
        "buggy_code": '''def fibonacci(n):
    if n <= 1:
        return n  # BUG: 负数静默返回负数
    a, b = 0, 1
    for _ in range(n-1):
        a, b = b, a + b
    return b''',
        "expected_bugs": ["负数输入静默返回负数而非报错", "斐波那契序列仅对 n>=0 定义"],
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
    # ============================================================
    # 第二阶段：深度对抗（7 用例）
    # ============================================================
    {
        "id": "S1",
        "title": "前提错误 / 整除丢余数",
        "error_type": "L2: premise error",
        "category": "deep_adversarial",
        "z_score": 5,
        "value": "normal",
        "task": "写一个函数 split_bill(total, people)，将账单（total 分）平分给每个人。total 是整数，people 是名字列表。返回 {名字: 金额} 字典。",
        "snake_head_analysis": "这是一个简单的除法问题。将 total 除以 len(people) 得到每人应付金额。由于金额必须是整数分，使用整除 //。约束：total 和 len(people) 均为正整数，整除不会抛异常。风险点：无，逻辑简单明确。",
        "buggy_code": '''def split_bill(total, people):
    avg = total // len(people)  # BUG: 整除丢余数，总和可能≠total
    return {p: avg for p in people}''',
        "expected_bugs": ["整除丢余数，总和≠total", "应分配余数：前 remainder 人各+1"],
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
        "id": "S3",
        "title": "主观评判 / 代码质量差",
        "error_type": "L4: subjective / code quality",
        "category": "deep_adversarial",
        "z_score": 3,
        "value": "normal",
        "task": "写一个函数 process_orders(orders)，按类型打折处理订单。类型 A=9折，B=满100减20，C=原价。返回总金额。",
        "buggy_code": '''def process_orders(orders):
    total = 0
    count = 0
    for o in orders:
        p = o['price']
        if o['type'] == 'A':
            p = p * 0.9
        elif o['type'] == 'B':
            if p >= 100:
                p = p - 20
        elif o['type'] == 'C':
            p = p
        total += p
        count += 1
    return total  # BUG: 功能正确但8个质量问题''',
        "expected_bugs": ["魔法字符串/数字", "违反开闭原则", "无输入校验", "高耦合", "变量命名差", "冗余累加器", "无docstring"],
        "ground_truth": "PASS",  # 功能正确，但质量差——主观评判
    },
    {
        "id": "S4",
        "title": "蛇头冲突 / 双蛇分歧",
        "error_type": "L3: snake head conflict",
        "category": "deep_adversarial",
        "z_score": 6,
        "value": "normal",
        "task": "写一个函数 parse_date_range(expr)，解析 'YYYY-MM-DD to YYYY-MM-DD' 格式的日期范围，返回日期列表。",
        "buggy_code": '''def parse_date_range(expr):
    parts = expr.split(' ')
    start = parts[0]
    end = parts[2]  # BUG: 假设精确格式，未处理多余空格/大小写变体
    from datetime import datetime, timedelta
    s = datetime.strptime(start, '%Y-%m-%d')
    e = datetime.strptime(end, '%Y-%m-%d')
    return [(s + timedelta(days=i)).strftime('%Y-%m-%d') for i in range((e-s).days+1)]''',
        "expected_bugs": ["假设精确格式，未处理多余空格", "未处理 'To'/'TO' 大小写变体", "无输入校验"],
        "ground_truth": "PASS",  # 对于给定需求基本正确
    },
    {
        "id": "S5",
        "title": "监督盲区 / 双蛇同错",
        "error_type": "L2: dual consensus error",
        "category": "deep_adversarial",
        "z_score": 5,
        "value": "normal",
        "task": "写一个函数 binary_search(arr, target)，在有序数组中二分查找目标值，返回索引或 -1。",
        "snake_head_analysis": "标准二分查找。维护 left/right 指针，每次取 mid 比较后更新边界。循环条件 left < right，因为当 left==right 时只剩一个元素。风险点：无，经典算法。",
        "buggy_code": '''def binary_search(arr, target):
    left, right = 0, len(arr) - 1
    while left < right:  # BUG: 应为 <=
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid  # BUG: 应为 mid + 1
        else:
            right = mid  # BUG: 应为 mid - 1
    return -1''',
        "expected_bugs": ["left=mid 导致死循环", "right=mid 导致死循环", "循环条件 left<right 应为 left<=right"],
        "ground_truth": "FAIL",
    },
    {
        "id": "S6",
        "title": "回归检测 / 浅拷贝陷阱",
        "error_type": "L3: regression / shallow copy",
        "category": "deep_adversarial",
        "z_score": 6,
        "value": "high",
        "task": "写一个函数 merge_dicts(d1, d2)，将 d2 的键值合并到 d1，返回合并结果，不修改原始输入。",
        "buggy_code": '''def merge_dicts(d1, d2):
    result = d1.copy()  # BUG: 浅拷贝，嵌套可变对象仍共享引用
    for k, v in d2.items():
        result[k] = v
    return result''',
        "expected_bugs": ["浅拷贝：嵌套 dict/list 仍共享引用", "修改 result 的嵌套对象会污染 d1", "应使用 copy.deepcopy"],
        "ground_truth": "FAIL",
    },
    {
        "id": "S7",
        "title": "矫枉过正 / 修复边界",
        "error_type": "L2: interface / strict repair",
        "category": "deep_adversarial",
        "z_score": 4,
        "value": "normal",
        "task": "写一个函数 format_name(first, last)，返回 'Last, First' 格式。",
        "buggy_code": '''def format_name(first, last):
    return last + ', ' + first  # BUG: 未做类型检查''',
        "expected_bugs": ["未检查 first/last 是否为字符串", "None 值导致 TypeError"],
        "ground_truth": "FAIL",
    },
]

# 分类汇总
CATEGORIES = {
    "L1_explicit": ["case1", "case2", "case4", "case5", "case6", "case8"],
    "L2_logic": ["case7", "case9", "S1", "S5", "S7"],
    "L3_domain": ["case3", "case10", "S2", "S4", "S6"],
    "L4_subjective": ["S3"],
}

# P0-前置A/B 已测用例（6个）
PRE_TESTED_CASES = ["case1", "case5", "case9", "case10", "S1", "S5"]

# 待测用例（11个）
UNTESTED_CASES = [c["id"] for c in TEST_CASES if c["id"] not in PRE_TESTED_CASES]

# V×Z 分层映射
def get_vz_config(case):
    """根据 V×Z 返回推荐配置"""
    z = case["z_score"]
    v = case["value"]
    
    if z <= 3 and v == "normal":
        return {"judges": 2, "level": "L1", "deep_dive": False, "tier": "standard"}
    elif z <= 3 and v == "high":
        return {"judges": 3, "level": "L2", "deep_dive": False, "tier": "standard"}
    elif z <= 6:
        return {"judges": 3, "level": "L2", "deep_dive": True, "tier": "strict"}
    else:
        return {"judges": 3, "level": "L3", "deep_dive": True, "tier": "heavy"}

if __name__ == "__main__":
    print(f"总用例数: {len(TEST_CASES)}")
    print(f"已测: {len(PRE_TESTED_CASES)} ({', '.join(PRE_TESTED_CASES)})")
    print(f"待测: {len(UNTESTED_CASES)} ({', '.join(UNTESTED_CASES)})")
    for c in TEST_CASES:
        config = get_vz_config(c)
        print(f"  {c['id']}: Z={c['z_score']}, V={c['value']} → {config['tier']} ({config['judges']}法官, {config['level']})")
