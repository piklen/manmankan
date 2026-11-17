import { createRoot } from "react-dom/client";
import "./styles/global.css";
import { HistoricalExample } from "./pages/HistoricalExample";

createRoot(document.getElementById("root")!).render(
  <HistoricalExample publicSite />,
);
