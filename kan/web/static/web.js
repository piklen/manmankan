// 主题切换
function kanToggleTheme() {
  const html = document.documentElement;
  const isDark = html.getAttribute("data-theme") === "dark";
  if (isDark) {
    html.removeAttribute("data-theme");
    localStorage.setItem("kan-theme", "light");
  } else {
    html.setAttribute("data-theme", "dark");
    localStorage.setItem("kan-theme", "dark");
  }
}

// 全局键盘快捷键
document.addEventListener("keydown", function(e) {
  // 输入框内不触发
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
  const path = window.location.pathname;
  if (e.key === "d" || e.key === "D") {
    // D = 切换深色模式
    kanToggleTheme();
  } else if (e.key === "1") {
    window.location.href = kanSessionUrl("/");
  } else if (e.key === "2") {
    window.location.href = kanSessionUrl("/find");
  } else if (e.key === "3") {
    window.location.href = kanSessionUrl("/hold");
  } else if (e.key === "4") {
    window.location.href = kanSessionUrl("/settings");
  } else if (e.key === "r" || e.key === "R") {
    // R = 刷新数据（仅首页）
    if (path === "/") {
      const btn = document.querySelector("[x-data] button.primary");
      if (btn && !btn.disabled) btn.click();
    }
  } else if (e.key === "/") {
    // / = 聚焦添加自选输入框
    e.preventDefault();
    const input = document.getElementById("watchlist-codes");
    if (input) input.focus();
  }
});

// 最近浏览记录（localStorage，最多 8 只）
var kanRecent = {
  KEY: "kan-recent-stocks",
  get: function() {
    try { return JSON.parse(localStorage.getItem(this.KEY) || "[]"); } catch(_) { return []; }
  },
  add: function(code, name) {
    var list = this.get().filter(function(item) { return item.code !== code; });
    list.unshift({ code: code, name: name || code, time: Date.now() });
    if (list.length > 8) list = list.slice(0, 8);
    localStorage.setItem(this.KEY, JSON.stringify(list));
  },
};

// 轻量 toast 通知
function kanToast(message, type) {
  var container = document.getElementById("kan-toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "kan-toast-container";
    container.style.cssText = "position:fixed;top:16px;right:16px;z-index:9999;display:grid;gap:8px;pointer-events:none;";
    document.body.appendChild(container);
  }
  var toast = document.createElement("div");
  var bg = type === "error" ? "var(--high)" : "var(--accent)";
  toast.style.cssText = "padding:10px 16px;border-radius:8px;background:" + bg + ";color:#fff;font-size:14px;box-shadow:0 4px 12px rgba(0,0,0,.15);opacity:0;transform:translateX(20px);transition:all .3s ease;max-width:320px;";
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(function() {
    toast.style.opacity = "1";
    toast.style.transform = "translateX(0)";
  });
  setTimeout(function() {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(20px)";
    setTimeout(function() { toast.remove(); }, 300);
  }, 3000);
}

