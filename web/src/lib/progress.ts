// The progress stream (GET /api/agents/<id>/events, server-sent events) folded into what the page shows.
import { useEffect, useReducer, useRef } from "react";
import type { Cause } from "./api";

export type Stage = "questions" | "drafting" | "checking" | "testing" | "writing";
type StepStatus = "waiting" | "start" | "done" | "kept";

export interface CallState {
  id: string; kind: string; expected: string; name?: string; round: number;
  status: "waiting" | "running" | "done"; ok?: boolean; outcome?: string | null; end?: string | null;
  cause?: Cause | null; why?: string[]; seconds?: number;
}

export interface Progress {
  job: "questions" | "setup" | null;
  jobStatus: "none" | "queued" | "started" | "done";
  position: number;
  stage: Stage | null;
  draft: { basics: StepStatus; flow: StepStatus; lines: StepStatus; linesDone: number; linesTotal: number; fresh: boolean };
  checks: { round: number; n: number; errors: string[] }[];
  checkKept: boolean;
  calls: Record<string, CallState>;
  order: string[];
  repairs: { round: number; failed: string[] }[];
  log: string[];
  tokens: Record<string, number>;
  finished: Record<string, unknown> | null;
  stopped: { error: string; daily_limit: boolean } | null;
  questions: string[] | null;
  count: number;
}

const START: Progress = {
  job: null, jobStatus: "none", position: 0, stage: null,
  draft: { basics: "waiting", flow: "waiting", lines: "waiting", linesDone: 0, linesTotal: 0, fresh: false },
  checks: [], checkKept: false, calls: {}, order: [], repairs: [], log: [], tokens: {},
  finished: null, stopped: null, questions: null, count: 0,
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Event = Record<string, any>;

export function fold(p: Progress, e: Event): Progress {
  const next: Progress = { ...p, count: p.count + 1 };
  if (e.tokens) next.tokens = e.tokens;
  switch (e.type) {
    case "job":
      if (e.status === "queued") return { ...START, job: e.job, jobStatus: "queued", position: e.position ?? 0, count: next.count, tokens: next.tokens };
      next.job = e.job;
      next.jobStatus = e.status;
      return next;
    case "stage":
      next.stage = e.stage;
      return next;
    case "draft": {
      const d = { ...p.draft };
      if (e.step === "lines") {
        // a batch is written ("start" then "done") or reused from the last run ("kept")
        if (e.status === "start") d.fresh = true;
        const all = (e.done ?? 0) >= (e.total ?? 1);
        d.lines = e.status === "start" || !all ? "start" : d.fresh ? "done" : "kept";
        d.linesDone = e.done ?? d.linesDone;
        d.linesTotal = e.total ?? d.linesTotal;
      } else if (e.step === "basics" || e.step === "flow") {
        d[e.step as "basics" | "flow"] = e.status;
      }
      next.draft = d;
      return next;
    }
    case "check":
      if (e.status === "kept") next.checkKept = true;
      else next.checks = [...p.checks.filter((c) => c.round !== e.round), { round: e.round, n: e.n, errors: e.errors ?? [] }];
      return next;
    case "personas": {
      const calls: Record<string, CallState> = {};
      for (const x of e.personas) calls[x.id] = { id: x.id, kind: x.kind, expected: x.expected, name: x.name, round: 1, status: "waiting" };
      next.calls = calls;
      next.order = e.personas.map((x: Event) => x.id);
      return next;
    }
    case "call": {
      const old = p.calls[e.id] ?? { id: e.id, kind: e.kind, expected: e.expected ?? "", round: e.round, status: "waiting" };
      next.calls = {
        ...p.calls,
        [e.id]: e.status === "running"
          ? { ...old, round: e.round, status: "running", ok: undefined, cause: undefined, why: undefined }
          : { ...old, round: e.round, status: "done", ok: e.ok, outcome: e.outcome, end: e.end, cause: e.cause, why: e.why, seconds: e.seconds },
      };
      if (!next.order.includes(e.id)) next.order = [...p.order, e.id];
      return next;
    }
    case "repair":
      next.repairs = [...p.repairs, { round: e.round, failed: e.failed }];
      next.calls = { ...p.calls };
      for (const id of e.failed) if (next.calls[id]) next.calls[id] = { ...next.calls[id], status: "waiting" };
      return next;
    case "questions":
      next.questions = e.questions;
      return next;
    case "log":
      next.log = [...p.log.slice(-299), e.text];
      return next;
    case "finished":
      next.finished = e.result ?? {};
      return next;
    case "stopped":
      next.stopped = { error: e.error, daily_limit: !!e.daily_limit };
      return next;
    default:
      return next;
  }
}

type Action = { kind: "event"; e: Event } | { kind: "reset" };

function reducer(p: Progress, a: Action): Progress {
  return a.kind === "reset" ? START : fold(p, a.e);
}

/** Follows an agent's progress. `epoch` changes when a new job starts, so the stream is opened again. */
export function useProgress(agentId: string | null, epoch: number, onEnd?: () => void): Progress {
  const [p, dispatch] = useReducer(reducer, START);
  const endRef = useRef(onEnd);
  endRef.current = onEnd;

  useEffect(() => {
    if (!agentId) return;
    dispatch({ kind: "reset" });
    let seen = 0;
    let es: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const open = () => {
      es = new EventSource(`/api/agents/${agentId}/events?since=${seen}`);
      es.onmessage = (m) => {
        seen += 1;
        try {
          dispatch({ kind: "event", e: JSON.parse(m.data) });
        } catch { /* skip */ }
      };
      es.addEventListener("reset", () => {
        seen = 0;
        dispatch({ kind: "reset" });
      });
      es.addEventListener("end", () => {
        es?.close();
        endRef.current?.();
      });
      es.onerror = () => {
        es?.close();
        if (!closed) retry = setTimeout(open, 2000);
      };
    };
    open();
    return () => {
      closed = true;
      es?.close();
      clearTimeout(retry);
    };
  }, [agentId, epoch]);
  return p;
}
