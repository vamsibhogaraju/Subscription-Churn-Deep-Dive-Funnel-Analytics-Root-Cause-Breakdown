"""
KKBox Revenue Intelligence Dashboard
─────────────────────────────────────
Layout
  Row 1  KPI Ribbon  (5 cards)
  Row 2  Registration Growth Trend  │  Plan Type Distribution Donut
  Row 3  6-Stage Square-Area Chart  │  RCA Root-Cause Table

Run:  streamlit run dashboard_app.py
"""

import math
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import psycopg2

# ══════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="KKBox · Revenue Intelligence",
    page_icon="♟️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════════════
# DESIGN TOKENS  — no red in this palette
# ══════════════════════════════════════════════════════════════
BG       = "#0B0F19"
SURFACE  = "#111827"
SURFACE2 = "#1A2235"
BORDER   = "#1F2D45"
TEXT     = "#F1F5F9"      # primary text
LABEL    = "#94A3B8"      # KPI labels, axis ticks  (was #64748B — too dim)
SUBTEXT  = "#64748B"      # KPI sub-text            (was #334155 — near-invisible)
DIM      = "#334155"      # grid lines, faintest elements only

TEAL   = "#0D9488"
CYAN   = "#06B6D4"
BLUE   = "#3B82F6"
INDIGO = "#6366F1"
VIOLET = "#7C3AED"
AMBER  = "#D97706"
ORANGE = "#EA580C"
SLATE  = "#64748B"

# KPI accent borders — no red
KPI_ACCENTS = [TEAL, BLUE, CYAN, INDIGO, VIOLET]

# RCA table dot colours — orange replaces red
RCA_COLORS = {
    "Voluntary Churn":              ORANGE,
    "Involuntary Payment Failure":  AMBER,
    "Discount Leakage":             TEAL,
    "Passive Expiry":               BLUE,
    "Silent Abandonment":           SLATE,
}

# Stage grid colours — teal → rich blue → indigo → violet → amethyst → slate
STAGE_COLORS = [TEAL, "#2563EB", INDIGO, VIOLET, "#A855F7", SLATE]

# Base chart layout (transparent surface so card bg shows)
_CL = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor ="rgba(0,0,0,0)",
    font=dict(family="Inter, sans-serif", color=LABEL, size=11),
)

# ══════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════
DB = dict(host="localhost", port=5432, dbname="kkbox",
          user="postgres", password="password")

def _conn():
    return psycopg2.connect(**DB)

@st.cache_data(ttl=600, show_spinner=False)
def qry(sql: str) -> pd.DataFrame:
    c = _conn()
    df = pd.read_sql(sql, c)
    c.close()
    return df

def db_alive() -> bool:
    try:
        c = _conn(); c.close(); return True
    except Exception:
        return False

# ══════════════════════════════════════════════════════════════
# SQL — all business logic preserved exactly
# ══════════════════════════════════════════════════════════════
SQL_KPIS = """
WITH
paying AS (
    SELECT COUNT(DISTINCT user_id) AS paying_users,
           SUM(amount_paid)        AS total_revenue
    FROM   transactions WHERE amount_paid > 0
),
registered AS (
    SELECT COUNT(DISTINCT user_id) AS total_users FROM members
),
churned_count AS (
    WITH last_exp AS (
        SELECT user_id, MAX(expire_date) AS last_expire
        FROM   transactions GROUP BY user_id
    ),
    cutoff AS (SELECT MAX(transaction_date) AS end_date FROM transactions)
    SELECT COUNT(*) AS churned_users
    FROM   last_exp le CROSS JOIN cutoff c
    WHERE  le.last_expire < c.end_date
      AND  NOT EXISTS (
               SELECT 1 FROM transactions t
               WHERE  t.user_id = le.user_id
                 AND  t.transaction_date > le.last_expire)
)
SELECT r.total_users, p.paying_users, p.total_revenue, ch.churned_users,
       ROUND(ch.churned_users * 100.0 / NULLIF(p.paying_users, 0), 2) AS churn_rate_pct,
       ROUND(p.total_revenue  * 1.0   / NULLIF(p.paying_users, 0), 2) AS arpu
FROM registered r, paying p, churned_count ch;
"""

SQL_REG_TREND = """
SELECT DATE_TRUNC('month', registration_date)::DATE AS month,
       COUNT(user_id) AS new_users
FROM   members
WHERE  registration_date IS NOT NULL
GROUP  BY 1 ORDER BY 1;
"""

