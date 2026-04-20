const PROVIDER_NAMES = {
  demo: "演示赔率",
  api_football_odds: "API-Football 赔率",
  api_football: "API-Football 比分",
  betexplorer_scrape: "BetExplorer 抓取",
  "demo-live": "演示比分",
  auto: "自动",
  "auto-live": "自动",
  unavailable: "不可用",
  off: "关闭",
};

const MODE_NAMES = {
  demo: "演示",
  api_football_odds: "API-Football",
  betexplorer_scrape: "免费抓取",
  auto: "自动",
};

const SIGNAL_NAMES = {
  bullish: "偏多",
  bearish: "偏空",
  neutral: "中性",
};

const RISK_NAMES = {
  Low: "低",
  Medium: "中",
  High: "高",
};

const STATUS_NAMES = {
  NS: "未开赛",
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
  relatedMarketsPanel: document.getElementById("relatedMarketsPanel"),
  monitorTableBody: document.getElementById("monitorTableBody"),
  oddsCaption: document.getElementById("oddsCaption"),
  probabilityCaption: document.getElementById("probabilityCaption"),
};

const oddsChartElement = document.getElementById("oddsChart");
const probabilityChartElement = document.getElementById("probabilityChart");
const chartsEnabled = typeof window !== "undefined" && typeof window.echarts !== "undefined";
const oddsChart = chartsEnabled && oddsChartElement ? echarts.init(oddsChartElement) : null;
const probabilityChart = chartsEnabled && probabilityChartElement ? echarts.init(probabilityChartElement) : null;

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

function formatLine(value) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  const number = Number(value);
  return number > 0 ? `+${number.toFixed(2)}` : number.toFixed(2);
}

function sideText(value) {
  return {
    home: "主队",
    draw: "平局",
    away: "客队",
    balanced: "均衡",
    over: "大球",
    under: "小球",
  }[value] || value || "--";
}

function localizeProvider(value) {
  return PROVIDER_NAMES[value] || value || "--";
}

function localizeMode(value) {
  return MODE_NAMES[value] || value || "--";
}

function localizeSignal(value) {
  return SIGNAL_NAMES[value] || value || "中性";
}

function localizeRisk(value) {
  return RISK_NAMES[value] || value || "--";
}

function localizeStatus(value) {
  return STATUS_NAMES[value] || value || "--";
}

