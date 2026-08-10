#!/usr/bin/env python
"""
R11 结构化模板 + 反轻信指令 验证实验
对比P2基线,测试结构化deviation_log和反轻信指令对法官判断的影响

场景S1: compute_variance(无偏离)- 蛇身遵循蛇头规划
场景S2: process_sales_csv(主动偏离)- 蛇身用csv替代pandas

每组各2个模型法官:deepseek-v4-pro (t=0.7) + gemini-3.6-flash (t=0.3)
A组:只看代码
B组:看代码 + 结构化deviation_log + 反轻信指令
"""
import json, time, os, sys, requests

# ============================================================
# API配置
# ============================================================
import yaml
with open(r'C:/Users/GOD/AppData/Local/hermes/config.yaml') as f:
    config = yaml.safe_load(f)
tokeness_provider = [x for x in config['custom_providers'] if x['name'] == 'tokeness'][0]
API_KEY = tokeness_provider['api_key']
BASE_URL = "https://n.tokeness.io/v1/chat/completions"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def call_llm(model, messages, temperature=0.3, max_tokens=3000, max_retries=3):
    """Call the LLM API and return (content, usage_dict)."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
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
# 场景定义
# ============================================================

# S1: compute_variance - 无偏离场景
S1_SNAKE_HEAD_PLAN = """# compute_variance(data) 实现计划

## 1. 算法选择与理由

计算总体方差有两种主流算法,需要权衡:

**方案 A:两遍遍历法(Two-pass algorithm)**
- 第一遍:计算均值 `mean = sum(data) / n`
- 第二遍:计算 `sum((x - mean)^2 for x in data) / n`
- 优点:数值稳定性好,实现简单直观
- 缺点:需要遍历两次数据

**方案 B:Welford 在线算法(单遍遍历)**
- 边遍历边维护均值和平方差累积量,递推更新
- 优点:只需一次遍历,且在流式/大数据场景下数值稳定性优于朴素单遍公式 `E[X^2] - E[X]^2`
- 缺点:实现稍复杂

**决策:优先选择方案 A(两遍遍历法)**,理由:
- 任务输入是"列表"(已知长度,可重复访问),不是流式数据,两次遍历的额外开销可忽略(仍是 O(n))
- 两遍法逻辑清晰,易于验证正确性,数值稳定性已经足够好
- 如果后续需要支持超大数据流或增量更新,再切换为 Welford 算法

**绝对不采用**朴素单遍公式 `E[X^2] - E[X]^2`,因为该算法在大数场景下容易发生灾难性抵消(catastrophic cancellation),甚至可能返回负方差.

## 2. 边界条件与异常处理

- **空列表**:应抛出明确异常(如 `ValueError("data must not be empty")`),不应返回 0 或 None(语义错误)
- **单元素列表**:方差为 0,函数应自然返回 0.0
- **非数值元素**:不做特殊检查,由 Python 自带 TypeError 自然传播(调用方责任)
- **列表元素含 NaN 或 inf**:不做特殊处理,让其自然传播(结果为 NaN 或 inf),但在文档注明该行为

## 3. 输入类型约束

- 参数类型应为 `Sequence[float]`,允许 list,tuple 等可重复迭代的序列
- 不强制转换为 list(空间 O(1) 额外存储)

## 4. 复杂度分析

- 时间:O(n)(两次遍历,仍是线性)
- 空间:O(1)"""

S1_CODE = """from typing import Sequence

def compute_variance(data: Sequence[float]) -> float:
    \"\"\"
    计算总体方差(两遍遍历法).
    
    参数:
        data: 数值序列(支持多次迭代的 Sequence 类型,如 list, tuple)
        
    返回:
        float: 总体方差
        
    异常:
        ValueError: 输入序列为空
        TypeError: 输入不是可迭代对象或元素包含非数值类型(由底层运算自然触发)
    \"\"\"
    if len(data) == 0:
        raise ValueError("data must not be empty")
    n = len(data)
    mean = sum(data) / n
    variance = sum((x - mean) ** 2 for x in data) / n
    return variance"""

# S1: 结构化 deviation_log(无偏离)
S1_STRUCTURED_DEVLOG = """[步骤ID] step_1_algo
[是否偏离] 否
[已执行操作] 采用两遍遍历法(方案A):第一遍 sum(data)/n 求均值,第二遍 sum((x-mean)^2)/n 求方差.返回 float 类型总体方差.
[偏离原因] 
[已规避风险] 
[未处理场景] 
[我无法确认] docstring中未说明NaN/inf传播行为是否满足plan要求——plan要求注明但实际docstring未提及

[步骤ID] step_2_boundary
[是否偏离] 否
[已执行操作] 空列表抛出 ValueError("data must not be empty");单元素自然返回0.0;非数值由Python自带TypeError传播
[偏离原因] 
[已规避风险] 
[未处理场景] 
[我无法确认] 无

