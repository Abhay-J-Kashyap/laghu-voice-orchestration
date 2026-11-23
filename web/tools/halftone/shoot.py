"""Saves the two hero renders from tools/halftone/index.html (served by `npx vite` from web/) to web/public.
    python tools/halftone/shoot.py [http://localhost:5173]"""
import asyncio, io, sys
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright

URL = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173") + "/tools/halftone/index.html"
PUBLIC = Path(__file__).resolve().parents[2] / "public"

async def main():
    async with async_playwright() as p:
        kw = {"args": ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]}
        if Path("/usr/bin/google-chrome").exists():
            kw["executable_path"] = "/usr/bin/google-chrome"
        b = await p.chromium.launch(**kw)
        pg = await b.new_page(viewport={"width": 2100, "height": 1200}, device_scale_factor=1)
        await pg.goto(URL)
        await pg.wait_for_timeout(4000)
        for name in ("hero-default", "hero-mosaic"):
            png = await (await pg.query_selector(f"#{name}")).screenshot()
            out = PUBLIC / f"{name}.webp"
            Image.open(io.BytesIO(png)).convert("RGB").save(out, "WEBP", quality=80)
            print(out.name, out.stat().st_size // 1024, "KB")
        await b.close()

asyncio.run(main())