function kanScanDesk(initialScan) {
  return {
    scan: initialScan,
    activeTab: "table",
    mode: "low",
    resonanceOnly: false,
    sortKey: "resonance",
    sortDir: "desc",
    heatmapPage: 0,
    heatmapPageSize: 60,
    chart: null,
    indexLoading: true,
    indexData: { ok: false, periods: [], rows: [] },
    fetching: false,
    fetchMessage: "",
    eventSource: null,
    addCodes: "",
    watchlistMessage: "",
    recentStocks: [],
    init() {
      this.recentStocks = kanRecent.get();
      this.loadIndex();
      window.addEventListener("resize", () => {
        if (this.chart) this.chart.resize();
      });
    },
    get positionDistribution() {
      // 按 180 日位置分布统计：低位(0-20) / 中位(20-80) / 高位(80-100)
      const rows = this.scan.rows;
      if (!rows || rows.length === 0) return null;
      let low = 0, mid = 0, high = 0, na = 0;
      for (const row of rows) {
        const pct = row.p180_pct;
        if (pct === null || pct === undefined) { na++; continue; }
        if (pct <= 20) low++;
        else if (pct >= 80) high++;
        else mid++;
      }
      const total = rows.length - na;
      if (total === 0) return null;
      return { low, mid, high, total };
    },
    get sortedRows() {
      const rows = this.scan.rows.filter((row) => !this.resonanceOnly || this.resonance(row) > 0);
      const direction = this.sortDir === "desc" ? -1 : 1;
      return rows.slice().sort((a, b) => {
        const av = this.sortValue(a);
        const bv = this.sortValue(b);
        if (av === bv) return a.code.localeCompare(b.code);
        if (av === null) return 1;
        if (bv === null) return -1;
        return av > bv ? direction : -direction;
      });
    },
    get heatmapPageCount() {
      return Math.max(1, Math.ceil(this.sortedRows.length / this.heatmapPageSize));
    },
    get heatmapPageText() {
      return `${this.heatmapPage + 1}/${this.heatmapPageCount}`;
    },
    setTab(tab) {
      this.activeTab = tab;
      if (tab === "heatmap") this.$nextTick(() => this.renderHeatmap());
    },
    toggleSortDir() {
      this.sortDir = this.sortDir === "desc" ? "asc" : "desc";
      this.heatmapPage = 0;
      this.$nextTick(() => this.renderHeatmap());
    },
    sortValue(row) {
      if (this.sortKey === "resonance") return this.resonance(row);
      const period = Number(this.sortKey.slice(1));
      return this.periodPct(row, period);
    },
    resonance(row) {
      return this.mode === "high" ? row.high_resonance : row.low_resonance;
    },
    periodPct(row, period) {
      const value = row[`p${period}_pct`];
      return value === undefined ? null : value;
    },
    periodClass(row, period) {
      const pct = this.periodPct(row, period);
      const classes = [];
      if (pct !== null && pct <= 20) classes.push("pct-low");
      if (pct !== null && pct >= 80) classes.push("pct-high");
      if (row[`p${period}_at_low`] || row[`p${period}_at_high`]) classes.push("pct-extreme");
      return classes.join(" ");
    },
    formatPct(value) {
      return value === null ? "—" : `${Number(value).toFixed(1)}%`;
    },
    formatPrice(value) {
      return value === null ? "—" : Number(value).toFixed(2);
    },
    openStock(code) {
      window.location.href = kanSessionUrl(`/stock/${code}`);
    },
    prevHeatmapPage() {
      if (this.heatmapPage > 0) {
        this.heatmapPage -= 1;
        this.$nextTick(() => this.renderHeatmap());
      }
    },
    nextHeatmapPage() {
      if (this.heatmapPage < this.heatmapPageCount - 1) {
        this.heatmapPage += 1;
        this.$nextTick(() => this.renderHeatmap());
      }
    },
    renderHeatmap() {
      if (this.activeTab !== "heatmap") return;
      const el = document.getElementById("scan-heatmap");
      if (!el) return;
      kanLoadEcharts().then(() => {
        this._doRenderHeatmap(el);
      });
    },
    _doRenderHeatmap(el) {
      if (this.heatmapPage >= this.heatmapPageCount) this.heatmapPage = this.heatmapPageCount - 1;
      const start = this.heatmapPage * this.heatmapPageSize;
      const rows = this.sortedRows.slice(start, start + this.heatmapPageSize);
      el.style.height = `${Math.max(320, rows.length * 14 + 110)}px`;
      const names = rows.map((row) => `${row.name} ${row.code}`);
      const codes = new Set(rows.map((row) => row.code));
      const periods = this.scan.periods;
      const cells = this.scan.heatmap
        .filter((cell) => codes.has(cell.code) && cell.position_pct !== null)
        .map((cell) => [
          periods.indexOf(cell.period),
          rows.findIndex((row) => row.code === cell.code),
          Number(cell.position_pct),
          cell.code,
        ])
        .filter((cell) => cell[0] >= 0 && cell[1] >= 0);
      if (!this.chart) {
        this.chart = echarts.init(el);
        this.chart.on("click", (params) => {
          const code = params.value && params.value[3];
          if (code) this.openStock(code);
        });
      }
      this.chart.setOption({
        grid: { left: 128, right: 24, top: 24, bottom: 58 },
        tooltip: {
          formatter(params) {
            const period = periods[params.value[0]];
            const name = names[params.value[1]];
            return `${name}<br>${period}日 · ${params.value[2].toFixed(1)}%`;
          },
        },
        xAxis: { type: "category", data: periods.map((period) => `${period}日`) },
        yAxis: { type: "category", data: names },
        visualMap: {
          min: 0,
          max: 100,
          // 数据项是 [周期, 行, 位置%, 代码] 四维;不显式指定维度时
          // ECharts 默认取最后一维(代码字符串)做颜色映射,会整行染错色
          dimension: 2,
          calculable: false,
          orient: "horizontal",
          left: "center",
          bottom: 12,
          text: ["100=N日最高", "0=N日最低"],
          inRange: { color: ["#047857", "#f8fafc", "#b42318"] },
        },
        series: [{ type: "heatmap", data: cells }],
      });
      this.chart.resize();
    },
    async loadIndex() {
      this.indexLoading = true;
      try {
        const response = await kanFetch("/api/index");
        this.indexData = response.ok ? await response.json() : { ok: false, periods: [], rows: [] };
      } catch (_error) {
        this.indexData = { ok: false, periods: [], rows: [] };
      } finally {
        this.indexLoading = false;
      }
    },
    indexPct(row, period) {
      const item = row.periods[String(period)];
      return item ? item.position_pct : null;
    },
    async startFetch() {
      this.fetching = true;
      this.fetchMessage = "准备";
      let listening = false;
      try {
        const response = await kanFetch("/api/fetch", {
          method: "POST",
          headers: { "X-Kan-Web": "1" },
        });
        if (!response.ok) {
          this.fetchMessage = "数据不可用";
          return;
        }
        const payload = await response.json();
        this.listenFetch(payload.job);
        listening = true;
      } catch (_error) {
        this.fetchMessage = "数据不可用";
      } finally {
        if (!listening) this.fetching = false;
      }
    },
    listenFetch(job) {
      if (this.eventSource) this.eventSource.close();
      this.eventSource = new EventSource(
        kanSessionUrl(`/api/fetch/events?job=${encodeURIComponent(job)}`),
      );
      this.eventSource.addEventListener("progress", async (event) => {
        const data = JSON.parse(event.data);
        const total = data.total || 0;
        this.fetchMessage = total ? `${data.stage} ${data.completed}/${total}` : data.stage;
        if (data.status === "done") {
          this.eventSource.close();
          const reloaded = await this.reloadScan();
          this.fetching = false;
          this.fetchMessage = reloaded
            ? (data.stage || "更新完成")
            : `${data.stage || "更新完成"} · 页面刷新失败，请手动刷新`;
          kanToast(reloaded ? "数据更新完成" : "更新完成，请手动刷新页面");
        }
        if (data.status === "partial") {
          this.eventSource.close();
          const reloaded = await this.reloadScan();
          this.fetching = false;
          const message = data.error || data.stage || "部分股票未更新 · 可重试";
          this.fetchMessage = reloaded ? message : `${message} · 请手动刷新页面`;
          kanToast(message, "error");
        }
        if (data.status === "error") {
          this.eventSource.close();
          this.fetching = false;
          this.fetchMessage = data.error || "数据不可用";
          kanToast(data.error || "数据更新失败", "error");
        }
      });
      this.eventSource.onerror = () => {
        this.fetching = false;
        this.fetchMessage = "进度连接中断";
        this.eventSource.close();
      };
    },
    async reloadScan() {
      try {
        const response = await kanFetch("/api/scan");
        if (!response.ok) return false;
        this.scan = await response.json();
        this.heatmapPage = 0;
        this.$nextTick(() => this.renderHeatmap());
        return true;
      } catch (_error) {
        return false;
      }
    },
    async addWatchlist() {
      this.watchlistMessage = "添加中";
      try {
        const response = await kanFetch("/api/watchlist", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Kan-Web": "1",
          },
          body: JSON.stringify({ codes: this.addCodes }),
        });
        const payload = await response.json();
        if (!response.ok) {
          this.watchlistMessage = payload.detail || "添加失败";
          kanToast(payload.detail || "添加失败", "error");
          return;
        }
        this.addCodes = "";
        this.watchlistMessage = `${(payload.messages || []).join(" · ") || "已添加"} · 正在更新行情`;
        kanToast((payload.messages || []).join(" · ") || "已添加自选");
        await this.startFetch();
      } catch (_error) {
        this.watchlistMessage = "添加失败";
        kanToast("添加失败", "error");
      }
    },
    async removeWatchlist(code) {
      if (!window.confirm(`确认移除自选 ${code}？`)) return;
      this.watchlistMessage = "移除中";
      try {
        const response = await kanFetch(`/api/watchlist/${encodeURIComponent(code)}`, {
          method: "DELETE",
          headers: { "X-Kan-Web": "1" },
        });
        const payload = await response.json();
        if (!response.ok) {
          this.watchlistMessage = payload.detail || "移除失败";
          kanToast(payload.detail || "移除失败", "error");
          return;
        }
        this.watchlistMessage = payload.message || "已移除";
        kanToast(payload.message || `已移除 ${code}`);
        await this.reloadScan();
      } catch (_error) {
        this.watchlistMessage = "移除失败";
        kanToast("移除失败", "error");
      }
    },
  };
}

