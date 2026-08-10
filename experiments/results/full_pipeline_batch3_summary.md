# Batch3 全链路异构法官实验结果

## 实验配置
- 蛇头层: claude-sonnet-5 (t=0.3)
- 法官1: deepseek-v4-pro (t=0.3)
- 法官2: deepseek-v4-pro (t=0.7)
- 法官3: gemini-3.6-flash (t=0.3)
- 深挖: deepseek-v4-pro (t=0.3) — 全部一致判决，无需触发

## 各用例结果
### S3 [L4: subjective / code quality] — ✗ 误判
- Ground Truth: PASS, 判决: FAIL, 投票: PASS=0 FAIL=3
- Token: 10187
### S4 [L3: snake head conflict] — ✗ 误判
- Ground Truth: PASS, 判决: FAIL, 投票: PASS=0 FAIL=3
- Token: 14426
### S5 [L2: dual consensus error] — ✓ 正确
- Ground Truth: FAIL, 判决: FAIL, 投票: PASS=0 FAIL=3
- Token: 9171
### S6 [L3: regression / shallow copy] — ✓ 正确
- Ground Truth: FAIL, 判决: FAIL, 投票: PASS=0 FAIL=3
- Token: 16835
### S7 [L2: interface / strict repair] — ✓ 正确
- Ground Truth: FAIL, 判决: FAIL, 投票: PASS=0 FAIL=3
- Token: 6674

## 整体统计
- 准确率: 60.0% (3/5)
- 总Token: 57293
- 深挖触发: 0次（全部一致判决）

## 分析
- S3(代码质量): 功能正确但代码质量差，三法官均判FAIL — 误判，法官过于严格
- S4(日期解析): 功能正确但脆弱(split方式)，三法官均判FAIL — 误判，法官对实现细节过度敏感
- S5(二分查找): 存在死循环bug，三法官均正确判FAIL — 正确检出
- S6(浅拷贝): 浅拷贝导致嵌套修改，三法官均正确判FAIL — 正确检出
- S7(格式函数): 缺少类型检查/空值处理，三法官均正确判FAIL — 正确检出

结论: 异构三法官在功能bug(S5-S7)上全正确，但在主观质量/脆弱性问题(S3-S4)上过于严格。3/5=60%准确率。