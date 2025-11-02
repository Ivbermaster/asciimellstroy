# app.py
from __future__ import annotations

import asyncio
import io
import json
import os
from functools import lru_cache
from typing import List, Iterable, Dict, Literal

from fastapi import FastAPI, HTTPException, Query, Path, Request
from fastapi.responses import StreamingResponse, PlainTextResponse, JSONResponse
from rich.console import Console

app = FastAPI(title="ASCII Streamer (JSON-only)", version="2.1")
base_dir = os.path.dirname(os.path.abspath(__file__))

# ------------ CONFIG ------------
DEFAULT_DELAY = 0.04
# Альт-экран выключен по умолчанию (чтобы зум/скролл терминала работали как раньше)
ALT_SCREEN_DEFAULT = False

# Реестр анимаций — ТОЛЬКО абсолютные пути
# banner_kind: "big" (многострочный логотип) или "ticker" (бегущая строка)
ANIMS: Dict[str, Dict[str, str]] = {
    "woohoo": {
        "json_path": os.path.join(base_dir, "assets/mellstroy2_ascii.json"),
        "banner_kind": "big",
        "banner_text": "MELLSTROY • STREAM • ASCII",
        "color": "0,255,180",
    },
    "clap": {
        "json_path": os.path.join(base_dir, "assets/mellstroy3_ascii.json"),
        "banner_kind": "big",
        "banner_text": "MELLSTROY • STREAM • ASCII",
        "color": "255,165,0",
    },
    "blyat": {
        "json_path": os.path.join(base_dir, "assets/mellstroy4_ascii.json"),
        "banner_kind": "big",
        "banner_text": "MELLSTROY • STREAM • ASCII",
        "color": "255,0,0",
    },
}

# Глобальная консоль Rich (TrueColor)
CONSOLE = Console(force_terminal=True, color_system="truecolor")

# ------------ BROWSER DETECTION ------------
def is_browser(req: Request) -> bool:
    ua = (req.headers.get("user-agent") or "").lower()
    accept = (req.headers.get("accept") or "").lower()
    ua_browser = any(k in ua for k in ["mozilla", "chrome", "safari", "edg", "firefox", "opera"])
    accept_html = "text/html" in accept
    return ua_browser or accept_html

BROWSER_HINT = (
    "Этот эндпоинт отдаёт поток ANSI-графики и предназначен для терминала.\n\n"
    "Открой через терминал, например:\n"
    "  curl -N http://<host>:<port>/a/roma?delay=0.04\n"
    "или под Windows PowerShell:\n"
    "  curl.exe -N http://<host>:<port>/a/roma?delay=0.04\n\n"
    "Список доступных анимаций: /a\n"
)

# ------------ BIG ASCII BANNER (как был) ------------
BANNER_BIG_RAW = r"""
                         /$$ /$$             /$$                                                                                  
                        | $$| $$            | $$                                                                                  
 /$$$$$$/$$$$   /$$$$$$ | $$| $$  /$$$$$$$ /$$$$$$    /$$$$$$   /$$$$$$  /$$   /$$      /$$$$$$   /$$$$$$  /$$$$$$/$$$$   /$$$$$$ 
| $$_  $$_  $$ /$$__  $$| $$| $$ /$$_____/|_  $$_/   /$$__  $$ /$$__  $$| $$  | $$     /$$__  $$ |____  $$| $$_  $$_  $$ /$$__  $$
| $$ \ $$ \ $$| $$$$$$$$| $$| $$|  $$$$$$   | $$    | $$  \__/| $$  \ $$| $$  | $$    | $$  \ $$  /$$$$$$$| $$ \ $$ \ $$| $$$$$$$$
| $$ | $$ | $$| $$_____/| $$| $$ \____  $$  | $$ /$$| $$      | $$  | $$| $$  | $$    | $$  | $$ /$$__  $$| $$ | $$ | $$| $$_____/
| $$ | $$ | $$|  $$$$$$$| $$| $$ /$$$$$$$/  |  $$$$/| $$      |  $$$$$$/|  $$$$$$$ /$$|  $$$$$$$|  $$$$$$$| $$ | $$ | $$|  $$$$$$$
|__/ |__/ |__/ \_______/|__/|__/|_______/    \___/  |__/       \______/  \____  $$|__/ \____  $$ \_______/|__/ |__/ |__/ \_______/
                                                                         /$$  | $$     /$$  \ $$                                  
                                                                        |  $$$$$$/    |  $$$$$$/                                  
                                                                         \______/      \______/                                   
""".splitlines()

