import { Link, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { StudyPage, SavedStudyPage } from "./pages/StudyPage";
import { StudiesPage } from "./pages/StudiesPage";
import { TrendScreenerPage } from "./pages/TrendScreenerPage";
import { DataPage } from "./pages/DataPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<TrendScreenerPage />} />
        <Route path="studies/new" element={<StudyPage key="new" />} />
        <Route path="studies" element={<StudiesPage />} />
        <Route path="studies/:studyId" element={<SavedStudyPage />} />
        <Route path="data" element={<DataPage />} />
        <Route
          path="*"
          element={
            <div className="standalone-empty">
              <h1>这个页面不存在</h1>
              <Link to="/">返回趋势筛选</Link>
            </div>
          }
        />
      </Route>
    </Routes>
  );
}
