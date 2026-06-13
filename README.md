# MediaAgentSuite — Claude Code 插件

Twitter/X 内容发现、分析、创作、发布。

## 前置条件

- 已安装 [uv](https://docs.astral.sh/uv/)（`uv --version` 确认）
- 已安装并登录 Claude Code

## 安装（首次）

```bash
# 第 1 步：安装插件（加载 skills/agents/hooks）
claude plugin marketplace add https://github.com/LuckyKit/media-agent-suite-cc-plugin
claude plugin install media-agent-suite

# 第 2 步：安装 mekit CLI（全局，一次即可）
uv tool install "mediakit @ git+https://github.com/LuckyKit/media-agent-suite-cc-plugin.git"

# 第 3 步：配置 API Key
# 编辑 ~/.media-agent/.env，填入：
#   TWITTERAPI_IO_KEY=你的key
# 注册获取 Key → https://twitterapi.io/dashboard
```

## 日常更新

```bash
# 只需更新插件（CLI 会在下次使用时自动升级）
claude plugin marketplace update
claude plugin update media-agent-suite@MediaAgentSuite
```

## 使用

在 Claude Code 中直接说：

| 你说 | 做什么 |
|------|--------|
| "找 Twitter 上关于 AI 的爆款" | 搜索热门推文 |
| "分析这条推文为什么火" | 拆解传播规律 |
| "帮我写条推文" | 生成文案 |

## License

MIT
