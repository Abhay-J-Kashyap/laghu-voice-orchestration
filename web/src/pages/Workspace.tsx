import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Grainient from "@/components/bits/Grainient";
import { Loader } from "@/components/Loader";
import StatusPill from "@/components/StatusPill";
import TopBar from "@/components/TopBar";
import { api, type AgentDetail, type Answer, type Review } from "@/lib/api";
import { useProgress } from "@/lib/progress";
import Describe from "./workspace/Describe";
import Questions from "./workspace/Questions";
import BuildTest from "./workspace/BuildTest";
import ReviewPanel from "./workspace/ReviewPanel";
import Approve from "./workspace/Approve";

const STEPS = [
  { id: "describe", title: "Describe" },
  { id: "questions", title: "Answer questions" },
  { id: "build", title: "Build and test" },
  { id: "review", title: "Review" },
  { id: "approve", title: "Approve" },
] as const;

export default function Workspace() {
  const { id } = useParams();
  const nav = useNavigate();
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!!id);
  const [acting, setActing] = useState(false);
  const reviewFor = useRef("");

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const a = await api.agent(id);
      setAgent(a);
      setError("");
      const key = `${id}:${a.updated}`;
      if (a.result && reviewFor.current !== key && !a.job) {
        reviewFor.current = key;
        setReview(await api.review(id));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    setAgent(null);
    setReview(null);
    reviewFor.current = "";
    setLoading(!!id);
    load();
  }, [id, load]);

  const progress = useProgress(id ?? null, epoch, load);

  // a link to a section (/build/mba#review) lands there once the section exists
  const jumped = useRef("");
  useEffect(() => {
    const hash = window.location.hash.slice(1);
    if (!hash || jumped.current === `${id}#${hash}`) return;
    const el = document.getElementById(hash);
    if (el) {
      jumped.current = `${id}#${hash}`;
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [id, agent, review]);

  // a job's milestones change what the page shows: refresh the agent then
  useEffect(() => {
    if (progress.finished || progress.stopped || progress.questions || progress.jobStatus === "started") load();
  }, [progress.finished, progress.stopped, progress.questions, progress.jobStatus, load]);

  // while a job waits or runs, the summary (queue position, status) is polled too
  useEffect(() => {
    if (!agent?.job) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [agent?.job, load]);

  const act = async (f: () => Promise<unknown>) => {
    setActing(true);
    setError("");
    try {
      await f();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setActing(false);
    }
  };

  const startJob = async (agentId: string, job: () => Promise<unknown>) => {
    await job();
    setEpoch((n) => n + 1);
    if (agentId === id) await load();
  };

  const create = (name: string, description: string, ask: boolean) =>
    act(async () => {
      const a = await api.create(name, description);
      if (ask) await api.askQuestions(a.id);
      else await api.setAnswers(a.id, []);
      nav(`/build/${a.id}`);
    });

  const saveDescription = (description: string) =>
    act(async () => { if (id) setAgent(await api.setDescription(id, description)); });

  const ask = () => act(() => startJob(id!, () => api.askQuestions(id!)));

  const answerAndBuild = (answers: Answer[], build: boolean) =>
    act(async () => {
      setAgent(await api.setAnswers(id!, answers));
      if (build) await startJob(id!, () => api.run(id!));
    });

  const run = () => act(() => startJob(id!, () => api.run(id!)));

  const approve = () =>
    act(async () => {
      await api.approve(id!);
      await load();
    });

  const status = agent?.status ?? "new";
  const busy = !!agent?.job;
  const reached = {
    describe: true,
    questions: !!agent && (status !== "new" || progress.job === "questions"),
    build: !!agent && (["queued", "running", "passed", "needs_work", "paused", "stopped", "approved"].includes(status)
      || progress.job === "setup" || !!agent.result),
    review: !!agent?.result && !(busy && agent.job?.kind === "setup"),
    approve: !!agent?.result && !(busy && agent.job?.kind === "setup"),
  };
  const current = !agent ? "describe"
    : status === "new" ? "describe"
    : ["asking", "questions", "answered"].includes(status) ? "questions"
    : ["queued", "running"].includes(status) ? "build"
    : status === "approved" ? "approve" : "review";

  return (
    <div className="relative min-h-screen">
      <div className="fixed inset-0 z-0" aria-hidden="true">
        <Grainient
          colors={["#16131f", "#2a1622", "#7a2e2a", "#c9772f", "#f0c98a"]}
          angle={62}
          flow={0.7}
          silk={0.3}
          saturation={0.82}
          contrast={0.95}
          grainAmount={0.07}
          speed={0.6}
          stir={0.6}
        />
      </div>
      <div className="relative z-10">
        <TopBar transparent />
        <div className="px-4 sm:px-8 lg:px-10 pb-16 pt-4 grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)] max-w-[88rem]">
          <aside className="lg:sticky lg:top-6 self-start pane p-5">
            <p className="display text-3xl leading-none break-words">{agent?.name ?? "New agent"}</p>
            {agent && <div className="mt-3"><StatusPill status={status} /></div>}
            <ol className="mt-6 space-y-1">
              {STEPS.map((s, i) => {
                const on = reached[s.id];
                const here = s.id === current;
                return (
                  <li key={s.id}>
                    <a
                      href={on ? `#${s.id}` : undefined}
                      aria-current={here ? "step" : undefined}
                      aria-disabled={!on}
                      className={`flex items-baseline gap-3 rounded-lg px-2 py-1.5 ${
                        here ? "bg-ink-3/80 text-parchment" : on ? "text-parchment/80 hover:bg-ink-3/50" : "text-dust/50"}`}
                    >
                      <span className={`display text-xl w-5 ${here ? "text-marigold" : ""}`}>{i + 1}</span>
                      {s.title}
                    </a>
                  </li>
                );
              })}
            </ol>
          </aside>

          <main className="min-w-0 space-y-6">
            {error && (
              <div className="pane p-4 border-[var(--c-agent)]/50 text-[var(--c-agent)]" role="alert">{error}</div>
            )}
            {loading ? (
              <div className="pane p-10"><Loader label="Opening this agent" /></div>
            ) : id && !agent && error ? null : (
              <>
                <Describe agent={agent} busy={busy || acting} onCreate={create} onSave={saveDescription} />
                {reached.questions && agent && (
                  <Questions agent={agent} progress={progress} busy={busy || acting} onAsk={ask}
                             onSubmit={answerAndBuild} />
                )}
                {reached.build && agent && (
                  <BuildTest agent={agent} progress={progress} review={review} busy={busy || acting} onRun={run} />
                )}
                {reached.review && review && <ReviewPanel review={review} />}
                {reached.approve && agent && (
                  <Approve agent={agent} review={review} busy={busy || acting} onApprove={approve} />
                )}
              </>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
