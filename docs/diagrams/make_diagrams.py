#!/usr/bin/env python3
# © 2026 Layer1Labs Silicon Inc. All rights reserved.
# CONFIDENTIAL — ChronoHive Evaluation Package. Licensed solely for
# evaluation under the ChronoHive Terms of Confidentiality (TOC.md) and
# the ChronoHive Evaluation License (LICENSE). Do not distribute.
"""Generate styled block diagrams for docs/ARCHITECTURE.md (200 DPI)."""
from __future__ import annotations

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

HERE = os.path.dirname(os.path.abspath(__file__))

INK = "#1e293b"
MUTED = "#64748b"
ACCENT = "#0f766e"
ACCENT_LT = "#ccfbf1"
ACCENT_DK = "#115e59"
WARN = "#b45309"
WARN_LT = "#fef3c7"
BG = "#ffffff"
PANEL = "#f8fafc"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans"],
    "text.color": INK,
})


def rbox(ax, x, y, w, h, face=BG, edge=ACCENT, lw=1.6, rad=0.12):
    p = FancyBboxPatch((x, y), w, h,
                       boxstyle=f"round,pad=0.02,rounding_size={rad}",
                       facecolor=face, edgecolor=edge, linewidth=lw)
    ax.add_patch(p)
    return p


def txt(ax, x, y, s, size=10, weight="bold", color=INK, ha="center",
        va="center", style="normal", ls=1.5):
    ax.text(x, y, s, ha=ha, va=va, fontsize=size, weight=weight, color=color,
            style=style, linespacing=ls)


def arrow(ax, a, b, label=None, color=MUTED, ls="-", lw=1.6, lxoff=0.0):
    arr = FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=14,
                          color=color, linewidth=lw, linestyle=ls,
                          shrinkA=1, shrinkB=5)
    ax.add_patch(arr)
    if label:
        mx, my = (a[0] + b[0]) / 2 + lxoff, (a[1] + b[1]) / 2
        ax.text(mx + 0.28, my, label, ha="left", va="center", fontsize=8.5,
                color=color, style="italic")


def save(ax, name, w=10, h=6):
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.set_aspect("equal")
    ax.axis("off")
    path = os.path.join(HERE, name)
    plt.tight_layout(pad=0.5)
    plt.savefig(path, dpi=200, facecolor=BG, bbox_inches="tight")
    plt.close()
    print("wrote", path)


# ------------------------------------------------------------ request gating
def diagram_gating():
    W, H = 10, 7.0
    fig, ax = plt.subplots(figsize=(W, H))
    txt(ax, 5.0, 6.72, "How a request is gated \u2014 first failure wins, in order",
        size=12)

    rbox(ax, 3.9, 5.85, 2.2, 0.55)
    txt(ax, 5.0, 6.12, "Request arrives", size=10.5)

    gates = [
        ("Gate 1 \u2014 API key valid?", "missing / unknown / expired", "401"),
        ("Gate 2 \u2014 TOC executed?", "not on file for this key", "403"),
        ("Gate 3 \u2014 Quota available?", "50 scenarios/day \u00b7 60 decides/min", "429"),
        ("Gate 4 \u2014 Licensed?", "compile endpoint only", "403"),
    ]
    tops = [5.55, 4.47, 3.39, 2.31]
    bh = 0.78
    for i, ((title, note, code), y) in enumerate(zip(gates, tops)):
        rbox(ax, 2.9, y - bh, 4.2, bh, face=ACCENT_LT, edge=ACCENT)
        txt(ax, 5.0, y - 0.30, title, size=10.5)
        txt(ax, 5.0, y - 0.56, note, size=8.5, weight="normal", color=MUTED)
        # fail branch
        arrow(ax, (7.1, y - bh / 2), (8.35, y - bh / 2), color=WARN)
        rbox(ax, 8.35, y - bh / 2 - 0.24, 1.05, 0.48, face=WARN_LT, edge=WARN)
        txt(ax, 8.875, y - bh / 2, code, size=10)
        # pass arrow down (label to the right of the line)
        if i < 3:
            arrow(ax, (5.0, y - bh), (5.0, tops[i + 1]), label="pass")
        else:
            arrow(ax, (5.0, y - bh), (5.0, 1.02), label="pass")

    rbox(ax, 3.75, 0.42, 2.5, 0.60, edge=ACCENT_DK, lw=2.0)
    txt(ax, 5.0, 0.72, "Endpoint logic", size=10.5)
    save(ax, "request-gating.png", W, H)


