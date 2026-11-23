// A use-case description as written (Markdown-ish): headings, lists and paragraphs, with the hard line breaks of
// the source file joined back into sentences.
export default function Prose({ text }: { text: string }) {
  const blocks = text.replace(/\r/g, "").split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
  return (
    <div className="space-y-3 max-w-[46rem] text-parchment/90">
      {blocks.map((b, i) => {
        if (/^#{1,6}\s/.test(b)) return <p key={i} className="font-bold text-lg text-parchment">{b.replace(/^#+\s*/, "")}</p>;
        const lines = b.split("\n");
        const items = lines.reduce<string[]>((acc, l) => {
          if (/^\s*[-*]\s+/.test(l)) acc.push(l.replace(/^\s*[-*]\s+/, ""));
          else if (acc.length) acc[acc.length - 1] += " " + l.trim();
          else acc.push("\u0000" + l.trim());
          return acc;
        }, []);
        const lead = items[0]?.startsWith("\u0000") ? items.shift()!.slice(1) : null;
        return (
          <div key={i}>
            {lead && <p>{lead}</p>}
            {items.length > 0 && (
              <ul className="list-disc pl-5 space-y-0.5">{items.map((x, k) => <li key={k}>{x}</li>)}</ul>
            )}
          </div>
        );
      })}
    </div>
  );
}
