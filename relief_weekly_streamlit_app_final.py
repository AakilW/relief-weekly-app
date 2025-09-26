# relief_weekly_streamlit_app_final.py
# Finalized Streamlit app implementing requested changes (ERA + Provider logic update + Self-Pay in Provider Visits + Exclude PAT from AR)
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from io import BytesIO
from datetime import date

# ---------------------- Page Setup ----------------------
st.set_page_config(page_title="Relief Weekly Update", layout="wide")

# ---------------------- Add Logos / Header ----------------------
from datetime import date

# Format today's date
today_str = date.today().strftime('%B %d, %Y')  # e.g., 'September 19, 2025'

# Layout with logos and centered title
col1, col2, col3 = st.columns([1, 5, 1])
with col1:
    st.image("assets/simplibill.png", width=120)
with col2:
    st.markdown(f"<h1 style='text-align: center;'>Weekly Update - {today_str}</h1>", unsafe_allow_html=True)
with col3:
    st.image("assets/Picture1.png", width=120)

st.markdown("---")

# ---------------------- Constants / Required columns ----------------------
REQUIRED_371 = [
    'Claim Status Code', 'Claim Status Group Name',
    'Primary Payer', 'Claim No', 'Rendering Provider', 'Billed Charge', 'Payer Charge',
    'Total Payment', 'Payer Payment', 'Patient Payment', 'Contractual Adjustment',
    'Fee Schedule Allowed Fee', 'Total(Balance)'
]

REQUIRED_123 = [
    'Date', 'Billed Charges', 'Self Pay Charges', 'Payer Charges', 'Total Payments',
    'Patient Payments', 'Payer Payments', 'Contractual Adjustments'
]

DOS_CUTOFF = pd.to_datetime(date(2024, 11, 1))  # Global DOS filter
EXCLUDE_PROVIDER = 'salah, ahmad'

# ---------------------- Utility functions ----------------------
def try_parse_dates(df, col_candidates):
    for c in col_candidates:
        if c in df.columns:
            try:
                df[c] = pd.to_datetime(df[c], errors='coerce')
                return c
            except Exception:
                continue
    return None

def validate_columns(df, required, name):
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.warning(f"File '{name}' is missing expected columns: {missing}. App will attempt best-effort processing.")
    return missing

@st.cache_data
def load_file(file):
    if file is None:
        return None
    name = file.name
    if name.lower().endswith('.csv'):
        return pd.read_csv(file, low_memory=False)
    else:
        return pd.read_excel(file, engine='openpyxl')

# ---------------------- Sidebar / Upload ----------------------
st.sidebar.title("Upload reports & options")
file_371 = st.sidebar.file_uploader("Upload 371.05 - Financial Analysis at CPT Level – Detail", type=['xlsx','xls','csv'], key='u371')
file_123 = st.sidebar.file_uploader("Upload 123.07 - Daily Transactions", type=['xlsx','xls','csv'], key='u123')
file_era = st.sidebar.file_uploader("Upload ERA (Unposted Payments)", type=['xlsx'], key='uera')

enable_export = st.sidebar.checkbox('Enable export of KPI workbook', value=True)

# ---------------------- Load files ----------------------
df371 = load_file(file_371)
df123 = load_file(file_123)

if df371 is None or df123 is None:
    st.info('Please upload both required reports (371.05 and 123.07) in the sidebar to continue.')
    st.stop()

st.markdown(f"**Files loaded:** 371.05: **{file_371.name}**, 123.07: **{file_123.name}**")

# ---------------------- Validate & Preprocess ----------------------
validate_columns(df371, REQUIRED_371, file_371.name)
validate_columns(df123, REQUIRED_123, file_123.name)

# Parse dates
dos_col = try_parse_dates(df371, ['Start Date of Service','DOS'])
claimdate_col = try_parse_dates(df371, ['Claim Date'])
date123_col = try_parse_dates(df123, ['Date'])

# Numeric coercion
num_cols_371 = ['Billed Charge','Payer Charge','Total Payment','Payer Payment','Patient Payment','Contractual Adjustment','Total(Balance)','Fee Schedule Allowed Fee']
for col in num_cols_371:
    if col in df371.columns:
        df371[col] = pd.to_numeric(df371[col], errors='coerce').fillna(0.0)

# Working copies
line_items = df371.copy()
claims = df371.drop_duplicates(subset=['Claim No']).copy()

# Normalize payer/provider
for df in [line_items, claims]:
    df['Primary Payer'] = df.get('Primary Payer','').fillna('Unknown').astype(str)
    df['Rendering Provider'] = df.get('Rendering Provider','').fillna('').astype(str)

# Balance
if 'Total(Balance)' in claims.columns:
    claims['Balance'] = pd.to_numeric(claims['Total(Balance)'], errors='coerce').fillna(0.0)
