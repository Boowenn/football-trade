# 足球赔率分析可视化系统

这是一个不依赖 Betfair 的纯免费版足球盘口分析 MVP。

系统现在只围绕两类数据工作：

- API-Football 的比赛、比分、事件和胜平负赔率
- 无 key 时的本地演示赔率与演示比分回退

它不再提供交易所语义的数据：

- 没有 Back / Lay
- 没有成交量
- 没有挂单深度
- 没有 Whale 资金流检测

当前建议逻辑基于以下因素输出辅助下注建议：

- 博彩公司赔率从开盘到当前的收缩或上浮
- 不同博彩公司之间的盘口分歧
- 实时比分、红牌和比赛分钟

## 启动

1. 运行 `start.bat`
2. 浏览器打开 `http://127.0.0.1:8000`

## 推荐配置

推荐直接用：

- `DATA_MODE=auto`
- `LIVE_SCORE_MODE=auto`

行为如下：

- 已配置 `API_FOOTBALL_KEY`：自动使用 API-Football 真实免费数据
- 未配置 `API_FOOTBALL_KEY`：自动回退到演示赔率和演示比分，页面仍可正常展示

如果你只想强制跑真实数据，也可以手动设置：

- `DATA_MODE=api_football_odds`
- `LIVE_SCORE_MODE=api_football`

如果你只想本地演示：

- `DATA_MODE=demo`
- `LIVE_SCORE_MODE=demo`

## 环境变量

编辑 `.env`：

```env
DATA_MODE=auto
LIVE_SCORE_MODE=auto

API_FOOTBALL_KEY=你的免费API_FOOTBALL_KEY
API_FOOTBALL_BASE_URL=https://v3.football.api-sports.io
API_FOOTBALL_TIMEZONE=Asia/Tokyo

PREFERRED_BOOKMAKERS=Bet365,William Hill,1xBet,Pinnacle,Unibet
TARGET_LEAGUE_IDS=
```

说明：

- `API_FOOTBALL_KEY` 为空时，系统会自动回退到演示数据
- `PREFERRED_BOOKMAKERS` 可以缩小赔率来源，减少噪音
- `TARGET_LEAGUE_IDS` 可以只追踪特定联赛，进一步控制免费请求数
- 当前默认轮询已经压到免费档可承受的级别，不适合做高频准实时盯盘

## 页面内容

- 比赛列表
- 单场详情
- 实时比分与事件流
- 博彩公司赔率表
- 赔率走势和隐含概率走势
- 基于赔率变化、盘口分歧、比分和红牌的下注建议

## 说明

- 这是辅助决策工具，不是自动下注系统
- 免费档是 `100 requests/day` 级别，不能长期高频刷新；想稳定使用就要接受低频轮询
- 若要长期跑真实数据，建议把追踪联赛和博彩公司范围收窄
