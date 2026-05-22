import math
import io
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

# ─────────────────────────────────────────────
#  Page config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Leveling Computation Tool",
    page_icon="leveling",
    layout="wide",
)


# ─────────────────────────────────────────────
#  Logic helpers
# ─────────────────────────────────────────────

THREE_WIRE_COLS = ['BS_point','BS_upper','BS_middle','BS_lower','FS_point','FS_upper','FS_middle','FS_lower']
DIFF_COLS       = ['BS_point','BS_Reading','BS_Dist','FS_point','FS_Readings','FS_Dist']


def detect_type(df: pd.DataFrame) -> str:
    cols = df.columns.tolist()
    if all(c in cols for c in THREE_WIRE_COLS):
        return '3-Wire'
    if all(c in cols for c in DIFF_COLS):
        return 'Differential'
    return ''


def compute_elevations(df: pd.DataFrame, level_type: str, bm_elev: float):
    df = df.copy()
    HI_list, elev_list = [], []
    current = bm_elev

    if level_type == '3-Wire':
        df['BS_Reading'] = ((df['BS_upper'] + df['BS_middle'] + df['BS_lower']) / 3).round(3)
        df['FS_Readings'] = ((df['FS_upper'] + df['FS_middle'] + df['FS_lower']) / 3).round(3)

    for _, row in df.iterrows():
        hi = current + row['BS_Reading']
        HI_list.append(hi)
        elev = hi - row['FS_Readings']
        elev_list.append(elev)
        current = elev

    df['HI'] = HI_list
    df['Elevation'] = elev_list
    return df, HI_list, elev_list


def compute_misclosure(df: pd.DataFrame, level_type: str):
    df = df.copy()

    if level_type == '3-Wire':
        df['BS_Dist'] = (df['BS_upper'] - df['BS_lower']) * 100
        df['FS_Dist'] = (df['FS_upper'] - df['FS_lower']) * 100

    df['Total_Dist'] = df['BS_Dist'] + df['FS_Dist']
    df['Dist_from_BM'] = df['Total_Dist'].cumsum()

    tot_dist = df['Total_Dist'].sum()
    misclosure = round(df['BS_Reading'].sum() - df['FS_Readings'].sum(), 4)

    tot_dist_km = tot_dist / 1000
    sqrt_d = math.sqrt(tot_dist_km) if tot_dist_km > 0 else 0
    abs_err = abs(misclosure)

    if abs_err <= 0.004 * sqrt_d:
        order = 'First Order'
    elif abs_err <= 0.008 * sqrt_d:
        order = 'Second Order'
    elif abs_err <= 0.012 * sqrt_d:
        order = 'Third Order'
    else:
        order = 'Rejected'

    return df, misclosure, order, tot_dist


def adjust_elevations(df: pd.DataFrame, misclosure: float, tot_dist: float):
    df = df.copy()
    if tot_dist > 0:
        df['Adj_Elev'] = df['Elevation'] - misclosure * (df['Dist_from_BM'] / tot_dist)
    else:
        df['Adj_Elev'] = df['Elevation']
    return df


def make_profile_fig(df: pd.DataFrame, title: str):
    fig, ax = plt.subplots(figsize=(10, 4))

    x = df['Dist_from_BM']
    y = df['Adj_Elev']

    ax.plot(x, y, marker='o', linewidth=2, markersize=5, label='Adjusted Elevation')
    ax.fill_between(x, y, alpha=0.12)

    ax.set_title(f'{title} — Elevation Profile', fontsize=11, pad=10)
    ax.set_xlabel('Distance from BM (m)', fontsize=9)
    ax.set_ylabel('Elevation (m)', fontsize=9)
    ax.grid(True, linewidth=0.5, alpha=0.9)
    ax.legend(fontsize=8)
    plt.tight_layout()
    return fig


# ─────────────────────────────────────────────
#  Session state init
# ─────────────────────────────────────────────
for key in ('df_raw','level_type','df_computed','df_final','misclosure','accuracy','tot_dist','last_uploaded'):
    if key not in st.session_state:
        st.session_state[key] = None


