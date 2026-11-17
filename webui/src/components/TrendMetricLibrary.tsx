import { Activity, ArrowUpRight, ChartCandlestick, ChartNoAxesCombined, Plus, Search, Waypoints, X } from "lucide-react";
import { useState } from "react";
import type { StudyCondition } from "../api/client";
import { FIELDS } from "../lib/study";

type Field = StudyCondition["field"];
type Metric = { fields: Field[]; name: string; note: string };
function metric(field: Field, note: string, name = FIELDS[field].label): Metric {
  return { fields: [field], name, note };
}
const sections = [
  {
    name: "方向与力度", icon: ChartNoAxesCombined,
    metrics: [
      metric("return_pct", "一段时间里涨跌了多少"),
      metric("trend_slope", "用每日斜率看价格方向"),
      metric("trend_efficiency", "净变化占累计波动的比例"),
      metric("position", "当前收盘在区间高低点之间的位置"),
    ],
  },
  {
    name: "连续走势", icon: Activity,
    metrics: [
      metric("up_days", "收盘高于前收持续了几天", "连续上涨"),
      metric("down_days", "收盘低于前收持续了几天", "连续下跌"),
      { fields: ["previous_down_days", "up_days"], name: "先跌后涨", note: "分别核对紧邻两段的天数" },
      { fields: ["previous_up_days", "down_days"], name: "先涨后跌", note: "分别核对紧邻两段的天数" },
      metric("rising_days", "在同一窗口内统计上涨或下跌天数", "区间涨跌天数"),
    ],
  },
  {
    name: "波段与形态", icon: Waypoints,
    metrics: [
      metric("swing_structure", "已确认的波峰和波谷怎样变化"),
      metric("swing_direction", "最后一个确认转折之后的方向"),
      metric("swing_count", "窗口内已走完多少段"),
      metric("shape_distance", "与指定股票某段收盘路径的距离", "形态检索"),
    ],
  },
  {
    name: "价格与成交", icon: ChartCandlestick,
    metrics: [
      metric("volume_ratio", "当日成交量相对历史均量的倍数"),
      metric("change_pct", "本日收盘相对前收的变化"),
      metric("gap_pct", "当日开盘相对前收的变化"),
      metric("body_pct", "本日收盘相对开盘的变化"),
      metric("low_age", "最近一次区间低点距今多少天"),
      metric("candle_balance", "统计阳线、阴线或两者数量差", "区间阳阴线"),
      metric("bull_days", "收盘高于开盘持续了几天"),
      metric("bear_days", "收盘低于开盘持续了几天"),
      metric("joint_up_days", "同时满足收阳和上涨的连续天数"),
    ],
  },
] satisfies { name: string; icon: typeof Activity; metrics: Metric[] }[];

export function TrendMetricLibrary({ count, onPick, onBrowse, browseDisabled, onClose }: {
  count: number;
  onPick: (fields: Field[]) => void;
  onBrowse: () => void;
  browseDisabled: boolean;
  onClose?: () => void;
}) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const keyword = search.trim().toLowerCase();
  const visible = sections.filter((section) => !category || category === section.name)
    .map((section) => ({
      ...section,
      metrics: section.metrics.filter((item) =>
        [section.name, item.name, item.note, ...item.fields.map((field) => FIELDS[field].label)]
          .join(" ").toLowerCase().includes(keyword)),
    })).filter((section) => section.metrics.length);

  return (
    <section className="metric-library" aria-labelledby="metric-library-title">
      <header className="metric-library-heading">
        <div><h2 id="metric-library-title">选择指标</h2><p>加入指标后，填写自己的比较条件。</p></div>
        {onClose ? <button type="button" className="small-link" onClick={onClose}><X size={15} />返回结果</button> : null}
      </header>
      <label className="search-field metric-library-search">
        <Search size={16} />
        <input type="search" aria-label="查找指标" value={search} placeholder="搜索指标，如「斜率」" onChange={(event) => setSearch(event.target.value)} />
      </label>
      <div className="metric-library-tabs" role="group" aria-label="指标类别">
        {["", ...sections.map((section) => section.name)].map((name) =>
          <button type="button" key={name} aria-pressed={category === name} onClick={() => setCategory(name)}>{name || "全部"}</button>)}
      </div>
      <div className="metric-library-groups">
        {visible.map(({ name, icon: Icon, metrics }) => (
          <section key={name} className="metric-family">
            <h3><Icon aria-hidden="true" size={16} />{name}</h3>
            {metrics.map((item) => (
              <button type="button" key={item.name} aria-label={item.name}
                disabled={count + item.fields.length > 10} onClick={() => onPick(item.fields)}>
                <span><strong>{item.name}</strong><small>{item.note}</small></span><Plus size={15} />
              </button>
            ))}
          </section>
        ))}
      </div>
      {!visible.length && <p className="metric-library-no-matches">当前类别没有匹配指标。<button type="button" className="small-link" onClick={() => { setSearch(""); setCategory(""); }}>显示全部指标</button></p>}
      <button type="button" className="metric-browse" onClick={onBrowse} disabled={browseDisabled}>
        <span>浏览当前范围<small>按股票代码查看全部成员</small></span><ArrowUpRight size={17} />
      </button>
    </section>
  );
}
