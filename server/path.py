from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SB_GRID    = DATA / "darkness" / "jeju_sb_grid.npz"
SB_RAW     = DATA / "raw" / "jeju_2025_GeoTIFF_raw.tif"
VIIRS      = DATA / "raw" / "jeju_2025_viirs_npp.tif"
EPHEM      = DATA / "ephem" / "de421.bsp"
SPOTS      = DATA / "jeju_spots.json"