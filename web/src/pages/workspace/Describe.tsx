import { useEffect, useState } from "react";
import { examples as getExamples, type AgentDetail, type Example } from "@/lib/api";
import Prose from "@/components/Prose";
import Section from "./Section";

export default function Describe({ agent, busy, onCreate, onSave }: {
  agent: AgentDetail | null;
  busy: boolean;
  onCreate: (name: string, description: string, ask: boolean) => void;
  onSave: (description: string) => void;
}) {
  const [name, setName] = useState("");
  const [text, setText] = useState(agent?.description ?? "");
  const [editing, setEditing] = useState(!agent);
  const [examples, setExamples] = useState<Example[]>([]);

  useEffect(() => { setText(agent?.description ?? ""); setEditing(!agent); }, [agent?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!agent) getExamples().then(setExamples).catch(() => setExamples([])); }, [agent]);

  const short = text.trim().length < 40;

  if (agent && !editing) {
    return (
      <Section id="describe" n={1} title="The call"
        aside={<button className="btn btn-quiet" disabled={busy} onClick={() => setEditing(true)}>Edit</button>}>
        <div className="max-h-80 overflow-auto scroll-thin">
          {agent.description ? <Prose text={agent.description} /> : <p className="text-dust">No description.</p>}
        </div>
      </Section>
    );
  }

  return (
    <Section id="describe" n={1} title={agent ? "Edit the description" : "Describe the call"}>
      {!agent && (
        <>
          <p className="text-dust max-w-[42rem]">
            Say who's calling whom and why, what the agent must find out, what counts as done, and when a person
            should take over. Prices, timings and rules help; anything missing, setup will ask you about.
          </p>
          <label className="block mt-6 font-bold" htmlFor="agent-name">Name</label>
          <input id="agent-name" className="field mt-2 max-w-md" value={name} placeholder="Clinic appointments"
                 onChange={(e) => setName(e.target.value)} />
        </>
      )}
      <label className="block mt-5 font-bold" htmlFor="agent-desc">What the call is for</label>
      <textarea id="agent-desc" className="field mt-2 min-h-64 max-w-[48rem]" value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="We are a small clinic in Lucknow. People call us to book an appointment with one of our three doctors..." />
      {!agent && examples.length > 0 && (
        <p className="mt-3 text-sm text-dust">
          Start from an example:{" "}
          {examples.map((x, i) => (
            <span key={x.id}>
              {i > 0 && ", "}
              <button type="button" className="underline underline-offset-4 hover:text-parchment"
                      onClick={() => { setText(x.description); if (!name) setName(x.title.split(":")[0]); }}>
                {x.title}
              </button>
            </span>
          ))}
        </p>
      )}
      <div className="mt-6 flex flex-wrap gap-3">
        {agent ? (
          <>
            <button className="btn" disabled={busy || short} onClick={() => { onSave(text); setEditing(false); }}>
              Save description
            </button>
            <button className="btn btn-quiet" disabled={busy} onClick={() => { setText(agent.description); setEditing(false); }}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <button className="btn" disabled={busy || short} onClick={() => onCreate(name, text, true)}>
              Save and get setup's questions
            </button>
            <button className="btn btn-quiet" disabled={busy || short} onClick={() => onCreate(name, text, false)}>
              Skip the questions
            </button>
          </>
        )}
      </div>
      {short && text.length > 0 && <p className="mt-3 text-sm text-dust">A few sentences at least, so setup has something to work from.</p>}
    </Section>
  );
}
