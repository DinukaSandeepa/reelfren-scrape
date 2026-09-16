#!/usr/bin/env python3
import os
import sys
import shutil
import platform
import subprocess
from pathlib import Path

# Ensure UTF-8 output on Windows runners (avoids cp1252 UnicodeEncodeError)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def get_target_triple():
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()
    if os.environ.get("TARGET_TRIPLE"):
        return os.environ.get("TARGET_TRIPLE").strip()
    
    try:
        res = subprocess.run(["rustc", "-vV"], stdout=subprocess.PIPE, text=True, check=True)
        for line in res.stdout.splitlines():
            if line.startswith("host:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
        
    arch = platform.machine().lower()
    if arch in ("arm64", "aarch64"):
        arch_str = "aarch64"
    elif arch in ("x86_64", "amd64"):
        arch_str = "x86_64"
    else:
        arch_str = arch

    if sys.platform == "darwin":
        return f"{arch_str}-apple-darwin"
    elif sys.platform == "win32":
        return f"{arch_str}-pc-windows-msvc"
    else:
        return f"{arch_str}-unknown-linux-gnu"

def main():
    target_triple = get_target_triple()
    print(f"[Sidecar] Building for target triple: {target_triple}")
    
    project_root = Path(__file__).resolve().parent.parent
    binaries_dir = project_root / "src-tauri" / "binaries"
    binaries_dir.mkdir(parents=True, exist_ok=True)
    
    sep = ";" if sys.platform == "win32" else ":"
    templates_path = f"templates{sep}templates"
    core_path = f"core{sep}core"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "reelfren-backend",
        "--add-data", templates_path,
        "--add-data", core_path,
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "camoufox",
        "--hidden-import", "wzgram",
        "--hidden-import", "warpcrypto",
        "--hidden-import", "aiosqlite",
        str(project_root / "run.py")
    ]
    
    print("[Sidecar] Running PyInstaller command...")
    subprocess.run(cmd, check=True, cwd=str(project_root))
    
    ext = ".exe" if sys.platform == "win32" else ""
    dist_bin = project_root / "dist" / f"reelfren-backend{ext}"
    target_bin = binaries_dir / f"reelfren-backend-{target_triple}{ext}"
    
    if not dist_bin.exists():
        print(f"Error: Expected binary not found at {dist_bin}", file=sys.stderr)
        sys.exit(1)
        
    shutil.copy2(dist_bin, target_bin)
    if sys.platform != "win32":
        target_bin.chmod(0o755)
        
    print(f"[Sidecar] SUCCESS: Sidecar binary created: {target_bin}")

if __name__ == "__main__":
    main()
