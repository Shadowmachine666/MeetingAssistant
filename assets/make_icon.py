"""Генератор иконки MeetingAssistant: микрофон + звуковые волны (двухканальный диалог/перевод)."""
from PIL import Image, ImageDraw
from pathlib import Path

S = 1024  # рабочий холст (рендерим крупно, потом уменьшаем для чёткости)
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# --- Фон: скруглённый квадрат с вертикальным градиентом (индиго -> фиолетовый) ---
top = (79, 70, 229)      # indigo-600
bot = (139, 92, 246)     # violet-500
grad = Image.new("RGB", (1, S))
for y in range(S):
    t = y / (S - 1)
    grad.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
grad = grad.resize((S, S))

mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=220, fill=255)
img.paste(grad, (0, 0), mask)
d = ImageDraw.Draw(img)

W = (255, 255, 255, 255)
cx = S // 2

# --- Звуковые волны по обе стороны (двухканальность/диалог) ---
wave_c = (cx, 405)
for r in (250, 335):
    box = [wave_c[0] - r, wave_c[1] - r, wave_c[0] + r, wave_c[1] + r]
    d.arc(box, start=-48, end=48, fill=(255, 255, 255, 235), width=34)   # справа
    d.arc(box, start=132, end=228, fill=(255, 255, 255, 235), width=34)  # слева

# --- Микрофон: капсула ---
mic_w = 200
d.rounded_rectangle([cx - mic_w // 2, 250, cx + mic_w // 2, 600],
                    radius=mic_w // 2, fill=W)

# --- Держатель (U-образная дуга) ---
hr = 188
d.arc([cx - hr, 470 - hr, cx + hr, 470 + hr], start=18, end=162, fill=W, width=40)
# Ножка
d.rounded_rectangle([cx - 20, 470 + hr - 10, cx + 20, 760], radius=20, fill=W)
# Подставка
d.rounded_rectangle([cx - 110, 745, cx + 110, 790], radius=22, fill=W)

# --- Сохранение: уменьшаем и пишем многоразмерный .ico ---
out_dir = Path(__file__).parent
sizes = [16, 32, 48, 64, 128, 256]
frames = [img.resize((s, s), Image.LANCZOS) for s in sizes]
ico_path = out_dir / "MeetingAssistant.ico"
frames[-1].save(ico_path, format="ICO", sizes=[(s, s) for s in sizes])

# Превью для визуальной проверки
img.resize((256, 256), Image.LANCZOS).save(out_dir / "icon_preview.png")
print("OK:", ico_path)

# --- Копия иконки на локальный диск (C:), т.к. проект лежит на Google Drive.
# Ярлыки Windows должны ссылаться на локальную копию: иконку с виртуального
# диска G: Проводник читает ненадёжно и показывает белый лист.
import os
import shutil

local_dir = Path(os.environ["LOCALAPPDATA"]) / "MeetingAssistant"
local_dir.mkdir(parents=True, exist_ok=True)
local_ico = local_dir / "MeetingAssistant.ico"
shutil.copyfile(ico_path, local_ico)
print("Local copy:", local_ico)
