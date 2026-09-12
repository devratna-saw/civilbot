"""
Thin wrapper around the Gemini free-tier API with function-calling wired to
the deterministic structural_engine, so the model reports engine output
instead of inventing numbers for beam/column checks.
"""
from __future__ import annotations

import os
from typing import Optional

import google.generativeai as genai

from . import structural_engine as eng

_API_KEY = os.environ.get("GEMINI_API_KEY")
_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
_configured = False


def _ensure_configured():
    global _configured
    if not _API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey "
            "and set it as an environment variable before starting the server."
        )
    if not _configured:
        genai.configure(api_key=_API_KEY)
        _configured = True


SYSTEM_PROMPTS = {
    "general": (
        "You are CivilBot, a friendly, capable general-purpose AI assistant - you can help with "
        "everyday questions on any topic, like a general chatbot. When a question touches civil or "
        "structural engineering and calls for a precise numeric result (bending moment, deflection, "
        "required member size, buckling capacity, etc.), you MUST call the matching calculation tool "
        "instead of estimating the number yourself, then explain the result in plain language."
    ),
    "student": (
        "You are CivilBot in Learning Mode - a patient tutor for civil/structural engineering students. "
        "Explain concepts step by step, connect results back to the underlying theory, and whenever a "
        "numeric result is relevant (beam design, column capacity, truss member force, etc.) call the "
        "calculation tool and then walk the student through *why* the formula produces that number, not "
        "just what the number is. Encourage the student to try changing one input at a time to build intuition."
    ),
    "professional": (
        "You are CivilBot in Professional Analysis Mode, assisting a practicing engineer who needs exact, "
        "defensible numbers for design/checking work. Never state a numeric structural result (moment, "
        "shear, deflection, stress, required dimension, buckling load) without first calling the matching "
        "calculation tool - you must ground every number in the tool's output, not your own estimate. If "
        "required inputs are missing or ambiguous, ask for them rather than assuming values. If the user "
        "has uploaded a document, prefer its extracted parameters as defaults but confirm them before use, "
        "since automatic extraction can be wrong."
    ),
}


def _schema(props: dict, required: list[str]):
    return genai.protos.Schema(
        type=genai.protos.Type.OBJECT,
        properties=props,
        required=required,
    )


def _num(desc: str):
    return genai.protos.Schema(type=genai.protos.Type.NUMBER, description=desc)


def _enum_str(desc: str, values: list[str]):
    return genai.protos.Schema(type=genai.protos.Type.STRING, description=desc, enum=values)


BEAM_TOOL = genai.protos.FunctionDeclaration(
    name="calculate_beam",
    description=(
        "Analyze a rectangular-section beam (simply supported or cantilever) under a point or "
        "uniformly distributed load: returns reactions, max bending moment, max shear, max "
        "deflection, bending stress, and pass/fail checks against allowable stress and deflection "
        "limit, plus the minimum section depth needed to pass each check. Use this for ANY beam "
        "sizing/checking question instead of estimating numbers yourself."
    ),
    parameters=_schema(
        {
            "support_type": _enum_str("Beam support condition", ["simply_supported", "cantilever"]),
            "load_type": _enum_str(
                "Load pattern: point_midspan (single point load at midspan/free end), "
                "point_at (single point load at a given distance from the left/fixed support), "
                "or udl (uniformly distributed load in N/m)",
                ["point_midspan", "point_at", "udl"],
            ),
            "span_m": _num("Span length in metres"),
            "load_value": _num("Load magnitude: newtons for point loads, N/m for udl"),
            "load_position_m": _num("Only for load_type=point_at: distance from left/fixed support, metres"),
            "width_m": _num("Rectangular section width b, metres"),
            "depth_m": _num("Rectangular section depth d, metres (the value being checked/sized)"),
            "E_pa": _num("Modulus of elasticity in pascals (default 200e9 for steel if unspecified)"),
            "allowable_stress_pa": _num("Allowable bending stress in pascals, if known"),
            "deflection_limit_ratio": _num("Span/deflection limit ratio, e.g. 360 (default 360)"),
        },
        ["support_type", "load_type", "span_m", "load_value", "width_m", "depth_m"],
    ),
)

