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
          <span>趋势搜索与定位</span>
        </Link>
        <nav aria-label="主导航">
          <NavLink to="/" end>
            发现趋势
          </NavLink>
          <NavLink to="/studies">我的研究</NavLink>
          <NavLink to="/data">数据</NavLink>
        </nav>
      </header>
      <main id="main-content">
        <Outlet />
      </main>
      <footer className="app-footer">
        日线事实研究 · 创新低 ≠ 见底 · 创新高 ≠ 顶 · 历史价格不预示未来 ·
        仅供参考，不构成投资建议
      </footer>
    </div>
  );
}