[步骤ID] step_3_type_constraint
[是否偏离] 否
[已执行操作] 参数类型 Sequence[float],不强制转list,保持O(1)额外空间
[偏离原因] 
[已规避风险] 
[未处理场景] 
[我无法确认] 无"""

# S2: process_sales_csv - 主动偏离场景
S2_SNAKE_HEAD_PLAN = """# `process_sales_csv(input_path, output_path)` 实现计划

## 1. 使用的库和工具选择

- **pandas**:优先选择,理由是内置 CSV 解析,分组聚合(`groupby`),类型转换和缺失值处理都很成熟,代码量少且易维护.
- 若项目要求零依赖(仅标准库),备选方案:`csv` 模块读取 + `collections.defaultdict` 做累加,`decimal.Decimal` 处理金额避免浮点误差.
- 日志使用标准库 `logging`,用于记录跳过的异常行,警告信息.
- 文件路径操作使用 `pathlib.Path`,便于跨平台校验和处理.

本计划以 **pandas 方案为主**,标准库方案作为备选说明.

## 2. 数据处理流程

1. **输入校验**
   - 检查 `input_path` 是否存在,是否为文件,扩展名是否为 `.csv`(非强制,仅告警).
   - 检查 `output_path` 所在目录是否存在,不存在则尝试创建(`Path.parent.mkdir(parents=True)`).

2. **数据读取与清洗**
   - 使用 `pd.read_csv(input_path)` 读取 CSV
   - 列名校验:必须包含 `date, product, quantity, price` 四列(不区分大小写,自动映射)
   - 日期解析:使用 `pd.to_datetime(column, errors='coerce')`,解析失败的行标记为异常
   - 数值转换:使用 `pd.to_numeric(column, errors='coerce')` 转换 quantity 和 price
   - 缺失值处理:丢弃任何含 NaN 的行,记录日志
   - 异常数据记录:对于被跳过的行,记录行号,原始内容,异常原因到日志

3. **业务计算**
   - 按 `product` 分组,对 `quantity` 求和,对 `price * quantity` 求和得到总金额
   - 计算每个产品的平均单价:总金额 / 总数量
   - 结果按总金额降序排列

4. **输出**
   - 根据 `output_path` 扩展名决定输出格式:
     - `.csv`:使用 `df.to_csv(index=False)`
     - `.xlsx`:使用 `df.to_excel`,可增加表头样式(需 `openpyxl`)
   - 末尾可追加一行 TOTAL 汇总行(可选)
   - 单独输出一份异常数据文件供人工核查(可选增强功能)
   - 输出路径无写权限:捕获 `PermissionError`,向上抛出明确提示

5. **返回值**
   - 返回处理摘要字典:包含处理行数,跳过行数,产品数量,总金额等信息

## 3. 容错与边界

- 文件编码:尝试 UTF-8,失败则回退 GBK/Big5
- quantity 必须为非负整数,price 必须为非负数(允许 0)
- 日期解析失败的行标记为异常并跳过
- 空字符串,空白字符串视为缺失值"""

S2_CODE = """import csv
import logging
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import sys

# 配置日志,默认输出到 stderr,可由调用方进一步配置
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# 常量定义
REQUIRED_COLUMNS = {'date', 'product', 'quantity', 'price'}
# 尝试解析的日期格式列表
DATE_FORMATS = [
    '%Y-%m-%d',
    '%Y/%m/%d',
    '%d-%m-%Y',
    '%d/%m/%Y',
    '%m-%d-%Y',
    '%m/%d/%Y',
    '%Y%m%d',
]
OUTPUT_DEFAULT_EXT = '.csv'

def _parse_date(date_str: str) -> Optional[datetime]:
    """尝试多种格式解析日期字符串,返回 datetime 对象或 None"""
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

def _to_decimal(value_str: str, column_name: str) -> Optional[Decimal]:
    """将字符串转为 Decimal,返回 None 若失败"""
    if value_str is None:
        return None
    cleaned = value_str.strip()
    if not cleaned:
        return None
    try:
        d = Decimal(cleaned)
        return d
    except (InvalidOperation, ValueError) as e:
        logger.debug(f"无法将 {column_name} 转为 Decimal: '{value_str}' -> {e}")
        return None

def _validate_quantity(d: Decimal) -> bool:
    """校验数量:必须为非负整数"""
    if d.is_signed() and d < 0:
        return False
    # 检查是否为整数:无小数部分
    if d % 1 != 0:
        return False
    return True

def _validate_price(d: Decimal) -> bool:
    """校验价格:必须为非负数"""
    if d.is_signed() and d < 0:
        return False
    return True

