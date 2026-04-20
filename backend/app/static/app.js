const TEAM_NAME_MAP = {
  Arsenal: "阿森纳",
  Liverpool: "利物浦",
  "Real Madrid": "皇家马德里",
  Barcelona: "巴塞罗那",
  Inter: "国际米兰",
  Internazionale: "国际米兰",
  Juventus: "尤文图斯",
  "Bayern Munich": "拜仁慕尼黑",
  "Borussia Dortmund": "多特蒙德",
  Dortmund: "多特蒙德",
  PSG: "巴黎圣日耳曼",
  "Paris Saint Germain": "巴黎圣日耳曼",
  Marseille: "马赛",
  "Manchester City": "曼城",
  Chelsea: "切尔西",
  "Manchester United": "曼联",
  "Atletico Madrid": "马德里竞技",
  "Atletico de Madrid": "马德里竞技",
  Sevilla: "塞维利亚",
  Milan: "AC米兰",
  "AC Milan": "AC米兰",
  Napoli: "那不勒斯",
  Draw: "平局",
  Home: "主队",
  Away: "客队",
};

const PROVIDER_NAME_MAP = {
  demo: "演示赔率",
  api_football_odds: "API-Football 赔率",
  api_football: "API-Football 比分",
  "demo-live": "演示比分",
  auto: "自动",
  "auto-live": "自动",
  unavailable: "未接入",
  off: "关闭",
};

const MODE_NAME_MAP = {
  demo: "演示模式",
  api_football_odds: "免费真实版",
  api_football: "免费真实版",
  auto: "自动模式",
};

const SIGNAL_NAME_MAP = {
  bullish: "看涨",
  bearish: "看跌",
  neutral: "中性",
};

const RISK_NAME_MAP = {
  Low: "低",
  Medium: "中",
  High: "高",
};

const STATUS_NAME_MAP = {
  NS: "未开始",
  LIVE: "进行中",
  "1H": "上半场",
  HT: "中场",
  "2H": "下半场",
  ET: "加时",
  P: "点球",
  BT: "中断",
  INT: "中断",
  FT: "完场",
  SUSP: "暂停",
};

const EVENT_TYPE_MAP = {
  Goal: "进球",
  Card: "红黄牌",
  subst: "换人",
};

const EVENT_DETAIL_MAP = {
  "Normal Goal": "普通进球",
  Penalty: "点球",
  "Yellow Card": "黄牌",
  "Red Card": "红牌",
  Substitution: "换人",
};

const TEXT_REPLACEMENTS = [
  ["Not Started", "未开始"],
  ["First Half", "上半场"],
  ["Second Half", "下半场"],
  ["Halftime", "中场休息"],
  ["Finished", "已结束"],
  ["Suspended", "暂停"],
  ["Cancelled", "取消"],
  ["Postponed", "延期"],
  ["Assist", "助攻"],
];

const state = {
  matches: [],
  selectedMarketId: null,
  snapshot: null,
  system: null,
};