else:
    claims['Balance'] = claims['Billed Charge'] - claims['Total Payment'] - claims['Contractual Adjustment']

# Aging
if dos_col:
    claims['DOS_parsed'] = pd.to_datetime(claims[dos_col], errors='coerce')
    claims['AgingDays'] = (pd.to_datetime(date.today()) - claims['DOS_parsed']).dt.days
else:
    claims['AgingDays'] = np.nan

st.success('Validation and preprocessing complete.')

# ---------------------- KPI MODULES ----------------------

# 1) Provider-Level Visits Breakdown
st.header('PROVIDER LEVEL VISITS BREAKDOWN')
with st.expander('Provider-level monthly unique claim counts (Self-Pay included, Salah Ahmad excluded)'):
    pv = claims.copy()

    if 'Start Date of Service' in pv.columns:
        pv['Start Date of Service'] = pd.to_datetime(pv['Start Date of Service'], errors='coerce')
        pv = pv[pv['Start Date of Service'] >= DOS_CUTOFF]
    pv = pv[~pv['Rendering Provider'].str.lower().str.strip().eq(EXCLUDE_PROVIDER)]

    pv = pv.drop_duplicates(subset=['Claim No'])

    if 'Claim Date' in pv.columns:
        pv['Month'] = pd.to_datetime(pv['Claim Date'], errors='coerce').dt.strftime('%Y-%m')
    else:
        pv['Month'] = 'Unknown'

    pt = pv.groupby(['Rendering Provider','Month'])['Claim No'].nunique().unstack(fill_value=0)
    pt['Grand Total'] = pt.sum(axis=1)

    total_row = pd.DataFrame(pt.sum()).T
    total_row.index = ['Grand Total']
    pt_full = pd.concat([pt, total_row])

    total_claims = pt_full.loc['Grand Total','Grand Total']
    pt_full['% Share'] = ((pt_full['Grand Total'] / total_claims) * 100).round(0)

    st.dataframe(pt_full.fillna(0).astype({c:int for c in pt_full.select_dtypes(include='number').columns}), width="stretch")

    pie_df = pt_full.reset_index().rename(columns={'index':'Rendering Provider'})
    pie_df_chart = pie_df[pie_df['Rendering Provider'] != 'Grand Total'][['Rendering Provider','Grand Total']]
    fig = px.pie(pie_df_chart, values='Grand Total', names='Rendering Provider', title='Claims by Rendering Provider')
    st.plotly_chart(fig, width="stretch")

# 2) Payer Mix Based on Visits
st.header('PAYER MIX BASED ON VISITS')
with st.expander('Payer mix (by unique claims) — includes Self-Pay and groups smaller payers into Other minor payers'):
    pm = claims.copy()
    pm_counts = pm.groupby('Primary Payer')['Claim No'].nunique().reset_index(name='Claims')

    minor_threshold = 10
    major = pm_counts[pm_counts['Claims'] >= minor_threshold].copy()
    minor = pm_counts[pm_counts['Claims'] < minor_threshold].copy()
    if not minor.empty:
        other_sum = minor['Claims'].sum()
        major = pd.concat([major, pd.DataFrame({'Primary Payer':['Other minor payers'], 'Claims':[other_sum]})], ignore_index=True)
    major = major.sort_values('Claims', ascending=False)
    major['Pct'] = (major['Claims'] / major['Claims'].sum() * 100).round(2)
    st.dataframe(major.reset_index(drop=True))

    fig = px.pie(major, values='Claims', names='Primary Payer', title='Payer Mix by Claims (including Self-Pay)')
    st.plotly_chart(fig, width="stretch")

