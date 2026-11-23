import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { useEffect } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import "./index.css";
import Landing from "./pages/Landing";
import Agents from "./pages/Agents";
import Workspace from "./pages/Workspace";

// a new page starts at its top (or at its #section), not where the last page was scrolled to
function ScrollReset() {
  const { pathname, hash } = useLocation();
  useEffect(() => { if (!hash) window.scrollTo(0, 0); }, [pathname, hash]);
  return null;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ScrollReset />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/agents" element={<Agents />} />
        <Route path="/build/new" element={<Workspace />} />
        <Route path="/build/:id" element={<Workspace />} />
        <Route path="*" element={<Landing />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
