# star_research.md 수치 검증 보고서

검증일: 2026-07-23 / 대상 범위: 전체 (체크리스트 34개 항목)
대상 문서: `C:\Users\user\Desktop\iseul\mcp_jeju_star\common\star_research.md`
파생 구현 코드: **없음** (프로젝트에 `.py`/`.js` 소스 파일 부재. `common/`, `data/`의 GeoTIFF 4개와 `cr.json`(Crossref 응답 캐시)만 존재) → 문서–코드 상수 불일치 점검은 수행 불가. 대신 **보유 GeoTIFF 원본을 직접 디코딩해 문서의 데이터 주장과 대조**함.

---

## 요약

✅ 검증됨 **14건** · 🟡 조건부 **7건** · ⚠️ 미확인 **5건** · ❌ 불일치 **4건** · 🔵 관례 **4건**

### 우선 수정 권고

| 순위 | 항목 | 문제 | 심각도 |
| --- | --- | --- | --- |
| **1** | **[8] SQM→NELM 대응표** | 표의 값이 **문서가 인용한 공식의 계산 결과와 최대 1.08등급 어긋남.** 실제 표는 `NELM = SQM − 14.3` 이라는 별개의 선형식이며, 이 값이 e) 카탈로그 필터링의 기준선이 되므로 **보이는 천체 목록이 계통적으로 과다 산출됨** | ❌ 치명 |
| **2** | **[12] 대기량(X) 표** | 인용식 `X=(1−0.96sin²z)^−0.5` 로 계산하면 고도 30°→1.890, 20°→2.562, 10°→3.808. 문서 표는 1.62 / 2.05 / 3.13 으로 **최대 −20% 오차.** 게다가 문서 말미 예시("고도 25° → 대기량 2.4")는 표와도 인용식과도 다른 제3의 값(sec z 계열) | ❌ 치명 |
| **3** | **[27] 구름 층 고도 구분** | 문서의 `저층 ~2km / 중층 2–6km / 고층 6km~` 는 **WMO 온대역 정의(0–2 / 2–7 / 5–13 km)와도, 실제 사용 API인 Open-Meteo 정의(≤3 / 3–8 / >8 km)와도 불일치** | ❌ |
| **4** | **[33] Sönmez & Graefe (1998) 인용** | 논문은 실재하나 **"위험 회피형 / 위험 추구형 두 유형 구분"이라는 서술이 원문에 없음.** 오귀속 | ❌ |
| **5** | **[2] 영점 상수 1.08×10⁸** | 실재하는 관용 상수이나 **9550 K 흑체(Vega형) 스펙트럼 + Johnson V 밴드 전제에서만 유효.** LED·나트륨등이 지배하는 광해 하늘에 적용 시 계통 편의 존재(2500 K 광원 기준 영점은 12.25×10⁴로 +13%) | 🟡 영향 큼 |
| **6** | **[3] Bortle↔SQM 경계** | **Bortle(2001) 원문에 SQM 수치 경계가 존재하지 않음을 원문 전문으로 확인.** 프로젝트가 따르는 lightpollutionmap 기준은 개인 웹사이트(handprint.com) 표로 소급되며 1차 출처 없음 | ⚠️ 영향 큼 |
| **7** | **[1] 자연 밤하늘 0.171168465 mcd/m²** | 문서 내부 계산은 정확하나, **동일한 "22.00 mag/arcsec²"에 대해 Falchi et al. (2016)은 174 μcd/m² 를 사용**(1.6% 차이). 두 값을 혼용하면 Ratio·Bortle 경계가 어긋남 | 🟡 |

---

## 상세

# A. 광공해 · SQM

### [1] 자연 밤하늘 상수 0.171168465 mcd/m²

- **문서 기재**: `총밝기 = 인공밝기 + 0.171168465 (mcd/m², 자연 밤하늘 = 22.00 mag/arcsec²)`
- **판정**: 🟡 **조건부 검증**
- **근거 출처**
  - lightpollutionmap.info, *Help / FAQ #31* — **등급 [C]**
    원문: "Assuming that the natural brightness of the night sky is 22.00 mag./arc sec 2 or 0.171168465 mcd/m 2 , you can then calculate other properties: Total brightness: ARTIFICIAL_BRIGHTNESS + 0.171168465 mcd/m 2"
  - Falchi, F. et al. 2016, *The new world atlas of artificial night sky brightness*, Science Advances 2(6), e1600377, DOI 10.1126/sciadv.1600377 — **등급 [A]**
    원문: "We chose 22.0 mag/arcsec2, corresponding to 174 μcd/m2, as a typical brightness of the night sky background during solar minimum activity, excluding stars brighter than magnitude 7, away from Milky Way and from Gegenschein and zodiacal light."
- **검산**
  - `1.08e8 × 10^(−0.4×22.00) = 0.17116846478 mcd/m²` → 문서 값과 소수 10자리까지 일치 (차 −2.1×10⁻¹⁰). 즉 문서 상수는 **영점 1.08×10⁸ 에서 역산된 값**으로 내부적으로 정확.
  - Falchi의 174 μcd/m² 를 문서 공식에 넣으면 SQM = **21.982**, 즉 22.00이 아님. 174 μcd/m² 가 22.00에 대응하려면 영점이 1.0979×10⁸ 이어야 함.
- **차이/유의점**: 두 값 모두 "22.00 mag/arcsec²"라고 주장하지만 **1.6%(0.018 mag) 다름.** 원인은 영점 상수 차이([2] 참조). World Atlas 레이어(Falchi 기준)와 Sky Brightness 레이어(LPM 기준)를 섞어 쓰면 Ratio 및 Bortle 경계가 미세하게 어긋남.
- **권고**: 문서에 "이 상수는 lightpollutionmap의 영점 1.08×10⁸ 규약에서 역산한 값이며, Falchi et al.(2016)의 174 μcd/m²와 1.6% 차이가 있다. 본 프로젝트는 sb_2025 레이어를 쓰므로 LPM 규약을 따른다"고 명시.

---

### [2] 영점 상수 1.08×10⁸ (= 10.8×10⁴ cd/m²)

- **문서 기재**: `SQM = log10(총밝기 / 108000000) / (-0.4)`
- **판정**: 🟡 **조건부 검증**
- **근거 출처**
  - Bará, S. 2017, *Variations on a classical theme: On the formal relationship between magnitudes per square arcsecond and luminance*, International Journal of Sustainable Lighting, 19(1), 104–111 — **등급 [A]** (peer-reviewed)
  - Garstang, R. H. 1986, *Model for artificial night-sky illumination*, PASP 98, 364–375, DOI 10.1086/131768 — **등급 [A]**
  - Allen, C. W. 1973, *Astrophysical Quantities*, 3rd ed. — (Bará를 통한 간접 확인)
- **원문 확인 내용** (Bará 2017, §3, 전문 PDF 직접 확인)
  - Eq.(11): "L'VC ≈ 10.8 ×10⁴ ×10^(−0.4 mVJ)" — "An expression of this kind frequently used in light pollution studies"
  - Garstang(1986)의 실제 식은 Eq.(12) `b = 34.08 exp(20.7233 − 0.92104 V)` [nL] 이며, 이를 변환하면 **영점 10.85×10⁴** 가 나옴 ("Eq.(12) can be rewritten in the form of Eq.(11) with a zero-point luminance L'0,VC = 10.85 ×10⁴ cd·m⁻²")
  - Allen(1973) p.26 기반 → **10.89×10⁴**, p.197 기반 → **10.81×10⁴**, AB 절대등급 기반 CIE V(λ) → **10.96×10⁴**
  - 핵심 제약: "This equation can then be applied for transforming magnitudes to luminance, **provided that the source has a blackbody spectral radiance distribution with effective temperature 9550 K**, and the magnitudes are measured in the Johnson V band... **the zero-point luminance shall be modified if the source is a blackbody of different temperature, reaching a value of 12.25×10⁴ cd·m⁻² for 2500 K sources.**"
- **검산**: Garstang Eq.(12)를 V=22.00에 대입 → 54.008 nL = **171.91 μcd/m²** (문서 값 171.17 μcd/m² 대비 +0.43%). V=20.37 → 771.5 μcd/m² (문서 방식 768.1 μcd/m²).
- **차이/유의점**
  - 1.08×10⁴ 계열 상수는 **실재하고 광해 연구에서 관용적으로 쓰임 ✅**. 그러나 문서가 쓰는 정확히 `1.08×10⁸ mcd/m²`는 Garstang 원식(10.85)이 아니라 **Allen p.197 계열(10.81)에 가장 가까움.**
  - 근본 한계: **밴드 정의 의존.** SQM 계기는 CIE V(λ)와 다른 자체 밴드를 가지며, 광해 하늘의 스펙트럼은 9550 K 흑체와 거리가 멂(HPS ~2000 K, 4000 K LED). 저색온 광원 지배 지역에서는 영점이 최대 13% 높아야 함 → **SQM이 계통적으로 약 0.13 mag 낮게(밝게) 나올 수 있음.**
- **권고**: 문서 각주로 "영점 1.08×10⁴ cd/m²는 Garstang(1986)/Allen(1973) 계열의 관용 상수이며, 엄밀히는 9550 K 흑체·Johnson V 조건에서만 유효(Bará 2017). 광해 하늘 스펙트럼에서는 수 % 수준의 계통 편의가 존재" 를 추가.

---

### [3] Bortle 등급 ↔ SQM 경계값

- **문서 기재**: "→ Bortle 등급 경계값은 출처마다 조금씩 다름! 본프로젝트는 **lightpollutionmap.info 기준**으로 통일해 사용"
- **판정**: ⚠️ **출처 미확인** (1차 문헌 부재를 확인함)
- **근거 출처**
  - Bortle, J. E. 2001, *Introducing the Bortle Dark-Sky Scale*, Sky & Telescope, February 2001, pp. 126–129 — **원전(peer-reviewed 아님, 등급 미부여)**. skyandtelescope.org 배포 PDF 전문 확보·확인.
  - lightpollutionmap.info Help/FAQ #31 — **등급 [C]**
- **원문 확인 내용 (Bortle 2001 전문)**
  - **SQM 수치는 단 한 번도 등장하지 않음.** 각 등급은 (a) 맨눈 한계등급(NELM) 범위 + (b) 서술적 지표(황도광·M33·은하수 구조·구름의 밝기·망원경이 보이는 정도)로만 정의됨.
  - 오히려 Bortle 본인이 "Limiting Magnitude Isn't Enough / naked-eye limiting magnitude is a poor criterion. It depends too much on a person's visual acuity" 라고 명시.
  - Bortle 2001의 등급별 NELM: 1: 7.6–8.0 / 2: 7.1–7.5 / 3: 6.6–7.0 / 4: 6.1–6.5 / 5: 5.6–6.0 / 6: ~5.5 / 7: 5.0 / 8: 4.5 / 9: ≤4.0
- **추적 경로**: lightpollutionmap.info Help/FAQ #31 원문 HTML에서 `Bortle: SQM --> <a href="https://www.handprint.com/ASTRO/bortle.html">classification table</a>` 확인 → **handprint.com은 개인 취미 사이트(Bruce MacEvoy)이며, 해당 페이지는 SQM 경계값의 출처를 밝히지 않음.** 즉 프로젝트가 채택한 Bortle 경계는 **거부 등급 출처로 소급됨.**
- **참고 (handprint/LPM 경계값)**: 1: 22.00–21.99 / 2: 21.99–21.89 / 3: 21.89–21.69 / 4: 21.69–20.49 / 5: 20.49–19.50 / 6: 19.50–18.94 / 7: 18.94–18.38 / 8: <18.38.
  구간 폭이 0.01 mag(Class 1)에서 1.20 mag(Class 4)까지 **120배 차이나는 비상식적 분할**이며, 문헌 근거가 제시되지 않음.
