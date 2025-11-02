import json
from PIL import Image, ImageSequence

ASCII_CHARS = "@%#*+=-:. "
GIF_PATH = r"D:\Downloads\asciipython\mellstroy2.gif"
OUTPUT_JSON = r"D:\Downloads\asciipython\mellstroy2_ascii.json"
NEW_WIDTH = 100

def frame_to_ascii(frame, new_width=NEW_WIDTH):
    width, height = frame.size
    new_height = int(height / width * new_width * 0.55)
    frame = frame.resize((new_width, new_height))
    frame = frame.convert("RGB")

    lines = []
    for y in range(new_height):
        line = ""
        for x in range(new_width):
            r, g, b = frame.getpixel((x, y))
            brightness = int((r + g + b) / 3)
            index = brightness * (len(ASCII_CHARS) - 1) // 255
            char = ASCII_CHARS[index]
            line += f"[rgb({r},{g},{b})]{char}[/]"
        lines.append(line)
    return "\n".join(lines)

# --- Сохраняем все кадры в JSON ---
with Image.open(GIF_PATH) as img:
    frames_ascii = [frame_to_ascii(frame.copy()) for frame in ImageSequence.Iterator(img)]

with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
    json.dump(frames_ascii, f, ensure_ascii=False)
