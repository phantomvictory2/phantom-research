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

---

# ADDENDUM — Executability Study (20 July 2026)

**Question:** does H003's statistical relationship survive the price you'd
actually pay?

**Method:** entry taken at the **ask**, not the midpoint. UP entries use
`up_ask` directly; DOWN entries use `1 − up_bid` (the binary-market identity,
since the collector stores bid/ask for the UP side only). Buy the displaced
side, hold to resolution, payout 1 or 0.

## Results — real executable prices

| t | Band | n | Spread | Entry (ask) | Win% | Implied | Edge | EV/$1 | EV−1% | Robust? |
|---|---|---|---|---|---|---|---|---|---|---|
| 60s | <1bp | 84 | 0.0177 | 0.5456 | 52.4% | 54.6% | −2.2 | −0.040 | −0.050 | no |
| 60s | 1–3bp | 127 | 0.0192 | 0.6159 | 63.0% | 61.6% | +1.4 | +0.023 | +0.013 | no |
| 60s | 3–7bp | 109 | 0.0191 | 0.6859 | 74.3% | 68.6% | +5.7 | +0.083 | +0.073 | no |
| 60s | 7bp+ | 46 | 0.0148 | 0.7957 | 80.4% | 79.6% | +0.9 | +0.011 | +0.001 | no |
| 120s | <1bp | 77 | 0.0208 | 0.5452 | 50.6% | 54.5% | −3.9 | −0.071 | −0.081 | no |
| 120s | 1–3bp | 113 | 0.0200 | 0.6312 | 63.7% | 63.1% | +0.6 | +0.010 | −0.001 | no |
| 120s | 3–7bp | 144 | 0.0197 | 0.7310 | 79.9% | 73.1% | +6.8 | +0.093 | +0.083 | borderline |
| 120s | 7bp+ | 52 | 0.0160 | 0.8355 | 94.2% | 83.5% | +10.7 | +0.128 | +0.118 | **yes** |
| 180s | <1bp | 88 | 0.0183 | 0.5294 | 63.6% | 52.9% | +10.7 | +0.202 | +0.192 | **yes** |
| 180s | 1–3bp | 127 | 0.0235 | 0.6633 | 68.5% | 66.3% | +2.2 | +0.033 | +0.023 | no |
| 180s | 3–7bp | 131 | 0.0179 | 0.7635 | 86.3% | 76.3% | +9.9 | +0.130 | +0.120 | **yes** |
| 180s | 7bp+ | 54 | 0.0166 | 0.8623 | 96.3% | 86.2% | +10.1 | +0.117 | +0.107 | **yes** |

"Robust?" = EV still positive using the **pessimistic** (lower 95% Wilson) bound
on the win rate.

## Verdict — H003 does NOT convert to a demonstrated edge where liquidity is

**At 60s — where ~73% of all volume trades — no band survives.** Edges are
+0.9 to +5.7pp and every one collapses under its own confidence interval. The
market is priced close to efficiently at the moment you can actually transact.

**Spread is the mechanism.** At ~1.8–2.4¢ on prices of 0.55–0.86, the round-trip
cost consumes most of a 2–6pp edge before any fee is applied.

**Apparent edges appear only at 120–180s**, i.e. *after* the liquidity peak —
the same information/liquidity tension found in §4.5, now confirmed with real
prices rather than midpoints.

## Why this is NOT a green light

1. **No depth data.** `snapshots` stores no size. We know the ask *price*, not
   how much is available at it. The wallet study found average fills of
   \$13–80 — an edge that cannot be scaled is not a business.
2. **Multiple comparisons.** 12 cells were tested; 4 "survive". No Bonferroni
   or FDR correction has been applied. Some survivors are likely noise.
3. **Averaging bias.** EV is computed from *average* ask and *average* win rate
   per cell, not per-window. Jensen's inequality makes this an approximation.
4. **The 180s <1bp cell (+0.202) is suspicious** — flat windows should be the
   *least* informative, yet it shows the largest EV. Most likely small-sample
   noise (n=88); treat as a red flag on the method, not a discovery.
5. **No slippage or partial-fill modelling.** The −1% column is a placeholder,
   not a calibrated cost model from `execution_journal`.

## Status

**H003 remains SUPPORTED / STATISTICALLY_SUPPORTED — and explicitly NOT
tradable.** The executability study was designed to kill the idea and it
substantially did so for the liquid part of the window. The 120–180s residual
is a *lead worth testing properly*, not an edge.

**No strategy change is justified. The Last Shadow 3bp gate remains unchanged.**

## Required before any strategy work

1. **Collect order-book depth** — without size at the ask, none of this is
   actionable. This is now the top data-collection priority.
2. **Per-window EV** with multiple-comparison correction.
3. **Calibrate costs from `execution_journal`** real slippage, not a 1% guess.