- **검산 (내부 정합성 반증)**: 이 경계값 + 문서가 인용한 Schaefer NELM 공식을 결합하면 Class 1의 NELM은 **6.62**가 나옴. Bortle 2001의 Class 1 정의(NELM 7.6–8.0)와 **1.0–1.4등급 어긋남.** 즉 SQM→Bortle→NELM 세 축이 서로 닫히지 않음.
- **권고**
  1. "Bortle 등급"이라는 라벨을 계속 쓰려면 문서에 **"본 프로젝트의 Bortle 값은 lightpollutionmap.info의 SQM 구간 매핑을 따른 것이며, Bortle(2001) 원문은 SQM 경계를 정의하지 않는다"**를 명시.
  2. 대안: 문헌 근거가 확실한 **Falchi et al.(2016) Table 1의 인공/자연 밝기 비율 등급**(<0.01, 0.01–0.02, …, >41)을 1차 지표로 쓰고 Bortle은 참고 표기로 격하.

### [3-b] Bortle 등급 설명표의 서술

- **문서 기재**: `3 = 은하수가 아주 선명`, `4 = 은하수 잘 보임`, `5 = 교외 수준. 은하수는 보이지만 디테일이 조금 줄어듦`
- **판정**: 🟡 **조건부 검증** (원전과 강도 불일치)
- **원문 확인 내용 (Bortle 2001)**
  - Class 5 (Suburban sky): "The Milky Way is **very weak or invisible near the horizon and looks rather washed out overhead.**" → 문서의 "디테일이 조금 줄어듦"은 **원문보다 현저히 낙관적.**
  - Class 4: "The Milky Way well above the horizon is still impressive but **lacks all but the most obvious structure.**"
  - Class 3 (Rural): "The Milky Way still appears complex" — 문서의 "아주 선명"은 Bortle Class 2("highly structured... veined marble")에 가까움.
- **권고**: 등급 설명을 Bortle 2001 원문 서술로 교체하고 출처 표기. 특히 Class 5를 "은하수가 천정에서 뿌옇게 보이고 지평선 근처에서는 거의 안 보임"으로 수정.

---

### [4] SQM 등급 해석표 (22.0 = 산 정상급, 21.5 = 매우 좋은 시골 …)

- **문서 기재**: `22.0 매우 어두움(산 정상급) / 21.5 매우 좋은 시골 / 21.0 좋은 시골 / 20.3~20.5 보통 시골, 은하수는 보임 / 19~20 교외 / 18 이하 도시`
- **판정**: ⚠️ **출처 미확인**
- **추적 시도 경로**: (1) lightpollutionmap Help/FAQ 전문 HTML 검색 → 해당 표 없음. (2) Unihedron 공식 문서 → NELM↔MPSAS 변환식만 있고 서술 등급표 없음. (3) Bortle 2001 원문 → SQM 없음. (4) Falchi 2016 → 서술은 있으나 SQM 단위가 아닌 mcd/m² 비율 기준.
- **문헌으로 대조 가능한 지점 (Falchi et al. 2016, 등급 [A])**
  - "the orange level sets the point of artificial brightness that masks the summer Milky Way as well. This level corresponds to an approximate total sky brightness of between **20.6 and 20.0 mag/arcsec2**"
  - → 문서의 "20.3~20.5 = 은하수는 보임"은 **Falchi 기준으로는 여름 은하수가 가려지기 시작하는 구간**에 해당. 서로 어긋남.
- **권고**: 해석표를 삭제하거나, Falchi et al.(2016) 본문 서술(위 인용) + Bortle 2001 서술로 재작성하고 출처를 각 행에 붙일 것.

---

### [5] Falchi et al. (2016) 인용 요건 및 레이어 대응

- **문서 기재**: "NASA 제품이 아니라 **NASA VIIRS Black Marble 기반으로 lightpollutionmap.info가 산출한 레이어**임. (World Atlas 레이어를 쓸 경우 Falchi et al., 2016 인용 필요)"
- **판정**: ✅ **검증됨**
- **근거 출처**: lightpollutionmap.info Help(데이터 출처 절) — **등급 [C]** / Falchi et al. 2016 — **등급 [A]**
- **원문 확인 내용** (LPM Help 원문 HTML)
  - "Sky brightness : Created from Black Marble 2.0 product suite (VNP46A4/VJ146A4) provided by the NASA VIIRS Black Marble science team."
  - "World Atlas 2015 : Falchi, Fabio; Cinzano, Pierantonio; Duriscoe, Dan; Kyba, Christopher C. M.; Elvidge, Christopher D.; Baugh, Kimberly; Portnov, Boris; Rybnikova, Nataliya A.; Furgoni, Riccardo (2016): Supplement to: The New World Atlas of Artificial Night Sky Brightness. GFZ Data Services. doi:10.5880/GFZ.1.4.2016.001"
  - "The original VIIRS data has a resolution of 15 arc seconds, while Sky Brightness has 30 arc seconds for each pixel."
- **차이/유의점**: 문서의 레이어 구분(Sky Brightness ≠ World Atlas, 인용 요건 분리)은 정확. 다만 본 프로젝트는 `sb_2025` 레이어를 쓰므로 **Falchi 2016은 인용 대상이 아니고 Black Marble(VNP46A4/VJ146A4) + lightpollutionmap 귀속이 필요**하다는 점을 attribution 문자열에 반영해야 함.
- **권고**: `attribution` 최상위 필드에 위 두 문장을 축어 그대로 넣을 것. 참고문헌의 Falchi 항목에 DOI 10.1126/sciadv.1600377 추가.

---

### [6] `+3.2%/year` 복사휘도 증가

- **문서 기재**: "2012~2025년 동안의 변화. **복사휘도(radiance) 기준 연 약 3.2% 증가** … 같은 기간 SQM은 20.3 → 19.9"
- **판정**: 🟡 **조건부 검증** (내부 정합성은 확인, 문헌 근거는 없음)
- **검산**
  - 1.032^13 = 1.506 → 0.445 mag. 문서가 말한 SQM 20.3→19.9 (0.40 mag)와 근사.
  - 총밝기 기준 역산: L(20.3)=0.8193, L(19.9)=1.1842 mcd/m² → 인공분 0.6481→1.0130, 비 1.563 → **연 3.50%/yr**. 문서의 3.2%와 0.3%p 차이(반올림·자연배경 처리 방식 차이로 설명 가능).
- **문헌 대조**: Kyba, C. C. M. et al. 2017, *Artificially lit surface of Earth at night increasing in radiance and extent*, Science Advances 3, e1701528, DOI 10.1126/sciadv.1701528 — **등급 [A]**. 전 지구 2012–2016 **연 2.2%** (밝기·면적 모두).
- **차이/유의점**: 문서의 3.2%는 **lightpollutionmap 팝업의 단일 픽셀 타임라인 판독값**이며 논문 수치가 아님. 지점 값이므로 전 지구 평균과 직접 비교 불가. 또한 VIIRS DNB가 청색에 둔감하므로([17]) LED 전환기의 radiance 추세는 실제 하늘 밝기 추세를 과소평가할 수 있음.
- **권고**: "(해당 픽셀의 lightpollutionmap 타임라인 판독값, 논문 통계 아님)" 명시. 전 지구 맥락이 필요하면 Kyba et al.(2017) 2.2%/yr 를 병기.

### [A-추가] 문서의 제주 SQM 분포 통계 — **직접 재현 검증**

- **문서 기재**: "Sky Brightness 118×98 / 0.008333°(30초각), VIIRS 311×260 / 0.004167°(15초각). 제주 영역 SQM 분포는 min 19.14 / p25 21.12 / p50 21.50 / p95 21.86 / max 21.93"
- **판정**: ✅ **검증됨** (보유 GeoTIFF를 직접 디코딩해 재현)
- **검산** (`common/sb_202500.tif`, LZW/float32 직접 디코딩, nodata −999.9 마스킹, 유효 11,349 px)
  ```
  인공밝기 min 0.01114  max 2.2084 mcd/m²
  SQM  min 19.14  p25 21.12  p50 21.50  p95 21.86  max 21.93   ← 문서와 전 항목 일치
  ```
- **부수 확인**: 최고 SQM(=가장 어두운) 픽셀은 **33.0°N / 127.07°E — 제주 남동쪽 외해**. 최저 SQM(=가장 밝은) 픽셀은 33.50°N / 126.53°E — 제주시. 문서의 "가장 어두운 픽셀은 바다 위" 주장 ✅.
- **⚠️ 용어 오류**: 문서는 "**최저 SQM 픽셀은 바다 위**"라고 적었는데, 바다 위 픽셀은 **최고 SQM**(가장 어두움)임. 같은 문단에서 "래스터 최댓값은 해상"이라고도 적어 지시 대상이 모호. 문서 다른 곳에서는 "SQM은 낮아질수록 하늘이 밝아지는 것"이라고 올바르게 서술하고 있으므로 **표기 실수.** → "가장 어두운(=SQM 최고) 픽셀은 해상" 으로 수정 권고.

---

# B. 한계등급 (NELM)

### [7] NELM 공식의 출처

- **문서 기재**: `NELM = 7.93 − 5log10(10^(4.316 − SQM/5) + 1)` — "Bradley Schaefer의 시각 한계등급 연구에 기반하며, lightpollutionmap.info가 공개 게시하고 있는 식"
- **판정**: ⚠️ **출처 미확인** (인용 사슬은 추적했으나 1차 문헌 본문에서 상수 확인 실패)
- **추적 경로 (3단계)**
  1. lightpollutionmap.info Help/FAQ #31 원문: `NELM: 7.93-5*log(10^(4.316-(SQM MPSAS/5))+1)` **"from Unihedron website"** — 등급 [C]
  2. Unihedron, *Conversion Calculator — NELM (V) to MPSAS (B) systems* — 등급 [C]
     - 정방향 식: `B_mpsas = 21.58 - 5 log(10^(1.586-NELM/5)-1)`, 출처를 "Schaefer, B.E. Feb. 1990. Telescopic Limiting Magnitude. PASP 102:212-229"로 표기
     - 역방향 식(문서가 쓰는 식): 출처를 **"Olof Carlin, Nils. About Bradley E. Schaefer: Telescopic limiting Magnitudes"** — 개인 웹페이지(거부 등급)
  3. Schaefer, B. E. 1990, *Telescopic Limiting Magnitudes*, PASP 102, 212–229, DOI 10.1086/132629 — 등급 [A]. **ADS/IOPscience 초록까지만 확인. 전문 접근 실패로 상수 21.58 / 1.586 이 원문에 등장하는지 확인하지 못함.**
- **검산 (대수 정합성은 확인)**: 정방향식을 NELM에 대해 풀면
  `NELM = 5×1.586 − 5·log10(10^(21.58/5 − B/5) + 1) = 7.93 − 5·log10(10^(4.316 − B/5) + 1)`
  → **7.93 = 5×1.586, 4.316 = 21.58/5.** 문서 식은 Unihedron 정방향식의 **정확한 역함수**이며 유도 오류는 없음.