# 3) Insurance AR Aging — new logic with expander
st.header('INSURANCE AR AGING')
with st.expander("Insurance AR Aging (DOS-based; excludes Self-Pay and PAT status)", expanded=False):
    if file_371:
        df = pd.read_excel(file_371)

        # Normalize column names
        df.columns = df.columns.str.strip()

        # Parse Start Date of Service
        df["Start Date of Service"] = pd.to_datetime(df.get("Start Date of Service"), errors="coerce")

        # Calculate Aging Days
        today = pd.Timestamp.today().normalize()
        df["AgingDays"] = (today - df["Start Date of Service"]).dt.days

        # Filter: Exclude Self Pay
        df = df[~df["Primary Payer"].astype(str).str.strip().str.upper().eq("SELF PAY")]

        # Filter: Exclude PAT status
        if "Claim Status Code" in df.columns:
            df = df[~df["Claim Status Code"].astype(str).str.upper().str.contains("PAT", na=False)]

        # Bucket Aging Days
        bins = [-1, 30, 60, 90, 120, float("inf")]
        labels = ["0 - 30 Days", "31 - 60 Days", "61 - 90 Days", "91 - 120 Days", "Above 120 Days"]
        df["AgingBucket"] = pd.cut(df["AgingDays"].fillna(999999), bins=bins, labels=labels)

        # Clean numeric columns
        df["Charges"] = pd.to_numeric(df.get("Billed Charge", 0), errors="coerce").fillna(0)
        df["AllowedFee"] = pd.to_numeric(df.get("Fee Schedule Allowed Fee", 0), errors="coerce").fillna(0)
        df["PaymentsCollected"] = pd.to_numeric(df.get("Total Payment", 0), errors="coerce").fillna(0)

        # Expected Payments always derived from Allowed Fee
        df["ExpectedPayments"] = df["AllowedFee"]

        # Calculate Pending to be Collected
        df["Pending"] = df["ExpectedPayments"] - df["PaymentsCollected"]

        # Group by Aging Bucket
        aging_summary = (
            df.groupby("AgingBucket")
            .agg(
                Charges=("Charges", "sum"),
                AllowedFee=("AllowedFee", "sum"),
                ExpectedPayments=("ExpectedPayments", "sum"),
                PaymentsCollected=("PaymentsCollected", "sum"),
                Pending=("Pending", "sum")
            )
            .reset_index()
        )

        # Append Grand Total row
        totals = aging_summary[["Charges", "AllowedFee", "ExpectedPayments", "PaymentsCollected", "Pending"]].sum()
        total_row = pd.DataFrame({
            "AgingBucket": ["Grand Total"],
            "Charges": [totals["Charges"]],
            "AllowedFee": [totals["AllowedFee"]],
            "ExpectedPayments": [totals["ExpectedPayments"]],
            "PaymentsCollected": [totals["PaymentsCollected"]],
            "Pending": [totals["Pending"]]
        })
        aging_summary_full = pd.concat([aging_summary, total_row], ignore_index=True)

        # Display Table
        st.subheader("AR Aging Summary Table")
        st.dataframe(aging_summary_full, width="stretch")

        # Pie Chart: Pending Distribution
        chart_df = aging_summary_full[aging_summary_full["AgingBucket"] != "Grand Total"]
        if not chart_df.empty:
            fig = px.pie(
                chart_df,
                values="Pending",
                names="AgingBucket",
                title="Pending to be Collected by Aging Bucket",
                hole=0.4
            )
            st.plotly_chart(fig, width="stretch")
                
# 4) Charges, Payments & Adjustments
st.header('CHARGES, PAYMENTS, & ADJUSTMENTS')
with st.expander('Monthly transaction summary (table only)'):
    if date123_col is None:
        st.warning('123.07 Date column not detected in the 123 file; monthly table cannot be produced without a transaction date.')
    else:
        df123[date123_col] = pd.to_datetime(df123[date123_col], errors='coerce')
        df123['Month'] = df123[date123_col].dt.to_period('M').astype(str)

        monthly_summary = (df123.groupby('Month')
                           .agg(BILLED_CHARGES=('Billed Charges', 'sum'),
                                PATIENT_PAYMENTS=('Patient Payments', 'sum'),
                                PAYER_PAYMENTS=('Payer Payments', 'sum'),
                                CONTRACTUAL_ADJUSTMENTS=('Contractual Adjustments', 'sum'))
                           .reset_index())

        try:
            monthly_summary['TRANSACTION MONTH'] = pd.to_datetime(monthly_summary['Month']).dt.strftime('%b %Y')
        except Exception:
            monthly_summary['TRANSACTION MONTH'] = monthly_summary['Month']

        monthly_summary = monthly_summary[['TRANSACTION MONTH','BILLED_CHARGES','PATIENT_PAYMENTS','PAYER_PAYMENTS','CONTRACTUAL_ADJUSTMENTS']]

        totals = monthly_summary[['BILLED_CHARGES','PATIENT_PAYMENTS','PAYER_PAYMENTS','CONTRACTUAL_ADJUSTMENTS']].sum()
        total_row = pd.DataFrame({
            'TRANSACTION MONTH': ['Grand Total'],
            'BILLED_CHARGES': [totals['BILLED_CHARGES']],
            'PATIENT_PAYMENTS': [totals['PATIENT_PAYMENTS']],
            'PAYER_PAYMENTS': [totals['PAYER_PAYMENTS']],
            'CONTRACTUAL_ADJUSTMENTS': [totals['CONTRACTUAL_ADJUSTMENTS']]
        })
        monthly_summary_full = pd.concat([monthly_summary, total_row], ignore_index=True)

        display_df = monthly_summary_full.copy()
        def fmt_currency_col(col):
            display_df[col] = display_df[col].apply(lambda x: "${:,.0f}".format(x) if pd.notna(x) else "$0")
        for c in ['BILLED_CHARGES','PATIENT_PAYMENTS','PAYER_PAYMENTS','CONTRACTUAL_ADJUSTMENTS']:
            fmt_currency_col(c)
        st.table(display_df)

