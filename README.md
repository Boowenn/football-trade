# 足球赔率分析可视化系统

一个基于 FastAPI 的免费足球赔率看盘面板。当前默认模式不依赖 Betfair，也不依赖付费 API，而是直接抓取 BetExplorer 网页中的胜平负赔率，生成比赛列表、盘口结构和辅助下注建议。

## 当前版本做了什么

- 默认使用 `BetExplorer` 网页抓取模式
- 展示可抓取到的赛前/滚球比赛列表
- 展示胜平负赔率、超额利润、盘口分歧、赔率走势和隐含概率
- 输出基于盘口强弱、赔率差距、超低赔惩罚、盘口分歧的建议
- 前端默认优先选中一场有明确方向的比赛
- 默认端口改为 `5001`

## 不包含什么

当前版本不是 Betfair 交易所系统，也不是资金流分析系统。下面这些数据现在都没有：

- Betfair Back / Lay
- 成交量
- 挂单深度
- Whale 检测
- 真实投注量
- 默认实时比分和比赛事件

## 当前数据源

默认数据源：

- `DATA_MODE=betexplorer_scrape`
- `LIVE_SCORE_MODE=off`

说明：

- 赔率来自 BetExplorer 网页抓取
- 当前主要抓取胜平负盘口
- `bookmakers` 面板目前是基于抓取页面整理出的单源展示，不是完整多书商明细
- 如果页面结构变动，抓取可能失效

## 下注建议逻辑

当前建议不是“预测比分”，而是盘口结构辅助判断，核心规则包括：

- 最低赔率方向与第二低赔率方向的差距
- 隐含概率领先幅度
- 盘口分歧惩罚
- 超低赔过滤
- 历史赔率如果没有真实变化，不强行按趋势模型打分
- 没有实时比分时，不把无效滚球噪音当成强信号

因此页面上会同时出现：

- `主胜 / 客胜`
- `观察 主胜 / 观察 客胜`
- `不下注`

`不下注` 不是异常，通常代表盘口优势不够、赔率太薄，或者当前抓到的信息不足以支持直接下单。

## 启动方式

### 方式一

直接双击：

```bat
start.bat
```

### 方式二

手动运行：

```powershell
cd D:\football
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 5001
```

浏览器打开：

```text
http://127.0.0.1:5001
```

## 环境变量

参考 `.env.example`。

推荐最小配置：

```env
APP_PORT=5001

DATA_MODE=betexplorer_scrape
LIVE_SCORE_MODE=off

TRACKED_MARKETS_LIMIT=6
MARKET_WINDOW_HOURS=18
```

可选备用配置：

```env
API_FOOTBALL_KEY=
API_FOOTBALL_BASE_URL=https://v3.football.api-sports.io
API_FOOTBALL_TIMEZONE=Asia/Tokyo
```

说明：

- 抓取模式默认不依赖 `API_FOOTBALL_KEY`
- `API_FOOTBALL_KEY` 目前仅作为备用模式保留
- `TRACKED_MARKETS_LIMIT` 控制首页展示的比赛数
- `PREFERRED_BOOKMAKERS` 和 `TARGET_LEAGUE_IDS` 可以进一步收缩范围

## 主要文件

- `backend/app/main.py`: FastAPI 入口
- `backend/app/services/providers.py`: 数据源与 BetExplorer 抓取逻辑
- `backend/app/services/analyzer.py`: 下注建议逻辑
- `backend/app/services/market_hub.py`: 市场汇总、排序、缓存和推送
- `backend/app/static/index.html`: 前端页面
- `backend/app/static/app.js`: 前端交互和渲染
- `scripts/start.ps1`: 启动脚本

## 已知限制

- 目前没有稳定的免费实时比分抓取
- 当前建议更适合做盘口参考，不适合当成全自动下注信号
- 单网页抓取模式下，盘口变化的时间序列信息比较弱
- 如果远端网站改版，需要同步调整解析逻辑

## 本次仓库更新包含

- 切到 BetExplorer 抓取模式作为默认数据源
- 修正 `5001` 端口配置和启动脚本
- 修正前端等待态和图表组件容错
- 调整建议引擎，避免“有历史点但没有真实波动”时全变成 `不下注`
- 重写 README，和当前代码实现保持一致
