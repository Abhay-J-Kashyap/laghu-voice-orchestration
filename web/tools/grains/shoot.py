"""Saves each rendered tile from tools/grains/index.html (served by `npx vite` from web/) as a WebP in web/public.
    python tools/grains/shoot.py [http://localhost:5173]"""
import asyncio, io, sys
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright

URL = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173") + "/tools/grains/index.html"
PUBLIC = Path(__file__).resolve().parents[2] / "public"

async def main():
    async with async_playwright() as p:
        kw = {"args": ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]}
        if Path("/usr/bin/google-chrome").exists():
            kw["executable_path"] = "/usr/bin/google-chrome"
        b = await p.chromium.launch(**kw)
        pg = await b.new_page(viewport={"width": 520, "height": 900}, device_scale_factor=1)
        await pg.goto(URL)
        await pg.wait_for_timeout(2500)
        for el in await pg.query_selector_all(".tile"):
            name = await el.get_attribute("id")
            folder = PUBLIC / "grains"
            folder.mkdir(parents=True, exist_ok=True)
            png = await el.screenshot()
            out = folder / f"{name.removeprefix('sprite-')}.webp"
            Image.open(io.BytesIO(png)).convert("RGB").save(out, "WEBP", quality=88)
            print(out.relative_to(PUBLIC.parent), out.stat().st_size // 1024, "KB")
        await b.close()

asyncio.run(main())
