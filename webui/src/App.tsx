import { Link, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { StudyPage, SavedStudyPage } from "./pages/StudyPage";
import { StudiesPage } from "./pages/StudiesPage";
import { TrendMapPage } from "./pages/TrendMapPage";
import { DataPage } from "./pages/DataPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<TrendMapPage />} />
        <Route path="studies/new" element={<StudyPage key="new" />} />
        <Route path="studies" element={<StudiesPage />} />
        <Route path="studies/:studyId" element={<SavedStudyPage />} />
        <Route path="data" element={<DataPage />} />
        <Route
          path="*"
          element={
            <div className="standalone-empty">
              <h1>这个页面不存在</h1>
              <Link to="/">开始一项新研究</Link>
            </div>
          }
        />
      </Route>
    </Routes>
  );
}
