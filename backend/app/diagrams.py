"""
Renders PNG diagrams (loading/shear/moment for beams, force diagrams for
trusses) straight from structural_engine inputs/outputs - no separate
image-generation model involved, so these are exact and free to produce.

Kept out of the Gemini tool-calling path on purpose: embedding image bytes
in a function_response would blow up the model's context for no benefit.
These are only served to the Simulator panel via dedicated endpoints.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from . import structural_engine as eng

_TENSION = "#d64550"
_COMPRESSION = "#3b82c4"
_ZERO = "#9aa5b8"
_BEAM = "#e7ebf5"
_ACCENT = "#ff8a3d"
_BG = "#151b2c"
_GRID = "#2a3350"


def _style_axes(ax):
    ax.set_facecolor(_BG)
    ax.tick_params(colors=_BEAM, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(_GRID)
    ax.grid(True, color=_GRID, linewidth=0.5, alpha=0.6)
    ax.xaxis.label.set_color(_BEAM)
    ax.yaxis.label.set_color(_BEAM)
    ax.title.set_color(_BEAM)


def _fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=_BG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _beam_curves(inp: eng.BeamInput):
    """Returns (xs, shear_n, moment_nm, load_desc) sampled along the span."""
    L = inp.span_m
    xs = np.linspace(0, L, 300)
    P_or_w = inp.load_value

    if inp.support_type == "simply_supported":
        if inp.load_type == "udl":
            w = P_or_w
            R = w * L / 2
            V = R - w * xs
            M = R * xs - w * xs ** 2 / 2
            desc = f"UDL {w:,.0f} N/m"
        elif inp.load_type == "point_midspan":
            P = P_or_w
            R = P / 2
            a = L / 2
            V = np.where(xs <= a, R, R - P)
            M = np.where(xs <= a, R * xs, R * xs - P * (xs - a))
            desc = f"Point load {P:,.0f} N at midspan"
        else:
            a = inp.load_position_m
            b = L - a
            P = P_or_w
            R_left = P * b / L
            R_right = P * a / L
            V = np.where(xs <= a, R_left, -R_right)
            M = np.where(xs <= a, R_left * xs, R_left * xs - P * (xs - a))
            desc = f"Point load {P:,.0f} N at {a:.2g} m from left support"
    else:
        if inp.load_type == "udl":
            w = P_or_w
            V = w * (L - xs)
            M = -w * (L - xs) ** 2 / 2
            desc = f"UDL {w:,.0f} N/m"
        else:
            P = P_or_w
            V = np.full_like(xs, P)
            M = -P * (L - xs)
            desc = f"Point load {P:,.0f} N at free end"

    return xs, V, M, desc


def _draw_support(ax, x, kind, y=0.0):
    size = 0.06
    if kind == "pin_left":
        ax.plot([x - size, x, x + size, x - size], [y - 2 * size, y, y - 2 * size, y - 2 * size], color=_BEAM, lw=1.2)
    elif kind == "roller_right":
        ax.plot([x - size, x, x + size, x - size], [y - 2 * size, y, y - 2 * size, y - 2 * size], color=_BEAM, lw=1.2)
        circ = plt.Circle((x, y - 2.4 * size), size * 0.5, color=_BEAM, fill=False)
        ax.add_patch(circ)
    elif kind == "fixed":
        ax.plot([x, x], [y - 3 * size, y + 3 * size], color=_BEAM, lw=3)
        for i in range(5):
            yy = y - 3 * size + i * 1.5 * size
            ax.plot([x - size, x], [yy, yy + size * 0.6], color=_BEAM, lw=0.8)


def beam_diagram_png(inp: eng.BeamInput, result: eng.BeamResult) -> bytes:
    L = inp.span_m
    xs, V, M, load_desc = _beam_curves(inp)

    fig, (ax0, ax1, ax2) = plt.subplots(3, 1, figsize=(7, 6.4), sharex=True)
    fig.patch.set_facecolor(_BG)

    ax0.plot([0, L], [0, 0], color=_BEAM, lw=3)
    if inp.support_type == "simply_supported":
        _draw_support(ax0, 0, "pin_left")
        _draw_support(ax0, L, "roller_right")
    else:
        _draw_support(ax0, 0, "fixed")

    if inp.load_type == "udl":
        for xi in np.linspace(0.03 * L, 0.97 * L, 14):
            ax0.annotate("", xy=(xi, 0.02), xytext=(xi, 0.22),
                         arrowprops=dict(arrowstyle="->", color=_ACCENT, lw=1))
    else:
        px = L if inp.support_type == "cantilever" else (
            L / 2 if inp.load_type == "point_midspan" else inp.load_position_m
        )
        ax0.annotate("", xy=(px, 0.02), xytext=(px, 0.3),
                     arrowprops=dict(arrowstyle="->", color=_ACCENT, lw=2))
    ax0.set_ylim(-0.35, 0.4)
    ax0.set_yticks([])
    ax0.set_title(f"Loading  |  {inp.support_type.replace('_', ' ')}, {load_desc}", fontsize=10)
    _style_axes(ax0)
    ax0.grid(False)

    ax1.fill_between(xs, V, 0, color=_ACCENT, alpha=0.35)
    ax1.plot(xs, V, color=_ACCENT, lw=1.6)
    ax1.axhline(0, color=_GRID, lw=1)
    ax1.set_ylabel("Shear V (N)")
    ax1.set_title(f"Shear force diagram  (max |V| = {result.max_shear_n:,.0f} N)", fontsize=10)
    _style_axes(ax1)

    ax2.fill_between(xs, M, 0, color="#4d8dff", alpha=0.35)
    ax2.plot(xs, M, color="#4d8dff", lw=1.6)
    ax2.axhline(0, color=_GRID, lw=1)
    ax2.set_ylabel("Moment M (N·m)")
    ax2.set_xlabel("Position along span (m)")
    ax2.set_title(f"Bending moment diagram  (max |M| = {result.max_bending_moment_nm:,.0f} N·m)", fontsize=10)
    _style_axes(ax2)

    fig.tight_layout()
    return _fig_to_png(fig)


def truss_diagram_png(inp: eng.TrussInput, result: eng.TrussResult) -> bytes:
    nodes = {n.id: n for n in inp.nodes}
    xs = [n.x_m for n in inp.nodes]
    ys = [n.y_m for n in inp.nodes]
    span_x = max(xs) - min(xs) or 1.0
    span_y = max(ys) - min(ys) or 1.0
    arrow_len = 0.12 * max(span_x, span_y)

    fig, ax = plt.subplots(figsize=(7, 5.5))
    fig.patch.set_facecolor(_BG)

    forces = result.member_forces_n
    max_force = max((abs(f) for f in forces.values()), default=1.0) or 1.0

    for mem in inp.members:
        ni, nj = nodes[mem.node_i], nodes[mem.node_j]
        force = forces.get(mem.id, 0.0)
        mtype = result.member_types.get(mem.id, "zero-force")
        color = _TENSION if mtype == "tension" else (_COMPRESSION if mtype == "compression" else _ZERO)
        lw = 1 + 3 * (abs(force) / max_force)
        ax.plot([ni.x_m, nj.x_m], [ni.y_m, nj.y_m], color=color, lw=lw, solid_capstyle="round", zorder=2)
        mx, my = (ni.x_m + nj.x_m) / 2, (ni.y_m + nj.y_m) / 2
        ax.annotate(f"{mem.id}\n{force:,.0f} N", (mx, my), color=_BEAM, fontsize=7.5,
                    ha="center", va="center", zorder=4,
                    bbox=dict(boxstyle="round,pad=0.15", fc=_BG, ec=_GRID, lw=0.5))

    for n in inp.nodes:
        ax.scatter([n.x_m], [n.y_m], color=_BEAM, s=40, zorder=3)
        ax.annotate(n.id, (n.x_m, n.y_m), color=_BEAM, fontsize=9, fontweight="bold",
                    xytext=(6, 6), textcoords="offset points", zorder=5)
        if n.support != "none":
            marker = "^" if "roller" not in n.support else "o"
            ax.scatter([n.x_m], [n.y_m - arrow_len * 0.4], color=_ACCENT, marker="v", s=90, zorder=3)

    for ld in inp.loads:
        n = nodes[ld.node]
        if abs(ld.fy_n) > 1e-9:
            dy = -arrow_len if ld.fy_n < 0 else arrow_len
            ax.annotate("", xy=(n.x_m, n.y_m + dy), xytext=(n.x_m, n.y_m),
                        arrowprops=dict(arrowstyle="->", color="#f5c542", lw=2), zorder=6)
            ax.annotate(f"{abs(ld.fy_n):,.0f} N", (n.x_m, n.y_m + dy), color="#f5c542", fontsize=8,
                        ha="center", va="top" if dy < 0 else "bottom")
        if abs(ld.fx_n) > 1e-9:
            dx = arrow_len if ld.fx_n > 0 else -arrow_len
            ax.annotate("", xy=(n.x_m + dx, n.y_m), xytext=(n.x_m, n.y_m),
                        arrowprops=dict(arrowstyle="->", color="#f5c542", lw=2), zorder=6)

    ax.set_aspect("equal", adjustable="datalim")
    ax.set_facecolor(_BG)
    ax.set_title("Truss analysis  |  red = tension, blue = compression, grey = zero-force", fontsize=10, color=_BEAM)
    margin = 0.25 * max(span_x, span_y)
    ax.set_xlim(min(xs) - margin, max(xs) + margin)
    ax.set_ylim(min(ys) - margin - arrow_len, max(ys) + margin)
    ax.tick_params(colors=_BEAM, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(_GRID)
    ax.grid(True, color=_GRID, linewidth=0.5, alpha=0.5)

    fig.tight_layout()
    return _fig_to_png(fig)
