import { useState } from "react";
import type { AgentDetail, Review } from "@/lib/api";
import Section from "./Section";

export default function Approve({ agent, review, busy, onApprove }: {
  agent: AgentDetail; review: Review | null; busy: boolean; onApprove: () => void;
}) {
  const r = agent.result!;
  const [sure, setSure] = useState(false);
  const failed = (r.test_calls ?? 0) - (r.passed ?? 0);
  const approved = r.approved ?? agent.approved;
  const installed = approved?.as ? approved.as.replace(/\\/g, "/").replace(/^.*?(agents\/)/, "$1") : "";
  const command = `python -m laghu_voice.server --tts laghu --listen full --dialog agent --agent-spec ${installed}`;

  if (approved) {
    return (
      <Section id="approve" n={5} title="Approved">
        <p>
          Approved on {new Date(approved.at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
          {installed && <> and installed as <code className="text-marigold">{installed}</code></>}.
        </p>
        <p className="mt-4 text-dust">Start the voice server with this agent to take calls in Laghu's voice:</p>
        <pre className="mt-2 rounded-xl bg-ink-2/90 p-4 overflow-auto scroll-thin text-sm">{command}</pre>
        <p className="mt-4 text-dust max-w-[46rem]">
          Run setup again after changing the description or answers, then approve the new version: it replaces this
          one.
        </p>
      </Section>
    );
  }

  if (!r.ok) {
    return (
      <Section id="approve" n={5} title="Approve">
        <p className="max-w-[46rem]">
          The checker still finds problems in the agent, so it can't be approved yet. Change the description or
          the answers to cover them, then run again.
        </p>
        <ul className="mt-3 space-y-1 list-disc pl-5 text-parchment/85 max-w-[52rem]">
          {r.errors.map((e) => <li key={e} className="break-words">{e}</li>)}
        </ul>
      </Section>
    );
  }

  return (
    <Section id="approve" n={5} title="Approve">
      <p className="max-w-[46rem]">
        Approving installs this agent so the voice server can run it.
        {review ? ` It has ${review.lines.length} lines and ${review.states.length} steps in its flow.` : ""}
      </p>
      {failed > 0 && (
        <label className="mt-4 flex items-start gap-3 max-w-[46rem]">
          <input type="checkbox" className="mt-1.5" checked={sure} onChange={(e) => setSure(e.target.checked)} />
          <span>
            {failed} test call{failed > 1 ? "s" : ""} still fail. I've read why in the review and want to approve
            anyway.
          </span>
        </label>
      )}
      <button className="btn mt-5" disabled={busy || (failed > 0 && !sure)} onClick={onApprove}>
        Approve this agent
      </button>
    </Section>
  );
}
