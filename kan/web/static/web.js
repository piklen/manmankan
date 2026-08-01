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
    window.location.href = kanSessionUrl("/compare");
  } else if (e.key === "4") {
    window.location.href = kanSessionUrl("/hold");
  } else if (e.key === "5") {
    window.location.href = kanSessionUrl("/settings");
  } else if (e.key === "r" || e.key === "R") {
    // R = 刷新数据（仅首页）
    if (path === "/") {
      const btn = document.getElementById("refresh-data-button");
      if (btn && !btn.disabled) btn.click();
    }
  } else if (e.key === "/") {
    // / = 聚焦添加自选输入框
    e.preventDefault();
    const input = document.getElementById("watchlist-codes");
    if (input) input.focus();
  } else if (e.key === "?") {
    // ? = 显示快捷键帮助
    kanShowShortcuts();
  } else if (e.key === "Escape") {
    var overlay = document.getElementById("kan-shortcuts-overlay");
    if (overlay) overlay.remove();
  }
});

function kanShowShortcuts() {
  var existing = document.getElementById("kan-shortcuts-overlay");
  if (existing) { existing.remove(); return; }
  var overlay = document.createElement("div");
  overlay.id = "kan-shortcuts-overlay";
  overlay.style.cssText = "position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.5);backdrop-filter:blur(2px);";
  overlay.innerHTML = '<div style="background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:24px 28px;max-width:360px;width:90%;box-shadow:var(--shadow-lg);">' +
    '<strong style="font-size:16px;">键盘快捷键</strong>' +
    '<table style="width:100%;margin-top:14px;border-collapse:collapse;font-size:14px;">' +
    '<tr><td style="padding:6px 0;color:var(--muted);">1 / 2 / 3 / 4 / 5</td><td>今日 / 找股票 / 对比 / 持仓 / 设置</td></tr>' +
    '<tr><td style="padding:6px 0;color:var(--muted);">D</td><td>切换深色模式</td></tr>' +
    '<tr><td style="padding:6px 0;color:var(--muted);">R</td><td>更新数据（首页）</td></tr>' +
    '<tr><td style="padding:6px 0;color:var(--muted);">/</td><td>聚焦添加自选</td></tr>' +
    '<tr><td style="padding:6px 0;color:var(--muted);">?</td><td>显示/关闭本帮助</td></tr>' +
    '<tr><td style="padding:6px 0;color:var(--muted);">Esc</td><td>关闭本帮助</td></tr>' +
    '</table>' +
    '<div style="margin-top:14px;text-align:center;"><button onclick="this.closest(\'#kan-shortcuts-overlay\').remove()" style="min-height:32px;padding:0 16px;border:1px solid var(--line);border-radius:6px;background:var(--panel);cursor:pointer;">关闭</button></div>' +
    '</div>';
  overlay.addEventListener("click", function(ev) { if (ev.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
}

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

// 全局搜索组件
function kanGlobalSearch() {
  return {
    query: "",
    results: [],
    open: false,
    searched: false,
    _timer: null,
    debounceSearch() {
      clearTimeout(this._timer);
      var self = this;
      var q = this.query.trim();
      if (!q) {
        this.results = [];
        this.open = false;
        this.searched = false;
        return;
      }
      this._timer = setTimeout(function() { self.doSearch(q); }, 200);
    },
    async doSearch(q) {
      try {
        var resp = await kanFetch(`/api/search?q=${encodeURIComponent(q)}`);
        var data = await resp.json();
        this.results = data.results || [];
        this.searched = true;
        this.open = true;
      } catch(_) {
        this.results = [];
        this.searched = true;
        this.open = true;
      }
    },
    goFirst() {
      if (this.results.length > 0) {
        window.location.href = kanSessionUrl(`/stock/${this.results[0].code}`);
      }
    }
  };
}

// 术语提示字典
var kanTermTips = {
  "位置百分位": "当前价格在过去 N 天最高价和最低价之间的位置。0% = 区间最低点，100% = 区间最高点。只描述坐标，不代表买卖信号。",
  "共振": "多个时间周期（如 30日、60日、180日）同时接近低位或高位。×N 表示有 N 个周期同时满足。",
  "量价方向": "今天成交量和价格变化的配合方向。如“放量上涨”表示成交量放大且价格上涨。",
  "换手率": "当天成交量占流通股总数的比例。换手率高表示交易活跃。",
  "PE TTM": "市盈率（滚动 12 个月）= 股价 / 每股收益。反映市场对公司盈利的估值水平。",
  "PB": "市净率 = 股价 / 每股净资产。反映市场对公司净资产的估值水平。",
  "股息率": "过去 12 个月分红 / 当前股价。反映持有股票的现金回报率。",
  "一手": "A 股最小交易单位 = 100 股。一手金额 = 现价 × 100。",
};

// 生成术语提示 HTML
function kanTip(term) {
  var tip = kanTermTips[term] || "";
  if (!tip) return term;
  return `<span class="term-tip">${term}<span class="tip-icon">?</span><span class="tip-content">${tip}</span></span>`;
}

function kanScanDesk(initialScan) {
  return {
    scan: initialScan,
    // 默认位置热力图:概览优先(首屏关键变化 + 分页图),数据表按需点开
    // 与首页设计文案「先看关键变化和极端位置,需要时再展开全部数据」对齐;
    // 此前默认 table 导致移动端首屏 193 行全表(~13000px)。
    activeTab: "heatmap",
    mode: "low",
    resonanceOnly: false,
    sortKey: "resonance",
    sortDir: "desc",
    heatmapPage: 0,
    heatmapPageSize: 60,
    chart: null,
    indexLoading: true,
    indexData: { ok: false, periods: [], rows: [] },
    marketData: { ok: false },
    fetching: false,
    fetchMessage: "",
    fetchProgress: 0,
    fetchStage: "准备",
    eventSource: null,
    addCodes: "",
    watchlistMessage: "",
    recentStocks: [],
    watchlistGroups: [],
    activeGroup: "",
    // 新手引导
    onboardStep: 1,
    showOnboarding: false,
    init() {
      this.recentStocks = kanRecent.get();
      this.loadIndex();
      this.loadMarket();
      this.loadGroups();
      // 新手引导：无自选、无持仓、无缓存数据时显示
      var onboarded = localStorage.getItem("kan-onboarded");
      var isNewUser = !onboarded && this.scan.stats.targets === 0 && this.scan.rows.length === 0;
      this.showOnboarding = isNewUser;
      // 不用 x-effect 渲染 heatmap:x-effect 会把 render 内部对 this.chart /
      // heatmapPage 的响应式读写也收进依赖,首次给 chart 赋值会重触发自身,
      // 上一帧渲染未完成时重复 setOption 直接抛 TypeError。
      // $watch 只盯 activeTab,依赖不扩散;首屏主动渲染一次。
      this.$watch("activeTab", (tab) => {
        if (tab === "heatmap") this.$nextTick(() => this.renderHeatmap());
      });
      if (this.activeTab === "heatmap") {
        // 首屏渲染等 window load 全资源就绪,避开 Alpine init 期的 DOM 动荡
        const firstRender = () => this.renderHeatmap();
        if (document.readyState === "complete") {
          requestAnimationFrame(firstRender);
        } else {
          window.addEventListener(
            "load", () => requestAnimationFrame(firstRender), { once: true },
          );
        }
      }
      window.addEventListener("resize", () => {
        clearTimeout(this._heatmapResizeTimer);
        this._heatmapResizeTimer = setTimeout(() => {
          if (this.chart && this.activeTab === "heatmap") this.chart.resize();
        }, 80);
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
    get positionChangeSummary() {
      const rows = this.scan.rows;
      if (!rows || rows.length === 0) return null;
      let up = 0, down = 0, flat = 0, hasData = false;
      for (const row of rows) {
        const change = row.p180_change;
        if (change === null || change === undefined) continue;
        hasData = true;
        if (change > 0) up++;
        else if (change < 0) down++;
        else flat++;
      }
      if (!hasData) return null;
      return { up, down, flat };
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
      // 渲染交给 init() 里的 $watch("activeTab"),这里只改状态,避免双渲染
      this.activeTab = tab;
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
      // kanLoadEcharts 是异步的 · 加载期间若又触发新渲染(翻页/排序/重进 tab),
      // 只让最新一次落地,丢弃过期回调,杜绝并发 setOption 赛跑
      const ticket = (this._renderTicket = (this._renderTicket || 0) + 1);
      kanLoadEcharts().then(() => {
        if (ticket !== this._renderTicket) return;
        this._doRenderHeatmap(el);
      });
    },
    _doRenderHeatmap(el) {
      // 首屏默认 heatmap 时,x-effect 可能在 x-show 生效前触发:
      // display:none 下 clientWidth=0,echarts.init(0 宽容器)渲染即抛
      // TypeError。等一帧布局完成再渲染。
      if (el.clientWidth === 0) {
        requestAnimationFrame(() => this._doRenderHeatmap(el));
        return;
      }
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
      } else {
        // 分页最后一页高度可能变化，先同步容器尺寸再更新模型。
        this.chart.resize({ width: el.clientWidth, height: el.clientHeight, silent: true });
      }
      this.chart.setOption({
        animation: false,
        grid: { left: 128, right: 24, top: 24, bottom: 58 },
        tooltip: {
          // 显式 item 触发 + 关 axisPointer:默认轴触发在首帧轴未就绪时
          // 会走 getAxesOnZeroOf 抛 TypeError;热力图格子本就该按 item 触发
          trigger: "item",
          axisPointer: { type: "none" },
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
      }, { notMerge: true, lazyUpdate: false, silent: true });
      // lazyUpdate 会把轴模型提交推迟到下一帧；首屏 resize 恰好落在中间时，
      // ECharts 5.6 会读取尚未挂载的轴并抛 getAxesOnZeroOf。这里的数据量只有
      // 60×周期数，同步整批更新更快，也消除了需要反复自愈的竞态窗口。
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
    async loadMarket() {
      try {
        const response = await kanFetch("/api/market");
        this.marketData = response.ok ? await response.json() : { ok: false };
      } catch (_error) {
        this.marketData = { ok: false };
      }
    },
    async loadGroups() {
      try {
        const response = await kanFetch("/api/watchlist/groups");
        const data = response.ok ? await response.json() : { ok: false, groups: [] };
        this.watchlistGroups = data.groups || [];
      } catch (_error) {
        this.watchlistGroups = [];
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
        this.fetchStage = data.stage || "准备";
        this.fetchProgress = total > 0 ? Math.round(data.completed / total * 100) : 0;
        if (data.status === "done") {
          this.eventSource.close();
          const reloaded = await this.reloadScan();
          this.fetching = false;
          this.fetchProgress = 100;
          this.fetchMessage = reloaded
            ? (data.stage || "更新完成")
            : `${data.stage || "更新完成"} · 页面刷新失败，请手动刷新`;
          if (this.watchlistMessage.includes("正在更新行情")) {
            this.watchlistMessage = reloaded
              ? "已添加并更新行情"
              : "已添加，行情更新完成 · 请手动刷新页面";
          }
          kanToast(reloaded ? "数据更新完成" : "更新完成，请手动刷新页面");
        }
        if (data.status === "partial") {
          this.eventSource.close();
          const reloaded = await this.reloadScan();
          this.fetching = false;
          const message = data.error || data.stage || "部分股票未更新 · 可重试";
          this.fetchMessage = reloaded ? message : `${message} · 请手动刷新页面`;
          if (this.watchlistMessage.includes("正在更新行情")) {
            this.watchlistMessage = `已添加 · ${message}`;
          }
          kanToast(message, "error");
        }
        if (data.status === "error") {
          this.eventSource.close();
          this.fetching = false;
          this.fetchMessage = data.error || "数据不可用";
          if (this.watchlistMessage.includes("正在更新行情")) {
            this.watchlistMessage = `已添加 · ${this.fetchMessage}`;
          }
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
    dismissOnboarding() {
      this.showOnboarding = false;
      localStorage.setItem("kan-onboarded", "1");
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
    exportCsv() {
      const rows = this.sortedRows;
      if (rows.length === 0) { kanToast("没有可导出的数据", "error"); return; }
      const periods = this.scan.periods;
      const header = ["代码", "名称", "现价", ...periods.map((p) => `${p}日位置%`), "低点共振", "高点共振"];
      const lines = [header.join(",")];
      for (const row of rows) {
        const cols = [
          row.code,
          `"${row.name}"`,
          row.price !== null ? row.price : "",
          ...periods.map((p) => { const v = row[`p${p}_pct`]; return v !== null && v !== undefined ? v : ""; }),
          row.low_resonance,
          row.high_resonance,
        ];
        lines.push(cols.join(","));
      }
      const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `慢慢看_位置扫描_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      kanToast(`已导出 ${rows.length} 只股票数据`);
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
    init() {
      // 渲染不在 x-effect 里做:x-effect 会把 renderPie 内部对 pieChart 的
      // 响应式读写也收进依赖,首次赋值即重触发自身造成双渲染(同首页
      // heatmap 的教训)。$watch 只盯行数,依赖不扩散。
      this.$watch("hold.rows.length", (n) => {
        if (n > 1) this.$nextTick(() => this.renderPie());
      });
      if (this.hold.rows.length > 1) this.$nextTick(() => this.renderPie());
    },
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
    exportHoldCsv() {
      const rows = this.hold.rows;
      if (!rows || rows.length === 0) { kanToast("没有可导出的持仓数据", "error"); return; }
      const header = ["代码", "名称", "成本", "股数", "现价", "今日盈亏", "今日盈亏%", "累计盈亏", "累计盈亏%", "仓位%", "30日位置%", "60日位置%", "180日位置%", "回本价", "距回本%", "位置预警"];
      const lines = [header.join(",")];
      for (const row of rows) {
        const cols = [
          row.code,
          `"${row.name}"`,
          row.cost,
          row.shares,
          row.price !== null ? row.price : "",
          row.daily_pnl !== null ? row.daily_pnl : "",
          row.daily_pnl_pct !== null ? row.daily_pnl_pct : "",
          row.total_pnl !== null ? row.total_pnl : "",
          row.total_pnl_pct !== null ? row.total_pnl_pct : "",
          row.weight_pct !== null ? row.weight_pct : "",
          row.p30_pct !== null ? row.p30_pct : "",
          row.p60_pct !== null ? row.p60_pct : "",
          row.p180_pct !== null ? row.p180_pct : "",
          row.breakeven_price !== null ? row.breakeven_price : "",
          row.distance_to_breakeven !== null ? row.distance_to_breakeven : "",
          row.position_alert === "high" ? "高位" : row.position_alert === "low" ? "低位" : "",
        ];
        lines.push(cols.join(","));
      }
      const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `慢慢看_持仓_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      kanToast(`已导出 ${rows.length} 只持仓数据`);
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
    watchlistMsg: info.in_watchlist ? "已在自选 ✓" : "加入自选",
    // K 线图状态
    klineDays: 120,
    klineChart: null,
    klineReady: false,
    klineMessage: "K 线数据加载中",
    // 一手计算器
    cashAmount: 0,
    init() {
      // 记录最近浏览
      kanRecent.add(info.code, info.name);
      this.loadHistory();
      this.loadKline();
      this.loadCash();
      window.addEventListener("resize", () => {
        clearTimeout(this._resizeTimer);
        this._resizeTimer = setTimeout(() => {
          if (this.chart) this.chart.resize();
          if (this.klineChart) this.klineChart.resize();
        }, 80);
      });
    },
    get lotAmount() {
      if (!this.info.price) return "—";
      return "¥" + (this.info.price * 100).toLocaleString("zh-CN", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
    },
    get lotPctOfCash() {
      if (!this.info.price || this.cashAmount <= 0) return "—";
      const pct = (this.info.price * 100 / this.cashAmount * 100).toFixed(1);
      return pct + "%";
    },
    get distanceToHigh() {
      const p180 = this.info.periods?.find(p => p.period === 180);
      if (!p180 || p180.distance_to_high_pct === null || p180.distance_to_high_pct === undefined) return "—";
      return Math.abs(p180.distance_to_high_pct).toFixed(1) + "%";
    },
    get distanceToLow() {
      const p180 = this.info.periods?.find(p => p.period === 180);
      if (!p180 || p180.distance_to_low_pct === null || p180.distance_to_low_pct === undefined) return "—";
      return Math.abs(p180.distance_to_low_pct).toFixed(1) + "%";
    },
    formatMoney(value) {
      if (value === null || value === undefined) return "—";
      return "¥" + Number(value).toLocaleString("zh-CN", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      });
    },
    async loadCash() {
      try {
        const resp = await kanFetch("/api/hold");
        const data = await resp.json();
        if (data.ok && data.account) {
          this.cashAmount = data.account.cash || 0;
        }
      } catch(_) {}
    },
    async addToWatchlist() {
      if (this.info.in_watchlist) return;
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
        this.info.in_watchlist = true;
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
        this._lastSeries = series;
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
        }, { notMerge: true, lazyUpdate: false, silent: true });
      });
    },
    exportHistoryCsv() {
      if (!this._lastSeries || this._lastSeries.length === 0) {
        kanToast("暂无可导出的历史数据", "error");
        return;
      }
      const header = ["日期", `${this.period}日位置%`];
      const lines = [header.join(",")];
      for (const item of this._lastSeries) {
        lines.push(`${item.date},${item.position_pct !== null ? item.position_pct : ""}`);
      }
      const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `慢慢看_${this.info.code}_${this.period}日位置历史.csv`;
      a.click();
      URL.revokeObjectURL(url);
      kanToast(`已导出 ${this._lastSeries.length} 条位置历史`);
    },
    setKlineDays(days) {
      this.klineDays = days;
      this.loadKline();
    },
    async loadKline() {
      this.klineReady = false;
      this.klineMessage = "K 线数据加载中";
      try {
        const response = await kanFetch(`/api/kline/${this.info.code}?days=${this.klineDays}`);
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          this.klineMessage = payload.detail || "本地没有 K 线缓存，请先在首页更新数据";
          return;
        }
        const payload = await response.json();
        if (!payload.rows || payload.rows.length === 0) {
          this.klineMessage = "本地没有 K 线缓存，请先在首页更新数据";
          return;
        }
        this.klineReady = true;
        this.$nextTick(() => this.renderKline(payload.rows));
      } catch (_error) {
        this.klineMessage = "本地没有 K 线缓存，请先在首页更新数据";
      }
    },
    renderKline(rows) {
      const el = document.getElementById("kline-chart");
      if (!el) return;
      kanLoadEcharts().then(() => {
        if (!this.klineChart) this.klineChart = echarts.init(el);
        const dates = rows.map(r => r.date);
        const ohlc = rows.map(r => [r.open, r.close, r.low, r.high]);
        const volumes = rows.map(r => r.volume);
        const isDark = document.documentElement.getAttribute("data-theme") === "dark";
        const upColor = isDark ? "#f87171" : "#dc2626";
        const downColor = isDark ? "#34d399" : "#059669";
        this.klineChart.setOption({
          animation: false,
          tooltip: {
            trigger: "axis",
            axisPointer: { type: "cross" },
          },
          grid: [
            { left: 60, right: 20, top: 20, height: "55%" },
            { left: 60, right: 20, top: "72%", height: "18%" },
          ],
          xAxis: [
            { type: "category", data: dates, gridIndex: 0, axisLabel: { show: false } },
            { type: "category", data: dates, gridIndex: 1 },
          ],
          yAxis: [
            { scale: true, gridIndex: 0, splitLine: { lineStyle: { opacity: 0.3 } } },
            { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false } },
          ],
          dataZoom: [
            { type: "inside", xAxisIndex: [0, 1], start: 50, end: 100 },
          ],
          series: [
            {
              name: "K线",
              type: "candlestick",
              data: ohlc,
              xAxisIndex: 0,
              yAxisIndex: 0,
              itemStyle: {
                color: upColor,
                color0: downColor,
                borderColor: upColor,
                borderColor0: downColor,
              },
            },
            {
              name: "成交量",
              type: "bar",
              data: volumes,
              xAxisIndex: 1,
              yAxisIndex: 1,
              itemStyle: {
                color: function(params) {
                  const row = rows[params.dataIndex];
                  return row.close >= row.open ? upColor : downColor;
                },
              },
            },
          ],
        }, { notMerge: true, lazyUpdate: false, silent: true });
      });
    },
  };
}

function kanMissingStock(code) {
  return {
    loading: false,
    message: "",
    async load() {
      this.loading = true;
      this.message = "正在拉取行情";
      try {
        const response = await kanFetch(`/api/info/${encodeURIComponent(code)}/refresh`, {
          method: "POST",
          headers: { "X-Kan-Web": "1" },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          this.message = payload.detail || "行情加载失败";
          return;
        }
        this.message = "行情已加载，正在打开";
        window.location.reload();
      } catch (_error) {
        this.message = "行情加载失败，请检查网络后重试";
      } finally {
        this.loading = false;
      }
    },
  };
}
