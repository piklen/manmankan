import { useEffect } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

export function AppShell() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <header className="app-header">
        <Link to="/" className="brand">
          <strong>慢慢看</strong>
          <span>市场变化研究</span>
        </Link>
        <nav aria-label="主导航">
          <NavLink to="/" end>
            市场观察
          </NavLink>
          <NavLink to="/explore">趋势筛选</NavLink>
          <NavLink
            to="/studies"
            className={
              pathname.startsWith("/observations/") ? "active" : undefined
            }
          >
            我的研究
          </NavLink>
          <NavLink to="/data">数据</NavLink>
        </nav>
      </header>
      <main id="main-content">
        <Outlet />
      </main>
      <footer className="app-footer">
        慢慢看 ·
        数据帮助理解，判断留给自己。历史价格不预示未来，不构成投资建议。
      </footer>
    </div>
  );
}
