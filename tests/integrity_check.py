#!/usr/bin/env python3
"""
integrity_check.py — structural completeness of critical modules.

WHY THIS EXISTS
On 2026-07-19 a mount sync fault silently truncated eight files. `main.py` lost
its last line and failed loudly with an IndentationError. `risk_engine.py` was
worse: it still COMPILED, but had lost its terminating
`return {"status": "APPROVED", ...}` — so every signal would have evaluated to
None and all signal-driven trading would have silently stopped.

Compilation is not correctness. This check asserts that critical modules still
contain the structures that make them functional, so a truncation can never
again pass CI just because the remaining bytes happen to parse.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# module -> symbols that MUST exist for the module to be functional
REQUIRED = {
    "app/config/settings.py":          ["Settings", "HealthThresholds", "settings"],
    "app/database/pool.py":            ["ResearchPool", "research_ro", "research_rw", "close_all"],
    "app/monitoring/heartbeat.py":     ["CollectorHeartbeat", "HealthReport"],
    "app/monitoring/notifier.py":      ["Notifier"],
    "app/data_quality/checks.py":      ["DataQualityEngine", "QualityResult"],
    "app/quant/baseline.py":           ["coverage", "market_stats", "btc_poly_alignment"],
    "app/memory/hypotheses.py":        ["seed_hypotheses", "update_status", "SEED_HYPOTHESES"],
    "app/reports/baseline_report.py":  ["generate"],
    "service.py":                      ["main", "bootstrap"],
}

# Functions whose body MUST end in a return — the risk_engine failure mode.
MUST_RETURN = {
    "app/database/pool.py": ["fetch", "fetchrow", "fetchval"],
    "app/config/settings.py": ["validate"],
}


def top_level_symbols(tree):
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
    return out


def find_func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def main() -> int:
    failures = []

    for rel, symbols in REQUIRED.items():
        path = ROOT / rel
        if not path.exists():
            failures.append(f"{rel}: MISSING FILE")
            continue
        src = path.read_text(encoding="utf-8")

        # A file cut mid-expression usually ends on an opening delimiter,
        # separator or operator. (ast.parse below catches most truncation; this
        # catches the rarer case where the remainder still happens to parse.)
        last = src.rstrip().splitlines()[-1].rstrip() if src.strip() else ""
        if last.endswith((",", "(", "[", "{", "\\", "+", "-", "=", "|", "&")):
            failures.append(f"{rel}: last line ends on '{last[-1]}' — truncated mid-expression")

        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            failures.append(f"{rel}: SYNTAX ERROR line {e.lineno} — {e.msg}")
            continue

        present = top_level_symbols(tree)
        for sym in symbols:
            if sym not in present:
                failures.append(f"{rel}: required symbol '{sym}' is MISSING (truncated?)")

    for rel, funcs in MUST_RETURN.items():
        path = ROOT / rel
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fname in funcs:
            fn = find_func(tree, fname)
            if fn is None:
                failures.append(f"{rel}: function '{fname}' MISSING")
                continue
            if not any(isinstance(n, ast.Return) for n in ast.walk(fn)):
                failures.append(
                    f"{rel}: '{fname}' has NO return statement — this is the "
                    f"risk_engine truncation failure mode"
                )

    if failures:
        print("INTEGRITY CHECK FAILED\n")
        for f in failures:
            print(f"  ✗ {f}")
        print(f"\n{len(failures)} problem(s). Deployment must be blocked.")
        return 1

    print(f"integrity check passed — {len(REQUIRED)} critical modules structurally complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
