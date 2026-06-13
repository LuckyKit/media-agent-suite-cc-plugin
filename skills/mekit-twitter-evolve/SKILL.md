---
name: mekit:twitter-evolve
description: 分析 Twitter/X 历史数据，优化策略与内容质量
triggers:
  - "优化Twitter策略"
  - "看看Twitter历史数据"
  - "Twitter复盘"
  - "Twitter进化一下"
  - "复盘推文"
  - "运营分析"
  - "Twitter数据"
  - "内容优化"
  - "策略优化"
  - "分析历史"
  - "内容表现"
  - "数据回顾"
workflow:
  - step: 1
    action: "读取 Twitter 历史 → mekit twitter evolve analyze --since=7d|30d|all"
    agent: mekit-twitter-analyst
  - step: 1.5
    action: "【约束】若 mekit evolve 失败，立即停止并报告错误（遵守 settings.json 全局 CLI 约束）"
    agent: mekit-twitter-analyst
  - step: 2
    action: >
      生成洞察报告（写入 .media-agent/shared/reports/twitter/）：
      1. KPI 仪表盘 — 发推数、均互动率、粉丝净增、转发率；
         与 memory/phase.json 退出标准对比，标注达标/未达标
      2. 预警阈值检查 — 互动率连续 3 天 < 1.5%？粉丝增长连续 2 周不达标？
      3. Top 3 / Bottom 3 — BRQ-5 简版归因
      4. 【自进化】模板评分更新：
         a. 读取 .media-agent/shared/tracking/twitter/template_usage.jsonl
         b. 关联周复盘时用户提供的互动率数据
         c. 互动率 > 3% → 对应模板 score +1
         d. 互动率 < 1.5% → 对应模板 score -1
         e. 连续 3 次互动率 < 2% → 模板 status=retired
         f. 用 Edit 工具更新 memory/templates/twitter/**/*.json
      5. 【自进化】关键词优选：
         a. 读取 ~/.media-agent/memory/insights/twitter/keyword_stats.json
         b. 标记本周表现最好的关键词和表现最差的
         c. 建议下周优先使用哪个关键词
      6. 新成功模式 → 建议提取为新模板
    agent: mekit-twitter-analyst
  - step: 3
    action: "生成优化建议（Skill 改进 / Agent Prompt 优化 / 模板更新）"
    agent: mekit-twitter-strategist
  - step: 4
    action: "人工确认后应用 → mekit twitter evolve apply --insight-id=xxx"
    agent: mekit-twitter-strategist
---

# /mekit:twitter-evolve — Twitter 自进化

## 职责
指挥 mekit-twitter-analyst + mekit-twitter-strategist 分析 Twitter 历史数据，生成并应用改进建议。

## 一件事
**只做"Twitter 进化建议"**，不执行具体业务操作（发现/分析/创作/发布），不涉及 YouTube。

## 支持的命令

| 谓语 | 宾语 | CLI 命令 | 说明 |
|------|------|---------|------|
| twitter | evolve | analyze | `mekit twitter evolve analyze --since=7d` | 分析 Twitter 历史数据 |
| twitter | evolve | suggest | `mekit twitter evolve suggest` | 生成改进建议 |
| twitter | evolve | apply | `mekit twitter evolve apply --insight-id=xxx` | 应用指定建议 |

## 分析维度

mekit-twitter-analyst 从 Twitter 历史数据中提取：

1. **高频成功模式**
   - 哪些 topic / style / Thread 长度组合评分最高
   - 发布时间 vs 表现的关系
   - 首句钩子与互动率的关联

2. **失败教训**
   - 低评分内容的共性（选题过宽？钩子太弱？Thread 断裂？）
   - 被预检查拦截的原因统计

3. **趋势变化**
   - Twitter 算法偏好变化（通过发现数据推断）
   - 竞品内容升级方向

## 输出物

mekit-twitter-strategist 输出到 `memory/insights/twitter/`：
- `YYYY-MM-DD-twitter-insight-{id}.md` — 结构化洞察报告
- 包含：发现 → 建议 → 预期效果 → 应用风险

## 注意事项
- `apply` 必须人工确认，禁止 Agent 自动修改 Skill/Agent 文件
- 进化周期建议：每周一次轻量分析，每月一次深度复盘
- 历史数据只追加不删除，长期趋势依赖完整数据集
