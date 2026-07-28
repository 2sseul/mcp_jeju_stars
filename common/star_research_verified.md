# 검증 통합본 — 무엇이 확인됐고, 무엇이 코드에 반영됐고, 무엇이 남았나

`star_research.md` 의 계산식·상수·기준치에 대한 **1차 검증 → 수정안 → 2차 검증** 세 문서를
하나로 합친 것이다. 원본은 그대로 보존돼 있으며, 근거 사슬을 따라가야 할 때 본다.

| 원본 | 날짜 | 역할 |
|---|---|---|
| `star_research_validation.md` | 2026-07-23 | 1차 검증 — 항목별 상세 근거·검산 코드 |
| `star_research_fixes.md` | 2026-07-23 | 수정안 F1~F15 — "현재 원문 → 교체 텍스트" |
| `star_research_validation2.md` | 2026-07-24 | 2차 검증 — 40건 재판정, 참고문헌 확정 |

**근거 등급**: A = 논문·공인기관 1차 문서 / B = 국가기관 / C = 데이터 제공처 문서(검증 아님)
**판정**: ✅ 일치 · 🟡 부분(조건 차이·내부 불일치) · ⚠️ 1차 전문 미열람(계산은 정합) · ❌ 불일치

> 2차 검증 총계: ✅ 24 / 🟡 8 / ⚠️ 6 / ❌ 2 (40건)
> ❌ 2건은 **계산값이 아니라 인용 표기** 문제다. 구현을 막는 항목은 없다.

---

## 1. 코드에 반영 완료

지금 돌아가는 코드가 쓰는 값들이다. **임계값 대장은 `docs/decisions.md` §1** 에 있고,
이 절은 그 값이 어떤 검증을 통과했는지만 기록한다.

| 항목 | 판정 | 근거 | 반영 위치 |
|---|---|---|---|
| `0.171168465 = 1.08e8 × 10^(−0.4×22)` | ✅ | 자체 검산, 소수 9자리 일치 | `core/darkness.py` `NATURAL_MCD` |
| `SQM = log10(총밝기/1.08e8)/(−0.4)` | ✅ | Pogson 1856 측광식 (A) | `core/darkness.py` |
| 영점 1.08e8 = 9550 K 흑체·Johnson V 전제 | ✅ 내용 / ❌ 인용 | **Bará et al. 2020, MNRAS 493, 2429** (A) | `decisions.md` §1.4 — 서지 정정 완료 |
| Falchi 6단계 경계 (1.7/14/87/688/3000 μcd/m²) | ✅ | Falchi et al. 2016, Sci Adv 2:e1600377 (A) | `core/darkness.py` `_FALCHI_UCD` |
| Falchi 174 μcd/m² ↔ 영점 1.098e8, "1.6% 차이" | ✅ | 검산 1.65%, 반올림 정합 | `decisions.md` §1.4 혼용 금지 조항 |
| Bortle 원문에 SQM 경계 없음 → 보조 표기로 강등 | ✅ | Bortle 2001 원문 확인 (A) | `core/darkness.py` `_BORTLE_SQM` 주석 |
| 박명 −6°/−12°/−18° 정의 | ✅ | USNO/IAU 표준 (A) | `core/astro.py` |
| 5등급차 = 100배 | ✅ | Pogson 1856 (A) | (개념) |
| de421.bsp 유효 ~1900–2050 | ✅ | JPL DE421 (A) | `data/ephem/de421.bsp` |
| 30″ 격자 ≈ 0.9km(NS) × 0.8km(EW) @33.4°N | ✅ | 자체 검산 | 격자 해상도 전제 |
| 제주 SQM 분포 min 19.14 / p50 21.50 / max 21.93 | ✅ | 원본 GeoTIFF 직접 디코딩 재현 | `decisions.md` §1.7 픽스처 |
| 용눈이오름 SQM 21.19 → Falchi iv / 제주시 19.18 → v·Bortle 6 | ✅ | 검산 재현 | `decisions.md` §1.7 픽스처 |
| VIIRS 현지 01:30 수집 / DNB 505–890nm | ✅ | Suomi-NPP 궤도, DNB SRF (A) | 데이터 한계 서술 |