COLUMN_TOOL = genai.protos.FunctionDeclaration(
    name="calculate_column",
    description=(
        "Check a column against Euler elastic buckling: returns critical buckling load, "
        "effective length, and safety factor against the applied axial load. Use this for ANY "
        "column buckling question instead of estimating numbers yourself."
    ),
    parameters=_schema(
        {
            "length_m": _num("Unbraced column length, metres"),
            "E_pa": _num("Modulus of elasticity, pascals (default 200e9 for steel if unspecified)"),
            "I_m4": _num("Moment of inertia of the column section about the buckling axis, m^4"),
            "K": _num("Effective length factor: 0.5 fixed-fixed, 0.7 fixed-pinned, 1.0 pinned-pinned, 2.0 fixed-free (default 1.0)"),
            "applied_load_n": _num("Applied axial load, newtons"),
        },
        ["length_m", "I_m4", "applied_load_n"],
    ),
)

TOOLS = [genai.protos.Tool(function_declarations=[BEAM_TOOL, COLUMN_TOOL])]


def _run_tool(name: str, args: dict) -> dict:
    if name == "calculate_beam":
        inp = eng.BeamInput(
            support_type=args["support_type"],
            load_type=args["load_type"],
            span_m=args["span_m"],
            load_value=args["load_value"],
            load_position_m=args.get("load_position_m"),
            E_pa=args.get("E_pa", 200e9),
            section=eng.RectSection(width_m=args["width_m"], depth_m=args["depth_m"]),
            allowable_stress_pa=args.get("allowable_stress_pa"),
            deflection_limit_ratio=args.get("deflection_limit_ratio", 360),
        )
        result = eng.analyze_beam(inp)
        return result.model_dump()
    if name == "calculate_column":
        inp = eng.ColumnInput(
            length_m=args["length_m"],
            E_pa=args.get("E_pa", 200e9),
            I_m4=args["I_m4"],
            K=args.get("K", 1.0),
            applied_load_n=args["applied_load_n"],
        )
        result = eng.analyze_column(inp)
        return result.model_dump()
    return {"error": f"Unknown tool {name}"}


class ChatSession:
    def __init__(self, mode: str):
        _ensure_configured()
        self.mode = mode
        self.model = genai.GenerativeModel(
            _MODEL_NAME,
            tools=TOOLS,
            system_instruction=SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["general"]),
        )
        self.chat = self.model.start_chat(enable_automatic_function_calling=False)

    def send(self, message: str) -> tuple[str, list[dict]]:
        """Returns (final_text, tool_calls_made)."""
        response = self.chat.send_message(message)
        tool_calls_made: list[dict] = []

        # Loop to resolve any function calls the model requests.
        for _ in range(5):
            fn_calls = [
                part.function_call
                for cand in response.candidates
                for part in cand.content.parts
                if part.function_call and part.function_call.name
            ]
            if not fn_calls:
                break
            responses_parts = []
            for fc in fn_calls:
                args = dict(fc.args)
                try:
                    result = _run_tool(fc.name, args)
                except eng.EngineError as e:
                    result = {"error": str(e)}
                except Exception as e:  # defensive: surface engine errors to the model, don't 500
                    result = {"error": f"Calculation failed: {e}"}
                tool_calls_made.append({"tool": fc.name, "args": args, "result": result})
                responses_parts.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(name=fc.name, response={"result": result})
                    )
                )
            response = self.chat.send_message(genai.protos.Content(parts=responses_parts, role="user"))

        try:
            final_text = response.text
        except Exception:
            final_text = "".join(
                part.text for cand in response.candidates for part in cand.content.parts if hasattr(part, "text") and part.text
            ) or "(no response text)"
        return final_text, tool_calls_made