function kanHoldPage(initialHold) {
  return {
    hold: initialHold,
    masked: false,
    cashInput: initialHold.account.cash === null ? "" : String(initialHold.account.cash),
    positionForm: { code: "", cost: "", shares: "" },
    editingCode: null,
    saving: false,
    message: "",
    pieChart: null,
    renderPie() {
      const el = document.getElementById("hold-pie");
      if (!el || this.hold.rows.length < 2) return;
      kanLoadEcharts().then(() => {
        if (!this.pieChart) this.pieChart = echarts.init(el);
        const data = this.hold.rows.map((row) => ({
          name: `${row.name} ${row.code}`,
          value: row.market_value || 0,
        }));
        if (this.hold.account.cash > 0) {
          data.push({ name: "现金", value: this.hold.account.cash });
        }
        this.pieChart.setOption({
          tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
          series: [{
            type: "pie",
            radius: ["40%", "70%"],
            avoidLabelOverlap: true,
            itemStyle: { borderRadius: 6, borderColor: "var(--panel)", borderWidth: 2 },
            label: { show: true, fontSize: 12 },
            data,
          }],
        });
        this.pieChart.resize();
      });
    },
    formatMoney(value) {
      if (this.masked && value !== null) return "***";
      return value === null ? "—" : Number(value).toLocaleString("zh-CN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    },
    formatCost(value) {
      if (this.masked && value !== null) return "***";
      if (value === null) return "—";
      // 与 CLI 同为最多 4 位小数(摊薄成本精度),但去掉尾随零免得整数成本显示成 x.0000
      return String(Number(Number(value).toFixed(4)));
    },
    formatPrice(value) {
      return value === null ? "—" : Number(value).toFixed(2);
    },
    formatInt(value) {
      return value === null ? "—" : String(value);
    },
    formatPct(value) {
      return value === null ? "—" : `${Number(value).toFixed(1)}%`;
    },
    formatPnl(value, pct) {
      if (value === null) return "—";
      const pctText = pct === null ? "" : ` (${Number(pct).toFixed(2)}%)`;
      if (this.masked) return `***${pctText}`;
      const sign = value > 0 ? "+" : "";
      return `${sign}${this.formatMoney(value)}${pctText}`;
    },
    pnlClass(value) {
      if (value === null || value === 0) return "";
      return value > 0 ? "change-up" : "change-down";
    },
    positionClass(value) {
      if (value === null) return "";
      if (value <= 20) return "pct-low";
      if (value >= 80) return "pct-high";
      return "";
    },
    async saveCash() {
      await this.mutate("/api/positions/cash", "POST", { cash: this.cashInput });
    },
    async submitPosition() {
      const editing = Boolean(this.editingCode);
      const url = editing
        ? `/api/positions/${encodeURIComponent(this.editingCode)}`
        : "/api/positions";
      const method = editing ? "PUT" : "POST";
      const ok = await this.mutate(url, method, {
        code: this.positionForm.code,
        cost: this.positionForm.cost,
        shares: this.positionForm.shares,
      });
      if (ok) this.cancelEdit();
    },
    startEdit(row) {
      this.editingCode = row.code;
      this.positionForm = {
        code: row.code,
        cost: String(row.cost),
        shares: String(row.shares),
      };
      document.getElementById("hold-cost")?.focus();
    },
    cancelEdit() {
      this.editingCode = null;
      this.positionForm = { code: "", cost: "", shares: "" };
    },
    async removePosition(row) {
      if (!window.confirm(`确认删除 ${row.name} ${row.code} 的持仓记录？`)) return;
      await this.mutate(`/api/positions/${encodeURIComponent(row.code)}`, "DELETE");
    },
    async mutate(url, method, body = null) {
      this.saving = true;
      this.message = "保存中";
      try {
        const options = {
          method,
          headers: { "X-Kan-Web": "1" },
        };
        if (body !== null) {
          options.headers["Content-Type"] = "application/json";
          options.body = JSON.stringify(body);
        }
        const response = await kanFetch(url, options);
        const payload = await response.json();
        if (!response.ok) {
          this.message = payload.detail || payload.error || "保存失败";
          return false;
        }
        this.message = payload.message || "已保存";
        const reloaded = await this.reloadHold();
        if (!reloaded) {
          this.message = `${payload.message || "已保存"}，但页面刷新失败 · 请手动刷新确认`;
        }
        return true;
      } catch (_error) {
        this.message = "保存失败，请稍后重试";
        return false;
      } finally {
        this.saving = false;
      }
    },
    async reloadHold() {
      try {
        const response = await kanFetch("/api/hold");
        if (!response.ok) return false;
        const payload = await response.json();
        if (!payload.ok) return false;
        this.hold = payload;
        this.cashInput = this.hold.account.cash === null ? "" : String(this.hold.account.cash);
        return true;
      } catch (_error) {
        return false;
      }
    },
  };
}

function kanSettingsPage(initialToken) {
  return {
    token: initialToken,
    tokenInput: "",
    message: "",
    get tokenText() {
      return this.token.configured ? `已配置 ${this.token.masked}` : "未配置";
    },
    async saveToken() {
      this.message = "保存中";
      try {
        const response = await kanFetch("/api/config/token", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Kan-Web": "1",
          },
          body: JSON.stringify({ token: this.tokenInput }),
        });
        if (!response.ok) {
          this.message = "保存失败";
          return;
        }
        this.token = await response.json();
        this.tokenInput = "";
        this.message = "已保存";
      } catch (_error) {
        this.message = "保存失败";
      }
    },
    async clearToken() {
      this.message = "清除中";
      try {
        const response = await kanFetch("/api/config/token", {
          method: "DELETE",
          headers: { "X-Kan-Web": "1" },
        });
        if (!response.ok) {
          this.message = "清除失败";
          return;
        }
        this.token = await response.json();
        this.message = "已清除";
      } catch (_error) {
        this.message = "清除失败";
      }
    },
  };
}

