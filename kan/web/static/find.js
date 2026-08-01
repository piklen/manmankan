function kanFindPage() {
  return {
    pool: { type: "watchlist", value: "" },
    filters: [],
    filterOptions: window.KAN_FIND_FILTERS || [],
    maxFilters: window.KAN_FIND_MAX_FILTERS || 12,
    matchMode: "all",
    excludeSt: false,
    loading: false,
    message: "",
    copyMessage: "",
    result: null,
    nextId: 1,
    batchMsg: "本页加入自选",
    // 排序
    sortKey: "",
    sortDir: "desc",
    page: 1,
    pageSize: 50,
    get resultPeriods() {
      return this.result ? this.result.periods : [];
    },
    get filterSpecs() {
      return Object.fromEntries(this.filterOptions.map((item) => [item.type, item]));
    },
    get sortOptions() {
      const options = [{ key: "price", label: "现价" }];
      for (const period of this.resultPeriods) {
        options.push({ key: `position:${period}`, label: `${period}日位置` });
      }
      for (const filter of this.validFilters()) {
        const key = this.sortKeyForFilter(filter);
        const spec = this.filterSpecs[filter.type];
        if (key && spec && !options.some((item) => item.key === key)) {
          const prefix = this.needsPeriod(filter) ? `${filter.period}日` : "";
          options.push({ key, label: `${prefix}${spec.label}` });
        }
      }
      return options;
    },
    get sortedRows() {
      if (!this.result || !this.result.rows) return [];
      var rows = [...this.result.rows];
      if (this.sortKey) {
        var dir = this.sortDir === "desc" ? -1 : 1;
        var key = this.sortKey;
        var sortValue = this.sortValue.bind(this);
        rows.sort(function(a, b) {
          var va = sortValue(a, key), vb = sortValue(b, key);
          var aMissing = va === null || va === undefined;
          var bMissing = vb === null || vb === undefined;
          if (aMissing && bMissing) return 0;
          if (aMissing) return 1;
          if (bMissing) return -1;
          return (va - vb) * dir;
        });
      }
      const start = (this.page - 1) * this.pageSize;
      return rows.slice(start, start + this.pageSize);
    },
    get totalPages() {
      if (!this.result || !this.result.rows) return 1;
      return Math.max(1, Math.ceil(this.result.rows.length / this.pageSize));
    },
    get pageStart() {
      if (!this.result || this.result.rows.length === 0) return 0;
      return (this.page - 1) * this.pageSize + 1;
    },
    get pageEnd() {
      if (!this.result) return 0;
      return Math.min(this.page * this.pageSize, this.result.rows.length);
    },
    get resultSummary() {
      if (!this.result) return "";
      var text = `命中 ${this.result.stats.matched} 只`;
      if (this.result.rows.length > this.pageSize) {
        text += ` · ${this.totalPages} 页，每页 ${this.pageSize} 只`;
      } else {
        text += ` · 显示 ${this.result.rows.length} 只`;
      }
      if (this.result.stats.data_cutoff) {
        text += ` · 数据截止 ${this.result.stats.data_cutoff}`;
      }
      if (this.result.stats.stale) text += " · 数据可能需要更新";
      return text;
    },
    get cliCommand() {
      const parts = ["kan", "find"];
      if (this.pool.type === "watchlist") parts.push("--only-watchlist");
      if (this.pool.type === "holdings") parts.push("--only-holdings");
      if (this.pool.type === "all") parts.push("--all");
      if (this.pool.type === "codes" && this.pool.value.trim()) {
        parts.push("--codes", this.pool.value.trim().replace(/\s+/g, ","));
      }
      if (this.pool.type === "industry" && this.pool.value.trim()) {
        parts.push("--industry", this.pool.value.trim());
      }
      if (this.pool.type === "theme" && this.pool.value.trim()) {
        parts.push("--theme", this.pool.value.trim());
      }
      if (this.matchMode === "any") parts.push("--any");
      for (const filter of this.validFilters()) {
        const spec = this.filterSpecs[filter.type];
        if (spec) parts.push(spec.flag, this.filterParam(filter));
      }
      if (this.excludeSt) parts.push("--exclude-st");
      parts.push("--format", "json");
      return parts.map((part) => this.quote(part)).join(" ");
    },
    addFilter() {
      if (this.filters.length >= this.maxFilters) return;
      this.filters.push({
        id: this.nextId++,
        type: "",
        period: "",
        level: "",
        op: "",
        value: "",
      });
    },
    applyExample(kind) {
      const examples = {
        low180: { type: "pos", period: "180", level: "", op: "lt", value: "10" },
        high180: { type: "pos", period: "180", level: "", op: "gt", value: "90" },
        lowResonance: { type: "resonance", period: "", level: "low", op: "gte", value: "3" },
      };
      const example = examples[kind];
      if (!example) return;
      this.filters = [{ id: this.nextId++, ...example }];
      this.message = "示例条件已填入，你可以继续修改";
    },
    removeFilter(index) {
      this.filters.splice(index, 1);
    },
    normalizeFilter(filter) {
      if (!this.needsPeriod(filter)) filter.period = "";
      if (filter.type !== "resonance") filter.level = "";
    },
    needsPeriod(filter) {
      const spec = this.filterSpecs[filter.type];
      return Boolean(spec && spec.input === "period");
    },
    supportsAll(filter) {
      const spec = this.filterSpecs[filter.type];
      return !spec || spec.supports_all;
    },
    validFilters() {
      return this.filters.filter((filter) => {
        if (!filter.type || filter.value === "" || !filter.op) return false;
        if (this.needsPeriod(filter)) return filter.period;
        if (filter.type === "resonance") return filter.level;
        return filter.op;
      });
    },
    filterParam(filter) {
      if (this.needsPeriod(filter)) {
        return `${filter.period}:${filter.op}:${filter.value}`;
      }
      if (filter.type === "resonance") {
        return `${filter.level}:${filter.op}:${filter.value}`;
      }
      return `${filter.op}:${filter.value}`;
    },
    filterUnit(filter) {
      const spec = this.filterSpecs[filter.type];
      return spec ? spec.unit : "";
    },
    filterValueLabel(filter) {
      const spec = this.filterSpecs[filter.type];
      return spec ? `${spec.label}阈值` : "条件数值";
    },
    requestPayload() {
      return {
        pool: { type: this.pool.type, value: this.pool.value },
        filters: this.validFilters().map((filter) => ({
          type: filter.type,
          period: filter.period,
          level: filter.level,
          op: filter.op,
          value: filter.value,
        })),
        exclude_st: this.excludeSt,
        match_any: this.matchMode === "any",
      };
    },
    async submit() {
      if (this.filters.length !== this.validFilters().length) {
        this.message = "请完整填写或删除未完成的筛选条件";
        kanToast(this.message, "error");
        return;
      }
      if (this.pool.type === "all" && this.filters.some((filter) => !this.supportsAll(filter))) {
        this.message = "当前条件不支持全市场，请更换候选池";
        kanToast(this.message, "error");
        return;
      }
      this.loading = true;
      this.message = this.pool.type === "all" ? "正在扫描全市场截面数据" : "正在读取候选池数据";
      this.result = null;
      try {
        const response = await kanFetch("/api/find", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Kan-Web": "1",
          },
          body: JSON.stringify(this.requestPayload()),
        });
        const payload = await response.json();
        if (!response.ok) {
          this.message = typeof payload.detail === "string" ? payload.detail : "查询失败";
          kanToast(this.message, "error");
          return;
        }
        payload.rows.forEach((row) => { row._added = false; });
        this.result = payload;
        this.sortKey = "";
        this.page = 1;
        this.batchMsg = "本页加入自选";
        this.message = this.resultSummary;
        kanToast(payload.stats.matched > 0 ? `找到 ${payload.stats.matched} 只符合条件的股票` : "没有符合条件的股票");
      } catch (_error) {
        this.message = "查询失败";
        kanToast("查询失败", "error");
      } finally {
        this.loading = false;
      }
    },
    async copyCommand() {
      try {
        await navigator.clipboard.writeText(this.cliCommand);
        this.copyMessage = "已复制";
      } catch (_error) {
        this.copyMessage = "复制失败";
      }
    },
    quote(value) {
      if (/^[A-Za-z0-9_./:=,-]+$/.test(value)) return value;
      return `'${String(value).replace(/'/g, "'\\''")}'`;
    },
    formatPrice(value) {
      return value === null ? "—" : Number(value).toFixed(2);
    },
    formatPct(value) {
      return value === null ? "—" : `${Number(value).toFixed(1)}%`;
    },
    formatTriggers(items) {
      if (!items || items.length === 0) return "—";
      return items.join(" · ");
    },
    formatMetrics(items) {
      if (!items || items.length === 0) return "—";
      return items.map((item) => {
        const value = item.value === null || item.value === undefined ? "—" : Number(item.value).toFixed(2);
        return `${item.label} ${value}${item.unit || ""}`;
      }).join(" · ");
    },
    sortKeyForFilter(filter) {
      if (filter.type === "pos") return `position:${filter.period}`;
      if (this.needsPeriod(filter)) return `${filter.type}:${filter.period}`;
      if (filter.type === "resonance") return `resonance:${filter.level}`;
      return filter.type;
    },
    sortValue(row, key) {
      if (key === "price") return row.price;
      if (key.startsWith("position:")) {
        return row.positions ? row.positions[key.slice("position:".length)] : null;
      }
      return row.sort_values ? row.sort_values[key] : null;
    },
    openStock(code) {
      window.location.href = kanSessionUrl(`/stock/${code}`);
    },
    async addToWatchlist(code) {
      const row = this.result.rows.find((r) => r.code === code);
      if (!row || row.in_watchlist || row._added) return;
      try {
        const response = await kanFetch("/api/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Kan-Web": "1" },
          body: JSON.stringify({ codes: code }),
        });
        if (response.ok) {
          row._added = true;
          row.in_watchlist = true;
          kanToast(`${row.name} 已加入自选`);
        } else {
          const payload = await response.json();
          kanToast(payload.detail || "添加失败", "error");
        }
      } catch (_error) {
        kanToast("添加失败", "error");
      }
    },
    async addAllToWatchlist() {
      const rows = this.sortedRows.filter((row) => !row.in_watchlist && !row._added);
      if (rows.length === 0) {
        this.batchMsg = "本页均在自选 ✓";
        return;
      }
      const codes = rows.map((r) => r.code).join(",");
      this.batchMsg = "添加中";
      try {
        const response = await kanFetch("/api/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Kan-Web": "1" },
          body: JSON.stringify({ codes }),
        });
        if (response.ok) {
          rows.forEach((r) => { r._added = true; r.in_watchlist = true; });
          this.batchMsg = "本页已加入 ✓";
          kanToast(`${rows.length} 只股票已加入自选`);
        } else {
          const payload = await response.json();
          this.batchMsg = "本页加入自选";
          kanToast(payload.detail || "批量添加失败", "error");
        }
      } catch (_error) {
        this.batchMsg = "本页加入自选";
        kanToast("批量添加失败", "error");
      }
    },
  };
}