### 수정안 F 항목의 처리 결과

| # | 내용 | 결과 |
|---|---|---|
| **F1** | NELM 대응표가 자기 공식과 최대 1.08등급 어긋남 | ✅ **해소** — 문서를 Schaefer 계열 NELM 에서 **Crumey(2014)로 교체**. 별 개수 축(P7) 픽스처도 Crumey m₀ 채택 |
| **F4** | Sönmez 인용의 "2유형 구분"이 원문에 없음 | ✅ **해소** — "회피의도를 더 강하게 예측"(Sönmez) + "3개 군집"(Roehl)으로 정정. P10 `priority` 파라미터 근거로 계승 |
| **F5** | 자연광 상수의 영점 종속성 | ✅ **반영** — 영점·자연광 상수를 한 쌍으로 고정, 혼용 금지 (`decisions.md` §1.4) |
| **F6** | 영점의 색온도 전제 + Bará 서지 | ✅ **반영** — 서지를 Bará 2020 으로 정정 |
| **F10** | Bortle → Falchi 주 기준 전환 | ✅ **반영** — `core/darkness.py` 가 Falchi 로 판정, Bortle 은 보조 표기 |
| **F13** | "최저 SQM 픽셀은 바다 위" 용어 오류 | ✅ **해소** — SQM 은 클수록 어둡다. 바다는 **최댓값**(21.93 @ 33.0°N/127.07°E 외해) |

---

## 2. 다음 단계에서 쓸 확정값

아직 구현 안 된 축의 값이지만 **검증은 끝났다**. 해당 단계 착수 시 회귀 픽스처로 먼저 박는다
(`docs/plan.md` §2·§3).

### 별 개수 축 (P7) — Crumey · K&S

| 항목 | 판정 | 값 |
|---|---|---|
| Crumey 2014 서지 | ✅ | MNRAS 442, 2600–2619, DOI 10.1093/mnras/stu992 |
| m₀ 점광원 한계 (F=2) | ✅ 자기정합 | 21.93→6.22 / 21.5→6.05 / 21.2→5.94 / 20.40→5.63 / 19.14→5.22 |
| F 전형 범위 | ✅ | 1.4 ~ 2.4, F=2 표준 |
| K&S 1991 서지·5입력·구조 | ✅ | PASP 103, 1033, DOI 10.1086/132921. Rayleigh+Mie+airglow |
| K&S 정확도 8~23%, 마우나케아 2800 m | ✅ | Jones et al. 2013, A&A 560, A91 로 교차확인 |
| K&S 식(20) `I* = 10^(−0.4(3.84+0.026\|α\|+4e−9·α⁴))` | ✅ | 상수 재현 확인 |
| K&S 식(21) `f(ρ) = 10^5.36[1.06+cos²ρ] + 10^(6.15−ρ/40)` | ✅ | 원문과 **완전 일치** |
| 소광계수 k | ✅ | 원문 마우나케아 0.172 / **제주 기본 0.33** (Falchi K=1 ↔ Δm=0.33 mag, 해수면·해양성) |
| BSC5 | ✅ | 9,096 stars, 완전한계 6.5 (Hoffleit & Warren 1991) |
| 면밝기 `μ_V = V + 2.5log10(π/4·a·b)` | ✅ | 표준 정의 (A) |

### 방위 축 (P9) — 대기량 · 거리 감쇠

