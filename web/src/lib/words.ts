// The words the interface uses for the system's states, in one place so every page says the same thing.
import type { Cause, Status } from "./api";

export const STATUS: Record<Status, { label: string; tone: string }> = {
  new: { label: "Not started", tone: "text-dust" },
  asking: { label: "Working out questions", tone: "text-marigold" },
  questions: { label: "Waiting for your answers", tone: "text-marigold" },
  answered: { label: "Ready to build", tone: "text-parchment" },
  queued: { label: "Waiting its turn", tone: "text-dust" },
  running: { label: "Building and testing", tone: "text-marigold" },
  passed: { label: "All test calls passed", tone: "text-ok" },
  needs_work: { label: "Some test calls failed", tone: "text-[var(--c-agent)]" },
  paused: { label: "Paused at the daily limit", tone: "text-[var(--c-caller)]" },
  stopped: { label: "Stopped with an error", tone: "text-[var(--c-agent)]" },
  approved: { label: "Approved", tone: "text-ok" },
};

export const CAUSE: Record<Cause, { label: string; means: string }> = {
  spec: { label: "Spec", means: "The agent's script can't do what the call needed. Setup repairs this." },
  agent: { label: "Engine", means: "The caller said the right thing and the engine misread it or got stuck." },
  caller: { label: "Test caller", means: "The simulated caller didn't stick to its own facts. Not the agent's fault." },
  judge: { label: "Judge", means: "The agent got it right in other words; the scoring was too strict." },
  unclear: { label: "Unclear", means: "The record doesn't show why. Read the transcript." },
};

export const OUTCOME: Record<string, string> = {
  success: "done what it was for",
  declined: "caller said no",
  transferred: "handed to a person",
  failed: "failed",
  no_contact: "no answer",
};

export function outcomeWords(o: string | null | undefined): string {
  return o ? OUTCOME[o] ?? o.replace(/_/g, " ") : "no ending";
}

export const DAILY_LIMIT = 200_000;        // Groq free tier, per model, counted over the last 24 hours