const elements = {
  providerBadge: document.getElementById("providerBadge"),
  modeBadge: document.getElementById("modeBadge"),
  liveBadge: document.getElementById("liveBadge"),
  systemNotice: document.getElementById("systemNotice"),
  matchList: document.getElementById("matchList"),
  refreshButton: document.getElementById("refreshButton"),
  eventTitle: document.getElementById("eventTitle"),
  eventMeta: document.getElementById("eventMeta"),
  marketStatus: document.getElementById("marketStatus"),
  scoreStatus: document.getElementById("scoreStatus"),
  scoreProvider: document.getElementById("scoreProvider"),
  scoreHomeName: document.getElementById("scoreHomeName"),
  scoreAwayName: document.getElementById("scoreAwayName"),
  scoreHomeValue: document.getElementById("scoreHomeValue"),
  scoreAwayValue: document.getElementById("scoreAwayValue"),
  scoreMinute: document.getElementById("scoreMinute"),
  scoreCards: document.getElementById("scoreCards"),
  recommendationAction: document.getElementById("recommendationAction"),
  recommendationSelection: document.getElementById("recommendationSelection"),
  recommendationScore: document.getElementById("recommendationScore"),
  recommendationRisk: document.getElementById("recommendationRisk"),
  recommendationReasons: document.getElementById("recommendationReasons"),
  metricBookmakers: document.getElementById("metricBookmakers"),
  metricOverround: document.getElementById("metricOverround"),
  metricSpread: document.getElementById("metricSpread"),
  metricSignal: document.getElementById("metricSignal"),
  metricLive: document.getElementById("metricLive"),
  metricCards: document.getElementById("metricCards"),
  metricUpdated: document.getElementById("metricUpdated"),
  signalPanel: document.getElementById("signalPanel"),
  eventsPanel: document.getElementById("eventsPanel"),
  bookmakerPanel: document.getElementById("bookmakerPanel"),
  monitorTableBody: document.getElementById("monitorTableBody"),
  oddsCaption: document.getElementById("oddsCaption"),
  probabilityCaption: document.getElementById("probabilityCaption"),
};