- **차이/유의점**
  - Schaefer 1990은 **망원경** 한계등급 논문이며, 맨눈은 구경·배율의 특수 경우. 21.58/1.586이 Schaefer의 어느 식에서 나왔는지는 미확인.
  - 문서의 체크리스트 후보였던 Schaefer 1993(Vistas in Astronomy 36, 311)은 이번 추적에서 인용 사슬에 등장하지 않았음.
  - 독립 검증용 A등급 대안 존재: **Crumey, A. 2014, *Human contrast threshold and astronomical visibility*, MNRAS 442(3), 2600–2619, DOI 10.1093/mnras/stu992** — Schaefer 모델을 명시적으로 비판("he assumed the personal factor of the observer... was approximately 1")하고 대체식 제시:
    - Eq.(54) `m₀ = 0.3834 μ_sky − 1.4400 − 2.5 log F` (20 < μ < 22)
    - Eq.(55) `m₀ = 0.4260 μ_sky − 2.3650 − 2.5 log F` (21 < μ < 25)
- **권고**: 문서의 출처 문구를 **"lightpollutionmap.info가 Unihedron 계산기에서 인용한 식이며, Unihedron은 이를 Schaefer(1990) PASP 102, 212에서 유도한 것으로 표기한다. 역함수 형태의 출처는 개인 문서이며 원논문에서 상수를 직접 확인하지 못했다"**로 정직하게 수정. 가능하면 Crumey(2014) Eq.(55)를 병행 산출해 두 값의 차이를 응답에 노출.

---

### [8] SQM → NELM 대응표

- **문서 기재**

  | SQM | NELM | 의미 |
  | --- | --- | --- |
  | 22.0 | 7.7 | 최상급 다크스카이 |
  | 21.2 | 6.9 | 제주 중산간 수준 |
  | 20.4 | 6.1 | 보통 시골 |
  | 19.2 | 4.8 | 제주시 수준 |

- **판정**: ❌ **불일치** — 문서가 바로 위 줄에 적은 공식으로 계산한 값과 다름
- **검산** (python, 문서 공식 그대로)

  | SQM | 문서 표 | 공식 계산 | 차이 | `SQM − 14.3` |
  | --- | --- | --- | --- | --- |
  | 22.0 | 7.7 | **6.62** | **+1.08** | 7.7 |
  | 21.2 | 6.9 | **6.23** | **+0.67** | 6.9 |
  | 20.4 | 6.1 | **5.76** | **+0.34** | 6.1 |
  | 19.2 | 4.8 | **4.92** | −0.12 | 4.9 |

  → 문서 표는 공식이 아니라 **`NELM ≈ SQM − 14.3` 이라는 선형 근사**를 그대로 옮긴 것. 공식은 SQM→∞ 에서 7.93으로 점근하므로 어떤 SQM에서도 7.7이 나오려면 SQM ≈ 23.5 이상이어야 함(제주에서 물리적으로 불가능).
- **독립 대조 (Crumey 2014, 등급 [A])**: Eq.(55)로 SQM 22.0 → **7.01 (F=1)** / **6.25 (F=2)**. 즉 별개의 peer-reviewed 모델도 **7.7이 아닌 6.2–7.0** 을 준다.
- **하류 영향 (반증 시도)**: 이 값은 e) 카탈로그 필터링의 기준선이다. SQM 21.2에서 문서 표(6.9)를 쓰면 공식값(6.23)보다 **0.67등급 어두운 천체까지 "보인다"고 판정** → 실제로는 안 보이는 대상이 결과에 포함됨. 성단·성운은 표면밝기 문제로 더 심함.
- **권고**
  1. 표를 공식 계산값으로 즉시 교체: 22.0→6.62, 21.2→6.23, 20.4→5.76, 19.2→4.92.
  2. 또는 표를 유지하려면 **`NELM = SQM − 14.3` 이 별도의 경험식임을 밝히고 출처를 제시**해야 하나, 이번 검증에서 해당 선형식의 1차 출처는 찾지 못함.
  3. 문서가 "→ 달빛·광공해·고도가 **모두 반영된** 물리적 기준선이므로, 기존 임의식을 완전히 대체함"이라고 쓴 것은 현재 표 기준으로는 성립하지 않음. `MAG_LIMIT = 6.0 − 3×달조도` 를 임의식이라 비판했는데, 대체품 표도 출처 불명의 선형식이라는 점에서 같은 문제.

---

# C. 달빛 · 대기량

### [9] Krisciunas & Schaefer (1991) 실재 여부 및 5개 입력 변수

- **문서 기재**: "(Krisciunas, K. & Schaefer, B. E. 1991, *A Model of the Brightness of Moonlight*, PASP, 103, 1033. DOI: 10.1086/132921) … 5개를 입력으로 받아: 1 달의 위상 2 달의 천정거리 3 관측 대상의 천정거리 4 달과 대상 사이의 각거리 5 지역 대기 소광계수"
- **판정**: ✅ **검증됨**
- **근거 출처**: Krisciunas, K. & Schaefer, B. E. 1991, PASP 103, 1033–1039, DOI 10.1086/132921 — **등급 [A]** (IOPscience 초록 직접 확인, ADS 서지 대조)
- **원문 확인 내용 (초록 축어)**: "a model is presented for predicting the moonlight as a function of **the moon's phase, the zenith distance of the moon, the zenith distance of the sky position, the angular separation of the moon and sky position, and the local extinction coefficient**."
- **차이/유의점**: 문서의 5개 항목이 초록의 5개 변수와 **순서·내용 모두 정확히 일치.** 서지사항(권 103, 시작 페이지 1033, DOI)도 정확. 페이지 범위는 1033–1039.
- **부속 판정 — Rayleigh + Mie 분해 구조**: 🟡. K&S 1991 전문에 접근하지 못해 `B_moon = B_moon,R + B_moon,M` 형태를 원문에서 직접 확인하지 못함. 다만 A등급 2차 문헌(Neilsen, E. et al., *Dark Energy Survey's Observation Strategy, Tactics, and Exposure Scheduler*, arXiv:1912.06254)이 "follows the general approach used by Krisciunas & Schaefer (1991), estimating overall sky brightness by adding flux from three major contributors: **airglow, Rayleigh scattering of moonlight, and Mie scattering of moonlight by aerosols**"라고 기술 → 문서 서술과 일치.
- **권고**: 참고문헌에 페이지 범위 `1033–1039` 보완.

---

### [10] "정확도 8~23%" 주장

- **문서 기재**: "K&S 모델은 마우나케아에서 V밴드 33회 관측에 대한 경험적 피팅이며, **정확도는 8~23%. 보름달 근처에서는 정확도가 저하됨.**"
- **판정**: ✅ **검증됨** (8~23% 부분) / ⚠️ (보름달 부분)
- **근거 출처**: K&S 1991 초록 — **등급 [A]**
- **원문 확인 내용 (축어)**: "A comparison of the model with lunar data and with some Russian solar data shows **the accuracy of the predictions to range from 8 percent to 23 percent**."
- **차이/유의점**
  - 8~23%는 원문의 명시 수치 ✅. 다만 원문은 이를 **"루나 데이터 + 일부 러시아 태양 데이터와의 비교"** 결과로 서술함. 문서가 이를 "마우나케아 33회 관측에 대한 피팅의 정확도"로 묶어 쓴 것은 **출처 문장의 범위를 넘어선 서술.**
  - "보름달 근처에서 정확도 저하"는 초록에 없음. 전문 미확인 → ⚠️.
- **권고**: "정확도 8~23% (원문: 달 관측 데이터 및 러시아 태양 데이터와의 비교 기준)"으로 문구 조정하고, 보름달 관련 서술은 근거를 찾거나 삭제.

---

### [11] "마우나케아 V밴드 33회 관측" 피팅

- **문서 기재**: "K&S 모델은 마우나케아에서 **V밴드 33회 관측**에 대한 경험적 피팅"
- **판정**: ⚠️ **출처 미확인**
- **원문 확인 내용 (초록 축어)**: "measurements of the sky brightness from the **2800-m level of Mauna Kea** are reported."
- **추적 시도**: IOPscience 본문 접근 시 초록 + 메타데이터만 반환. ADS는 리다이렉트 후 본문 미제공. **"33회"라는 관측 횟수, "V밴드"라는 측광 밴드는 초록에 없으며 전문 접근 실패로 확인 불가.**
- **차이/유의점**: 초록이 명시하는 것은 **해발 2,800 m 지점(Hale Pōhaku)** 이며 마우나케아 정상(4,205 m)이 아님. 문서의 "마우나케아에서"는 틀리진 않으나 고도 조건이 다르다는 점이 소광계수 이식 시 중요.
- **권고**: "33회 / V밴드"의 근거를 원문 본문에서 확인하거나, 확인 전까지 "(관측 횟수·밴드는 원문 전문 미확인)"으로 표기. 고도 2,800 m 조건을 명시.

---

### [12] 대기량 식 `X = (1 − 0.96 sin²z)^(−0.5)` 및 대기량 표

- **문서 기재**

  | 고도 | 천정거리 z | 대기량 X |
  | --- | --- | --- |
  | 90° | 0° | 1.00 |
  | 60° | 30° | 1.13 |
  | 30° | 60° | 1.62 |
  | 20° | 70° | 2.05 |
  | 10° | 80° | 3.13 |

- **판정**: **식은 ✅ / 표는 ❌ 불일치**
- **근거 출처**: K&S 1991 (IOPscience 본문 텍스트에서 `X(Z) = (1 - 0.96 sin^2 Z)^-0.5` 형태 확인) — **등급 [A]**. 동일 식은 Bará(2017) 등 후속 문헌에서도 K&S에 귀속됨.
- **검산** (python, 문서 식 그대로)

  | 고도 | 문서 표 | K&S 식 계산 | 오차 | sec z | Kasten & Young 1989 |
  | --- | --- | --- | --- | --- | --- |
  | 90° | 1.00 | 1.000 | 0.0% | 1.000 | 1.000 |
  | 60° | 1.13 | **1.147** | −1.5% | 1.155 | 1.154 |
  | 30° | 1.62 | **1.890** | **−14.3%** | 2.000 | 1.994 |
  | 20° | 2.05 | **2.562** | **−20.0%** | 2.924 | 2.903 |
  | 10° | 3.13 | **3.808** | **−17.8%** | 5.759 | 5.586 |

- **반증 시도 — 다른 식이었나?**: `X = (1 − k sin²z)^−0.5` 형태로 각 표값을 만족하는 k를 역산하면 고도 60°→0.867, 30°→0.825, 20°→0.863, 10°→0.926 으로 **k가 일정하지 않음.** 즉 문서 표는 어떤 단일 대기량 공식으로도 재현되지 않으며, sec z / Kasten-Young / Pickering / Rozenberg / Young(1994) 어느 것과도 일치하지 않음.
- **2차 내부 모순**: 문서 결과 예시에 "(남쪽 전갈자리는 고도가 낮아 **대기량 2.4**로 흐릿함)"이 있는데, 고도 25°에서 K&S 식은 **2.175**, sec z는 **2.366**, Kasten-Young은 **2.356**. 즉 예시의 2.4는 표와도 인용식과도 다른 제3계열(할선 근사) 값.
- **차이/유의점**: K&S 식은 지평선에서 X=5로 유계(bounded)이므로 **소광이 아니라 산란광 경로 근사에 특화된 식**이다. 고도 10° 이하에서 표준 대기량(Kasten-Young 5.59)의 68%에 불과하므로, 이 식을 별의 소광 보정에 그대로 쓰면 **저고도 천체의 감광을 과소평가**한다. 문서 f)절이 "대기량 X를 통해 밝기 감소를 정량 반영"한다고 한 부분이 여기에 해당하므로 용도 분리가 필요.
- **권고**
  1. 표를 즉시 재계산값으로 교체: 60°→1.15, 45°→1.39, 30°→1.89, 20°→2.56, 10°→3.81.
  2. 결과 예시의 "대기량 2.4"를 2.18(K&S)로 수정.
  3. **용도 분리 명시**: 산란광/스카이글로우 가중에는 K&S X, **별 자체의 소광 보정에는 Kasten & Young(1989) 등 표준 대기량**을 쓸 것. 두 식이 저고도에서 47% 차이나므로 혼용 시 오류가 큼.

