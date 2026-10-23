"""Gera as vídeo-aulas da página "Aprendendo": telas (Pillow) + voz narrada (Piper) + vídeo (ffmpeg).

Uso (na raiz do projeto):
    pip install piper-tts pillow
    python tools/aulas/build.py            # todas as aulas
    python tools/aulas/build.py aula3      # só uma
Saída: assets/aulas/<id>.mp4, <id>.vtt e aulas.json.

A voz é baixada na primeira execução (pt_BR-faber-medium, do repositório rhasspy/piper-voices).
As capturas de tela ficam em tools/aulas/shots/ e podem ser refeitas com tools/aulas/capturas.py."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / "assets" / "aulas"
VOICE_DIR = HERE / "voz"
VOICE = "pt_BR-faber-medium"
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/" + VOICE
sys.path.insert(0, str(HERE))
from roteiros import AVISO, LESSONS  # noqa: E402

W, H = 1280, 720
BG, PANEL, LINE = (14, 17, 23), (24, 29, 38), (48, 54, 66)
TEXT, MUTED, DIM = (250, 250, 250), (154, 160, 168), (110, 116, 126)
ACCENT, GREEN, RED, AMBER = (38, 166, 154), (76, 175, 80), (239, 83, 80), (255, 193, 7)
FPS = 10
SILENCE_FRASE, SILENCE_FIM = 0.5, 1.0
_FD = "/usr/share/fonts/truetype/dejavu/"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_FD + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), size)


_EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿️‍]")


def clean(t: str) -> str:
    return _EMOJI.sub("", t).strip()


# ------------------------------------------------------------------ pronúncia (só para a voz)
_SPEAK = [("TradeBot", "Treide Bot"), ("Streamlit Community", "Estrimlit Comiunity"), ("OpenRouter", "Ópen Ráuter"),
          ("Binance", "Bainâns"), ("OKX", "O K X"), ("USDT", "U S D T"), ("worker", "uórker"), ("GitHub", "Guit Rab"),
          ("TradingView", "Treidin Viu"), ("Bollinger", "Bolinger"), ("SuperTrend", "Super Trend"), ("Ichimoku", "Ixímoku"),
          ("SOL", "Sol"), ("Ether", "Íter"), ("Bitcoin", "Bitcóin"), ("pullback", "púlbék"), ("Pullback", "Púlbék"),
          ("stop loss", "stop lóss"), ("take profit", "teik profit"), ("stop", "stópi"), ("Stop", "Stópi"), ("funding", "fândin"),
          ("timeframe", "taimfreime"), ("candles", "candôs"), ("candle", "candôl"), ("P L", "pê éle")]
_SHOW = [("U S D T", "USDT"), ("A T R", "ATR"), ("I A", "IA"), ("R S I", "RSI"), ("M A C D", "MACD"), ("A D X", "ADX"),
         ("V W A P", "VWAP"), ("P L", "P&L"), ("O K X", "OKX"), ("um vírgula cinco", "1,5")]


def to_speech(t: str) -> str:
    for a, b in _SPEAK:
        t = t.replace(a, b)
    return t


def to_caption(t: str) -> str:
    for a, b in _SHOW:
        t = t.replace(a, b)
    return t


# ------------------------------------------------------------------ desenho
def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, width: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=fnt) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def base(lesson: dict, idx: int, total: int, title: str | None) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 6], fill=ACCENT)
    d.text((56, 24), clean(f"AULA {lesson['id'][-1]}  ·  {lesson['titulo']}").upper(), font=font(15, True), fill=ACCENT)
    if title:
        d.text((56, 56), clean(title), font=font(42, True), fill=TEXT)
    d.rectangle([56, H - 40, W - 56, H - 36], fill=LINE)
    d.rectangle([56, H - 40, 56 + int((W - 112) * (idx + 1) / total), H - 36], fill=ACCENT)
    d.text((56, H - 28), "TradeBot · Aprendendo", font=font(13), fill=DIM)
    d.text((W - 56 - d.textlength(AVISO, font=font(13)), H - 28), AVISO, font=font(13), fill=DIM)
    return im, d


def bullets(d: ImageDraw.ImageDraw, items: list[str], foco, x: int, y: int, width: int, size: int = 29, gap: int = 22) -> int:
    f, fb = font(size), font(size, True)
    for i, raw in enumerate(items):
        t = clean(raw)
        active = foco == i
        dim = foco is not None and not active
        col = ACCENT if active else (DIM if dim else TEXT)
        lines = wrap(d, t, fb if active else f, width - 40)
        h = len(lines) * (size + 8)
        if active:
            d.rounded_rectangle([x - 14, y - 8, x + width, y + h + 4], 10, fill=PANEL)
            d.rectangle([x - 14, y - 8, x - 9, y + h + 4], fill=ACCENT)
        d.ellipse([x + 4, y + size // 2 - 4, x + 14, y + size // 2 + 6], fill=col)
        for j, ln in enumerate(lines):
            d.text((x + 30, y + j * (size + 8)), ln, font=fb if active else f, fill=col)
        y += h + gap
    return y


def img_titulo(lesson, idx, total, sc, foco):
    im, d = base(lesson, idx, total, None)
    d.ellipse([W // 2 - 70, 120, W // 2 + 70, 260], fill=PANEL, outline=ACCENT, width=5)
    n = lesson["id"][-1]
    d.text((W // 2, 190), n, font=font(78, True), fill=ACCENT, anchor="mm")
    fnt = font(54, True)
    for i, ln in enumerate(wrap(d, clean(sc["titulo"]), fnt, 1080)):
        d.text((W // 2, 345 + i * 68), ln, font=fnt, fill=TEXT, anchor="mm")
    d.text((W // 2, 345 + 68 * len(wrap(d, clean(sc["titulo"]), fnt, 1080)) + 30), clean(sc.get("sub", "")), font=font(28), fill=MUTED, anchor="mm")
    return im


def img_topicos(lesson, idx, total, sc, foco):
    im, d = base(lesson, idx, total, sc["titulo"])
    bullets(d, sc["itens"], foco, 70, 150, W - 140, size=30, gap=26)
    return im


def img_tela(lesson, idx, total, sc, foco):
    im, d = base(lesson, idx, total, sc["titulo"])
    src = Image.open(HERE / "shots" / sc["arquivo"]).convert("RGB")
    box = sc.get("recorte") or (300, 0, 1500, 880) if sc["arquivo"] not in ("daytrade.png",) or sc.get("recorte") else (300, 0, 1500, 880)
    cx0, cy0, cx1, cy1 = box if sc.get("recorte") else (300, 0, 1500, src.height)
    crop = src.crop((cx0, cy0, cx1, cy1))
    aspect = crop.width / crop.height
    top = aspect >= 2.2
    if top:
        mw, mh, ox, oy = W - 112, 250, 56, 140
    else:
        mw, mh, ox, oy = 760, H - 190, 56, 128
    s = min(mw / crop.width, mh / crop.height)
    crop = crop.resize((int(crop.width * s), int(crop.height * s)), Image.LANCZOS)
    rect = None
    dest = sc.get("destaques") or []
    if foco is not None and foco < len(dest) and dest[foco]:
        x0, y0, x1, y1 = dest[foco]
        rect = (int((max(x0, cx0) - cx0) * s), int((max(y0, cy0) - cy0) * s), int((min(x1, cx1) - cx0) * s), int((min(y1, cy1) - cy0) * s))
    if rect and rect[2] > rect[0] and rect[3] > rect[1]:
        over = Image.new("RGBA", crop.size, (0, 0, 0, 105))
        shot = crop.convert("RGBA")
        shot = Image.alpha_composite(shot, over)
        shot.paste(crop.crop(rect), rect[:2])
        crop = shot.convert("RGB")
        ImageDraw.Draw(crop).rectangle(rect, outline=ACCENT, width=4)
    d.rounded_rectangle([ox - 4, oy - 4, ox + crop.width + 4, oy + crop.height + 4], 6, outline=LINE, width=2)
    im.paste(crop, (ox, oy))
    if top:
        bullets(d, sc["itens"], foco, 70, oy + crop.height + 28, W - 140, size=24, gap=12)
    else:
        bullets(d, sc["itens"], foco, ox + crop.width + 50, 140, W - (ox + crop.width + 50) - 56, size=25, gap=20)
    return im


def img_fluxo(lesson, idx, total, sc, foco):
    im, d = base(lesson, idx, total, sc["titulo"])
    steps = sc["passos"]
    n = len(steps)
    bw, gap = 164, 34
    x0 = (W - (n * bw + (n - 1) * gap)) // 2
    y0 = 260
    for i, (name, sub) in enumerate(steps):
        x = x0 + i * (bw + gap)
        active = foco == i
        done = foco is not None and i < foco
        fill = ACCENT if active else PANEL
        d.rounded_rectangle([x, y0, x + bw, y0 + 150], 14, fill=fill, outline=ACCENT if (active or done) else LINE, width=3)
        d.text((x + bw // 2, y0 + 22), str(i + 1), font=font(20, True), fill=BG if active else (ACCENT if done else DIM), anchor="mm")
        for j, ln in enumerate(wrap(d, name, font(18, True), bw - 12)):
            d.text((x + bw // 2, y0 + 60 + j * 26), ln, font=font(18, True), fill=BG if active else (TEXT if (done or foco is None) else DIM), anchor="mm")
        for j, ln in enumerate(wrap(d, sub, font(15), bw - 16)):
            d.text((x + bw // 2, y0 + 110 + j * 19), ln, font=font(15), fill=BG if active else MUTED, anchor="mm")
        if i < n - 1:
            ax = x + bw + 4
            d.polygon([(ax, y0 + 69), (ax + gap - 10, y0 + 75), (ax, y0 + 81)], fill=ACCENT if (foco is not None and i < foco) else LINE)
    if foco is not None:
        d.text((W // 2, 470), clean(f"{steps[foco][0]}: {steps[foco][1]}"), font=font(30, True), fill=ACCENT, anchor="mm")
    return im


def _dashed(d, x0, x1, y, col, w=3):
    x = x0
    while x < x1:
        d.line([x, y, min(x + 14, x1), y], fill=col, width=w)
        x += 24


def img_escada(lesson, idx, total, sc, foco):
    im, d = base(lesson, idx, total, sc["titulo"])
    fb, f = font(24, True), font(22)
    if sc["modo"] == "fixo":
        top, ent, stp = 190, 360, 520
        for name, y, col, fi in (("ALVO (take profit)", top, GREEN, 2), ("ENTRADA", ent, TEXT, 0), ("STOP (stop loss)", stp, RED, 1)):
            on = foco == fi or foco is None
            _dashed(d, 140, 900, y, col, 5 if foco == fi else 3)
            d.text((920, y), name, font=fb if on else f, fill=col if on else DIM, anchor="lm")
        d.line([140, stp, 140, top], fill=LINE, width=3)
        for (ya, yb, lab, col, fi) in ((ent, stp, "1R  = risco", RED, 1), (top, ent, "2R  = ganho", GREEN, 2)):
            d.line([700, ya, 700, yb], fill=col, width=4)
            d.text((690, (ya + yb) // 2), lab, font=fb, fill=col, anchor="rm")
        pts = [(160, 400), (230, 360), (300, 380), (370, 330), (440, 340), (510, 280), (580, 250), (650, 190)]
        d.line(pts, fill=MUTED, width=4)
        d.ellipse([160 - 6, 360 - 6, 160 + 6, 360 + 6], fill=TEXT)
        d.text((W // 2, 610), "Quanto maior o ganho em R em relação ao risco, menos acertos você precisa para empatar.", font=f, fill=MUTED, anchor="mm")
    else:
        for k, (x0, x1, name) in enumerate(((60, 600, "ALVO FIXO"), (680, 1220, "SURFAR (stop móvel)"))):
            d.rounded_rectangle([x0, 150, x1, 560], 14, fill=PANEL, outline=ACCENT if (foco == k or (foco == 1 and k == 1) or foco is None) and foco != 0 or foco == k else LINE, width=3)
            d.text(((x0 + x1) // 2, 180), name, font=fb, fill=TEXT, anchor="mm")
        # alvo fixo
        ey, ty = 440, 260
        _dashed(d, 90, 570, ey, TEXT)
        _dashed(d, 90, 570, ty, GREEN, 4)
        d.text((100, ty - 16), "alvo", font=font(18), fill=GREEN)
        d.line([(110, 430), (170, 400), (230, 410), (300, 350), (370, 330), (440, 290), (500, 262)], fill=MUTED, width=4)
        d.text((330, 520), "sai aqui, com ganho limitado", font=font(19), fill=MUTED, anchor="mm")
        # surfar
        xs = [710, 770, 830, 890, 950, 1010, 1070, 1130, 1180]
        price = [440, 410, 420, 370, 380, 320, 330, 290, 385]
        dist = 70
        stop, run, hi = [], [], 9999
        be_on = False
        for p in price:
            hi = min(hi, p)
            run.append(hi + dist)
        stop = run
        if foco in (None, 1, 2, 3):
            d.line(list(zip(xs, price)), fill=MUTED, width=4)
        if foco in (None, 2, 3, 1):
            st = [stop[0]] + stop
            xs2 = [xs[0] - 20] + xs
            pts = []
            for i in range(len(xs2) - 1):
                pts += [(xs2[i], st[i]), (xs2[i + 1], st[i])]
            pts.append((xs2[-1], st[-1]))
            d.line(pts, fill=RED if foco in (None, 2, 1) else DIM, width=5 if foco == 2 else 3)
        _dashed(d, 700, 1190, 440, TEXT, 2)
        d.text((706, 452), "entrada", font=font(18), fill=TEXT)
        if foco in (None, 3):
            d.line([700, 440 - 4, 1190, 440 - 4], fill=AMBER, width=4 if foco == 3 else 2)
            d.text((1190, 425), "equilíbrio", font=font(18), fill=AMBER, anchor="rm")
        d.text((950, 520), "o stop só sobe; sai quando o preço recua até ele", font=font(19), fill=MUTED, anchor="mm")
        d.text((W // 2, 610), clean({0: "Alvo fixo: ganho limitado, saída certa.", 1: "Surfar: sem alvo, o ganho pode crescer enquanto houver tendência.",
                                      2: "O stop acompanha o preço a uma distância fixa (em ATR).", 3: "Opcional: stop no ponto de equilíbrio após certo ganho."}.get(foco, "")), font=fb, fill=ACCENT, anchor="mm")
    return im


def img_tabela(lesson, idx, total, sc, foco):
    im, d = base(lesson, idx, total, sc["titulo"])
    rows = sc["linhas"]
    lo, hi = foco if isinstance(foco, tuple) else ((foco, foco) if foco is not None else (None, None))
    y = 135
    for i, (a, b) in enumerate(rows):
        on = lo is not None and lo <= i <= hi
        if on:
            d.rounded_rectangle([60, y - 6, W - 60, y + 42], 8, fill=PANEL, outline=ACCENT, width=2)
        col = TEXT if (lo is None or on) else DIM
        d.text((90, y), a, font=font(27, on), fill=col)
        d.text((W - 90, y), b, font=font(27, True), fill=ACCENT if on else col, anchor="ra")
        y += 54
    return im


RENDER = {"titulo": img_titulo, "topicos": img_topicos, "tela": img_tela, "fluxo": img_fluxo, "escada": img_escada, "tabela": img_tabela}


# ------------------------------------------------------------------ voz
def load_voice():
    from piper import PiperVoice

    VOICE_DIR.mkdir(exist_ok=True)
    for ext in (".onnx", ".onnx.json"):
        p = VOICE_DIR / (VOICE + ext)
        if not p.exists():
            print("baixando", p.name)
            urllib.request.urlretrieve(VOICE_URL + ext, p)
    return PiperVoice.load(VOICE_DIR / (VOICE + ".onnx"))


def speak(voice, text: str) -> np.ndarray:
    from piper.config import SynthesisConfig

    cfg = SynthesisConfig(length_scale=1.12, noise_scale=0.55, noise_w_scale=0.7)  # mais lenta e suave
    parts = [c.audio_float_array for c in voice.synthesize(to_speech(text), cfg)]
    return np.concatenate(parts).astype(np.float32)


def ts(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def build(lesson: dict, voice, sr: int) -> dict:
    out_dir = OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    work = HERE / "_work" / lesson["id"]
    work.mkdir(parents=True, exist_ok=True)
    audio, cues, frames, chapters = [], [], [], []
    t = 0.0
    total = len(lesson["cenas"])
    for si, sc in enumerate(lesson["cenas"]):
        chapters.append({"t": round(t), "titulo": clean(sc["titulo"]), "fala": []})
        prev = -1
        for fi, (text, foco) in enumerate(sc["fala"]):
            wav = speak(voice, text)
            last = fi == len(sc["fala"]) - 1
            pad = SILENCE_FIM if last else SILENCE_FRASE
            n = len(wav) + int(pad * sr)
            n = int(np.ceil(n / sr * FPS) * sr / FPS)  # múltiplo de um quadro
            seg = np.zeros(n, dtype=np.float32)
            seg[:len(wav)] = wav
            dur = n / sr
            f = foco
            if sc["tipo"] == "tabela" and foco is not None:
                f = (prev + 1, foco)
                prev = foco
            img = RENDER[sc["tipo"]](lesson, si, total, sc, f)
            p = work / f"{si:02d}_{fi:02d}.png"
            img.save(p)
            frames.append((p, dur))
            audio.append(seg)
            cues.append((t, t + len(wav) / sr, to_caption(text)))
            chapters[-1]["fala"].append(to_caption(text))
            t += dur
    sig = np.concatenate(audio)
    rms = float(np.sqrt((sig ** 2).mean()))
    sig = np.tanh(sig * (0.12 / max(rms, 1e-6)) * 1.0)  # volume uniforme, sem estourar
    pcm = (sig * 32767 * 0.92).astype(np.int16)
    wav_path = work / "audio.wav"
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    listing = work / "frames.txt"
    with listing.open("w") as fh:
        for p, dur in frames:
            fh.write(f"file '{p.name}'\nduration {dur:.4f}\n")
        fh.write(f"file '{frames[-1][0].name}'\n")
    mp4 = out_dir / f"{lesson['id']}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(wav_path),
                    "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-tune", "stillimage",
                    "-c:a", "aac", "-b:a", "80k", "-ar", "22050", "-movflags", "+faststart", "-shortest", str(mp4)], check=True)
    vtt = out_dir / f"{lesson['id']}.vtt"
    vtt.write_text("WEBVTT\n\n" + "\n".join(f"{i + 1}\n{ts(a)} --> {ts(b)}\n{txt}\n" for i, (a, b, txt) in enumerate(cues)), encoding="utf-8")
    dur_total = len(sig) / sr
    print(f"{lesson['id']}: {dur_total / 60:.1f} min · {mp4.stat().st_size / 1e6:.1f} MB", flush=True)
    return {"id": lesson["id"], "titulo": lesson["titulo"], "resumo": lesson["resumo"], "duracao_s": round(dur_total),
            "video": f"assets/aulas/{lesson['id']}.mp4", "legenda": f"assets/aulas/{lesson['id']}.vtt", "capitulos": chapters}


def main() -> None:
    only = set(sys.argv[1:])
    voice = load_voice()
    sr = voice.config.sample_rate
    meta_path = OUT / "aulas.json"
    meta = {m["id"]: m for m in json.loads(meta_path.read_text(encoding="utf-8"))} if meta_path.exists() else {}
    for lesson in LESSONS:
        if only and lesson["id"] not in only:
            continue
        meta[lesson["id"]] = build(lesson, voice, sr)
    OUT.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps([meta[k] for k in sorted(meta)], ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