const oddsChart = echarts.init(document.getElementById("oddsChart"));
const probabilityChart = echarts.init(document.getElementById("probabilityChart"));

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatTime(value) {
  if (!value) return "--";
  return new Date(value).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatCompactNumber(value) {
  if (value == null) return "--";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(value);
}

function formatOverround(value) {
  if (value == null) return "--";
  return `${((value - 1) * 100).toFixed(1)}%`;
}

function localizeProvider(value) {
  return PROVIDER_NAME_MAP[value] || value || "--";
}

function localizeMode(value) {
  return MODE_NAME_MAP[value] || value || "--";
}

function localizeSignal(value) {
  return SIGNAL_NAME_MAP[value] || value || "中性";
}

function localizeRisk(value) {
  return RISK_NAME_MAP[value] || value || "--";
}

function localizeStatus(value) {
  return STATUS_NAME_MAP[value] || value || "--";
}

function localizeTeamName(name) {
  return TEAM_NAME_MAP[name] || name || "--";
}

function localizeText(value) {
  let text = String(value ?? "");
  const teamEntries = Object.entries(TEAM_NAME_MAP).sort((left, right) => right[0].length - left[0].length);
  teamEntries.forEach(([english, chinese]) => {
    text = text.replaceAll(english, chinese);
  });
  TEXT_REPLACEMENTS.forEach(([english, chinese]) => {
    text = text.replaceAll(english, chinese);
  });
  return text;
}

function localizeMatchName(eventName, homeName, awayName) {
  if (homeName && awayName) {
    return `${localizeTeamName(homeName)} vs ${localizeTeamName(awayName)}`;
  }
  return localizeText(eventName || "--");
}

function localizeEventType(value) {
  return EVENT_TYPE_MAP[value] || localizeText(value);
}

function localizeEventDetail(value) {
  return EVENT_DETAIL_MAP[value] || localizeText(value);
}

function getLiveScore(record) {
  return (
    record?.live_score || {
      minute_label: "--",
      home_score: null,
      away_score: null,
      home_yellow: 0,
      away_yellow: 0,
      home_red: 0,
      away_red: 0,
      status_long: "暂无实时比分数据",
      provider: "--",
      home_name: record?.home_name || "Home",
      away_name: record?.away_name || "Away",
      events: [],
    }
  );
}

function formatScore(liveScore) {
  if (liveScore.home_score == null || liveScore.away_score == null) {
    return "--";
  }
  return `${liveScore.home_score} - ${liveScore.away_score}`;
}

function formatCards(liveScore) {
  return `黄牌 ${liveScore.home_yellow || 0}-${liveScore.away_yellow || 0} | 红牌 ${liveScore.home_red || 0}-${liveScore.away_red || 0}`;
}

function usesDemoFallback(system) {
  if (!system) return false;
  return (
    system.active_provider === "demo" ||
    system.active_live_score_provider === "demo-live" ||
    system.fallback_active ||
    system.live_score_fallback_active
  );
}

function primarySystemMessage(system) {
  if (!system) {
    return "当前没有真实比赛数据。";
  }
  if (!system.api_football_ready) {
    if (usesDemoFallback(system)) {
      return "未配置 API_FOOTBALL_KEY，当前展示的是演示赔率和演示比分。填入免费 key 后会自动切到真实数据。";
    }
    return "未配置 API_FOOTBALL_KEY，当前无法抓取真实比赛和博彩公司赔率。";
  }
  return system.last_error || system.live_score_last_error || "当前没有可展示的比赛。";
}

function buildSystemNotice(system) {
  if (!system) {
    return ["正在读取系统状态…"];
  }

  const lines = [];
  if (!system.api_football_ready) {
    if (usesDemoFallback(system)) {
      lines.push("缺少 API_FOOTBALL_KEY，当前已回退到演示数据。");
      lines.push("在 D:\\football\\.env 里填入免费 key 后会自动切到真实盘口和真实比分。");
    } else {
      lines.push("缺少 API_FOOTBALL_KEY。");
      lines.push("请先在 D:\\football\\.env 里填入免费 key。");
    }
  }
  if (system.last_error) {
    lines.push(localizeText(system.last_error));
  }
  if (system.live_score_last_error && system.live_score_last_error !== system.last_error) {
    lines.push(localizeText(system.live_score_last_error));
  }
  if (!lines.length) {
    lines.push("当前已连接真实免费数据源。");
  }
  lines.push("免费档请求数有限，默认按保守频率轮询。");
  return lines;
}

function renderSystem(system) {
  state.system = system;
  elements.providerBadge.textContent = `盘口源：${localizeProvider(system.active_provider)}`;
  elements.modeBadge.textContent = `模式：${localizeMode(system.configured_mode)}`;
  elements.liveBadge.textContent = `比分源：${localizeProvider(system.active_live_score_provider)}`;
  elements.providerBadge.className = `pill ${system.fallback_active ? "warning" : ""}`;
  elements.modeBadge.className = "pill ghost";
  elements.liveBadge.className = `pill ${system.live_score_fallback_active ? "warning" : "ghost"}`;
  elements.systemNotice.innerHTML = buildSystemNotice(system)
    .map((line) => `<div>${escapeHtml(line)}</div>`)
    .join("");
}

function renderMatchList() {
  if (!state.matches.length) {
    elements.matchList.innerHTML = `<div class="empty-block">${escapeHtml(localizeText(primarySystemMessage(state.system)))}</div>`;
    return;
  }

  elements.matchList.innerHTML = state.matches
    .map((match) => {
      const liveScore = getLiveScore(match);
      const active = match.market_id === state.selectedMarketId ? "active" : "";
      const liveTag = match.in_play ? '<span class="tag live">进行中</span>' : '<span class="tag">赛前</span>';
      return `
        <button class="match-item ${active}" data-market-id="${escapeHtml(match.market_id)}">
          <div class="match-item-top">
            <strong>${escapeHtml(localizeMatchName(match.event_name, match.home_name, match.away_name))}</strong>
            ${liveTag}
          </div>
          <div class="match-scoreline">
            <span>${escapeHtml(formatScore(liveScore))}</span>
            <span>${escapeHtml(liveScore.minute_label || "--")}</span>
          </div>
          <div class="match-item-meta">
            <span>${escapeHtml(`博彩公司 ${match.bookmaker_count || 0}`)}</span>
            <span>${escapeHtml(localizeSignal(match.signal))}</span>
          </div>
          <div class="match-item-foot">${escapeHtml(formatTime(match.start_time))}</div>
        </button>
      `;
    })
    .join("");

  elements.matchList.querySelectorAll("[data-market-id]").forEach((button) => {
    button.addEventListener("click", () => {
      selectMarket(button.dataset.marketId);
    });
  });
}

function renderMonitorTable() {
  if (!state.matches.length) {
    elements.monitorTableBody.innerHTML = `
      <tr>
        <td colspan="8" class="monitor-empty">${escapeHtml(localizeText(primarySystemMessage(state.system)))}</td>
      </tr>
    `;
    return;
  }

  elements.monitorTableBody.innerHTML = state.matches
    .map((match) => {
      const liveScore = getLiveScore(match);
      return `
        <tr class="${match.market_id === state.selectedMarketId ? "selected" : ""}">
          <td>${escapeHtml(localizeMatchName(match.event_name, match.home_name, match.away_name))}</td>
          <td>${escapeHtml(formatScore(liveScore))}</td>
          <td>${escapeHtml(liveScore.minute_label || "--")}</td>
          <td>${escapeHtml(formatCompactNumber(match.bookmaker_count || 0))}</td>
          <td>${escapeHtml(match.spread != null ? match.spread.toFixed(2) : "--")}</td>
          <td>${escapeHtml(localizeSignal(match.signal))}</td>
          <td>${escapeHtml(Math.round(match.confidence || 0))}</td>
          <td>${escapeHtml(formatTime(match.updated_at))}</td>
        </tr>
      `;
    })
    .join("");
}

function renderEmptyCharts(message) {
  const option = {
    backgroundColor: "transparent",
    title: {
      text: message,
      left: "center",
      top: "middle",
      textStyle: {
        color: "#9ab0c6",
        fontSize: 16,
        fontWeight: 500,
      },
    },
    xAxis: { show: false },
    yAxis: { show: false },
    series: [],
  };
  oddsChart.setOption(option, true);
  probabilityChart.setOption(option, true);
}

function renderEmptyDashboard() {
  const systemMessage = localizeText(primarySystemMessage(state.system));
  elements.marketStatus.textContent = usesDemoFallback(state.system) ? "演示回退中" : "等待真实数据";
  elements.eventTitle.textContent = usesDemoFallback(state.system)
    ? "当前未连接免费真实数据，已回退到演示面板"
    : "当前没有可展示的真实比赛";
  elements.eventMeta.textContent = systemMessage;

  elements.scoreStatus.textContent = systemMessage;
  elements.scoreProvider.textContent = `比分源：${localizeProvider(state.system?.active_live_score_provider || "--")}`;
  elements.scoreHomeName.textContent = "主队";
  elements.scoreAwayName.textContent = "客队";
  elements.scoreHomeValue.textContent = "-";
  elements.scoreAwayValue.textContent = "-";
  elements.scoreMinute.textContent = "--";
  elements.scoreCards.textContent = "黄牌 0-0 | 红牌 0-0";

  elements.recommendationAction.textContent = "等待数据";
  elements.recommendationSelection.textContent = "暂无建议方向";
  elements.recommendationScore.textContent = "--";
  elements.recommendationRisk.textContent = "--";
  elements.recommendationReasons.innerHTML = `
    <li>${escapeHtml(systemMessage)}</li>
    <li>${
      usesDemoFallback(state.system)
        ? "当前仍可查看演示数据；填入免费 key 后会切换到真实比赛、真实比分和真实赔率。"
        : "免费版需要 API_FOOTBALL_KEY 才能抓取真实比赛和赔率。"
    }</li>
  `;

  elements.metricBookmakers.textContent = "--";
  elements.metricOverround.textContent = "--";
  elements.metricSpread.textContent = "--";
  elements.metricSignal.textContent = "--";
  elements.metricLive.textContent = "--";
  elements.metricCards.textContent = "--";
  elements.metricUpdated.textContent = state.system?.updated_at ? formatTime(state.system.updated_at) : "--";

  elements.signalPanel.innerHTML = `<div class="empty-block">${escapeHtml(systemMessage)}</div>`;
  elements.eventsPanel.innerHTML = '<div class="empty-block">接入真实数据后，这里会显示进球、红黄牌和换人。</div>';
  elements.bookmakerPanel.innerHTML = '<div class="empty-block">接入真实数据后，这里会显示各家博彩公司盘口。</div>';
  elements.oddsCaption.textContent = "等待赔率数据";
  elements.probabilityCaption.textContent = "等待概率数据";
  renderEmptyCharts("等待真实数据");
}

async function fetchJSON(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`请求失败：${url}`);
  }
  return response.json();
}