| 항목 | 판정 | 값 |
|---|---|---|
| `X = (1 − 0.96sin²z)^(−0.5)` | ✅ | K&S 1991 식(3), 산란광용 |
| 대기량 표 (**F2** 정정본) | ✅ 전부 일치 | 90°→1.00 / 60°→1.15 / 40°→1.51 / 30°→1.89 / **25°→2.17** / 20°→2.56 / 10°→3.81 |
| sec z 비교 | ✅ | 30°→2.00, 10°→5.76. 억제는 오류가 아니라 **용도 차이** |
| 표준 대기량은 Kasten & Young 1989 계열 | ✅ | 소광=KY / 산란광=K&S 구분이 타당 |
| **F8** 거리 감쇠 지수 | 🟡 → 파라미터화 | `d^−p`, 기본 p=2. **p = 2/2.5/3 민감도 검사 후 채택**. 순위가 바뀌면 "방위 차 불명확"으로 판정 |
| **F14** VIIRS 재샘플링 | ⚠️ → 회피 | 보유 래스터에 `0<v<0.5` 픽셀 3,864개(4.8%) 실재 → **파생물**. 픽셀 절댓값 불신, 방위 집계 전용 |
| p 스캔 불안정 | — | 12지점 중 5지점(42%) 불안정 (성산일출봉·산굼부리 등) 재현 확인 |

> ⚠️ **구식 값 폐기**: 결과 예시의 "고도 25° → 대기량 2.4" 는 K&S 식(2.17)도 구 문서 표도
> 아닌 제3의 값이다. **2.17 을 쓴다.**

### 기타

| 항목 | 판정 | 값 |
|---|---|---|
| 구름 광학두께 → 투과율 | ✅ | τ<0.03→97% / 0.03~0.3→74% / 0.3~3→5% / 층운→0.005% (`T=exp(−τ)` 재현) |
| ISCCP 운정기압·광학두께 | ✅ | high<440, mid 440–680, low≥680 hPa; τ 경계 3.6·23 |
| IAU 88 별자리 경계 | ✅ | Delporte 1930, IAU 공식 |
| Kyba 2017 전 지구 야간광 연 2.2% | ✅ | Sci Adv 3:e1701528 |

---

## 3. 미해결 — 값은 쓰되 한계를 안다

**전부 "1차 전문 미열람"이며 형태·검산은 정합**하다. 구현을 막지 않는다.

| # | 항목 | 상태 | 취급 |
|---|---|---|---|
| 1 | **Crumey "F=2 (limit 6.18 mag)" 인용** ❌/🟡 | 자기 식(Eq.54)을 μ=22.0 에 대입하면 6.22~6.24, 2차 재현본은 "6.25 at the darkest sites". 6.18 은 μ≈21.8 상당 | **픽스처는 인용문 6.18 이 아니라 자기정합값**(21.9→6.20, 22.0→6.22)을 쓴다. 원문 pp.2600–2619 확보 시 인용 문구만 정정 |
| 2 | **K&S 식(2)(15)(19) 절대상수** ⚠️ | IOP/ADS PDF 403 으로 전문 열람 실패. 식(20)(21)·정확도·k=0.172 는 교차확인됨 | 구현은 진행. **식(2) 천정거리 보정 누락 금지**를 회귀 테스트로 강제 |
| 3 | **Crumey Table 1 면밝기 보정 sup** ⚠️ | 상위 구간 기울기 0.320/SQM 로 자기정합. 절대값 전문 미열람 | P8 천체 목록 착수 시 재확인 |
| 4 | **Bará 2020 색온도표 "+13%"** ⚠️ | 변환표는 존재하나 수치 전문 미확인. 방향(저색온도→계통오차)은 타당 | 한계 서술로만 사용 |
| 5 | **Garstang 1986 상수 10.85×10⁴** ⚠️ | 서지 실재 확인(PASP 98, 364). 상수 전문 대조 실패 | 참고 언급으로만 |
| 6 | **Black Marble 0.5 nW 임계 정확 문구** ⚠️ | User Guide 실재 확인. 정확한 수치 문구 미추출 | Román et al. 2018 RSE 참조 |
| 7 | **Falchi SQM 참고열 근거** 🟡 | 21.97/21.90/… 는 본문 서술("Falchi 174 기준 환산")과 달리 **프로젝트 영점 1.08e8 로 계산**된 값. 차이 0.02 mag | 판정은 인공 밝기 절대값으로 하므로 **결과 불변**. 캡션만 "프로젝트 영점 환산" |
| 8 | **전천 누적 별 개수표** 🟡 | 표준 star-count 와 대체로 정합(6.0≈5,000, 6.5≈8,000~9,000대). 특정 1차표 미특정 | 관용 범위로 수용 |
| 9 | **IDSA Bronze/Silver/Gold SQM 경계** 🟡 | 인용 취지 타당, IDA 원문 직접 대조 미실시 | 참고 표기 |
| 10 | **Sassen 권운 τ 구분** 🟡 | 구분 관례와 정합. 인용에 연도·저널 누락 | 서지 보완 권장 |
| 11 | **Sönmez "회피의도를 더 강하게"** 🟡 | 두 의도를 모두 모델링한 것은 사실이나 **비교급은 전문 미확인** | 뉘앙스 과장 가능 — 단정하지 않는다 |
| 12 | **관광 위험연구 → 파라미터 근거** 🟡 | 인용은 정확하나 **정량 도출이 아닌 유추적 정당화** | "동기부여 근거"로만 유효 |

