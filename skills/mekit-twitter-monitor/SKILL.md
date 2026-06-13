---
name: mekit:twitter-monitor
description: Twitter/X 竞品监控（档案卡更新 + 竞品矩阵 + 策略告警）
triggers:
  - "竞品监控"
  - "更新竞品"
  - "竞品分析"
  - "竞品矩阵"
  - "看看竞品"
  - "竞品动态"
  - "追踪竞品"
  - "competitor monitor"
workflow:
  - step: 1
    action: "读取 memory/competitors/twitter/index.json，列出当前所有竞品"
    agent: mekit-twitter-strategist
  - step: 2
    action: "按 tier 优先级（S > A > B）对每个竞品执行 mekit twitter analyze user --username=..."
    agent: mekit-twitter-analyst
  - step: 2.5
    action: "【约束】若 mekit analyze 失败，跳过该竞品继续下一个，不阻断整体流程"
    agent: mekit-twitter-analyst
  - step: 3
    action: "更新竞品档案卡 memory/competitors/twitter/@{handle}.md（粉丝数、最新爆款、策略变化）"
    agent: mekit-twitter-analyst
  - step: 4
    action: "生成竞品矩阵对比表（粉丝增长排行、互动率排行、威胁度评级）"
    agent: mekit-twitter-strategist
  - step: 5
    action: "策略告警：哪个竞品威胁度上升？哪个有新的变现动作？哪个内容策略变了？"
    agent: mekit-twitter-strategist
---

# /mekit:twitter-monitor — Twitter 竞品监控

## 职责

指挥 analyst + strategist 对 Twitter 竞品账号做系统化追踪：读取竞品清单 → 逐个分析 → 更新档案卡 → 生成竞品矩阵 → 策略告警。

## 一件事

**只做"Twitter 竞品追踪"**，不发现新内容，不制作新内容，不执行发布，不涉及 YouTube。

## 竞品分级

| Tier | 含义 | 监控频率 | 说明 |
|------|------|---------|------|
| **S** | 直接对标 | 每周 | 粉丝 5000-50000，你的核心学习和差异化对象 |
| **A** | 同赛道不同方向 | 每 2 周 | 粉丝 1000-10000，可跨界借鉴 |
| **B** | 英文源大号 | 每月 | 粉丝 > 50000，仅做素材来源 |

## 输出：竞品矩阵

每次监控输出以下对比表：

```markdown
| 账号 | Tier | 粉丝 | 月增长 | 均互动率 | 主钩子 | 变现 | 威胁度 |
|------|------|------|--------|---------|--------|------|--------|
| @A   | S    | 3000 | +200   | 3.2%    | 数字型 | aff  | ⭐⭐⭐   |
| @B   | A    | 1500 | +80    | 4.5%    | 故事型 | 无   | ⭐⭐⭐⭐  |
```

**威胁度评级逻辑**：
- ⭐⭐⭐⭐⭐ = 粉丝比你少但互动率比你高（最大威胁）
- ⭐⭐⭐⭐ = 增长速度比你快
- ⭐⭐⭐ = 内容策略相似且规模相当
- ⭐⭐ = 粉丝比你多但互动率低
- ⭐ = 不构成威胁

## 策略告警

当检测到以下情况时输出告警：
- 🔴 某个竞品威胁度上升（粉丝少但互动率突然飙升）
- 🟡 某个竞品开始变现（affiliate/课程/社群）
- 🟡 某个竞品内容策略转型（话题方向/频率/形式变化）
- 🟢 某个竞品出现了内容空白（你可以抢占的方向）

## 竞品档案卡模板

每次更新 `memory/competitors/twitter/@{handle}.md`，模板见 `docs/platforms/twitter/implementation-plan.md` §3.7。

## 注意事项
- 竞品分析是"学习+差异化"，禁止建议模仿或抄袭
- S 级竞品每周更新，A 级每 2 周，B 级每月
- 档案卡首次创建后必须持续更新，至少记录粉丝数变化
- 新竞品的添加由用户手动触发（说"追踪 @xxx"），不在本 Skill 自动添加