PADDING = 10  # отступ для горизонтального скролла

def _normalize_banner_lines(lines: List[str], pad: int = PADDING) -> tuple[List[str], int]:
    """
    Делает все строки одинаковой ширины = max_len + pad.
    Возвращает (список_строк_фикс_ширины, width).
    """
    raw = [ln.rstrip() for ln in lines if ln.strip()]
    max_len = max((len(ln) for ln in raw), default=0)
    width = max_len + pad
    fixed = [ln.ljust(width) for ln in raw]
    return fixed, width

# Фиксируем «большой» баннер один раз при импорте
BANNER_BIG, BANNER_BIG_WIDTH = _normalize_banner_lines(BANNER_BIG_RAW, pad=PADDING)

def make_ticker_lines(text: str, pad: int = PADDING) -> tuple[List[str], int]:
    """
    Возвращает одинарный баннер-тикер в виде списка из одной строки фиксированной ширины и саму ширину.
    """
    text = " ".join(text.split())
    base = text if text else ""
    width = len(base) + pad
    return [base.ljust(width)], width

def shift_lines(lines: List[str], offset: int, total_width: int) -> Iterable[str]:
    """
    Сдвигает все строки на один и тот же оффсет по модулю общей ширины.
    Это гарантирует, что «рисунок» не будет расползаться между строками.
    """
    o = offset % max(1, total_width)
    for line in lines:
        # line гарантированно длины total_width
        yield line[o:] + line[:o]

def render_frame_with_banner(
    frame_rich_text: str,
    banner_lines: Iterable[str],
    banner_color: str,
) -> str:
    """
    Печатаем кадр + баннер в буфер, принудительно очищая остаток каждой строки (ESC[K),
    чтобы не оставались «хвосты». В конце кадра также очистим экран вниз (ESC[J).
    """
    buf = io.StringIO()
    CONSOLE.file = buf

    def print_line_and_clear(line: str = ""):
        # печатаем строку БЕЗ перевода, потом очищаем хвост, потом \n
        CONSOLE.print(line, end="")
        buf.write("\x1b[K")  # ESC[K — очистить до конца строки
        buf.write("\n")

    # 1) Кадр (многострочный Rich-текст): печатаем построчно, очищая хвост каждой
    for line in frame_rich_text.splitlines():
        print_line_and_clear(line)

    # 2) Пустая строка-разделитель
    print_line_and_clear("")

    # 3) Баннерные строки
    for ln in banner_lines:
        print_line_and_clear(f"[rgb({banner_color})]{ln}[/]")

    # 4) Очистка экрана вниз от текущей позиции (на случай, если предыдущий кадр был выше)
    buf.write("\x1b[J")  # ESC[J — очистить до конца экрана

    return buf.getvalue()

# ------------ JSON FRAMES CACHE ------------
@lru_cache(maxsize=32)
def load_json_frames(json_path: str) -> List[str]:
    if not os.path.isabs(json_path):
        raise ValueError(f"JSON path must be absolute: {json_path}")
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"JSON not found: {json_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise ValueError("JSON must be a non-empty list of frames (strings).")
    for i, fr in enumerate(data):
        if not isinstance(fr, str):
            raise ValueError(f"Frame #{i} is not a string.")
    return data

