import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowDown } from "@/components/Arrow";
import FlowingMenu from "@/components/bits/FlowingMenu";
import InfiniteSpiral from "@/components/bits/InfiniteSpiral";
import HalftoneReveal from "@/components/bits/HalftoneReveal";
import TechText from "@/components/bits/TechText";
import type { FlowingMenuItem, SpiralItem } from "@/components/bits/index";
import { api, type AgentSummary, type QueueState } from "@/lib/api";
import "./landing.css";

/* Two screens. The hero (Laghu, one line, an arrow); a wheel notch, a key or the arrow plays one eased glide to
 * the index and the numbers, and the hero morphs on the way: its picture swells and blurs while the second
 * screen opens out from the arrow. The page's own scrollbar is hidden. On narrow screens the two simply stack. */

const GLIDE_MS = 1200;
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function useMorph() {
  const stage = useRef<HTMLDivElement>(null);
  const [on, setOn] = useState(false);
  const gliding = useRef(0);          // the animation frame of a glide in progress, 0 when none
  const quietUntil = useRef(0);       // a trackpad keeps sending wheel events after a glide: ignore them a moment

  // motion here is driven by the visitor's own scrolling, so it runs even when the system asks for less motion
  useEffect(() => {
    const narrow = window.matchMedia("(max-width: 900px)");
    const decide = () => setOn(!narrow.matches);
    decide();
    narrow.addEventListener("change", decide);
    return () => narrow.removeEventListener("change", decide);
  }, []);

  const glide = useRef((to: number) => {
    cancelAnimationFrame(gliding.current);
    const from = window.scrollY;
    if (Math.abs(to - from) < 1) return;
    const t0 = performance.now();
    const ms = GLIDE_MS * Math.min(1, 0.45 + Math.abs(to - from) / window.innerHeight * 0.55);
    const step = (now: number) => {
      const t = Math.min(1, (now - t0) / ms);
      window.scrollTo({ top: from + (to - from) * ease(t), behavior: "instant" as ScrollBehavior });
      if (t < 1) gliding.current = requestAnimationFrame(step);
      else { gliding.current = 0; quietUntil.current = performance.now() + 450; }
    };
    gliding.current = requestAnimationFrame(step);
  }).current;

  useEffect(() => {
    const root = document.documentElement;
    root.classList.add("landing-page");
    if (!on) return () => root.classList.remove("landing-page");
    let raf = 0;
    let settle: ReturnType<typeof setTimeout> | undefined;
    const busy = () => gliding.current !== 0 || performance.now() < quietUntil.current;
    const paint = () => {
      raf = 0;
      const p = Math.min(1, Math.max(0, window.scrollY / window.innerHeight));
      const el = stage.current;
      if (!el) return;
      el.style.setProperty("--p", p.toFixed(4));
      el.dataset.open = p > 0.92 ? "yes" : "no";
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(paint);
      // a scroll that stops part way (a dragged scrollbar, a touchpad) finishes the glide to the nearer screen
      clearTimeout(settle);
      settle = setTimeout(() => {
        if (busy()) return;
        const y = window.scrollY, h = window.innerHeight;
        if (y > 1 && y < h - 1) glide(y > h / 2 ? h : 0);
      }, 160);
    };
    const onWheel = (e: WheelEvent) => {
      if (Math.abs(e.deltaY) < 1) return;
      const h = window.innerHeight;
      const open = window.scrollY >= h - 2;
      // over the numbers, once open, the wheel turns the spiral instead
      if (open && (e.target as Element | null)?.closest?.(".second-numbers")) return;
      e.preventDefault();
      if (busy()) return;
      if (e.deltaY > 0 && !open) glide(h);
      else if (e.deltaY < 0 && window.scrollY > 1) glide(0);
    };
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as Element | null)?.closest?.("input, textarea, select, [contenteditable]")) return;
      const h = window.innerHeight;
      if (["ArrowDown", "PageDown", " "].includes(e.key) && window.scrollY < h - 1) { e.preventDefault(); glide(h); }
      else if (["ArrowUp", "PageUp"].includes(e.key) && window.scrollY > 1) { e.preventDefault(); glide(0); }
    };
    paint();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    window.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("keydown", onKey);
    return () => {
      root.classList.remove("landing-page");
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("keydown", onKey);
      cancelAnimationFrame(raf);
      cancelAnimationFrame(gliding.current);
      clearTimeout(settle);
    };
  }, [on, glide]);
  return { on, stage, glide };
}

export default function Landing() {
  const { on, stage, glide } = useMorph();
  const second = useRef<HTMLElement>(null);
  const down = () => {
    if (on) glide(window.innerHeight);
    else second.current?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className={on ? "morph-track" : ""}>
      <div ref={stage} className={on ? "morph-stage" : ""} data-open="no">
        <Hero onDown={down} />
        <IndexAndNumbers ref={second} wheel={on} />
      </div>
    </div>
  );
}

