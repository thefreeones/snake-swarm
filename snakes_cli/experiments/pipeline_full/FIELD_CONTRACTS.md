# 数据字段契约 — Student Score Analyzer

## 测试数据说明
score_data.json包含10条学生记录，其中嵌入了4个需要清洗的脏数据：
- 孙七: math=-5 (负分→无效)
- 周八: eng=null (缺失科目→无效)
- 郑十: math=999 (超出0-100范围→无效)
- 赵六: math=45,eng=60,cs=55 (全部偏低但有效，清洗后保留)

## M1: Loader — 字段契约

```
输入: score_data.json (文件路径)
产出字段:
  students: List[{
    name: str,
    scores: {math: float|null, eng: float|null, cs: float|null}
  }]
  total_loaded: int
```

## M2: Cleaner — 字段契约

```
输入字段(依赖M1):
  M1.students: List[{name, scores}]

清洗规则:
  1. 任一模考分数为null → 剔除
  2. 任一模考分数<0 或 >100 → 剔除
  3. 保留通过的记录

产出字段:
  students: List[{name, scores}]  # 仅有效记录
  total_loaded: int               # 传入总数
  removed: int                    # 剔除数
  removed_records: List[str]      # 被剔除的学生名+原因
```

## M3: Stats — 字段契约

```
输入字段(依赖M2):
  M2.students: List[{name, scores}]

产出字段:
  avg_math: float
  avg_eng: float
  avg_cs: float
  top_student: str          # 总分最高的学生名
  top_total: float          # 最高总分
  pass_rate: float          # 三科均≥60的学生比例(%)
  total_students: int       # 有效学生数
```

## M4: Reporter — 字段契约

```
输入字段(依赖M1+M2+M3):
  M1.total_loaded: int
  M2.removed: int
  M3.avg_math, avg_eng, avg_cs, top_student, top_total, pass_rate, total_students

产出:
  report.md — 格式化的Markdown报告，包含：
    # 学生成绩分析报告
    ## 数据概览 (加载数/有效数/剔除数和原因)
    ## 成绩统计 (三科均分)
    ## 最佳表现 (最高分学生)
    ## 及格率
```

## 数据契约验证（集成时执行）

蛇α正向检查:
  - M1是否实际产出students字段？类型是否正确？
  - M2是否实际产出students/removed字段？
  - M3是否实际产出avg_math等6个字段？
  - M4输出的report.md是否存在？

蛇β反向检查:
  - M2依赖的M1.students字段 → M1是否声明产出？
  - M3依赖的M2.students字段 → M2是否声明产出？
  - M4依赖的M3字段 → M3是否声明产出？
  - M4依赖的M1.total_loaded → M1是否声明产出？
