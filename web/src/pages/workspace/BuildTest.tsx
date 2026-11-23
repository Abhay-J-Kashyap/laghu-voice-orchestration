import { Loader } from "@/components/Loader";
import type { AgentDetail, Cause, Review } from "@/lib/api";
import type { CallState, Progress, Stage } from "@/lib/progress";
import { CAUSE, DAILY_LIMIT, outcomeWords } from "@/lib/words";
import Section from "./Section";

const STAGES: { id: Stage; title: string }[] = [
  { id: "drafting", title: "Drafting" },
  { id: "checking", title: "Checking" },
  { id: "testing", title: "Test calls" },
  { id: "writing", title: "Writing the review" },
];

export function CauseChip({ cause }: { cause: Cause }) {
  return <span className={`cause-chip cause-${cause}`} title={CAUSE[cause].means}>{CAUSE[cause].label}</span>;
}

export default function BuildTest({ agent, progress, review, busy, onRun }: {
  agent: AgentDetail; progress: Progress; review: Review | null; busy: boolean; onRun: () => void;
}) {
  const job = agent.job?.kind === "setup" ? agent.job : null;
  const live = progress.job === "setup";
  const result = agent.result;
  const stopped = live ? progress.stopped : null;
  const running = !!job;

  const calls: CallState[] = live && progress.order.length
    ? progress.order.map((k) => progress.calls[k])
    : latestCalls(review);

  const stageAt = progress.finished ? STAGES.length : STAGES.findIndex((s) => s.id === progress.stage);

  return (
    <Section id="build" n={3} title="Build and test"
      aside={!running && <button className="btn btn-quiet" disabled={busy} onClick={onRun}>Run again</button>}>
      {job?.state === "queued" && (
        <Loader label={`Waiting its turn: ${job.position} job(s) ahead. Setup runs one at a time on Groq's free tier.`} />
      )}

      {live && job?.state !== "queued" && (
        <ol className="grid grid-cols-2 sm:grid-cols-4 gap-2" aria-label="Stages">
          {STAGES.map((s, i) => {
            const state = stopped && i === stageAt ? "stopped" : i < stageAt ? "done" : i === stageAt ? "active" : "later";
            return (
              <li key={s.id}
                  className={`rounded-xl px-3 py-2.5 border ${state === "active" ? "border-marigold/70 bg-marigold/10"
                    : state === "stopped" ? "border-[var(--c-agent)]/60" : "border-ink-3"}`}>
                <div className="flex items-center gap-2">
                  {state === "active" && running ? <Loader role="inline" />
                    : <span className={`size-2.5 rounded-full ${state === "done" ? "bg-ok" : state === "stopped" ? "bg-[var(--c-agent)]" : "bg-ink-3"}`} />}
                  <span className={state === "later" ? "text-dust" : ""}>{s.title}</span>
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {live && <Drafting progress={progress} running={running} />}

      {calls.length > 0 && (
        <div className="mt-7">
          <h3 className="font-bold text-lg">The eight test callers</h3>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {calls.map((c) => <CallTile key={c.id} c={c} />)}
          </ul>
          <Legend calls={calls} />
        </div>
      )}

      {live && progress.repairs.length > 0 && (
        <ul className="mt-5 space-y-1 text-dust">
          {progress.repairs.map((r) => (
            <li key={r.round}>
              Repair {r.round}: the failed calls ({r.failed.join(", ")}) went back to the setup model, and only
              those callers ring again.
            </li>
          ))}
        </ul>
      )}

      {stopped && (
        <div className="mt-6 rounded-xl border border-[var(--c-caller)]/50 bg-[var(--c-caller)]/10 p-4 max-w-[46rem]" role="status">
          {stopped.daily_limit ? (
            <>
              <p className="font-bold">Paused: Groq's daily token limit for the setup model is used up.</p>
              <p className="mt-1 text-parchment/85">
                Everything drafted and repaired so far is kept. Groq counts the last 24 hours, so tokens free up a
                day after they were used. Run again then and setup picks up where it stopped.
              </p>
            </>
          ) : (
            <>
              <p className="font-bold">Setup stopped.</p>
              <p className="mt-1 text-parchment/85 break-words">{stopped.error}</p>
            </>
          )}
        </div>
      )}

      {!running && result && <Outcome agent={agent} />}

      {live && Object.keys(progress.tokens).length > 0 && <Tokens tokens={progress.tokens} />}

      {live && progress.log.length > 0 && (
        <details className="mt-6">
          <summary className="cursor-pointer text-dust hover:text-parchment">Setup's log ({progress.log.length} lines)</summary>
          <pre className="mt-3 max-h-80 overflow-auto scroll-thin text-sm text-parchment/80 whitespace-pre-wrap bg-ink-2/80 rounded-xl p-4">
            {progress.log.join("\n")}
          </pre>
        </details>
      )}

      {!live && !result && !job && <p className="text-dust">Not built yet.</p>}
    </Section>
  );
}

function Drafting({ progress, running }: { progress: Progress; running: boolean }) {
  const d = progress.draft;
  const items: [string, string][] = [
    ["Persona, facts and what it asks", d.basics],
    ["Call flow", d.flow],
    [d.linesTotal ? `Lines, ${d.linesDone} of ${d.linesTotal}` : "Lines", d.lines],
  ];
  const last = progress.checks[progress.checks.length - 1];
  return (
    <div className="mt-6 grid gap-6 md:grid-cols-2">
      <div>
        <h3 className="font-bold">Drafting</h3>
        <ul className="mt-2 space-y-1.5">
          {items.map(([label, st]) => (
            <li key={label} className="flex items-center gap-2.5">
              {st === "start" && running ? <Loader role="thinking" size={16} />
                : <span className={`size-2 rounded-full ${st === "done" || st === "kept" ? "bg-ok" : "bg-ink-3"}`} />}
              <span className={st === "waiting" ? "text-dust" : ""}>{label}</span>
              {st === "kept" && <span className="text-sm text-dust">reused from the last run</span>}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h3 className="font-bold">Checking</h3>
        {progress.checkKept && <p className="mt-2 text-dust">Repairs from the last run reused.</p>}
        {progress.checks.length === 0 && !progress.checkKept && <p className="mt-2 text-dust">Waits for the draft.</p>}
        <ul className="mt-2 space-y-1.5">
          {progress.checks.map((c) => (
            <li key={c.round}>
              {c.round === 0 ? "First check" : `After repair ${c.round}`}:{" "}
              <span className={c.n ? "text-marigold" : "text-ok"}>
                {c.n ? `${c.n} problem${c.n > 1 ? "s" : ""}` : "no problems"}
              </span>
            </li>
          ))}
        </ul>
        {last && last.n > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-sm text-dust hover:text-parchment">What the checker found</summary>
            <ul className="mt-2 space-y-1 text-sm text-parchment/80 list-disc pl-5">
              {last.errors.map((e) => <li key={e} className="break-words">{e}</li>)}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}

function CallTile({ c }: { c: CallState }) {
  const failed = c.status === "done" && !c.ok;
  return (
    <li className={`rounded-xl border p-3.5 ${failed ? "border-[var(--c-agent)]/40" : c.status === "done" ? "border-ok/30" : "border-ink-3"} bg-ink-2/60`}>
      <div className="flex items-baseline gap-2">
        <span className="display text-2xl">{c.id}</span>
        <span className="font-bold capitalize">{c.kind}</span>
        {c.round > 1 && <span className="ml-auto text-xs text-dust">retest {c.round - 1}</span>}
      </div>
      <p className="mt-0.5 text-sm text-dust">Should end: {outcomeWords(c.expected)}</p>
      <div className="mt-2.5 min-h-7">
        {c.status === "running" && <Loader role="call" label="On the call" />}
        {c.status === "waiting" && <span className="text-dust">Waiting</span>}
        {c.status === "done" && c.ok && <span className="text-ok font-bold">Passed</span>}
        {failed && (
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[var(--c-agent)] font-bold">Failed</span>
              {c.cause && <CauseChip cause={c.cause} />}
            </div>
            <p className="mt-1 text-sm text-parchment/80">
              Ended: {outcomeWords(c.outcome)}.{c.why?.[0] ? ` ${c.why[0]}` : ""}
            </p>
          </div>
        )}
      </div>
    </li>
  );
}

function Legend({ calls }: { calls: CallState[] }) {
  const seen = [...new Set(calls.filter((c) => c.status === "done" && !c.ok && c.cause).map((c) => c.cause as Cause))];
  if (!seen.length) return null;
  return (
    <dl className="mt-4 space-y-1.5 text-sm max-w-[48rem]">
      {seen.map((k) => (
        <div key={k} className="flex gap-2 items-baseline">
          <dt><CauseChip cause={k} /></dt>
          <dd className="text-dust">{CAUSE[k].means}</dd>
        </div>
      ))}
    </dl>
  );
}

function Outcome({ agent }: { agent: AgentDetail }) {
  const r = agent.result!;
  if (r.stopped && !agent.job) return null;
  const all = !r.test_calls || r.passed === r.test_calls;
  return (
    <p className="mt-6 text-lg max-w-[48rem]">
      {r.ok ? `The checker passed${r.check_rounds ? ` after ${r.check_rounds} repair round${r.check_rounds > 1 ? "s" : ""}` : ""}.`
        : `The checker still finds ${r.errors.length} problem${r.errors.length === 1 ? "" : "s"}.`}{" "}
      {r.test_calls ? `${r.passed} of ${r.test_calls} test calls passed${all ? "." : "; the review shows why the others failed."}` : ""}
      {r.minutes != null && <span className="text-dust"> Took {r.minutes} min.</span>}
    </p>
  );
}

function Tokens({ tokens }: { tokens: Record<string, number> }) {
  const rows = [["Setup model", tokens.setup], ["Agent model", tokens.agent], ["Test-caller model", tokens.caller]]
    .filter(([, v]) => v != null) as [string, number][];
  return (
    <div className="mt-6 max-w-[34rem]">
      <h3 className="font-bold">Tokens used since the server started</h3>
      <ul className="mt-2 space-y-2">
        {rows.map(([label, v]) => (
          <li key={label}>
            <div className="flex justify-between text-sm"><span>{label}</span>
              <span className="text-dust">{v.toLocaleString()} of {DAILY_LIMIT.toLocaleString()} a day</span></div>
            <div className="mt-1 h-1.5 rounded-full bg-ink-3 overflow-hidden" role="meter" aria-label={label}
                 aria-valuenow={v} aria-valuemin={0} aria-valuemax={DAILY_LIMIT}>
              <div className="h-full bg-marigold" style={{ width: `${Math.min(100, (v / DAILY_LIMIT) * 100)}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function latestCalls(review: Review | null): CallState[] {
  if (!review) return [];
  const by = new Map<string, CallState>();
  for (const c of review.calls) {
    const old = by.get(c.id);
    if (!old || c.round >= old.round) {
      by.set(c.id, { id: c.id, kind: c.kind, expected: c.expected, name: c.name, round: c.round, status: "done",
        ok: c.ok, outcome: c.outcome, end: c.end, cause: c.cause, why: c.why, seconds: c.seconds });
    }
  }
  return [...by.values()].sort((a, b) => a.id.localeCompare(b.id));
}
