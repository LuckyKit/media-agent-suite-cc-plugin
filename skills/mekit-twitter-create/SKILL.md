---
name: mekit:twitter-create
description: 制作 Twitter/X 内容（Thread、推文、钩子文案）
triggers:
  - "写个Twitter Thread"
  - "发推文案"
  - "Twitter文案"
  - "生成Twitter钩子"
  - "写条推文"
  - "写推文"
  - "生成推文"
  - "帮我写Twitter"
  - "创作推文"
  - "构思推文"
  - "推文创意"
  - "草稿"
  - "写个thread"
  - "create tweet"
  - "write tweet"
workflow:
  - step: 1
    action: "明确主题、风格、参考案例"
    agent: mekit-twitter-writer
  - step: 2
    action: >
      从 memory/templates/twitter/{hooks,structures,ctas}/ 中，
      按 score 降序取 Top 5 模板。根据当前 topic 和 style 选择最匹配的 2-3 个。
      生成的 draft.json 中必须记录 template_refs（使用的模板 ID 列表）。
    agent: mekit-twitter-writer
  - step: 3
    action: "生成内容 → mekit twitter create <target> --topic=..."
    agent: mekit-twitter-writer
  - step: 3.5
    action: "【约束】若 mekit create 失败，立即停止并报告错误（遵守 settings.json 全局 CLI 约束）"
    agent: mekit-twitter-writer
  - step: 4
    action: "输出多版本备选 + Twitter 适配建议"
    agent: mekit-twitter-writer
---

# /mekit:twitter-create — Twitter 内容制作

## 职责
指挥 mekit-twitter-writer 调用 CLI 生成适合 Twitter/X 平台的内容。

## 一件事
**只做"Twitter 内容制作"**，不发现趋势，不分析竞品，不执行发布，不涉及 YouTube。

## 支持的创建目标

| 谓语 | 宾语 | CLI 命令 | 说明 |
|------|------|---------|------|
| twitter | create | thread | `mekit twitter create thread --topic="..." --style=...` | Thread 大纲 |
| twitter | create | tweet | `mekit twitter create tweet --topic="..."` | 单条推文 |
| twitter | create | hook | `mekit twitter create hook --topic="..."` | 开头钩子文案 |

## 输入参数

mekit-twitter-writer 必须收集：
- **topic**: 核心主题
- **style**: 风格（hot-take / story-driven / listicle / educational / meme）
- **length**: 长度（单推 / 短 Thread 3-5 推 / 长 Thread 10+ 推）
- **reference**: 参考案例（可选，从 mekit:twitter-analyze 结果带入）

## 输出标准

1. **主版本**
   - 完整 Thread 或推文
   - 每推标注角色（钩子/展开/证据/总结/CTA）

2. **备选版本**
   - 至少 1 个不同风格的备选

3. **Twitter 适配建议**
   - 首句变体（不同钩子角度）
   - Hashtag 建议（0-2 个，自然嵌入）
   - 最佳发布时间建议

4. **元数据**
   - 预估字数、推数
   - 目标受众画像

## 注意事项
- 优先引用 memory/templates/ 中高评分历史模板
- 生成内容必须为原创，禁止建议搬运
- 单推严格限制 280 字，Thread 每推独立成意
