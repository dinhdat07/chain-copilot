"""ChainCopilot Design System — Modern SaaS Aesthetic (Horizon UI Inspired)."""
from __future__ import annotations

import streamlit as st

_CSS = """
<style>
/* ── Fonts & Icons ──────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,400,1,0');

html, body, [class*="css"], .stMarkdown, .stText,
[data-testid="stMetricLabel"], [data-testid="stMetricValue"] {
    font-family: 'Plus Jakarta Sans', -apple-system, sans-serif !important;
}

.material-icons {
    font-family: 'Material Symbols Rounded';
    font-weight: normal;
    font-style: normal;
    font-size: 24px;
    display: inline-block;
    line-height: 1;
    text-transform: none;
    letter-spacing: normal;
    word-wrap: normal;
    white-space: nowrap;
    direction: ltr;
    vertical-align: middle;
}

/* ── Global Layout ──────────────────────────────────────── */
.stApp, .block-container {
    background-color: #F4F7FE !important; /* Soft cool gray background */
}

/* Container padding */
.block-container {
    padding-top: 2rem !important;
    padding-bottom: 4rem !important;
    max-width: 1400px;
}

/* ── Typography & Headers ───────────────────────────────── */
h1 {
    color: #2B3674 !important;
    font-weight: 700 !important;
    font-size: 2.2rem !important;
    margin-bottom: 0.2rem !important;
    display: flex;
    align-items: center;
    gap: 12px;
}

h1 .material-icons {
    font-size: 2.6rem;
    color: #4318FF;
    background: #FFFFFF;
    padding: 8px;
    border-radius: 16px;
    box-shadow: 0px 4px 20px rgba(112, 144, 176, 0.12);
}

.page-subtitle {
    color: #A3AED0;
    font-size: 0.95rem;
    font-weight: 500;
    margin-top: 0 !important;
    margin-bottom: 2rem !important;
}

.section-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: #2B3674;
    margin: 2rem 0 0.5rem 0;
    display: flex;
    align-items: center;
    gap: 10px;
}

.section-title .material-icons {
    color: #4318FF;
    font-size: 1.4rem;
}

.section-sub {
    font-size: 0.85rem;
    font-weight: 500;
    color: #A3AED0;
    margin: 0 0 1.5rem 0;
}

/* ── Cards & Containers ─────────────────────────────────── */
.custom-card, 
[data-testid="stMetric"], 
[data-testid="stDataFrameContainer"],
.stTabs [data-baseweb="tab-panel"] {
    background: #FFFFFF !important;
    border: none !important;
    border-radius: 20px !important;
    box-shadow: 0px 18px 40px rgba(112, 144, 176, 0.08) !important;
    transition: all 0.3s ease;
}

[data-testid="stDataFrameContainer"] {
    padding: 12px !important;
}

[data-testid="stMetric"] {
    padding: 24px !important;
    background: #FFFFFF !important;
    display: flex;
    flex-direction: column;
    justify-content: center;
}

[data-testid="stMetricLabel"] {
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    color: #A3AED0 !important;
    text-transform: capitalize !important;
    letter-spacing: 0px !important;
}

[data-testid="stMetricValue"] {
    font-size: 2rem !important;
    font-weight: 700 !important;
    color: #2B3674 !important;
    margin-top: 4px;
}

[data-testid="stMetricDelta"] {
    font-weight: 600 !important;
    font-size: 0.9rem !important;
}

/* Custom Component Cards (HTML) */
.kpi-card {
    background: #FFFFFF;
    border-radius: 20px;
    padding: 20px;
    box-shadow: 0px 18px 40px rgba(112, 144, 176, 0.08);
    display: flex;
    align-items: center;
    gap: 16px;
    height: 100%;
}

.kpi-icon-wrapper {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}
.kpi-icon-wrapper .material-icons {
    font-size: 28px;
}

/* Icon Colors */
.kpi-green  .kpi-icon-wrapper { background: #E2FDEE; color: #05CD99; }
.kpi-yellow .kpi-icon-wrapper { background: #FFF4DE; color: #FFB547; }
.kpi-red    .kpi-icon-wrapper { background: #FFE2E5; color: #EE5D50; }
.kpi-blue   .kpi-icon-wrapper { background: #F4F7FE; color: #4318FF; }

.kpi-content {
    display: flex;
    flex-direction: column;
}
.kpi-label {
    font-size: 0.85rem;
    font-weight: 600;
    color: #A3AED0;
}
.kpi-value {
    font-size: 1.6rem;
    font-weight: 700;
    color: #2B3674;
    line-height: 1.2;
    margin-top: 2px;
}

/* ── Custom Data Tables ─────────────────────────────────── */
.table-container {
    width: 100%;
    overflow-x: auto;
    border-radius: 16px;
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    box-shadow: 0px 4px 10px rgba(112, 144, 176, 0.05);
}

.custom-table {
    width: 100%;
    border-collapse: collapse;
    font-family: 'Plus Jakarta Sans', sans-serif;
    margin: 0;
}

.custom-table th {
    background-color: #F4F7FE;
    color: #A3AED0;
    font-size: 0.8rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 16px 20px;
    text-align: left;
    border-bottom: 2px solid #E2E8F0;
}

.custom-table td {
    padding: 16px 20px;
    color: #2B3674;
    font-size: 0.9rem;
    font-weight: 600;
    border-bottom: 1px solid #F1F5F9;
    white-space: nowrap;
}

.custom-table tr:last-child td {
    border-bottom: none;
}

.custom-table tbody tr:hover td {
    background-color: #F8FAFC;
    color: #4318FF; /* Highlight on hover */
}

/* ── Sidebar ────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: #FFFFFF !important;
    border-right: none !important;
    box-shadow: 4px 0 24px rgba(112, 144, 176, 0.06) !important;
}
section[data-testid="stSidebar"] > div:first-child {
    padding-top: 1.5rem;
}

/* ── Buttons ────────────────────────────────────────────── */
.stButton > button {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-weight: 600 !important;
    border-radius: 12px !important;
    padding: 0.5rem 1rem !important;
    transition: all 0.2s ease !important;
    border: none !important;
    box-shadow: 0px 4px 12px rgba(112, 144, 176, 0.1) !important;
}
.stButton > button[kind="primary"] {
    background: #4318FF !important; /* Horizon Blue */
    color: #FFFFFF !important;
    box-shadow: 0px 8px 16px rgba(67, 24, 255, 0.25) !important;
}
.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0px 12px 20px rgba(112, 144, 176, 0.15) !important;
}
.stButton > button[kind="primary"]:hover {
    background: #3311DB !important;
    box-shadow: 0px 12px 24px rgba(67, 24, 255, 0.35) !important;
}

/* ── Tabs ───────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 16px;
    background: none !important;
    border: none !important;
    margin-bottom: 16px;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;
    color: #A3AED0 !important;
    padding: 10px 16px;
    border: none !important;
    background: transparent !important;
    border-radius: 12px;
    transition: all 0.2s ease;
}
.stTabs [aria-selected="true"] {
    color: #4318FF !important;
    background: #FFFFFF !important;
    box-shadow: 0px 4px 14px rgba(112, 144, 176, 0.12) !important;
}

/* ── Mode Banner ────────────────────────────────────────── */
.mode-banner {
    border-radius: 20px;
    padding: 16px 24px;
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 24px;
    box-shadow: 0px 10px 30px rgba(112, 144, 176, 0.1);
}
.mode-banner.normal  { background: linear-gradient(135deg, #05CF9A 0%, #03A177 100%); color: #fff; }
.mode-banner.crisis  { background: linear-gradient(135deg, #FFB547 0%, #F59300 100%); color: #fff; }
.mode-banner.approval{ background: linear-gradient(135deg, #EE5D50 0%, #D83A2C 100%); color: #fff; }

.mode-banner .material-icons {
    font-size: 32px;
    background: rgba(255,255,255,0.2);
    padding: 10px;
    border-radius: 16px;
}
.mode-banner strong {
    font-size: 1.1rem;
    font-weight: 700;
    display: block;
    margin-bottom: 2px;
}
.mode-banner span:not(.material-icons) {
    font-size: 0.9rem;
    opacity: 0.9;
}

/* ── Badges ─────────────────────────────────────────────── */
.badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 6px 14px;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    box-shadow: 0px 4px 10px rgba(112,144,176,0.1);
}
.badge-green  { background:#E2FDEE; color:#05CD99; }
.badge-yellow { background:#FFF4DE; color:#FFB547; }
.badge-red    { background:#FFE2E5; color:#EE5D50; }
.badge-blue   { background:#F4F7FE; color:#4318FF; }
.badge-gray   { background:#F1F5F9; color:#A3AED0; }

/* ── Stepper (Agentic Loop) ─────────────────────────────── */
.stepper-container {
    background: #FFFFFF;
    border-radius: 20px;
    padding: 24px;
    box-shadow: 0px 18px 40px rgba(112, 144, 176, 0.08);
}
.stepper-step {
    display: flex;
    align-items: flex-start;
    gap: 16px;
    padding: 14px 16px;
    border-radius: 16px;
    margin-bottom: 8px;
    background: #F4F7FE;
    transition: all 0.2s ease;
}
.stepper-step:last-child { margin-bottom: 0; }
.stepper-dot {
    width: 36px; height: 36px;
    border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    color: #fff;
    box-shadow: 0px 4px 10px rgba(112,144,176,0.15);
}
.stepper-dot.done    { background: #05CD99; }
.stepper-dot.waiting { background: #FFB547; }
.stepper-dot.idle    { background: #CBD5E1; color: #64748B; box-shadow: none; }
.stepper-name {
    font-size: 0.95rem;
    font-weight: 700;
    color: #2B3674;
    margin-bottom: 2px;
}
.stepper-detail {
    font-size: 0.8rem;
    color: #A3AED0;
    font-weight: 500;
}

/* ── Scenario Card ──────────────────────────────────────── */
.scenario-card {
    background: #FFFFFF;
    border-radius: 20px;
    padding: 24px;
    box-shadow: 0px 18px 40px rgba(112, 144, 176, 0.08);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    min-height: 140px;
    position: relative;
    overflow: hidden;
}
.scenario-card::after {
    content: '';
    position: absolute;
    top: 0; right: 0; bottom: 0; left: 0;
    border-radius: 20px;
    box-shadow: 0px 18px 40px rgba(67, 24, 255, 0.15);
    opacity: 0;
    transition: opacity 0.3s;
    pointer-events: none;
}
.scenario-card:hover {
    transform: translateY(-4px);
}
.scenario-card:hover::after {
    opacity: 1;
}
.scenario-card.blocked {
    opacity: 0.6;
    pointer-events: none;
    filter: grayscale(100%);
}
.scenario-icon {
    width: 50px; height: 50px;
    border-radius: 14px;
    background: #F4F7FE;
    color: #4318FF;
    display: flex; align-items: center; justify-content: center;
    margin-bottom: 16px;
}
.scenario-icon .material-icons { font-size: 28px; }
.scenario-title {
    font-size: 1.1rem;
    font-weight: 700;
    color: #2B3674;
    margin-bottom: 6px;
}
.scenario-desc {
    font-size: 0.85rem;
    color: #A3AED0;
    font-weight: 500;
    line-height: 1.5;
}

/* ── Approval Block ─────────────────────────────────────── */
.approval-block {
    background: #FFE2E5;
    border-radius: 20px;
    padding: 20px 24px;
    margin-bottom: 24px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    box-shadow: 0px 10px 30px rgba(238, 93, 80, 0.15);
}
.approval-title {
    font-size: 1.1rem;
    font-weight: 700;
    color: #EE5D50;
    display: flex;
    align-items: center;
    gap: 10px;
}
.approval-detail {
    font-size: 0.9rem;
    color: #D83A2C;
    font-weight: 500;
}

/* ── Timeline ───────────────────────────────────────────── */
.timeline-item {
    display: flex;
    gap: 20px;
    align-items: flex-start;
    position: relative;
}
.timeline-rail {
    display: flex;
    flex-direction: column;
    align-items: center;
    position: absolute;
    left: 8px;
    top: 4px;
    bottom: -24px;
}
.timeline-dot {
    width: 16px; height: 16px;
    border-radius: 50%;
    border: 4px solid #FFFFFF;
    box-shadow: 0px 0px 0px 2px rgba(112, 144, 176, 0.2);
    flex-shrink: 0;
    z-index: 2;
}
.timeline-line {
    width: 2px;
    height: 100%;
    background: #E2E8F0;
    margin-top: 4px;
}
.timeline-card {
    flex: 1;
    background: #FFFFFF;
    border-radius: 16px;
    padding: 16px 20px;
    margin-bottom: 16px;
    margin-left: 40px;
    box-shadow: 0px 10px 30px rgba(112, 144, 176, 0.06);
}
.timeline-id {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 0.95rem;
    font-weight: 700;
    color: #2B3674;
}
.timeline-meta {
    font-size: 0.85rem;
    font-weight: 500;
    color: #A3AED0;
    margin-top: 4px;
}
</style>
"""

def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)

def section_header(title: str, subtitle: str = "", icon: str = "") -> None:
    icon_html = f'<span class="material-icons">{icon}</span>' if icon else ""
    sub_html = f'<p class="section-sub">{subtitle}</p>' if subtitle else ""
    st.markdown(f'<p class="section-title">{icon_html}{title}</p>{sub_html}', unsafe_allow_html=True)

def badge(text: str, variant: str = "blue") -> str:
    return f'<span class="badge badge-{variant}">{text}</span>'
