"""The index sprites: 8 x 8 pixel icons in solid black on a clear background, as SVG (sharp at any size).
    python tools/sprites/make_sprites.py          # writes public/sprites/<name>.svg"""
from pathlib import Path

SPRITES = {               # 8 x 8: few, big pixels, each one visible
    "build":  ["......##", ".....##.", "....##..", "...##...", "..##....", ".##.....", "........", "##.##.##"],  # a pen and its line
    "agents": ["##......", "###.....", ".##.....", ".##.....", "..##....", "...##.##", "....####", ".....##."],  # a phone handset
    "live":   ["...#....", "...#..#.", ".#.#..#.", ".#.##.#.", "##.##.##", "##.##.##", "##.##.##", "########"],  # sound bars
    "review": ["########", "#......#", "#.....##", "#....#.#", "#.#.#..#", "#..#...#", "#......#", "########"],  # a tick in a frame
}

out = Path(__file__).resolve().parents[2] / "public" / "sprites"
out.mkdir(parents=True, exist_ok=True)
for name, rows in SPRITES.items():
    # a 3:2 box (the band's picture frame), the icon centred in it with a little room around; square pixels
    w, h, pad = 15, 10, 1
    ox = (w - len(rows[0])) / 2
    dots = "".join(f'<rect x="{ox + x + 0.05:g}" y="{pad + y + 0.05:g}" width="0.9" height="0.9" rx="0.05"/>'
                   for y, row in enumerate(rows) for x, c in enumerate(row) if c == "#")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" shape-rendering="geometricPrecision">'
           f'<g fill="#000">{dots}</g></svg>\n')
    (out / f"{name}.svg").write_text(svg, encoding="utf-8")
    print(name, len(svg), "bytes")