SQL_PLAN = """
SELECT CASE plan_type
           WHEN '30-day'  THEN 'Monthly'
           WHEN '90-day'  THEN 'Quarterly'
           WHEN '180-day' THEN 'Semi-Annual'
           WHEN '365-day' THEN 'Annual'
           ELSE plan_type END     AS plan_label,
       COUNT(DISTINCT user_id)    AS unique_users
FROM   transactions
WHERE  plan_type <> 'other' AND amount_paid > 0
GROUP  BY 1
ORDER  BY unique_users DESC;
"""

SQL_FUNNEL = """
WITH
s1 AS (SELECT DISTINCT user_id FROM members),
s2 AS (
    SELECT DISTINCT t.user_id FROM transactions t
    JOIN   s1 ON s1.user_id = t.user_id WHERE t.amount_paid > 0
),
s3 AS (
    SELECT s2.user_id FROM s2
    WHERE  NOT EXISTS (
        SELECT 1 FROM transactions tc
        WHERE  tc.user_id = s2.user_id AND tc.is_cancel = 1
          AND  tc.transaction_date < (
               SELECT MIN(te.expire_date) FROM transactions te
               WHERE  te.user_id = s2.user_id))
),
s4 AS (
    SELECT t.user_id FROM transactions t JOIN s3 ON s3.user_id = t.user_id
    WHERE  t.amount_paid > 0 AND t.is_cancel = 0
    GROUP  BY t.user_id HAVING COUNT(*) >= 2
),
s5 AS (
    SELECT t.user_id FROM transactions t JOIN s4 ON s4.user_id = t.user_id
    GROUP  BY t.user_id
    HAVING MAX(t.transaction_date) - MIN(t.transaction_date) >= 180
),
gm AS (
    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY engagement_score) AS med
    FROM   user_engagement
),
s6 AS (
    SELECT e.user_id FROM user_engagement e JOIN s5 ON s5.user_id = e.user_id
    CROSS  JOIN gm WHERE e.engagement_score > gm.med
),
counts AS (
    SELECT (SELECT COUNT(*) FROM s1) c1, (SELECT COUNT(*) FROM s2) c2,
           (SELECT COUNT(*) FROM s3) c3, (SELECT COUNT(*) FROM s4) c4,
           (SELECT COUNT(*) FROM s5) c5, (SELECT COUNT(*) FROM s6) c6
)
SELECT stage, users FROM (VALUES
    ('Registered',          (SELECT c1 FROM counts)),
    ('First Payment',       (SELECT c2 FROM counts)),
    ('Survived 1st Period', (SELECT c3 FROM counts)),
    ('Renewed ≥2×',         (SELECT c4 FROM counts)),
    ('Six-Month Tenure',    (SELECT c5 FROM counts)),
    ('Highly Engaged',      (SELECT c6 FROM counts))
) t(stage, users);
"""

SQL_RCA = """
WITH
last_exp AS (
    SELECT user_id, MAX(expire_date) AS last_expire
    FROM   transactions GROUP BY user_id
),
cutoff AS (SELECT MAX(transaction_date) AS end_date FROM transactions),
churned AS (
    SELECT le.user_id FROM last_exp le CROSS JOIN cutoff c
    WHERE  le.last_expire < c.end_date
      AND  NOT EXISTS (
               SELECT 1 FROM transactions t
               WHERE  t.user_id = le.user_id
                 AND  t.transaction_date > le.last_expire)
),
ranked AS (
    SELECT t.*,
           ROW_NUMBER() OVER (
               PARTITION BY t.user_id
               ORDER BY t.transaction_date DESC, t.expire_date DESC) rn
    FROM   transactions t JOIN churned c ON c.user_id = t.user_id
),
last_txn AS (SELECT * FROM ranked WHERE rn = 1),
rca AS (
    SELECT CASE
               WHEN is_cancel         = 1          THEN 'Voluntary Churn'
               WHEN is_payment_failed = 1          THEN 'Involuntary Payment Failure'
               WHEN amount_paid       < plan_price THEN 'Discount Leakage'
               WHEN is_auto_renew     = 0          THEN 'Passive Expiry'
               ELSE 'Silent Abandonment' END AS category,
           plan_price
    FROM last_txn
)
SELECT category,
       COUNT(*)        AS user_count,
       SUM(plan_price) AS revenue_lost,
       ROUND(SUM(plan_price)*100.0 / NULLIF(SUM(SUM(plan_price)) OVER (),0),2) AS share_pct
FROM   rca GROUP BY category ORDER BY revenue_lost DESC;
"""