function getLiveScore(record) {
  return (
    record?.live_score || {
      matched: false,
      minute_label: "--",
      home_score: null,
      away_score: null,
      home_yellow: 0,
      away_yellow: 0,
      home_red: 0,
      away_red: 0,
      status_long: "暂无比分数据",
      provider: "off",
      home_name: record?.home_name || "主队",
      away_name: record?.away_name || "客队",
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

function primarySystemMessage(system) {
  if (!system) {
    return "正在连接系统。";
  }
  return system.last_error || system.live_score_last_error || "已接入真实赔率抓取。";
}

function buildSystemNotice(system) {
  if (!system) {
    return ["正在连接系统。"];
  }

  const lines = [];
  if (system.active_provider === "betexplorer_scrape") {
    lines.push("当前赔率来自 BetExplorer 抓取，建议基于多家公司盘口，不使用 Betfair 深度。");
  }
  if (system.active_live_score_provider === "off") {
    lines.push("当前未启用单独比分源，建议主要依赖盘口结构和赔率变化。");
  }
  if (system.last_error) {
    lines.push(system.last_error);
  }
  if (system.live_score_last_error && system.live_score_last_error !== system.last_error) {
    lines.push(system.live_score_last_error);
  }
  if (!lines.length) {
    lines.push("数据同步正常。");
  }
  return lines;
}

function renderSystem(system) {
  state.system = system;
  elements.providerBadge.textContent = `赔率源 ${localizeProvider(system.active_provider)}`;
  elements.modeBadge.textContent = `模式 ${localizeMode(system.configured_mode)}`;
  elements.liveBadge.textContent = `比分源 ${localizeProvider(system.active_live_score_provider)}`;
  elements.providerBadge.className = `pill ${system.fallback_active ? "warning" : ""}`;
  elements.modeBadge.className = "pill ghost";
  elements.liveBadge.className = `pill ${system.live_score_fallback_active ? "warning" : "ghost"}`;
  elements.systemNotice.innerHTML = buildSystemNotice(system)
    .map((line) => `<div>${escapeHtml(line)}</div>`)
    .join("");
}

function renderMatchList() {
  if (!state.matches.length) {
    elements.matchList.innerHTML = `<div class="empty-block">${escapeHtml(primarySystemMessage(state.system))}</div>`;
    return;
  }

  elements.matchList.innerHTML = state.matches
    .map((match) => {
      const liveScore = getLiveScore(match);
      const active = match.market_id === state.selectedMarketId ? "active" : "";
      const liveTag = match.in_play ? '<span class="tag live">滚球</span>' : '<span class="tag">赛前</span>';
      return `
        <button class="match-item ${active}" data-market-id="${escapeHtml(match.market_id)}">
          <div class="match-item-top">
            <strong>${escapeHtml(match.event_name || "--")}</strong>
            ${liveTag}
          </div>
          <div class="match-scoreline">
            <span>${escapeHtml(formatScore(liveScore))}</span>
            <span>${escapeHtml(liveScore.minute_label || "--")}</span>
          </div>
          <div class="match-item-meta">
            <span>${escapeHtml(`公司 ${match.bookmaker_count || 0}`)}</span>
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
        <td colspan="8" class="monitor-empty">${escapeHtml(primarySystemMessage(state.system))}</td>
      </tr>
    `;
    return;
  }

  elements.monitorTableBody.innerHTML = state.matches
    .map((match) => {
      const liveScore = getLiveScore(match);
      return `
        <tr class="${match.market_id === state.selectedMarketId ? "selected" : ""}">
          <td>${escapeHtml(match.event_name || "--")}</td>
          <td>${escapeHtml(formatScore(liveScore))}</td>
          <td>${escapeHtml(liveScore.minute_label || "--")}</td>
          <td>${escapeHtml(formatCompactNumber(match.bookmaker_count || 0))}</td>
          <td>${escapeHtml(match.spread != null ? Number(match.spread).toFixed(2) : "--")}</td>
          <td>${escapeHtml(localizeSignal(match.signal))}</td>
          <td>${escapeHtml(Math.round(match.confidence || 0))}</td>
          <td>${escapeHtml(formatTime(match.updated_at))}</td>
        </tr>
      `;
    })
    .join("");
}

function renderChartFallback(container, message) {
  if (!container) return;
  container.innerHTML = `<div class="empty-block">${escapeHtml(message)}</div>`;
}

function renderEmptyCharts(message) {
  if (!oddsChart || !probabilityChart) {
    renderChartFallback(oddsChartElement, message);
    renderChartFallback(probabilityChartElement, message);
    return;
  }

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
  const systemMessage = primarySystemMessage(state.system);
  elements.marketStatus.textContent = "等待数据";
  elements.eventTitle.textContent = "暂无可展示比赛";
  elements.eventMeta.textContent = systemMessage;
  elements.scoreStatus.textContent = systemMessage;
  elements.scoreProvider.textContent = `比分源 ${localizeProvider(state.system?.active_live_score_provider || "off")}`;
  elements.scoreHomeName.textContent = "主队";
  elements.scoreAwayName.textContent = "客队";
  elements.scoreHomeValue.textContent = "-";
  elements.scoreAwayValue.textContent = "-";
  elements.scoreMinute.textContent = "--";
  elements.scoreCards.textContent = "黄牌 0-0 | 红牌 0-0";

  elements.recommendationAction.textContent = "等待数据";
  elements.recommendationSelection.textContent = "尚未选出方向";
  elements.recommendationScore.textContent = "--";
  elements.recommendationRisk.textContent = "--";
  elements.recommendationReasons.innerHTML = `<li>${escapeHtml(systemMessage)}</li>`;

  elements.metricBookmakers.textContent = "--";
  elements.metricOverround.textContent = "--";
  elements.metricSpread.textContent = "--";
  elements.metricSignal.textContent = "--";
  elements.metricLive.textContent = "--";
  elements.metricCards.textContent = "--";
  elements.metricUpdated.textContent = state.system?.updated_at ? formatTime(state.system.updated_at) : "--";

  elements.signalPanel.innerHTML = `<div class="empty-block">${escapeHtml(systemMessage)}</div>`;
  elements.eventsPanel.innerHTML = '<div class="empty-block">暂无比赛事件。</div>';
  elements.bookmakerPanel.innerHTML = '<div class="empty-block">暂无博彩公司报价。</div>';
  elements.relatedMarketsPanel.innerHTML = '<div class="empty-block">暂无亚盘和大小球数据。</div>';
  elements.oddsCaption.textContent = "等待数据";
  elements.probabilityCaption.textContent = "等待数据";
  renderEmptyCharts("等待数据");
}

async function fetchJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`请求失败: ${url}`);
  }
  return response.json();
}

async function refreshMatches() {
  const [matches, system] = await Promise.all([fetchJSON("/api/matches"), fetchJSON("/api/system/status")]);
  state.matches = matches;
  renderSystem(system);

  if (!state.selectedMarketId && matches.length) {
    state.selectedMarketId = pickDefaultMarketId(matches);
  }
  if (state.selectedMarketId && !matches.some((match) => match.market_id === state.selectedMarketId)) {
    state.selectedMarketId = matches.length ? pickDefaultMarketId(matches) : null;
  }

  renderMatchList();
  renderMonitorTable();

  if (!state.selectedMarketId) {
    renderEmptyDashboard();
    return;
  }

  await loadSelectedMarket();
}

function pickDefaultMarketId(matches) {
  const preferred =
    matches.find((match) => (match.confidence || 0) >= 56 && match.signal !== "neutral") ||
    matches.find((match) => (match.confidence || 0) >= 56) ||
    matches[0];
  return preferred?.market_id || null;
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

  elements.marketStatus.textContent = snapshot.in_play ? "滚球盘口" : "赛前盘口";
  elements.eventTitle.textContent = snapshot.event_name || "--";
  elements.eventMeta.textContent = `${formatTime(snapshot.start_time)} | ${localizeProvider(snapshot.provider)} | ${localizeStatus(snapshot.status)}`;

  elements.scoreStatus.textContent = liveScore.status_long || "暂无比分数据";
  elements.scoreProvider.textContent = `比分源 ${localizeProvider(liveScore.provider || "off")}`;
  elements.scoreHomeName.textContent = liveScore.home_name || snapshot.home_name || "主队";
  elements.scoreAwayName.textContent = liveScore.away_name || snapshot.away_name || "客队";
  elements.scoreHomeValue.textContent = liveScore.home_score ?? "-";
  elements.scoreAwayValue.textContent = liveScore.away_score ?? "-";
  elements.scoreMinute.textContent = liveScore.minute_label || "--";
  elements.scoreCards.textContent = formatCards(liveScore);

  elements.recommendationAction.textContent = recommendation.recommendation || "不下注";
  elements.recommendationSelection.textContent = recommendation.selection_name || "暂无明确方向";
  elements.recommendationScore.textContent = Math.round(recommendation.score || 0);
  elements.recommendationRisk.textContent = localizeRisk(recommendation.risk_level);
  elements.recommendationReasons.innerHTML = (recommendation.reasons || [])
    .map((reason) => `<li>${escapeHtml(reason)}</li>`)
    .join("");

  elements.metricBookmakers.textContent = formatCompactNumber(extra.bookmaker_count || 0);
  elements.metricOverround.textContent = formatOverround(extra.overround);
  elements.metricSpread.textContent = primaryRunner.market_width != null ? Number(primaryRunner.market_width).toFixed(2) : "--";
  elements.metricSignal.textContent = localizeSignal(recommendation.signal);
  elements.metricLive.textContent = liveScore.minute_label || "--";
  elements.metricCards.textContent = formatCards(liveScore);
  elements.metricUpdated.textContent = formatTime(snapshot.updated_at);

  renderSignals(snapshot.signals || []);
  renderEvents(liveScore.events || []);
  renderBookmakers(extra.bookmakers || []);
  renderRelatedMarkets(extra.related_markets || {});
  renderOddsChart(snapshot, timeseries);
  renderProbabilityChart(snapshot, timeseries);
}

function renderSignals(signals) {
  if (!signals.length) {
    elements.signalPanel.innerHTML = '<div class="empty-block">当前没有额外风险提示。</div>';
    return;
  }

  elements.signalPanel.innerHTML = signals
    .map((signal) => `
      <article class="signal-card ${escapeHtml(signal.type || "neutral")}">
        <div class="signal-title">${escapeHtml(signal.title || "风险提示")}</div>
        <p>${escapeHtml(signal.detail || "")}</p>
      </article>
    `)
    .join("");
}

function renderEvents(events) {
  if (!events.length) {
    elements.eventsPanel.innerHTML = '<div class="empty-block">当前没有可用比赛事件。</div>';
    return;
  }

  elements.eventsPanel.innerHTML = events
    .slice()
    .reverse()
    .map((event) => {
      const teamClass = event.team_side || "neutral";
      const title = `${event.type || "事件"} ${event.detail || ""}`.trim();
      const metaParts = [event.team || "", event.player || "", event.assist ? `助攻 ${event.assist}` : ""].filter(Boolean);
      return `
        <article class="event-item ${escapeHtml(teamClass)}">
          <div class="event-minute">${escapeHtml(event.minute_label || "--")}</div>
          <div class="event-content">
            <div class="event-title">${escapeHtml(title)}</div>
            <div class="event-meta">${escapeHtml(metaParts.join(" / "))}</div>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderBookmakers(bookmakers) {
  if (!bookmakers.length) {
    elements.bookmakerPanel.innerHTML = '<div class="empty-block">当前没有多家公司 1X2 数据。</div>';
    return;
  }

  elements.bookmakerPanel.innerHTML = `
    <div class="table-wrap">
      <table class="bookmaker-table">
        <thead>
          <tr>
            <th>公司</th>
            <th>主胜</th>
            <th>平</th>
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

function renderRelatedMarkets(relatedMarkets) {
  const matchWinner = relatedMarkets.match_winner || {};
  const matchSummary = matchWinner.summary || {};
  const asianHandicap = relatedMarkets.asian_handicap || {};
  const ahSummary = asianHandicap.summary || {};
  const overUnder = relatedMarkets.over_under || {};
  const ouSummary = overUnder.summary || {};

  const cards = [
    buildMarketCard(
      "胜平负",
      matchWinner.bookmaker_count || 0,
      [
        ["主流方向", sideText(matchSummary.favorite_side)],
        ["均价主胜", formatPrice(matchSummary.avg_home)],
        ["均价平局", formatPrice(matchSummary.avg_draw)],
        ["均价客胜", formatPrice(matchSummary.avg_away)],
      ],
    ),
    buildMarketCard(
      "亚盘主线",
      asianHandicap.bookmaker_count || 0,
      [
        ["主线", formatLine(asianHandicap.active_line)],
        ["盘面支持", sideText(ahSummary.line_favored_side)],
        ["赔率倾向", sideText(ahSummary.lean)],
        ["主队均价", formatPrice(ahSummary.avg_home)],
        ["客队均价", formatPrice(ahSummary.avg_away)],
      ],
      buildTwoWayRows(asianHandicap.rows || [], "line", "home", "away", "主队", "客队", true),
    ),
    buildMarketCard(
      "大小球主线",
      overUnder.bookmaker_count || 0,
      [
        ["主线", overUnder.active_line != null ? Number(overUnder.active_line).toFixed(2) : "--"],
        ["倾向", sideText(ouSummary.lean)],
        ["大球均价", formatPrice(ouSummary.avg_over)],
        ["小球均价", formatPrice(ouSummary.avg_under)],
      ],
      buildTwoWayRows(overUnder.rows || [], "line", "over", "under", "大球", "小球", false),
    ),
  ];

  elements.relatedMarketsPanel.innerHTML = cards.join("");
}

function buildMarketCard(title, count, rows, detailTable = "") {
  return `
    <article class="market-summary-card">
      <div class="market-summary-head">
        <div>
          <div class="market-summary-title">${escapeHtml(title)}</div>
          <div class="market-summary-meta">赔率源 ${escapeHtml(String(count || 0))} 家</div>
        </div>
      </div>
      <div class="market-summary-body">
        ${rows
          .map(
            ([label, value]) => `
              <div class="market-summary-row">
                <span>${escapeHtml(label)}</span>
                <strong>${escapeHtml(value)}</strong>
              </div>
            `,
          )
          .join("")}
      </div>
      ${detailTable}
    </article>
  `;
}

function buildTwoWayRows(rows, lineKey, leftKey, rightKey, leftLabel, rightLabel, signedLine) {
  if (!rows.length) return "";
  return `
    <div class="market-mini-table">
      <div class="market-mini-head">${escapeHtml(leftLabel)} / ${escapeHtml(rightLabel)}</div>
      ${rows
        .slice(0, 5)
        .map(
          (row) => `
            <div class="market-mini-row">
              <span>${escapeHtml(row.name || "--")}</span>
              <span>${escapeHtml(row[lineKey] != null ? (signedLine ? formatLine(row[lineKey]) : Number(row[lineKey]).toFixed(2)) : "--")}</span>
              <span>${escapeHtml(row[leftKey] != null ? Number(row[leftKey]).toFixed(2) : "--")}</span>
              <span>${escapeHtml(row[rightKey] != null ? Number(row[rightKey]).toFixed(2) : "--")}</span>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function formatPrice(value) {
  if (value == null) return "--";
  return Number(value).toFixed(2);
}

function renderOddsChart(snapshot, timeseries) {
  if (!oddsChart) {
    renderChartFallback(oddsChartElement, "图表库未加载");
    elements.oddsCaption.textContent = "图表不可用";
    return;
  }

  const runnerMap = new Map();
  (snapshot.runners || []).forEach((runner) => {
    runnerMap.set(runner.selection_id, { name: runner.name, values: [] });
  });

  timeseries.forEach((point) => {
    (point.runners || []).forEach((runner) => {
      const series = runnerMap.get(runner.selection_id);
      const price = runner.price ?? runner.mid_price;
      if (series && price != null) {
        series.values.push([point.timestamp, Number(price)]);
      }
    });
  });

  elements.oddsCaption.textContent = (snapshot.runners || [])
    .map((runner) => `${runner.name} ${runner.price != null ? Number(runner.price).toFixed(2) : "--"}`)
    .join(" / ");

  oddsChart.setOption(
    {
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
    },
    true,
  );
}

function renderProbabilityChart(snapshot, timeseries) {
  if (!probabilityChart) {
    renderChartFallback(probabilityChartElement, "图表库未加载");
    elements.probabilityCaption.textContent = "图表不可用";
    return;
  }

  const runnerMap = new Map();
  (snapshot.runners || []).forEach((runner) => {
    runnerMap.set(runner.selection_id, { name: runner.name, values: [] });
  });

  timeseries.forEach((point) => {
    (point.runners || []).forEach((runner) => {
      const series = runnerMap.get(runner.selection_id);
      const price = runner.price ?? runner.mid_price;
      if (series && price != null && Number(price) > 0) {
        series.values.push([point.timestamp, Number((100 / Number(price)).toFixed(2))]);
      }
    });
  });

  elements.probabilityCaption.textContent = "按当前赔率换算出的隐含概率";
  probabilityChart.setOption(
    {
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
    },
    true,
  );
}

function initSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/market-stream`);

  socket.onmessage = async (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type !== "matches") return;

    state.matches = payload.matches || [];
    renderSystem(payload.system);

    if (!state.selectedMarketId && state.matches.length) {
      state.selectedMarketId = pickDefaultMarketId(state.matches);
    }
    if (state.selectedMarketId && !state.matches.some((match) => match.market_id === state.selectedMarketId)) {
      state.selectedMarketId = state.matches.length ? pickDefaultMarketId(state.matches) : null;
    }

    renderMatchList();
    renderMonitorTable();

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
    if (!chartsEnabled) {
      console.warn("ECharts failed to load; rendering without charts.");
    }
    await refreshMatches();
    initSocket();
  } catch (error) {
    console.error(error);
    elements.systemNotice.textContent = "启动失败，请检查本地服务是否已运行。";
    renderEmptyDashboard();
  }
}

elements.refreshButton.addEventListener("click", async () => {
  await refreshMatches();
});

window.addEventListener("resize", () => {
  if (oddsChart) oddsChart.resize();
  if (probabilityChart) probabilityChart.resize();
});

bootstrap();