---

### [13] `영향도 = 섹터 점수 × X(고도)`

- **문서 기재**: `영향도 = 섹터 점수 × X(고도)`
- **판정**: 🟡 **조건부 검증 — 물리식이 아니라 순위 비교용 휴리스틱**
- **근거/판단 논거**
  - 대기량 X(z)는 **관측 시선이 통과하는 상대 대기 경로**이며, 관측 시선 방향의 **자체 발광/산란 강도**가 아니다. 스카이글로우의 시선 방향 밝기는 광원 분포와 시선을 따른 산란 계수·위상함수의 적분(Garstang 1986 계열)이며, 대기 경로가 길어지면 산란 기여가 늘어나는 동시에 **소광도 함께 커져** 실제로는 포화한다. 단순 곱은 이 포화를 반영하지 않는다.
  - Garstang, R. H. 1986, PASP 98, 364, DOI 10.1086/131768 — **등급 [A]**. 초록: "Molecular scattering and aerosol scattering are included, with the amount of aerosols being an adjustable parameter, and different scale heights being adopted for molecules and aerosols."
  - 또한 섹터 점수는 **방위별** 값이고 X는 **고도별** 값이므로, 곱은 두 축이 독립이라는 가정을 암묵적으로 요구한다(실제로는 저고도일수록 특정 방위 광원의 기여가 급증하는 결합 효과가 있음).
- **차이/유의점**: 문서는 섹터 점수에 대해서는 "절대값은 의미 없으므로 상대 비교"라고 정직하게 한정했으나, `영향도` 수식에는 같은 단서를 붙이지 않아 물리량처럼 읽힌다.
- **권고**: 수식 아래에 "**본 값은 물리 단위를 갖지 않으며, 동일 시각·동일 관측지 내에서 대상 간 순위 비교에만 사용한다**"를 명시. 절대 밝기가 필요하면 Sky Brightness 레이어 값을 쓸 것(문서가 이미 그렇게 설계함 ✅).

---

### [14] 소광계수 기본값

- **문서 기재**: "제주 대기 조건과 차이가 있으므로 소광계수는 **지역값으로 조정 필요**." — **구체적 수치는 제시하지 않음.**
- **판정**: ⚠️ **미확인 / 문서에 검증 대상 수치 자체가 없음**
- **참고 문헌값 (권고용, 등급 [A])**
  - Roque de los Muchachos (라팔마, 2,400 m): V밴드 소광계수 최빈값 0.11, 중앙값 0.113 mag/airmass
  - Cerro Tololo (CTIO): V밴드 0.164 ± 0.005 mag/airmass
  - 위 값들은 모두 **고고도 건조 관측지**의 것이며, 제주(해발 0–1,950 m, 해양성 기후, 해염 에어로졸)에는 그대로 적용 불가. 저고도 해안 관측지는 이보다 유의하게 큼.
- **권고**: K&S 모델 구현 시 소광계수는 필수 입력이므로 **기본값을 반드시 문서에 명시**할 것. 문헌값이 없으면 "제주 기본값 k_V = 0.2X mag/airmass (근거: ___)"처럼 근거와 함께 적고, 이 값이 결과에 미치는 민감도를 함께 기재. 근거가 없으면 "임의 설정값"이라고 명시.

---

# D. VIIRS / 야간광

### [15] `0.5 nW·cm⁻²·sr⁻¹ 미만을 0으로 설정`

- **문서 기재**: "NASA가 잔여 배경 노이즈 제거를 위해 **0.5 nW·cm⁻²·sr⁻¹ 미만의 복사휘도를 0으로 설정**하기 때문(Black Marble User Guide)."
- **판정**: ✅ **검증됨**
- **근거 출처**: Román, M. O. et al., *Black Marble User Guide (Collection 2.0)*, NASA GSFC VIIRS Land / viirsland.gsfc.nasa.gov — **등급 [A]** (PDF 전문 다운로드·텍스트 추출로 직접 확인, §2.3)
- **원문 확인 내용 (축어)**: "The monthly and yearly NTL composite are then calculated from the mean values of the remaining observations. **To remove any residual background noise, the NTL composite values with radiances less than 0.5 nW·cm-2·sr-1 are set to zero.** Aurora-contaminated pixels are filled with gap-filled values."
- **권고**: 참고문헌에 정식 서지 추가 — *Black Marble User Guide (Collection 2.0)*, NASA VIIRS Land Science Team, https://viirsland.gsfc.nasa.gov/PDF/BlackMarbleUserGuide_Collection2.0.pdf . 관련 peer-reviewed 근거로 Román, M. O. et al. 2018, *NASA's Black Marble nighttime lights product suite*, Remote Sensing of Environment 210, 113–143 도 병기 권장(본 검증에서 초록 미확인이므로 서지 확인 후 추가할 것).

### [15-b] "제주 영역 VIIRS 유효 픽셀의 71.9%가 값이 정확히 0" — 인과 서술 검증

- **판정**: 🟡 **조건부 검증** (수치는 재현됨, 원인 설명은 보유 파일과 부합하지 않음)
- **검산** (`common/viirs_npp_202500.tif` 직접 디코딩, 311×260 = 80,860 px, nodata 0개)
  ```
  값이 정확히 0.0 인 픽셀 : 58,266 (72.1%)      ← 문서 71.9%와 사실상 일치 ✅
  0 < 값 < 0.5 인 픽셀    :  3,864 (4.8%)       ← 문제 지점
  최소 비영 값            : 0.0925 nW/cm²·sr
  최댓값                  : 107.60
  ```
- **반증**: NASA의 0.5 임계가 이 래스터에 적용되어 있다면 **0과 0.5 사이 값이 존재할 수 없어야 하는데, 3,864개가 존재**한다. 즉 보유 파일은 VNP46A4 원본이 아니라 lightpollutionmap이 재투영/리샘플링한 파생물일 가능성이 높다.
- **권고**: 문서 문장을 "**NASA Black Marble 합성 단계에서 0.5 nW 미만을 0으로 설정하기 때문(A등급 확인). 다만 보유 래스터에는 0<v<0.5 픽셀이 4.8% 존재하므로, 이 파일은 원본이 아니라 재샘플링된 파생물로 보인다**"로 보완. 데이터 출처를 VNP46A4 원본으로 바꾸면 이 모호성이 사라짐.

---

### [16] "VIIRS는 현지시각 약 01:30에 수집"

- **문서 기재**: "VIIRS 데이터는 **현지 시각 01:30경에 수집**되므로 그 전후 시간대는 더 밝거나 어두울 수 있음 → 관측 시작 시각(21시대)과 다름"
- **판정**: ✅ **검증됨**
- **근거 출처**
  - Falchi et al. 2016, Science Advances 2, e1600377 — **등급 [A]**. 축어: "The maps were calibrated to match the time of satellite overpass, **at around 1 a.m.** Because of the decrease in artificial illumination during the night, **brighter skies should typically be expected for observations made earlier in the night.**"
  - NOAA 위성운영 문서: Suomi-NPP 태양동기궤도, **하강 노드 현지 적도통과시각 01:30**(승교점 13:30) — **등급 [A/B]** (검색 결과 기준, 원문 PDF 직접 확인은 CISESS 자료까지)
  - lightpollutionmap.info Help — **등급 [C]**. 축어: "VIIRS data is collected at around 01:30 local time, so if you take measurements before or after that time, it can be brighter or darker than the modelled data."
- **차이/유의점**: 문서의 방향성 서술("21시대는 더 밝을 수 있음")은 Falchi 2016의 A등급 문장과 정확히 같은 취지 ✅. 즉 **문서가 SQM 절댓값이 아니라 상대 비교로 포지셔닝한 것은 문헌적으로 정당함.**

---

### [17] "DNB는 500nm 이하에 사실상 반응하지 않음"

- **문서 기재**: "VIIRS 검출기는 **500nm 이하에 사실상 반응하지 않아**, 강한 백색·청색 조명이 있는 곳은 실제 하늘이 모델 예측보다 훨씬 밝음 → 한국은 LED 가로등 교체가 많이 진행되어 **실측이 모델보다 밝게 나올 가능성이 구조적으로 존재**"
- **판정**: ✅ **검증됨** (앞부분) / ⚠️ (한국 LED 관련 구체적 주장)
- **근거 출처**
  - Falchi et al. 2016 — **등급 [A]**. 축어: "The DNB is sensitive to light in the range **0.5 to 0.9 μm**, so its sensitivity spans out into the near-infrared region, beyond the range of the human eye, **whereas it leaves out the blue and violet parts of the visible spectrum.** … This will prevent a good control of the evolution of light pollution in this important spectral band, **where the white LEDs now being installed have strong emissions.**"
  - NASA, *Black Marble User Guide (Collection 2.0)* — **등급 [A]**. "the VIIRS DNB spectral band [0.5-0.9 μm]"
  - NOAA STAR JPSS, VIIRS 계기 사양 — **등급 [A/B]**. DNB는 0.7 μm 중심, **반치폭 0.505–0.890 μm**
- **차이/유의점**
  - "사실상 반응하지 않는다"는 표현은 정확도 측면에서 적정. 엄밀히는 **반치폭(50% 응답) 하단이 505 nm**이며 그 아래로 응답이 0이 되는 것은 아니고 급격히 감소함. 원한다면 "반치폭 하단이 약 505 nm이므로 청색·보라 영역은 사실상 누락됨"으로 정밀화 가능.
  - "한국은 LED 가로등 교체가 많이 진행되어" 부분: **일반 원리는 Falchi 2016이 명시적으로 지지 ✅.** 그러나 한국의 LED 전환률이나 그로 인한 SQM 편차 크기에 대한 1차 자료는 확인하지 못함 → ⚠️. 정량적 주장은 하지 말 것.

---

### [18] `섹터 점수 = Σ V_i / (d_i² + ε)` — 거리 제곱 반비례 근사

