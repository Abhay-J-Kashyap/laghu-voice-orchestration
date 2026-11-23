import { useEffect, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { api, type QueueState } from "@/lib/api";
import { Loader } from "./Loader";

export default function TopBar({ transparent = false }: { transparent?: boolean }) {
  const [q, setQ] = useState<QueueState | null>(null);
  useEffect(() => {
    let live = true;
    const tick = () => api.queue().then((x) => live && setQ(x)).catch(() => live && setQ(null));
    tick();
    const t = setInterval(tick, 5000);
    return () => { live = false; clearInterval(t); };
  }, []);
  const link = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-1.5 rounded-full transition-colors ${isActive ? "bg-ink-3 text-parchment" : "text-dust hover:text-parchment"}`;
  return (
    <header className={`relative z-20 flex items-center gap-4 px-5 sm:px-8 py-4 ${transparent ? "" : "border-b border-ink-3/70"}`}>
      <Link to="/" className="display text-2xl text-parchment" aria-label="Laghu setup, home">laghu</Link>
      <nav className="flex items-center gap-1 text-[0.95rem]">
        <NavLink to="/agents" className={link}>Your agents</NavLink>
        <NavLink to="/build/new" className={link}>Build one</NavLink>
      </nav>
      <div className="ml-auto text-sm text-dust hidden sm:flex items-center gap-2">
        {q?.running ? (
          <Link to={`/build/${q.running.agent}`} className="inline-flex items-center gap-2 hover:text-parchment">
            <Loader role="inline" />
            {q.running.kind === "setup" ? "Building" : "Asking about"} {q.running.agent}
            {q.waiting.length ? `, ${q.waiting.length} waiting` : ""}
          </Link>
        ) : q ? <span>Nothing running</span> : <span>Server not reachable</span>}
      </div>
    </header>
  );
}
