import os
import zlib
import struct
import subprocess
from pathlib import Path

def create_png(width, height, color_fn):
    raw_data = bytearray()
    for y in range(height):
        raw_data.append(0)
        for x in range(width):
            r, g, b, a = color_fn(x, y, width, height)
            raw_data.extend([r, g, b, a])
    
    compressed = zlib.compress(bytes(raw_data), 9)
    
    def chunk(tag, data):
        length = len(data)
        crc = zlib.crc32(tag + data) & 0xffffffff
        return struct.pack(">I", length) + tag + data + struct.pack(">I", crc)
    
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    idat = chunk(b"IDAT", compressed)
    iend = chunk(b"IEND", b"")
    return header + ihdr + idat + iend

def icon_gradient_play(x, y, w, h):
    cx, cy = w / 2, h / 2
    corner_r = w * 0.22
    dx = abs(x - cx)
    dy = abs(y - cy)
    
    in_box = True
    if dx > (cx - corner_r) and dy > (cy - corner_r):
        dist = ((dx - (cx - corner_r))**2 + (dy - (cy - corner_r))**2)**0.5
        if dist > corner_r:
            in_box = False
            
    if not in_box:
        return 0, 0, 0, 0
    
    ratio = (x + y) / (w + h)
    r = int(79 + ratio * (139 - 79))
    g = int(70 + ratio * (92 - 70))
    b = int(229 + ratio * (246 - 229))
    
    px = (x - cx) / (w * 0.25)
    py = (y - cy) / (h * 0.25)
    
    if px >= -0.5 and px <= 0.7:
        max_y = (0.7 - px) * 0.65
        if abs(py) <= max_y:
            return 255, 255, 255, 255
            
    return r, g, b, 255

def create_ico(png_bytes, width, height):
    # ICO header (6 bytes)
    header = struct.pack("<HHH", 0, 1, 1)
    # Entry (16 bytes)
    w_byte = width if width < 256 else 0
    h_byte = height if height < 256 else 0
    entry = struct.pack("<BBBBHHII", w_byte, h_byte, 0, 0, 1, 32, len(png_bytes), 22)
    return header + entry + png_bytes

icons_dir = Path("src-tauri/icons")
icons_dir.mkdir(parents=True, exist_ok=True)

png_32 = create_png(32, 32, icon_gradient_play)
png_128 = create_png(128, 128, icon_gradient_play)
png_256 = create_png(256, 256, icon_gradient_play)
png_512 = create_png(512, 512, icon_gradient_play)

(icons_dir / "icon.png").write_bytes(png_512)
(icons_dir / "32x32.png").write_bytes(png_32)
(icons_dir / "128x128.png").write_bytes(png_128)
(icons_dir / "128x128@2x.png").write_bytes(png_256)
(icons_dir / "icon.ico").write_bytes(create_ico(png_32, 32, 32))

try:
    iconset_dir = Path("/tmp/app.iconset")
    if iconset_dir.exists():
        import shutil
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir(parents=True)
    
    for size in [16, 32, 64, 128, 256, 512]:
        p = iconset_dir / f"icon_{size}x{size}.png"
        p.write_bytes(create_png(size, size, icon_gradient_play))
        if size <= 256:
            p2x = iconset_dir / f"icon_{size}x{size}@2x.png"
            p2x.write_bytes(create_png(size * 2, size * 2, icon_gradient_play))
            
    subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icons_dir / "icon.icns")], check=True)
    import shutil
    shutil.rmtree(iconset_dir)
    print("Generated icon.icns successfully")
except Exception as e:
    print(f"Notice: iconutil icns creation: {e}")

print("All icons successfully generated in src-tauri/icons/!")
