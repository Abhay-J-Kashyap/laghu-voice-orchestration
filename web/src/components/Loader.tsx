import type { ComponentType } from "react";

/* Dot Matrix loaders (dotmatrix.zzzzshawn.cloud), added with shadcn:
 *   npx shadcn@latest add @dotmatrix/dotm-square-3 @dotmatrix/dotm-circular-20 @dotmatrix/dotm-square-18 @dotmatrix/dotm-3x3-1
 * They land in src/components/ui/ and are picked up here by file name. Until they are added, a small dot grid of
 * our own stands in, so the page builds and runs either way. */
const found = import.meta.glob("./ui/dotm-*.tsx", { eager: true }) as Record<string, Record<string, unknown>>;

function fromFile(name: string): ComponentType<Record<string, unknown>> | null {
  const mod = found[`./ui/${name}.tsx`];
  if (!mod) return null;
  const hit = Object.entries(mod).find(([k, v]) => k.startsWith("Dotm") && typeof v === "function");
  return (hit?.[1] as ComponentType<Record<string, unknown>>) ?? null;
}

/** Which loader means what, used the same way on every page. */
const ROLES = {
  page: "dotm-square-3",        // Core Spiral: a page or panel is loading
  thinking: "dotm-circular-20", // Glyph Cycle: the setup model is writing (questions, drafts, repairs)
  call: "dotm-square-18",       // Sound Bars: a test call is in progress
  inline: "dotm-3x3-1",         // Square Spiral: inside a button or a line of text
} as const;

export type LoaderRole = keyof typeof ROLES;

export function Loader({ role = "page", size, label }: { role?: LoaderRole; size?: number; label?: string }) {
  const Dotm = fromFile(ROLES[role]);
  const px = size ?? (role === "inline" ? 16 : role === "call" ? 22 : 36);
  return (
    <span className="inline-flex items-center gap-2 text-[var(--marigold)]" role="status" aria-live="polite">
      {Dotm ? (
        <Dotm size={px} dotSize={Math.max(2, Math.round(px / 7))} color="currentColor" ariaLabel={label ?? "Working"} />
      ) : (
        <DotGrid size={px} />
      )}
      {label ? <span className="text-[var(--parchment)]/80">{label}</span> : <span className="sr-only">Working</span>}
    </span>
  );
}

function DotGrid({ size }: { size: number }) {
  const dot = Math.max(2, Math.round(size / 6));
  return (
    <span className="dotgrid" style={{ width: size, height: size, gap: (size - dot * 3) / 2 }} aria-hidden="true">
      {Array.from({ length: 9 }, (_, i) => (
        <i key={i} style={{ width: dot, height: dot, animationDelay: `${[0, 1, 2, 7, 8, 3, 6, 5, 4][i] * 90}ms` }} />
      ))}
    </span>
  );
}
