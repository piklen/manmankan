import type { SwingEvidence as SwingFacts } from "../api/client";
import { fieldValue } from "../lib/study";
import { number, percent } from "../lib/format";

export function swingStage(structure: number | null | undefined, direction: number | null | undefined, broken?: boolean | null) {
  if (broken) return structure === 1 ? "已确认上升结构 · 已越过最近波谷" : "已确认下降结构 · 已越过最近波峰";
  const shape = structure == null ? "结构尚不明确" : fieldValue("swing_structure", structure);
  const phase = direction === 1
    ? structure === -1 ? "当前反弹中" : "当前上行中"
    : direction === -1
      ? structure === 1 ? "当前回撤中" : "当前下行中"
      : direction == null ? "当前方向无法确认" : "方向尚未形成";
  return `${shape} · ${phase}`;
}

export function SwingEvidencePanel({ evidence, windows, onWindow }: {
  evidence: SwingFacts;
  windows: number[];
  onWindow: (window: number) => void;
}) {
  const current = evidence.current;
  const pivots = evidence.pivots ?? [];
  return (
    <section className="swing-evidence" aria-label="波段结构证据">
      <header>
        <div><span>波段结构</span><h3>{swingStage(evidence.structure, evidence.direction, evidence.structure_broken)}</h3></div>
        {windows.length > 1 ? (
          <select aria-label="波段图证窗口" value={evidence.window} onChange={(event) => onWindow(Number(event.target.value))}>
            {windows.map((window) => <option key={window} value={window}>{window} 日</option>)}
          </select>
        ) : <span>{evidence.window} 日窗口</span>}
      </header>
      <p className="field-hint">收盘反向移动 {number(evidence.reversal_pct)}% 确认转折 · 实线为已完成段，虚线仍在形成。</p>
      {evidence.structure_broken ? <p className="swing-reason">结构名称描述已确认高低点的历史关系；当前收盘已越过最近确认{evidence.structure === 1 ? "波谷" : "波峰"}，不能解释为结构仍然完整。</p> : null}
      {evidence.reason ? <p className="swing-reason">{evidence.reason}</p> : null}
      <dl className="swing-facts">
        <div><dt>已完成波段</dt><dd>{evidence.direction == null ? "—" : Math.max(0, pivots.length - 1)} <small>段</small></dd></div>
        <div><dt>当前段持续</dt><dd>{current ? number(current.days, 0) : "—"} <small>交易日</small></dd></div>
        <div><dt>距当前段起点</dt><dd>{percent(current?.return_pct, 2)}</dd></div>
      </dl>
      {current ? <p className="field-hint">{current.start_confirmed ? "当前段起于" : "当前段以窗口内锚点开始于"} {current.start_date}（{number(current.start_price)}）；截至当前尚未完成。当前段内极值 {current.extreme_date}（{number(current.extreme_price)}）。</p> : null}
      <details className="swing-pivots">
        <summary>已确认转折点 <span>{pivots.length} 个</span></summary>
        {pivots.length ? <div className="table-scroll"><table>
          <thead><tr><th>转折</th><th>发生日期</th><th>收盘价</th><th>确认日期</th></tr></thead>
          <tbody>{pivots.map((pivot) => <tr key={pivot.date}>
            <td>{pivot.kind === "high" ? "波峰" : "波谷"}</td><td>{pivot.date}</td><td>{number(pivot.price)}</td><td>{pivot.confirmed_at}</td>
          </tr>)}</tbody>
        </table></div> : <p>窗口内尚无已确认转折；不能把首尾边界当作波峰波谷。</p>}
        <p className="field-hint">转折发生后，达到反向幅度才确认。历史判断使用确认日期；最新段不会提前算成已完成。</p>
      </details>
    </section>
  );
}