async function refreshMatches() {
  const [matches, system] = await Promise.all([
    fetchJSON("/api/matches"),
    fetchJSON("/api/system/status"),
  ]);

  state.matches = matches;
  renderSystem(system);

  if (!state.selectedMarketId && matches.length) {
    state.selectedMarketId = matches[0].market_id;
  }
  if (state.selectedMarketId && !matches.some((match) => match.market_id === state.selectedMarketId)) {
    state.selectedMarketId = matches.length ? matches[0].market_id : null;
  }

  renderMatchList();
  renderMonitorTable();

  if (!state.selectedMarketId) {
    renderEmptyDashboard();
    return;
  }

  await loadSelectedMarket();
}

async function selectMarket(marketId) {
  state.selectedMarketId = marketId;
  renderMatchList();
  renderMonitorTable();
  await loadSelectedMarket();
}

async function loadSelectedMarket() {
  if (!state.selectedMarketId) {
    renderEmptyDashboard();
    return;
  }

  const [snapshot, timeseries] = await Promise.all([
    fetchJSON(`/api/market/${state.selectedMarketId}/snapshot`),
    fetchJSON(`/api/market/${state.selectedMarketId}/timeseries?limit=120`),
  ]);
  state.snapshot = snapshot;
  renderSnapshot(snapshot, timeseries);
}

