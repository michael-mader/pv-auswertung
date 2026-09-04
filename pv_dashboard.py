import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import datetime
from pymongo import MongoClient, UpdateOne

st.set_page_config(page_title="PV & Stromverbrauch Dashboard", layout="wide")
st.title("☀️ Interaktives PV & Stromverbrauch Dashboard (MongoDB)")

# --- MongoDB Verbindung aufbauen ---
@st.cache_resource
def init_connection():
    return MongoClient(st.secrets["mongo"]["uri"])

client = init_connection()
db = client["pv_dashboard_db"]
collection = db["tageswerte"]
settings_collection = db["settings"]

# ==========================================
# SEITENLEISTE: DATEN UPLOAD & IMPORT
# ==========================================
st.sidebar.header("Daten Upload")
file_smiles = st.sidebar.file_uploader("S-Miles Cloud Export (CSV)", type=['csv'])
file_everhome = st.sidebar.file_uploader("Everhome Export (CSV)", type=['csv'])

if file_smiles or file_everhome:
    if st.sidebar.button("⬇️ Daten in Datenbank importieren"):
        with st.spinner("Daten werden verarbeitet und in MongoDB gespeichert..."):
            try:
                upload_dict = {}

                # 1. S-Miles verarbeiten
                if file_smiles:
                    file_smiles.seek(0)
                    df_smiles = pd.read_csv(file_smiles, sep=None, engine='python')
                    df_smiles = df_smiles.iloc[:, [0, 1]]
                    df_smiles.columns = ['Datum', 'Ertrag_Wh']
                    df_smiles['Datum'] = pd.to_datetime(df_smiles['Datum'], errors='coerce').dt.date
                    
                    for _, row in df_smiles.dropna(subset=['Datum']).iterrows():
                        d_str = row['Datum'].strftime('%Y-%m-%d')
                        val = row['Ertrag_Wh']
                        if pd.notna(val):
                            if d_str not in upload_dict:
                                upload_dict[d_str] = {}
                            upload_dict[d_str]['PV_Erzeugung_Wh'] = float(val)

                # 2. Everhome verarbeiten
                if file_everhome:
                    file_everhome.seek(0)
                    df_everhome = pd.read_csv(file_everhome, sep=None, engine='python')
                    
                    col_bezug = next((c for c in df_everhome.columns if 'Differenz Bezug' in c), [c for c in df_everhome.columns if 'Bezug' in c][0])
                    col_einspeisung = next((c for c in df_everhome.columns if 'Differenz Einspeisung' in c), [c for c in df_everhome.columns if 'Einspeisung' in c][0])

                    df_everhome['Datetime'] = pd.to_datetime(df_everhome['Datum'] + ' ' + df_everhome['Uhrzeit'], format='%d.%m.%Y %H:%M:%S', errors='coerce')
                    df_everhome['Datum'] = df_everhome['Datetime'].dt.date

                    daily_everhome = df_everhome.groupby('Datum').agg({
                        col_bezug: 'sum',
                        col_einspeisung: 'sum'
                    }).reset_index()

                    for _, row in daily_everhome.dropna(subset=['Datum']).iterrows():
                        d_str = row['Datum'].strftime('%Y-%m-%d')
                        b_val = row[col_bezug]
                        e_val = row[col_einspeisung]
                        
                        if d_str not in upload_dict:
                            upload_dict[d_str] = {}
                        if pd.notna(b_val):
                            upload_dict[d_str]['Netzbezug_Wh'] = float(b_val)
                        if pd.notna(e_val):
                            upload_dict[d_str]['Einspeisung_Wh'] = float(e_val)

                # 3. In MongoDB schreiben (Batch-Update)
                date_keys = list(upload_dict.keys())
                
                if date_keys:
                    existing_docs_cursor = collection.find({"_id": {"$in": date_keys}})
                    existing_docs = {doc["_id"]: doc for doc in existing_docs_cursor}

                    bulk_operations = []

                    for d_str, fields in upload_dict.items():
                        existing_doc = existing_docs.get(d_str, {})
                        update_data = {}
                        
                        for field, new_val in fields.items():
                            if new_val is not None and new_val != 0:
                                update_data[field] = new_val
                            elif field not in existing_doc or existing_doc.get(field) is None:
                                update_data[field] = new_val

                        if update_data:
                            bulk_operations.append(
                                UpdateOne(
                                    {"_id": d_str},
                                    {"$set": update_data},
                                    upsert=True
                                )
                            )

                    if bulk_operations:
                        collection.bulk_write(bulk_operations)
                        
                st.sidebar.success("Daten extrem schnell in MongoDB aktualisiert!")

            except Exception as e:
                st.sidebar.error(f"Fehler beim Importieren: {e}")

