import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { CandidatesPage } from "./pages/CandidatesPage";
import { ComparePage } from "./pages/ComparePage";
import { MarketDataPage } from "./pages/MarketDataPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { ResearchPage } from "./pages/ResearchPage";
import { ScreenWorkbench } from "./pages/ScreenWorkbench";
import { SettingsPage } from "./pages/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/screen" replace />} />
        <Route path="screen" element={<ScreenWorkbench />} />
        <Route path="candidates" element={<CandidatesPage />} />
        <Route path="compare" element={<ComparePage />} />
        <Route path="research" element={<ResearchPage />} />
        <Route path="research/:symbol" element={<ResearchPage />} />
        <Route path="market" element={<MarketDataPage />} />
        <Route path="portfolio" element={<PortfolioPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="find" element={<Navigate to="/screen" replace />} />
        <Route path="stock/:symbol" element={<ResearchPage />} />
        <Route path="hold" element={<Navigate to="/portfolio" replace />} />
        <Route path="*" element={<Navigate to="/screen" replace />} />
      </Route>
    </Routes>
  );
}
