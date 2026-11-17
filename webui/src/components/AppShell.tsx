import {
  BookOpen,
  ChartNoAxesColumnIncreasing,
  Database,
  ListFilter,
  Telescope,
} from "lucide-react";
import { useEffect } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

export function AppShell() {
  const { pathname, search } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return (
    <div className="app-shell">
      <a className="skip-link" href={pathname + search + "#main-content"}>
        跳到主要内容
      </a>
      <header className="app-header">
        <Link to="/" className="brand" aria-label="慢慢看首页">
          <svg width="33" height="32" viewBox="0 0 33 32" aria-hidden="true">
            <path
              d="m2 25 10-11 7 6L29 7"
              fill="none"
              stroke="currentColor"
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <circle cx="29" cy="7" r="3.5" fill="currentColor" />
          </svg>
          <strong>慢慢看</strong>
        </Link>
        <nav aria-label="主导航">
          <NavLink to="/" end>
            <ChartNoAxesColumnIncreasing />
            市场观察
          </NavLink>
          <NavLink to="/explore">
            <ListFilter />
            趋势筛选
          </NavLink>
          <NavLink
            to="/studies"
            className={
              pathname.startsWith("/observations/") ? "active" : undefined
            }
          >
            <BookOpen />
            我的研究
          </NavLink>
          <NavLink to="/data">
            <Database />
            数据
          </NavLink>
        </nav>
        <Link className="rail-example" to="/example">
          <Telescope size={17} />
          打开历史样本
        </Link>
      </header>
      <main id="main-content">
        <Outlet />
      </main>
      <footer className="app-footer">
        慢慢看 · 仅供历史数据研究，不构成投资建议。
      </footer>
    </div>
  );
}
