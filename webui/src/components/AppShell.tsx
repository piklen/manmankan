import {
  BarChart3,
  BriefcaseBusiness,
  ChevronRight,
  CircleDotDashed,
  Database,
  GitCompareArrows,
  LibraryBig,
  Search,
  Settings,
  Sparkles,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

const navigation = [
  { to: "/screen", label: "选股工作台", icon: CircleDotDashed },
  { to: "/candidates", label: "研究候选", icon: LibraryBig },
  { to: "/compare", label: "横向对比", icon: GitCompareArrows },
  { to: "/research", label: "个股研究", icon: Search },
  { to: "/market", label: "市场与数据", icon: BarChart3 },
  { to: "/portfolio", label: "持仓事实", icon: BriefcaseBusiness },
  { to: "/settings", label: "设置", icon: Settings },
];

export function AppShell() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <NavLink to="/screen" className="brand" aria-label="慢慢看首页">
          <span className="brand__mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span>
            <strong>慢慢看</strong>
            <small>ManManKan</small>
          </span>
        </NavLink>

        <nav className="sidebar__nav" aria-label="主导航">
          <p className="nav-label">研究工作流</p>
          {navigation.slice(0, 4).map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className="nav-item">
              <Icon size={18} strokeWidth={1.8} />
              <span>{label}</span>
              <ChevronRight className="nav-item__arrow" size={14} />
            </NavLink>
          ))}
          <p className="nav-label nav-label--spaced">账户与数据</p>
          {navigation.slice(4).map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className="nav-item">
              <Icon size={18} strokeWidth={1.8} />
              <span>{label}</span>
              <ChevronRight className="nav-item__arrow" size={14} />
            </NavLink>
          ))}
        </nav>

        <div className="sidebar__footer">
          <Database size={17} />
          <div>
            <strong>本机工作区</strong>
            <span>数据与规则不出本机</span>
          </div>
          <span className="status-dot" title="本地服务已连接" />
        </div>
      </aside>

      <div className="app-main">
        <div className="utility-bar">
          <div className="utility-bar__trail">
            <Sparkles size={15} />
            <span>可解释选股 · 每个结果都有证据</span>
          </div>
          <div className="utility-bar__meta">
            <span className="local-chip">LOCAL</span>
            <span>latest complete</span>
          </div>
        </div>
        <main className="page-content">
          <Outlet />
          <footer className="product-disclaimer">
            候选 ≠ 买入信号 · 工具只呈现符合你设置规则的客观数据 · 历史价格不预示未来 · 不构成投资建议
          </footer>
        </main>
      </div>

      <nav className="mobile-nav" aria-label="移动端主导航">
        {navigation.slice(0, 5).map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to}>
            <Icon size={19} />
            <span>{label.slice(0, 4)}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
