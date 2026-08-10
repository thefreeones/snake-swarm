# 蛇群端到端实验 — Student Score Analyzer 数据管道

## 项目：学生成绩分析数据管道

### 管道结构
```
Loader(加载) → Cleaner(清洗) → Stats(统计) → Reporter(报告)
   ↓产出         ↓产出            ↓产出           ↓产出
 raw_data      cleaned_data     stats          report.md
```

### 模块1: Loader — 数据加载与解析
**功能**: 从JSON文件加载学生成绩数据
**输入**: score_data.json (含学生名、数学/英...[truncated]