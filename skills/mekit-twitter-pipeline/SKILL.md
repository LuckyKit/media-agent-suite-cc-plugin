---
name: mekit:twitter-pipeline
description: Twitter/X 每日内容流水线（发现→筛选→创作→发布 一键串联）
triggers:
  - "今日推文"
  - "每日流水线"
  - "跑一遍"
  - "daily pipeline"
  - "一键发推"
  - "自动发推"
  - "日常推文"
workflow:
  - step: 1
    action: "确认今日选题方向（关键词 / Hashtag / 素材偏好）"
    agent: mekit-twitter-strategist
  - step: 2
    action: "执行 discover → mekit twitter discover tweets（遵守 settings.json 全局 CLI 约束：失败即终止）"
    agent: mekit-twitter-strategist
  - step: 3
    action: "按 S/A/B 标准筛选最佳候选 1-3 条，选定今日策展目标"
    agent: mekit-twitter-strategist
  - step: 4
    action: "对选定的候选执行 create → mekit twitter create tweet（引用 Top 3 高分模板）"
    agent: mekit-twitter-writer
  - step: 4.5
    action: "【约束】若 mekit create 失败，立即停止并报告错误"
    agent: mekit-twitter-writer
  - step: 5
    action: "执行 publish → mekit twitter publish tweet --draft=..."
    agent: mekit-twitter-publisher
  - step: 5.5
    action: "【约束】若 mekit publish 失败，立即停止并报告错误"
    agent: mekit-twitter-publisher
  - step: 6
    action: "输出今日流水线摘要：已发布推文链接 + 互动预测 + 明日选题建议"
    agent: mekit-twitter-strategist
---

# /mekit:twitter-pipeline — Twitter 每日内容流水线

## 职责

一键串联 discover → 筛选 → create → publish，把"今日推文"四个字变成一条已发布的推文。

## 一件事

**只做"Twitter 每日流水线编排"**，每个环节由对应的 Agent 执行，不做跨平台操作。

## 工作流

### Step 1: 确认选题方向
Strategist 读取 `memory/strategy.json` + `memory/phase.json`，确认：
- 今日关键词方向（默认：AI tool / 免费工具）
- 当前 Phase 阶段对内容类型的要求
- 是否避开最近竞品已发的话题

### Step 2: 执行发现
调用 `mekit twitter discover tweets`，参数基于 Step 1 的选题方向。

### Step 3: S/A/B 筛选
Strategist 按 discover Skill 的筛选标准（赞粉比、时效、可复现、去重）对结果进行 S/A/B 分级，选定最佳的 1 个候选为今日策展目标。

### Step 4: 创作推文
Writer 从 `memory/templates/twitter/` 按 score 降序取 Top 5 模板，选择匹配的 2-3 个模板进行创作。生成的 draft.json 必须记录 `template_refs`。

### Step 5: 发布
Publisher 执行 pre-publish 检查后发布。

### Step 6: 输出摘要
```
📊 今日流水线摘要
━━━━━━━━━━━━━━━━━━━━
✅ 已发布：[推文链接]
📝 钩子类型：[X]
📋 使用模板：[template_1, template_2]
📈 预计互动率：[X%]
💡 明日选题方向：[建议]
```

## 注意事项
- 每个环节的 CLI 命令是唯一入口，失败即终止
- 流水线默认每天运行 1 次，不要重复执行
- 如果今日已发过推文，先提示用户确认是否再发
- 所有中间产物（draft、history）自动归档到 .media-agent/shared/
