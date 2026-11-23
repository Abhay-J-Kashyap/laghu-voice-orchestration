import type { ReactNode } from "react";

export default function Section({ id, n, title, aside, children }: {
  id: string; n: number; title: string; aside?: ReactNode; children: ReactNode;
}) {
  return (
    <section id={id} className="pane p-5 sm:p-7 scroll-mt-6" aria-labelledby={`${id}-title`}>
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <span className="display text-4xl text-marigold" aria-hidden="true">{n}</span>
        <h2 id={`${id}-title`} className="display text-3xl sm:text-4xl">{title}</h2>
        {aside && <div className="ml-auto">{aside}</div>}
      </header>
      <div className="mt-5">{children}</div>
    </section>
  );
}
