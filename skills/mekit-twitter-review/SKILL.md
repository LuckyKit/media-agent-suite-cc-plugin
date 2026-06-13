---
name: mekit:twitter-review
description: Twitter/X 周/月复盘（BRQ-5 归因 + KPI 仪表盘 + 模板评分更新）
triggers:
  - "周复盘"
  - "本周总结"
  - "月度复盘"
  - "月复盘"
  - "运营复盘"
  - "复盘一下"
  - "数据复盘"
  - "weekly review"
  - "monthly review"
workflow:
  - step: 1
    action: "确认复盘时间范围（默认 7d，月度用 30d）"
    agent: mekit-twitter-strategist
  - step: 2
    action: "执行 evolve analyze → mekit twitter evolve analyze --since=7d|30d"
    agent: mekit-twitter-analyst
  - step: 2.5
    action: "【约束】若 mekit evolve 失败，立即停止并报告错误"
    agent: mekit-twitter-analyst
  - step: 3
    action: "BRQ-5 归因：Top 3 和 Bottom 3 推文逐一归因"
    agent: mekit-twitter-analyst
  - step: 4
    action: "KPI 仪表盘：对比 Phase 退出标准 + 预警阈值检查"
    agent: mekit-twitter-analyst
  - step: 5
    action: "模板评分更新：本周使用的模板 ±1 分；连续 3 次表现差 → retired；新成功模式 → 建议提取"
    agent: mekit-twitter-strategist
  - step: 6
    action: "竞品动态摘要 + 下周行动建议"
    agent: mekit-twitter-strategist
  - step: 7
    action: >
      输出复盘报告到 .media-agent/shared/reports/twitter/weekly-{date}.md。
      
      【强制】更新 memory/phase.json：
      a. 追加本周 KPI snapshot 到 kpi_snapshots 数组
      b. 逐项更新 exit_criteria 中的 current 值（粉丝数、模板库条目数等）
      c. 检查退出标准：如果某条标准的 current ≥ target → met=true
      d. 如果全部标准 met=true → 提示用户进入下一 Phase
      e. 用 Edit 工具写入 memory/phase.json
    agent: mekit-twitter-strategist
---

# /mekit:twitter-review — Twitter 周/月复盘

## 职责

指挥 analyst + strategist 对指定时间范围内的 Twitter 历史数据做结构化复盘，输出 BRQ-5 归因、KPI 仪表盘、模板评分更新、竞品动态和下周行动建议。

## 一件事

**只做"Twitter 复盘分析"**，不发现新内容，不制作新内容，不执行发布，不涉及 YouTube。

## 输出标准格式

复盘报告写入 `.media-agent/shared/reports/twitter/weekly-{YYYY-MM-DD}.md`（月度用 `monthly-{YYYY-MM}.md`），报告模板见 `docs/platforms/twitter/implementation-plan.md` §3.10–3.11。

### 报告必须包含的 6 大板块

1. **KPI 仪表盘**
   - 发推数、均互动率、粉丝净增、粉丝总数、转发率、归因准确率
   - 与 Phase 退出标准对比，每项标注达标/未达标
   - 预警阈值检查：互动率连续 3 天 < 1.5%？粉丝增长连续 2 周不达标？

2. **Top 3 推文（BRQ-5 归因）**
   - 每条：互动率 + Q1-Q5 简版归因 + 可提取模板因子 + 下周复用建议

3. **Bottom 3 推文（失败归因）**
   - 失败原因归类：钩子弱 / 选题偏 / 时间错 / 工具冷门
   - 每条 1 句话教训

4. **模板评分更新**
   - 本周使用的模板，根据实际互动率调整 score（±1）
   - 连续 3 次互动率 < 2% → 标记 status=retired
   - 新发现的成功模式 → 建议提取为新模板

5. **竞品动态**
   - 从 memory/competitors/twitter/ 读取最近更新
   - 标记竞品策略变化 + 是否需要应对

6. **下周行动**
   - 1 个要试的新东西（新钩子类型/新内容形式）
   - 1 个要补的短板
   - 1 个要防的退步

### phase.json 同步更新

复盘完成后必须更新 `memory/phase.json`：
- 追加本周 KPI snapshot 到 `kpi_snapshots` 数组
- 更新 `exit_criteria` 中各项的 `current` 值
- 如果全部退出标准达标 → 提示用户进入下一 Phase

## 注意事项
- 周复盘每周末执行，月复盘每月末执行
- 所有数据来源于 mekit CLI 返回结果，不猜测不构造
- 模板评分调整需给出理由（基于哪条推文的表现）
- 复盘报告写入后不删除，长期积累形成运营日志
