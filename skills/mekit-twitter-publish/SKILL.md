---
name: mekit:twitter-publish
description: 发布内容到 Twitter/X
triggers:
  - "发推"
  - "发布Twitter"
  - "发Twitter Thread"
  - "Twitter定时发布"
  - "发布推文"
  - "定时发送"
  - "推文发布"
  - "推到Twitter"
  - "发送推文"
  - "发一条推"
  - "publish tweet"
workflow:
  - step: 1
    action: "确认发布内容与类型"
    agent: mekit-twitter-publisher
  - step: 2
    action: "预检查 → hooks/twitter/pre-publish.py（合规/格式/敏感词/Twitter限制）"
    agent: mekit-twitter-publisher
  - step: 3
    action: "执行发布 → mekit twitter publish <target> --draft=..."
    agent: mekit-twitter-publisher
  - step: 3.5
    action: "【约束】若 mekit publish 失败，立即停止并报告错误（遵守 settings.json 全局 CLI 约束）"
    agent: mekit-twitter-publisher
  - step: 4
    action: "归档结果 → hooks/twitter/post-publish.py（链接/ID/时间戳）"
    agent: mekit-twitter-publisher
  - step: 5
    action: "输出发布确认与后续跟踪建议"
    agent: mekit-twitter-publisher
---

# /mekit:twitter-publish — Twitter 发布管理

## 职责
指挥 mekit-twitter-publisher 将内容发布到 Twitter/X，并触发前后钩子。

## 一件事
**只做"Twitter 发布执行"**，不发现趋势，不分析竞品，不制作新内容，不涉及 YouTube。

## 支持的主谓宾命令

| 主语 | 谓语 | 宾语 | CLI 命令 |
|------|------|------|---------|
| twitter | publish | tweet | `mekit twitter publish tweet --draft=./draft.json` |
| twitter | publish | thread | `mekit twitter publish thread --draft=./draft.json` |

## draft.json 格式约定

```json
{
  "platform": "twitter",
  "type": "tweet",
  "text": "...",
  "media_paths": ["./image1.jpg"],
  "scheduled_at": "2025-06-10T09:00:00Z"
}
```

## 工作流细节

### Step 2: 预检查
`hooks/pre-publish.py` 检查项：
- 敏感词 / 合规风险
- 单推 280 字限制
- Thread 原子性检查
- 发布频率合理性

### Step 4: 归档
`hooks/post-publish.py` 归档项：
- 发布链接、推文 ID、发布时间
- 写入 `memory/history.jsonl`
- 如果 rating 高，自动提取模板到 `memory/templates/`

## 注意事项
- 预检查失败时阻断发布，返回错误明细
- Thread 发布需保证原子性：全发或全不发
- 定时发布依赖 Twitter API 能力，不支持时给出替代方案