- **문서 기재**: 거리 제곱 반비례. 이어서 "실제 광공해 전파는 거리뿐 아니라 대기 상태·산란각·광원의 상향 발광 패턴에 의존하며, 정확한 계산에는 Garstang (1986) 계열의 점확산함수(PSF)가 필요함. 본 프로젝트는 **절대 밝기가 아닌 방위 간 상대 순위 비교**가 목적이므로 거리 제곱 반비례 근사를 사용함."
- **판정**: 🟡 **조건부 검증** (한계 인식은 정확, 다만 편의의 방향과 크기가 문서에 없음)
- **근거 출처**
  - Garstang, R. H. 1986, PASP 98, 364–375, DOI 10.1086/131768 — **등급 [A]**. 스카이글로우는 분자산란·에어로졸산란을 각각 다른 척도고도로 적분하는 방식이며, 단일 거듭제곱 법칙이 아님.
  - Cinzano, P., Falchi, F. & Elvidge, C. D. 2001, *The first World Atlas of the artificial night sky brightness*, MNRAS 328(3), 689–707, DOI 10.1046/j.1365-8711.2001.04882.x — **등급 [A]** (서지 확인). 대기 중 광전파의 정밀 모델링 기반.
  - **⚠️ 미확인**: 흔히 인용되는 "Walker의 법칙 d^−2.5" (Walker 1977) 및 Duriscoe 등의 지수 −2 ~ −2.5, Aubé의 −3.33 은 **2차 요약을 통해서만 확인했고 1차 문헌 본문은 확인하지 못함.** 보고서에서는 참고로만 언급.
- **검산 — 편의의 방향과 크기 (거리 1 km 광원 대비 상대 가중치)**

  | 거리 | d^−2 (문서) | d^−2.5 | d^−3 | 문서식이 d^−2.5 대비 과대 |
  | --- | --- | --- | --- | --- |
  | 2 km | 0.2500 | 0.1768 | 0.1250 | 1.4배 |
  | 5 km | 0.0400 | 0.0179 | 0.0080 | 2.2배 |
  | 10 km | 0.0100 | 0.00316 | 0.0010 | 3.2배 |
  | 20 km | 0.00250 | 0.00056 | 0.00013 | 4.5배 |
  | 30 km | 0.00111 | 0.00020 | 0.00004 | **5.5배** |

  → **d^−2는 문헌에서 보고된 지수 범위(−2 ~ −3.33) 중 가장 완만한 쪽 끝.** 반경 30 km를 훑는 본 설계에서 **먼 대도시(제주시·서귀포)의 기여가 근거리 소규모 광원 대비 최대 5배 이상 과대평가**된다. 실제 영향: "관측지 바로 옆 마을"보다 "30 km 밖 제주시" 방위가 부당하게 나쁘게 나올 수 있음 → **방위 순위가 뒤집힐 수 있으므로 "상대 비교라서 괜찮다"는 논거만으로는 방어되지 않음.**
- **권고**
  1. 지수를 파라미터화(`p`, 기본 2.5)하고 문서에 "p=2는 원거리 광원을 과대평가하는 방향의 편의가 있다"를 명시.
  2. 또는 최소한 반경을 30 km에서 축소(예: 15–20 km)해 편의 노출을 줄일 것.
  3. Garstang(1986)을 "PSF가 필요"라고만 언급하지 말고, **본 근사가 어느 방향으로 틀리는지**를 위 표 형태로 문서에 남길 것.

---

### [19] `30초각 ≈ 남북 0.9km × 동서 0.8km @ 위도 33.4°`

- **판정**: ✅ **검증됨**
- **검산** (WGS84 타원체, 위도 33.4°)
  ```
  자오선 곡률반경 M = a(1-e²)/W³,  묘유선 곡률반경 N = a/W
  30″ = 0.0083333°
  남북 = M × Δφ = 924.3 m
  동서 = N cosφ × Δλ = 775.2 m
  ```
  → 문서의 "약 0.9 km(남북) × 0.8 km(동서)" 정확 ✅
- **부수**: 15초각(VIIRS)은 462 m × 388 m. 문서가 다른 곳에서 쓴 "약 500m/픽셀(VIIRS), 1000m(Sky Brightness)"는 lightpollutionmap Help의 투영 후 표기와 일치 ✅.
- **⚠️ 경미한 불일치**: 문서 다른 곳에서 "**900m 격자**"라고 반복 표기하는데, 이는 남북 방향(924 m)만 반영한 값. 동서는 775 m이므로 "약 0.9 × 0.8 km"로 통일 권고.

---

### [20] GeoTIFF nodata −999.9, 단위 mcd/m² vs 팝업 μcd/m²

- **판정**: ✅ **검증됨** (보유 파일 헤더 직접 확인 + 제공처 문서 대조)
- **검산 — 보유 GeoTIFF 4개 헤더 직접 파싱**

  | 파일 | 크기 | 픽셀 크기 | nodata | CRS | 형식 |
  | --- | --- | --- | --- | --- | --- |
  | `common/sb_202500.tif` | 118×98 | 0.0083333° (30″) | **−999.9** | WGS 84 | float32, LZW |
  | `common/viirs_npp_202500.tif` | 311×260 | 0.0041667° (15″) | **−999.9** | WGS 84 | float32, LZW |
  | `data/jeju_2025_GeoTIFF_raw.tif` | 118×98 | 동일 | −999.9 | WGS 84 | 동일 (sb와 바이트 동일) |
  | `data/jeju_2025_viirs_npp.tif` | 311×260 | 동일 | −999.9 | WGS 84 | tiepoint 위도만 미세 상이 |

  → 문서의 "nodata 값은 −999.9 (float32, EPSG:4326)", "118×98 / 0.008333°, 311×260 / 0.004167°" **전부 일치 ✅**
- **NASA 문서 대조**: Black Marble User Guide (Collection 2.0) 데이터 사양 표에서 DNB 레이어들의 fill value가 **−999.9**로 명시됨 — **등급 [A]** ✅
- **단위 1000배 차이**: 검산 결과 `인공밝기 0.594 mcd/m² + 0.171168465 = 0.765168` → SQM **20.374** (문서 예시 20.37 ✅). 즉 GeoTIFF 값이 mcd/m², 팝업이 μcd/m²라는 문서 서술은 **수치적으로 확인됨 ✅**
- **🟡 주의 (제공처 문서의 오타)**: lightpollutionmap Help/FAQ #31 원문은 "artificial brightness in **mcd/cm 2**"라고 적고 있으나 바로 다음 줄에서 mcd/m²로 계산함. **제공처 문서 자체에 단위 오타가 있음.** 문서에 이 사실을 각주로 남겨 두면 향후 혼동 방지에 도움.
- **Ratio 3.48 검산**: LPM 정의는 `Ratio = ARTIFICIAL_BRIGHTNESS / 0.171168465` (원문 확인). 0.594/0.171168465 = **3.470**. 문서가 "Ratio = 3.48"이라 적고 스스로 "계산: 0.594/0.171 ≈ 3.47"이라 병기한 것은 팝업 표시값의 반올림 차(인공밝기가 594.x μcd)로 설명됨 → 경미, 문제 없음.

---

# E. 천체 계산

### [21] 박명 정의 −6° / −12° / −18°

- **판정**: ✅ **검증됨**
- **근거 출처**: U.S. Naval Observatory, Astronomical Applications Dept., *Rise, Set, and Twilight Definitions*, https://aa.usno.navy.mil/faq/RST_defs — **등급 [A]**
- **원문 확인 내용 (축어)**
  - "Civil twilight is defined to begin in the morning, and to end in the evening when the center of the Sun is geometrically **6 degrees** below the horizon."
  - "Nautical twilight … **12 degrees** below the horizon."
  - "Astronomical twilight … **18 degrees** below the horizon."
- **차이/유의점**: 문서 표의 각도 구간(0~−6 / −6~−12 / −12~−18 / −18 이하)과 명칭 모두 USNO 정의와 일치 ✅. 다만 **정의 기준은 "태양 중심(center of the Sun)의 기하학적 위치"** 라는 점이 문서에 없음 → Skyfield `dark_twilight_day`도 동일 규약이므로 문제는 없으나 명시 권장.
- **🔵 서술 부분**: "시민박명 = 밖에서 신문을 읽을 수 있는 밝기"는 USNO 원문에 없음(USNO는 "artificial illumination is normally required to carry on ordinary outdoor activities"). 관례적 서술이므로 🔵로 분류하고, 원한다면 USNO 문장으로 교체 권고.

---

### [22] `밤 관측 기준 = 태양고도 −18° 이하`

- **판정**: ✅ **검증됨**
- **근거 출처**: USNO, *Rise, Set, and Twilight Definitions* — **등급 [A]**
- **원문 확인 내용 (축어)**: "**Before the beginning of astronomical twilight in the morning and after the end of astronomical twilight in the evening, scattered light from the Sun is less than that from starlight and other natural sources.**"
- **차이/유의점**: 문서의 "이 시점 전에는 어두운 천체가 잔광에 묻힘"은 위 USNO 문장의 직접적 함의 ✅. Skyfield `almanac.dark_twilight_day`의 반환값 0 = 완전한 밤 이라는 서술도 라이브러리 문서와 일치(등급 [C], 라이브러리 공식 문서).
- **권고**: 근거 문장을 USNO 축어 인용으로 문서에 추가하면 "관례"가 아닌 "규격"임이 분명해짐.

---

### [23] 등급 체계 — 5등급 차 = 100배

- **문서 기재**: "숫자가 작을수록 밝다 … **1등성이 6등성보다 100배 밝음.**"
- **판정**: ✅ **검증됨**
- **근거 출처**: Pogson, N. R. 1856, *Magnitudes of Thirty-Six of the Minor Planets for the First Day of Each Month of the Year 1857*, MNRAS 17, 12–15 — **등급 [A]** (서지 확인. 본문 전문은 미열람이나 5등급=100배 규약의 원전으로 널리 확립)
- **검산**: 1등급과 6등급의 차 = 5등급, 10^(0.4×5) = **100.0** ✅
- **권고**: 참고문헌에 Pogson(1856) 추가 및 "5등급 차 = 정확히 100배 (Pogson 비 2.512)" 명시.

---

### [24] de421.bsp 천체력의 유효 기간·정확도

- **문서 기재**: "JPL de421.bsp (skyfield-data) | 로컬 파일 17MB | 해·달·행성 궤도" — **유효 기간·정확도는 문서에 없음**
- **판정**: ✅ **검증됨** (아래 값이 확인됨) / 문서에는 **미기재**
- **근거 출처**: Folkner, W. M., Williams, J. G. & Boggs, D. H. 2009, *The Planetary and Lunar Ephemeris DE 421*, IPN Progress Report 42-178, NASA JPL, https://ipnpr.jpl.nasa.gov/progress_report/42-178/178C.pdf — **등급 [A]**
- **확인 내용**: DE421 수록 구간 **JED 2414864.5 (1899-07-29) ~ 2471184.5 (2053-10-09)**, 즉 실용상 **1900–2050**. ICRF1 대비 정렬 정확도 1 mas 이하. 금성 200 m, 지구·화성 300 m 수준.
- **차이/유의점**: 제주 관측 용도(2026년, 각도 정확도 수 각초 이하면 충분)에는 **과잉 정확도**이며 전혀 문제없음 ✅. 다만 2050년 이후 날짜가 요청되면 계산이 실패하므로 방어 로직이 필요.
- **권고**: 문서에 "de421 유효 구간 1900–2050 (Folkner et al. 2009, IPN PR 42-178). 범위 밖 날짜는 명시적 에러로 반환" 을 추가.

---

### [25] IAU 88개 별자리 경계 공식 지정

- **문서 기재**: "IAU가 88개 별자리와 그 경계를 공식 지정하고 있으며, **각 항성의 소속 별자리는 바이어 명명법(Bayer designation)에 이미 담겨 있음.**"
- **판정**: ✅ **검증됨** (88개 및 경계 지정) / 🟡 (바이어 명명법 부분)
- **근거 출처**: IAU, *The Constellations* (iau.org 공식 페이지) 및 Delporte, E. 1930, *Délimitation Scientifique des Constellations*, IAU — **등급 [A]**
- **확인 내용**
  - 1922년 로마 IAU 제1회 총회에서 **88개 별자리와 3문자 약어** 확정
  - Delporte가 적경·적위선을 따르는 경계안을 제출, **1928년 라이덴 총회에서 승인**, **1930년 출판**. 기준 분점은 **B1875.0**
