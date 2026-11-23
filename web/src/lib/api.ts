// The setup API (laghu_voice/web/app.py).

export type Status =
  | "new" | "asking" | "questions" | "answered" | "queued" | "running"
  | "passed" | "needs_work" | "paused" | "stopped" | "approved";

export interface Job { agent: string; kind: "questions" | "setup"; state: "queued" | "running"; position: number }

export interface AgentSummary {
  id: string; name: string; company: string; status: Status; job: Job | null; updated: string | null;
  test_calls: number | null; passed: number | null; approved: { at: string; as: string } | null;
}

export interface SetupResult {
  ok: boolean; errors: string[]; warnings: string[]; check_rounds: number; minutes?: number; requests?: number;
  test_calls?: number; passed?: number; stopped?: string; approved?: { at: string; as: string };
}

export interface Answer { q: string; a: string }

export interface AgentDetail extends AgentSummary {
  description: string; questions: string[]; answers: Answer[] | null; result: SetupResult | null;
}

export type Cause = "spec" | "agent" | "caller" | "judge" | "unclear";

export interface Turn { who: "agent" | "caller"; text: string; roman: string; cut: number | null }

export interface Call {
  id: string; kind: string; name: string; round: number; expected: string; outcome: string | null; end: string | null;
  ok: boolean; facts: Record<string, string>; persona_facts: Record<string, unknown>; safety: string[];
  error: string | null; cause: Cause | null; why: string[]; seconds: number; transcript: Turn[];
}

export interface Line { key: string; kind: "fixed" | "llm"; text: string; roman: string; en: string; goal: string | null }

export interface State {
  name: string; say: string | null; expect: string | null; tool: string | null; commits: boolean;
  on: Record<string, string>; next: string | null; end: string | null; outcome: string | null;
}

export interface Review {
  id: string; result: SetupResult | null; agent: Record<string, string>; knowledge: Record<string, unknown>;
  slots: { name: string; type: string; describe: string; options: string[] }[]; states: State[]; lines: Line[];
  answers: Answer[]; calls: Call[]; warnings: string[]; review_md: string;
}

export interface QueueState { running: Job | null; waiting: Job[]; tokens: Record<string, number> }

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j?.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  agents: () => call<AgentSummary[]>("GET", "/api/agents"),
  agent: (id: string) => call<AgentDetail>("GET", `/api/agents/${id}`),
  create: (name: string, description: string) => call<AgentDetail>("POST", "/api/agents", { name, description }),
  setDescription: (id: string, description: string) =>
    call<AgentDetail>("PUT", `/api/agents/${id}/description`, { description }),
  setAnswers: (id: string, answers: Answer[]) => call<AgentDetail>("PUT", `/api/agents/${id}/answers`, { answers }),
  askQuestions: (id: string) => call<Job>("POST", `/api/agents/${id}/questions`),
  run: (id: string, simulate = true) => call<Job>("POST", `/api/agents/${id}/run`, { simulate }),
  review: (id: string) => call<Review>("GET", `/api/agents/${id}/review`),
  approve: (id: string) => call<AgentDetail & { installed: string; run: string }>("POST", `/api/agents/${id}/approve`),
  queue: () => call<QueueState>("GET", "/api/queue"),
};

export interface Example { id: string; title: string; description: string }
export const examples = () => call<Example[]>("GET", "/api/examples");