def process_sales_csv(input_path: str, output_path: str) -> Dict[str, Any]:
    """
    处理销售CSV文件,按产品汇总并生成报告.
    
    参数:
        input_path: 输入CSV文件路径
        output_path: 输出文件路径(支持.csv或.xlsx后缀)
        
    返回:
        Dict[str, Any]: 处理摘要
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    
    # 输入校验
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")
    if not input_path.is_file():
        raise ValueError(f"输入路径不是文件: {input_path}")
    if input_path.suffix.lower() != '.csv':
        logger.warning(f"输入文件扩展名非.csv: {input_path.suffix}")
    
    # 创建输出目录
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 读取CSV
    rows = []
    with open(input_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        # 列名校验
        actual_cols = set(reader.fieldnames or [])
        normalized_cols = {c.strip().lower() for c in actual_cols}
        required_normalized = {c.lower() for c in REQUIRED_COLUMNS}
        if not required_normalized.issubset(normalized_cols):
            missing = required_normalized - normalized_cols
            raise ValueError(f"CSV缺少必需列: {missing}")
        
        for row in reader:
            rows.append(row)
    
    # 数据处理
    product_data = defaultdict(lambda: {'total_quantity': Decimal('0'), 'total_amount': Decimal('0')})
    skipped = 0
    total_rows = len(rows)
    
    for i, row in enumerate(rows, 1):
        # 标准化列名
        normalized = {k.strip().lower(): v for k, v in row.items()}
        
        # 校验必填字段
        date_str = normalized.get('date', '')
        product = normalized.get('product', '')
        quantity_str = normalized.get('quantity', '')
        price_str = normalized.get('price', '')
        
        # 检查空值
        if not product or not product.strip():
            logger.warning(f"第{i}行跳过: 产品名称为空")
            skipped += 1
            continue
        
        # 解析日期
        date_obj = _parse_date(date_str)
        if date_obj is None:
            logger.warning(f"第{i}行跳过: 无效日期 '{date_str}'")
            skipped += 1
            continue
        
        # 解析数值
        quantity = _to_decimal(quantity_str, 'quantity')
        price = _to_decimal(price_str, 'price')
        
        if quantity is None:
            logger.warning(f"第{i}行跳过: quantity 无法解析 '{quantity_str}'")
            skipped += 1
            continue
        if price is None:
            logger.warning(f"第{i}行跳过: price 无法解析 '{price_str}'")
            skipped += 1
            continue
        
        if not _validate_quantity(quantity):
            logger.warning(f"第{i}行跳过: quantity 非法值 {quantity}")
            skipped += 1
            continue
        if not _validate_price(price):
            logger.warning(f"第{i}行跳过: price 非法值 {price}")
            skipped += 1
            continue
        
        # 累加
        product_data[product]['total_quantity'] += quantity
        product_data[product]['total_amount'] += quantity * price
    
    # 计算平均单价并排序
    summary = []
    for product, data in product_data.items():
        qty = data['total_quantity']
        amt = data['total_amount']
        avg_price = amt / qty if qty > 0 else Decimal('0')
        summary.append({
            'product': product,
            'total_quantity': int(qty),
            'total_amount': float(amt.quantize(Decimal('0.01'))),
            'avg_price': float(avg_price.quantize(Decimal('0.01')))
        })
    
    summary.sort(key=lambda x: x['total_amount'], reverse=True)
    
    # 写入输出
    out_ext = output_path.suffix.lower()
    if out_ext == '.xlsx':
        logger.warning(f".xlsx 输出不支持(未安装 openpyxl),降级为 .csv 格式")
        out_ext = '.csv'
        output_path = output_path.with_suffix('.csv')
    
    if out_ext == '.csv':
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['product', 'total_quantity', 'total_amount', 'avg_price'])
            writer.writeheader()
            writer.writerows(summary)
            # 追加TOTAL汇总行
            total_qty = sum(s['total_quantity'] for s in summary)
            total_amt = sum(s['total_amount'] for s in summary)
            writer.writerow({
                'product': 'TOTAL',
                'total_quantity': total_qty,
                'total_amount': round(total_amt, 2),
                'avg_price': round(total_amt / total_qty, 2) if total_qty > 0 else 0
            })
    
    return {
        'total_rows': total_rows,
        'processed_rows': total_rows - skipped,
        'skipped_rows': skipped,
        'product_count': len(summary),
        'total_amount': round(sum(s['total_amount'] for s in summary), 2)
    }"""

