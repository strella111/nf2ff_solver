# -*- coding: utf-8 -*-
"""Сборка build/FarZone.ico из far_zone/styles/glyphs/app.svg.

Нужна только для сборки .exe: PyInstaller берёт иконку файлом (.ico), а в
исходниках она живёт как SVG — один источник и для окна, и для экзешника.

Вызывается автоматически из build.py; можно и вручную:
    python build_icon.py

Отрисовка своя, на numpy, без Qt: инициализация графики есть не везде (в
headless-окружении Qt просто падает), а иконка не должна ронять сборку.
Поддержано ровно то, из чего сделан app.svg: скруглённый прямоугольник с
заливкой и обводка путей из отрезков и кубических кривых. PNG и ICO пишутся
руками — оба формата в этой части простые (Windows понимает PNG внутри ICO
начиная с Vista).
"""
from __future__ import annotations

import re
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
SVG = ROOT / 'far_zone' / 'styles' / 'glyphs' / 'app.svg'
OUT = ROOT / 'build' / 'FarZone.ico'
SIZES = (16, 24, 32, 48, 64, 128, 256)

_NUM = re.compile(r'[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?')


def _rgb(value):
    value = (value or '#000000').lstrip('#')
    return np.array([int(value[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def flatten_path(d, steps=16):
    """Путь -> список полилиний (списков точек). Поддержаны M/m, C/c, S/s, H/h, L/l."""
    tokens = re.findall(r'([MmLlHhVvCcSsZz])([^MmLlHhVvCcSsZz]*)', d)
    lines, current = [], []
    x = y = 0.0
    prev_ctrl = None
    for letter, raw in tokens:
        args = [float(n) for n in _NUM.findall(raw)]
        low = letter.lower()
        rel = letter.islower()
        if low == 'm':
            if current:
                lines.append(current)
            x, y = (x + args[0], y + args[1]) if rel else (args[0], args[1])
            current = [(x, y)]
            prev_ctrl = None
            args = args[2:]
            low = 'l'                      # последующие пары — линии
        while args:
            if low == 'l' and len(args) >= 2:
                nx, ny = (x + args[0], y + args[1]) if rel else (args[0], args[1])
                args = args[2:]
                current.append((nx, ny))
                x, y, prev_ctrl = nx, ny, None
            elif low == 'h' and args:
                nx = x + args[0] if rel else args[0]
                args = args[1:]
                current.append((nx, y))
                x, prev_ctrl = nx, None
            elif low == 'v' and args:
                ny = y + args[0] if rel else args[0]
                args = args[1:]
                current.append((x, ny))
                y, prev_ctrl = ny, None
            elif low in ('c', 's'):
                need = 6 if low == 'c' else 4
                if len(args) < need:
                    break
                base = (x, y) if rel else (0.0, 0.0)
                if low == 'c':
                    c1 = (base[0] + args[0], base[1] + args[1])
                    c2 = (base[0] + args[2], base[1] + args[3])
                    end = (base[0] + args[4], base[1] + args[5])
                else:
                    # s: первая контрольная — отражение предыдущей
                    c1 = (2 * x - prev_ctrl[0], 2 * y - prev_ctrl[1]) if prev_ctrl else (x, y)
                    c2 = (base[0] + args[0], base[1] + args[1])
                    end = (base[0] + args[2], base[1] + args[3])
                args = args[need:]
                for i in range(1, steps + 1):
                    t = i / steps
                    u = 1 - t
                    px = (u ** 3 * x + 3 * u * u * t * c1[0]
                          + 3 * u * t * t * c2[0] + t ** 3 * end[0])
                    py = (u ** 3 * y + 3 * u * u * t * c1[1]
                          + 3 * u * t * t * c2[1] + t ** 3 * end[1])
                    current.append((px, py))
                x, y, prev_ctrl = end[0], end[1], c2
            else:
                break
        if low == 'z' and current:
            current.append(current[0])
    if current:
        lines.append(current)
    return lines


def stroke_coverage(shape, polylines, width, scale):
    """Покрытие обводки: расстояние до полилинии <= половины толщины.

    Скруглённые концы и стыки получаются сами собой — расстояние до отрезка
    уже даёт круглую «шапку». Считаем только внутри рамки каждого отрезка,
    иначе на 256×256 это миллионы лишних точек.
    """
    cover = np.zeros(shape, dtype=float)
    radius = width * scale / 2.0
    pad = int(np.ceil(radius)) + 2
    for line in polylines:
        pts = np.asarray(line, dtype=float) * scale
        for (ax, ay), (bx, by) in zip(pts[:-1], pts[1:]):
            x0 = max(int(min(ax, bx)) - pad, 0)
            x1 = min(int(max(ax, bx)) + pad, shape[1])
            y0 = max(int(min(ay, by)) - pad, 0)
            y1 = min(int(max(ay, by)) + pad, shape[0])
            if x0 >= x1 or y0 >= y1:
                continue
            ys, xs = np.mgrid[y0:y1, x0:x1]
            px, py = xs + 0.5, ys + 0.5
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy
            if length2 < 1e-12:
                dist = np.hypot(px - ax, py - ay)
            else:
                t = np.clip(((px - ax) * dx + (py - ay) * dy) / length2, 0.0, 1.0)
                dist = np.hypot(px - (ax + t * dx), py - (ay + t * dy))
            alpha = np.clip(radius - dist + 0.5, 0.0, 1.0)
            block = cover[y0:y1, x0:x1]
            np.maximum(block, alpha, out=block)
    return cover


def rounded_rect_coverage(shape, w, h, rx, scale):
    """Покрытие скруглённого прямоугольника (знаковое расстояние)."""
    ys, xs = np.mgrid[0:shape[0], 0:shape[1]]
    px, py = xs + 0.5, ys + 0.5
    half_w, half_h, r = w * scale / 2, h * scale / 2, rx * scale
    qx = np.abs(px - half_w) - (half_w - r)
    qy = np.abs(py - half_h) - (half_h - r)
    outside = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
    inside = np.minimum(np.maximum(qx, qy), 0)
    return np.clip(0.5 - (outside + inside - r), 0.0, 1.0)


def over(dst_rgb, dst_a, src_rgb, src_a):
    """Наложение src на dst (premultiplied-free вариант «source over»)."""
    out_a = src_a + dst_a * (1 - src_a)
    safe = np.where(out_a > 1e-6, out_a, 1.0)
    out_rgb = (src_rgb * src_a[..., None]
               + dst_rgb * (dst_a * (1 - src_a))[..., None]) / safe[..., None]
    return out_rgb, out_a


def render(svg_text, size):
    """Отрисовать app.svg в массив RGBA (size × size)."""
    root = ET.fromstring(svg_text)
    view = [float(v) for v in root.get('viewBox').split()]
    scale = size / view[2]
    shape = (size, size)

    rgb = np.zeros(shape + (3,), dtype=float)
    alpha = np.zeros(shape, dtype=float)

    for el in root.iter():
        tag = el.tag.split('}')[-1]
        if tag == 'rect':
            cover = rounded_rect_coverage(shape, float(el.get('width')),
                                          float(el.get('height')),
                                          float(el.get('rx', 0)), scale)
            rgb, alpha = over(rgb, alpha, _rgb(el.get('fill')), cover)
        elif tag == 'path':
            width = float(el.get('stroke-width', 1))
            opacity = float(el.get('stroke-opacity', 1))
            cover = stroke_coverage(shape, flatten_path(el.get('d', '')), width, scale)
            rgb, alpha = over(rgb, alpha, _rgb(el.get('stroke')), cover * opacity)

    out = np.zeros(shape + (4,), dtype=np.uint8)
    out[..., :3] = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(np.round(alpha * 255), 0, 255).astype(np.uint8)
    return out


def encode_png(pixels):
    """RGBA-массив -> байты PNG (без внешних библиотек)."""
    height, width = pixels.shape[:2]
    raw = b''.join(b'\x00' + pixels[y].tobytes() for y in range(height))

    def chunk(kind, payload):
        body = kind + payload
        return (struct.pack('>I', len(payload)) + body
                + struct.pack('>I', zlib.crc32(body) & 0xffffffff))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9))
            + chunk(b'IEND', b''))


def write_ico(frames, out_path):
    header = struct.pack('<HHH', 0, 1, len(frames))    # reserved, type=icon, count
    entries, blobs = b'', b''
    offset = len(header) + 16 * len(frames)            # таблица кадров: по 16 байт
    for size, blob in frames:
        side = 0 if size >= 256 else size              # 256 кодируется нулём
        entries += struct.pack('<BBBBHHII', side, side, 0, 0, 1, 32,
                               len(blob), offset)
        offset += len(blob)
        blobs += blob
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(header + entries + blobs)


def main() -> int:
    if not SVG.exists():
        print(f'[build_icon] нет {SVG} — иконка не собрана')
        return 1
    svg_text = SVG.read_text(encoding='utf-8')
    frames = [(size, encode_png(render(svg_text, size))) for size in SIZES]
    write_ico(frames, OUT)
    print(f'[build_icon] {OUT} ({len(frames)} кадров, {OUT.stat().st_size} байт)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