function kanStockPage(info) {
  return {
    info,
    // 默认 30 日:与 CLI history 默认一致,每日快照最常见的记录周期,避免首屏空态
    period: 30,
    chart: null,
    historyReady: false,
    historyMessage: "该周期暂无足够历史 · 可切换周期，或在不同交易日多次更新数据后再看",
    watchlistMsg: "加入自选",
    init() {
      // 记录最近浏览
      kanRecent.add(info.code, info.name);
      this.loadHistory();
      window.addEventListener("resize", () => {
        if (this.chart) this.chart.resize();
      });
    },
    async addToWatchlist() {
      this.watchlistMsg = "添加中";
      try {
        const response = await kanFetch("/api/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Kan-Web": "1" },
          body: JSON.stringify({ codes: this.info.code }),
        });
        const payload = await response.json();
        if (!response.ok) {
          this.watchlistMsg = payload.detail || "添加失败";
          kanToast(payload.detail || "添加失败", "error");
          return;
        }
        this.watchlistMsg = "已在自选 ✓";
        kanToast(`${this.info.name} 已加入自选`);
      } catch (_error) {
        this.watchlistMsg = "添加失败";
        kanToast("添加失败", "error");
      }
    },
    setPeriod(period) {
      this.period = period;
      this.loadHistory();
    },
    async loadHistory() {
      this.historyReady = false;
      this.historyMessage = "读取本地快照";
      try {
        const response = await kanFetch(`/api/history/${this.info.code}?period=${this.period}`);
        if (!response.ok) {
          this.historyMessage = "该周期暂无足够历史 · 可切换周期，或在不同交易日多次更新数据后再看";
          return;
        }
        const payload = await response.json();
        const series = payload.series.filter((item) => item.position_pct !== null);
        if (series.length === 0) {
          this.historyMessage = "该周期暂无足够历史 · 可切换周期，或在不同交易日多次更新数据后再看";
          return;
        }
        this.historyReady = true;
        this.$nextTick(() => this.renderHistory(series));
      } catch (_error) {
        this.historyMessage = "该周期暂无足够历史 · 可切换周期，或在不同交易日多次更新数据后再看";
      }
    },
    renderHistory(series) {
      const el = document.getElementById("history-chart");
      if (!el) return;
      kanLoadEcharts().then(() => {
        if (!this.chart) this.chart = echarts.init(el);
        this.chart.setOption({
          grid: { left: 48, right: 24, top: 24, bottom: 40 },
          tooltip: { trigger: "axis" },
          xAxis: { type: "category", data: series.map((item) => item.date) },
          yAxis: { type: "value", min: 0, max: 100, axisLabel: { formatter: "{value}%" } },
          series: [{
            type: "line",
            smooth: false,
            showSymbol: false,
            data: series.map((item) => item.position_pct),
          }],
        });
        this.chart.resize();
      });
    },
  };
}
