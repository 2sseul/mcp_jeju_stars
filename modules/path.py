from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUTS = ROOT / "outputs"

SB_GRID    = DATA / "darkness" / "jeju_sb_grid.npz"
SB_RAW     = DATA / "light_pollution" / "jeju_2025_GeoTIFF_raw.tif"
VIIRS_GRID = DATA / "light_pollution" / "jeju_viirs_grid.npz"
VIIRS_RAW  = DATA / "light_pollution" / "jeju_2025_viirs_npp.tif"
EPHEM      = DATA / "ephem" / "de421.bsp"

# 표고 격자 — FABDEM(1초각 ~30m, 수관·건물 제거된 **맨땅**)을 제주만 잘라 담은 것.
# 도보 경로의 고도차·경사를 여기서 읽는다. 라이선스(CC BY-NC-SA)상 재배포하지
# 않으므로 **둘 다 커밋하지 않는다**(`.gitignore` 가 `data/elevation/` 전체를 뺀다).
# `scripts/build_elevation_grid.py` 를 한 번 돌리면 만들어진다.
DEM_GRID   = DATA / "elevation" / "jeju_dem_grid.npz"
DEM_RAW    = DATA / "elevation" / "N33E126_FABDEM_V1-2.tif"
SPOTS      = DATA / "jeju_spots.json"

LAMPS_JEJU     = DATA / "streetlight" / "jeju_streetlight.csv"
LAMPS_SEOGWIPO = DATA / "streetlight" / "seogwipo_streetlight.csv"

PARKING_JEJU     = DATA / "car_parking" / "jeju_car_parking.csv"
PARKING_SEOGWIPO = DATA / "car_parking" / "seogwipo_car_parking.csv"

# OpenStreetMap `amenity=parking`(Overpass). 공영 표준데이터가 담지 않는
# 오름·해변·관광지 주차장이 여기 있다. `scripts/fetch_osm_parking.py` 로 재수집한다.
PARKING_OSM = DATA / "car_parking" / "jeju_parking_osm.csv"

# 공중화장실 표준데이터. 원본에 좌표가 없어 `scripts/geocode_toilets.py` 가
# 위도·경도 컬럼을 채워 넣은 뒤부터 반경 조회에 쓸 수 있다.
TOILET = DATA / "toilet" / "jeju_toilet.csv"

# OSM 도로망(Overpass)과 세그먼트별 어둡기. 후보 발굴에서 '차로 닿는가'를 판정한다.
ROADS_OSM      = DATA / "road" / "jeju_roads_osm.json"
ROAD_DARKNESS  = DATA / "road" / "jeju_road_darkness.npz"

# 도로별 폭·차선·노면. 30MB 짜리 OSM 원본을 `core` 가 열 수 없어
# `scripts/build_road_tags.py` 가 잰 값만 작은 배열로 줄여 둔 것.
ROAD_TAGS      = DATA / "road" / "jeju_road_tags.npz"

# 주행 가능 도로만 이어 붙인 **연결 그래프**(CSR). 위 두 파일은 세그먼트를 흩어 놓은
# 것이라 "어디서 어디까지 몇 분"을 답하지 못한다 — 이어짐을 담는 것은 이 파일뿐이다.
# `scripts/build_road_graph.py` 가 만든다.
ROAD_GRAPH     = DATA / "road" / "jeju_road_graph.npz"

# 카카오 로컬 API 로 긁어 둔 장소(공원·휴게소 등).
# `scripts/fetch_kakao_places.py` 로 재수집한다.
KAKAO_PLACES = DATA / "kakao_places"

# 사람이 검토해 남긴 판단. 재생성할 수 없으므로 산출물이 아니라 **입력 데이터**다.
PARKING_REVIEW = DATA / "candidates" / "parking_review.jsonl"

# 지도에서 사람이 직접 찍어 둔 지점(주차장 목록에 없는 자리). 위와 같은 입력 데이터.
SPOT_PINS = DATA / "candidates" / "spot_pins.jsonl"

# Open-Meteo 응답 캐시(requests-cache 가 `.sqlite` 를 붙인다). 판정 결과가 아니라
# 외부 응답의 사본이라 지워도 재생성되지만, 지운 만큼 외부 호출이 다시 나간다.
# 작업 디렉터리가 아니라 저장소 루트에 두는 것은 어디서 실행하든 같은 캐시를 쓰기
# 위함이다. **파일이 아니라 디렉터리 안에 두는 것**은 컨테이너에서 `CACHE_DIR` 을
# 볼륨으로 잡기 위해서다 — 없는 파일 하나를 볼륨으로 마운트할 수는 없다.
CACHE_DIR      = ROOT / ".cache"
FORECAST_CACHE = CACHE_DIR / "forecast"

# 발표용 산출물(HTML). 저장소에 커밋하지 않는다 — 스크립트로 언제든 재생성한다.
LIGHT_MAP   = OUTPUTS / "jeju_light_map.html"
SPOT_REPORT = OUTPUTS / "jeju_spot_report.html"