function Hero({ onDown }: { onDown: () => void }) {
  return (
    <section className="hero" aria-label="Laghu">
      <HalftoneReveal
        className="hero-picture"
        src="/hero-default.webp"
        revealSrc="/hero-mosaic.webp"
        fit="cover"
        paperColor="#f2f1e8"
        shape="dot"
        cellSize={9}
        angle={30}
        revealRadius={150}
        softness={0.55}
        linger={1.4}
        ignoreReducedMotion
      />
      <div className="hero-copy">
        <div className="hero-word">
          <TechText
            text="Laghu"
            fontFamily="'Anek Latin Variable', 'Anek Latin', sans-serif"
            fontWeight={720}
            fontSize={320}
            letterSpacing={-0.03}
            color="#000000"
            accentColor="#b4471f"
            reveal="letter"
            intro="assemble"
            introDuration={1.8}
            specks={15}
            guides
            ignoreReducedMotion
          />
        </div>
      </div>
      {/* the line, split across the bottom corners on the photo's dark ground, either side of the arrow */}
      <div className="hero-foot">
        <p className="hero-tag">Laghu means small.</p>
        <div className="hero-tag-right">
          <p className="hero-tag">Its calls aren't.</p>
          <p className="hero-sub">A 7M-parameter Hindi voice, orchestrated into a whole phone agent.</p>
        </div>
      </div>
      <button className="hero-down" onClick={onDown} aria-label="Go to the index">
        <ArrowDown size={26} />
      </button>
    </section>
  );
}

const IndexAndNumbers = ({ ref, wheel }: { ref: React.RefObject<HTMLElement | null>; wheel: boolean }) => {
  const nav = useNavigate();
  const [agents, setAgents] = useState<AgentSummary[] | null>(null);
  const [queue, setQueue] = useState<QueueState | null>(null);

  useEffect(() => {
    api.agents().then(setAgents).catch(() => setAgents([]));
    api.queue().then(setQueue).catch(() => setQueue(null));
  }, []);

  const items: FlowingMenuItem[] = useMemo(() => {
    const list = agents ?? [];
    const running = queue?.running?.agent;
    const latest = [...list].sort((a, b) => (b.updated ?? "").localeCompare(a.updated ?? ""))[0];
    const tested = list.filter((a) => a.test_calls).sort((a, b) => (b.updated ?? "").localeCompare(a.updated ?? ""))[0];
    return [
      { text: "Build an agent", link: "/build/new", image: "/sprites/build.svg", meta: "describe a call" },
      { text: "Your agents", link: "/agents", image: "/sprites/agents.svg",
        meta: agents ? `${list.length} set up` : "" },
      { text: "Live build", link: running ? `/build/${running}` : latest ? `/build/${latest.id}` : "/build/new",
        image: "/sprites/live.svg", meta: running ? "running now" : "nothing running" },
      { text: "Review calls", link: tested ? `/build/${tested.id}#review` : "/agents", image: "/sprites/review.svg",
        meta: tested ? `${tested.passed}/${tested.test_calls} passed` : "no runs yet" },
    ];
  }, [agents, queue]);

  const kpis: SpiralItem[] = useMemo(() => {
    const list = agents ?? [];
    const runs = list.filter((a) => a.test_calls);
    const passed = runs.reduce((n, a) => n + (a.passed ?? 0), 0);
    const total = runs.reduce((n, a) => n + (a.test_calls ?? 0), 0);
    const facts: [string, string][] = [
      ["7M", "parameters in Laghu, the Hindi voice that speaks every line"],
      ["8", "kinds of simulated caller test every agent before it's approved"],
      [agents ? String(list.length) : "…", "agents set up from a plain-English description"],
      [total ? `${passed}/${total}` : "–", total ? "test calls passed in each agent's latest run" : "test calls run so far"],
      ["42/42", "scripted loan calls handled, none unsafe"],
      ["248", "automated checks pass on the engine and setup"],
    ];
    // two turns of the spiral, so it reads as a column rather than a ring of six
    return [0, 1].flatMap((turn) => facts.map(([value, label], i) => ({
      id: `${turn}-${i}`, src: `/grains/kpi-${i + 1}.webp`, alt: "", label: `${value} ${label}`,
      content: (
        <div className="kpi">
          <span className="kpi-value">{value}</span>
          <span className="kpi-label">{label}</span>
        </div>
      ),
    })));
  }, [agents]);

  return (
    <section ref={ref} className="second" aria-label="Index and numbers">
      <div className="second-menu">
        <FlowingMenu
          items={items}
          speed={40}
          stretch={0.3}
          magnet={0.15}
          followCursor={0.2}
          textColor="var(--p2-ink)"
          bgColor="var(--p2-bg)"
          marqueeBgColor="#ece7dc"
          marqueeTextColor="var(--p2-bg)"
          direction="alternate"
          duration={0.45}
          dimInactive
          align="left"
          showIndex
          showArrow
          imageShape="rounded"
          ariaLabel="Index"
          ignoreReducedMotion
          onItemClick={(item, _i, e) => {
            if (!item.link) return;
            e.preventDefault();
            nav(item.link);
          }}
        />
      </div>
      <div className="second-numbers">
        <InfiniteSpiral
          items={kpis}
          animationMode="all"
          wheel={wheel}
          ignoreReducedMotion
          speed={0.45}
          radius={150}
          cardWidth={244}
          cardHeight={162}
          verticalSpacing={112}
          edgeFade={0.35}
          perspective={1100}
          cardRadius={14}
          centerScale={1.15}
          edgeBlur={5}
          cardsPerTurn={7}
          pauseOnHover
        />
      </div>
    </section>
  );
};