# ------------ STREAMER ------------
async def stream_json_with_banner(
    *,
    json_path: str,
    banner_kind: Literal["big", "ticker"],
    banner_text: str,
    banner_color: str,
    delay: float,
    alt_screen: bool,
):
    frames = load_json_frames(json_path)

    # стартовые/завершающие ANSI-последовательности
    if alt_screen:
        start = "\033[?1049h\033[2J\033[H\033[?25l"  # альт-экран + очистка + курсор в (1,1) + скрыть курсор
        end = "\033[?25h\033[?1049l"                 # показать курсор + вернуться с альт-экрана
    else:
        start = "\033[2J\033[H\033[?25l"             # обычный экран: очистка + курсор в (1,1) + скрыть курсор
        end = "\033[?25h"                            # показать курсор (без выхода из альт-экрана)

    # подготовка баннера (фиксированная ширина + общий модуль сдвига)
    if banner_kind == "big":
        banner_template = BANNER_BIG
        banner_width = BANNER_BIG_WIDTH
    else:
        banner_template, banner_width = make_ticker_lines(banner_text, pad=PADDING)

    try:
        yield start.encode("utf-8")
        banner_offset = 0
        n = len(frames)
        while True:
            for i in range(n):
                shifted = list(shift_lines(banner_template, banner_offset, banner_width))
                content = render_frame_with_banner(frames[i], shifted, banner_color)
                banner_offset += 1
                # просто «домой» и рисуем буфер (без тотальной очистки каждый кадр)
                yield ("\033[H" + content).encode("utf-8")
                await asyncio.sleep(delay)
    except asyncio.CancelledError:
        pass
    finally:
        try:
            yield end.encode("utf-8")
        except Exception:
            pass

# ------------ ROUTES ------------
@app.get("/", response_class=PlainTextResponse)
def index(request: Request) -> str:
    if is_browser(request):
        return PlainTextResponse(BROWSER_HINT, status_code=200)
    return (
        "ASCII Streamer (JSON-only) is running.\n\n"
        "Endpoints:\n"
        "  GET /a                 -> list available animations\n"
        "  GET /a/{name}          -> stream named animation (terminal only)\n"
        "       Query: delay (float), alt (bool), banner (big|ticker)\n"
        "  GET /healthz           -> liveness probe\n"
        "\n"
        "В браузере стримы не отображаются. Используй терминал (curl -N ...).\n"
    )

@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"

@app.get("/a", response_class=JSONResponse)
def list_anims():
    # валидация абсолютных путей

    for name, cfg in ANIMS.items():
        p = cfg.get("json_path", "")
        if not os.path.isabs(p):
            raise HTTPException(status_code=500, detail=f"Animation '{name}' has non-absolute json_path: {p}")
    return [name for name in ANIMS.keys()]


@app.get("/a/{name}")
async def stream_anim(
    request: Request,
    name: str = Path(..., description="Animation name from registry"),
    delay: float = Query(DEFAULT_DELAY, gt=0.0, le=1.0),
    alt: bool = Query(ALT_SCREEN_DEFAULT, description="Use alternate screen buffer"),
    banner: Literal["big", "ticker"] | None = Query(None, description="Override banner kind"),
):
    if is_browser(request):
        return PlainTextResponse(BROWSER_HINT, status_code=200)

    cfg = ANIMS.get(name)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Animation '{name}' not found")

    json_path = cfg["json_path"]
    if not os.path.isabs(json_path):
        raise HTTPException(status_code=500, detail=f"Animation '{name}' has non-absolute json_path: {json_path}")

    banner_kind = banner or cfg.get("banner_kind", "big")
    gen = stream_json_with_banner(
        json_path=json_path,
        banner_kind=banner_kind,                # "big" по умолчанию — как просил
        banner_text=cfg.get("banner_text", ""), # используется для ticker
        banner_color=cfg.get("color", "255,215,0"),
        delay=delay,
        alt_screen=alt,
    )
    headers = {"Cache-Control": "no-store"}
    return StreamingResponse(gen, media_type="text/plain; charset=utf-8", headers=headers)

# ------------ STARTUP ------------
@app.on_event("startup")
async def warmup_cache():
    # проверка абсолютных путей + мягкий прогрев
    for name, cfg in ANIMS.items():
        path = cfg.get("json_path")
        if not path or not os.path.isabs(path):
            raise RuntimeError(f"Animation '{name}' must have an absolute json_path: {path}")
        try:
            load_json_frames.cache_clear()
            _ = load_json_frames(path)
        except Exception:
            pass