### 서지 정정이 필요한 곳

- `star_research.md` L315·L1443 의 **"Bará et al. 2017, MNRAS 471, 4164, DOI 10.1093/mnras/stx1839"**
  는 세 서지가 뒤섞인 오귀속이다.
  - 내용(9550 K·Johnson V·1.08×10⁵ cd/m²)의 실제 출처 →
    **Bará, Aubé, Barentine & Zamorano 2020, MNRAS 493, 2429, DOI 10.1093/mnras/staa323**
  - "MNRAS 473, 4164" 는 제목이 다른 Bará 2017
    (*Characterizing the zenithal night sky brightness…*)의 페이지
  - `docs/decisions.md` §1.4 에는 정정본이 들어가 있다.
- Sönmez & Graefe 는 **동명 저자의 1998년 논문이 둘** 있다. 본 프로젝트가 근거로 삼는 것은
  **J. Travel Research 37(2), 171–177** 판이다.

---

## 4. 폐기된 검증 항목

구조가 바뀌어 **적용 대상이 사라진** 것들이다. 되살리려면 `docs/decisions.md` §2 를 먼저 읽는다.

| 원 항목 | 왜 폐기됐나 |
|---|---|
| **F3** 구름층 고도 경계 (3km / 3–8km / 8km~, 저층은 안개 포함) | 구름을 **총운량 단일 축**으로 바꾸면서 층 구분 자체를 쓰지 않는다 (`decisions.md` §2.1). Open-Meteo 정의 자체는 여전히 정확 |
| 층별 가중치 `w_low > w_mid > w_high` | 문헌 근거 없음(🔵 관례)으로 남아 있던 항목. 총운량 전환으로 소멸 |
| 차폐율 `1−(1−C_low)(1−C_mid)` 픽스처 (저5/중10/고25 → 14.5%) | 위와 동일. **더 이상 유효하지 않다** |
| **F11** NELM 공식 상수 7.93 / 4.316 출처 | Crumey 로 교체돼 이 식 자체를 쓰지 않는다 (F1) |
| 습도 85% · 이슬점 차 2°C · 강수확률 30% · 풍속 10 m/s | 판정에 쓰지 않는다. 되살린다면 **운영 기준이며 문헌 근거가 아님**을 명시해야 하는 값들 |
| 기상청 단기예보 격자 5km·발표시각 | Open-Meteo 를 쓰므로 미사용 |
| 표고 기반 운해 보정 (기압면 운량·Elevation API) | 총운량 전환과 함께 제거 (`decisions.md` §2.2) |
| **F9** `+3.2%/year` 픽셀 타임라인 | 논문 통계가 아닌 단일 픽셀 판독값. **정성 근거로만**, 예측·외삽 금지 |

---

