"""Boundary services — orchestration that lives outside the LangGraph graph.

V26 adds portfolio import (CSV + natural-language parsing). These run at the
API boundary, never inside the graph, so graph purity (portfolio_dict ->
FinalReport) is preserved.
"""
