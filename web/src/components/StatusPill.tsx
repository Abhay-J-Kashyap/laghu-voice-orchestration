import type { Status } from "@/lib/api";
import { STATUS } from "@/lib/words";
import { Loader } from "./Loader";

export default function StatusPill({ status }: { status: Status }) {
  const s = STATUS[status];
  const busy = status === "running" || status === "asking";
  return (
    <span className={`inline-flex items-center gap-1.5 text-sm font-bold ${s.tone}`}>
      {busy ? <Loader role="inline" size={13} /> : <span className="size-2 rounded-full bg-current" aria-hidden="true" />}
      {s.label}
    </span>
  );
}
