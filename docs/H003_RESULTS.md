# H003 — BTC Displacement vs Reversal Probability

**Status: SUPPORTED**
**Evidence level: STATISTICALLY_SUPPORTED** (not ROBUSTNESS_VALIDATED — see §6)
**Date:** 20 July 2026 · **Sample:** n = 2,738 resolved windows
**Data period:** 2026-07-07 → 2026-07-20 (11 full days; 17–19 Jul collector outage excluded)

---

## 1. Hypothesis

Does BTC displacement magnitude from the 5-minute window open relate to the
probability that the leading direction reverses before resolution?

## 2. Method (fixed before querying)

| Element | Definition |
|---|---|
| Observation unit | One resolved 5-minute BTC window |
| Observation point | Last clean snapshot with `elapsed_s BETWEEN 240 AND 285` |
| Displacement | `(btc_price − btc_open) / btc_open × 10000` bp |
| Reversal | `sign(displacement) ≠ resolved winner` |
| Source | `research.clean_snapshots` ⋈ `research.clean_markets` |
| Exclusions | Contaminated rows (via clean views), null/zero `btc_open` |

`btc_open` is the window's opening price, known at t=0 — **no look-ahead**.
`winner` is used strictly as an outcome label, never as an input.

## 3. Primary result

| Displacement | n | Reversals | Rate | 95% Wilson CI |
|---|---|---|---|---|
| <1bp | 333 | 79 | **23.72%** | [19.47%, 28.58%] |
| 1–3bp | 560 | 50 | 8.93% | [6.84%, 11.58%] |
| 3–7bp | 867 | 17 | 1.96% | [1.23%, 3.12%] |
| 7–15bp | 694 | 2 | 0.29% | [0.08%, 1.04%] |
| 15bp+ | 284 | 0 | **0.00%** | [0.00%, 1.33%] |

Monotonically decreasing across all five bands. Overall reversal rate 5.41%.

- `<1bp` vs `3–7bp`: z = 12.44, **p = 1.5×10⁻³⁵**, relative risk **12.1×**
- `<1bp` vs `7–15bp`: z = 13.04, **p = 7.0×10⁻³⁹**, relative risk **82×**

## 4. Devil's advocate battery

### 4.1 UP vs DOWN symmetry — **PASSED**

| Band | DOWN | UP | Diff | p |
|---|---|---|---|---|
| <1bp | 24.21% (190) | 23.08% (143) | +1.13pp | 0.810 |
| 1–3bp | 10.07% (288) | 7.72% (272) | +2.35pp | 0.330 |
| 3–7bp | 1.97% (458) | 1.96% (409) | +0.01pp | 0.992 |
| 7–15bp | 0.30% (335) | 0.28% (359) | +0.02pp | 0.961 |
| 15bp+ | 0.00% (144) | 0.00% (140) | 0.00pp | 1.000 |

No directional asymmetry at any band. The 3–7bp bands differ by 0.01pp.

### 4.2 Day-by-day stability — **PASSED (11/11)**

| Date | n | <1bp rev | ≥3bp rev |
|---|---|---|---|
| 07-07 | 160 | 33.3% | 1.7% |
| 07-08 | 227 | 17.2% | 1.8% |
| 07-09 | 238 | 35.0% | 1.1% |
| 07-10 | 254 | 19.0% | 0.6% |
| 07-11 | 269 | 19.7% | 0.0% |
| 07-12 | 267 | 15.6% | 2.0% |
| 07-13 | 277 | 25.0% | 1.6% |
| 07-14 | 288 | 27.3% | 0.9% |
| 07-15 | 288 | 31.0% | 0.0% |
| 07-16 | 285 | 16.7% | 1.5% |
| 07-19 | 130 | 33.3% | 0.0% |

`<1bp` range 15.6–35.0% (mean 24.8%). `≥3bp` range 0.0–2.0% (mean 1.0%).
**The ranges never overlap on any day.** Worst-case ≥3bp day (2.0%) is still
far below the best-case <1bp day (15.6%).

This is the test that destroyed the earlier "mid-window momentum" candidate,
which was positive in aggregate but negative in its first half. H003 shows no
such regime dependence.

*(07-20 excluded from stability stats: partial day, n=56, tiny <1bp subsample.)*

### 4.3 Tail behaviour (7–15bp, 15bp+) — **PASSED**

The decline continues monotonically to zero. 284 windows above 15bp produced
**zero** reversals. No inflection or reversal-of-trend at the extreme.

### 4.4 Survivorship — **INFERRED, not directly queried**

n = 2,738 observations against ~2,750 resolved windows in the period ⇒ roughly
**99.5% coverage**. Windows lacking a 240–285s snapshot are rare, so selection
bias is negligible. Should still be confirmed with a direct query.

### 4.5 TTR conditioning — **PASSED, but with a decisive caveat**