# --------------------------------------------------------------- evaluation
def diagram_evaluation():
    W, H = 10, 6.6
    fig, ax = plt.subplots(figsize=(W, H))
    txt(ax, 5.0, 6.32, "How evaluation works \u2014 one question, three endpoints",
        size=12)
    txt(ax, 5.0, 6.02,
        "Does kernel-coordinated admission stall less than uncoordinated admission?",
        size=10, weight="normal", color=MUTED, style="italic")

    cards = [
        ("POST /v1/scenarios", "Checkpoint/prefetch simulation", [
            "baseline + coordinated per seed",
            "deterministic per seed",
            "PASS: \u226520% stall cut, makespan \u00b11%",
            "quota: 50/day",
        ]),
        ("POST /v1/admission/decide", "Live kernel decision window", [
            "submit transfer requests",
            "kernel admits earliest-deadline-first",
            "drives QoS on simulated backend",
            "quota: 60/min",
        ]),
        ("POST /v1/admission/compare", "Baseline vs coordinated run", [
            "preregistered LF workload, no-op effectors",
            "infinite capacities \u2194 real capacities",
            "delta = coordination behavior",
            "no wall-clock claims",
        ]),
    ]
    cw, chh, y0 = 3.0, 3.05, 2.05
    for i, (title, sub, body) in enumerate(cards):
        x = 0.25 + i * 3.25
        rbox(ax, x, y0, cw, chh, edge=ACCENT)
        txt(ax, x + cw / 2, y0 + chh - 0.38, title, size=10)
        txt(ax, x + cw / 2, y0 + chh - 0.68, sub, size=8.5, weight="normal",
            color=MUTED, style="italic")
        ax.plot([x + 0.35, x + cw - 0.35], [y0 + chh - 0.92] * 2, color="#e2e8f0",
                lw=1)
        for j, line in enumerate(body):
            txt(ax, x + cw / 2, y0 + chh - 1.30 - j * 0.34, line, size=8.5,
                weight="normal", ls=1.4)
        if i < 2:
            arrow(ax, (x + cw, y0 + chh / 2), (x + cw + 0.25, y0 + chh / 2))

    # kernel strip
    sy = 0.62
    rbox(ax, 0.25, sy, 9.5, 1.05, face=PANEL, edge=MUTED)
    # REAL tag
    rbox(ax, 0.55, sy + 0.55, 1.15, 0.34, face=ACCENT_LT, edge=ACCENT, lw=1.2,
         rad=0.08)
    txt(ax, 1.125, sy + 0.72, "REAL", size=8, color=ACCENT_DK)
    # SIMULATED tag
    rbox(ax, 1.85, sy + 0.55, 1.85, 0.34, face=WARN_LT, edge=WARN, lw=1.2,
         rad=0.08)
    txt(ax, 2.775, sy + 0.72, "SIMULATED", size=8, color=WARN)
    txt(ax, 5.35, sy + 0.42,
        "Real Runtime kernel makes every grant/refuse  \u00b7  Simulated backend, contention model, API surface",
        size=9, weight="normal")
    for i in range(3):
        x = 0.25 + i * 3.25 + cw / 2
        arrow(ax, (x, y0), (x, sy + 1.05), ls=(0, (4, 3)), lw=1.4)

    txt(ax, 5.0, 0.28,
        "GET /v1/scenarios/{id} fetches any stored result for your records",
        size=8.5, weight="normal", color=MUTED, style="italic")
    save(ax, "evaluation-flow.png", W, H)


