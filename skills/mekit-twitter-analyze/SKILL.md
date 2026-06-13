---
name: mekit:twitter-analyze
description: 分析 Twitter/X 爆款内容的规律与可复用模式
triggers:
  - "分析这条推文"
  - "为什么这条推火了"
  - "拆解Twitter爆款"
  - "Twitter有什么规律"
  - "分析Twitter竞品"
  - "分析推文"
  - "拆解这条"
  - "为什么火了"
  - "研究推文"
  - "推文分析"
  - "分析Twitter"
  - "分析竞品"
  - "深度分析"
  - "这条为什么火"
  - "analyze tweet"
workflow:
  - step: 1
    action: "确认分析对象 → mekit twitter analyze <target> --url/id=..."
    agent: mekit-twitter-analyst
  - step: 1.5
    action: "【约束】若 mekit analyze 失败，立即停止并报告错误（遵守 settings.json 全局 CLI 约束）"
    agent: mekit-twitter-analyst
  - step: 2
    action: "获取深度元数据（首句结构、互动曲线、转发链、时间分布）"
    agent: mekit-twitter-analyst
  - step: 3
    action: "提炼规律：文字钩子、Thread 结构、互动设计、差异化"
    agent: mekit-twitter-analyst
  - step: 4
    action: "输出可复用模式清单"
    agent: mekit-twitter-analyst
---

# /mekit:twitter-analyze — 分析 Twitter 爆款

## 职责
指挥 mekit-twitter-analyst 调用 CLI 对指定 Twitter 内容做深度分析，提炼可复用的爆款规律。

## 一件事
**只做"Twitter 分析提炼"**，不发现新内容，不制作内容，不执行发布，不涉及 YouTube。

## 支持的主谓宾命令

| 主语 | 谓语 | 宾语 | CLI 命令 |
|------|------|------|---------|
| twitter | analyze | tweet | `mekit twitter analyze tweet --url="https://..."` |
| twitter | analyze | thread | `mekit twitter analyze thread --thread-id=xxx` |
| twitter | analyze | user | `mekit twitter analyze user --username=xxx` |
| twitter | analyze | hashtag | `mekit twitter analyze hashtag --tag=#AI` |

## 输出标准格式

mekit-twitter-analyst 必须输出以下结构化分析：

1. **基础画像**
   - 发布时间、内容形式（单推/Thread/回复）
   - 核心数据（展示量、互动率、转发率、收藏率、粉丝数、字数）

2. **BRQ-5 归因框架**（所有分析必须使用此框架）
   - **Q1 钩子类型**：从 7 类中选择（数字冲击/反常识/身份认同/好奇心缺口/恐惧驱动/故事开头/问题驱动），附原文首句 + 为什么有效
   - **Q2 情绪触发点**：从 5 类中选择（FOMO/愤怒/惊喜/认同/收藏欲），附证据（转发词频、收藏率异常等）
   - **Q3 信息差还是观点差**：判断是"用户不知道"还是"用户没从这个角度想过"，标注信息新鲜度（高/中/低）
   - **Q4 转发动机**：从 5 类中选择（炫耀/利他/表达/社交货币/收藏后转），附证据
   - **Q5 为什么是这个人发才火**：分析粉丝基数、人设加成、首发优势、时机因素

3. **可提取的模板因子**
   - 至少 1 条钩子模板 pattern
   - 至少 1 条结构模板 pattern
   - 至少 1 条 CTA 模板 pattern
   - 每条注明复用风险

4. **分析报告保存**
   - 写入 .media-agent/shared/reports/twitter/analysis-{tweet_id}.md
   - 报告模板见 docs/platforms/twitter/implementation-plan.md §3.9

## 注意事项
- 分析结果写入 memory/history.jsonl，供 mekit:twitter-evolve 优化
- 禁止输出"搬运这个内容"的建议，只提炼"模式"
