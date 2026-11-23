// The hero's two looks of tools/halftone/photo.jpg, rendered once with Paper's halftone-dots shader
// (shaders.paper.design/halftone-dots): "default" is what the page shows, "mosaic" is what the cursor reveals.
// Run: npx vite, then python tools/halftone/shoot.py writes public/hero-default.webp and public/hero-mosaic.webp.
import { createRoot } from "react-dom/client";
import { HalftoneDots } from "@paper-design/shaders-react";

const W = 2048, H = 1147;            // the photo's shape (625 x 350), at a size that stays sharp full screen
const common = { image: "/tools/halftone/photo.jpg", width: W, height: H, grid: "hex" as const, inverted: false,
  grainSize: 0.5, scale: 1, fit: "cover" as const };

createRoot(document.getElementById("root")!).render(
  <>
    <div className="tile" id="hero-default">
      <HalftoneDots {...common} colorBack="#f2f1e8" colorFront="#2b2b2b" originalColors={false} type="gooey"
                    size={0.5} radius={1.25} contrast={0.4} grainMixer={0.2} grainOverlay={0.2} />
    </div>
    <div className="tile" id="hero-mosaic">
      <HalftoneDots {...common} colorBack="#000000" colorFront="#b2aeae" originalColors type="classic"
                    size={0.6} radius={2} contrast={0.01} grainMixer={0} grainOverlay={0} />
    </div>
  </>,
);
