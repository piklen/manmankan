import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CircleDollarSign,
  Landmark,
  PieChart,
  Plus,
  RefreshCw,
  Trash2,
  WalletCards,
} from "lucide-react";
import { FormEvent, useState } from "react";
import { api } from "../api/client";
import { Badge, Button, Card, EmptyState, Loading, PageHeader } from "../components/ui";
import { errorMessage, number, percent } from "../lib/format";

export function PortfolioPage() {
  const queryClient = useQueryClient();
  const [cash, setCash] = useState("");
  const [code, setCode] = useState("");
  const [cost, setCost] = useState("");
  const [shares, setShares] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const portfolioQuery = useQuery({
    queryKey: ["portfolio"],
    queryFn: api.portfolio,
    retry: false,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["portfolio"] });
  const cashMutation = useMutation({
    mutationFn: () => api.updateCash(Number(cash)),
    onSuccess: () => { setCash(""); setNotice("可用现金已保存"); void refresh(); },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const positionMutation = useMutation({
    mutationFn: () => api.addPosition({
      code,
      cost: Number(cost),
      shares: Number(shares),
    }),
    onSuccess: () => {
      setCode(""); setCost(""); setShares(""); setNotice("持仓事实已保存"); void refresh();
    },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const deleteMutation = useMutation({
    mutationFn: (symbol: string) => api.deletePosition(symbol),
    onSuccess: () => void refresh(),
    onError: (error) => setNotice(errorMessage(error)),
  });
  const data = portfolioQuery.data;

  const submitPosition = (event: FormEvent) => {
    event.preventDefault();
    positionMutation.mutate();
  };

  return (
    <div>
      <PageHeader
        eyebrow="Portfolio facts"
        title="持仓页只负责把账户事实算清楚"
        description="成本、数量、现金与本地价格共同形成账户快照；这里不替你决定买卖。"
        actions={
          <>
            {notice ? <span className="notice-pill">{notice}</span> : null}
            <Button variant="secondary" onClick={() => void refresh()}><RefreshCw size={15} /> 重新读取</Button>
          </>
        }
      />
      {portfolioQuery.isLoading ? <Loading label="读取持仓账本" /> : null}
      <div className="portfolio-metrics">
        <Card><span><Landmark size={17} /> 总资产</span><strong>¥ {number(data?.account.total_assets)}</strong><small>现金 + 持仓市值</small></Card>
        <Card><span><WalletCards size={17} /> 可用现金</span><strong>¥ {number(data?.account.cash)}</strong><small>本地手工账本</small></Card>
        <Card><span><PieChart size={17} /> 仓位</span><strong>{percent(data?.account.total_position_pct)}</strong><small>持仓市值 / 总资产</small></Card>
        <Card><span><CircleDollarSign size={17} /> 累计浮动盈亏</span><strong>¥ {number(data?.account.total_pnl)}</strong><small>按当前缓存价格</small></Card>
      </div>

      <div className="portfolio-layout">
        <Card className="portfolio-table-card">
          <div className="research-section__heading">
            <div><span className="panel-kicker">Position ledger</span><h2>持仓明细</h2></div>
            <Badge tone={data?.data_cutoff ? "neutral" : "warning"}>截止 {data?.data_cutoff ?? "未知"}</Badge>
          </div>
          {!portfolioQuery.isLoading && !(data?.rows?.length) ? (
            <EmptyState title="还没有持仓记录" detail="在右侧录入代码、成本与数量；数据只写入本机。" />
          ) : null}
          {data?.rows?.length ? (
            <div className="result-table-wrap">
              <table className="result-table portfolio-table">
                <thead><tr><th>股票</th><th>数量</th><th>成本</th><th>价格</th><th>市值</th><th>仓位</th><th>180 日位置</th><th>浮动盈亏</th><th /></tr></thead>
                <tbody>
                  {(data.rows ?? []).map((row) => (
                    <tr key={row.code}>
                      <td><div className="stock-cell"><strong>{row.name}</strong><span>{row.code}</span></div></td>
                      <td>{number(row.shares, 0)}</td>
                      <td>{number(row.cost)}</td>
                      <td>{number(row.price)}</td>
                      <td>{number(row.market_value)}</td>
                      <td>{percent(row.weight_pct)}</td>
                      <td>{percent(row.p180_pct)}</td>
                      <td><span className={(row.total_pnl ?? 0) >= 0 ? "value-up" : "value-down"}>{number(row.total_pnl)} · {percent(row.total_pnl_pct)}</span></td>
                      <td><button className="icon-button" type="button" aria-label="删除持仓" onClick={() => deleteMutation.mutate(row.code)}><Trash2 size={14} /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </Card>

        <aside className="portfolio-editor">
          <Card>
            <h3>账户现金</h3>
            <p>用于计算仓位比例，不会连接券商。</p>
            <form onSubmit={(event) => { event.preventDefault(); cashMutation.mutate(); }}>
              <label><span>可用现金</span><input type="number" min="0" step="0.01" value={cash} onChange={(event) => setCash(event.target.value)} placeholder={String(data?.account.cash ?? 0)} /></label>
              <Button size="sm" type="submit">保存现金</Button>
            </form>
          </Card>
          <Card>
            <h3><Plus size={16} /> 录入持仓</h3>
            <form onSubmit={submitPosition}>
              <label><span>股票代码</span><input value={code} onChange={(event) => setCode(event.target.value)} placeholder="600519" /></label>
              <label><span>持仓成本</span><input type="number" min="0" step="0.0001" value={cost} onChange={(event) => setCost(event.target.value)} /></label>
              <label><span>持股数量</span><input type="number" min="1" step="1" value={shares} onChange={(event) => setShares(event.target.value)} /></label>
              <Button size="sm" type="submit">保存持仓</Button>
            </form>
          </Card>
        </aside>
      </div>
    </div>
  );
}