Displacement measured at each stage; outcome always at resolution.

| Elapsed | n <1bp | rev <1bp | n ≥3bp | rev ≥3bp | Separation | p |
|---|---|---|---|---|---|---|
| 0s | 820 | 37.9% | 1,022 | **25.4%** | 1.5× | 8.5e-09 |
| 60s | 567 | 45.3% | 1,435 | **16.9%** | 2.7× | 6.5e-40 |
| 120s | 469 | 40.7% | 1,681 | **9.6%** | 4.2× | 1.9e-58 |
| 180s | 383 | 37.1% | 1,803 | **4.4%** | 8.4× | 8.6e-83 |
| 240–285s | 333 | 23.7% | ~1,845 | **~1.5%** | ~16× | 1.5e-35 |

*(The raw 240s bucket spans elapsed 240–299; its last snapshot sits essentially
at resolution and cannot reverse by construction, so the clean 240–285s
measurement is used instead.)*

**The relationship holds at every stage — and it is highly significant even at
60s. But its discriminative power grows monotonically through the window, which
creates the central problem for tradability:**

- At **60s**, where ~73% of all volume trades, a ≥3bp displacement **still
  reverses 16.9% of the time** — roughly 1 in 6.
- At **240s+**, where reversal risk falls to ~1.5% (1 in 67), **liquidity is
  nearly absent** (prior work: only 32 fills ever recorded in the final 15s).

**The signal is weakest exactly where you can trade, and strongest where you
cannot.** This is a classic information/liquidity tradeoff and it is the single
most important constraint on any strategy built from H003.

## 5. Practical interpretation

A flat window (<1bp) reverses roughly **1 in 4** times. A displaced window
(7–15bp) reverses about **1 in 345**. The decline is smooth and continuous — a
**stable region**, not a threshold. No single "optimal" value should be inferred.

**On the Last Shadow 3bp gate (unchanged, as instructed):** the gate's real
justification is that the `<1bp` band is where reversals concentrate, and — per
the price-conditioning work — where expectancy turns negative (−1.4%). Above
1bp, EV was roughly flat (+6.9% to +8.2%). So 3bp sits in a defensible region,
and moving to 5bp would sacrifice the 449-window 3–5bp band for no measurable
EV gain.

## 6. Why NOT ROBUSTNESS_VALIDATED

Two gaps remain, and one finding actively argues against tradability:

1. **Survivorship inferred, not queried** (§4.4).
2. **TTR conditioning reveals an information/liquidity tradeoff** (§4.5): the
   protective effect is weak (16.9% reversal at ≥3bp) in the liquid part of the
   window and only becomes strong where liquidity has evaporated.
3. **Most importantly: low reversal risk ≠ profitable trade.** The
   price-conditioning analysis showed Polymarket largely prices displacement in
   — the favourite's mid rises 0.81 → 0.94 across the bands. A residual +4–5
   point gap between realised and implied probability exists, but it was
   measured on **midpoints, not executable asks**, with no spread, slippage,
   fee or partial-fill modelling, in a part of the window where liquidity is
   thin. **H003 is a statement about market structure, not a tradable edge.**

## 7. Reproduction

```sql
WITH obs AS (
  SELECT DISTINCT ON (s.slug) s.slug,
         (s.btc_price - m.btc_open)/m.btc_open*10000.0 AS disp_bp,
         m.winner, m.open_time
  FROM research.clean_snapshots s
  JOIN research.clean_markets m ON s.slug = m.slug
  WHERE s.elapsed_s BETWEEN 240 AND 285
    AND m.btc_open IS NOT NULL AND m.btc_open <> 0
  ORDER BY s.slug, s.elapsed_s DESC
)
SELECT CASE WHEN abs(disp_bp)<1 THEN 'a_lt1'
            WHEN abs(disp_bp)<3 THEN 'b_1to3'
            WHEN abs(disp_bp)<7 THEN 'c_3to7'
            WHEN abs(disp_bp)<15 THEN 'd_7to15'
            ELSE 'e_15plus' END AS band,
       count(*) n,
       count(*) FILTER (WHERE (disp_bp>0 AND winner='DOWN')
                           OR (disp_bp<0 AND winner='UP')) rev
FROM obs GROUP BY band ORDER BY band;
```

## 8. Next experiments

1. **Executability study** — now the decisive experiment. Measure spread,
   depth and realistic fills at 60s / 120s / 180s, where the signal is weaker
   but tradable, rather than at 240s+ where it is strong but unfillable.
2. **Direct survivorship query** — close §4.4.
3. **Original executability framing** — spread, depth and realistic fills at 240–285s.
   This decides whether the +4–5 point gap is money or an artefact of quoting
   midpoints. Until then, no strategy change is justified.

---

**Phantom V2 was not modified. The Last Shadow 3bp gate was not changed.**