# ------------------------------------------------------------------ compile
def diagram_compile():
    W, H = 10, 5.4
    fig, ax = plt.subplots(figsize=(W, H))
    txt(ax, 5.0, 5.12, "The LF \u2192 CSP1 compile pipeline", size=12)

    stages = [
        ("Your LF project", ["1\u201364 .lf files \u00b7 entrypoint",
                             "params \u00b7 capacities"], BG, ACCENT),
        ("lfc 0.13.0 gate", ["pinned validation",
                             "fail here \u2192 nothing else runs"], ACCENT_LT, ACCENT),
        ("chronoc lowering", ["validated project \u2192 kernel ops",
                              "admission-aware schedule"], BG, ACCENT),
        ("CSP1 specification", ["magic \u201cCSP1\u201d \u00b7 version",
                       "ops \u00b7 schedule \u00b7 CRC-32"], PANEL, ACCENT_DK),
    ]
    sw, shh, y0 = 2.05, 1.65, 2.55
    for i, (title, lines, face, edge) in enumerate(stages):
        x = 0.35 + i * 2.42
        rbox(ax, x, y0, sw, shh, face=face, edge=edge,
             lw=2.0 if i == 3 else 1.6)
        txt(ax, x + sw / 2, y0 + shh - 0.42, title, size=10)
        for j, line in enumerate(lines):
            txt(ax, x + sw / 2, y0 + shh - 0.82 - j * 0.32, line, size=8.5,
                weight="normal", color=MUTED, ls=1.4)
        if i < 3:
            arrow(ax, (x + sw, y0 + shh / 2), (x + sw + 0.37, y0 + shh / 2))

    rbox(ax, 2.4, 0.95, 5.2, 0.95, face=ACCENT_LT, edge=ACCENT)
    txt(ax, 5.0, 1.60, "Deterministic", size=10)
    txt(ax, 5.0, 1.28, "same project \u2192 byte-identical blob (verify with sha256sum)",
        size=8.5, weight="normal", color=MUTED)
    txt(ax, 5.0, 0.5,
        "Three ways in: hosted API (needs compile license)  \u00b7  local pinned toolchain  \u00b7  offline --check",
        size=8.5, weight="normal", color=MUTED, style="italic")
    save(ax, "compile-pipeline.png", W, H)


# ------------------------------------------------------ toolchain chain (LF doc)
def diagram_toolchain_chain():
    W, H = 10, 5.6
    fig, ax = plt.subplots(figsize=(W, H))
    txt(ax, 5.0, 5.32, "The toolchain chain \u2014 IDE to API", size=12)

    stages = [
        ("LF IDE", ["author .lf files",
                    "vscode extension",
                    "validation advisory"], BG, ACCENT),
        ("lfc 0.13.0", ["pinned \u00b7 authoritative gate",
                        "rejects \u2192 never built"], ACCENT_LT, ACCENT),
        ("chronoc (Rust)", ["accepted subset \u2192 .cspec v1",
                            "SHA-256 + provenance",
                            "no LF validation of its own"], BG, ACCENT),
        ("Engine", ["blob executor",
                    "+ Runtime kernel",
                    "admit \u00b7 start \u00b7 observe"], BG, ACCENT),
        ("Eval API", ["/v1/scenarios",
                      "/v1/admission/decide",
                      "/v1/lf/compile"], PANEL, ACCENT_DK),
    ]
    sw, shh, y0, gap = 1.62, 1.85, 2.35, 0.32
    for i, (title, lines, face, edge) in enumerate(stages):
        x = 0.31 + i * (sw + gap)
        rbox(ax, x, y0, sw, shh, face=face, edge=edge,
             lw=2.0 if i in (1, 4) else 1.6)
        txt(ax, x + sw / 2, y0 + shh - 0.42, title, size=10)
        for j, line in enumerate(lines):
            txt(ax, x + sw / 2, y0 + shh - 0.85 - j * 0.32, line, size=7.5,
                weight="normal", color=MUTED, ls=1.4)
        if i < 4:
            arrow(ax, (x + sw, y0 + shh / 2), (x + sw + gap, y0 + shh / 2))

    rbox(ax, 1.6, 0.95, 6.8, 0.95, face=ACCENT_LT, edge=ACCENT)
    txt(ax, 5.0, 1.60, "One rule for the whole chain", size=10)
    txt(ax, 5.0, 1.28, "lfc is the sole authority on valid LF \u00b7 "
                       "chronoc replaces lfc\u2019s code generator",
        size=8.5, weight="normal", color=MUTED)
    save(ax, "toolchain-chain.png", W, H)


if __name__ == "__main__":
    diagram_gating()
    diagram_evaluation()
    diagram_compile()
    diagram_toolchain_chain()
