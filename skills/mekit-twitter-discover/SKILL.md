---
name: mekit:twitter-discover
description: 发现 Twitter/X 上的爆款内容，支持 Twitter 搜索 + Product Hunt + Hacker News 多源发现
triggers:
  - "找Twitter爆款"
  - "Twitter上有什么火的"
  - "看看推特点什么火"
  - "搜一下Twitter"
  - "Twitter discover"
  - "帮我找推"
  - "搜推"
  - "推上热门"
  - "Twitter趋势"
  - "X上有什么"
  - "找灵感"
  - "发现推文"
  - "热门推文"
  - "刷推"
  - "trending tweets"
  - "找今天的AI工具"
  - "Product Hunt有什么"
  - "HN上有什么"
  - "今天有什么新工具"
  - "帮我找新AI工具"
web_sources:
  product_hunt:
    url: "https://www.producthunt.com/"
    description: "每日新产品榜单，AI 工具最集中"
    when_to_use: "用户说'找今天的工具'/'Product Hunt有什么'/'找新AI工具'"
  hacker_news:
    url: "https://news.ycombinator.com/"
    description: "Show HN 类帖子，开发者自发分享的工具"
    when_to_use: "用户说'HN上有什么'/'找开源工具'/'开发者工具'"
workflow:
  - step: 0
    action: >
      判断发现模式：
      - 用户提到"Product Hunt"/"今天新工具"/"PH" → 执行 Step 0A（网页抓取模式）
      - 用户提到"HN"/"Hacker News"/"Show HN" → 执行 Step 0B（HN 模式）
      - 其他所有情况 → 跳到 Step 1（Twitter 搜索模式）
    agent: mekit-twitter-strategist

  - step: 0A
    action: >
      【Product Hunt 模式】
      使用 WebFetch 抓取 https://www.producthunt.com/
      提取今日榜单前 10 个产品：名称、一句话描述、标签、得票数
      筛选出标签含 AI / Productivity / Developer Tools 的产品
      输出格式：
        🔥 今日 Product Hunt AI 工具榜单
        1. [产品名] — [描述] ([票数]票)
        2. ...
      然后问用户："选哪个工具作为今天的推文主角？"
      用户选定后 → 跳到 Step 1，用工具名作为 keyword 搜 Twitter
    agent: mekit-twitter-strategist

  - step: 0B
    action: >
      【Hacker News 模式】
      使用 WebFetch 抓取 https://news.ycombinator.com/
      提取标题含 "Show HN" 且话题相关的帖子（AI / tool / open source / free）
      输出前 5 条：标题、链接、评论数
      输出格式：
        🛠 今日 HN Show HN 精选
        1. [标题] — [评论数]条评论
           链接：[url]
      然后问用户："选哪个作为今天的内容方向？"
      用户选定后 → 跳到 Step 1，用工具名作为 keyword 搜 Twitter
    agent: mekit-twitter-strategist

  - step: 1
    action: "确认搜索意图（关键词 / Hashtag / 筛选条件）"
    agent: mekit-twitter-strategist
  - step: 2
    action: "pre-discover hook 准入检查（数据源 + 频率限制）"
    agent: mekit-twitter-strategist
  - step: 3
    action: "执行 CLI → result（遵守 settings.json 全局 CLI 约束：失败即终止，禁止 fallback）"
    agent: mekit-twitter-strategist
  - step: 4
    action: "post-discover hook 经验沉淀（历史 + 关键词统计 + 作者排行）"
    agent: mekit-twitter-strategist
  - step: 5
    action: >
      按以下标准逐条筛选并输出 S/A/B 优先级：
      (a) 赞/粉比 > 5%？（赞数 / 作者粉丝数）
      (b) 发布时间 < 24h？（若来自 PH/HN，放宽到 72h）
      (c) 工具可复现/可验证？（不是纯概念/观点类内容）
      (d) 与 .media-agent/shared/seen/twitter.json 中的已有内容不重复？
      
      输出格式（每条候选）：
        【S级-立刻策展】满足全部 4 条
        【A级-加入候选池】满足 3 条（标注缺失项）
        【B级-观察】满足 1-2 条（标注缺失项）
        【不通过】满足 0 条（不输出给用户）
      
      最终输出按优先级排序的候选列表，附筛选结果和策展建议。
      如果来源是 PH/HN，额外输出：工具官网链接 + 建议实测角度
    agent: mekit-twitter-strategist
