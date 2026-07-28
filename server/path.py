from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUTS = ROOT / "outputs"

SB_GRID    = DATA / "darkness" / "jeju_sb_grid.npz"
SB_RAW     = DATA / "light_pollution" / "jeju_2025_GeoTIFF_raw.tif"
VIIRS_GRID = DATA / "light_pollution" / "jeju_viirs_grid.npz"
VIIRS_RAW  = DATA / "light_pollution" / "jeju_2025_viirs_npp.tif"
EPHEM      = DATA / "ephem" / "de421.bsp"
SPOTS      = DATA / "jeju_spots.json"

LAMPS_JEJU     = DATA / "streetlight" / "jeju_streetlight.csv"
LAMPS_SEOGWIPO = DATA / "streetlight" / "seogwipo_streetlight.csv"

# 발표용 산출물(HTML). 저장소에 커밋하지 않는다 — 스크립트로 언제든 재생성한다.
LIGHT_MAP   = OUTPUTS / "jeju_light_map.html"