# ══════════════════════════════════════════════════════════════
# HELPER
# ══════════════════════════════════════════════════════════════
def _fmt(n: float) -> str:
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.0f}K"
    return f"{n:,.0f}"

# ══════════════════════════════════════════════════════════════
# VISUAL 1 — Registration Growth Trend
# ══════════════════════════════════════════════════════════════
def chart_reg_trend(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=df["month"], y=df["new_users"],
        mode="lines",
        line=dict(color=BLUE, width=2, shape="spline"),
        fill="tozeroy",
        fillcolor="rgba(59,130,246,0.07)",
        hovertemplate="%{x|%b %Y}  ·  %{y:,.0f} new users<extra></extra>",
    ))
    fig.update_layout(
        **_CL,
        title=dict(text="Registration Growth", x=0,
                   font=dict(color=TEXT, size=13, family="Inter")),
        xaxis=dict(gridcolor=DIM, showline=False,
                   tickformat="%Y", tickfont=dict(size=10, color=LABEL)),
        yaxis=dict(gridcolor=DIM, showline=False, zeroline=False,
                   tickfont=dict(size=10, color=LABEL)),
        hovermode="x unified",
        margin=dict(l=0, r=0, t=36, b=0),
        height=300,
    )
    return fig

# ══════════════════════════════════════════════════════════════
# VISUAL 2 — Plan Type Distribution Donut
# ══════════════════════════════════════════════════════════════
def chart_plan_donut(df: pd.DataFrame) -> go.Figure:
    plan_colours = {
        "Monthly":     TEAL,        # dominant — deep teal
        "Semi-Annual": "#2563EB",   # rich blue (matches funnel stage 2)
        "Quarterly":   INDIGO,      # indigo
        "Annual":      "#A855F7",   # amethyst purple
    }
    colours = [plan_colours.get(p, SLATE) for p in df["plan_label"]]
    total   = int(df["unique_users"].sum())

    fig = go.Figure(go.Pie(
        labels=df["plan_label"].tolist(),
        values=df["unique_users"].tolist(),
        hole=0.70,
        marker=dict(colors=colours, line=dict(color=BG, width=2)),
        textinfo="none",
        hovertemplate="<b>%{label}</b><br>%{value:,} users  (%{percent})<extra></extra>",
        direction="clockwise",
        sort=False,
    ))
    fig.add_annotation(
        text=(
            f"<span style='font-size:22px;font-weight:700;color:{TEXT}'>"
            f"{_fmt(total)}</span>"
            f"<br>"
            f"<span style='font-size:10px;font-weight:500;"
            f"color:{LABEL};letter-spacing:0.06em'>SUBSCRIBERS</span>"
        ),
        x=0.5, y=0.5,
        font=dict(family="Inter"),
        showarrow=False, align="center",
    )
    fig.update_layout(
        **_CL,
        title=dict(text="Plan Type Distribution", x=0,
                   font=dict(color=TEXT, size=13, family="Inter")),
        showlegend=True,
        legend=dict(
            orientation="v", x=1.0, y=0.5, xanchor="left",
            font=dict(size=11, color=LABEL),
            bgcolor="rgba(0,0,0,0)",
            itemsizing="constant",
        ),
        margin=dict(l=0, r=90, t=36, b=0),
        height=300,
    )
    return fig

