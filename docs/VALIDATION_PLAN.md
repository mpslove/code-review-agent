# 验证方案

## 方法：真实PR对照实验

### 数据来源

从GitHub爬取Python项目PR，筛选条件：
1. 至少有3条review comments
2. 不涉及重命名/格式化（太简单）
3. 代码量100-500行

### 选10个PR

从以下项目随机选：
- Django、Flask、FastAPI、Requests、Pytest
- 或直接用 `gh search prs` 搜 "fix: security" "fix: bug" 开源的Python PR

### Ground Truth

直接用PR上已有的**人工review comments**：
- 标注人指出的具体行号+问题
- 不自己标，不自己判断对错
- 如果review comments说"这里SQL注入"→ ground truth就是SQL注入

### 运行

每个PR跑agent 3次（消除随机性），取中位数。

### 指标

```
precision = agent发现的真实问题数 / agent报告的总问题数
recall    = agent发现的真实问题数 / 人工标注的问题总数
f1        = 2 * precision * recall / (precision + recall)
```

### 目标

| 指标 | 最低 | 目标 | 
|------|------|------|
| precision | >0.5 | >0.7 |
| recall | >0.3 | >0.5 |
| f1 | >0.4 | >0.6 |

如果能达到目标，比很多学术论文的baseline高，可以拿来说。

### 预期产出

一份验证报告：
- 10个PR的逐个结果
- precision/recall/f1
- 典型误报/漏报案例分析
- 结论：能做什么，不能做什么

---

## 动手步骤

1. 选10个PR，下载diff和review comments → 1小时
2. 跑agent 10×3=30次 → 约15分钟API时间
3. 人工对review comments做结构化标注（转录到YAML） → 2小时
4. 跑benchmark runner算指标 → 10分钟
5. 写分析报告 → 1小时
