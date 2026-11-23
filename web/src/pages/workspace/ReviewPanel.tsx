import { useMemo, useState } from "react";
import type { Call, Review } from "@/lib/api";
import { outcomeWords } from "@/lib/words";
import { CauseChip } from "./BuildTest";
import Section from "./Section";

type Tab = "calls" | "lines" | "flow" | "facts";
type Script = "latin" | "hindi" | "both";

const TABS: { id: Tab; title: string }[] = [
  { id: "calls", title: "Test calls" },
  { id: "lines", title: "What it says" },
  { id: "flow", title: "Flow" },
  { id: "facts", title: "Facts and answers" },
];

function Said({ text, roman, script }: { text: string; roman: string; script: Script }) {
  if (script === "hindi") return <span className="hindi">{text}</span>;
  if (script === "latin") return <span>{roman}</span>;
  return (
    <>
      <span className="hindi block">{text}</span>
      <span className="block text-parchment/70 italic">{roman}</span>
    </>
  );
}

export default function ReviewPanel({ review }: { review: Review }) {
  const [tab, setTab] = useState<Tab>(review.calls.length ? "calls" : "lines");
  const [script, setScript] = useState<Script>("latin");

  return (
    <Section id="review" n={4} title="Review"
      aside={
        <div role="radiogroup" aria-label="Show Hindi as" className="flex rounded-full border border-ink-3 p-0.5 text-sm">
          {(["latin", "hindi", "both"] as Script[]).map((s) => (
            <button key={s} role="radio" aria-checked={script === s} onClick={() => setScript(s)}
                    className={`px-3 py-1 rounded-full ${script === s ? "bg-ink-3 text-parchment" : "text-dust hover:text-parchment"}`}>
              {s === "latin" ? "Latin letters" : s === "hindi" ? "Devanagari" : "Both"}
            </button>
          ))}
        </div>
      }>
      <div role="tablist" aria-label="Review" className="flex flex-wrap gap-1 border-b border-ink-3">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
                  className={`px-3.5 py-2 -mb-px border-b-2 ${tab === t.id ? "border-marigold text-parchment" : "border-transparent text-dust hover:text-parchment"}`}>
            {t.title}
            {t.id === "calls" && review.calls.length > 0 && <span className="ml-1.5 text-dust">{passedOf(review.calls)}</span>}
          </button>
        ))}
      </div>
      <div className="mt-5" role="tabpanel">
        {tab === "calls" && <Calls calls={review.calls} script={script} />}
        {tab === "lines" && <Lines review={review} script={script} />}
        {tab === "flow" && <Flow review={review} />}
        {tab === "facts" && <Facts review={review} />}
      </div>
    </Section>
  );
}

function passedOf(calls: Call[]): string {
  const latest = latest_(calls);
  return `${latest.filter((c) => c.ok).length}/${latest.length}`;
}

function latest_(calls: Call[]): Call[] {
  const by = new Map<string, Call>();
  for (const c of calls) if (!by.has(c.id) || c.round >= by.get(c.id)!.round) by.set(c.id, c);
  return [...by.values()].sort((a, b) => a.id.localeCompare(b.id));
}