# ══════════════════════════════════════════════════════════════
# VISUAL 3 — 6-Stage Square-Area Chart
#
# True square-area style: each stage is its own 2-D block of
# equal-sized squares that wraps into as many rows as needed.
# Larger stages produce larger rectangular blocks; smaller
# stages produce smaller ones — all clearly separated.
#
# Visual encoding
#   • Each stage → its own block, stacked top-to-bottom
#   • Block area (number of squares) = √-scaled to handle the
#     6.77 M → 3.3 K range while keeping all stages visible
#   • Squares fill left-to-right, wrap to next row
#   • Stage label  left  |  block  center  |  count + %  right
#   • √ scaling disclosed in subtitle; exact counts labeled
#
# No business-logic changes — uses df_funnel exactly as-is.
# ══════════════════════════════════════════════════════════════
def chart_stage_grid(df: pd.DataFrame) -> go.Figure:
    stages = df["stage"].tolist()   # exact stage names from SQL
    users  = df["users"].tolist()   # exact counts from SQL

    # √-scale: up to 50 squares for the largest stage, min 1
    sqrt_u   = [math.sqrt(u) for u in users]
    max_sqrt = max(sqrt_u)
    MAX_SQ    = 64          # max squares assigned to largest block
    COLS      = 16          # squares per row within each block
    ROW_STEP  = 0.88        # y-units between rows within a block (< 1 = tighter)
    GAP       = 0.75        # y-units of blank space between stage blocks

    n_sq = [max(1, round(s / max_sqrt * MAX_SQ)) for s in sqrt_u]
    # With real funnel data → [50, 20, 20, 6, 2, 1]

    fig         = go.Figure()
    y_top       = 0.0      # top y of current block (decrements downward)
    y_min       = 0.0
    annotations = []

    for stage, count, n, color in zip(stages, users, n_sq, STAGE_COLORS):
        n_rows = math.ceil(n / COLS)
        pct    = count / users[0] * 100

        # Squares: fill left-to-right, wrap to next row (ROW_STEP controls density)
        xs = [sq % COLS                       for sq in range(n)]
        ys = [y_top - (sq // COLS) * ROW_STEP for sq in range(n)]

        fig.add_trace(go.Scatter(
            x=xs, y=ys,
            mode="markers",
            name=stage,
            marker=dict(
                symbol="square", size=20,
                color=color, opacity=0.88,
                line=dict(color=BG, width=1.5),
            ),
            hovertemplate=(
                f"<b>{stage}</b><br>"
                f"{count:,.0f} users · {pct:.1f}% of registered"
                "<extra></extra>"
            ),
            showlegend=False,
        ))

        y_center = y_top - (n_rows - 1) / 2 * ROW_STEP
        y_bottom = y_top - (n_rows - 1) * ROW_STEP

        # Stage name — anchored left of block
        annotations.append(dict(
            x=-1.2, y=y_center,
            xanchor="right", yanchor="middle",
            text=f"<b>{stage}</b>",
            font=dict(size=10, color=TEXT, family="Inter"),
            showarrow=False,
        ))

        # Count + % — anchored right of block
        annotations.append(dict(
            x=COLS + 0.5, y=y_center,
            xanchor="left", yanchor="middle",
            text=(
                f"<b style='color:{color}'>{count:,.0f}</b>"
                f"<span style='color:{SUBTEXT};font-size:10px'>"
                f"  {pct:.1f}%</span>"
            ),
            font=dict(size=11, family="Inter"),
            showarrow=False,
        ))

        y_min  = min(y_min, y_bottom)
        y_top  = y_bottom - GAP     # next block starts below this one

    y_span = abs(y_min) + 1.2       # total y range + padding
    height = max(360, int(y_span * 30))

    fig.update_layout(
        **_CL,
        title=dict(
            text=(
                "6-Stage Revenue Funnel"
                f"<span style='font-size:10px;color:{SUBTEXT};font-weight:400;'>"
                "  ·  block area √-scaled  ·  exact counts labeled"
                "</span>"
            ),
            x=0, font=dict(color=TEXT, size=13, family="Inter"),
        ),
        annotations=annotations,
        xaxis=dict(
            showgrid=False, showticklabels=False,
            zeroline=False, range=[-9, COLS + 11],
        ),
        yaxis=dict(
            showgrid=False, showline=False, zeroline=False,
            showticklabels=False,
            range=[y_min - 0.8, 0.8],
        ),
        margin=dict(l=10, r=10, t=48, b=10),
        height=height,
        showlegend=False,
    )
    return fig

# ══════════════════════════════════════════════════════════════
# VISUAL 4 — RCA Table  (HTML, polished)
# ══════════════════════════════════════════════════════════════
def render_rca_table(df: pd.DataFrame) -> None:
    df = df.copy()
    df.columns = ["category", "user_count", "revenue_lost", "share_pct"]
    df = df.sort_values("revenue_lost", ascending=False).reset_index(drop=True)
    df["cum_pct"] = df["share_pct"].cumsum().round(1)

    TH = (f"padding:9px 14px;font-size:10px;font-weight:600;"
          f"text-transform:uppercase;letter-spacing:0.07em;"
          f"color:{LABEL};border-bottom:1px solid {BORDER};")
    TD_L = (f"padding:11px 14px;font-size:12px;color:{TEXT};"
            f"border-bottom:1px solid {BORDER};vertical-align:middle;")
    TD_R = (f"padding:11px 14px;font-size:12px;color:{LABEL};"
            f"border-bottom:1px solid {BORDER};text-align:right;")
    TD_REV = (f"padding:11px 14px;font-size:12px;color:{TEXT};font-weight:600;"
              f"border-bottom:1px solid {BORDER};text-align:right;")
    TD_CUM = (f"padding:11px 14px;font-size:12px;color:{TEAL};font-weight:500;"
              f"border-bottom:1px solid {BORDER};text-align:right;")

    rows = ""
    for _, r in df.iterrows():
        dot_c = RCA_COLORS.get(r["category"], SLATE)
        dot   = (f"<span style='display:inline-block;width:7px;height:7px;"
                 f"border-radius:50%;background:{dot_c};"
                 f"margin-right:9px;flex-shrink:0;'></span>")
        rows += f"""
        <tr>
          <td style='{TD_L}'><span style='display:flex;align-items:center;'>{dot}{r['category']}</span></td>
          <td style='{TD_R}'>{int(r['user_count']):,}</td>
          <td style='{TD_REV}'>${int(r['revenue_lost']):,}</td>
          <td style='{TD_R}'>{r['share_pct']:.1f}%</td>
          <td style='{TD_CUM}'>{r['cum_pct']:.1f}%</td>
        </tr>"""

    st.markdown(f"""
    <div style='font-family:Inter,sans-serif;'>
      <div style='font-size:13px;font-weight:600;color:{TEXT};
                  margin-bottom:12px;letter-spacing:0.01em;'>
        Revenue Leakage — Root Cause Analysis
      </div>
      <table style='width:100%;border-collapse:collapse;
                    background:{SURFACE};border-radius:6px;
                    overflow:hidden;border:1px solid {BORDER};'>
        <thead>
          <tr style='background:{SURFACE2};'>
            <th style='{TH}text-align:left;'>Root Cause</th>
            <th style='{TH}text-align:right;'>Users Lost</th>
            <th style='{TH}text-align:right;'>Revenue Lost</th>
            <th style='{TH}text-align:right;'>Share</th>
            <th style='{TH}text-align:right;'>Cumulative</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {{
    font-family: 'Inter', sans-serif !important;
    background-color: {BG} !important;
    color: {TEXT};
}}
#MainMenu, footer, header {{ visibility: hidden; }}
section[data-testid="stSidebar"] {{ display: none; }}
.block-container {{
    padding-top: 1.8rem !important;
    padding-bottom: 2rem !important;
}}

/* ── KPI Card ─────────────────────────────────────────────── */
.kpi-card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-left: 3px solid var(--accent);
    border-radius: 7px;
    padding: 18px 20px 16px;
    height: 100%;
}}
.kpi-label {{
    font-size: 10px;
    font-weight: 600;
    color: {LABEL};           /* #94A3B8 — clearly readable */
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 8px;
}}
.kpi-value {{
    font-size: 28px;
    font-weight: 700;
    color: {TEXT};
    line-height: 1.15;
    letter-spacing: -0.02em;
    margin-bottom: 6px;
}}
.kpi-sub {{
    font-size: 11px;
    font-weight: 500;
    color: {SUBTEXT};         /* #64748B — visible but secondary */
    margin-top: 0;
}}

/* ── Chart card ───────────────────────────────────────────── */
.chart-card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 20px 18px 16px;
}}

/* ── Section label ────────────────────────────────────────── */
.section-label {{
    font-size: 10px;
    font-weight: 600;
    color: {LABEL};
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin: 18px 0 10px;
    display: flex;
    align-items: center;
    gap: 8px;
}}
.section-label::after {{
    content: '';
    flex: 1;
    height: 1px;
    background: {BORDER};
}}

/* ── Footer ───────────────────────────────────────────────── */
.footer-line {{
    border: none;
    border-top: 1px solid {BORDER};
    margin: 24px 0 12px;
}}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════
ok = db_alive()
dot, status = ("🟢", "Connected") if ok else ("🔴", "Offline")

hc1, hc2 = st.columns([6, 1])
with hc1:
    st.markdown(
        f"<h2 style='margin:0;font-size:22px;font-weight:700;"
        f"letter-spacing:-0.02em;color:{TEXT};'>"
        f"Revenue Intelligence"
        f"<span style='color:{LABEL};font-weight:400;'> · KKBox</span>"
        f"</h2>",
        unsafe_allow_html=True,
    )
with hc2:
    st.markdown(
        f"<div style='text-align:right;font-size:11px;color:{LABEL};"
        f"padding-top:8px;'>{dot} {status}</div>",
        unsafe_allow_html=True,
    )

st.markdown(
    f"<div style='height:1px;background:{BORDER};margin:10px 0 20px;'></div>",
    unsafe_allow_html=True,
)

if not ok:
    st.error("Cannot reach PostgreSQL. Is the server running?")
    st.stop()

# ══════════════════════════════════════════════════════════════
# LOAD DATA
# ══════════════════════════════════════════════════════════════
with st.spinner("Loading…"):
    raw_kpi   = qry(SQL_KPIS)
    if raw_kpi.empty:
        st.error("No KPI data returned."); st.stop()
    k         = raw_kpi.iloc[0]
    df_reg    = qry(SQL_REG_TREND)
    df_plan   = qry(SQL_PLAN)
    df_funnel = qry(SQL_FUNNEL)
    df_rca    = qry(SQL_RCA)

# ══════════════════════════════════════════════════════════════
# KPI RIBBON
# ══════════════════════════════════════════════════════════════
kpis = [
    ("Total Registered",  f"{int(k['total_users']):,}",        "Members table"),
    ("Paying Users",      f"{int(k['paying_users']):,}",        f"{k['paying_users']/k['total_users']:.1%} of registered"),
    ("Gross Revenue",     f"${int(k['total_revenue']):,}",     "Lifetime paid"),
    ("Churn Rate",        f"{float(k['churn_rate_pct']):.1f}%", "Of paying base"),
    ("ARPU",              f"${float(k['arpu']):,.0f}",          "Avg revenue / user"),
]

cols = st.columns(5, gap="small")
for (label, val, sub), col, accent in zip(kpis, cols, KPI_ACCENTS):
    with col:
        st.markdown(
            f"<div class='kpi-card' style='--accent:{accent};'>"
            f"<div class='kpi-label'>{label}</div>"
            f"<div class='kpi-value'>{val}</div>"
            f"<div class='kpi-sub'>{sub}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

# ══════════════════════════════════════════════════════════════
# ROW 2 — Visual 1: Reg Trend  │  Visual 2: Plan Donut
# ══════════════════════════════════════════════════════════════
st.markdown(
    "<div class='section-label'>Acquisition &amp; Plan Mix</div>",
    unsafe_allow_html=True,
)

c_reg, c_plan = st.columns([3, 2], gap="medium")

with c_reg:
    st.markdown("<div class='chart-card'>", unsafe_allow_html=True)
    st.plotly_chart(chart_reg_trend(df_reg), use_container_width=True,
                    config={"displayModeBar": False})
    st.markdown("</div>", unsafe_allow_html=True)

with c_plan:
    st.markdown("<div class='chart-card'>", unsafe_allow_html=True)
    st.plotly_chart(chart_plan_donut(df_plan), use_container_width=True,
                    config={"displayModeBar": False})
    st.markdown("</div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# ROW 3 — Visual 3: Stage Grid  │  Visual 4: RCA Table
# ══════════════════════════════════════════════════════════════
st.markdown(
    "<div class='section-label'>Churn Diagnostics</div>",
    unsafe_allow_html=True,
)

c_grid, c_rca = st.columns(2, gap="medium")

with c_grid:
    st.markdown("<div class='chart-card'>", unsafe_allow_html=True)
    st.plotly_chart(chart_stage_grid(df_funnel), use_container_width=True,
                    config={"displayModeBar": False})
    st.markdown("</div>", unsafe_allow_html=True)

with c_rca:
    st.markdown("<div class='chart-card'>", unsafe_allow_html=True)
    render_rca_table(df_rca)
    st.markdown("</div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════
st.markdown("<div class='footer-line'></div>", unsafe_allow_html=True)
st.markdown(
    f"<div style='text-align:center;color:{SUBTEXT};font-size:10px;"
    f"letter-spacing:0.04em;'>"
    f"KKBOX · REVENUE INTELLIGENCE · DATA: 2015–2017 · CACHE: 10 MIN"
    f"</div>",
    unsafe_allow_html=True,
)
