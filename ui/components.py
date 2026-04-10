"""Reusable visual components for ChainCopilot dashboard.

Every function here returns rendered Streamlit widgets or HTML.
Charts use Plotly for professional, interactive visualizations.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.enums import ActionType, ApprovalStatus, Mode
from core.models import DecisionLog, KPIState, Plan, SystemState
from ui.styles import badge, section_header

# ── Plotly layout defaults ────────────────────────────────────────────────────

_PLOTLY_LAYOUT = dict(
    font=dict(family="Plus Jakarta Sans, sans-serif", size=12, color="#A3AED0"),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=0, r=0, t=28, b=0),
    hoverlabel=dict(
        bgcolor="#2B3674",
        font_color="#FFFFFF",
        font_family="Plus Jakarta Sans, sans-serif",
        font_size=12,
    ),
)

_CHART_COLORS = ["#4318FF", "#39B8FF", "#05CD99", "#FFCE20", "#EE5D50", "#E1E9F8"]


def _apply_layout(fig: go.Figure, height: int = 280) -> go.Figure:
    fig.update_layout(**_PLOTLY_LAYOUT, height=height, showlegend=True,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    fig.update_xaxes(gridcolor="#E2E8F0", zerolinecolor="#E2E8F0", tickfont=dict(color="#A3AED0"))
    fig.update_yaxes(gridcolor="#E2E8F0", zerolinecolor="#E2E8F0", tickfont=dict(color="#A3AED0"))
    return fig


# ── KPI rendering ────────────────────────────────────────────────────────────

_KPI_THRESHOLDS = {
    #                  (good,  bad,  higher_is_better)
    "service_level":   (0.90,  0.75, True),
    "disruption_risk": (0.25,  0.50, False),
    "recovery_speed":  (0.70,  0.45, True),
    "stockout_risk":   (0.20,  0.40, False),
}

def _kpi_color_class(key: str, value: float) -> str:
    if key not in _KPI_THRESHOLDS:
        return "blue"
    good, bad, higher = _KPI_THRESHOLDS[key]
    if higher:
        return "green" if value >= good else ("red" if value <= bad else "yellow")
    else:
        return "green" if value <= good else ("red" if value >= bad else "yellow")


def render_kpi_cards(state: SystemState) -> None:
    """5 KPI cards with colored top-accent bar."""
    kpis = state.kpis
    items = [
        ("Service Level",   "service_level",   f"{kpis.service_level:.1%}", "speed"),
        ("Total Cost",      "total_cost",       f"${kpis.total_cost:,.0f}", "attach_money"),
        ("Disruption Risk", "disruption_risk",  f"{kpis.disruption_risk:.1%}", "warning"),
        ("Recovery Speed",  "recovery_speed",   f"{kpis.recovery_speed:.1%}", "bolt"),
        ("Stockout Risk",   "stockout_risk",    f"{kpis.stockout_risk:.1%}", "inventory_2"),
    ]
    cols = st.columns(5)
    for col, (label, key, formatted, icon) in zip(cols, items):
        color = _kpi_color_class(key, getattr(kpis, key))
        col.markdown(
            f'<div class="kpi-card kpi-{color}">'
            f'<div class="kpi-icon-wrapper"><span class="material-icons">{icon}</span></div>'
            f'<div class="kpi-content">'
            f'<div class="kpi-label">{label}</div>'
            f'<div class="kpi-value">{formatted}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )


def render_kpi_delta_cards(before: KPIState, after: KPIState) -> None:
    """5 KPI metric cards with before→after delta values."""
    items = [
        ("Service Level",   "service_level",   f"{after.service_level:.1%}",   after.service_level - before.service_level),
        ("Total Cost",      "total_cost",       f"${after.total_cost:,.0f}",    after.total_cost - before.total_cost),
        ("Disruption Risk", "disruption_risk",  f"{after.disruption_risk:.1%}", after.disruption_risk - before.disruption_risk),
        ("Recovery Speed",  "recovery_speed",   f"{after.recovery_speed:.1%}",  after.recovery_speed - before.recovery_speed),
        ("Stockout Risk",   "stockout_risk",    f"{after.stockout_risk:.1%}",   after.stockout_risk - before.stockout_risk),
    ]
    cols = st.columns(5)
    for col, (label, key, fmt, delta) in zip(cols, items):
        _, _, higher = _KPI_THRESHOLDS.get(key, (0,0,True))
        if key == "total_cost":
            delta_str = f"{delta:+,.0f}"
            dc = "inverse"
        else:
            delta_str = f"{delta:+.3f}"
            dc = "normal" if (higher and delta >= 0) or (not higher and delta <= 0) else "inverse"
        col.metric(label, fmt, delta=delta_str, delta_color=dc)


# ── Mode banner ───────────────────────────────────────────────────────────────

def render_mode_banner(state: SystemState) -> None:
    modes_map = {
        Mode.NORMAL: ("normal", "check_circle", "Normal Operations",
                       "System is running cost-optimized daily planning."),
        Mode.CRISIS: ("crisis", "bolt", "Crisis Response Active",
                       "Disruption detected — recovery and resilience prioritized."),
        Mode.APPROVAL: ("approval", "lock", "Awaiting Approval",
                         "A high-risk recovery plan requires human approval."),
    }
    cls, icon, title, msg = modes_map.get(state.mode, modes_map[Mode.NORMAL])
    st.markdown(
        f'<div class="mode-banner {cls}">'
        f'<span class="material-icons" style="font-size:1.4rem;">{icon}</span>'
        f'<div><strong>{title}</strong> — {msg}</div></div>',
        unsafe_allow_html=True,
    )


# ── Inventory charts ──────────────────────────────────────────────────────────

def render_inventory_bar_chart(state: SystemState) -> None:
    """Grouped bar chart: On Hand / Incoming / Forecast per SKU."""
    items = list(state.inventory.values())
    if not items:
        st.info("No inventory data available.")
        return

    df = pd.DataFrame({
        "SKU": [it.sku for it in items],
        "On Hand": [it.on_hand for it in items],
        "Incoming": [it.incoming_qty for it in items],
        "Forecast Demand": [it.forecast_qty for it in items],
    })
    fig = px.bar(
        df.melt(id_vars="SKU", var_name="Type", value_name="Quantity"),
        x="SKU", y="Quantity", color="Type", barmode="group",
        color_discrete_sequence=["#4318FF", "#39B8FF", "#FFB547"],
    )
    _apply_layout(fig, 260)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── Supplier charts ───────────────────────────────────────────────────────────

def render_supplier_chart(state: SystemState) -> None:
    """Horizontal bar chart of supplier reliability with primary indicator."""
    suppliers = list(state.suppliers.values())
    if not suppliers:
        st.info("No supplier data.")
        return

    df = pd.DataFrame({
        "Supplier": [s.supplier_id for s in suppliers],
        "Reliability": [s.reliability for s in suppliers],
        "Primary": ["★ Primary" if s.is_primary else "Backup" for s in suppliers],
        "Lead Days": [s.lead_time_days for s in suppliers],
    })
    fig = px.bar(
        df, x="Reliability", y="Supplier", color="Primary", orientation="h",
        color_discrete_map={"★ Primary": "#4318FF", "Backup": "#A3AED0"},
        text="Reliability",
    )
    fig.update_traces(texttemplate="%{text:.0%}", textposition="outside")
    fig.update_xaxes(range=[0, 1.15], tickformat=".0%")
    _apply_layout(fig, 240)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── Route risk chart ──────────────────────────────────────────────────────────

def render_route_chart(state: SystemState) -> None:
    """Scatter chart: transit days vs cost, sized by risk score."""
    routes = list(state.routes.values())
    if not routes:
        st.info("No route data.")
        return

    df = pd.DataFrame({
        "Route": [r.route_id for r in routes],
        "Leg": [f"{r.origin} → {r.destination}" for r in routes],
        "Transit Days": [r.transit_days for r in routes],
        "Cost": [r.cost for r in routes],
        "Risk": [r.risk_score for r in routes],
        "Status": [r.status for r in routes],
    })
    fig = px.scatter(
        df, x="Transit Days", y="Cost", size="Risk", color="Status",
        hover_data=["Route", "Leg"],
        color_discrete_map={"active": "#05CD99", "blocked": "#EE5D50"},
        size_max=30,
    )
    _apply_layout(fig, 260)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── KPI comparison charts ─────────────────────────────────────────────────────

def render_kpi_comparison_chart(before: KPIState, after: KPIState) -> None:
    """Grouped bar chart comparing before/after KPIs (rate metrics only)."""
    metrics = ["Service Level", "Disruption Risk", "Recovery Speed", "Stockout Risk"]
    before_vals = [before.service_level, before.disruption_risk, before.recovery_speed, before.stockout_risk]
    after_vals = [after.service_level, after.disruption_risk, after.recovery_speed, after.stockout_risk]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Before", x=metrics, y=before_vals, marker_color="#E2E8F0"))
    fig.add_trace(go.Bar(name="After",  x=metrics, y=after_vals,  marker_color="#4318FF"))
    fig.update_layout(barmode="group", yaxis_tickformat=".0%")
    _apply_layout(fig, 280)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_kpi_radar(before: KPIState, after: KPIState) -> None:
    """Radar/spider chart overlaying before vs after KPIs."""
    categories = ["Service Level", "Disruption Risk", "Recovery Speed", "Stockout Risk"]
    before_vals = [before.service_level, before.disruption_risk, before.recovery_speed, before.stockout_risk]
    after_vals = [after.service_level, after.disruption_risk, after.recovery_speed, after.stockout_risk]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=before_vals + [before_vals[0]], theta=categories + [categories[0]],
                                   name="Before", line=dict(color="#A3AED0"), fill="toself",
                                   fillcolor="rgba(163,174,208,0.15)"))
    fig.add_trace(go.Scatterpolar(r=after_vals + [after_vals[0]], theta=categories + [categories[0]],
                                   name="After", line=dict(color="#4318FF"), fill="toself",
                                   fillcolor="rgba(67,24,255,0.12)"))
    fig.update_layout(polar=dict(radialaxis=dict(range=[0, 1], tickformat=".0%")))
    _apply_layout(fig, 320)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── Score breakdown ───────────────────────────────────────────────────────────

def render_score_breakdown(log: DecisionLog) -> None:
    """Donut chart of score breakdown components."""
    if not log.score_breakdown:
        return
    labels = list(log.score_breakdown.keys())
    values = list(log.score_breakdown.values())
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.55,
        marker=dict(colors=_CHART_COLORS[:len(labels)]),
        textinfo="label+percent",
        textfont=dict(size=11),
    ))
    _apply_layout(fig, 260)
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── Event pills ───────────────────────────────────────────────────────────────

def render_event_pills(state: SystemState) -> None:
    if not state.active_events:
        st.markdown(badge("No active disruptions", "green"), unsafe_allow_html=True)
        return
    pills_html = " ".join(
        badge(f"{e.type.value}  ·  {e.severity:.0%}", "red" if e.severity >= 0.5 else "yellow")
        for e in state.active_events
    )
    st.markdown(pills_html, unsafe_allow_html=True)


# ── Demo stepper ──────────────────────────────────────────────────────────────

def render_demo_stepper(state: SystemState) -> None:
    latest = state.decision_logs[-1] if state.decision_logs else None
    steps = [
        ("Daily Planning", "done" if latest else "idle",
         "Plan generated." if latest else "Run the daily plan to begin."),
        ("Disruption Sensing", "done" if state.active_events else "idle",
         ", ".join(e.type.value for e in state.active_events) if state.active_events else "No disruptions detected."),
        ("Autonomous Replan", "done" if latest and latest.event_ids else "idle",
         f"Plan {latest.plan_id}" if latest and latest.event_ids else "Awaiting disruption event."),
        ("Approval Gate",
         "waiting" if state.pending_plan else ("done" if latest and latest.approval_required else "idle"),
         "Pending human approval." if state.pending_plan else "No approval needed."),
        ("Learning", "done" if state.scenario_history else "idle",
         f"{len(state.scenario_history)} scenario(s) recorded." if state.scenario_history else "No outcomes recorded."),
    ]

    html = ""
    for name, status, detail in steps:
        dot_cls = status  # done | waiting | idle
        icon = "check" if status == "done" else ("hourglass_empty" if status == "waiting" else "more_horiz")
        html += (
            f'<div class="stepper-step">'
            f'<div class="stepper-dot {dot_cls}"><span class="material-icons" style="font-size:16px;">{icon}</span></div>'
            f'<div><div class="stepper-name">{name}</div>'
            f'<div class="stepper-detail">{detail}</div></div>'
            f'</div>'
        )
    st.markdown(html, unsafe_allow_html=True)


# ── Dataframe helpers ─────────────────────────────────────────────────────────

def mode_summary(state: SystemState) -> dict:
    m = {
        Mode.NORMAL: ("Normal", "success", "Cost-optimized daily operations."),
        Mode.CRISIS: ("Crisis", "warning", "Disruption detected — recovery mode."),
        Mode.APPROVAL: ("Pending Approval", "error", "High-risk plan awaiting human decision."),
    }
    label, tone, msg = m.get(state.mode, m[Mode.NORMAL])
    return {"label": label, "tone": tone, "message": msg}


def selected_action_summary(plan: Plan | None) -> dict | None:
    if plan is None or not plan.actions:
        return None
    action = next((a for a in plan.actions if a.action_type != ActionType.NO_OP), plan.actions[0])
    return {
        "title": f"{action.action_type.value.replace('_',' ').title()} → {action.target_id}",
        "impact": f"Service: {action.estimated_service_delta:+.2f} · Risk: {action.estimated_risk_delta:+.2f} · Cost: {action.estimated_cost_delta:+.2f}",
        "detail": action.reason or "—",
    }


def plan_actions_dataframe(plan: Plan) -> pd.DataFrame:
    return pd.DataFrame([
        {"Action": a.action_type.value, "Target": a.target_id,
         "Cost Δ": f"{a.estimated_cost_delta:+.1f}", "Risk Δ": f"{a.estimated_risk_delta:+.2f}",
         "Recovery Hrs": f"{a.estimated_recovery_hours:.0f}", "Reason": a.reason or "—"}
        for a in plan.actions
    ])


def inventory_dataframe(state: SystemState) -> pd.DataFrame:
    return pd.DataFrame([
        {"SKU": it.sku, "On Hand": it.on_hand, "Incoming": it.incoming_qty,
         "Forecast": it.forecast_qty, "Safety Stock": it.safety_stock,
         "Supplier": it.preferred_supplier_id, "Route": it.preferred_route_id}
        for it in state.inventory.values()
    ])


def score_breakdown_dataframe(log: DecisionLog) -> pd.DataFrame:
    return pd.DataFrame([
        {"Component": c, "Score": round(v, 4)} for c, v in log.score_breakdown.items()
    ])


def rejected_actions_dataframe(log: DecisionLog) -> pd.DataFrame:
    return pd.DataFrame(log.rejected_actions) if log.rejected_actions else pd.DataFrame()


def memory_tables(state: SystemState) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    mem = state.memory
    if not mem:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    sup_df = pd.DataFrame([{"Supplier": k, "Reliability": v} for k,v in mem.supplier_reliability.items()])
    route_df = pd.DataFrame([{"Route": k, "Disruption Prior": v} for k,v in mem.route_disruption_priors.items()])
    scen_df = pd.DataFrame([
        {"Scenario": k, "Runs": d.get("runs",0), "Latest Plan": d.get("latest_plan_id","—"),
         "Approval": d.get("latest_approval_status","—")}
        for k,d in mem.scenario_outcomes.items()
    ])
    return sup_df, route_df, scen_df


def approval_badge(log: DecisionLog | None) -> str:
    if log is None:
        return badge("No decisions", "gray")
    badge_map = {
        ApprovalStatus.PENDING: ("Pending", "yellow"),
        ApprovalStatus.APPROVED: ("Approved", "green"),
        ApprovalStatus.AUTO_APPLIED: ("Auto-applied", "blue"),
        ApprovalStatus.REJECTED: ("Rejected", "red"),
        ApprovalStatus.NOT_REQUIRED: ("Not Required", "gray"),
    }
    text, variant = badge_map.get(log.approval_status, ("Unknown", "gray"))
    return badge(text, variant)

def styled_table(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No data available.")
        return
    html = df.to_html(classes="custom-table", index=False, border=0, escape=True)
    wrapped = f'<div class="table-container">{html}</div>'
    st.markdown(wrapped, unsafe_allow_html=True)