# ==========================================
# DATEN AUS MONGODB LADEN
# ==========================================
cursor = collection.find({})
data_list = []
for doc in cursor:
    row = {'Datum': doc['_id']}
    row['PV_Erzeugung_Wh'] = doc.get('PV_Erzeugung_Wh', 0)
    row['Netzbezug_Wh'] = doc.get('Netzbezug_Wh', 0)
    row['Einspeisung_Wh'] = doc.get('Einspeisung_Wh', 0)
    data_list.append(row)

if not data_list:
    st.info("👈 Bislang sind keine Daten in der Datenbank vorhanden. Bitte lade CSV-Dateien hoch und klicke auf 'Importieren'.")
else:
    # Datenaufbereitung
    merged = pd.DataFrame(data_list)
    merged['Datum'] = pd.to_datetime(merged['Datum'])
    merged = merged.sort_values('Datum').reset_index(drop=True)

    merged['Eigenverbrauch_Wh'] = merged.apply(lambda row: max(0, row['PV_Erzeugung_Wh'] - row['Einspeisung_Wh']), axis=1)
    merged['Gesamtverbrauch_Wh'] = merged['Netzbezug_Wh'] + merged['Eigenverbrauch_Wh']
    merged['EVQ_%'] = np.where(merged['PV_Erzeugung_Wh'] > 0, (merged['Eigenverbrauch_Wh'] / merged['PV_Erzeugung_Wh']) * 100, 0)
    merged['Autarkie_%'] = np.where(merged['Gesamtverbrauch_Wh'] > 0, (merged['Eigenverbrauch_Wh'] / merged['Gesamtverbrauch_Wh']) * 100, 0)

    # ==========================================
    # SEITENLEISTE: ZEITRAUM FILTER
    # ==========================================
    st.sidebar.markdown("---")
    st.sidebar.header("🗓️ Zeitraum Filter")
    
    min_date = merged['Datum'].min().date()
    max_date = merged['Datum'].max().date()

    if "start_date" not in st.session_state:
        st.session_state.start_date = min_date
    if "end_date" not in st.session_state:
        st.session_state.end_date = max_date

    auswahl_optionen = [
        "Manuell (Kalender nutzen)", 
        "Gestern",
        "Letzte 7 Tage", 
        "Letzte 14 Tage", 
        "Letzte 30 Tage", 
        "Aktueller Monat",
        "Letzter Monat",
        "Letzte 3 Monate",
        "Gesamter Zeitraum"
    ]
    
    quick_select = st.sidebar.selectbox("Schnellauswahl", auswahl_optionen, index=4)

    if quick_select == "Gestern":
        gestern = max_date - datetime.timedelta(days=1)
        st.session_state.start_date = max(min_date, gestern)
        st.session_state.end_date = max(min_date, gestern) 
    elif quick_select == "Letzte 7 Tage":
        st.session_state.start_date = max(min_date, max_date - datetime.timedelta(days=6))
        st.session_state.end_date = max_date
    elif quick_select == "Letzte 14 Tage":
        st.session_state.start_date = max(min_date, max_date - datetime.timedelta(days=13))
        st.session_state.end_date = max_date
    elif quick_select == "Letzte 30 Tage":
        st.session_state.start_date = max(min_date, max_date - datetime.timedelta(days=29))
        st.session_state.end_date = max_date
    elif quick_select == "Aktueller Monat":
        start_of_month = max_date.replace(day=1)
        st.session_state.start_date = max(min_date, start_of_month)
        st.session_state.end_date = max_date
    elif quick_select == "Letzter Monat":
        end_of_last_month = max_date.replace(day=1) - datetime.timedelta(days=1)
        start_of_last_month = end_of_last_month.replace(day=1)
        st.session_state.start_date = max(min_date, start_of_last_month)
        st.session_state.end_date = min(max_date, end_of_last_month)
    elif quick_select == "Letzte 3 Monate":
        start_3_months = (pd.to_datetime(max_date) - pd.DateOffset(months=3)).date()
        st.session_state.start_date = max(min_date, start_3_months)
        st.session_state.end_date = max_date
    elif quick_select == "Gesamter Zeitraum":
        st.session_state.start_date = min_date
        st.session_state.end_date = max_date

    date_selection = st.sidebar.date_input(
        "Datum auswählen",
        value=(st.session_state.start_date, st.session_state.end_date),
        min_value=min_date,
        max_value=max_date,
        disabled=(quick_select != "Manuell (Kalender nutzen)") 
    )

    if len(date_selection) == 2:
        start_date, end_date = date_selection
        if quick_select == "Manuell (Kalender nutzen)":
            st.session_state.start_date = start_date
            st.session_state.end_date = end_date
    else:
        start_date = date_selection[0]
        end_date = date_selection[0]

    mask = (merged['Datum'].dt.date >= start_date) & (merged['Datum'].dt.date <= end_date)
    filtered_df = merged.loc[mask]

    # ==========================================
    # SEITENLEISTE: FINANZEN 
    # ==========================================
    st.sidebar.markdown("---")
    st.sidebar.header("⚙️ Finanzielle Einstellungen")
    
    settings_doc = settings_collection.find_one({"_id": "app_finanzen"}) or {}
    saved_strompreis = settings_doc.get("strompreis_ct", 28.32)
    saved_invest = settings_doc.get("investitionskosten", 800.0)
    
    strompreis_ct = st.sidebar.number_input(
        "Strompreis (ct/kWh)", min_value=0.0, max_value=100.0, value=float(saved_strompreis), step=0.01, format="%.2f"
    )
    
    investitionskosten = st.sidebar.number_input(
        "Anschaffungskosten Anlage (€)", min_value=0.0, value=float(saved_invest), step=50.0, format="%.2f"
    )
    
    if strompreis_ct != saved_strompreis or investitionskosten != saved_invest:
        settings_collection.update_one(
            {"_id": "app_finanzen"},
            {"$set": {
                "strompreis_ct": strompreis_ct,
                "investitionskosten": investitionskosten
            }},
            upsert=True
        )

    # ==========================================
    # HAUPTBEREICH: DASHBOARD ANZEIGEN
    # ==========================================
    if filtered_df.empty:
        st.warning("Für den gewählten Zeitraum sind keine Daten in der Datenbank vorhanden.")
    else:
        total_pv = filtered_df['PV_Erzeugung_Wh'].sum()
        total_bezug = filtered_df['Netzbezug_Wh'].sum()
        total_einspeisung = filtered_df['Einspeisung_Wh'].sum()
        total_eigen = filtered_df['Eigenverbrauch_Wh'].sum()
        total_verbrauch = filtered_df['Gesamtverbrauch_Wh'].sum()
        
        evq = (total_eigen / total_pv * 100) if total_pv > 0 else 0
        autarkie = (total_eigen / total_verbrauch * 100) if total_verbrauch > 0 else 0
        ersparnis_euro = (total_eigen / 1000) * (strompreis_ct / 100)

        pv_mean = filtered_df['PV_Erzeugung_Wh'].mean() / 1000
        pv_max = filtered_df['PV_Erzeugung_Wh'].max() / 1000
        
        active_pv_days = filtered_df[filtered_df['PV_Erzeugung_Wh'] > 10]
        pv_min = (active_pv_days['PV_Erzeugung_Wh'].min() / 1000) if not active_pv_days.empty else 0

        st.header(f"📊 Auswertung ({start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')})")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("PV-Erzeugung (Gesamt)", f"{total_pv/1000:.2f} kWh")
        col2.metric("Tatsächlicher Netzbezug", f"{total_bezug/1000:.2f} kWh", f"-{total_eigen/1000:.2f} kWh (Ersparnis)", delta_color="inverse")
        col3.metric("Eigenverbrauchsquote", f"{evq:.1f} %")
        col4.metric("Autarkiegrad", f"{autarkie:.1f} %")
        
        st.markdown("### ☀️ PV-Leistung & Ersparnis")
        col_pv1, col_pv2, col_pv3, col_pv4 = st.columns(4)
        col_pv1.metric("Ø Tagesertrag", f"{pv_mean:.2f} kWh")
        col_pv2.metric("Maximaler Tagesertrag", f"{pv_max:.2f} kWh")
        col_pv3.metric("Minimaler Tagesertrag (aktiv)", f"{pv_min:.2f} kWh")
        col_pv4.metric("Ersparnis im Zeitraum", f"{ersparnis_euro:.2f} €")

        st.markdown("### 🔮 Jahres-Prognose (basierend auf Zeitraum)")
        avg_daily_verbrauch = filtered_df['Gesamtverbrauch_Wh'].mean() / 1000
        avg_daily_eigen = filtered_df['Eigenverbrauch_Wh'].mean() / 1000
        avg_daily_ersparnis = avg_daily_eigen * (strompreis_ct / 100)
        
        forecast_verbrauch = avg_daily_verbrauch * 365
        forecast_ersparnis = avg_daily_ersparnis * 365
        
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        col_f1.metric("Ø Stromverbrauch / Tag", f"{avg_daily_verbrauch:.2f} kWh")
        col_f2.metric("Prognose Verbrauch / Jahr", f"{forecast_verbrauch:.0f} kWh")
        col_f3.metric("Ø PV-Ersparnis / Tag", f"{avg_daily_ersparnis:.2f} €")
        col_f4.metric("Prognose Ersparnis / Jahr", f"{forecast_ersparnis:.2f} €")

        # ==========================================
        # CHART MIT AGGREGATION & LABEL-AUSWAHL
        # ==========================================
        st.markdown("---")
        st.header("📈 Verlauf")
        
        col_agg, col_label = st.columns(2)
        with col_agg:
            agg_option = st.radio("Ansicht aggregieren:", ["Täglich", "Wöchentlich", "Monatlich"], horizontal=True)
        with col_label:
            label_option = st.radio("Beschriftung im Diagramm:", ["Eigenverbrauchsquote (EVQ)", "Autarkiegrad"], horizontal=True)
        
        chart_df = filtered_df.copy()
        
        if agg_option != "Täglich":
            chart_df.set_index('Datum', inplace=True)
            if agg_option == "Wöchentlich":
                chart_df = chart_df.resample('W-MON').sum().reset_index()
            elif agg_option == "Monatlich":
                chart_df = chart_df.resample('ME').sum().reset_index()
            
            # Quoten für aggregierte Zeiträume neu berechnen
            chart_df['Gesamtverbrauch_Wh'] = chart_df['Netzbezug_Wh'] + chart_df['Eigenverbrauch_Wh']
            chart_df['EVQ_%'] = np.where(chart_df['PV_Erzeugung_Wh'] > 0, (chart_df['Eigenverbrauch_Wh'] / chart_df['PV_Erzeugung_Wh']) * 100, 0)
            chart_df['Autarkie_%'] = np.where(chart_df['Gesamtverbrauch_Wh'] > 0, (chart_df['Eigenverbrauch_Wh'] / chart_df['Gesamtverbrauch_Wh']) * 100, 0)

        fig = go.Figure()

        # 1. Positiver Balken: Eigenverbrauch (Grün)
        fig.add_trace(go.Bar(
            x=chart_df['Datum'],
            y=chart_df['Eigenverbrauch_Wh']/1000,
            name='Eigenverbrauch (kWh)',
            marker_color='green'
        ))

        # 2. Positiver Balken (darauf gestapelt): Netzbezug (Orange)
        fig.add_trace(go.Bar(
            x=chart_df['Datum'],
            y=chart_df['Netzbezug_Wh']/1000,
            name='Netzbezug (kWh)',
            marker_color='orange'
        ))
        
        # 3. Negativer Balken (nach unten gestapelt): Einspeisung (Gold)
        fig.add_trace(go.Bar(
            x=chart_df['Datum'],
            y=-chart_df['Einspeisung_Wh']/1000,
            name='Einspeisung (kWh)',
            marker_color='gold',
            customdata=chart_df['Einspeisung_Wh']/1000,
            hovertemplate='%{customdata:.2f} kWh' 
        ))

        # 4. Linie: PV Erzeugung (Blau)
        fig.add_trace(go.Scatter(
            x=chart_df['Datum'],
            y=chart_df['PV_Erzeugung_Wh']/1000,
            name='PV Erzeugung (kWh)',
            mode='lines+markers',
            line=dict(color='blue', width=2),
            marker=dict(size=8)
        ))

        # 5. Unsichtbarer Trace nur für den Hover-Tooltip: Gesamtverbrauch
        fig.add_trace(go.Scatter(
            x=chart_df['Datum'],
            y=chart_df['Gesamtverbrauch_Wh']/1000,
            name='Gesamtverbrauch',
            mode='lines',
            line=dict(color='rgba(0,0,0,0)'),
            showlegend=False,
            hovertemplate='%{y:.2f} kWh'
        ))

        y_max = np.maximum(
            (chart_df['Eigenverbrauch_Wh'] + chart_df['Netzbezug_Wh']) / 1000,
            chart_df['PV_Erzeugung_Wh'] / 1000
        )
        
        if label_option == "Eigenverbrauchsquote (EVQ)":
            text_labels = chart_df['EVQ_%'].apply(lambda x: f"<b>{x:.0f} %</b>" if x > 0 else "")
        else:
            text_labels = chart_df['Autarkie_%'].apply(lambda x: f"<b>{x:.0f} %</b>" if x > 0 else "")

        # Labels oben auf den positiven Balken
        fig.add_trace(go.Scatter(
            x=chart_df['Datum'],
            y=y_max,
            mode='text',
            text=text_labels,
            textposition="top center",
            showlegend=False,
            hoverinfo='skip'
        ))

        # Y-Achsen Skalierung berechnen
        max_total = chart_df['Gesamtverbrauch_Wh'].max()
        max_pv = chart_df['PV_Erzeugung_Wh'].max()
        graph_max_y = max(max_total, max_pv) / 1000 if not chart_df.empty else 1
        
        max_einspeisung = chart_df['Einspeisung_Wh'].max() / 1000 if not chart_df.empty else 0
        graph_min_y = -max_einspeisung * 1.1 if max_einspeisung > 0 else 0
        
        fig.update_layout(
            barmode='relative', 
            yaxis_title='Energie (kWh)',
            yaxis=dict(range=[graph_min_y, (graph_max_y * 1.25) if graph_max_y > 0 else 1]),
            hovermode='x unified',
            legend=dict(
                orientation="h", 
                yanchor="bottom", 
                y=1.02, 
                xanchor="right", 
                x=1
            ),
            margin=dict(l=0, r=0, t=40, b=0)
        )

        st.plotly_chart(fig, use_container_width=True)

        with st.expander("Tabelle mit Daten anzeigen"):
            display_df = chart_df[['Datum', 'PV_Erzeugung_Wh', 'Netzbezug_Wh', 'Einspeisung_Wh', 'Eigenverbrauch_Wh', 'EVQ_%', 'Autarkie_%']].copy()
            cols_to_convert = ['PV_Erzeugung_Wh', 'Netzbezug_Wh', 'Einspeisung_Wh', 'Eigenverbrauch_Wh']
            display_df[cols_to_convert] = display_df[cols_to_convert].astype(float) / 1000.0
            display_df.rename(columns=lambda x: x.replace('_Wh', ' (kWh)'), inplace=True)
            display_df['Datum'] = display_df['Datum'].dt.strftime('%d.%m.%Y')
            st.dataframe(display_df, use_container_width=True)


        # ==========================================
        # NEU: LANGZEIT-VERGLEICH (MoM & YoY)
        # ==========================================
        st.markdown("---")
        st.header("📅 Langzeit-Vergleich (Monate & Jahre)")
        
        # Datengrundlage ist das gesamte Datenset (merged), nicht das gefilterte
        df_monthly = merged.copy()
        df_monthly['Jahr'] = df_monthly['Datum'].dt.year
        df_monthly['Monat'] = df_monthly['Datum'].dt.month
        
        monthly_agg = df_monthly.groupby(['Jahr', 'Monat']).agg({
            'PV_Erzeugung_Wh': 'sum',
            'Netzbezug_Wh': 'sum',
            'Eigenverbrauch_Wh': 'sum',
            'Gesamtverbrauch_Wh': 'sum',
            'Einspeisung_Wh': 'sum'
        }).reset_index()
        
        month_names = {1:"Januar", 2:"Februar", 3:"März", 4:"April", 5:"Mai", 6:"Juni", 
                       7:"Juli", 8:"August", 9:"September", 10:"Oktober", 11:"November", 12:"Dezember"}
        
        # Generiere die Auswahlmöglichkeiten (z.B. "August 2026")
        available_months = monthly_agg.apply(lambda row: f"{month_names[int(row['Monat'])]} {int(row['Jahr'])}", axis=1).tolist()
        
        col_sel1, col_sel2 = st.columns([1, 3])
        with col_sel1:
            selected_month_str = st.selectbox("Vergleichsmonat wählen:", available_months, index=len(available_months)-1)
        
        if selected_month_str:
            sel_m_name, sel_y_str = selected_month_str.split(" ")
            sel_y = int(sel_y_str)
            sel_m = list(month_names.keys())[list(month_names.values()).index(sel_m_name)]
            
            curr_m_data = monthly_agg[(monthly_agg['Jahr'] == sel_y) & (monthly_agg['Monat'] == sel_m)]
            
            # Daten für Vormonat (MoM) berechnen
            prev_m = sel_m - 1 if sel_m > 1 else 12
            prev_m_y = sel_y if sel_m > 1 else sel_y - 1
            mom_data = monthly_agg[(monthly_agg['Jahr'] == prev_m_y) & (monthly_agg['Monat'] == prev_m)]
            
            # Daten für Vorjahresmonat (YoY) berechnen
            prev_y = sel_y - 1
            yoy_data = monthly_agg[(monthly_agg['Jahr'] == prev_y) & (monthly_agg['Monat'] == sel_m)]
            
            # Hilfsfunktionen
            def get_delta_pct(curr, prev):
                if prev is None or prev.empty or curr is None or curr.empty:
                    return None
                val_c = curr.iloc[0]
                val_p = prev.iloc[0]
                if val_p == 0: return None
                return ((val_c - val_p) / val_p) * 100

            def get_val(df_row, col):
                return df_row[col].iloc[0] / 1000 if not df_row.empty else 0

            # Werte extrahieren
            pv_curr = get_val(curr_m_data, 'PV_Erzeugung_Wh')
            pv_mom_pct = get_delta_pct(curr_m_data['PV_Erzeugung_Wh'], mom_data['PV_Erzeugung_Wh'])
            pv_yoy_pct = get_delta_pct(curr_m_data['PV_Erzeugung_Wh'], yoy_data['PV_Erzeugung_Wh'])
            
            netz_curr = get_val(curr_m_data, 'Netzbezug_Wh')
            netz_mom_pct = get_delta_pct(curr_m_data['Netzbezug_Wh'], mom_data['Netzbezug_Wh'])
            netz_yoy_pct = get_delta_pct(curr_m_data['Netzbezug_Wh'], yoy_data['Netzbezug_Wh'])

            eigen_curr = get_val(curr_m_data, 'Eigenverbrauch_Wh')
            eigen_mom_pct = get_delta_pct(curr_m_data['Eigenverbrauch_Wh'], mom_data['Eigenverbrauch_Wh'])
            eigen_yoy_pct = get_delta_pct(curr_m_data['Eigenverbrauch_Wh'], yoy_data['Eigenverbrauch_Wh'])
            
            # Darstellung Metriken
            st.markdown(f"#### Vergleich zum Vormonat (MoM) — {month_names[prev_m]} {prev_m_y}")
            c1, c2, c3 = st.columns(3)
            c1.metric("PV-Erzeugung", f"{pv_curr:.1f} kWh", f"{pv_mom_pct:.1f} %" if pv_mom_pct is not None else None)
            c2.metric("Netzbezug", f"{netz_curr:.1f} kWh", f"{netz_mom_pct:.1f} %" if netz_mom_pct is not None else None, delta_color="inverse")
            c3.metric("Eigenverbrauch", f"{eigen_curr:.1f} kWh", f"{eigen_mom_pct:.1f} %" if eigen_mom_pct is not None else None)
            
            st.markdown(f"#### Vergleich zum Vorjahresmonat (YoY) — {month_names[sel_m]} {prev_y}")
            c4, c5, c6 = st.columns(3)
            c4.metric("PV-Erzeugung", f"{pv_curr:.1f} kWh", f"{pv_yoy_pct:.1f} %" if pv_yoy_pct is not None else None)
            c5.metric("Netzbezug", f"{netz_curr:.1f} kWh", f"{netz_yoy_pct:.1f} %" if netz_yoy_pct is not None else None, delta_color="inverse")
            c6.metric("Eigenverbrauch", f"{eigen_curr:.1f} kWh", f"{eigen_yoy_pct:.1f} %" if eigen_yoy_pct is not None else None)
            
            # Chart für YoY (Alle Jahre nebeneinander)
            st.markdown("<br>#### Jahresverlauf im direkten Vergleich", unsafe_allow_html=True)
            compare_metric = st.radio("Metrik für das Diagramm wählen:", ["PV-Erzeugung", "Netzbezug", "Eigenverbrauch", "Gesamtverbrauch"], horizontal=True)
            
            metric_map = {
                "PV-Erzeugung": "PV_Erzeugung_Wh",
                "Netzbezug": "Netzbezug_Wh",
                "Eigenverbrauch": "Eigenverbrauch_Wh",
                "Gesamtverbrauch": "Gesamtverbrauch_Wh"
            }
            y_col = metric_map[compare_metric]
            
            fig_yoy = go.Figure()
            jahre = sorted(monthly_agg['Jahr'].unique())
            colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
            
            for i, jahr in enumerate(jahre):
                df_j = monthly_agg[monthly_agg['Jahr'] == jahr].sort_values('Monat')
                # Auffüllen fehlender Monate mit 0, damit die X-Achse immer alle 12 Monate perfekt ausrichtet
                df_j_full = pd.DataFrame({'Monat': range(1, 13)})
                df_j_full = df_j_full.merge(df_j, on='Monat', how='left').fillna(0)
                
                short_month_names = {1:"Jan", 2:"Feb", 3:"Mär", 4:"Apr", 5:"Mai", 6:"Jun", 
                                     7:"Jul", 8:"Aug", 9:"Sep", 10:"Okt", 11:"Nov", 12:"Dez"}
                
                fig_yoy.add_trace(go.Bar(
                    x=[short_month_names[m] for m in df_j_full['Monat']],
                    y=df_j_full[y_col] / 1000,
                    name=str(jahr),
                    marker_color=colors[i % len(colors)]
                ))
                
            fig_yoy.update_layout(
                barmode='group',
                yaxis_title=f"{compare_metric} (kWh)",
                hovermode='x unified',
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=0, r=0, t=40, b=0)
            )
            st.plotly_chart(fig_yoy, use_container_width=True)


        # ==========================================
        # AMORTISATION GANZ UNTEN
        # ==========================================
        st.markdown("---")
        st.header("💰 Amortisation / Return on Investment")
        
        lifetime_eigen_wh = merged['Eigenverbrauch_Wh'].sum()
        lifetime_ersparnis = (lifetime_eigen_wh / 1000) * (strompreis_ct / 100)
        
        if investitionskosten > 0:
            roi_percent = (lifetime_ersparnis / investitionskosten) * 100
            
            col_r1, col_r2, col_r3 = st.columns(3)
            col_r1.metric("Anschaffungskosten", f"{investitionskosten:.2f} €")
            col_r2.metric("Historische Gesamtersparnis", f"{lifetime_ersparnis:.2f} €")
            col_r3.metric("Amortisiert", f"{roi_percent:.1f} %")
            
            st.progress(min(roi_percent / 100.0, 1.0))
            
            if roi_percent >= 100:
                st.success(f"🎉 Glückwunsch! Deine Anlage hat sich komplett amortisiert und bereits **{lifetime_ersparnis - investitionskosten:.2f} €** reinen Gewinn erwirtschaftet!")
            else:
                rest = investitionskosten - lifetime_ersparnis
                st.info(f"Es fehlen noch **{rest:.2f} €**, bis sich die Anlage vollständig bezahlt gemacht hat.")
        else:
            st.info("Trage links in der Seitenleiste deine Anschaffungskosten (> 0 €) ein, um den Fortschritt zu sehen.")

        # ==========================================
        # NEU: SPEICHER-SIMULATOR
        # ==========================================
        st.markdown("---")
        st.header("🔋 Batterie-Speicher Simulator (AC)")
        st.markdown("Berechnet den potenziellen Nutzen eines Speichers basierend auf den exakten Daten des oben ausgewählten Zeitraums.")
        
        col_sim1, col_sim2, col_sim3 = st.columns(3)
        with col_sim1:
            speicher_kapazitaet_wh = st.number_input("Kapazität (Wh)", value=1600, step=100, help="Nettokapazität des Speichers in Wattstunden.")
        with col_sim2:
            speicher_preis = st.number_input("Speicher Preis (€)", value=700.0, step=50.0, help="Anschaffungskosten für den Speicher.")
        with col_sim3:
            speicher_effizienz = st.number_input("Effizienz (0.1 - 1.0)", value=0.85, min_value=0.1, max_value=1.0, step=0.05, help="Berücksichtigt Umwandlungs- und Ladeverluste (< 1.0).")
            
        st.caption("Hinweis: Das Modell nutzt eine vereinfachte Tagesbetrachtung. Es wird angenommen, dass der Speicher pro Tag den Überschuss bis zu seiner Maximalkapazität aufnehmen kann und nachts mit maximal 800W zur Deckung des Netzbezugs entladen wird. (1 Vollzyklus pro Tag)")

        # Simulator Berechnung auf Basis des ausgewählten Zeitraums (filtered_df)
        sim_df = filtered_df.copy()
        
        # 1. Speicher laden: Min(Tägliche Einspeisung, Speicherkapazität)
        sim_df['Akku_Ladung_Wh'] = sim_df['Einspeisung_Wh'].apply(lambda x: min(x, speicher_kapazitaet_wh))
        
        # 2. Speicher entladen: Min(Geladene Energie * Effizienz, Tatsächlicher Netzbezug)
        sim_df['Akku_Entladung_Wh'] = sim_df.apply(lambda row: min(row['Akku_Ladung_Wh'] * speicher_effizienz, row['Netzbezug_Wh']), axis=1)
        
        total_akku_entladung = sim_df['Akku_Entladung_Wh'].sum()
        akku_ersparnis_period = (total_akku_entladung / 1000) * (strompreis_ct / 100)
        
        days_in_period = (end_date - start_date).days + 1
        
        if days_in_period > 0:
            yearly_akku_ersparnis = (akku_ersparnis_period / days_in_period) * 365
            if yearly_akku_ersparnis > 0:
                amortization_years = speicher_preis / yearly_akku_ersparnis
            else:
                amortization_years = 0
                
            col_res1, col_res2, col_res3 = st.columns(3)
            col_res1.metric(f"Zusätzliche Ersparnis im Zeitraum ({days_in_period} Tage)", f"{akku_ersparnis_period:.2f} €", f"{total_akku_entladung/1000:.1f} kWh genutzt")
            col_res2.metric("Prognostizierte Ersparnis / Jahr", f"{yearly_akku_ersparnis:.2f} €")
            
            if amortization_years > 0:
                col_res3.metric("Amortisationsdauer (Speicher)", f"{amortization_years:.1f} Jahre")
            else:
                col_res3.metric("Amortisationsdauer (Speicher)", "Nie")
                
            # Neue theoretische Autarkie berechnen
            theoretischer_netzbezug = total_bezug - total_akku_entladung
            neue_autarkie = ((total_verbrauch - theoretischer_netzbezug) / total_verbrauch * 100) if total_verbrauch > 0 else 0
            st.info(f"💡 Mit diesem Speicher würde dein **Autarkiegrad** im ausgewählten Zeitraum von **{autarkie:.1f}%** auf **{neue_autarkie:.1f}%** steigen.")