# 5) Payments by Payer
st.header('PAYMENTS BY PAYER')
with st.expander('Payments received by payer (sums of Payer Payment across line items)'):
    li = line_items.copy()
    li = li[~li['Rendering Provider'].str.lower().str.strip().eq(EXCLUDE_PROVIDER)]
    li['Payer Payment'] = pd.to_numeric(li.get('Payer Payment', 0), errors='coerce').fillna(0)

    payments_by_payer = li.groupby('Primary Payer')['Payer Payment'].sum().reset_index()

    minor_threshold_amount = payments_by_payer['Payer Payment'].quantile(0.10)
    if pd.isna(minor_threshold_amount) or minor_threshold_amount <= 0:
        minor_threshold_amount = 1.0

    major_payments = payments_by_payer[payments_by_payer['Payer Payment'] >= minor_threshold_amount].copy()
    minor_payments = payments_by_payer[payments_by_payer['Payer Payment'] < minor_threshold_amount].copy()
    if not minor_payments.empty:
        other_sum = minor_payments['Payer Payment'].sum()
        major_payments = pd.concat([major_payments, pd.DataFrame({'Primary Payer':['Other minor payers'], 'Payer Payment':[other_sum]})], ignore_index=True)

    payments_by_payer_final = major_payments.sort_values('Payer Payment', ascending=False).reset_index(drop=True)
    st.dataframe(payments_by_payer_final)

    if not payments_by_payer_final.empty:
        fig = px.pie(payments_by_payer_final.head(20), values='Payer Payment', names='Primary Payer', title='Payments by Payer (sum of line items)')
        st.plotly_chart(fig, width="stretch")

# ---------------------- Unposted Payments & Denials + ERA ----------------------
st.header('UNPOSTED PAYMENTS')
with st.expander('Unposted payments (123.07 & ERA) and denials summary'):
   
    # ------------------ Unposted 123.07 ------------------
    unposted = df123[df123.get('Posting Status','').astype(str).str.contains('unpost', case=False, na=False)] if 'Posting Status' in df123.columns else pd.DataFrame()
    if not unposted.empty:
        st.dataframe(unposted, width="stretch")  # use width="stretch" instead of deprecated use_container_width

    # ------------------ ERA ------------------
    if file_era is not None:
        df_era = load_file(file_era)
    needed_cols = ['Payer','Method','Dated','Trace','Amount']
    era = df_era[needed_cols].copy()
    era = era.rename(columns={
        'Trace':'CHECK/EFT #',
        'Dated':'DATE',
        'Method':'METHOD',
        'Payer':'PAYER',
        'Amount':'AMOUNT'
    })

    # Fix types
    era['CHECK/EFT #'] = era['CHECK/EFT #'].astype(str)  # ensure string
    if 'DATE' in era.columns:
        era['DATE'] = pd.to_datetime(era['DATE'], errors='coerce').dt.strftime('%Y-%m-%d')
    era['AMOUNT'] = pd.to_numeric(era['AMOUNT'], errors='coerce').fillna(0)

    # Sort and add totals
    era = era.sort_values('AMOUNT', ascending=False)
    total_amt = era['AMOUNT'].sum()
    total_row = pd.DataFrame({
        'PAYER': ['Grand Total'],
        'METHOD': [''],
        'DATE': [''],
        'CHECK/EFT #': [''],  # string
        'AMOUNT': [total_amt]
    })
    era_full = pd.concat([era, total_row], ignore_index=True)
    st.markdown("**ERA Payments (sorted by Amount)**")
    st.dataframe(era_full, width="stretch")

    # ------------------ Denials ------------------
    den = claims.copy()
    den['is_denied'] = den.get('Claim Status Group Name','').astype(str).str.contains('den', case=False, na=False)
    denials = den[den['is_denied']]
    if not denials.empty:
        den_summary = (
            denials.groupby(['Claim Status Group Name'], observed=False)  # add observed=False to silence FutureWarning
                   .agg(Count=('Claim No','nunique'), ARBalance=('Balance','sum'))
                   .reset_index()
                   .sort_values('Count', ascending=False)
        )
        st.dataframe(den_summary, width="stretch")

# ---------------------- EXPORT results ----------------------
if enable_export:
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        pt_full.reset_index().to_excel(writer, sheet_name='Provider_Visits', index=False)
        if file_era is not None:
            era_full.to_excel(writer, sheet_name='ERA', index=False)
        line_items.to_excel(writer, sheet_name='raw_371_filtered', index=False)
        df123.to_excel(writer, sheet_name='raw_123', index=False)
    output.seek(0)
    st.download_button('Download KPI workbook (xlsx)', data=output, file_name='relief_weekly_kpis_final.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

st.markdown('---')
st.caption('Generated by Relief Urgent Care KPI Streamlit app')