function renderSnapshot(snapshot, timeseries) {
  const recommendation = snapshot.recommendation || {};
  const liveScore = getLiveScore(snapshot);
  const extra = snapshot.extra || {};
  const primaryRunner = snapshot.runners?.[0] || {};

  elements.marketStatus.textContent = snapshot.in_play ? "滚球赔率" : "赛前赔率";
  elements.eventTitle.textContent = localizeMatchName(snapshot.event_name, snapshot.home_name, snapshot.away_name);
  elements.eventMeta.textContent = `${formatTime(snapshot.start_time)} | ${localizeProvider(snapshot.provider)} | ${localizeStatus(snapshot.status)}`;

  elements.scoreStatus.textContent = localizeText(liveScore.status_long || "暂无实时比分");
  elements.scoreProvider.textContent = `比分源：${localizeProvider(liveScore.provider || "--")}`;
  elements.scoreHomeName.textContent = localizeTeamName(liveScore.home_name || snapshot.home_name || "Home");
  elements.scoreAwayName.textContent = localizeTeamName(liveScore.away_name || snapshot.away_name || "Away");
  elements.scoreHomeValue.textContent = liveScore.home_score ?? "-";
  elements.scoreAwayValue.textContent = liveScore.away_score ?? "-";
  elements.scoreMinute.textContent = liveScore.minute_label || "--";
  elements.scoreCards.textContent = formatCards(liveScore);

  elements.recommendationAction.textContent = recommendation.recommendation || "不下注";
  elements.recommendationSelection.textContent = recommendation.selection_name
    ? localizeTeamName(recommendation.selection_name)
    : "暂无建议方向";
  elements.recommendationScore.textContent = Math.round(recommendation.score || 0);
  elements.recommendationRisk.textContent = localizeRisk(recommendation.risk_level);
  elements.recommendationReasons.innerHTML = (recommendation.reasons || [])
    .map((reason) => `<li>${escapeHtml(localizeText(reason))}</li>`)
    .join("");

  elements.metricBookmakers.textContent = formatCompactNumber(extra.bookmaker_count || 0);
  elements.metricOverround.textContent = formatOverround(extra.overround);
  elements.metricSpread.textContent = primaryRunner.market_width != null ? primaryRunner.market_width.toFixed(2) : "--";
  elements.metricSignal.textContent = localizeSignal(recommendation.signal);
  elements.metricLive.textContent = liveScore.minute_label || "--";
  elements.metricCards.textContent = formatCards(liveScore);
  elements.metricUpdated.textContent = formatTime(snapshot.updated_at);

  renderSignals(snapshot.signals || []);
  renderEvents(liveScore.events || []);
  renderBookmakers(extra.bookmakers || []);
  renderOddsChart(snapshot, timeseries);
  renderProbabilityChart(snapshot, timeseries);
}