## 5. 확인된 참고문헌

검증 과정에서 **실재와 내용을 확인한 것만** 싣는다.

- Krisciunas, K. & Schaefer, B. E. 1991, *A Model of the Brightness of Moonlight*,
  PASP, 103, 1033. DOI 10.1086/132921
- Jones, A. et al. 2013, *An advanced scattered moonlight model for Cerro Paranal*,
  A&A, 560, A91
- Falchi, F. et al. 2016, *The New World Atlas of Artificial Night Sky Brightness*,
  Science Advances, 2(6), e1600377. DOI 10.1126/sciadv.1600377
- **Bará, S., Aubé, M., Barentine, J. & Zamorano, J. 2020, *Magnitude to luminance
  conversions and visual brightness of the night sky*, MNRAS, 493, 2429.
  DOI 10.1093/mnras/staa323** — 영점 1.08e8 의 실제 출처
- Bará, S. 2017, *Characterizing the zenithal night sky brightness in large territories…*,
  MNRAS, 473, 4164 — 오귀속된 페이지의 원 논문(제목 상이)
- Crumey, A. 2014, *Human Contrast Threshold and Astronomical Visibility*,
  MNRAS, 442, 2600–2619. DOI 10.1093/mnras/stu992
- Cinzano, P., Falchi, F. & Elvidge, C. D. 2001, *The First World Atlas of the Artificial
  Night Sky Brightness*, MNRAS, 328, 689–707. DOI 10.1046/j.1365-8711.2001.04882.x
- Garstang, R. H. 1986, *Model for Artificial Night-Sky Illumination*, PASP, 98, 364.
  DOI 10.1086/131768 — 서지 실재(상수 전문 미확인)
- Kasten, F. & Young, A. T. 1989, *Revised Optical Air Mass Tables and Approximation
  Formula*, Applied Optics, 28(22), 4735. DOI 10.1364/AO.28.004735
- Kyba, C. C. M. et al. 2017, *Artificially lit surface of Earth at night increasing in
  radiance and extent*, Science Advances, 3, e1701528. DOI 10.1126/sciadv.1701528
- Hoffleit, D. & Warren, W. H. 1991, *Yale Bright Star Catalogue*, 5th ed.
  — 9,096 stars, 완전한계 6.5
- Bortle, J. E. 2001, *Introducing the Bortle Dark-Sky Scale*, Sky & Telescope, 101(2), 126
  — ※ NELM·서술 기준으로 등급 정의, **SQM 경계값 없음**
- Sönmez, S. F. & Graefe, A. R. 1998, *Determining Future Travel Behavior from Past Travel
  Experience and Perceptions of Risk and Safety*, Journal of Travel Research, 37(2),
  171–177. DOI 10.1177/004728759803700209
- Roehl, W. S. & Fesenmaier, D. R. 1992, *Risk Perceptions and Pleasure Travel: An
  Exploratory Analysis*, Journal of Travel Research, 30(4), 17–26
- Kerber, F. et al. 2014 — ESO clear sky 정의 (A&A 2022,
  DOI 10.1051/0004-6361/202142493 에서 재인용)
- Xin, et al. 2020 — PTB/STB 정의 · 운량 30/50% 사다리
- Ehgamberdiev, S. et al. 2000 — clear night 25%
- Patat, F. 2006, A&A, 455 — 박명 단계별 별 가시성
- ISCCP (NASA GISS) — 운정기압 440/680 hPa · τ 3.6/23
- NASA VIIRS Black Marble (VNP46A4 / VJ146A4) User Guide, VIIRS Land Team
- ECMWF Forecast User Guide (Visibility) — 시정 예보 신뢰도
- WMO — 안개 1 km 정의 / *International Cloud Atlas* 운족 구분
- Open-Meteo API Documentation — `cloud_cover` · `visibility` 변수 정의
- USNO / IAU — 시민·항해·천문박명 표준 정의
- JPL DE421 — 천체력, 유효 ~1900–2050