---

# /mekit:twitter-discover — 发现 Twitter 爆款

## 职责
调用 `mekit twitter discover tweets` 发现 Twitter/X 热门推文，筛选出有二次创作价值的候选。

## 一件事
**只做"Twitter 发现"**，不分析传播原因，不生成推文，不执行发布，不涉及 YouTube。

## CLI 命令

```bash
mekit twitter discover tweets [options]
```

| 关键参数 | 作用 |
|---------|------|
| `--keyword` | 搜索词，如 `"deepseek codex"` |
| `--hashtag` | 话题标签，如 `"claude"` |
| `--limit` | 返回条数（默认 3） |
| `--viral` | 按互动率排序（找小号高质量内容） |
| `--personal` | 只看素人（粉丝 < 5 万） |
| `--diverse` | 每个作者最多 1 条 |
| `--fresh` | 跳过缓存 + 过滤已看 |
| `--lang` | 语言过滤（zh/en/ja 等），不指定则不限语言 |

## 关键词搜索策略（核心）

> **核心原则**：不要用泛词搜。`"AI"`、`"tool"`、`"免费"` 返回的全是大号和营销号。用 **信号词 + 场景词组合** 才能命中可策展的内容。

### 你的内容目标 → 搜索策略映射

| 你想找什么 | 用什么关键词 | 配什么参数 | 为什么这样搜 |
|-----------|-------------|-----------|-------------|
| 🆕 **刚发布的新工具** | `"just launched"` `"I built a"` `"I made a"` `"shipped"` | `--personal --diverse` | indie hacker 发布新产品时的固定用语 |
| 🆓 **免费工具/替代品** | `"free" + "alternative to"` `"free" + "open source"` | `--personal --diverse` | 找"XX 的免费替代品"类推荐 |
| 💰 **省钱/省时间** | `"save time"` `"save money"` `"boost productivity"` | `--personal` | 效率工具推荐常用这些短语 |
| 🔥 **爆款拆解素材** | `"I tried"` `"how I use"` `"my workflow"` | `--viral --diverse` | 个人使用体验类内容，互动率高 |
| 📊 **趋势/观点** | 具体的工具名或话题 `"Cursor AI"` `"Claude code"` `"no code AI"` | `--viral` | 围绕具体工具的讨论，有争议性 |
| 🇨🇳 **中文竞品内容** | `"AI 工具"` `"效率工具"` `"替代品"` `"神级"` `"好用"` | `--lang=zh --personal --diverse` | 中文圈高频推荐用词 |
| 🏗️ **开源项目** | `"open source"` `"github.com"` `"OSS"` | `--personal --diverse` | 找可以实测的免费开源工具 |
| 🧵 **Thread 拆解** | `"thread"` `"🧵"` `"(1/n)"` `"(1/5)"` | `--viral` | Thread 作者常会标注 |

### 关键词组合示例

```bash
# ✅ 好 — 信号词组合，命中 indie hacker 发布
mekit twitter discover tweets --keyword="I built a free" --personal --diverse --limit=10

# ✅ 好 — 场景词组合，命中替代品推荐
mekit twitter discover tweets --keyword="alternative to" --personal --diverse --limit=10

# ✅ 好 — 中文工具推荐，素人优先
mekit twitter discover tweets --keyword="AI 工具 推荐" --lang=zh --personal --diverse --limit=10

# ❌ 差 — 泛词，返回全是大号（386K 粉的 Cursor、264K 粉的 Fetch.ai）
mekit twitter discover tweets --keyword="AI tool" --limit=10
```

