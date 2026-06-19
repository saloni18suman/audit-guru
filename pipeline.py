"""
LangGraph pipeline — orchestrates OCR → Validation → Audit agents.
State flows through a typed dict; each node updates the state in place.
"""

import os
import json
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END

from agents.ocr_agent import run_ocr_agent
from agents.validation_agent import run_validation_agent
from agents.audit_agent import run_audit_agent


class PipelineState(TypedDict):
    pdf_path: str
    ocr_result: dict
    validation_result: dict
    audit_result: dict
    processed_invoices: list
    error: str


def ocr_node(state: PipelineState) -> PipelineState:
    try:
        result = run_ocr_agent(state["pdf_path"])
        return {**state, "ocr_result": result}
    except Exception as e:
        return {**state, "error": f"OCR failed: {e}", "ocr_result": {}}


def validation_node(state: PipelineState) -> PipelineState:
    if state.get("error"):
        return state
    try:
        result = run_validation_agent(
            state["ocr_result"],
            state.get("processed_invoices", []),
        )
        return {**state, "validation_result": result}
    except Exception as e:
        return {**state, "error": f"Validation failed: {e}", "validation_result": {}}


def audit_node(state: PipelineState) -> PipelineState:
    if state.get("error"):
        return state
    try:
        result = run_audit_agent(state["ocr_result"], state["validation_result"])
        return {**state, "audit_result": result}
    except Exception as e:
        return {**state, "error": f"Audit failed: {e}", "audit_result": {}}


def build_graph() -> StateGraph:
    graph = StateGraph(PipelineState)
    graph.add_node("ocr", ocr_node)
    graph.add_node("validation", validation_node)
    graph.add_node("audit", audit_node)

    graph.set_entry_point("ocr")
    graph.add_edge("ocr", "validation")
    graph.add_edge("validation", "audit")
    graph.add_edge("audit", END)

    return graph.compile()


_pipeline = None


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = build_graph()
    return _pipeline


def process_invoice(pdf_path: str, processed_invoices: list = None) -> dict:
    pipeline = get_pipeline()
    initial_state: PipelineState = {
        "pdf_path": pdf_path,
        "ocr_result": {},
        "validation_result": {},
        "audit_result": {},
        "processed_invoices": processed_invoices or [],
        "error": "",
    }
    final_state = pipeline.invoke(initial_state)
    return final_state
