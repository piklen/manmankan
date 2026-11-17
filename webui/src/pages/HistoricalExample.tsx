import { Link } from "react-router-dom";
import { useState } from "react";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { IndustryStrengthMap } from "../components/IndustryStrengthMap";
import snapshots from "../data/industry-snapshot.json";
import { number, percent } from "../lib/format";
import "../styles/discovery.css";
import "../styles/example.css";

export function HistoricalExample({
  publicSite = false,
}: {
  publicSite?: boolean;
}) {
  const [days, setDays] = useState(20);
  const [industry, setIndustry] = useState("");
  const snapshot = snapshots.find((item) => item.days === days)!;
  const group =
    snapshot.industries.find((item) => item.name === industry) ??
    snapshot.market;
  const delta = group.comparison.breadth_delta_pp;
  return (
    <article className="history-example">
      {publicSite && (
        <a className="example-back" href="./">
          <ArrowLeft size={16} />
          慢慢看
        </a>
      )}
      <header className="example-heading">
        <div>
          <h1>行业强弱，放在一起看</h1>
          <p>
            历史样本 · {snapshot.as_of} 收盘 ·{" "}
            {number(snapshot.market.total, 0)} 只 A 股
          </p>
        </div>
        <div className="example-windows" role="group" aria-label="历史样本窗口">
          {snapshots.map((item) => (
            <button
              type="button"
              key={item.days}
              aria-pressed={item.days === days}
              onClick={() => setDays(item.days)}
            >
              {item.days} 日
            </button>
          ))}
        </div>
      </header>
      <p className="example-lede">
        横向看行业涨跌与整个范围的差距，纵向看上涨有没有扩散。点一个行业，再切换窗口，比较同一行业在不同时间尺度上的表现。
      </p>
      <div className="example-body">
        <IndustryStrengthMap
          groups={snapshot.industries}
          selected={industry || null}
          onSelect={setIndustry}
        />
        <section className="example-reading" aria-label="所选范围的历史事实">
          <label>
            查看范围
            <select
              value={industry}
              onChange={(event) => setIndustry(event.target.value)}
            >
              <option value="">全部范围</option>
              {snapshot.industries.map((g) => (
                <option key={g.name}>{g.name}</option>
              ))}
            </select>
          </label>
          <h2>{group.name}</h2>
          <p className="example-dates">
            {snapshot.start} 至 {snapshot.as_of}
          </p>
          <dl>
            <div>
              <dt>区间涨跌中位数</dt>
              <dd>{percent(group.median, 2)}</dd>
            </div>
            {industry && (
              <div>
                <dt>与全部范围的差距</dt>
                <dd>
                  {number(group.relative_return_pp, 2)} <small>个百分点</small>
                </dd>
              </div>
            )}
            <div>
              <dt>区间上涨家数</dt>
              <dd>
                {number(group.up, 0)}{" "}
                <small>/ {number(group.available, 0)} 只有效</small>
              </dd>
            </div>
          </dl>
          <p className="example-finding" aria-live="polite">
            {delta == null ? (
              "两期共同成员资料不足。"
            ) : (
              <>
                同一批 {number(group.paired, 0)} 只股票，上涨占比从{" "}
                {percent(group.previous_share)} 到{" "}
                {percent(group.current_share)}，
                {delta === 0 ? (
                  "两期持平"
                ) : (
                  <>
                    {delta > 0 ? "扩大" : "缩小"}了 {number(Math.abs(delta), 1)}{" "}
                    个百分点
                  </>
                )}
                。
              </>
            )}
          </p>
          <p className="example-note">
            本期另有 {group.total - group.available} 只资料不足。
          </p>
        </section>
      </div>
      <footer className="example-source">
        <div>
          <h2>这个样本如何得出</h2>
          <p>
            用慢慢看从本地 TuShare
            复权日线计算，基准为完整查询范围内所有可判断股票的涨跌中位数。行业按生成样本时的申万一级归属，缺失行情单列。这里收录固定历史截面的聚合值。
          </p>
        </div>
        {publicSite ? (
          <a href="./#install" className="button button--secondary">
            在本机观察其他日期
            <ArrowRight size={15} />
          </a>
        ) : (
          <Link to="/" className="button button--secondary">
            打开我的市场观察
            <ArrowRight size={15} />
          </Link>
        )}
      </footer>
      {publicSite && (
        <p className="example-note">历史行情仅供研究，不构成投资建议。</p>
      )}
    </article>
  );
}
