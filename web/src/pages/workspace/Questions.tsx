import { useEffect, useState } from "react";
import { Loader } from "@/components/Loader";
import type { AgentDetail, Answer } from "@/lib/api";
import type { Progress } from "@/lib/progress";
import Section from "./Section";

export default function Questions({ agent, progress, busy, onAsk, onSubmit }: {
  agent: AgentDetail; progress: Progress; busy: boolean;
  onAsk: () => void; onSubmit: (answers: Answer[], build: boolean) => void;
}) {
  const asking = agent.job?.kind === "questions";
  const qs = agent.questions;
  const given = Object.fromEntries((agent.answers ?? []).map((a) => [a.q, a.a]));
  const [values, setValues] = useState<string[]>(qs.map((q) => given[q] ?? ""));
  const done = !!agent.answers && agent.status !== "questions";
  const [editing, setEditing] = useState(!done);

  useEffect(() => {
    setValues(qs.map((q) => given[q] ?? ""));
    setEditing(!(!!agent.answers && agent.status !== "questions"));
  }, [agent.id, qs.join("|"), agent.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const answers = () => qs.map((q, i) => ({ q, a: values[i]?.trim() ?? "" }));

  if (asking) {
    return (
      <Section id="questions" n={2} title="Questions about the business">
        {agent.job?.state === "queued" ? (
          <Loader role="page" label={`Waiting its turn: ${agent.job.position} job(s) ahead`} />
        ) : (
          <Loader role="thinking" label="Reading your description and working out what it still needs to know" />
        )}
      </Section>
    );
  }

  if (progress.stopped && progress.job === "questions") {
    return (
      <Section id="questions" n={2} title="Questions about the business">
        <p className="text-[var(--c-agent)]">Setup couldn't ask its questions: {progress.stopped.error}</p>
        <button className="btn mt-4" disabled={busy} onClick={onAsk}>Ask again</button>
      </Section>
    );
  }

  if (!editing) {
    return (
      <Section id="questions" n={2} title="Your answers"
        aside={<button className="btn btn-quiet" disabled={busy} onClick={() => setEditing(true)}>Change answers</button>}>
        {qs.length === 0 ? (
          <p className="text-dust">No questions were asked. The agent states only what the description says.</p>
        ) : (
          <dl className="space-y-4 max-w-[46rem]">
            {qs.map((q, i) => (
              <div key={q}>
                <dt className="text-dust">{q}</dt>
                <dd className="mt-0.5">{values[i] || <span className="italic text-dust">Not known. The agent won't state it.</span>}</dd>
              </div>
            ))}
          </dl>
        )}
      </Section>
    );
  }

  return (
    <Section id="questions" n={2} title="Questions about the business">
      {qs.length === 0 ? (
        <>
          <p className="text-dust max-w-[42rem]">
            {agent.status === "questions"
              ? "Setup has no questions: the description covers what it needs."
              : "Setup hasn't asked anything yet. Its questions catch facts the description leaves out."}
          </p>
          <div className="mt-5 flex flex-wrap gap-3">
            {agent.status !== "questions" && (
              <button className="btn btn-quiet" disabled={busy} onClick={onAsk}>Get setup's questions</button>
            )}
            <button className="btn" disabled={busy} onClick={() => onSubmit([], true)}>Build and test</button>
          </div>
        </>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); onSubmit(answers(), true); }}>
          <p className="text-dust max-w-[42rem]">
            Short answers are fine. Leave one empty if you don't know: the agent will never state a fact you
            didn't give it.
          </p>
          <ol className="mt-6 space-y-5 max-w-[46rem]">
            {qs.map((q, i) => (
              <li key={q}>
                <label htmlFor={`q${i}`} className="flex gap-3">
                  <span className="text-marigold font-bold w-5 shrink-0">{i + 1}</span>
                  <span>{q}</span>
                </label>
                <input id={`q${i}`} className="field mt-2 ml-8 w-[calc(100%-2rem)]" value={values[i] ?? ""}
                       onChange={(e) => setValues((v) => v.map((x, k) => (k === i ? e.target.value : x)))} />
              </li>
            ))}
          </ol>
          <div className="mt-7 flex flex-wrap gap-3 ml-8">
            <button type="submit" className="btn" disabled={busy}>Save answers and build</button>
            <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => onSubmit(answers(), false)}>
              Save answers
            </button>
          </div>
        </form>
      )}
    </Section>
  );
}
