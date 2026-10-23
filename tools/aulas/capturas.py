"""Refaz as capturas de tela usadas nas aulas (precisa do app rodando em localhost:8501 e do Playwright).

    streamlit run app.py &            # outra porta? ajuste BASE
    python tools/aulas/capturas.py
"""
import asyncio
import glob
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://localhost:8501"
OUT = Path(__file__).resolve().parent / "shots"
PAGES = [("painel", "", 14000), ("carteira2", "carteira", 7000), ("bots", "bots", 9000), ("personalidades", "personalidades", 9000)]
SCROLL = [("dt_0", 620), ("dt_1", 1250), ("dt_3", 2550)]  # Day Trade rolado


async def main():
    OUT.mkdir(exist_ok=True)
    async with async_playwright() as p:
        exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome") or [None])[0]
        b = await p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 1500, "height": 880})
        for name, path, wait in PAGES:
            await pg.goto(f"{BASE}/{path}", wait_until="domcontentloaded")
            await pg.wait_for_timeout(wait)
            await pg.screenshot(path=str(OUT / f"{name}.png"))
        await pg.goto(f"{BASE}/day-trade", wait_until="domcontentloaded")
        await pg.wait_for_timeout(16000)
        await pg.screenshot(path=str(OUT / "daytrade.png"))
        for name, y in SCROLL:
            await pg.evaluate(f"document.querySelector('[data-testid=stMain]').scrollTo(0,{y})")
            await pg.wait_for_timeout(2500)
            await pg.screenshot(path=str(OUT / f"{name}.png"))
        await b.close()


asyncio.run(main())
