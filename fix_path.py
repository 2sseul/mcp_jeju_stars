import re
from pathlib import Path

CONST = {
    "jeju_sb_grid.npz": "path.SB_GRID",
    "jeju_2025_GeoTIFF_raw.tif": "path.SB_RAW",
    "jeju_2025_viirs_npp.tif": "path.VIIRS",
    "jeju_spots.json": "path.SPOTS",
}

files = [p for d in ("server", "scripts") if Path(d).exists()
         for p in Path(d).rglob("*.py") if p.name != "path.py"]

for f in files:
    lines = f.read_text(encoding="utf-8").splitlines(keepends=True)
    out, changed = [], False
    for ln in lines:
        hit = next((c for k, c in CONST.items() if k in ln), None)
        m = re.match(r"^(\s*[\w.]+)\s*=\s*", ln)
        if hit and m:
            out.append(f"{m.group(1)} = {hit}\n")
            changed = True
            print(f"  {f}: {ln.strip()}  ->  {m.group(1)} = {hit}")
            continue
        if re.search(r"Path\(__file__\)|_HERE\s*=|_ROOT\s*=|_BASE\s*=", ln):
            changed = True
            print(f"  {f}: 삭제  {ln.strip()}")
            continue
        out.append(ln)
    if changed:
        src = "".join(out)
        if "from server import path" not in src:
            idx = max((i for i, l in enumerate(out)
                       if l.startswith(("import ", "from "))), default=0)
            out.insert(idx + 1, "from server import path\n")
            src = "".join(out)
        f.write_text(src, encoding="utf-8")
        print(f"[수정] {f}\n")