# S2: 结构化 deviation_log(主动偏离)
S2_STRUCTURED_DEVLOG = """[步骤ID] step_1_library_choice
[是否偏离] 是
[已执行操作] 未使用pandas,改用标准库csv模块+collections.defaultdict+decimal.Decimal实现
[偏离原因] 减少外部依赖,使代码零依赖可部署;Decimal避免浮点误差更精确
[已规避风险] 避免了pandas安装/版本兼容问题
[未处理场景] 未实现plan中pandas方案下的df.to_excel(.xlsx输出),pd.to_datetime自动推断日期格式
[我无法确认] 蛇头将pandas列为主方案,csv为备选方案,切换是否需审批?是否影响后续与其他模块的集成?

[步骤ID] step_2_input_validation
[是否偏离] 否
[已执行操作] 检查input_path存在性和文件类型;创建output_path父目录;校验CSV列名
[偏离原因] 
[已规避风险] 
[未处理场景] 
[我无法确认] 未额外检测文件编码(仅用utf-8,未按plan尝试GBK/Big5回退)

[步骤ID] step_3_data_read_cleanse
[是否偏离] 是
[已执行操作] 自行实现日期解析(预定义格式列表逐一尝试)而非pd.to_datetime(errors='coerce')
[偏离原因] 标准库无pandas的自动推断日期功能
[已规避风险] 预定义格式列表覆盖常见格式,避免自动推断的不确定性
[未处理场景] 非标准日期格式(如"2026年8月4日")无法解析
[我无法确认] 日期格式列表是否足够覆盖实际数据中的变体?

[步骤ID] step_4_business_calc
[是否偏离] 否
[已执行操作] 按product分组,quantity求和,amount=quantity*price求和;计算avg_price=amount/qty;按amount降序排列
[偏离原因] 
[已规避风险] 
[未处理场景] 
[我无法确认] 无

[步骤ID] step_5_output
[是否偏离] 是
[已执行操作] .xlsx后缀时降级输出为.csv并记录警告,而非使用openpyxl/df.to_excel
[偏离原因] 未引入openpyxl依赖
[已规避风险] 降级处理避免程序崩溃
[未处理场景] 真正的Excel用户需求未被满足;未实现plan中的"表头样式"增强
[我无法确认] 降级行为是否应向调用方抛异常而非静默替换格式?

[步骤ID] step_6_error_logging
[是否偏离] 是
[已执行操作] 日志仅记录行号和跳过原因描述,未记录行的完整原始内容
[偏离原因] 减少日志冗余,行号已可回溯原文件
[已规避风险] 无
[未处理场景] plan要求记录"行号,原始内容,异常原因"三要素
[我无法确认] 省略原始内容是否会导致线上排查困难?

[步骤ID] step_7_exception_export
[是否偏离] 是
[已执行操作] 未生成单独的异常数据文件(plan中的可选增强功能)
[偏离原因] 标记为可选功能,未实现
[已规避风险] 无
[未处理场景] 人工核查缺乏异常数据文件作为参考
[我无法确认] 可选功能未实现是否需要记录为偏离?

[步骤ID] step_8_return_value
[是否偏离] 否
[已执行操作] 返回处理摘要字典(total_rows, processed_rows, skipped_rows, product_count, total_amount)
[偏离原因] 
[已规避风险] 
[未处理场景] 
[我无法确认] 摘要中未包含plan提到的文件编码信息"""

# ============================================================
# 反轻信指令(追加到B组法官Prompt末尾)
# ============================================================
ANTI_GULLIBILITY_INSTRUCTION = """
[反轻信指令]
你审查的deviation_log是蛇身自述报告,可能不完整.强制检查:
1. 列出log中声明的每一步偏离
2. 交叉比对detailed_log:log声称的偏离是否与原始数据一致?是否有log未提及但数据显示的操作差异?
3. 指出任何遗漏,不一致或过度合理化
4. 如认为log不完整,明确指出"我无法基于当前log做出完整判断"

以"[执行日志审查结果]"开头
"""

# ============================================================
# Judge Prompt构建
# ============================================================

def build_judge_prompt_group_a(scenario_label, task_desc, snake_head_plan, code):
    """A组:只看代码+蛇头规划"""
    return f"""你是蛇群架构的独立法官.请对比蛇头规划和蛇身实际代码,审查偏离情况.

【场景】{scenario_label}
【任务】{task_desc}

【蛇头规划】
{snake_head_plan}

【蛇身代码】
```python
{code}
```

请逐项对比规划与实际代码,找出所有偏离点.对每个偏离说明:
1. 偏离类别(关键偏离/次要偏离/无影响偏离)
2. 偏离描述(plan要求什么 vs 代码实际做了什么)
3. 合理性判断(合理/不合理/待商榷)
4. 判断理由

注意:偏离不等于bug.偏离指实际代码与蛇头规划的决策不一致,即便功能正确也算偏离.

最后输出:
- 偏离总数
- 每个偏离的详细信息
- 总体评价"""