function Calls({ calls, script }: { calls: Call[]; script: Script }) {
  const [all, setAll] = useState(false);
  const shown = useMemo(() => (all ? [...calls].sort((a, b) => a.id.localeCompare(b.id) || a.round - b.round) : latest_(calls)), [calls, all]);
  const [pick, setPick] = useState(0);
  const c = shown[Math.min(pick, shown.length - 1)];
  if (!calls.length) return <p className="text-dust">No test calls were run.</p>;
  const rounds = new Set(calls.map((x) => x.round)).size > 1;

  return (
    <div className="grid gap-5 lg:grid-cols-[17rem_minmax(0,1fr)]">
      <div>
        <ul className="space-y-1" aria-label="Calls">
          {shown.map((x, i) => (
            <li key={`${x.id}-${x.round}`}>
              <button onClick={() => setPick(i)} aria-current={c === x}
                      className={`w-full text-left rounded-lg px-3 py-2 ${c === x ? "bg-ink-3" : "hover:bg-ink-3/50"}`}>
                <span className="flex items-center gap-2">
                  <span className={`size-2 rounded-full ${x.ok ? "bg-ok" : "bg-[var(--c-agent)]"}`} aria-label={x.ok ? "passed" : "failed"} />
                  <span className="font-bold">{x.id}</span>
                  <span className="capitalize">{x.kind}</span>
                  {all && rounds && <span className="text-xs text-dust">round {x.round}</span>}
                  {!x.ok && x.cause && <span className="ml-auto"><CauseChip cause={x.cause} /></span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
        {rounds && (
          <label className="mt-3 flex items-center gap-2 text-sm text-dust">
            <input type="checkbox" checked={all} onChange={(e) => { setAll(e.target.checked); setPick(0); }} />
            Show calls from before each repair
          </label>
        )}
      </div>

      {c && (
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h3 className="display text-2xl">{c.name || c.id}, {c.kind}</h3>
            <span className={c.ok ? "text-ok font-bold" : "text-[var(--c-agent)] font-bold"}>{c.ok ? "Passed" : "Failed"}</span>
          </div>
          <p className="text-dust">
            Should end: {outcomeWords(c.expected)}. Ended: {outcomeWords(c.outcome)}
            {c.end ? ` (${c.end.replace(/_/g, " ")})` : ""}.{c.seconds ? ` ${Math.round(c.seconds)} s.` : ""}
          </p>

          {!c.ok && (c.why.length > 0 || c.safety.length > 0) && (
            <div className="mt-3 rounded-xl border border-ink-3 bg-ink-2/70 p-3.5">
              {c.cause && <div className="mb-1.5"><CauseChip cause={c.cause} /></div>}
              <ul className="space-y-1 text-parchment/90 list-disc pl-5">
                {c.why.map((w) => <li key={w} className="break-words">{w}</li>)}
                {c.safety.filter((s) => !c.why.some((w) => w.includes(s.slice(0, 40)))).map((s) => (
                  <li key={s} className="break-words">Safety: {s}</li>))}
              </ul>
            </div>
          )}

          {Object.keys(c.facts).length > 0 && (
            <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              {Object.entries(c.facts).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-dust">{k.replace(/_/g, " ")}</dt>
                  <dd className={v === "matched" ? "text-ok" : v === "no persona value" ? "text-dust" : "text-[var(--c-agent)]"}>
                    {v === "matched" ? "right" : v}
                  </dd>
                </div>
              ))}
            </dl>
          )}

          <ol className="mt-5 space-y-2.5" aria-label="Transcript">
            {c.transcript.map((t, i) => (
              <li key={i} className={`flex ${t.who === "caller" ? "justify-end" : ""}`}>
                <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 ${t.who === "agent" ? "bg-ink-2/90 rounded-bl-md" : "bg-maroon/40 rounded-br-md"}`}>
                  <p className="text-xs text-dust mb-0.5">
                    {t.who === "agent" ? "Agent" : "Caller"}
                    {t.cut != null && " (cut off halfway)"}
                  </p>
                  <Said text={t.text} roman={t.roman} script={script} />
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function Lines({ review, script }: { review: Review; script: Script }) {
  return (
    <>
      <p className="text-dust max-w-[46rem]">
        Fixed lines are said word for word. Written lines are composed fresh on each call from a goal; the example
        shows the style, and is said as it is if the fresh words fail a check.
      </p>
      <ul className="mt-5 divide-y divide-ink-3">
        {review.lines.map((l) => (
          <li key={l.key} className="py-3.5 grid gap-1 md:grid-cols-[13rem_minmax(0,1fr)] md:gap-5">
            <div>
              <p className="font-bold break-words">{l.key.replace(/_/g, " ")}</p>
              <p className="text-sm text-dust">{l.kind === "fixed" ? "Fixed" : "Written each call"}</p>
            </div>
            <div className="min-w-0">
              <p className="text-lg">{l.en || <span className="text-dust italic">No English meaning</span>}</p>
              <p className="mt-0.5 text-parchment/75"><Said text={l.text} roman={l.roman} script={script} /></p>
              {l.goal && <p className="mt-1 text-sm text-dust">Goal: {l.goal}</p>}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

function Flow({ review }: { review: Review }) {
  const lineEn = Object.fromEntries(review.lines.map((l) => [l.key, l.en]));
  return (
    <ol className="space-y-2.5">
      {review.states.map((s) => (
        <li key={s.name} className="rounded-xl border border-ink-3 bg-ink-2/60 px-4 py-3">
          <div className="flex flex-wrap items-baseline gap-x-3">
            <span className="font-bold">{s.name.replace(/_/g, " ")}</span>
            {s.end && <span className="text-sm text-marigold">ends the call: {outcomeWords(s.outcome)}</span>}
            {s.commits && <span className="text-sm text-[var(--c-caller)]">books or records something</span>}
          </div>
          <ul className="mt-1 text-sm text-parchment/85 space-y-0.5">
            {s.say && <li>Says: {lineEn[s.say] || s.say}</li>}
            {s.expect && <li>Waits for: {s.expect.replace(/_/g, " ")}</li>}
            {s.tool && <li>Runs: {s.tool}</li>}
            {Object.entries(s.on).map(([e, to]) => <li key={e}>If {e.replace(/_/g, " ")}: go to {to.replace(/_/g, " ")}</li>)}
            {s.next && <li>Then: {s.next.replace(/_/g, " ")}</li>}
          </ul>
        </li>
      ))}
    </ol>
  );
}

function Facts({ review }: { review: Review }) {
  return (
    <div className="grid gap-8 lg:grid-cols-2">
      <div>
        <h3 className="font-bold text-lg">What the agent may state as fact</h3>
        <dl className="mt-3 space-y-2.5">
          {Object.entries(review.knowledge).map(([k, v]) => (
            <div key={k}>
              <dt className="text-dust text-sm">{k.replace(/_/g, " ")}</dt>
              <dd className="break-words">{typeof v === "string" ? v : JSON.stringify(v)}</dd>
            </div>
          ))}
          {Object.keys(review.knowledge).length === 0 && <p className="text-dust">Nothing.</p>}
        </dl>
        <h3 className="mt-8 font-bold text-lg">What it asks the caller</h3>
        <ul className="mt-3 space-y-2">
          {review.slots.map((s) => (
            <li key={s.name}>
              <span className="font-bold">{s.name.replace(/_/g, " ")}</span>{" "}
              <span className="text-dust text-sm">{s.type}</span>
              <p className="text-parchment/85">{s.describe}{s.options.length ? ` Options: ${s.options.join(", ")}.` : ""}</p>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h3 className="font-bold text-lg">Your answers</h3>
        <dl className="mt-3 space-y-2.5">
          {review.answers.map((a) => (
            <div key={a.q}>
              <dt className="text-dust text-sm">{a.q}</dt>
              <dd>{a.a || <span className="italic text-dust">Not known. The agent won't state it.</span>}</dd>
            </div>
          ))}
          {review.answers.length === 0 && <p className="text-dust">No questions were answered.</p>}
        </dl>
        {review.warnings.length > 0 && (
          <>
            <h3 className="mt-8 font-bold text-lg">Checker warnings</h3>
            <ul className="mt-3 space-y-1.5 list-disc pl-5 text-parchment/85">
              {review.warnings.map((w) => <li key={w} className="break-words">{w}</li>)}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
