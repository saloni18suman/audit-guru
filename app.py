import io, os, sys, uuid
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))
from config import load_config
load_config()
from db import init_db, load_all_results, save_review, save_corrections, get_audit_trail, save_queued_job
from s3_store import upload_invoice, get_presigned_url, is_available as s3_available
from sqs_queue import send_job, queue_depth
from agents.summary_agent import run_summary_agent
from report_pdf import build_report_pdf

init_db()
APP_NAME = os.environ.get("APP_NAME", "AnomaGuard")
st.set_page_config(page_title=APP_NAME, page_icon="🧾", layout="wide")

# ══════════════════════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html,body,.stApp{background:#F9FAFB;font-family:'Inter',-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;}
#MainMenu,footer,header{visibility:hidden;}
[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"]{display:none;}
.block-container{padding:0 !important;max-width:100% !important;}
section[data-testid="stMain"]>.block-container{padding:0 !important;}

/* ── Tabs (Fieldguide-style: light bar, green underline on active) ── */
.stTabs{margin-top:0;}
.stTabs [data-baseweb="tab-list"]{
  background:#ffffff;padding:0 28px;gap:4px;
  border-bottom:1px solid #E5E7EB;
}
.stTabs [data-baseweb="tab"]{
  color:#667085;padding:14px 18px;font-weight:500;font-size:.88rem;
  border-radius:0;border:none;background:transparent;transition:all .15s;
  border-bottom:2px solid transparent;
}
.stTabs [data-baseweb="tab"]:hover{color:#111827;background:transparent;}
.stTabs [aria-selected="true"]{
  color:#111827 !important;background:transparent !important;font-weight:700;
  border-bottom:2px solid #16B364 !important;
}
.stTabs [data-baseweb="tab-highlight"],.stTabs [data-baseweb="tab-border"]{display:none;}
.stTabs [data-baseweb="tab-panel"]{padding:28px 28px 40px;}

/* ── Buttons ── */
.stButton>button{border-radius:8px;font-weight:600;transition:all .15s;letter-spacing:.01em;}
.stButton>button[kind="primary"]{
  background:#16B364;border:none;color:white !important;padding:10px 28px;
  box-shadow:0 3px 10px rgba(22,179,100,.4);font-size:.9rem;
}
.stButton>button[kind="primary"]:hover{background:#0E9F6E;box-shadow:0 5px 16px rgba(22,179,100,.5);}
.stButton>button[kind="secondary"]{
  background:white;border:1px solid #E5E7EB;color:#111827 !important;font-size:.875rem;
}
.stButton>button[kind="secondary"]:hover{background:#F9FAFB;}
.stDownloadButton>button{
  background:#16B364 !important;border:none !important;color:white !important;
  border-radius:8px;font-weight:700;letter-spacing:.01em;
  box-shadow:0 3px 10px rgba(22,179,100,.4);
}
.stDownloadButton>button:hover{background:#0E9F6E !important;}

/* ── Cards / Expanders ── */
[data-testid="stExpander"]{
  background:white !important;border:1px solid #E5E7EB !important;
  border-radius:12px !important;margin-bottom:12px;
  box-shadow:0 2px 10px rgba(26,54,93,.08);
}
[data-testid="stExpander"] summary{color:#111827 !important;font-weight:600;padding:14px 20px;font-size:.9rem;}
[data-testid="stExpander"] summary:hover{background:#F9FAFB;}
[data-testid="metric-container"]{background:white;border-radius:12px;padding:18px;border:1px solid #E5E7EB;}
/* Force dark text on native widgets so they stay readable regardless of browser/OS theme */
[data-testid="stMetricValue"],[data-testid="stMetricLabel"],[data-testid="stMetricLabel"] *{color:#111827 !important;}
[data-testid="stMetricDelta"]{color:#027A48 !important;}
[data-testid="stMarkdownContainer"]{color:#111827;}

/* ── Inputs ── */
.stTextArea textarea{background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;color:#111827;font-size:.875rem;}
.stProgress>div>div{background:#16B364 !important;border-radius:6px;}
.stProgress>div{background:#E5E7EB !important;border-radius:6px;height:12px !important;}
/* Keep the app readable during reruns instead of a heavy full-screen dim */
[data-stale="true"]{opacity:1 !important;}
.stApp [data-testid="stStatusWidget"]{opacity:.9;}
hr{border-color:#E5E7EB;}
[data-testid="stFileUploader"]{border:2px dashed #98A2B3 !important;border-radius:14px !important;background:white !important;padding:18px 22px !important;}
[data-testid="stFileUploader"] label{margin-bottom:10px !important;font-weight:600;color:#344054;}
[data-testid="stFileUploaderDropzone"]{padding:14px 18px !important;border-radius:10px;}

/* ── Custom components ── */
.topbar{
  background:linear-gradient(135deg,#111827 0%,#1F2937 100%);
  padding:16px 28px;display:flex;align-items:center;justify-content:space-between;
  border-bottom:4px solid #16B364;
}
.tb-left{display:flex;align-items:center;gap:16px;}
.tb-title{font-size:1.18rem;font-weight:800;color:white;letter-spacing:-.01em;}
.tb-sub{font-size:.7rem;color:#98A2B3;margin-top:2px;letter-spacing:.02em;}
.tb-badge{
  background:rgba(22,179,100,.18);border:1px solid rgba(22,179,100,.55);
  color:#6CE9A6;font-size:.72rem;font-weight:600;padding:5px 14px;border-radius:20px;
}

.kpi{background:white;border-radius:14px;padding:22px 24px;
  border:1px solid #E5E7EB;box-shadow:0 2px 10px rgba(26,54,93,.07);}
.kpi-lbl{font-size:.67rem;font-weight:700;color:#667085;text-transform:uppercase;
  letter-spacing:.09em;margin-bottom:10px;}
.kpi-val{font-size:2.5rem;font-weight:800;color:#111827;line-height:1;}
.kpi-foot{font-size:.75rem;color:#667085;margin-top:6px;}
.kpi-bar{height:4px;border-radius:2px;margin-top:16px;}

.tbl{width:100%;border-collapse:collapse;background:white;border-radius:12px;
  overflow:hidden;box-shadow:0 2px 10px rgba(26,54,93,.07);border:1px solid #E5E7EB;}
.tbl thead tr{background:#111827;}
.tbl thead th{padding:13px 16px;text-align:left;font-size:.68rem;font-weight:700;
  color:#98A2B3;text-transform:uppercase;letter-spacing:.09em;white-space:nowrap;}
.tbl tbody tr{border-bottom:1px solid #F2F4F7;transition:background .1s;}
.tbl tbody tr:last-child{border-bottom:none;}
.tbl tbody tr:hover{background:#F9FAFB;}
.tbl td{padding:12px 16px;font-size:.86rem;color:#344054;vertical-align:middle;}
.tbl .t-id{font-family:monospace;color:#1570EF;font-size:.8rem;font-weight:600;}
.tbl .t-v{font-weight:700;color:#111827;}
.tbl .t-amt{font-weight:800;color:#111827;}

.pill{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;
  border-radius:999px;font-size:.71rem;font-weight:700;letter-spacing:.02em;white-space:nowrap;}
.p-APPROVED,.p-PASSED{background:#ECFDF3;color:#05603A;border:1px solid #A6F4C5;}
.p-REJECTED,.p-FAILED{background:#FEF3F2;color:#912018;border:1px solid #FDA29B;}
.p-NEEDS_REVIEW,.p-WARNING{background:#FFFAEB;color:#B54708;border:1px solid #FDB022;}
.p-default{background:#F9FAFB;color:#475467;border:1px solid #D0D5DD;}

.rbadge{display:inline-block;padding:2px 8px;border-radius:5px;font-size:.69rem;font-weight:700;}
.rb-HIGH{background:#FEF3F2;color:#D92D20;border:1px solid #FDA29B;}
.rb-MEDIUM{background:#FFFAEB;color:#B54708;border:1px solid #FDB022;}
.rb-LOW{background:#ECFDF3;color:#027A48;border:1px solid #A6F4C5;}

.sec-t{font-size:.66rem;font-weight:700;color:#667085;text-transform:uppercase;
  letter-spacing:.09em;margin:0 0 10px;padding-bottom:6px;border-bottom:1px solid #F2F4F7;}
.kv-l{font-size:.66rem;font-weight:700;color:#667085;text-transform:uppercase;
  letter-spacing:.07em;margin-bottom:2px;}
.kv-v{font-size:.9rem;color:#111827;font-weight:600;margin-bottom:11px;}

.cb-wrap{margin-bottom:12px;}
.cb-l{font-size:.66rem;font-weight:700;color:#667085;text-transform:uppercase;
  letter-spacing:.07em;margin-bottom:4px;}
.cb-track{height:5px;background:#E5E7EB;border-radius:3px;overflow:hidden;}
.cb-fill{height:100%;border-radius:3px;}
.cb-pct{font-size:.69rem;color:#667085;margin-top:3px;}

.box-blue{background:#EFF8FF;border-left:4px solid #2E90FA;padding:12px 16px;
  border-radius:0 8px 8px 0;font-size:.84rem;color:#1F2937;line-height:1.65;margin-bottom:12px;}
.box-gold{background:#FFFAEB;border-left:4px solid #F79009;padding:12px 16px;
  border-radius:0 8px 8px 0;font-size:.84rem;color:#93370D;line-height:1.65;margin-bottom:12px;}
.policy-ref{font-size:.76rem;color:#16B364;padding:2px 0;}

.flag-row{display:flex;align-items:flex-start;gap:8px;padding:5px 0;
  font-size:.8rem;color:#344054;border-bottom:1px solid #F9FAFB;}
.flag-row:last-child{border-bottom:none;}
.flag-code{font-family:monospace;background:#F9FAFB;padding:1px 6px;border-radius:4px;font-size:.76rem;}
.li-row{display:flex;justify-content:space-between;padding:5px 0;
  font-size:.82rem;color:#344054;border-bottom:1px solid #F9FAFB;}
.li-row:last-child{border-bottom:none;}
.li-amt{font-weight:700;color:#111827;}

.case-hd{
  background:linear-gradient(135deg,#111827,#1F2937);
  padding:14px 22px;display:flex;align-items:center;justify-content:space-between;
  border-radius:12px 12px 0 0;
}
.case-title{font-size:1rem;font-weight:700;color:white;}
.case-meta{font-size:.75rem;color:#98A2B3;margin-top:2px;}
.case-wrap{background:white;border:1px solid #E5E7EB;border-radius:12px;
  margin-bottom:20px;box-shadow:0 3px 14px rgba(26,54,93,.1);overflow:hidden;}
.case-body{padding:22px;}
.case-footer{padding:14px 22px;background:#F9FAFB;border-top:1px solid #E5E7EB;
  display:flex;align-items:center;gap:14px;}

.sum-row{display:flex;align-items:center;justify-content:space-between;
  padding:10px 16px;background:white;border:1px solid #E5E7EB;border-radius:10px;margin-bottom:7px;}
.sr-v{font-weight:700;color:#111827;font-size:.88rem;}
.sr-m{font-size:.74rem;color:#667085;margin-top:1px;}
.sr-amt{font-weight:800;color:#111827;font-size:1rem;}
.sr-id{font-size:.7rem;color:#667085;margin-top:2px;text-align:right;}

.decided-row{display:flex;align-items:center;justify-content:space-between;
  padding:9px 16px;background:white;border:1px solid #E5E7EB;border-radius:10px;margin-bottom:7px;}
.dc-v{font-weight:700;color:#111827;font-size:.87rem;}
.dc-m{font-size:.73rem;color:#667085;margin-top:1px;}

.empty-state{text-align:center;padding:60px 20px;color:#98A2B3;}
.empty-icon{margin-bottom:14px;opacity:.5;}
.empty-txt{font-size:.92rem;color:#667085;margin-top:6px;}

.pipe-step{text-align:center;flex:1;padding:18px 12px;}
.pipe-lbl{font-size:.83rem;font-weight:700;color:#111827;margin-top:10px;}
.pipe-sub{font-size:.71rem;color:#667085;margin-top:3px;}

/* ── Login page ── */
.login-bg{
  min-height:100vh;display:flex;align-items:center;justify-content:center;
  background:linear-gradient(135deg,#0B0E13 0%,#111827 45%,#0B0E13 100%);
}
.login-card{
  background:white;border-radius:20px;padding:48px 52px;width:440px;max-width:95vw;
  box-shadow:0 24px 80px rgba(0,0,0,.4);
}
.login-logo{display:flex;align-items:center;gap:14px;margin-bottom:32px;}
.login-title{font-size:1.6rem;font-weight:800;color:#111827;letter-spacing:-.02em;}
.login-sub{font-size:.78rem;color:#667085;margin-top:2px;letter-spacing:.02em;text-transform:uppercase;}
.login-role{display:inline-block;background:#FFFAEB;border:1px solid #FDB022;color:#B54708;
  font-size:.7rem;font-weight:700;padding:2px 8px;border-radius:4px;margin-top:4px;}
.login-divider{height:1px;background:#F2F4F7;margin:24px 0;}
.login-footer{font-size:.73rem;color:#98A2B3;text-align:center;margin-top:24px;}

/* ── User bar (light utility strip) ── */
.user-bar{
  display:flex;align-items:center;justify-content:flex-end;gap:10px;
  height:38px;padding:0;
}
.ub-name{font-size:.78rem;color:#344054;font-weight:600;}
.ub-role{font-size:.68rem;color:#027A48;font-weight:700;background:#ECFDF3;
  border:1px solid #A6F4C5;padding:2px 9px;border-radius:5px;margin-left:2px;}
.userbar-divider{border:none;border-top:1px solid #E5E7EB;margin:2px 0 4px;}
</style>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# SVG & helpers
# ══════════════════════════════════════════════════════════════════════════════
_P = {
    "file":     '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
    "check":    '<polyline points="20 6 9 17 4 12"/>',
    "x":        '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "warn":     '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "upload":   '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
    "shield":   '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "activity": '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    "clock":    '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "bar":      '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
}

def svg(k, size=20, color="#667085"):
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            f'{_P[k]}</svg>')

def pill(s):
    ico = {"APPROVED":"check","PASSED":"check","REJECTED":"x","FAILED":"x","NEEDS_REVIEW":"warn","WARNING":"warn"}.get(s)
    i = (f'<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
         f' stroke-width="3" stroke-linecap="round" stroke-linejoin="round">{_P[ico]}</svg>' if ico else "")
    cls = f"p-{s}" if s in ("APPROVED","REJECTED","NEEDS_REVIEW","PASSED","FAILED","WARNING") else "p-default"
    return f'<span class="pill {cls}">{i} {s}</span>'

def rbadge(r):
    c = {"HIGH":"rb-HIGH","MEDIUM":"rb-MEDIUM","LOW":"rb-LOW"}.get(r,"p-default")
    return f'<span class="rbadge {c}">{r}</span>'

def kv(l, v):
    return f'<div class="kv-l">{l}</div><div class="kv-v">{v}</div>'

def conf(v):
    p = int(v*100)
    c = "#12B76A" if p>=80 else "#F79009" if p>=50 else "#FDA29B"
    return (f'<div class="cb-wrap"><div class="cb-l">Confidence</div>'
            f'<div class="cb-track"><div class="cb-fill" style="width:{p}%;background:{c};"></div></div>'
            f'<div class="cb-pct">{p}%</div></div>')

def flags(fl):
    if not fl:
        return f'<div class="flag-row">{svg("check",12,"#12B76A")}<span style="color:#027A48;font-size:.8rem;">No flags</span></div>'
    rows=""
    for f in fl:
        red = f.split(":")[0] in ("MISSING_FIELD","DUPLICATE_INVOICE_ID","UNAPPROVED_CATEGORY")
        dot = f'<svg width="7" height="7" viewBox="0 0 8 8"><circle cx="4" cy="4" r="4" fill="{"#FDA29B" if red else "#FDB022"}"/></svg>'
        rows += f'<div class="flag-row">{dot}<span class="flag-code">{f}</span></div>'
    return rows

def litems(items):
    if not items: return ""
    rows = "".join(f'<div class="li-row"><span>{li.get("description","-")}</span><span class="li-amt">${li.get("amount",0):.2f}</span></div>' for li in items)
    return f'<div style="margin-top:4px;">{rows}</div>'

def flag_chips(fl, limit=None):
    """Compact warning chips for a flag list — red for critical, amber otherwise."""
    if not fl:
        return ('<span style="background:#ECFDF3;border:1px solid #A6F4C5;color:#027A48;'
                'font-size:.66rem;font-weight:600;padding:2px 9px;border-radius:6px;">✓ No flags</span>')
    shown = fl if limit is None else fl[:limit]
    chips = ""
    for f in shown:
        crit = f.split(":")[0] in ("MISSING_FIELD","DUPLICATE_INVOICE_ID","UNAPPROVED_CATEGORY")
        bg, bc, tc = ("#FEF3F2","#FDA29B","#912018") if crit else ("#FFFAEB","#FDB022","#B54708")
        chips += (f'<span style="background:{bg};border:1px solid {bc};color:{tc};font-size:.66rem;'
                  f'font-weight:600;padding:2px 8px;border-radius:6px;margin:2px 5px 2px 0;'
                  f'display:inline-block;font-family:monospace;">⚠ {f}</span>')
    if limit is not None and len(fl) > limit:
        chips += f'<span style="font-size:.66rem;color:#667085;">+{len(fl)-limit} more</span>'
    return f'<div style="margin-top:6px;">{chips}</div>'

def queue_stepper(status):
    """Horizontal Queued → Processing → Done stepper for an in-flight job."""
    steps = ["Queued", "Processing", "Done"]
    cur = {"QUEUED":0, "PROCESSING":1, "DONE":2, "ERROR":1}.get(status, 0)
    is_err = status == "ERROR"
    html = '<div style="display:flex;align-items:center;gap:5px;margin-top:7px;">'
    for i, lbl in enumerate(steps):
        done   = (status == "DONE") or i < cur
        active = (i == cur) and status != "DONE"
        if is_err and i == 1:
            color, bg, bdr, mark = "#F04438", "#FEF3F2", "#F04438", "✕"
        elif done:
            color, bg, bdr, mark = "#027A48", "#ECFDF3", "#12B76A", "✓"
        elif active:
            color, bg, bdr, mark = "#1570EF", "#EFF8FF", "#1570EF", "●"
        else:
            color, bg, bdr, mark = "#98A2B3", "#F9FAFB", "#E5E7EB", "○"
        html += (f'<span style="font-size:.64rem;font-weight:700;color:{color};background:{bg};'
                 f'border:1px solid {bdr};padding:2px 9px;border-radius:12px;">{mark} {lbl}</span>')
        if i < len(steps) - 1:
            html += '<span style="color:#D0D5DD;font-size:.7rem;">—</span>'
    return html + '</div>'

def inv_table(results):
    if not results:
        return '<div class="empty-state"><div class="empty-txt">No invoices processed yet.</div></div>'
    rows = ""
    for r in results:
        o=r.get("ocr",{}); a=r.get("audit",{}); v=r.get("validation",{})
        eff = r.get("review_decision") or a.get("audit_status","UNKNOWN")
        risk = a.get("risk_level","-")
        rows += (f'<tr><td class="t-id">{o.get("invoice_id","-")}</td>'
                 f'<td class="t-v">{o.get("vendor","-")}</td>'
                 f'<td>{o.get("date","-")}</td>'
                 f'<td class="t-amt">${o.get("amount",0):,.2f}</td>'
                 f'<td>{o.get("category","-")}</td>'
                 f'<td>{pill(eff)}</td>'
                 f'<td>{rbadge(risk)}</td>'
                 f'<td style="font-size:.78rem;color:#667085;">{len(v.get("flags",[]))}f</td>'
                 f'<td style="font-size:.75rem;color:#667085;">{r["filename"][:22]}{"…" if len(r["filename"])>22 else ""}</td></tr>')
    return (f'<div style="overflow-x:auto;margin-bottom:4px;">'
            f'<table class="tbl"><thead><tr>'
            f'<th>Invoice ID</th><th>Vendor</th><th>Date</th><th>Amount</th>'
            f'<th>Category</th><th>Status</th><th>Risk</th><th>Flags</th><th>File</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div>')

def kpi_card(label, val, foot, bar_color, icon_k, pct=None):
    bar = f'<div class="kpi-bar" style="background:{bar_color};' + (f'width:{pct}%' if pct else "width:100%") + ';"></div>' if pct is not None else f'<div class="kpi-bar" style="background:{bar_color};"></div>'
    return (f'<div class="kpi">{svg(icon_k,22,bar_color)}'
            f'<div style="margin-top:10px;"><div class="kpi-lbl">{label}</div>'
            f'<div class="kpi-val">{val}</div>'
            f'<div class="kpi-foot">{foot}</div>{bar}</div></div>')

# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════
_USERS = {
    "admin":    {"password": os.environ.get("ADMIN_PASSWORD",    "admin123"),  "role": "Admin",    "display": "Administrator"},
    "reviewer": {"password": os.environ.get("REVIEWER_PASSWORD", "review123"), "role": "Reviewer", "display": "Reviewer"},
    "viewer":   {"password": os.environ.get("VIEWER_PASSWORD",   "view123"),   "role": "Viewer",   "display": "Viewer"},
}

if "logged_in" not in st.session_state:
    st.session_state.logged_in   = False
    st.session_state.auth_user   = None
    st.session_state.auth_role   = None
    st.session_state.auth_error  = ""

if not st.session_state.logged_in:
    # Override page background and style the form as a card
    st.markdown("""<style>
    html, body, .stApp { background: linear-gradient(135deg,#0B0E13 0%,#111827 50%,#0B0E13 100%) !important; }
    section[data-testid="stMain"] > .block-container { padding-top: 90px !important; }
    div[data-testid="stForm"] {
        background: white !important; border-radius: 18px !important;
        padding: 40px 44px !important; box-shadow: 0 28px 80px rgba(0,0,0,.45) !important;
        border: none !important;
    }
    div[data-testid="stForm"] .stTextInput input {
        background: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 8px; color: #111827;
    }
    </style>""", unsafe_allow_html=True)

    _, mid, _ = st.columns([1.5, 2, 1.5])
    with mid:
        st.markdown(
            f'<div style="text-align:center;margin-bottom:28px;">'
            f'<div style="display:inline-flex;align-items:center;gap:14px;">'
            f'{svg("shield",46,"#16B364")}'
            f'<div style="text-align:left;">'
            f'<div style="font-size:2rem;font-weight:800;color:white;letter-spacing:-.02em;">{APP_NAME}</div>'
            f'<div style="font-size:.72rem;color:#98A2B3;letter-spacing:.12em;text-transform:uppercase;">AI-Powered Invoice Audit Platform</div>'
            f'</div></div></div>',
            unsafe_allow_html=True)
        with st.form("login_form"):
            st.markdown(f'<div style="font-size:1.05rem;font-weight:700;color:#111827;margin-bottom:18px;">Sign in to your account</div>', unsafe_allow_html=True)
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", placeholder="Enter your password", type="password")
            submitted = st.form_submit_button("Sign In →", type="primary", use_container_width=True)
            if submitted:
                u = _USERS.get(username.strip().lower())
                if u and password == u["password"]:
                    st.session_state.logged_in  = True
                    st.session_state.auth_user  = username.strip().lower()
                    st.session_state.auth_role  = u["role"]
                    st.session_state.auth_error = ""
                    st.rerun()
                else:
                    st.session_state.auth_error = "Invalid username or password."
            if st.session_state.auth_error:
                st.error(st.session_state.auth_error)
            st.markdown(
                '<div style="margin-top:20px;padding-top:18px;border-top:1px solid #F2F4F7;'
                'font-size:.73rem;color:#98A2B3;text-align:center;">'
                'Contact your administrator for access credentials.</div>',
                unsafe_allow_html=True)
    st.stop()

_role = st.session_state.auth_role   # "Admin" | "Reviewer" | "Viewer"
_user = st.session_state.auth_user

# ── Session state ─────────────────────────────────────────────────────────────
if "db_loaded" not in st.session_state:
    st.session_state.results = load_all_results()
    st.session_state.processed_invoices = [r["ocr"] for r in st.session_state.results if r["ocr"].get("invoice_id","UNKNOWN")!="UNKNOWN"]
    st.session_state.db_loaded = True

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

rs     = st.session_state.results
rs_done = [r for r in rs if r.get("queue_status","DONE") == "DONE"]   # exclude QUEUED/PROCESSING
approved_n = sum(1 for r in rs_done if r.get("audit",{}).get("audit_status")=="APPROVED" or r.get("review_decision")=="APPROVED")
rejected_n = sum(1 for r in rs_done if r.get("audit",{}).get("audit_status")=="REJECTED" or r.get("review_decision")=="REJECTED")
pending_n  = sum(1 for r in rs_done if r.get("audit",{}).get("audit_status")=="NEEDS_REVIEW" and not r.get("review_decision"))

# ── Top bar ───────────────────────────────────────────────────────────────────
st.markdown(
    f'<div class="topbar"><div class="tb-left">'
    f'{svg("shield",26,"#16B364")}'
    f'<div><div class="tb-title">{APP_NAME}</div>'
    f'<div class="tb-sub">AI-POWERED INVOICE AUDIT PLATFORM</div></div>'
    f'</div><div class="tb-badge">Groq · LangGraph · RAG</div></div>',
    unsafe_allow_html=True)

# ── User bar (right-aligned light utility strip) ──────────────────────────────
_sp, _uinfo, _ubtn, _rp = st.columns([7.4, 1.7, 1.0, 0.12], vertical_alignment="center")
with _uinfo:
    st.markdown(
        f'<div class="user-bar">'
        f'{svg("shield",13,"#16B364")}'
        f'<span class="ub-name">{_user}</span>'
        f'<span class="ub-role">{_role}</span>'
        f'</div>',
        unsafe_allow_html=True)
with _ubtn:
    if st.button("⎋ Sign Out", key="logout_btn", use_container_width=True):
        for k in ["logged_in","auth_user","auth_role","auth_error","db_loaded"]:
            st.session_state.pop(k, None)
        st.rerun()
st.markdown('<hr class="userbar-divider">', unsafe_allow_html=True)

# ── Tabs ─────────────────────────────────────────────────────────────────────
t1, t2, t3, t4, t5 = st.tabs([
    "📊   Dashboard",
    "📤   Upload Invoice",
    "🗂️   Invoices",
    f"⚠️   Review Queue{'  (' + str(pending_n) + ')' if pending_n else ''}",
    "📋   Reports",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Dashboard
# ══════════════════════════════════════════════════════════════════════════════
with t1:
    CHART_LAYOUT = dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif", color="#111827"),
        margin=dict(l=0, r=0, t=28, b=0),
    )

    if not rs_done:
        st.markdown('<div class="empty-state"><div class="empty-icon">'+svg("bar",44,"#98A2B3")+'</div><div style="font-size:1rem;font-weight:600;color:#667085;">No data yet</div><div class="empty-txt">Upload invoices in the Upload tab to populate the dashboard.</div></div>', unsafe_allow_html=True)
    else:
        rs = rs_done
        # ── Pre-compute ──────────────────────────────────────────────────────
        total_amt  = sum(r["ocr"].get("amount",0) for r in rs)
        a_amt      = sum(r["ocr"].get("amount",0) for r in rs if r.get("audit",{}).get("audit_status")=="APPROVED" or r.get("review_decision")=="APPROVED")
        r_amt      = sum(r["ocr"].get("amount",0) for r in rs if r.get("audit",{}).get("audit_status")=="REJECTED" or r.get("review_decision")=="REJECTED")
        avg_amt    = total_amt / len(rs) if rs else 0
        total_flags= sum(len(r["validation"].get("flags",[])) for r in rs)
        avg_conf   = sum(r["audit"].get("confidence",0) for r in rs) / len(rs) if rs else 0
        approval_r = (approved_n / len(rs) * 100) if rs else 0

        # Category spend
        cat_spend: dict = {}
        for r in rs:
            cat = r["ocr"].get("category","Other") or "Other"
            cat_spend[cat] = cat_spend.get(cat, 0) + r["ocr"].get("amount", 0)

        # Vendor spend
        vendor_spend: dict = {}
        for r in rs:
            v = r["ocr"].get("vendor","Unknown") or "Unknown"
            vendor_spend[v] = vendor_spend.get(v, 0) + r["ocr"].get("amount", 0)
        top_vendors = sorted(vendor_spend.items(), key=lambda x: x[1], reverse=True)[:8]

        # Risk distribution
        risk_counts = {"HIGH":0,"MEDIUM":0,"LOW":0}
        for r in rs:
            rk = r["audit"].get("risk_level","LOW")
            risk_counts[rk] = risk_counts.get(rk,0) + 1

        # Flag type counts
        flag_types: dict = {}
        for r in rs:
            for f in r["validation"].get("flags",[]):
                k = f.split(":")[0]
                flag_types[k] = flag_types.get(k,0) + 1

        # ── Row 1: Primary KPIs ──────────────────────────────────────────────
        c1,c2,c3,c4 = st.columns(4)
        with c1: st.markdown(kpi_card("Total Invoices", len(rs), f"${total_amt:,.2f} total value", "#16B364", "file"), unsafe_allow_html=True)
        with c2: st.markdown(kpi_card("Approved", approved_n, f"${a_amt:,.2f} cleared", "#12B76A", "check"), unsafe_allow_html=True)
        with c3: st.markdown(kpi_card("Rejected", rejected_n, f"${r_amt:,.2f} blocked", "#FDA29B", "x"), unsafe_allow_html=True)
        with c4: st.markdown(kpi_card("Pending Review", pending_n, "Awaiting human decision", "#F79009", "clock"), unsafe_allow_html=True)

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        # ── Row 2: Secondary KPIs ────────────────────────────────────────────
        s1,s2,s3,s4 = st.columns(4)
        def mini_kpi(label, value, sub=""):
            return (f'<div style="background:white;border-radius:12px;padding:16px 20px;'
                    f'border:1px solid #E5E7EB;box-shadow:0 1px 6px rgba(26,54,93,.06);">'
                    f'<div style="font-size:.65rem;font-weight:700;color:#667085;text-transform:uppercase;'
                    f'letter-spacing:.09em;margin-bottom:6px;">{label}</div>'
                    f'<div style="font-size:1.6rem;font-weight:800;color:#111827;">{value}</div>'
                    f'{"<div style=font-size:.74rem;color:#667085;margin-top:3px;>" + sub + "</div>" if sub else ""}'
                    f'</div>')
        with s1: st.markdown(mini_kpi("Avg Invoice", f"${avg_amt:,.2f}", "per invoice"), unsafe_allow_html=True)
        with s2: st.markdown(mini_kpi("Approval Rate", f"{approval_r:.0f}%", f"{approved_n} of {len(rs)} invoices"), unsafe_allow_html=True)
        with s3: st.markdown(mini_kpi("Total Flags", total_flags, f"across {len(rs)} invoices"), unsafe_allow_html=True)
        with s4: st.markdown(mini_kpi("Avg AI Confidence", f"{avg_conf:.0%}", "audit agent score"), unsafe_allow_html=True)

        st.markdown("<div style='height:22px'></div>", unsafe_allow_html=True)

        # ── Recent Flags (attention items) ───────────────────────────────────
        recent_flagged = [
            r for r in rs
            if r["validation"].get("flags")
            or (r.get("audit",{}).get("audit_status") in ("NEEDS_REVIEW","REJECTED") and not r.get("review_decision"))
        ][:6]
        if recent_flagged:
            st.markdown('<div style="font-size:.7rem;font-weight:700;color:#667085;text-transform:uppercase;letter-spacing:.09em;margin-bottom:10px;">⚠ Recent Flags — needs attention</div>', unsafe_allow_html=True)
            _rf_rows = ""
            for r in recent_flagged:
                o=r.get("ocr",{}); a=r.get("audit",{}); v=r.get("validation",{})
                eff = r.get("review_decision") or a.get("audit_status","UNKNOWN")
                _rf_rows += (
                    f'<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;'
                    f'padding:9px 14px;background:white;border:1px solid #E5E7EB;border-radius:9px;margin-bottom:6px;">'
                    f'<div style="min-width:0;"><span style="font-weight:700;color:#111827;font-size:.85rem;">{o.get("vendor","?")}</span>'
                    f'<span style="font-family:monospace;color:#1570EF;font-size:.74rem;margin-left:8px;">{o.get("invoice_id","-")}</span>'
                    f'<span style="color:#667085;font-size:.74rem;margin-left:8px;">${o.get("amount",0):,.2f}</span>'
                    f'<div>{flag_chips(v.get("flags",[]), limit=3)}</div></div>'
                    f'<div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">{pill(eff)}{rbadge(a.get("risk_level","-"))}</div>'
                    f'</div>')
            st.markdown(_rf_rows, unsafe_allow_html=True)
            st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

        # ── Row 3: Charts ────────────────────────────────────────────────────
        ch1, ch2, ch3 = st.columns([2, 2, 1.4])

        with ch1:
            st.markdown('<div style="font-size:.7rem;font-weight:700;color:#667085;text-transform:uppercase;letter-spacing:.09em;margin-bottom:10px;">Spend by Category</div>', unsafe_allow_html=True)
            cats = sorted(cat_spend.items(), key=lambda x: x[1], reverse=True)
            if cats:
                fig = go.Figure(go.Bar(
                    x=[v for _,v in cats], y=[c for c,_ in cats],
                    orientation="h",
                    marker=dict(
                        color=[f"rgba(22,179,100,{0.78 + 0.22*(i/max(len(cats)-1,1))})" for i in range(len(cats)-1,-1,-1)],
                        line=dict(width=0)
                    ),
                    text=[f"${v:,.0f}" for _,v in cats],
                    textposition="outside", textfont=dict(size=12, color="#111827"),
                    hovertemplate="<b>%{y}</b><br>$%{x:,.2f}<extra></extra>",
                ))
                fig.update_layout(**CHART_LAYOUT, height=max(240, 46*len(cats)), bargap=0.22,
                    xaxis=dict(showgrid=True, gridcolor="#F2F4F7", zeroline=False, tickformat="$,.0f", tickfont=dict(size=10)),
                    yaxis=dict(showgrid=False, tickfont=dict(size=11)))
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})

        with ch2:
            st.markdown('<div style="font-size:.7rem;font-weight:700;color:#667085;text-transform:uppercase;letter-spacing:.09em;margin-bottom:10px;">Top Vendors by Spend</div>', unsafe_allow_html=True)
            if top_vendors:
                vnames = [n for n,_ in top_vendors]
                vvals  = [v for _,v in top_vendors]
                fig2 = go.Figure(go.Bar(
                    x=vvals, y=vnames, orientation="h",
                    marker=dict(color="#16B364", opacity=1.0, line=dict(width=0)),
                    text=[f"${v:,.0f}" for v in vvals],
                    textposition="outside", textfont=dict(size=12, color="#111827"),
                    hovertemplate="<b>%{y}</b><br>$%{x:,.2f}<extra></extra>",
                ))
                fig2.update_layout(**CHART_LAYOUT, height=max(240, 46*len(vnames)), bargap=0.22,
                    xaxis=dict(showgrid=True, gridcolor="#F2F4F7", zeroline=False, tickformat="$,.0f", tickfont=dict(size=10)),
                    yaxis=dict(showgrid=False, tickfont=dict(size=11), categoryorder="total ascending"))
                st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar":False})

        with ch3:
            st.markdown('<div style="font-size:.7rem;font-weight:700;color:#667085;text-transform:uppercase;letter-spacing:.09em;margin-bottom:10px;">Status & Risk</div>', unsafe_allow_html=True)
            # Status donut
            status_labels = ["Approved","Rejected","Needs Review"]
            status_vals   = [approved_n, rejected_n, pending_n]
            status_colors = ["#12B76A","#FDA29B","#FDB022"]
            fig3 = go.Figure(go.Pie(
                labels=status_labels, values=status_vals,
                hole=0.62,
                marker=dict(colors=status_colors, line=dict(color="white", width=2)),
                textinfo="none",
                hovertemplate="<b>%{label}</b><br>%{value} invoices<extra></extra>",
            ))
            fig3.update_layout(**CHART_LAYOUT, height=130,
                showlegend=True,
                legend=dict(orientation="v", x=1, y=0.5, font=dict(size=10)),
                annotations=[dict(text=f"<b>{len(rs)}</b>", x=0.18, y=0.5, font=dict(size=16, color="#111827"), showarrow=False)])
            st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar":False})

            # Risk bar
            fig4 = go.Figure(go.Bar(
                x=["HIGH","MEDIUM","LOW"],
                y=[risk_counts["HIGH"], risk_counts["MEDIUM"], risk_counts["LOW"]],
                marker=dict(color=["#FDA29B","#FDB022","#12B76A"], line=dict(width=0)),
                hovertemplate="<b>%{x}</b><br>%{y} invoices<extra></extra>",
            ))
            fig4.update_layout(**CHART_LAYOUT, height=110,
                xaxis=dict(showgrid=False, tickfont=dict(size=10)),
                yaxis=dict(showgrid=True, gridcolor="#F2F4F7", tickfont=dict(size=10), dtick=1))
            st.plotly_chart(fig4, use_container_width=True, config={"displayModeBar":False})

        # ── Row 4: Flag breakdown + confidence scatter ───────────────────────
        if flag_types or len(rs) > 1:
            f1, f2 = st.columns(2)

            with f1:
                st.markdown('<div style="font-size:.7rem;font-weight:700;color:#667085;text-transform:uppercase;letter-spacing:.09em;margin-bottom:10px;">Flag Type Breakdown</div>', unsafe_allow_html=True)
                if flag_types:
                    ft_sorted = sorted(flag_types.items(), key=lambda x: x[1], reverse=True)
                    fig5 = go.Figure(go.Bar(
                        x=[k for k,_ in ft_sorted], y=[v for _,v in ft_sorted],
                        marker=dict(color="#FDA29B", opacity=0.8, line=dict(width=0)),
                        hovertemplate="<b>%{x}</b><br>%{y} occurrences<extra></extra>",
                    ))
                    fig5.update_layout(**CHART_LAYOUT, height=180,
                        xaxis=dict(showgrid=False, tickfont=dict(size=10), tickangle=-20),
                        yaxis=dict(showgrid=True, gridcolor="#F2F4F7", tickfont=dict(size=10), dtick=1))
                    st.plotly_chart(fig5, use_container_width=True, config={"displayModeBar":False})
                else:
                    st.markdown('<div style="padding:40px;text-align:center;color:#12B76A;font-size:.85rem;">✓ No flags raised</div>', unsafe_allow_html=True)

            with f2:
                st.markdown('<div style="font-size:.7rem;font-weight:700;color:#667085;text-transform:uppercase;letter-spacing:.09em;margin-bottom:10px;">Amount vs AI Confidence</div>', unsafe_allow_html=True)
                if len(rs) >= 2:
                    amts   = [r["ocr"].get("amount",0) for r in rs]
                    confs  = [r["audit"].get("confidence",0)*100 for r in rs]
                    vstats = [r.get("audit",{}).get("audit_status","UNKNOWN") for r in rs]
                    clr    = ["#12B76A" if s=="APPROVED" else "#FDA29B" if s=="REJECTED" else "#FDB022" for s in vstats]
                    fig6 = go.Figure(go.Scatter(
                        x=amts, y=confs, mode="markers",
                        marker=dict(size=12, color=clr, line=dict(color="white",width=1.5), opacity=0.85),
                        text=[r["ocr"].get("vendor","?") for r in rs],
                        hovertemplate="<b>%{text}</b><br>Amount: $%{x:,.2f}<br>Confidence: %{y:.0f}%<extra></extra>",
                    ))
                    fig6.update_layout(**CHART_LAYOUT, height=180,
                        xaxis=dict(showgrid=True, gridcolor="#F2F4F7", zeroline=False, tickformat="$,.0f", tickfont=dict(size=10), title=dict(text="Invoice Amount", font=dict(size=10))),
                        yaxis=dict(showgrid=True, gridcolor="#F2F4F7", tickfont=dict(size=10), title=dict(text="Confidence %", font=dict(size=10)), range=[0,105]))
                    st.plotly_chart(fig6, use_container_width=True, config={"displayModeBar":False})
                else:
                    st.markdown('<div style="padding:40px;text-align:center;color:#667085;font-size:.85rem;">Process 2+ invoices to see scatter</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Upload
# ══════════════════════════════════════════════════════════════════════════════
with t2:
    if _role != "Admin":
        st.markdown(
            '<div style="text-align:center;padding:80px 20px;">'
            '<div style="font-size:2.8rem;margin-bottom:16px;">🔒</div>'
            '<div style="font-size:1.05rem;font-weight:700;color:#111827;margin-bottom:8px;">Admin access only</div>'
            '<div style="font-size:.88rem;color:#667085;">Only Admins can upload and process invoices.<br>'
            'Log in as <strong>admin</strong> to use this feature.</div>'
            '</div>', unsafe_allow_html=True)
    else:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # ── Post-upload feedback (survives the rerun) ─────────────────────────
        _toast_msg = st.session_state.pop("upload_toast", None)
        if _toast_msg:
            st.toast(_toast_msg, icon="✅")
        _banner = st.session_state.get("upload_banner")
        if _banner:
            _names = ", ".join(_banner)
            st.markdown(
                f'<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;'
                f'padding:12px 18px;background:#ECFDF3;border:1px solid #A6F4C5;border-left:4px solid #12B76A;'
                f'border-radius:0 10px 10px 0;margin-bottom:18px;">'
                f'<div style="font-size:.9rem;color:#027A48;">'
                f'<strong>✅ {len(_banner)} invoice{"s" if len(_banner)!=1 else ""} queued for processing.</strong>'
                f'<span style="color:#475467;"> &nbsp;{_names}. Track progress below, then view results in the '
                f'<strong>Invoices</strong> tab.</span></div></div>',
                unsafe_allow_html=True)
            if st.button("Dismiss", key="dismiss_banner", type="secondary"):
                st.session_state.pop("upload_banner", None)
                st.rerun()
        if st.session_state.get("upload_failed"):
            st.error("Failed to queue: " + "; ".join(st.session_state.pop("upload_failed")))

        st.markdown("""
        <div style="display:flex;align-items:center;background:white;border:1px solid #E5E7EB;
          border-radius:14px;padding:22px 28px;margin-bottom:26px;box-shadow:0 2px 10px rgba(26,54,93,.07);">
          <div class="pipe-step">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#1570EF" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <div class="pipe-lbl">OCR</div><div class="pipe-sub">Extract invoice fields</div>
          </div>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#D0D5DD" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
          <div class="pipe-step">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#16B364" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
            <div class="pipe-lbl">Validate</div><div class="pipe-sub">Policy rule checks</div>
          </div>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#D0D5DD" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
          <div class="pipe-step">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#0E9F6E" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            <div class="pipe-lbl">Audit</div><div class="pipe-sub">AI decision + RAG</div>
          </div>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#D0D5DD" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
          <div class="pipe-step">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#16B364" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
            <div class="pipe-lbl">Decision</div><div class="pipe-sub">Approve / Review / Reject</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        s3_ok = s3_available()
        s3_bucket = os.environ.get("S3_BUCKET_NAME", "anomaguard-invoices")
        if s3_ok:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;padding:10px 16px;'
                f'background:#ECFDF3;border:1px solid #A6F4C5;border-radius:8px;margin-bottom:16px;font-size:.83rem;color:#027A48;">'
                f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
                f'<span><strong>S3 connected</strong> — uploads stored in <code>{s3_bucket}</code></span></div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                '<div style="display:flex;align-items:center;gap:10px;padding:10px 16px;'
                'background:#FFFAEB;border:1px solid #FDB022;border-radius:8px;margin-bottom:16px;font-size:.83rem;color:#B54708;">'
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
                '<span><strong>S3 unavailable</strong> — run <code>docker compose up -d</code> to enable storage.</span></div>',
                unsafe_allow_html=True)

        uploaded = st.file_uploader("Upload PDF invoices only", type=["pdf"], accept_multiple_files=True, key=f"pdf_up_{st.session_state.uploader_key}")

        # Validate each file is actually a PDF (check magic bytes)
        invalid = []
        valid = []
        if uploaded:
            for f in uploaded:
                header = f.read(4)
                f.seek(0)
                if header != b"%PDF":
                    invalid.append(f.name)
                else:
                    valid.append(f)
            if invalid:
                st.error(f"Not a valid PDF: {', '.join(invalid)}. Only real PDF files are accepted.")

        if valid:
            if st.button(f"Queue {len(valid)} Invoice{'s' if len(valid)!=1 else ''} for Processing", type="primary"):
                status_ph = st.empty()        # readable status line, above the bar
                bar = st.progress(0)
                queued, failed = [], []
                for i, f in enumerate(valid):
                    status_ph.markdown(
                        f'<div style="font-size:.95rem;font-weight:600;color:#111827;margin:6px 0;">'
                        f'⏳ Uploading <strong>{f.name}</strong> … ({i+1} of {len(valid)})</div>',
                        unsafe_allow_html=True)
                    bar.progress(i / len(valid))
                    try:
                        file_bytes = f.read()
                        s3_key, s3_url = upload_invoice(file_bytes, f.name)
                        job_id = str(uuid.uuid4())
                        save_queued_job(job_id, f.name, s3_key, s3_url)
                        send_job(job_id, f.name, s3_key, s3_url)
                        queued.append(f.name)
                    except Exception as e:
                        failed.append(f"{f.name}: {e}")
                bar.progress(1.0)
                status_ph.markdown(
                    '<div style="font-size:.95rem;font-weight:600;color:#027A48;margin:6px 0;">'
                    '✅ Done — queued for processing.</div>', unsafe_allow_html=True)
                # Feedback that survives the rerun (toast + persistent banner)
                if queued:
                    st.session_state.upload_toast  = f"{len(queued)} invoice{'s' if len(queued)!=1 else ''} queued successfully"
                    st.session_state.upload_banner = queued
                if failed:
                    st.session_state.upload_failed = failed
                st.session_state.results = load_all_results()
                st.session_state.uploader_key += 1
                st.rerun()
        # ── Queue status panel ────────────────────────────────────────────────
        queue_jobs = [r for r in st.session_state.results if r.get("queue_status") in ("QUEUED","PROCESSING","ERROR")]
        if queue_jobs:
            st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
            _qdepth = queue_depth()
            st.markdown(
                f'<div style="background:white;border:1px solid #E5E7EB;border-radius:12px;'
                f'padding:18px 22px;box-shadow:0 2px 8px rgba(26,54,93,.06);">'
                f'<div style="font-size:.7rem;font-weight:700;color:#667085;text-transform:uppercase;'
                f'letter-spacing:.09em;margin-bottom:14px;">Queue Status'
                f'<span style="font-weight:400;color:#667085;margin-left:10px;text-transform:none;">'
                f'{_qdepth} message{"s" if _qdepth!=1 else ""} in SQS</span></div>',
                unsafe_allow_html=True)
            _status_colors = {
                "QUEUED":     ("#FFFAEB","#F79009","⏳"),
                "PROCESSING": ("#EFF8FF","#1570EF","⚙️"),
                "ERROR":      ("#FEF3F2","#F04438","❌"),
            }
            for job in queue_jobs:
                bg, cl, ico = _status_colors.get(job["queue_status"], ("#F9FAFB","#475467","·"))
                err_txt = f'<div style="font-size:.74rem;color:#F04438;margin-top:2px;">{job["queue_error"]}</div>' if job.get("queue_error") else ""
                st.markdown(
                    f'<div style="display:flex;align-items:flex-start;justify-content:space-between;'
                    f'padding:8px 12px;background:{bg};border-radius:8px;margin-bottom:6px;">'
                    f'<div><div style="font-size:.85rem;font-weight:600;color:#111827;">{ico} {job["filename"]}</div>'
                    f'{queue_stepper(job["queue_status"])}{err_txt}</div>'
                    f'<span style="font-size:.7rem;font-weight:700;color:{cl};'
                    f'background:white;border:1px solid {cl};padding:2px 8px;border-radius:4px;">'
                    f'{job["queue_status"]}</span></div>',
                    unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
            if st.button("↻ Refresh status", key="refresh_queue"):
                st.session_state.results = load_all_results()
                st.rerun()

        if not uploaded and not st.session_state.results:
            st.markdown('<div class="empty-state"><div class="empty-icon">'+svg("upload",40,"#98A2B3")+'</div><div style="font-size:.92rem;color:#667085;">Upload one or more PDF invoices above to begin.</div></div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Invoices (filtered view)
# ══════════════════════════════════════════════════════════════════════════════
with t3:
    if not rs_done:
        st.markdown('<div class="empty-state"><div class="empty-icon">'+svg("file",44,"#98A2B3")+'</div><div style="font-size:1rem;font-weight:600;color:#667085;">No invoices yet</div><div class="empty-txt">Upload invoices to see them here.</div></div>', unsafe_allow_html=True)
    else:
        rs = rs_done
        all_categories = sorted(set(r["ocr"].get("category","Other") or "Other" for r in rs))
        all_vendors    = sorted(set(r["ocr"].get("vendor","Unknown") or "Unknown" for r in rs))
        all_amounts    = [r["ocr"].get("amount", 0) for r in rs]
        amt_min, amt_max = int(min(all_amounts)), int(max(all_amounts)) + 1

        # ── Filter bar ───────────────────────────────────────────────────────
        st.markdown('<div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:18px 22px;margin-bottom:20px;box-shadow:0 2px 8px rgba(26,54,93,.06);">', unsafe_allow_html=True)
        fa, fb, fc = st.columns(3)
        with fa:
            f_status = st.multiselect("Status", ["APPROVED","REJECTED","NEEDS_REVIEW"], placeholder="All statuses")
        with fb:
            f_risk = st.multiselect("Risk Level", ["HIGH","MEDIUM","LOW"], placeholder="All risk levels")
        with fc:
            f_cat = st.multiselect("Category", all_categories, placeholder="All categories")

        fd, fe, ff = st.columns([2,1,1])
        with fd:
            f_vendor = st.text_input("Search vendor or invoice ID", placeholder="Type a vendor name or invoice ID…")
        with fe:
            f_amt_min = st.number_input("Min amount ($)", min_value=0, value=0, step=50)
        with ff:
            f_amt_max = st.number_input("Max amount ($)", min_value=0, value=amt_max, step=50)

        fg, fh = st.columns([2,1])
        with fg:
            f_sort = st.selectbox("Sort by", ["Date","Amount","Vendor","Invoice ID","Risk"], key="inv_sort")
        with fh:
            f_dir = st.radio("Order", ["▼ Desc","▲ Asc"], horizontal=True, key="inv_dir", label_visibility="visible")
        st.markdown('</div>', unsafe_allow_html=True)

        # ── Apply filters ─────────────────────────────────────────────────────
        filtered = rs
        if f_status:
            filtered = [r for r in filtered if (r.get("review_decision") or r.get("audit",{}).get("audit_status","")) in f_status]
        if f_risk:
            filtered = [r for r in filtered if r.get("audit",{}).get("risk_level","") in f_risk]
        if f_cat:
            filtered = [r for r in filtered if (r["ocr"].get("category","") or "") in f_cat]
        if f_vendor:
            _q = f_vendor.lower()
            filtered = [r for r in filtered
                        if _q in (r["ocr"].get("vendor","") or "").lower()
                        or _q in str(r["ocr"].get("invoice_id","") or "").lower()]
        if f_amt_min or f_amt_max != amt_max:
            filtered = [r for r in filtered if f_amt_min <= r["ocr"].get("amount",0) <= f_amt_max]

        # ── Sort ──────────────────────────────────────────────────────────────
        _risk_rank = {"HIGH":3,"MEDIUM":2,"LOW":1}
        _sort_keys = {
            "Date":       lambda r: str(r["ocr"].get("date","")),
            "Amount":     lambda r: r["ocr"].get("amount",0) or 0,
            "Vendor":     lambda r: (r["ocr"].get("vendor","") or "").lower(),
            "Invoice ID": lambda r: str(r["ocr"].get("invoice_id","") or "").lower(),
            "Risk":       lambda r: _risk_rank.get(r.get("audit",{}).get("risk_level",""),0),
        }
        filtered = sorted(filtered, key=_sort_keys[f_sort], reverse=f_dir.startswith("▼"))

        # ── Results header ────────────────────────────────────────────────────
        hc, dc1, dc2 = st.columns([5,1,1])
        with hc:
            st.markdown(f'<div style="font-size:.7rem;font-weight:700;color:#667085;text-transform:uppercase;letter-spacing:.09em;margin-bottom:10px;">Showing {len(filtered)} of {len(rs)} invoices</div>', unsafe_allow_html=True)
        if filtered:
            rows_data = [{"File":r["filename"],"Invoice ID":r["ocr"].get("invoice_id","-"),"Vendor":r["ocr"].get("vendor","-"),"Amount":r["ocr"].get("amount",0),"Category":r["ocr"].get("category","-"),"Validation":r["validation"].get("validation_status","-"),"Audit":r["audit"].get("audit_status","-"),"Risk":r["audit"].get("risk_level","-"),"Flags":len(r["validation"].get("flags",[])),"Reviewer":r.get("review_decision") or ""} for r in filtered]
            with dc1:
                st.download_button("↓ CSV", pd.DataFrame(rows_data).to_csv(index=False).encode(), "invoices.csv", "text/csv", use_container_width=True, key="dl_invoices")
            with dc2:
                _buf = io.BytesIO()
                pd.DataFrame(rows_data).to_excel(_buf, index=False, engine="openpyxl")
                st.download_button("↓ XLSX", _buf.getvalue(), "invoices.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key="dl_invoices_xl")

        # ── Standardized detail modal (Details / Correct Fields / Audit Trail) ─
        @st.dialog("Invoice detail", width="large")
        def show_invoice_modal(result):
            o=result.get("ocr",{}); v=result.get("validation",{}); a=result.get("audit",{})
            corr=result.get("corrections",{}); rev=result.get("review_decision")
            eo={**o,**corr}; eff=rev or a.get("audit_status","ERROR")
            db_id=result["db_id"]; s3u=result.get("s3_url"); s3k=result.get("s3_key")
            st.markdown(
                f'<div style="font-size:1.05rem;font-weight:800;color:#111827;">{eo.get("vendor","Unknown")} '
                f'· <span style="font-family:monospace;color:#1570EF;">{eo.get("invoice_id","-")}</span>'
                f'<span style="color:#667085;font-weight:600;font-size:.9rem;">&nbsp;&nbsp;${eo.get("amount",0):,.2f}</span></div>'
                f'<div style="margin:6px 0 10px;">{pill(eff)}&nbsp;{rbadge(a.get("risk_level","-"))}</div>',
                unsafe_allow_html=True)

            mtab1, mtab2, mtab3 = st.tabs(["📋  Details", "✏️  Correct Fields", "🕐  Audit Trail"])

            with mtab1:
                md1, md2 = st.columns([1,1])
                with md1:
                    if s3u and s3k:
                        try:
                            _u=get_presigned_url(s3k, expires_in=1800)
                            st.markdown(f'<iframe src="{_u}" width="100%" height="460" style="border:1px solid #E5E7EB;border-radius:8px;"></iframe>', unsafe_allow_html=True)
                        except Exception:
                            st.markdown(f'<div style="font-size:.8rem;color:#667085;">PDF stored at <code>{s3k}</code></div>', unsafe_allow_html=True)
                    badge = '<span style="font-size:.68rem;background:#FFFAEB;color:#B54708;border:1px solid #FDB022;border-radius:4px;padding:1px 6px;margin-left:6px;">edited</span>' if corr else ""
                    st.markdown(f'<div class="sec-t" style="margin-top:10px;">Extracted Data{badge}</div>'
                        +kv("Date",eo.get("date","-"))+kv("Amount",f"${eo.get('amount',0):,.2f} {eo.get('currency','USD')}")
                        +kv("Category",eo.get("category","-"))+conf(o.get("confidence",0)), unsafe_allow_html=True)
                    if o.get("line_items"):
                        st.markdown('<div class="sec-t" style="margin-top:8px;">Line Items</div>'+litems(o["line_items"]), unsafe_allow_html=True)
                with md2:
                    st.markdown(f'<div class="sec-t">Validation</div><div style="margin-bottom:8px;">{pill(v.get("validation_status","UNKNOWN"))}</div>'
                        +flags(v.get("flags",[])), unsafe_allow_html=True)
                    st.markdown(f'<div class="sec-t" style="margin-top:10px;">Audit Reasoning</div>'
                        f'<div class="box-blue">{a.get("reasoning","-")}</div>'
                        f'<div class="kv-l">Recommendation</div><div class="box-gold">{a.get("recommendation","-")}</div>', unsafe_allow_html=True)
                    refs=a.get("policy_references",[])
                    if refs:
                        st.markdown('<div class="kv-l">Policy References</div>'+"".join(f'<div class="policy-ref">· {r}</div>' for r in refs), unsafe_allow_html=True)
                    if rev:
                        bg="#ECFDF3" if rev=="APPROVED" else "#FEF3F2"; bc="#A6F4C5" if rev=="APPROVED" else "#FDA29B"
                        st.markdown(f'<div style="margin-top:10px;padding:10px 14px;background:{bg};border:1px solid {bc};border-radius:8px;font-size:.82rem;color:#344054;"><strong>Reviewer:</strong> {pill(rev)}&nbsp;<em>{result.get("review_notes") or "No notes"}</em></div>', unsafe_allow_html=True)

            with mtab2:
                if _role not in ("Admin","Reviewer"):
                    st.markdown('<div style="padding:20px 0;font-size:.83rem;color:#98A2B3;font-style:italic;">View only — Reviewer or Admin role required to edit fields.</div>', unsafe_allow_html=True)
                else:
                    _cats = ["Travel","Accommodation","Meals","Office Supplies","Software","Professional Services","Other"]
                    with st.form(key=f"corr_{db_id}"):
                        cc1,cc2 = st.columns(2)
                        with cc1:
                            n_vendor  = st.text_input("Vendor",           value=eo.get("vendor",""))
                            n_inv_id  = st.text_input("Invoice ID",        value=eo.get("invoice_id",""))
                            n_date    = st.text_input("Date (YYYY-MM-DD)", value=eo.get("date",""))
                        with cc2:
                            n_amount  = st.number_input("Amount", value=float(eo.get("amount",0)), min_value=0.0, step=0.01)
                            cur_cat   = eo.get("category","Other")
                            n_category= st.selectbox("Category", _cats, index=_cats.index(cur_cat) if cur_cat in _cats else 6)
                        if st.form_submit_button("Save corrections", type="primary"):
                            save_corrections(db_id, {"vendor":n_vendor,"invoice_id":n_inv_id,"date":n_date,"amount":n_amount,"category":n_category}, o)
                            st.session_state.results = load_all_results()
                            st.rerun()

            with mtab3:
                trail = get_audit_trail(db_id)
                if not trail:
                    st.markdown('<div style="font-size:.8rem;color:#667085;padding:12px 0;">No events yet.</div>', unsafe_allow_html=True)
                else:
                    action_styles = {
                        "UPLOADED":  ("#EFF8FF","#1570EF"),
                        "APPROVED":  ("#ECFDF3","#12B76A"),
                        "REJECTED":  ("#FEF3F2","#F04438"),
                        "CORRECTED": ("#FFFAEB","#F79009"),
                    }
                    for entry in trail:
                        bg2,cl2 = action_styles.get(entry["action"],("#F9FAFB","#475467"))
                        ts  = entry["timestamp"][:16].replace("T"," ") + " UTC"
                        det = entry.get("details",{})
                        if entry["action"] == "CORRECTED":
                            detail_txt = " · ".join(f'{k}: "{vv["from"]}" → "{vv["to"]}"' for k,vv in det.get("changes",{}).items())
                        elif entry["action"] == "UPLOADED":
                            detail_txt = det.get("filename","")
                        else:
                            detail_txt = det.get("notes","") or ""
                        st.markdown(
                            f'<div style="display:flex;align-items:flex-start;gap:10px;padding:8px 0;border-bottom:1px solid #F2F4F7;">'
                            f'<span style="background:{bg2};color:{cl2};font-size:.68rem;font-weight:700;padding:2px 8px;border-radius:5px;white-space:nowrap;">{entry["action"]}</span>'
                            f'<div><div style="font-size:.75rem;color:#667085;">{ts}</div>'
                            f'{"<div style=font-size:.78rem;color:#344054;margin-top:2px;>" + detail_txt + "</div>" if detail_txt else ""}'
                            f'</div></div>',
                            unsafe_allow_html=True)

        # ── Master table — click 👁 on a row to open the detail modal ──────────
        if not filtered:
            st.markdown('<div style="padding:40px;text-align:center;color:#667085;font-size:.88rem;">No invoices match the selected filters.</div>', unsafe_allow_html=True)
        else:
            _cw = [1.3, 1.8, 1.0, 1.0, 1.3, 1.2, 0.8, 0.7]
            _hcols = st.columns(_cw)
            for _c, _lbl in zip(_hcols, ["Invoice ID","Vendor","Date","Amount","Category","Status","Risk","View"]):
                _c.markdown(f'<div style="font-size:.64rem;font-weight:700;color:#667085;text-transform:uppercase;letter-spacing:.08em;border-bottom:2px solid #E5E7EB;padding-bottom:6px;">{_lbl}</div>', unsafe_allow_html=True)
            for r in filtered:
                o=r.get("ocr",{}); a=r.get("audit",{}); eff=r.get("review_decision") or a.get("audit_status","UNKNOWN")
                row = st.columns(_cw, vertical_alignment="center")
                row[0].markdown(f'<div style="font-family:monospace;color:#1570EF;font-size:.8rem;font-weight:600;">{o.get("invoice_id","-")}</div>', unsafe_allow_html=True)
                row[1].markdown(f'<div style="font-weight:700;color:#111827;font-size:.85rem;">{o.get("vendor","-")}</div>', unsafe_allow_html=True)
                row[2].markdown(f'<div style="color:#344054;font-size:.83rem;">{o.get("date","-")}</div>', unsafe_allow_html=True)
                row[3].markdown(f'<div style="font-weight:800;color:#111827;font-size:.85rem;">${o.get("amount",0):,.2f}</div>', unsafe_allow_html=True)
                row[4].markdown(f'<div style="color:#344054;font-size:.83rem;">{o.get("category","-")}</div>', unsafe_allow_html=True)
                row[5].markdown(pill(eff), unsafe_allow_html=True)
                row[6].markdown(rbadge(a.get("risk_level","-")), unsafe_allow_html=True)
                if row[7].button("👁", key=f"view_{r['db_id']}", help="View full detail"):
                    show_invoice_modal(r)
                st.markdown('<div style="border-bottom:1px solid #F2F4F7;margin:2px 0;"></div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Review Queue
# ══════════════════════════════════════════════════════════════════════════════
with t4:
    needs = [r for r in rs_done if r.get("audit",{}).get("audit_status")=="NEEDS_REVIEW"]
    pending = [r for r in needs if not r.get("review_decision")]
    decided = [r for r in needs if r.get("review_decision")]

    if not needs:
        st.markdown('<div class="empty-state"><div class="empty-icon">'+svg("check",44,"#12B76A")+'</div><div style="font-size:1rem;font-weight:600;color:#027A48;">All clear</div><div class="empty-txt">No invoices need review right now. Flagged items (NEEDS_REVIEW) will appear here automatically as invoices are processed — head to the <strong>Upload Invoice</strong> tab to add more.</div></div>', unsafe_allow_html=True)
    else:
        if pending:
            rq_hd, rq_ba, rq_br = st.columns([5,1,1])
            with rq_hd:
                st.markdown(f'<div style="font-size:.78rem;font-weight:700;color:#F79009;text-transform:uppercase;letter-spacing:.09em;margin-bottom:4px;">{svg("warn",14,"#F79009")} {len(pending)} invoice{"s" if len(pending)!=1 else ""} awaiting decision</div>', unsafe_allow_html=True)
            if _role in ("Admin","Reviewer"):
                with rq_ba:
                    if st.button("✓ Approve All", key="bulk_approve", use_container_width=True, type="primary"):
                        conflicts = [_r["db_id"] for _r in pending if not save_review(_r["db_id"],"APPROVED","Bulk approved",_r.get("version",1))]
                        if conflicts:
                            st.warning(f"{len(conflicts)} record(s) were modified by another user and skipped.")
                        st.session_state.results=load_all_results(); st.rerun()
                with rq_br:
                    if st.button("✕ Reject All", key="bulk_reject", use_container_width=True):
                        conflicts = [_r["db_id"] for _r in pending if not save_review(_r["db_id"],"REJECTED","Bulk rejected",_r.get("version",1))]
                        if conflicts:
                            st.warning(f"{len(conflicts)} record(s) were modified by another user and skipped.")
                        st.session_state.results=load_all_results(); st.rerun()
            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

            for result in pending:
                o=result.get("ocr",{}); v=result.get("validation",{}); a=result.get("audit",{}); db_id=result["db_id"]
                risk=a.get("risk_level","-")

                # Case header
                st.markdown(
                    f'<div class="case-wrap"><div class="case-hd">'
                    f'<div><div class="case-title">{o.get("vendor","Unknown Vendor")}&nbsp;&nbsp;<span style="font-weight:400;font-size:.85rem;color:#98A2B3;">{o.get("invoice_id","-")}</span></div>'
                    f'<div class="case-meta">{o.get("date","-")}&nbsp;·&nbsp;{o.get("category","-")}&nbsp;·&nbsp;{result["filename"]}</div></div>'
                    f'<div style="display:flex;align-items:center;gap:10px;">'
                    f'<span style="font-size:1.3rem;font-weight:800;color:white;">${o.get("amount",0):,.2f}</span>'
                    f'&nbsp;{rbadge(risk)}</div></div>'
                    f'<div class="case-body">',
                    unsafe_allow_html=True)

                c1, c2 = st.columns([1,1])
                with c1:
                    st.markdown('<div class="sec-t">Invoice Details</div>', unsafe_allow_html=True)
                    st.markdown(kv("Invoice ID",o.get("invoice_id","-"))+kv("Vendor",o.get("vendor","-"))+kv("Date",o.get("date","-"))+kv("Amount",f"${o.get('amount',0):,.2f} {o.get('currency','USD')}")+kv("Category",o.get("category","-"))+conf(o.get("confidence",0)), unsafe_allow_html=True)
                    if o.get("line_items"):
                        st.markdown('<div class="sec-t" style="margin-top:6px;">Line Items</div>'+litems(o["line_items"]), unsafe_allow_html=True)
                    st.markdown('<div class="sec-t" style="margin-top:10px;">Validation Flags</div>'+flags(v.get("flags",[])), unsafe_allow_html=True)

                with c2:
                    st.markdown('<div class="sec-t">AI Audit Reasoning</div>', unsafe_allow_html=True)
                    st.markdown(conf(a.get("confidence",0))+f'<div class="kv-l">Reasoning</div><div class="box-blue">{a.get("reasoning","-")}</div><div class="kv-l">AI Recommendation</div><div class="box-gold">{a.get("recommendation","-")}</div>', unsafe_allow_html=True)
                    refs=a.get("policy_references",[])
                    if refs:
                        st.markdown('<div class="kv-l">Policy References</div>'+"".join(f'<div class="policy-ref">· {r}</div>' for r in refs), unsafe_allow_html=True)

                s3u = result.get("s3_url"); s3k = result.get("s3_key")
                if s3u:
                    st.markdown(
                        f'<div style="margin:0 0 8px;padding:8px 14px;background:#F9FAFB;border:1px solid #E5E7EB;'
                        f'border-radius:8px;display:flex;align-items:center;gap:8px;font-size:.78rem;">'
                        f'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#1570EF" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>'
                        f'<span style="color:#16B364;font-weight:600;">S3</span>'
                        f'<a href="{s3u}" target="_blank" style="color:#1570EF;font-family:monospace;word-break:break-all;">{s3k}</a>'
                        f'</div>',
                        unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)  # close case-body

                # Footer with actions
                st.markdown('<div class="case-footer"><div class="kv-l" style="margin:0;flex-shrink:0;">Reviewer Notes</div>', unsafe_allow_html=True)
                if _role in ("Admin","Reviewer"):
                    nk = f"n_{db_id}"
                    notes = st.text_input("Notes", key=nk, placeholder="Add justification or context…", label_visibility="collapsed")
                    b1, b2, _ = st.columns([1,1,6])
                    with b1:
                        if st.button("✓  Approve", key=f"ap_{db_id}", type="primary"):
                            ok = save_review(db_id,"APPROVED",st.session_state.get(nk,""),result.get("version",1))
                            if not ok:
                                st.warning("This record was updated by someone else. Refresh and try again.")
                            st.session_state.results=load_all_results(); st.rerun()
                    with b2:
                        if st.button("✕  Reject", key=f"re_{db_id}", type="secondary"):
                            ok = save_review(db_id,"REJECTED",st.session_state.get(nk,""),result.get("version",1))
                            if not ok:
                                st.warning("This record was updated by someone else. Refresh and try again.")
                            st.session_state.results=load_all_results(); st.rerun()
                else:
                    st.markdown('<span style="font-size:.78rem;color:#98A2B3;font-style:italic;">View only — Reviewer or Admin role required to make decisions.</span>', unsafe_allow_html=True)
                st.markdown('</div></div>', unsafe_allow_html=True)  # close footer + case-wrap

        if decided:
            st.markdown(f'<div style="font-size:.78rem;font-weight:700;color:#667085;text-transform:uppercase;letter-spacing:.09em;margin:24px 0 10px;">Decided ({len(decided)})</div>', unsafe_allow_html=True)
            for r in decided:
                o=r.get("ocr",{}); dec=r.get("review_decision",""); notes=r.get("review_notes","")
                dc="#05603A" if dec=="APPROVED" else "#912018"
                db="#ECFDF3" if dec=="APPROVED" else "#FEF3F2"
                dbc="#A6F4C5" if dec=="APPROVED" else "#FDA29B"
                st.markdown(
                    f'<div class="decided-row">'
                    f'<div><div class="dc-v">{o.get("vendor","?")}</div>'
                    f'<div class="dc-m">Invoice {o.get("invoice_id","?")} · ${o.get("amount",0):,.2f} · {notes or "No notes"}</div></div>'
                    f'<span style="background:{db};color:{dc};border:1px solid {dbc};'
                    f'font-size:.72rem;font-weight:700;padding:3px 12px;border-radius:6px;">{dec}</span>'
                    f'</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — Reports
# ══════════════════════════════════════════════════════════════════════════════
with t5:
    if not rs_done:
        st.markdown('<div class="empty-state">'+svg("bar",44,"#98A2B3")+'<div class="empty-txt">No data to report yet.</div></div>', unsafe_allow_html=True)
    else:
        approved_l=[r for r in rs_done if r.get("audit",{}).get("audit_status")=="APPROVED" or r.get("review_decision")=="APPROVED"]
        rejected_l=[r for r in rs_done if r.get("audit",{}).get("audit_status")=="REJECTED" or r.get("review_decision")=="REJECTED"]
        pending_l =[r for r in rs_done if r.get("audit",{}).get("audit_status")=="NEEDS_REVIEW" and not r.get("review_decision")]
        ta=sum(r["ocr"].get("amount",0) for r in approved_l)
        tr=sum(r["ocr"].get("amount",0) for r in rejected_l)
        tv=sum(r["ocr"].get("amount",0) for r in rs_done)

        c1,c2,c3,c4=st.columns(4)
        c1.metric("Total Value", f"${tv:,.2f}"); c2.metric("Approved", f"${ta:,.2f}", f"{len(approved_l)} invoices")
        c3.metric("Rejected", f"${tr:,.2f}", f"{len(rejected_l)} invoices"); c4.metric("Pending", len(pending_l))

        hc,dc1,dc2=st.columns([4,1,1])
        rows_data=[{"File":r["filename"],"Invoice ID":r["ocr"].get("invoice_id","-"),"Vendor":r["ocr"].get("vendor","-"),"Amount":r["ocr"].get("amount",0),"Category":r["ocr"].get("category","-"),"Validation":r["validation"].get("validation_status","-"),"Audit":r["audit"].get("audit_status","-"),"Risk":r["audit"].get("risk_level","-"),"Flags":len(r["validation"].get("flags",[])),"Reviewer":r.get("review_decision") or ""} for r in rs_done]
        with dc1:
            st.download_button("↓ CSV", pd.DataFrame(rows_data).to_csv(index=False).encode(),"audit_results.csv","text/csv",use_container_width=True, key="dl_reports")
        with dc2:
            try:
                _report_pdf = build_report_pdf(rs_done, st.session_state.get("expense_summary"))
                st.download_button("↓ PDF", _report_pdf, "audit_report.pdf","application/pdf",use_container_width=True, key="dl_reports_pdf")
            except Exception as _e:
                st.caption(f"PDF unavailable: {_e}")

        # ── AI Expense Summary ────────────────────────────────────────────────
        st.divider()
        sh, sb = st.columns([5, 1])
        with sh:
            st.markdown(
                '<div style="font-size:.72rem;font-weight:700;color:#16B364;text-transform:uppercase;'
                'letter-spacing:.09em;margin:4px 0 0;">✨ AI Expense Summary</div>'
                '<div style="font-size:.8rem;color:#667085;margin-top:2px;">'
                'Natural-language executive overview generated by the Summary Agent (Groq LLM).</div>',
                unsafe_allow_html=True)
        with sb:
            _gen = st.button("✨ Generate", key="gen_summary", use_container_width=True, type="primary")

        if _gen:
            with st.spinner("Summarising expenses with AI…"):
                try:
                    st.session_state.expense_summary = run_summary_agent(rs_done)
                except Exception as e:
                    st.session_state.expense_summary = {"error": str(e)}

        _summ = st.session_state.get("expense_summary")
        if _summ:
            if _summ.get("error"):
                st.error(f"Could not generate summary: {_summ['error']}")
            else:
                _stat = _summ["stats"]
                _chips = [
                    ("Total Spend",   f"${_stat['total_amount']:,.2f}"),
                    ("Documents",     _stat["total_invoices"]),
                    ("Duplicates",    _stat["duplicates"]),
                    ("High Risk",     _stat["high_risk"]),
                    ("Avg Confidence",f"{_stat['avg_confidence']:.0%}"),
                ]
                _chip_html = "".join(
                    f'<div style="background:#ECFDF3;border:1px solid #A6F4C5;border-radius:10px;'
                    f'padding:10px 16px;min-width:120px;">'
                    f'<div style="font-size:.62rem;font-weight:700;color:#16B364;text-transform:uppercase;'
                    f'letter-spacing:.08em;">{lbl}</div>'
                    f'<div style="font-size:1.15rem;font-weight:800;color:#111827;margin-top:2px;">{val}</div></div>'
                    for lbl, val in _chips)
                st.markdown(
                    f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0 16px;">{_chip_html}</div>',
                    unsafe_allow_html=True)
                st.markdown(
                    '<div style="background:white;border:1px solid #A6F4C5;border-left:4px solid #16B364;'
                    'border-radius:0 12px 12px 0;padding:18px 24px;box-shadow:0 2px 10px rgba(22,179,100,.08);">',
                    unsafe_allow_html=True)
                # Escape $ so Streamlit's markdown doesn't treat amounts as LaTeX math
                st.markdown(_summ["narrative"].replace("$", "\\$"))
                st.markdown('</div>', unsafe_allow_html=True)
                st.download_button(
                    "↓ Download Summary", _summ["narrative"].encode(),
                    "expense_summary.md", "text/markdown", key="dl_summary")

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        st.divider()
        for section, items, col in [("✅ Approved",approved_l,"#05603A"),("❌ Rejected",rejected_l,"#912018"),("⏳ Pending Review",pending_l,"#B54708")]:
            if not items: continue
            st.markdown(f'<div style="font-size:.72rem;font-weight:700;color:{col};text-transform:uppercase;letter-spacing:.09em;margin:18px 0 10px;">{section} — {len(items)} invoice{"s" if len(items)!=1 else ""}</div>', unsafe_allow_html=True)
            for r in items:
                o=r["ocr"]; a=r["audit"]; v=r.get("validation",{}); rev=r.get("review_decision")
                st.markdown(
                    f'<div style="background:white;border:1px solid #E5E7EB;border-radius:10px;'
                    f'padding:11px 16px;margin-bottom:7px;">'
                    f'<div style="display:flex;align-items:flex-start;justify-content:space-between;">'
                    f'<div><div class="sr-v">{o.get("vendor","?")}</div>'
                    f'<div class="sr-m">{a.get("recommendation","")}</div></div>'
                    f'<div style="text-align:right;flex-shrink:0;margin-left:12px;">'
                    f'<div class="sr-amt">${o.get("amount",0):,.2f}</div>'
                    f'<div class="sr-id">{o.get("invoice_id","?")}{"&nbsp;·&nbsp;reviewer" if rev else ""}</div>'
                    f'</div></div>'
                    f'{flag_chips(v.get("flags",[]), limit=6)}'
                    f'</div>', unsafe_allow_html=True)
