function kanFindPage() {
  return {
    pool: { type: "watchlist", value: "" },
    filters: [],
    excludeSt: false,
    loading: false,
    message: "",
    copyMessage: "",
    result: null,
    nextId: 1,
    get resultPeriods() {
      return this.result ? this.result.periods : [];
    },
    get cliCommand() {
      const parts = ["kan", "find"];
      if (this.pool.type === "watchlist") parts.push("--only-watchlist");
      if (this.pool.type === "holdings") parts.push("--only-holdings");
      if (this.pool.type === "codes" && this.pool.value.trim()) {
        parts.push("--codes", this.pool.value.trim().replace(/\s+/g, ","));
      }
      if (this.pool.type === "industry" && this.pool.value.trim()) {
        parts.push("--industry", this.pool.value.trim());
      }
      if (this.pool.type === "theme" && this.pool.value.trim()) {
        parts.push("--theme", this.pool.value.trim());
      }
      for (const filter of this.validFilters()) {
        if (filter.type === "pos") {
          parts.push("--pos", `${filter.period}:${filter.op}:${filter.value}`);
        }
        if (filter.type === "resonance") {
          parts.push("--resonance", `${filter.level}:gte:${filter.value}`);
        }
        if (filter.type === "pe") {
          parts.push("--pe", `${filter.op}:${filter.value}`);
        }
        if (filter.type === "moneyflow") {
          parts.push("--moneyflow", `${filter.op}:${filter.value}`);
        }
      }
      if (this.excludeSt) parts.push("--exclude-st");
      parts.push("--format", "json");
      return parts.map((part) => this.quote(part)).join(" ");
    },
    addFilter() {
      if (this.filters.length >= 6) return;
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
        lowResonance: { type: "resonance", period: "", level: "low", op: "", value: "3" },
      };
      const example = examples[kind];
      if (!example) return;
      this.filters = [{ id: this.nextId++, ...example }];
      this.message = "示例条件已填入，你可以继续修改";
    },
    removeFilter(index) {
      this.filters.splice(index, 1);
    },
    validFilters() {
      return this.filters.filter((filter) => {
        if (!filter.type || filter.value === "") return false;
        if (filter.type === "pos") return filter.period && filter.op;
        if (filter.type === "resonance") return filter.level;
        return filter.op;
      });
    },
    filterUnit(filter) {
      if (filter.type === "pos") return "%";
      if (filter.type === "pe") return "PE";
      if (filter.type === "moneyflow") return "万元";
      if (filter.type === "resonance") return "周期";
      return "";
    },
    filterValueLabel(filter) {
      const type = {
        pos: "位置阈值",
        resonance: "周期数量",
        pe: "市盈率阈值",
        moneyflow: "主力资金阈值",
      }[filter.type];
      return type || "条件数值";
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
      };
    },
    async submit() {
      this.loading = true;
      this.message = "正在读取本地数据";
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
        this.result = payload;
        this.message = `符合条件 ${payload.stats.matched} 只`;
        kanToast(`找到 ${payload.stats.matched} 只符合条件的股票`);
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
        return `${item.label} ${value}`;
      }).join(" · ");
    },
    openStock(code) {
      window.location.href = kanSessionUrl(`/stock/${code}`);
    },
  };
}