function renderSignals(signals) {
  if (!signals.length) {
    elements.signalPanel.innerHTML = '<div class="empty-block">当前没有明显市场信号。</div>';
    return;
  }

  elements.signalPanel.innerHTML = signals
    .map((signal) => `
      <article class="signal-card ${escapeHtml(signal.type || "neutral")}">
        <div class="signal-title">${escapeHtml(localizeText(signal.title || "市场信号"))}</div>
        <p>${escapeHtml(localizeText(signal.detail || ""))}</p>
      </article>
    `)
    .join("");
}

function renderEvents(events) {
  if (!events.length) {
    elements.eventsPanel.innerHTML = '<div class="empty-block">当前没有事件数据。</div>';
    return;
  }

  elements.eventsPanel.innerHTML = events
    .slice()
    .reverse()
    .map((event) => {
      const teamClass = event.team_side || "neutral";
      const title = `${localizeEventType(event.type)} · ${localizeEventDetail(event.detail)}`;
      const metaParts = [
        localizeTeamName(event.team || ""),
        event.player ? localizeText(event.player) : "",
        event.assist ? `助攻 ${localizeText(event.assist)}` : "",
      ].filter(Boolean);
      return `
        <article class="event-item ${escapeHtml(teamClass)}">
          <div class="event-minute">${escapeHtml(event.minute_label || "--")}</div>
          <div class="event-content">
            <div class="event-title">${escapeHtml(title)}</div>
            <div class="event-meta">${escapeHtml(metaParts.join(" · "))}</div>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderBookmakers(bookmakers) {
  if (!bookmakers.length) {
    elements.bookmakerPanel.innerHTML = '<div class="empty-block">当前没有博彩公司盘口数据。</div>';
    return;
  }

  elements.bookmakerPanel.innerHTML = `
    <div class="table-wrap">
      <table class="bookmaker-table">
        <thead>
          <tr>
            <th>博彩公司</th>
            <th>主胜</th>
            <th>平局</th>
            <th>客胜</th>
          </tr>
        </thead>
        <tbody>
          ${bookmakers
            .map((bookmaker) => `
              <tr>
                <td>${escapeHtml(bookmaker.name || "--")}</td>
                <td>${escapeHtml(bookmaker.home != null ? Number(bookmaker.home).toFixed(2) : "--")}</td>
                <td>${escapeHtml(bookmaker.draw != null ? Number(bookmaker.draw).toFixed(2) : "--")}</td>
                <td>${escapeHtml(bookmaker.away != null ? Number(bookmaker.away).toFixed(2) : "--")}</td>
              </tr>
            `)
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderOddsChart(snapshot, timeseries) {
  const runnerMap = new Map();
  (snapshot.runners || []).forEach((runner) => {
    runnerMap.set(runner.selection_id, {
      name: localizeTeamName(runner.name),
      values: [],
    });
  });

  timeseries.forEach((point) => {
    (point.runners || []).forEach((runner) => {
      const series = runnerMap.get(runner.selection_id);
      const price = runner.price ?? runner.mid_price;
      if (series && price != null) {
        series.values.push([point.timestamp, price]);
      }
    });
  });

  elements.oddsCaption.textContent = (snapshot.runners || [])
    .map((runner) => `${localizeTeamName(runner.name)} ${runner.price != null ? runner.price.toFixed(2) : "--"}`)
    .join(" / ");

  oddsChart.setOption({
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    legend: {
      textStyle: { color: "#dfe8f4" },
      top: 0,
    },
    grid: { left: 44, right: 18, top: 40, bottom: 32 },
    xAxis: {
      type: "time",
      axisLabel: { color: "#98acc1" },
      axisLine: { lineStyle: { color: "#38506c" } },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: "#98acc1" },
      splitLine: { lineStyle: { color: "rgba(122, 151, 182, 0.18)" } },
    },
    series: Array.from(runnerMap.values()).map((runner, index) => ({
      name: runner.name,
      type: "line",
      smooth: true,
      symbol: "none",
      lineStyle: { width: 2.8 },
      areaStyle: { opacity: 0.06 },
      emphasis: { focus: "series" },
      data: runner.values,
      color: ["#52ffa8", "#ff8756", "#3aa8ff"][index % 3],
    })),
  }, true);
}

function renderProbabilityChart(snapshot, timeseries) {
  const runnerMap = new Map();
  (snapshot.runners || []).forEach((runner) => {
    runnerMap.set(runner.selection_id, {
      name: localizeTeamName(runner.name),
      values: [],
    });
  });

  timeseries.forEach((point) => {
    (point.runners || []).forEach((runner) => {
      const series = runnerMap.get(runner.selection_id);
      const price = runner.price ?? runner.mid_price;
      if (series && price != null && price > 0) {
        series.values.push([point.timestamp, Number((100 / price).toFixed(2))]);
      }
    });
  });

  elements.probabilityCaption.textContent = "按平均赔率换算的隐含概率";
  probabilityChart.setOption({
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    legend: {
      textStyle: { color: "#dfe8f4" },
      top: 0,
    },
    grid: { left: 44, right: 18, top: 40, bottom: 32 },
    xAxis: {
      type: "time",
      axisLabel: { color: "#98acc1" },
      axisLine: { lineStyle: { color: "#38506c" } },
    },
    yAxis: {
      type: "value",
      axisLabel: {
        color: "#98acc1",
        formatter: "{value}%",
      },
      splitLine: { lineStyle: { color: "rgba(122, 151, 182, 0.18)" } },
    },
    series: Array.from(runnerMap.values()).map((runner, index) => ({
      name: runner.name,
      type: "line",
      smooth: true,
      symbol: "none",
      lineStyle: { width: 2.6 },
      data: runner.values,
      color: ["#a7ff83", "#ffd166", "#70d6ff"][index % 3],
    })),
  }, true);
}

function initSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/market-stream`);

  socket.onmessage = async (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type !== "matches") return;

    state.matches = payload.matches || [];
    renderSystem(payload.system);
    renderMatchList();
    renderMonitorTable();

    if (!state.selectedMarketId && state.matches.length) {
      state.selectedMarketId = state.matches[0].market_id;
    }
    if (state.selectedMarketId && !state.matches.some((match) => match.market_id === state.selectedMarketId)) {
      state.selectedMarketId = state.matches.length ? state.matches[0].market_id : null;
    }

    if (state.selectedMarketId) {
      await loadSelectedMarket();
    } else {
      renderEmptyDashboard();
    }

    socket.send("ack");
  };

  socket.onopen = () => socket.send("hello");
  socket.onclose = () => setTimeout(initSocket, 2000);
}

async function bootstrap() {
  try {
    await refreshMatches();
    initSocket();
  } catch (error) {
    console.error(error);
    elements.systemNotice.textContent = "前端初始化失败，请检查后端是否已启动。";
    renderEmptyDashboard();
  }
}

elements.refreshButton.addEventListener("click", async () => {
  await refreshMatches();
});

window.addEventListener("resize", () => {
  oddsChart.resize();
  probabilityChart.resize();
});

bootstrap();