### 一句话记忆

```
泛词 = 大号 + 低互动 → 没法用
信号词 + --personal = 小号 + 新工具 + 高互动 → 策展素材
```

## 工作流

### Step 1: 意图 → 参数（动态拼接）

Strategist 收到用户的自然语言后，按 `agents/twitter/strategist.md` 中的"意图识别规则"执行：

1. **识别意图**：用户话中包含哪些信号？（免费/替代/省钱/爆款/中文/...）
2. **选信号词组**：映射到对应的信号词组（A/B/C/D/E/F/G）
3. **查历史优选**：查询 `~/.media-agent/memory/insights/twitter/keyword_stats.json`，从组内选历史均互动率最高的关键词
4. **拼参数**：根据用户话中的时效/数量/人群限定词，拼装 `--personal` / `--viral` / `--fresh` / `--lang` / `--limit` 等

> **⚠️ 信号词优先**：即使对话中未明确搜索词，也必须自动补全为信号词。**禁止**使用泛词（"AI"、"tool"、"免费"）作为 keyword 参数。
>
> **⚠️ 参数优先原则**：用户明确给出的数字/语言/时效限定词必须原样传入 CLI，不得修改。用户未明确的参数使用默认值（--personal --diverse --fresh --limit=10）。

### Step 2: 准入检查（pre-discover hook）
执行 pre-discover hook 脚本：
- 检查 twitterapi.io API Key 可用性
- 频率限制：每小时最多 10 次，超限阻断

### Step 3: 执行发现（唯一入口）
调用 `mekit twitter discover tweets`：
- **参数约束**：Step 1 确定的参数（尤其是 `--limit`、`--keyword`、`--hashtag`）必须精确传入，禁止在 Step 3 中再次修改。
- **入口约束**：CLI 是唯一入口。若 CLI 返回错误（exit ≠ 0），**立即停止并向用户报告失败原因**，禁止猜测、绕过或构造假数据。
- **数据源唯一性**：mekit CLI 返回的数据（含 mock）即为**最终且唯一**的数据源，禁止调用 WebSearch、WebFetch 或任何其他工具进行补充搜索。即使数据是 mock，也必须基于这些数据完成分析输出，不得绕过。
- 数据源：twitterapi.io → mock（无 Key 时返回 mock 数据）
- 默认存储模式 `both`：SQLite 持久化 + 5 分钟缓存
- 每条 tweet 的原始字段完整存入 SQLite，供后续分析

### Step 4: 经验沉淀（post-discover hook）
执行 post-discover hook 脚本：
- `memory/history.jsonl` — 执行记录
- `memory/insights/twitter/keyword_stats.json` — 关键词效果排行
- `memory/insights/twitter/author_stats.json` — 作者热度追踪

### Step 5: 输出
Strategist 筛选并输出：
1. **推文列表**：内容 + 互动数据 + 互动率 + 链接
2. **初步判断**：哪些有二次创作价值
3. **选题方向**：基于这批推文，可以做什么内容

## 注意事项
- **无参数默认**：当用户只说"找爆款"而未指定关键词时，默认使用信号词组合 `"I built" OR "just launched" OR "how I"`，搭配 `--personal --diverse`。**禁止**默认使用泛词（如 `"AI"`、`"tool"`）。
- 用户参数即最终参数：用户明确给出的数字/关键词/筛选条件，必须逐字传入 CLI，不得放大、缩小或替换
- 发现结果通过 post-discover hook 自动沉淀，无需手动记录
- 不主动建议用户跟进敏感/争议话题
- **数据源**：twitterapi.io（`TWITTERAPI_IO_KEY`）。**严格按 CLI 返回的 `meta.source` 字段判断**：`twitterapi_io` = 真实数据，`mock` = 模拟数据。**只有 source 明确为 mock 时，才按 CLI notice 原文提示用户配置 Key。source 为 twitterapi_io 时，禁止添加任何"未配置 Key"、"数据为 mock"的提示。**