- **🟡 차이/유의점 (바이어 명명법)**: 바이어 명명(1603, *Uranometria*)의 속격 별자리명은 **IAU 1930 경계보다 300년 이상 앞선 할당**이며, 두 체계가 항상 일치하지는 않는다(경계 재획정 과정에서 일부 별의 소속이 바뀐 사례가 알려져 있음). 문서가 다루는 **밝은 별 20개 수준에서는 실무상 문제가 없으나**, "이미 담겨 있음 → 별도 데이터 파일 불필요"라는 일반 명제로는 부정확.
- **권고**: "밝은 항성 20개 범위에서는 바이어 속격이 IAU 경계와 일치하므로 별도 파일 없이 매핑 가능. 대상을 확장하면 IAU 경계 데이터(B1875.0)가 필요"로 조건을 붙일 것. 메시에 천체는 OpenNGC가 제공하는 별자리 필드를 쓰므로 무관 ✅.

---

### [26] 하한 고도 10° 적용

- **문서 기재**: "지형 차폐 한계를 고려해 **하한 10°만 유지.**" / "현재 범위에서는 미적용. 하한 고도 10°를 일괄 적용하는 것으로 근사"
- **판정**: 🔵 **관례적 임계값** (문헌 근거 없음 — 정직하게 분류)
- **판단 근거**: 아마추어 관측 실무에서 널리 쓰이는 값이나, 이를 규정한 A/B등급 문헌은 이번 검증에서 찾지 못함. 물리적으로도 임의 지점이며, 실제 차폐 각도는 지형에 따라 0°~30° 이상으로 크게 달라짐.
- **문헌으로 대체 가능한 지표 (권고)**
  - 고도 10°에서 K&S 대기량 X = **3.81**. 소광계수 0.15 mag/airmass 가정 시 **약 0.42 mag** 감광, 0.25 가정 시 **약 0.70 mag**.
  - 따라서 "고도 하한"이라는 임의 컷 대신 **"대기량에 의한 감광이 NELM 여유분을 초과하면 제외"** 라는 물리 기준으로 대체 가능하다. 문서 f)절이 이미 "대기량 기반 소광 보정으로 대체"한다고 선언했으므로 논리적으로도 일관됨.
  - 지형 차폐는 §4의 Copernicus GLO-30 지평선 프로파일(확장 과제)로 처리하는 것이 정석.
- **권고**: 문서에 "**10°는 물리 상수가 아니라 지형 차폐 미적용 상태의 임시 안전 마진**"이라고 명시.

---

# F. 기상 임계값

### [27] 구름 고도 구분 (저층 ~2km / 중층 2–6km / 고층 6km~)

- **문서 기재**

  | 구름층 | 고도 |
  | --- | --- |
  | 저층(low) | ~2km |
  | 중층(mid) | 2~6km |
  | 고층(high) | 6km~ |

- **판정**: ❌ **불일치** (두 기준 모두와 어긋남)
- **근거 출처 (1) — WMO 규격**: World Meteorological Organization, *International Cloud Atlas*, "Some useful concepts — Levels", Table 6 — **등급 [A]**

  | Level | Polar | **Temperate (제주 해당)** | Tropical |
  | --- | --- | --- | --- |
  | High | 3–8 km | **5–13 km** | 6–18 km |
  | Middle | 2–4 km | **2–7 km** | 2–8 km |
  | Low | 지표–2 km | **지표–2 km** | 지표–2 km |

- **근거 출처 (2) — 실제 사용 API**: Open-Meteo, *API Documentation* — **등급 [C]** (데이터 제공처 공식 문서)
  - `cloud_cover_low`: "**Low level clouds and fog up to 3 km altitude**"
  - `cloud_cover_mid`: "**Mid level clouds from 3 to 8 km altitude**"
  - `cloud_cover_high`: "**High level clouds from 8 km altitude**"
- **차이/유의점 (반증)**
  - 문서의 저층 상한 2 km는 WMO와 일치하나 **Open-Meteo와 1 km 어긋남.**
  - 문서의 중층 상한 6 km는 **WMO 온대 기준(7 km)과도, Open-Meteo(8 km)와도 불일치.** 어느 출처에서도 유래하지 않음.
  - WMO는 각 층이 **겹친다**고 명시(온대: middle 2–7, high 5–13 → 5–7 km 중첩). 문서의 배타적 구간 서술은 이 사실을 반영하지 않음.
  - **가장 중요**: 실제로 쓰는 값은 Open-Meteo가 내려주는 숫자이므로, **문서의 판정 기준은 반드시 Open-Meteo 정의를 따라야 한다.** Open-Meteo의 `cloud_cover_low`는 **안개(fog)를 포함**한다는 점도 문서에 없음 — 이는 §3-c의 이슬점 판정과 중복/보완 관계이므로 중요.
- **권고**: 표를 다음으로 교체.
  ```
  저층(low)  : 지표 ~ 3 km (안개 포함)  — Open-Meteo 정의. WMO 온대 정의는 지표~2 km
  중층(mid)  : 3 ~ 8 km               — Open-Meteo. WMO 온대는 2~7 km
  고층(high) : 8 km ~                 — Open-Meteo. WMO 온대는 5~13 km(중층과 중첩)
  ```
  각 행에 출처를 병기하고, 판정 로직은 Open-Meteo 정의를 기준으로 한다고 명시.

---

### [28] `상대습도 85% 이상 → 뿌연 하늘`

- **문서 기재**: `~60% 좋음 / 60~85% 보통 / 85%~ 뿌옇고 어두운 천체 관측 어려움`
- **판정**: 🔵 **관례적 임계값** (부분적으로 문헌 지지 가능, 그러나 85%라는 특정 수치는 문헌값 아님)
- **문헌 상태**
  - 에어로졸 습윤 성장에 따른 산란 증대는 확립된 현상. 산란증대인자 f(RH) = σ_scat(습)/σ_scat(건, RH≤30%)로 정의되며, **고습에서 산란이 1.5–4배 증가**한다는 관측이 다수 보고됨.
  - 그러나 다수 관측에서 f(RH)는 **RH에 따라 연속적으로 증가하며 뚜렷한 계단(deliquescence) 거동을 보이지 않는다**고 보고됨 → **85%라는 고정 임계는 물리적 변곡점이 아님.**
  - ⚠️ 위 f(RH) 관련 서술은 검색 결과 요약 기준이며, 개별 논문 본문을 직접 확인하지 못함.
- **제주(해양성)에 더 적합한 문헌 기준 (권고)**
  - **NaCl(해염)의 조해습도(DRH)는 약 75%** 로, 이 지점에서 입자가 용액방울로 전이하며 크기·산란단면적이 급증한다. 제주는 해염 에어로졸이 지배적이므로 **75%가 85%보다 물리적으로 근거 있는 변곡점**이다.
  - 유기물이 혼합된 해염은 DRH가 약 68%로 낮아짐 — Randles, C. A., Russell, L. M. & Ramaswamy, V. 2004, *Hygroscopic and optical properties of organic sea salt aerosol and consequences for climate forcing*, Geophysical Research Letters 31, L16108, DOI 10.1029/2004GL020628 — **등급 [A]** (서지 확인, 본문 미열람)
- **권고**: 문서에 "**85%는 운영상 관례값이며 물리 상수가 아니다**"를 명시. 근거 있는 대안으로 "해양성 지역인 제주는 해염 조해습도 ~75%(유기물 혼합 시 ~68%)를 1차 경보선으로, 85%를 강한 경보선으로 두는 2단 임계"를 제안. 가능하면 실측 SQM–RH 상관으로 지역 보정할 것.

---

### [29] `기온 − 이슬점 < 2°C → 결로/안개 주의`

- **판정**: 🔵 **관례적 임계값** / ⚠️ (기상청 공식 기준 확인 실패)
- **확인 내용**
  - 기상청은 **안개를 "수평시정 1 km 미만인 현상"으로 정의**하고, 이슬점을 "주어진 공기덩이가 일정 압력·수증기량에서 냉각될 때 포화가 발생하는 온도"로 정의한다 — **등급 [B]** (기상청 날씨누리 / 항공기상청 용어사전).
  - **그러나 "기온−이슬점(습수, dew-point depression) < 2°C" 를 안개 판정 기준으로 규정한 기상청 공식 기술문서는 이번 검증에서 찾지 못했다.** ⚠️
- **차이/유의점**: 습수 2°C는 항공기상·야외 촬영 실무에서 널리 쓰이는 경험칙. 물리적으로는 "기온이 이슬점까지 내려가면 포화"라는 정의로부터 자연스러운 근사이나, 임계 2°C 자체는 임의값.
  - **결로**와 **안개**는 서로 다른 현상이라는 점도 유의: 결로는 **복사냉각으로 장비 표면 온도가 이슬점 이하**가 될 때 발생하며, 기온 자체가 이슬점에 도달하지 않아도 맑은 밤에는 일어난다. 즉 습수 2°C 기준은 **결로에 대해서는 오히려 낙관적**(맑은 밤엔 습수 5°C에서도 렌즈 결로 발생).
- **권고**: "습수 2°C는 실무 관례값"이라고 명시. 결로는 별도 축으로 분리하고, 맑은 밤(저층운 <20%) + 저풍속 조건에서는 습수 임계를 더 크게(예: 5°C) 잡는 이원 기준을 제안. Open-Meteo의 `cloud_cover_low`가 안개를 포함한다는 점([27])과 연계 판정하면 정확도가 올라감.

---

### [30] `강수확률 30% 이상 → 비권장`, `풍속 10m/s 이상 → 주의`

- **판정**: 🔵 **관례적 임계값** (운영상 판단 기준, 문헌 근거 원래 없음)
- **확인 내용**
  - Open-Meteo `precipitation_probability` 정의: "**Probability of precipitation with more than 0.1 mm of the preceding hour**" — **등급 [C]** (공식 문서 확인). 즉 **0.1 mm 초과 강수 확률**이라는 정의를 문서가 명시하지 않고 있음.
  - `wind_speed_10m`: "Wind speed on 10 meters is the standard level" — 지상 10 m 표준 고도 ✅
  - 30% / 10 m/s 를 규정하는 문헌·규격은 없으며, 관측 활동의 위험 임계는 장비·개인차에 크게 의존.
- **권고**
  1. "이 두 값은 문헌 기준이 아니라 본 시스템의 운영 임계값"이라고 명시. `verdict` 근거 문자열에도 이 취지를 노출.
  2. `precipitation_probability`의 정의(0.1 mm 초과 기준)를 문서에 추가 — 사용자가 "30%"를 오해할 여지가 큼.
  3. 풍속은 안전 축이므로 기상청 **강풍주의보 기준(육상 풍속 14 m/s 이상 또는 순간 20 m/s 이상)** 같은 B등급 공식 기준을 상위 경보선으로 병기하면 근거가 생김. (해당 기준 수치는 본 검증에서 1차 확인하지 않았으므로 채택 전 기상청 원문 확인 필요 ⚠️)

---

### [31] 구름 층별 가중치 `w_low > w_mid > w_high`

