import { useQuery } from "@tanstack/react-query";
import {
  Braces,
  CheckCircle2,
  Database,
  FolderLock,
  KeyRound,
  Laptop,
  Server,
} from "lucide-react";
import { api } from "../api/client";
import { Badge, Card, Loading, PageHeader } from "../components/ui";

export function SettingsPage() {
  const metaQuery = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const filtersQuery = useQuery({ queryKey: ["filters"], queryFn: api.filters });
  const settingsQuery = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings,
    retry: false,
  });
  const meta = metaQuery.data;
  const filterCount = filtersQuery.data?.reduce((sum, group) => sum + group.options.length, 0) ?? 0;

  return (
    <div>
      <PageHeader
        eyebrow="Local workspace settings"
        title="软件运行边界，一眼看清"
        description="查看版本、API 能力、数据接入状态与本地隐私边界。凭据值不会在页面回显。"
      />
      {metaQuery.isLoading ? <Loading label="读取本地服务信息" /> : null}
      <div className="settings-grid">
        <Card className="settings-card settings-card--hero">
          <div className="settings-card__icon"><Laptop size={24} /></div>
          <div><span className="panel-kicker">Runtime</span><h2>ManManKan {meta?.product_version ?? "—"}</h2><p>Python 后端 + React 工作台 · 同一个本机进程交付。</p></div>
          <Badge tone="positive">本机模式</Badge>
        </Card>
        <Card className="settings-card">
          <h3><Server size={18} /> API 契约</h3>
          <dl>
            <div><dt>版本</dt><dd>{meta?.api_version ?? "—"}</dd></div>
            <div><dt>OpenAPI</dt><dd>/api/v1/openapi.json</dd></div>
            <div><dt>选股条件</dt><dd>{filterCount} 个</dd></div>
            <div><dt>状态后端</dt><dd>{settingsQuery.data?.state_backend ?? "—"}</dd></div>
          </dl>
        </Card>
        <Card className="settings-card">
          <h3><KeyRound size={18} /> TuShare 凭据</h3>
          <div className="credential-status">
            <CheckCircle2 size={18} />
            <div><strong>{settingsQuery.data?.tushare_configured ? "已配置" : "未配置"}</strong><span>{settingsQuery.data?.tushare_masked ?? "页面不会显示完整 token"}</span></div>
          </div>
          <p>凭据只由既有配置入口维护；工作台只读取遮罩状态。</p>
        </Card>
        <Card className="settings-card">
          <h3><FolderLock size={18} /> 本地数据</h3>
          <ul className="settings-list">
            <li><Database size={15} /><span>行情缓存</span><Badge tone="neutral">Parquet</Badge></li>
            <li><Braces size={15} /><span>规则、运行与候选</span><Badge tone="neutral">SQLite WAL</Badge></li>
            <li><FolderLock size={15} /><span>默认权限</span><Badge tone="positive">目录 0700 · 文件 0600</Badge></li>
          </ul>
          <p>{settingsQuery.data?.data_dir ?? "本地数据目录读取中"}</p>
        </Card>
        <Card className="settings-card settings-card--wide">
          <h3>已启用能力</h3>
          <div className="capability-list">
            {(meta?.capabilities ?? []).map((capability) => <Badge key={capability} tone="info">{capability}</Badge>)}
          </div>
          <p>Web、CLI 与 MCP 共用一套 ScreenSpec / ScreenRun，不各自维护筛选语义。</p>
        </Card>
      </div>
    </div>
  );
}
