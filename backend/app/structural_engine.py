"""
Rule-based structural engineering calculators.

These are closed-form / classical-statics methods (not a general FEA solver):
- Beam bending, shear and deflection for standard support/load cases.
- Truss analysis via the method of joints (statically determinate trusses only).
- Column buckling via the Euler formula.

All inputs/outputs use SI units (metres, newtons, pascals) unless noted.
Every result carries the formula/method used so the chatbot layer can quote
the exact basis for a number instead of inventing one.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np
from pydantic import BaseModel, Field


class EngineError(Exception):
    """Raised when the requested calculation is not well-posed."""


# ---------------------------------------------------------------------------
# Beam analysis
# ---------------------------------------------------------------------------

class RectSection(BaseModel):
    shape: Literal["rectangular"] = "rectangular"
    width_m: float = Field(..., gt=0, description="Section width b (m)")
    depth_m: float = Field(..., gt=0, description="Section depth d (m)")

    @property
    def I(self) -> float:  # noqa: N802 - moment of inertia, standard symbol
        return self.width_m * self.depth_m ** 3 / 12.0

    @property
    def c(self) -> float:
        return self.depth_m / 2.0

    @property
    def section_modulus(self) -> float:
        return self.I / self.c


class BeamInput(BaseModel):
    support_type: Literal["simply_supported", "cantilever"]
    load_type: Literal["point_midspan", "point_at", "udl"]
    span_m: float = Field(..., gt=0)
    load_value: float = Field(..., description="N for point load, N/m for UDL")
    load_position_m: Optional[float] = Field(
        None, description="Distance from left/fixed support, only for load_type='point_at'"
    )
    E_pa: float = Field(200e9, gt=0, description="Modulus of elasticity, default = structural steel")
    section: RectSection
    allowable_stress_pa: Optional[float] = Field(None, gt=0)
    deflection_limit_ratio: float = Field(360, gt=0, description="Span/ratio deflection limit, e.g. 360")


class BeamResult(BaseModel):
    method: str
    reactions_n: dict
    max_bending_moment_nm: float
    max_shear_n: float
    max_deflection_m: float
    bending_stress_pa: float
    allowable_deflection_m: float
    bending_check: Optional[bool]
    deflection_check: bool
    required_depth_for_bending_m: Optional[float] = None
    required_depth_for_deflection_m: Optional[float] = None
    notes: list[str] = field(default_factory=list)


def analyze_beam(inp: BeamInput) -> BeamResult:
    L = inp.span_m
    E = inp.E_pa
    I = inp.section.I
    notes: list[str] = []
    reactions: dict[str, float] = {}

    if inp.support_type == "simply_supported":
        if inp.load_type == "udl":
            w = inp.load_value
            R = w * L / 2.0
            reactions = {"R_left_n": R, "R_right_n": R}
            Mmax = w * L ** 2 / 8.0
            Vmax = R
            delta = 5 * w * L ** 4 / (384 * E * I)
            method = "Simply supported beam, uniformly distributed load: M=wL^2/8, delta=5wL^4/(384EI)"
        elif inp.load_type == "point_midspan":
            P = inp.load_value
            R = P / 2.0
            reactions = {"R_left_n": R, "R_right_n": R}
            Mmax = P * L / 4.0
            Vmax = R
            delta = P * L ** 3 / (48 * E * I)
            method = "Simply supported beam, point load at midspan: M=PL/4, delta=PL^3/(48EI)"
        else:  # point_at arbitrary position -> a from left support
            if inp.load_position_m is None:
                raise EngineError("load_position_m is required for load_type='point_at'")
            a = inp.load_position_m
            b = L - a
            if not (0 < a < L):
                raise EngineError("load_position_m must be strictly between 0 and span_m")
            P = inp.load_value
            R_left = P * b / L
            R_right = P * a / L
            reactions = {"R_left_n": R_left, "R_right_n": R_right}
            Mmax = P * a * b / L
            Vmax = max(R_left, R_right)
            # Deflection under the load itself (standard formula), reported as max approx.
            delta = (P * a ** 2 * b ** 2) / (3 * E * I * L)
            method = "Simply supported beam, point load at distance a from left support (Mmax=Pab/L)"
            notes.append("Deflection formula gives deflection at the load point, not necessarily the true global max for off-centre loads.")
    else:  # cantilever, fixed at left, free at right
        if inp.load_type == "udl":
            w = inp.load_value
            R = w * L
            reactions = {"R_fixed_n": R, "M_fixed_nm": w * L ** 2 / 2.0}
            Mmax = w * L ** 2 / 2.0
            Vmax = R
            delta = w * L ** 4 / (8 * E * I)
            method = "Cantilever beam, uniformly distributed load: M=wL^2/2, delta=wL^4/(8EI)"
        else:  # point load at free end (point_midspan/point_at both treated as free-end load)
            P = inp.load_value
            reactions = {"R_fixed_n": P, "M_fixed_nm": P * L}
            Mmax = P * L
            Vmax = P
            delta = P * L ** 3 / (3 * E * I)
            method = "Cantilever beam, point load at free end: M=PL, delta=PL^3/(3EI)"

    bending_stress = Mmax * inp.section.c / I
    allowable_defl = L / inp.deflection_limit_ratio
    deflection_check = delta <= allowable_defl

    bending_check = None
    req_depth_bending = None
    req_depth_deflection = None
    b_width = inp.section.width_m

    if inp.allowable_stress_pa:
        bending_check = bending_stress <= inp.allowable_stress_pa
        s_req = Mmax / inp.allowable_stress_pa
        req_depth_bending = math.sqrt(6 * s_req / b_width)

    if not deflection_check:
        i_req = 5 * inp.load_value * L ** 4 / (384 * E * allowable_defl) if inp.load_type == "udl" and inp.support_type == "simply_supported" else None
        if i_req is not None:
            req_depth_deflection = (12 * i_req / b_width) ** (1 / 3)
        else:
            scale = (delta / allowable_defl) ** (1 / 3)
            req_depth_deflection = inp.section.depth_m * scale
            notes.append("Required depth for deflection estimated by scaling (I ~ d^3) since a closed-form solve wasn't applicable to this load case.")

    return BeamResult(
        method=method,
        reactions_n=reactions,
        max_bending_moment_nm=Mmax,
        max_shear_n=Vmax,
        max_deflection_m=delta,
        bending_stress_pa=bending_stress,
        allowable_deflection_m=allowable_defl,
        bending_check=bending_check,
        deflection_check=deflection_check,
        required_depth_for_bending_m=req_depth_bending,
        required_depth_for_deflection_m=req_depth_deflection,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Truss analysis (method of joints, statically determinate only)
# ---------------------------------------------------------------------------

class TrussNode(BaseModel):
    id: str
    x_m: float
    y_m: float
    support: Literal["none", "pin", "roller_x", "roller_y"] = "none"


class TrussMember(BaseModel):
    id: str
    node_i: str
    node_j: str
    area_m2: Optional[float] = Field(None, gt=0)


class TrussLoad(BaseModel):
    node: str
    fx_n: float = 0.0
    fy_n: float = 0.0


class TrussInput(BaseModel):
    nodes: list[TrussNode]
    members: list[TrussMember]
    loads: list[TrussLoad]
    allowable_stress_pa: Optional[float] = Field(None, gt=0)


class TrussResult(BaseModel):
    method: str
    determinate: bool
    reactions_n: dict
    member_forces_n: dict
    member_types: dict
    member_stress_pa: Optional[dict] = None
    overstressed_members: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def analyze_truss(inp: TrussInput) -> TrussResult:
    nodes = {n.id: n for n in inp.nodes}
    if len(nodes) != len(inp.nodes):
        raise EngineError("Duplicate node ids")

    # Build reaction unknowns per support type
    reaction_defs: list[tuple[str, str]] = []  # (node_id, component: 'x'|'y')
    for n in inp.nodes:
        if n.support == "pin":
            reaction_defs.append((n.id, "x"))
            reaction_defs.append((n.id, "y"))
        elif n.support == "roller_x":
            reaction_defs.append((n.id, "x"))  # roller providing a horizontal reaction only
        elif n.support == "roller_y":
            reaction_defs.append((n.id, "y"))  # roller providing a vertical reaction only (typical floor roller)

    m = len(inp.members)
    r = len(reaction_defs)
    n_joints = len(inp.nodes)
    dof = 2 * n_joints

    if m + r != dof:
        raise EngineError(
            f"Truss is not statically determinate for the method of joints "
            f"(members + reactions = {m + r}, required = 2*joints = {dof}). "
            "Add/remove members or supports, or use a stiffness/FEA solver for indeterminate trusses."
        )

    unknowns = [("member", mem.id) for mem in inp.members] + [("reaction", *rd) for rd in reaction_defs]
    A = np.zeros((dof, len(unknowns)))
    b = np.zeros(dof)

    node_order = [n.id for n in inp.nodes]
    node_row = {nid: 2 * i for i, nid in enumerate(node_order)}

    member_geom = {}
    for mem in inp.members:
        ni, nj = nodes[mem.node_i], nodes[mem.node_j]
        dx, dy = nj.x_m - ni.x_m, nj.y_m - ni.y_m
        length = math.hypot(dx, dy)
        if length == 0:
            raise EngineError(f"Member {mem.id} has zero length")
        cx, cy = dx / length, dy / length
        member_geom[mem.id] = (cx, cy, length)

    for col, (kind, *rest) in enumerate(unknowns):
        if kind == "member":
            mem_id = rest[0]
            mem = next(mm for mm in inp.members if mm.id == mem_id)
            cx, cy, _ = member_geom[mem_id]
            # Force on node_i from member = tension pulls node_i toward node_j
            A[node_row[mem.node_i], col] += cx
            A[node_row[mem.node_i] + 1, col] += cy
            # Force on node_j is opposite direction
            A[node_row[mem.node_j], col] += -cx
            A[node_row[mem.node_j] + 1, col] += -cy
        else:
            node_id, comp = rest
            row = node_row[node_id] + (0 if comp == "x" else 1)
            A[row, col] = 1.0

    for ld in inp.loads:
        if ld.node not in node_row:
            raise EngineError(f"Load references unknown node {ld.node}")
        b[node_row[ld.node]] -= ld.fx_n
        b[node_row[ld.node] + 1] -= ld.fy_n

    try:
        x = np.linalg.solve(A, b)
    except np.linalg.LinAlgError as exc:
        raise EngineError(
            "Truss geometry/support layout is unstable (mechanism) even though the member/reaction count matches - "
            "check for a valid, non-collinear support arrangement."
        ) from exc

    member_forces = {}
    member_types = {}
    member_stress = {} if inp.allowable_stress_pa or any(mm.area_m2 for mm in inp.members) else None
    overstressed = []

    for col, (kind, *rest) in enumerate(unknowns):
        if kind == "member":
            mem_id = rest[0]
            force = x[col]
            member_forces[mem_id] = force
            member_types[mem_id] = "tension" if force > 1e-9 else ("compression" if force < -1e-9 else "zero-force")
            mem = next(mm for mm in inp.members if mm.id == mem_id)
            if mem.area_m2:
                stress = force / mem.area_m2
                if member_stress is not None:
                    member_stress[mem_id] = stress
                if inp.allowable_stress_pa and abs(stress) > inp.allowable_stress_pa:
                    overstressed.append(mem_id)

    reactions = {}
    for col, (kind, *rest) in enumerate(unknowns):
        if kind == "reaction":
            node_id, comp = rest
            reactions[f"{node_id}_{comp}_n"] = x[col]

    return TrussResult(
        method="Method of joints (statics equilibrium solved as one linear system); statically determinate trusses only.",
        determinate=True,
        reactions_n=reactions,
        member_forces_n=member_forces,
        member_types=member_types,
        member_stress_pa=member_stress,
        overstressed_members=overstressed,
    )


# ---------------------------------------------------------------------------
# Column buckling (Euler)
# ---------------------------------------------------------------------------

class ColumnInput(BaseModel):
    length_m: float = Field(..., gt=0)
    E_pa: float = Field(200e9, gt=0)
    I_m4: float = Field(..., gt=0)
    K: float = Field(1.0, gt=0, description="Effective length factor: 0.5 fixed-fixed, 0.7 fixed-pinned, 1.0 pinned-pinned, 2.0 fixed-free")
    applied_load_n: float = Field(..., gt=0)


class ColumnResult(BaseModel):
    method: str
    critical_load_n: float
    effective_length_m: float
    safety_factor: float
    buckling_check: bool


def analyze_column(inp: ColumnInput) -> ColumnResult:
    le = inp.K * inp.length_m
    pcr = math.pi ** 2 * inp.E_pa * inp.I_m4 / le ** 2
    sf = pcr / inp.applied_load_n
    return ColumnResult(
        method="Euler buckling: Pcr = pi^2 * E * I / (K*L)^2",
        critical_load_n=pcr,
        effective_length_m=le,
        safety_factor=sf,
        buckling_check=sf >= 1.0,
    )
