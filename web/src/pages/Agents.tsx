import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AgentSummary } from "@/lib/api";
import { Loader } from "@/components/Loader";
import StatusPill from "@/components/StatusPill";
import TopBar from "@/components/TopBar";

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h ago`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export default function Agents() {
  const [agents, setAgents] = useState<AgentSummary[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    const load = () =>
      api.agents().then((a) => { if (live) { setAgents(a); setError(""); } })
        .catch((e) => live && setError(String(e.message ?? e)));
    load();
    const t = setInterval(load, 4000);
    return () => { live = false; clearInterval(t); };
  }, []);

  return (
    <div className="min-h-screen">
      <TopBar />
      <main className="px-5 sm:px-8 lg:px-14 py-10 max-w-6xl">
        <div className="flex flex-wrap items-end gap-4">
          <h1 className="display text-5xl sm:text-6xl">Your agents</h1>
          <Link to="/build/new" className="btn ml-auto">Build an agent</Link>
        </div>

        {error && (
          <p className="mt-8 text-[var(--c-agent)]">
            Couldn't reach the setup server ({error}). Start it with <code className="text-parchment">python -m laghu_voice.web</code>.
          </p>
        )}
        {!agents && !error && <div className="mt-16"><Loader label="Loading your agents" /></div>}
        {agents && agents.length === 0 && (
          <div className="mt-14 max-w-[34rem]">
            <p className="text-xl">No agents yet.</p>
            <p className="mt-2 text-dust">Describe the first call you want handled, and setup will take it from there.</p>
            <Link to="/build/new" className="btn mt-6">Describe a call</Link>
          </div>
        )}
        {agents && agents.length > 0 && (
          <ul className="mt-10 divide-y divide-ink-3 border-y border-ink-3">
            {agents.map((a) => (
              <li key={a.id}>
                <Link
                  to={`/build/${a.id}`}
                  className="grid grid-cols-[1fr_auto] sm:grid-cols-[minmax(0,2fr)_minmax(0,1.3fr)_7rem_6rem] items-center gap-x-6 gap-y-1 py-5 px-2 -mx-2 rounded-lg hover:bg-ink-2"
                >
                  <span className="min-w-0">
                    <span className="block font-bold text-lg truncate">{a.name}</span>
                    <span className="block text-sm text-dust truncate">{a.company || a.id}</span>
                  </span>
                  <StatusPill status={a.status} />
                  <span className="text-sm text-dust hidden sm:block">
                    {a.test_calls ? `${a.passed}/${a.test_calls} calls passed` : "not tested"}
                  </span>
                  <span className="text-sm text-dust hidden sm:block text-right">{when(a.updated)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
