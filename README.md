# 足球盘口建议台

一个基于 FastAPI 的免费足球赔率看盘工具。

当前版本默认不依赖 Betfair，也不依赖付费 API。系统直接抓取 BetExplorer 的多家公司赔率，并把以下盘口一起纳入建议：

- 胜平负 1X2
- 亚盘 AH
- 平局退款 DNB
- 双重机会 DC
- 大小球 O/U
- BTTS
- 比赛事件和比分状态（如果后续接入实时比分源）

应用默认运行在 `http://127.0.0.1:5001/`。

## 当前架构

- 赔率源：`BetExplorer` 抓取
- 默认模式：`DATA_MODE=betexplorer_scrape`
- 默认端口：`5001`
- 当前建议逻辑：综合 1X2、亚盘主线、DNB、双重机会、大小球、BTTS、赔率离散度、多家公司数量和历史赔率变化

这不是交易所深度系统。当前版本不提供：

- Betfair Back / Lay
- 成交量
- 市场深度
- Whale 资金流

## 已实现功能

- 抓取真实比赛列表
- 抓取多家公司 1X2 赔率
- 抓取亚盘主线与盘口倾向
- 抓取 DNB、双重机会、BTTS
- 抓取大小球主线与盘口倾向
- 基于盘口结构生成多玩法建议
- 给出主推玩法
- 给出为什么不用其它玩法
- 给出建议仓位
- 展示赔率走势和隐含概率曲线
- 前端直接展示多家公司赔率、亚盘、大小球和风险提示

## 下注建议逻辑

建议不再只看单一胜平负赔率。

当前评分会综合这些因素：

- 1X2 当前主流方向和赔率差距
- 多家公司数量
- 各公司报价离散度
- 亚盘主线是否和 1X2 主方向一致
- 亚盘赔率倾向是否支持同一方向
- 大小球主线高低带来的波动判断
- 如果有历史数据，是否存在持续压盘或走弱
- 如果有实时比分，比分和红牌是否支持当前方向

输出结果不再只返回一个 `主胜 / 客胜` 结论，而是会同时返回：

- `primary_play`：主推玩法
- `stake_plan`：建议仓位、单位数和单场资金上限
- `why_not_others`：为什么不选其它备选玩法
- `plays`：当前盘口下的玩法分层列表

主推玩法可能来自：

- `胜平负`
- `亚盘`
- `平局退款`
- `双重机会`
- `大小球`
- `BTTS`
- `不下注`

仓位输出分为：

- `放弃`
- `试探仓`
- `标准仓`
- `进取仓`

## 启动方式

### 方式 1：脚本启动

```bat
start.bat
```

### 方式 2：手动启动

```powershell
cd D:\football
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 5001
```

启动后访问：

```text
http://127.0.0.1:5001/
```

## 环境变量

`.env` 示例：

```env
APP_PORT=5001

DATA_MODE=betexplorer_scrape
LIVE_SCORE_MODE=off

TRACKED_MARKETS_LIMIT=6
MARKET_WINDOW_HOURS=18
POLL_INTERVAL_SECONDS=300
DISCOVERY_INTERVAL_SECONDS=1800
```

说明：

- 当前抓取模式不要求 `API_FOOTBALL_KEY`
- 如果后续要接 API-Football，可以再补 `API_FOOTBALL_KEY`
- `TRACKED_MARKETS_LIMIT` 控制前端同时展示的比赛数量
- `POLL_INTERVAL_SECONDS` 控制轮询刷新间隔

## 核心文件

- `backend/app/main.py`：FastAPI 入口
- `backend/app/services/providers.py`：赔率数据源和 BetExplorer 明细盘口解析
- `backend/app/services/analyzer.py`：下注建议评分逻辑
- `backend/app/services/market_hub.py`：盘口缓存、历史序列和广播
- `backend/app/static/index.html`：前端页面结构
- `backend/app/static/app.js`：前端逻辑
- `backend/app/static/styles.css`：页面样式

## 已验证

这版已经做过这些检查：

- `python -m compileall backend`
- `node --check backend/app/static/app.js`
- 本地启动 `5001` 后，实际请求：
  - `/api/matches`
  - `/api/market/{id}/snapshot`
  - `/api/market/{id}/recommendation`

实际抓取结果里已经可以看到：

- 多家公司 1X2 行
- 亚盘主线和对应赔率
- DNB、双重机会、BTTS 盘口
- 大小球主线和对应赔率
- 主推玩法、建议仓位和不选其它玩法的解释
- 不再是所有比赛都显示 `不下注`

## 限制

- BetExplorer 某些比赛不一定同时有 1X2、AH、O/U 三类盘口
- 某些比赛公司数很少时，建议会偏保守
- 当前默认不单独接实时比分源，所以实时事件面板可能为空
- 抓取站点结构如果未来变化，需要同步调整解析器