def build_judge_prompt_group_b(scenario_label, task_desc, snake_head_plan, code, structured_devlog):
    """B组:代码+结构化deviation_log+反轻信指令"""
    return f"""你是蛇群架构的独立法官.请对比蛇头规划和蛇身实际代码,审查偏离情况.你将看到蛇身的结构化自述偏差日志,请结合日志进行审查.

【场景】{scenario_label}
【任务】{task_desc}

【蛇头规划】
{snake_head_plan}

【蛇身代码】
```python
{code}
```

【蛇身结构化偏差日志】
{structured_devlog}

请逐项对比规划与实际代码,找出所有偏离点.对每个偏离说明:
1. 偏离类别(关键偏离/次要偏离/无影响偏离)
2. 偏离描述(plan要求什么 vs 代码实际做了什么)
3. 合理性判断(合理/不合理/待商榷)
4. 判断理由

注意:
- 偏离不等于bug.偏离指实际代码与蛇头规划的决策不一致
- 如果deviation_log中已记录的偏离与你发现的偏离一致,请注明"已在devlog中记录"
- 如果你发现devlog未记录的偏离,请特别标注"devlog遗漏"
- 如果devlog记录的偏离实际并非偏离或过度合理化,请标注"devlog误报"

最后输出:
- 偏离总数(区分:devlog已记录 vs devlog遗漏 vs devlog误报)
- 每个偏离的详细信息
- 对deviation_log完整性的评价
- 总体评价""" + ANTI_GULLIBILITY_INSTRUCTION

# ============================================================
# 结果解析
# ============================================================

def parse_judge_output(content):
    """解析法官输出,提取偏离数和关键信息"""
    if not content:
        return {"total_deviations": 0, "deviations_found": [], "summary": "ERROR: No response", "log_audit": None}
    
    # 尝试提取偏离总数
    import re
    total = 0
    # 多种匹配模式
    patterns = [
        r'偏离总数[::]\s*(\d+)',
        r'total_deviations[::]\s*(\d+)',
        r'共.*?(\d+)\s*[个项条].*?偏离',
        r'发现.*?(\d+)\s*[个项条].*?偏离',
    ]
    for p in patterns:
        m = re.search(p, content, re.IGNORECASE)
        if m:
            total = int(m.group(1))
            break
    
    # If no explicit count, count deviation markers
    if total == 0:
        # Count deviation descriptions
        markers = ['关键偏离', '次要偏离', '无影响偏离']
        count = 0
        for m in markers:
            count += content.count(m)
        total = count if count > 0 else 0
    
    # Extract deviations
    deviations = []
    lines = content.split('\n')
    current_dev = None
    
    for line in lines:
        line = line.strip()
        if any(m in line for m in ['关键偏离', '次要偏离', '无影响偏离']):
            if current_dev:
                deviations.append(current_dev)
            current_dev = {'description': line[:200]}
        elif current_dev and line:
            current_dev['description'] = current_dev.get('description', '') + ' ' + line[:100]
    
    if current_dev:
        deviations.append(current_dev)
    
    # Extract log audit for Group B
    log_audit = None
    if '[执行日志审查结果]' in content:
        idx = content.find('[执行日志审查结果]')
        log_audit = content[idx:idx+1000]
    
    # Extract summary
    summary = content[-500:] if len(content) > 500 else content
    
    return {
        "total_deviations": total,
        "deviations_found": deviations,
        "summary": summary,
        "log_audit": log_audit
    }

# ============================================================
# 主实验
# ============================================================