- **판정**: 🟡 **조건부 검증** — 방향성은 문헌과 일치, 구체 비율은 확정 불가
- **근거 상태**
  - **방향성 ✅**: 권운/권층운은 가시광 광학두께가 매우 작고(대략 0.01–1.5 수준으로 보고됨), 층운·층적운은 이보다 수십 배 크다. 따라서 `w_low > w_mid > w_high` 순서 자체는 물리적으로 타당.
  - **비율 ⚠️**: 구체적 가중치 비율을 뒷받침할 A등급 표를 확보하지 못했다. ISCCP 운형별 광학두께 표(Hahn, Rossow & Warren 2001, *ISCCP Cloud Properties Associated with Standard Cloud Types Identified in Individual Surface Observations*, Journal of Climate 14, 11–28)를 조회하려 했으나 **출판사 서버가 HTTP 403을 반환해 원문 접근 실패.**
- **차이/유의점**: 관측 방해도는 광학두께만이 아니라 **투과율**의 함수다. 광학두께 τ의 구름을 통과할 때 별빛 감쇠는 대략 `Δm ≈ 1.086 τ`. 권운 τ=0.3이면 약 0.33 mag 감광 — 밝은 별은 보이고 성운은 사라진다. 이는 문서가 "대상 등급에 따라 다르게 판정"하겠다고 한 서술과 정확히 부합하며, **가중치를 임의 상수로 두는 대신 `Δm = 1.086 × τ_layer × (C_layer/100)` 형태의 물리식으로 대체 가능**하다.
- **권고**
  1. 가중치를 임의 상수로 둘 경우 "문헌 근거 없는 조정 파라미터"임을 명시.
  2. 물리식 대안: 층별 대표 광학두께(권운 ~0.3, 고층운 ~3, 층운/층적운 ~10 규모)를 가정해 감광 등급으로 환산하고, 이를 NELM에서 차감. 단 **대표 τ 값은 반드시 ISCCP/MODIS 기후값 원문에서 확인한 뒤 채택**할 것(현재 미확인 ⚠️).

---

### [32] 기상청 단기예보 격자 `5km×5km, 37,697개`, 발표시각 `02·05·08·11·14·17·20·23시`

- **판정**: ✅ **검증됨**
- **근거 출처**: 기상청, *기상기후데이터위키 — 기상예보 > 날씨예보 > 단기예보*, https://datawiki.kma.go.kr — **등급 [B]** (기상청 공식 기술 위키)
- **원문 확인 내용 (축어)**
  - "5km*5km 간격의 격자(동서 149(745km) × 남북 253(1.265km)), **총 37,697개**"
  - "2시부터 3시간 간격으로 **일 8회** 발표합니다."
  - SKY 코드: "맑음(1), 구름많음(3), 흐림(4)" → 문서의 "SKY 3단계(맑음/구름많음/흐림)" ✅
- **검산**: 149 × 253 = **37,697** ✅ (문서 수치와 정확히 일치)
- **🟡 부분 불일치 (예보기간)**: 문서는 "기상청 단기예보는 1시간 단위로 **글피까지** 제공한다"고 단정했으나, 원문은 조건부다 — "**02시, 05시, 08시, 11시, 14시에 발표한 단기예보의 예보대상기간은 오늘부터 모레까지**이며, 17시, 20시, 23시에 발표한 단기예보의 예보대상기간은 오늘부터 글피까지". 즉 **글피까지 나오는 것은 하루 8회 중 3회뿐.**
- **권고**: 문서 문장을 "17·20·23시 발표분은 글피까지, 그 외 발표분은 모레까지"로 수정. 배치 워커가 관측 창(당일 밤~익일 새벽)을 항상 커버하는지 확인 필요.
- **참고 (Open-Meteo 관련 문서 서술 검증)**: 문서는 "Open-Meteo도 좌표 리스트 및 **bounding box 일괄 조회**를 지원한다"고 적었으나, Open-Meteo 공식 문서에서 확인된 것은 **콤마 구분 다중 좌표**("Multiple coordinates can be comma separated. E.g. &latitude=52.52,48.85&longitude=13.41,2.35")뿐이며 **bounding box 파라미터는 확인되지 않았다** → 🟡. "좌표 리스트 일괄 조회 지원(bbox는 미지원, 격자 좌표를 직접 나열)"으로 수정 권고.

---

# G. 인용 적절성

### [33] Sönmez & Graefe (1998), Roehl & Fesenmaier (1992)

- **문서 기재**: "관광 위험 인식 연구는 **위험 회피형과 위험 추구형**이라는 두 유형의 의사결정자를 구분하며(Sönmez & Graefe 1998), 같은 목적지에 대해서도 이용자마다 주목하는 위험 차원이 다름을 밝힘(Roehl & Fesenmaier 1992)."
- **판정**: ❌ **오귀속** (Sönmez & Graefe) / 🟡 **조건부** (Roehl & Fesenmaier, 그리고 적용 논리)

**(a) Sönmez & Graefe (1998) — ❌**

- **서지 (확인됨)**: Sönmez, S. F. & Graefe, A. R. 1998, *Determining Future Travel Behavior from Past Travel Experience and Perceptions of Risk and Safety*, Journal of Travel Research 37(2), 171–177, DOI 10.1177/004728759803700209 — **등급 [A]** (Penn State 기관 리포지토리에서 초록 축어 확인). **논문은 실재함 ✅**
- **초록 축어**: "This study examined the influences of past international travel experience, types of risk associated with international travel, and the overall degree of safety felt during international travel on individuals' likelihood of travel to various geographic regions… **Results revealed that past travel experience to specific regions both increases the intention to travel there again and decreases the intention to avoid areas, particularly risky areas.** Perceived risks and safety were both found to be stronger predictors of avoiding regions than of planning to visit them."
- **불일치**: 이 논문은 **응답자를 유형으로 분류하지 않는다.** 과거 여행경험·지각된 위험·안전감이 방문의도/회피의도를 어떻게 예측하는지를 로지스틱 회귀로 분석한 연구이며, **"위험 회피형 / 위험 추구형"이라는 이분 유형론은 원문에 없다.**
- **권고**: 해당 문장에서 Sönmez & Graefe 인용을 삭제하거나, 원문 결론("지각된 위험·안전은 방문의도보다 **회피의도**의 더 강한 예측변수")으로 대체. 이 대체 결론은 오히려 프로젝트 논지에 더 적합하다 — 안전 정보는 "가라"보다 "가지 마라" 판단에 더 크게 작용하므로, `priority` 파라미터의 safety 축이 결과를 크게 뒤집는 설계를 정당화한다.

**(b) Roehl & Fesenmaier (1992) — 🟡**

- **서지 (확인됨)**: Roehl, W. S. & Fesenmaier, D. R. 1992, *Risk Perceptions and Pleasure Travel: An Exploratory Analysis*, Journal of Travel Research 30(4), 17–26, DOI 10.1177/004728759203000403 — **등급 [A]**. **논문 실재 ✅**
- **확인 내용**: 지각 위험의 **3개 차원**(physical-equipment risk, vacation risk, destination risk)을 도출하고, 이를 기준으로 군집분석해 **위험 지각이 크게 다른 3개 여행자 집단**을 식별. 또한 "Relationships between risk perceptions and travel behavior appear to be **situation-specific**"이라고 결론.
- **차이/유의점**: 문서의 "이용자마다 주목하는 위험 차원이 다름"이라는 요약은 **대체로 정확 ✅**. 다만 문서 문장 전체가 "두 유형"이라는 (Sönmez & Graefe에 잘못 귀속된) 프레임 아래 놓여 있어, 실제로는 **3개 군집**이라는 점이 가려진다.

**(c) 적용의 논리적 타당성 — 🟡**

- 두 논문 모두 **국제 여행 목적지 선택**에 관한 연구이며, "야간 관측지의 어둡기 대 접근성 가중치"를 다룬 바 없다. 관광 위험인식 연구를 **가중치 파라미터화의 근거**로 삼는 것은 직접 근거가 아니라 **유비(analogy)** 이다.
- 다만 결론 자체("사용자마다 위험 민감도가 달라 시스템이 단일 가중치를 강제하면 안 된다")는 **설계 원칙으로서 합리적이며, 문헌이 그 방향을 지지한다.** 논리적 비약이라기보다 **근거의 강도 과장**에 해당.
- **권고**: 문장을 다음과 같이 약화 — "관광 위험인식 연구는 이용자에 따라 지각 위험의 차원과 강도가 크게 다르며(Roehl & Fesenmaier 1992), 지각된 위험·안전이 목적지 **회피** 판단에 특히 강하게 작용함을 보고한다(Sönmez & Graefe 1998). 본 프로젝트는 이를 **직접 근거가 아닌 설계 방향의 참고**로 삼아, 어둡기와 접근성의 가중치를 시스템이 고정하지 않고 파라미터로 노출한다."

---

### [34] 참고문헌 목록 서지사항 정확성

- **판정**: 🟡 **조건부** — 실재성·서지 모두 대체로 정확하나 **DOI·페이지·권호 누락이 많음**

| 문서 기재 | 검증 결과 | 판정 |
| --- | --- | --- |
| Krisciunas, K. & Schaefer, B. E. 1991, *A Model of the Brightness of Moonlight*, PASP, 103, 1033. DOI: 10.1086/132921 | 정확. 페이지 범위 **1033–1039** 보완 권고 | ✅ |
| Falchi, F., Cinzano, P., Duriscoe, D., et al. 2016, *The New World Atlas of Artificial Night Sky Brightness*, Science Advances, 2(6), e1600377 | 정확. **DOI 10.1126/sciadv.1600377** 누락 | ✅ (DOI 보완) |
| Cinzano, P., Falchi, F. & Elvidge, C. D. 2001, *The First World Atlas of the Artificial Night Sky Brightness*, MNRAS, 328, 689 | 정확 (MNRAS **328(3), 689–707**, DOI **10.1046/j.1365-8711.2001.04882.x**) | ✅ (DOI·페이지 보완) |
| Garstang, R. H. 1986, *Model for Artificial Night-Sky Illumination*, PASP, 98, 364 | 정확 (PASP **98, 364–375**, DOI **10.1086/131768**) | ✅ (DOI·페이지 보완) |
| Bortle, J. E. 2001, *Introducing the Bortle Dark-Sky Scale*, Sky & Telescope | 정확 (**2001년 2월호, pp. 126–129**). Sky & Telescope는 peer-reviewed 아님 — 등급 부여 불가, "원전이지만 학술지 아님" 표기 권고 | 🟡 |
| NASA VIIRS Black Marble (VNP46A4 / VJ146A4), NASA VIIRS Black Marble science team | 실재 ✅. **User Guide (Collection 2.0) URL 및 Román et al. 2018, Remote Sensing of Environment 210, 113–143 병기 권고** | 🟡 |
| 국립공원관리공단, *국립공원 탐방로 등급제* — 탐방로 1,700여km GPS 측량 기반 5단계 난이도 | **본 검증에서 원문 미확인 ⚠️.** 또한 문서 본문에서 이 자료를 실제로 쓰는 대목이 없음 | ⚠️ |
| 산림청, *국가숲길 이용등급* (2022) — 1,070km, 500m 간격 2,151개 현장조사 | **본 검증에서 원문 미확인 ⚠️.** 본문 미사용 | ⚠️ |
| 도로교통법 정차·주차 금지 규정 | 조문 번호 미기재 (도로교통법 제32조·제33조 추정). **조문 특정 권고** ⚠️ | ⚠️ |
| 국토교통부 ITS 국가교통정보센터, 도로살얼음 주의구간 | 실재하는 서비스이나 **문서가 주장하는 "제공 시간대 23:00~09:00"의 근거 문서를 확인하지 못함** ⚠️ | ⚠️ |