# ─────────────────────────────────────────────
#  SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Leveling Tool")
    st.markdown("### Step 1 — Load Data")

    uploaded = st.file_uploader("Upload CSV file", type=['csv'])

    if uploaded:
        if st.session_state.last_uploaded != uploaded.name:
            try:
                df_raw = pd.read_csv(uploaded)
                ltype = detect_type(df_raw)
                if ltype:
                    st.session_state.df_raw = df_raw
                    st.session_state.level_type = ltype
                    st.session_state.df_computed = None
                    st.session_state.df_final = None
                    st.session_state.misclosure = None
                    st.session_state.last_uploaded = uploaded.name
                else:
                    st.error("Unrecognised CSV format. Check column names.")
            except Exception as e:
                st.error(f"Could not read file: {e}")

        if st.session_state.level_type:
            st.success(f"Detected: **{st.session_state.level_type} Leveling**")

    if st.session_state.level_type:
        st.markdown("### Step 2 — BM Elevation")
        bm_elev = st.number_input("Benchmark Elevation (m)", value=100.000, step=0.001, format="%.3f")

        if st.button("Compute", use_container_width=True):
            df = st.session_state.df_raw.copy()
            ltype = st.session_state.level_type

            df, hi_list, elev_list = compute_elevations(df, ltype, bm_elev)
            df, misc, order, tot_dist = compute_misclosure(df, ltype)
            df = adjust_elevations(df, misc, tot_dist)

            st.session_state.df_computed = df
            st.session_state.df_final = df
            st.session_state.misclosure = misc
            st.session_state.accuracy = order
            st.session_state.tot_dist = tot_dist

    if st.session_state.df_final is not None:
        st.markdown("### Step 3 — Export")
        proj_name = st.text_input("Project name", value="Project_A")

        col1, col2 = st.columns(2)

        with col1:
            df_out = st.session_state.df_final
            txt_buf = io.StringIO()
            txt_buf.write("--- LEVELING COMPUTATION REPORT ---\n\n")
            txt_buf.write(df_out.to_string(index=False))
            txt_buf.write("\n\n--- MISCLOSURE AND ACCURACY SUMMARY ---\n")
            txt_buf.write(f"Error of Misclosure: {st.session_state.misclosure}\n")
            txt_buf.write(f"Order of Accuracy: {st.session_state.accuracy}\n")
            st.download_button("TXT", txt_buf.getvalue(),
                               file_name=f"{proj_name}_report.txt", mime="text/plain",
                               use_container_width=True)

        with col2:
            html_str  = "<html><head><title>Leveling Report</title>"
            html_str += "<style>body{font-family:Arial,sans-serif;margin:40px;} table{border-collapse:collapse;width:100%;} th,td{border:1px solid #ccc;padding:8px;text-align:center;}</style></head><body>"
            html_str += "<h2>Leveling Computation Report</h2>"
            html_str += df_out.to_html(index=False)
            html_str += f"<h2>Misclosure & Accuracy</h2><p><b>Error of Misclosure:</b> {st.session_state.misclosure}</p>"
            html_str += f"<p><b>Order of Accuracy:</b> {st.session_state.accuracy}</p></body></html>"
            st.download_button("HTML", html_str,
                               file_name=f"{proj_name}_report.html", mime="text/html",
                               use_container_width=True)

        fig_dl = make_profile_fig(st.session_state.df_final, proj_name)
        img_buf = io.BytesIO()
        fig_dl.savefig(img_buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig_dl)
        st.download_button("Profile PNG", img_buf.getvalue(),
                           file_name=f"{proj_name}_profile.png", mime="image/png",
                           use_container_width=True)


# ─────────────────────────────────────────────
#  MAIN AREA
# ─────────────────────────────────────────────
st.title("Leveling Computation Tool")
st.write("Upload a differential or 3-wire leveling CSV, enter a benchmark elevation, and compute.")

if st.session_state.df_raw is None:
    st.info("Upload a CSV file in the sidebar to get started.")
    st.stop()

# ── Raw data preview ──────────────────────────
st.subheader("Raw Data Preview")
col_info1, col_info2 = st.columns([3, 1])
with col_info1:
    st.dataframe(st.session_state.df_raw, use_container_width=True, height=200)
with col_info2:
    rows = len(st.session_state.df_raw)
    ltype = st.session_state.level_type
    st.metric("Leveling Type", ltype)
    st.metric("Stations", rows)

if st.session_state.df_final is None:
    st.caption("Set the BM elevation in the sidebar and click **Compute** to continue.")
    st.stop()

df = st.session_state.df_final

# ── Summary metrics ───────────────────────────
st.subheader("Summary")
m1, m2, m3, m4 = st.columns(4)

misc  = st.session_state.misclosure
order = st.session_state.accuracy
tdist = st.session_state.tot_dist

with m1:
    st.metric("Error of Misclosure", f"{misc:.4f} m")
with m2:
    st.metric("Total Distance", f"{tdist:.1f} m", f"{tdist/1000:.3f} km")
with m3:
    st.metric("Final Elevation", f"{df['Adj_Elev'].iloc[-1]:.3f} m", "Last station")
with m4:
    st.metric("Order of Accuracy", order)

# ── Elevation Profile ──────────────────────────
st.subheader("Elevation Profile")
fig = make_profile_fig(df, "Survey")
st.pyplot(fig, use_container_width=True)
plt.close(fig)

# ── Computed table ────────────────────────────
st.subheader("Computed Results")

display_cols = ['BS_point', 'BS_Reading', 'FS_point', 'FS_Readings',
                'BS_Dist', 'FS_Dist', 'Total_Dist', 'Dist_from_BM',
                'HI', 'Elevation', 'Adj_Elev']
display_cols = [c for c in display_cols if c in df.columns]

st.dataframe(
    df[display_cols].style.format({
        c: '{:.3f}' for c in display_cols if c not in ('BS_point', 'FS_point')
    }),
    use_container_width=True,
    height=350,
)