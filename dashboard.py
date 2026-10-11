import streamlit as st
import pandas as pd
import json
from pathlib import Path
import requests
import sys

# Configure Page
st.set_page_config(page_title="Autonomous DQ & AI Incident Platform", layout="wide", page_icon="🛡️")

# Project Root
PROJECT_ROOT = Path(__file__).resolve().parent
METADATA_DIR = PROJECT_ROOT / "metadata"

st.title("🛡️ Autonomous Data Quality & AI Incident Platform")

# Sidebar
st.sidebar.header("Navigation")
page = st.sidebar.radio("Go to", ["Dashboard", "Incidents", "Pipeline Runner", "Audit Trail"])

# Helper to load data
def load_jsonl_as_df(file_path):
    if not file_path.exists():
        return pd.DataFrame()
    records = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return pd.DataFrame(records)

if page == "Dashboard":
    st.header("Overview")
    # Metric placeholders
    col1, col2, col3, col4 = st.columns(4)
    incidents_df = load_jsonl_as_df(METADATA_DIR / "incidents.jsonl")
    runs_df = load_jsonl_as_df(METADATA_DIR / "runs.jsonl")

    if not incidents_df.empty:
        col1.metric("Total Incidents", len(incidents_df))
        col2.metric("Open Incidents", len(incidents_df[incidents_df['status'] == 'OPEN']))

    col4.metric("Total Pipeline Runs", len(runs_df))

elif page == "Incidents":
    st.header("Incidents & Investigation")
    if not incidents_df.empty:
        selected_incident = st.selectbox("Select Incident", incidents_df['incident_id'].tolist())
        incident = incidents_df[incidents_df['incident_id'] == selected_incident].iloc[0]
        st.write(f"Status: {incident['status']}")

        if st.button("Run AI Investigation"):
            with st.spinner("Analyzing incident..."):
                # Simulating calling API or importing investigator
                st.success("Investigation Result:")
                st.json(incident.get('failures', {}))

elif page == "Pipeline Runner":
    st.header("Pipeline Runner")
    if st.button("Run Day 1 Pipeline (Baseline Clean)"):
        st.write("Running...")
    if st.button("Run Day 2 Pipeline (DQ Failures)"):
        st.write("Running...")

elif page == "Audit Trail":
    st.header("Audit Trail")
    audit_df = load_jsonl_as_df(METADATA_DIR / "audit.jsonl")
    st.table(audit_df)