def run_experiment():
    os.makedirs("D:/competation/design/experiments/results", exist_ok=True)
    
    scenarios = [
        {
            "id": "S1",
            "label": "S1: compute_variance(无偏离)",
            "task": "写一个函数 compute_variance(data),计算总体方差",
            "plan": S1_SNAKE_HEAD_PLAN,
            "code": S1_CODE,
            "devlog": S1_STRUCTURED_DEVLOG,
            "expected_deviation": False
        },
        {
            "id": "S2",
            "label": "S2: process_sales_csv(主动偏离)",
            "task": "写一个函数 process_sales_csv(input_path, output_path),处理销售CSV生成报告",
            "plan": S2_SNAKE_HEAD_PLAN,
            "code": S2_CODE,
            "devlog": S2_STRUCTURED_DEVLOG,
            "expected_deviation": True
        }
    ]
    
    judge_configs = [
        {"model": "deepseek-v4-pro", "temperature": 0.7, "tag_suffix": "DSV"},
        {"model": "gemini-3.6-flash", "temperature": 0.3, "tag_suffix": "GEM"},
    ]
    
    all_results = []
    
    for scenario in scenarios:
        print(f"\n{'='*70}")
        print(f"  {scenario['label']}")
        print(f"{'='*70}")
        
        # Group A: 纯代码
        print(f"\n  [Group A] 纯代码审查...")
        for jc in judge_configs:
            tag = f"{scenario['id']}-A-{jc['tag_suffix']}"
            print(f"    -> {tag} ({jc['model']}, t={jc['temperature']})...", end=" ", flush=True)
            
            prompt = build_judge_prompt_group_a(
                scenario['label'], scenario['task'],
                scenario['plan'], scenario['code']
            )
            content, usage = call_llm(
                jc['model'],
                [{"role": "user", "content": prompt}],
                temperature=jc['temperature'],
                max_tokens=4000
            )
            
            parsed = parse_judge_output(content)
            result = {
                "tag": tag,
                "scenario": scenario['id'],
                "group": "A",
                "group_desc": "纯代码",
                "model": jc['model'],
                "temperature": jc['temperature'],
                "parsed": parsed,
                "usage": usage,
                "raw_content": content[:300] if content else "ERROR"
            }
            all_results.append(result)
            
            print(f"{parsed['total_deviations']} deviations, {usage.get('total_tokens', 0)} tokens")
            time.sleep(1)
        
        # Group B: 代码+结构化devlog+反轻信指令
        print(f"\n  [Group B] 代码+结构化devlog+反轻信指令...")
        for jc in judge_configs:
            tag = f"{scenario['id']}-B-{jc['tag_suffix']}"
            print(f"    -> {tag} ({jc['model']}, t={jc['temperature']})...", end=" ", flush=True)
            
            prompt = build_judge_prompt_group_b(
                scenario['label'], scenario['task'],
                scenario['plan'], scenario['code'],
                scenario['devlog']
            )
            content, usage = call_llm(
                jc['model'],
                [{"role": "user", "content": prompt}],
                temperature=jc['temperature'],
                max_tokens=4000
            )
            
            parsed = parse_judge_output(content)
            result = {
                "tag": tag,
                "scenario": scenario['id'],
                "group": "B",
                "group_desc": "代码+结构化devlog+反轻信指令",
                "model": jc['model'],
                "temperature": jc['temperature'],
                "parsed": parsed,
                "usage": usage,
                "raw_content": content[:300] if content else "ERROR"
            }
            all_results.append(result)
            
            print(f"{parsed['total_deviations']} deviations, {usage.get('total_tokens', 0)} tokens")
            print(f"       Log audit: {'Yes' if parsed.get('log_audit') else 'No log audit section found'}")
            time.sleep(1)
    
    return all_results

# ============================================================
# 对比分析
# ============================================================