- **누락 권고 (본문에서 쓰이는데 참고문헌에 없는 것)**
  - USNO, *Rise, Set, and Twilight Definitions* — 박명 정의의 근거 [21][22]
  - Unihedron NELM/MPSAS 변환 계산기 + Schaefer, B. E. 1990, PASP 102, 212–229, DOI 10.1086/132629 — NELM 식의 출처 사슬 [7]
  - Folkner, W. M., Williams, J. G. & Boggs, D. H. 2009, IPN Progress Report 42-178 — de421 [24]
  - Delporte, E. 1930, *Délimitation Scientifique des Constellations*, IAU — 별자리 경계 [25]
  - Pogson, N. R. 1856, MNRAS 17, 12–15 — 등급 체계 [23]
  - WMO, *International Cloud Atlas*, "Levels" — 구름 층 구분 [27]
  - 기상청 기상기후데이터위키, 단기예보 — 격자·발표시각 [32]
  - Bará, S. 2017, IJSL 19(1), 104–111 — 영점 상수의 유효 조건 [2]
  - Crumey, A. 2014, MNRAS 442(3), 2600–2619, DOI 10.1093/mnras/stu992 — NELM 독립 검증 [8]
  - Kyba, C. C. M. et al. 2017, Science Advances 3, e1701528 — 야간광 증가율 [6]
  - lightpollutionmap.info Help/FAQ #31 — 모든 SQM/Bortle/NELM 변환식의 직접 출처 (C등급이지만 실제 출처이므로 반드시 명기)

---

## 미해결 항목

| # | 항목 | 사유 |
| --- | --- | --- |
| 7 | Schaefer 1990 (PASP 102, 212) 본문의 상수 21.58 / 1.586 | IOPscience·ADS 모두 초록까지만 접근. 전문 유료. **상수가 원문에 있는지 확인 못함** |
| 9 | K&S 1991의 `B_moon = B_R + B_M` 실제 수식 형태 | IOPscience 본문 미제공. A등급 2차 문헌(DES 논문)으로만 간접 확인 |
| 11 | K&S 1991의 "V밴드 33회 관측" | 전문 미접근. 초록에는 관측 횟수·밴드 없음 |
| 18 | Walker(1977) d^−2.5, Duriscoe(−2~−2.5), Aubé(−3.33) | 2차 요약만 확인. **1차 문헌 본문 미열람** — 보고서에서 참고로만 사용 |
| 28 | f(RH) 곡선의 "계단 거동 없음" 서술 | 검색 결과 요약 기준. 개별 논문 본문 미열람 |
| 29 | 기상청의 안개/결로 공식 판정 기준 (습수 임계) | 기상청 공식 기술문서에서 습수 임계 기준을 찾지 못함 |
| 31 | 운형별 대표 광학두께 (ISCCP) | Journal of Climate 서버가 **HTTP 403** 반환. 원문 접근 실패 |
| 30 | 기상청 강풍주의보 기준 수치 | 권고안에 언급했으나 **1차 확인하지 않음.** 채택 전 확인 필요 |
| 34 | 국립공원관리공단 탐방로 등급제, 산림청 국가숲길 이용등급 | 원문 미확인. 본문에서 실제로 쓰이지 않아 우선순위 낮음 |
| — | 문서의 "제주 본섬 5,088픽셀 중 36.1% VIIRS 0, 해당 픽셀 SQM 20.86~21.85" | 육지 마스크가 프로젝트에 없어 재현 불가. 전체 영역 통계(72.1%)만 검증함 |

---

## 참고문헌 (본 검증에서 실제로 확인한 것만)

**A등급 — peer-reviewed**

1. Krisciunas, K. & Schaefer, B. E. 1991, *A Model of the Brightness of Moonlight*, PASP 103, 1033–1039. DOI 10.1086/132921 — 초록 확인
2. Falchi, F., Cinzano, P., Duriscoe, D., Kyba, C. C. M., Elvidge, C. D., Baugh, K., Portnov, B. A., Rybnikova, N. A. & Furgoni, R. 2016, *The new world atlas of artificial night sky brightness*, Science Advances 2(6), e1600377. DOI 10.1126/sciadv.1600377 — **전문(arXiv:1609.01041) 확인**
3. Cinzano, P., Falchi, F. & Elvidge, C. D. 2001, *The first World Atlas of the artificial night sky brightness*, MNRAS 328(3), 689–707. DOI 10.1046/j.1365-8711.2001.04882.x — 서지 확인
4. Garstang, R. H. 1986, *Model for artificial night-sky illumination*, PASP 98, 364–375. DOI 10.1086/131768 — 초록 확인
5. Bará, S. 2017, *Variations on a classical theme: On the formal relationship between magnitudes per square arcsecond and luminance*, International Journal of Sustainable Lighting 19(1), 104–111 — **전문(arXiv:1710.06755) 확인**
6. Crumey, A. 2014, *Human contrast threshold and astronomical visibility*, MNRAS 442(3), 2600–2619. DOI 10.1093/mnras/stu992 — 본문 요지 확인
7. Kyba, C. C. M. et al. 2017, *Artificially lit surface of Earth at night increasing in radiance and extent*, Science Advances 3, e1701528. DOI 10.1126/sciadv.1701528 — 초록 확인
8. Schaefer, B. E. 1990, *Telescopic Limiting Magnitudes*, PASP 102, 212–229. DOI 10.1086/132629 — **초록까지만 확인**
9. Sönmez, S. F. & Graefe, A. R. 1998, *Determining Future Travel Behavior from Past Travel Experience and Perceptions of Risk and Safety*, Journal of Travel Research 37(2), 171–177. DOI 10.1177/004728759803700209 — 초록 축어 확인
10. Roehl, W. S. & Fesenmaier, D. R. 1992, *Risk Perceptions and Pleasure Travel: An Exploratory Analysis*, Journal of Travel Research 30(4), 17–26. DOI 10.1177/004728759203000403 — 초록 요지 확인
11. Randles, C. A., Russell, L. M. & Ramaswamy, V. 2004, *Hygroscopic and optical properties of organic sea salt aerosol and consequences for climate forcing*, Geophysical Research Letters 31, L16108. DOI 10.1029/2004GL020628 — 서지 확인, 본문 미열람
12. Pogson, N. R. 1856, *Magnitudes of Thirty-Six of the Minor Planets…*, MNRAS 17, 12–15 — 서지 확인
13. Neilsen, E. et al. 2019/2020, *Dark Energy Survey's Observation Strategy, Tactics, and Exposure Scheduler*, arXiv:1912.06254 — `skybright` 패키지 및 K&S 구현 서술 확인

**A등급 — 공인기관 1차 기술문서**

14. NASA VIIRS Land Science Team, *Black Marble User Guide (Collection 2.0)* — https://viirsland.gsfc.nasa.gov/PDF/BlackMarbleUserGuide_Collection2.0.pdf — **PDF 전문 확인** (0.5 nW 임계, DNB 0.5–0.9 μm, fill value −999.9)
15. U.S. Naval Observatory, Astronomical Applications Department, *Rise, Set, and Twilight Definitions* — https://aa.usno.navy.mil/faq/RST_defs — **전문 확인**
16. World Meteorological Organization, *International Cloud Atlas*, "Some useful concepts — Levels", Table 6 — https://cloudatlas.wmo.int/en/some-useful-concepts-levels.html — **표 전문 확인**
17. IAU, *The Constellations* (iau.org) / Delporte, E. 1930, *Délimitation Scientifique des Constellations*, IAU — 확인
18. Folkner, W. M., Williams, J. G. & Boggs, D. H. 2009, *The Planetary and Lunar Ephemeris DE 421*, IPN Progress Report 42-178, NASA JPL — 확인
19. NOAA / NOAA STAR JPSS — Suomi-NPP 하강노드 01:30 현지시각, VIIRS DNB 반치폭 0.505–0.890 μm — 확인

**B등급 — 국가기관 공식 문서**

20. 기상청, *기상기후데이터위키 — 단기예보* — https://datawiki.kma.go.kr — **원문 확인** (5 km 격자 37,697개, 일 8회 발표, SKY 3단계, 예보기간 조건부)
21. 기상청 날씨누리 / 항공기상청 용어사전 — 안개 정의(수평시정 1 km 미만), 이슬점 정의 — 확인

**C등급 — 데이터 제공처 공식 문서 (출처로만 표기, 검증 아님)**

22. lightpollutionmap.info, *Help / FAQ* — https://www.lightpollutionmap.info/help.html — **원문 HTML 확인.** SQM/NELM/Ratio/Bortle 변환식, 모델 한계 서술, 해상도, 데이터 귀속, 고도 출처(Copernicus GLO-30)
23. Unihedron, *Conversion Calculator — NELM (V) to MPSAS (B) systems* — https://www.unihedron.com/projects/darksky/NELM2BCalc.html — 확인
24. Open-Meteo, *API Documentation* — https://open-meteo.com/en/docs — 확인 (구름층 고도 정의, 변수 정의, 다중좌표 지원)

**원전이나 학술지 아님 (등급 부여 불가)**

25. Bortle, J. E. 2001, *Introducing the Bortle Dark-Sky Scale*, Sky & Telescope, February 2001, 126–129 — **전문 PDF 확인.** SQM 수치 경계 부재를 확인

**거부 등급 — 추적 결과 기록용 (근거로 사용하지 않음)**

26. handprint.com/ASTRO/bortle.html (개인 사이트) — lightpollutionmap이 Bortle↔SQM 경계로 링크하는 표. 출처 미표기
27. Olof Carlin, *About Bradley E. Schaefer: Telescopic limiting Magnitudes* (개인 페이지) — Unihedron이 NELM 역함수식의 출처로 표기

---

## 부록 — 검산 재현용 코드 요약

```python
import math
Z = 1.08e8                                    # mcd/m^2 zero point
sqm  = lambda L: math.log10(L/Z)/(-0.4)       # L = artificial + 0.171168465
lum  = lambda m: Z*10**(-0.4*m)
nelm = lambda s: 7.93 - 5*math.log10(10**(4.316 - s/5) + 1)
X_KS = lambda alt: (1 - 0.96*math.sin(math.radians(90-alt))**2)**-0.5

lum(22.00)      # 0.171168465  -> [1] 문서 상수 재현 ✅
nelm(22.0)      # 6.625        -> [8] 문서 표 7.7 과 불일치 ❌
X_KS(30)        # 1.890        -> [12] 문서 표 1.62 와 불일치 ❌
X_KS(10)        # 3.808        -> [12] 문서 표 3.13 과 불일치 ❌
sqm(0.594 + 0.171168465)   # 20.374 -> [20] 문서 예시 20.37 재현 ✅
```

30초각 격자 (WGS84, 위도 33.4°): 남북 **924.3 m**, 동서 **775.2 m** → 문서 "0.9 × 0.8 km" ✅

GeoTIFF 직접 디코딩 결과 (`common/sb_202500.tif`, LZW/float32, nodata −999.9 마스킹, 유효 11,349 px):
SQM min **19.14** / p25 **21.12** / p50 **21.50** / p95 **21.86** / max **21.93** → 문서 전 항목 재현 ✅
