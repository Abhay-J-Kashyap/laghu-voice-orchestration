// Renders the grain-gradient backgrounds (Paper shaders) once, so the page ships still images instead of a dozen
// live WebGL canvases. Run: npx vite, open /tools/grains/index.html, then tools/grains/shoot.py saves each tile.
import { createRoot } from "react-dom/client";
import { ShaderMount } from "@paper-design/shaders-react";
import { getShaderColorFromString, getShaderNoiseTexture, grainGradientFragmentShader, GrainGradientShapes,
  ShaderFitOptions } from "@paper-design/shaders";

// The blob shape calls clamp(0., 1., length(...)), arguments in the wrong order: GPUs happen to give the intended
// clamp(length(...), 0., 1.), the software renderer used here gives 0 (an empty tile). Put them in order.
const SHADER = grainGradientFragmentShader.replace(/clamp\(0\., 1\., length\(shape_uv \+ (f\d_traj)\)\)/g,
  "clamp(length(shape_uv + $1), 0., 1.)");

function GrainGradient(p: G & { width: number; height: number; speed: number; frame: number; rotation: number;
  offsetX: number; offsetY: number }) {
  const uniforms = {
    u_colorBack: getShaderColorFromString(p.colorBack), u_colors: p.colors.map(getShaderColorFromString),
    u_colorsCount: p.colors.length, u_softness: p.softness, u_intensity: p.intensity, u_noise: p.noise,
    u_shape: GrainGradientShapes[p.shape], u_noiseTexture: getShaderNoiseTexture(),
    u_fit: ShaderFitOptions.contain, u_scale: p.scale, u_rotation: p.rotation, u_offsetX: p.offsetX,
    u_offsetY: p.offsetY, u_originX: 0.5, u_originY: 0.5, u_worldWidth: 0, u_worldHeight: 0,
  };
  return <ShaderMount width={p.width} height={p.height} speed={p.speed} frame={p.frame}
                      fragmentShader={SHADER} uniforms={uniforms} />;
}

type G = { frame?: number; colors: string[]; colorBack: string; softness: number; intensity: number; noise: number;
  shape: "wave" | "ripple" | "dots" | "blob" | "sphere" | "corners" | "truchet"; scale: number };

// 1-4: the user's four (shaders.paper.design/grain-gradient links); 5-6: made to match them
export const GRAINS: G[] = [
  { colors: ["#c6750c", "#beae60", "#d7cbc6"], colorBack: "#000a0f", softness: 0.7, intensity: 0.15, noise: 0.5, shape: "wave", scale: 1 },
  { colors: ["#702d00", "#88ddae", "#2d0b1e"], colorBack: "#140a00", softness: 0.5, intensity: 0.5, noise: 0.5, shape: "ripple", scale: 0.5 },
  { colors: ["#700000", "#0080ff", "#f2ebca", "#33cc33"], colorBack: "#0a0000", softness: 1, intensity: 1, noise: 0.7, shape: "dots", scale: 0.6 },
  { colors: ["#3e6274", "#a49c74", "#568b50"], colorBack: "#0e0d16", softness: 0, intensity: 0.15, noise: 0.5, shape: "blob", scale: 1.3, frame: Number(new URLSearchParams(location.search).get("f") ?? 20000) },
  { colors: ["#b4471f", "#e9a23b", "#f2ebca"], colorBack: "#120f17", softness: 0.6, intensity: 0.3, noise: 0.5, shape: "sphere", scale: 0.9 },
  { colors: ["#1f4e5f", "#9ec5c9", "#c6750c"], colorBack: "#0b0e12", softness: 0.8, intensity: 0.25, noise: 0.55, shape: "corners", scale: 1 },
];

function Tile({ g, id, sprite }: { g: G; id: string; sprite?: string[] }) {
  return (
    <div className="tile" id={id}>
      <GrainGradient width={480} height={320} speed={0} frame={g.frame ?? 4000} rotation={0} offsetX={0} offsetY={0} {...g} />
      {sprite && (
        <div className="px">
          <svg viewBox={`0 0 ${sprite[0].length} ${sprite.length}`} shapeRendering="crispEdges">
            {sprite.flatMap((row, y) => [...row].map((c, x) =>
              c === "#" ? <rect key={`${x}-${y}`} x={x + 0.08} y={y + 0.08} width={0.84} height={0.84} rx={0.18} fill="#f4eee2" /> : null))}
          </svg>
        </div>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <>
    {GRAINS.map((g, i) => <Tile key={i} g={g} id={`kpi-${i + 1}`} />)}
  </>,
);