def analyze_and_compare(r11_results):
    """对比R11结果与P2基线"""
    import json as _json
    
    # Load P2 baseline
    with open("D:/competation/design/experiments/results/p2_deviation_log.json", 'r', encoding='utf-8') as f:
        p2 = _json.load(f)
    
    # P2 baseline deviations
    p2_data = {}
    for je in p2['judge_evaluations']:
        p2_data[je['tag']] = je['parsed']['total_deviations']
    
    # R11 deviations
    r11_data = {}
    for r in r11_results:
        r11_data[r['tag']] = r['parsed']['total_deviations']
    
    # Build comparison
    comparison = {
        "experiment": "R11_structured_devlog_validation",
        "timestamp": "2026-08-04",
        "hypotheses": {
            "H1": "结构化模板减少deviation_log遗漏和误报",
            "H2": "反轻信指令消除法官的log催眠效应"
        },
        "methods": {
            "S1": "compute_variance(无偏离),蛇身遵循蛇头规划",
            "S2": "process_sales_csv(主动偏离),蛇身用csv替代pandas",
            "R11_changes": [
                "deviation_log改用结构化模板(步骤ID/是否偏离/已执行操作/偏离原因/已规避风险/未处理场景/我无法确认)",
                "B组法官prompt末尾追加反轻信指令(4项强制检查)",
                "B组法官被要求区分devlog已记录/遗漏/误报"
            ]
        },
        "per_judge_comparison": {},
        "scenario_analysis": {},
        "log_hypnosis_analysis": {}
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
        scenario_analysis = {
            "A_纯代码": {},
            "B_代码+devlog": {}
        }
        
        for group in ['A', 'B']:
            group_label = "A_纯代码" if group == 'A' else "B_代码+devlog"
            for model_tag in ['DSV', 'GEM']:
                tag = f"{sid}-{group}-{model_tag}"
                p2_val = p2_data.get(tag, None)
                r11_val = r11_data.get(tag, None)
                scenario_analysis[group_label][model_tag] = {
                    "P2": p2_val,
                    "R11": r11_val,
                    "delta": (r11_val - p2_val) if (p2_val is not None and r11_val is not None) else None
                }
        
        # Calculate averages
        for gk, gv in scenario_analysis.items():
            p2_vals = [v['P2'] for v in gv.values() if v['P2'] is not None]
            r11_vals = [v['R11'] for v in gv.values() if v['R11'] is not None]
            gv['avg_P2'] = sum(p2_vals) / len(p2_vals) if p2_vals else None
            gv['avg_R11'] = sum(r11_vals) / len(r11_vals) if r11_vals else None
        
        comparison["scenario_analysis"][sid] = scenario_analysis
    
    # Log hypnosis analysis
    # Check if B group deviations changed more than A group
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
        
        comparison["log_hypnosis_analysis"][sid] = {
            "A组_平均变化": sum(a_delta) / len(a_delta) if a_delta else None,
            "B组_平均变化": sum(b_delta) / len(b_delta) if b_delta else None,
            "解释": ""
        }
        
        # Interpret
        a_avg = comparison["log_hypnosis_analysis"][sid]["A组_平均变化"]
        b_avg = comparison["log_hypnosis_analysis"][sid]["B组_平均变化"]
        if a_avg is not None and b_avg is not None:
            if b_avg > a_avg and b_avg > 0:
                comparison["log_hypnosis_analysis"][sid]["解释"] = "B组(代码+devlog)偏离发现数增加更多,反轻信指令可能有效提升了审查力度"
            elif b_avg < a_avg:
                comparison["log_hypnosis_analysis"][sid]["解释"] = "B组偏离发现数变化小于A组,可能需要进一步分析"
            else:
                comparison["log_hypnosis_analysis"][sid]["解释"] = "两组变化相近,无显著差异"
    
    # Check if B-group judges explicitly noted devlog issues (anti-gullibility effect)
    b_judge_log_audits = []
    for r in r11_results:
        if r['group'] == 'B' and r['parsed'].get('log_audit'):
            b_judge_log_audits.append({
                'tag': r['tag'],
                'has_log_audit': True,
                'audit_preview': r['parsed']['log_audit'][:300]
            })
    comparison["anti_gullibility_effect"] = {
        "B组法官是否响应反轻信指令": len(b_judge_log_audits),
        "details": b_judge_log_audits
    }
    
    # Overall conclusion
    comparison["conclusion"] = {
        "summary_cn": "",
        "detailed_cn": []
    }
    
    return comparison

def build_conclusion(comparison, r11_results):
    """Build Chinese-context conclusions"""
    lines = []
    
    lines.append("=== R11结构化模板+反轻信指令验证结论 ===\n")
    
    # 1. Deviation log quality improvement
    lines.append("## 1. 结构化模板对deviation_log质量的影响\n")
    
    for sid in ['S1', 'S2']:
        sa = comparison['scenario_analysis'][sid]
        lines.append(f"### 场景{sid}")
        
        for gk in ['A_纯代码', 'B_代码+devlog']:
            gv = sa[gk]
            lines.append(f"  {gk}: P2 avg={gv.get('avg_P2')}, R11 avg={gv.get('avg_R11')}")
        
        # Specific analysis
        if sid == 'S1':
            lines.append(f"  分析: S1为无偏离场景,理想情况下法官应发现0个偏离.")
            if sa['A_纯代码'].get('avg_R11', 0) <= sa['A_纯代码'].get('avg_P2', 0):
                lines.append(f"  → A组(纯代码)偏离发现数持平或减少,结构化devlog未引入干扰")
            if sa['B_代码+devlog'].get('avg_R11', 0) <= sa['B_代码+devlog'].get('avg_P2', 0):
                lines.append(f"  → B组(代码+devlog)偏离发现数持平或减少,结构化devlog+"我无法确认"字段可能帮助法官更准确判断")
        elif sid == 'S2':
            lines.append(f"  分析: S2为有偏离场景,理想情况下法官应发现所有真实偏离.")
            lines.append(f"  已知真实偏离: pandas→csv切换, .xlsx降级, 日志缺原始行内容, 未生成异常数据文件, 日期解析方式变更, 编码回退未实现")
            lines.append(f"  共约5-6个真实偏离点")
            if sa['B_代码+devlog'].get('avg_R11', 0) > sa['A_纯代码'].get('avg_R11', 0):
                lines.append(f"  → B组偏离发现数>A组,结构化devlog帮助法官发现更多偏离")
            elif sa['B_代码+devlog'].get('avg_R11', 0) < sa['A_纯代码'].get('avg_R11', 0):
                lines.append(f"  → B组偏离发现数<A组,警惕:即便结构化devlog仍可能存在催眠效应")
        
        lines.append("")
    
    # 2. Anti-gullibility effect
    lines.append("## 2. 反轻信指令效果\n")
    lines.append(f"  B组法官中{comparison['anti_gullibility_effect']['B组法官是否响应反轻信指令']}位明确输出了[执行日志审查结果]")
    
    for detail in comparison['anti_gullibility_effect']['details']:
        lines.append(f"  - {detail['tag']}: {detail['audit_preview'][:150]}...")
    
    # Check if Group B judges found devlog omissions/false-positives
    b_judges_with_findings = 0
    for r in r11_results:
        if r['group'] == 'B':
            if r.get('raw_content') and ('devlog遗漏' in r['raw_content'] or 'devlog误报' in r['raw_content'] or '遗漏' in r['raw_content']):
                b_judges_with_findings += 1
    
    lines.append(f"\n  B组法官中指出的devlog问题: {b_judges_with_findings}/4位")
    lines.append("")
    
    # 3. Log hypnosis analysis
    lines.append("## 3. Log催眠效应分析\n")
    
    # P2 baseline: B组DSV漏检了"权限错误"偏离 (4→3)
    # R11: check if similar pattern exists
    for sid in ['S1', 'S2']:
        la = comparison['log_hypnosis_analysis'][sid]
        lines.append(f"  {sid}: A组平均变化={la['A组_平均变化']}, B组平均变化={la['B组_平均变化']}")
        lines.append(f"  → {la['解释']}")
    lines.append("")
    
    # 4. Overall
    lines.append("## 4. 总体结论\n")
    
    # Calculate total deviation changes
    p2_total = sum(v for v in p2_data.values())
    r11_total = sum(r11_data.values() for r11_data in [r11_data])
    
    # Recalculate
    p2_total = sum(comparison['per_judge_comparison'][tag]['P2_baseline'] for tag in comparison['per_judge_comparison'] if comparison['per_judge_comparison'][tag]['P2_baseline'] is not None)
    r11_total = sum(comparison['per_judge_comparison'][tag]['R11_structured'] for tag in comparison['per_judge_comparison'] if comparison['per_judge_comparison'][tag]['R11_structured'] is not None)
    
    lines.append(f"  P2基线总偏离发现数: {p2_total}")
    lines.append(f"  R11结构模板总偏离发现数: {r11_total}")
    lines.append(f"  变化: {'+' if r11_total >= p2_total else ''}{r11_total - p2_total}")
    
    # Key finding
    s2_a_p2 = comparison['scenario_analysis']['S2']['A_纯代码'].get('avg_P2', 0)
    s2_a_r11 = comparison['scenario_analysis']['S2']['A_纯代码'].get('avg_R11', 0)
    s2_b_p2 = comparison['scenario_analysis']['S2']['B_代码+devlog'].get('avg_P2', 0)
    s2_b_r11 = comparison['scenario_analysis']['S2']['B_代码+devlog'].get('avg_R11', 0)
    
    lines.append(f"\n  关键对比(S2 有偏离场景):")
    lines.append(f"    A组(纯代码): P2={s2_a_p2} → R11={s2_a_r11}")
    lines.append(f"    B组(代码+devlog): P2={s2_b_p2} → R11={s2_b_r11}")
    
    if s2_b_r11 is not None and s2_b_p2 is not None:
        lines.append(f"    S2 B组变化: {'+' if s2_b_r11 >= s2_b_p2 else ''}{s2_b_r11 - s2_b_p2}")
    
    # Final judgment
    lines.append(f"\n  R11优化效果判定:")
    if s2_b_r11 is not None and s2_b_p2 is not None and s2_b_r11 > s2_b_p2:
        lines.append(f"  ✅ 结构化模板+反轻信指令使B组法官偏离发现数增加,log催眠效应减弱")
    else:
        lines.append(f"  ⚠️ 效果不显著或需要更多数据验证")
    
    return '\n'.join(lines)

# ============================================================
# Main
# ============================================================

def main():
    # Load P2 baseline for comparison
    with open("D:/competation/design/experiments/results/p2_deviation_log.json", 'r', encoding='utf-8') as f:
        p2 = json.load(f)
    
    p2_data = {}
    for je in p2['judge_evaluations']:
        p2_data[je['tag']] = je['parsed']['total_deviations']
    
    print("=" * 70)
    print("  R11 结构化模板 + 反轻信指令 验证实验")
    print("=" * 70)
    print(f"\nP2基线数据: {p2_data}")
    print(f"将运行 2场景 × 2组 × 2法官 = 8次API调用\n")
    
    # Run experiment
    r11_results = run_experiment()
    
    # Analyze and compare
    comparison = analyze_and_compare(r11_results)
    conclusion_text = build_conclusion(comparison, r11_results)
    
    # Build full output
    full_output = {
        **comparison,
        "r11_raw_results": r11_results,
        "chinese_analysis": conclusion_text
    }
    
    # Save
    output_path = "D:/competation/design/experiments/results/p2_structured_validation.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(full_output, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*70}")
    print(f"  实验完成!结果保存到: {output_path}")
    print(f"{'='*70}")
    print(f"\n{conclusion_text}")
    
    # Print summary table
    print(f"\n{'='*70}")
    print(f"  偏离发现数对比表")
    print(f"{'='*70}")
    print(f"{'Tag':<15} {'P2基线':>8} {'R11结构':>8} {'变化':>8}")
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
