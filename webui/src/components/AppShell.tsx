import {
  ArrowLeft, BriefcaseBusiness, CalendarCheck2, Database, GitCompareArrows,
  Menu, Monitor, NotebookPen, Search, Settings, Star, X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

const mainNavigation = [
  { to: "/focus", label: "我的关注", icon: Star },
  { to: "/trends", label: "发现与筛选", icon: Search },
  { to: "/candidates", label: "研究笔记", icon: NotebookPen },
  { to: "/compare", label: "横向对比", icon: GitCompareArrows },
];
const secondaryNavigation = [
  { to: "/portfolio", label: "持仓事实", icon: BriefcaseBusiness },
  { to: "/market", label: "数据管理", icon: Database },
  { to: "/settings", label: "设置", icon: Settings },
];
const discoveryPaths = ["/trends", "/screen", "/review", "/history/board"];

export function AppShell() {
  const { pathname } = useLocation();
  const [moreOpen, setMoreOpen] = useState(false);
  useEffect(() => {
    window.scrollTo(0, 0);
    setMoreOpen(false);
  }, [pathname]);
  const inDiscovery = discoveryPaths.includes(pathname);
  const navClass = (to: string) =>
    `nav-item${pathname === to || (to === "/trends" && inDiscovery) ? " active" : ""}`;
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className="sidebar">
        <NavLink to="/focus" className="brand" aria-label="慢慢看首页">
          <span><strong>慢慢看</strong><small>ManManKan</small></span>
        </NavLink>
        <nav className="sidebar__nav" aria-label="主导航">
          {mainNavigation.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={navClass(to)} title={label}>
              <Icon size={20} strokeWidth={1.7} /><span>{label}</span>
            </NavLink>
          ))}
          <p className="nav-label nav-label--spaced">数据与账户</p>
          {secondaryNavigation.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className="nav-item" title={label}>
              <Icon size={20} strokeWidth={1.7} /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar__footer"><Monitor size={18} /><div><strong>本机工作区</strong><span>笔记与持仓保存在本机</span></div></div>
      </aside>
      <div className="app-main">
        <div className="mobile-brand"><Link to="/focus">慢慢看</Link><span>本机研究工作区</span></div>
        <main className="page-content" id="main-content">
          {inDiscovery ? (
            <nav className="workspace-tabs" aria-label="发现与筛选">
              <NavLink to="/trends">行业与题材</NavLink>
              <NavLink to="/screen">条件筛选</NavLink>
              <NavLink to="/review">板块复看</NavLink>
              {pathname === "/history/board" ? <NavLink to="/history/board">历史复核</NavLink> : null}
              <NavLink to="/research">查一只股票</NavLink>
            </nav>
          ) : null}
          {pathname.startsWith("/research") || pathname.startsWith("/stock/") ? (
            <Link className="back-link" to="/focus"><ArrowLeft size={16} /> 返回我的关注</Link>
          ) : null}
          <Outlet />
          {pathname === "/screen" ? <p className="product-disclaimer">候选 ≠ 买入信号 · 工具仅返回符合您设置规则的股票数据 · 不构成任何形式的推荐或建议</p> : null}
          <footer className="product-disclaimer">创新低 ≠ 见底 · 创新高 ≠ 顶 · 历史价格不预示未来 · 仅供参考，不构成投资建议</footer>
        </main>
      </div>
      {moreOpen ? (
        <div className="mobile-more">
          <div className="mobile-more__heading"><strong>更多功能</strong><button type="button" className="icon-button" aria-label="关闭更多功能" onClick={() => setMoreOpen(false)}><X size={20} /></button></div>
          <nav aria-label="更多功能">
            {[...secondaryNavigation, { to: "/research", label: "查一只股票", icon: Search }, { to: "/review", label: "板块复看", icon: CalendarCheck2 }].map(({ to, label, icon: Icon }) => (
              <NavLink to={to} key={to} onClick={() => setMoreOpen(false)}><Icon size={18} />{label}</NavLink>
            ))}
          </nav>
        </div>
      ) : null}
      <nav className="mobile-nav" aria-label="移动端主导航">
        {mainNavigation.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className={pathname === to || (to === "/trends" && inDiscovery) ? "active" : ""} onClick={() => setMoreOpen(false)}>
            <Icon size={20} strokeWidth={1.7} /><span>{label}</span>
          </NavLink>
        ))}
        <button type="button" aria-expanded={moreOpen} aria-label="更多功能" onClick={() => setMoreOpen(!moreOpen)}><Menu size={20} /><span>更多</span></button>
      </nav>
    </div>
  );
}
