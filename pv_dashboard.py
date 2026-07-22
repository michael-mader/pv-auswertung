import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import datetime

st.set_page_config(page_title="PV & Stromverbrauch Dashboard", layout="wide")
st.title("☀️ Interaktives PV & Stromverbrauch Dashboard")

# Seitenleiste für die Uploads & Filter
st.sidebar.header("Daten Upload")
file_smiles = st.sidebar.file_uploader("S-Miles Cloud Export (CSV)", type=['csv'])
file_everhome = st.sidebar.file_uploader("Everhome Export (CSV)", type=['csv'])

# Konfiguration für den Strompreis in der Seitenleiste
st.sidebar.markdown("---")
st.sidebar.header("⚙️ Finanzielle Einstellungen")
strompreis_ct = st.sidebar.number_input(
    "Strompreis (ct/kWh)", 
    min_value=0.0, 
    max_value=100.0, 
    value=28.34, 
    step=0.01,
    format="%.2f"
)

if file_smiles and file_everhome:
    try:
        # --- 1. Datenaufbereitung ---
        # S-Miles Daten
        df_smiles = pd.read_csv(file_smiles)
        if ' ' in df_smiles.columns:
            df_smiles.rename(columns={' ': 'Datum'}, inplace=True)
        elif df_smiles.columns[0] != 'Datum': 
            df_smiles.rename(columns={df_smiles.columns[0]: 'Datum'}, inplace=True)
            
        df_smiles['Datum'] = pd.to_datetime(df_smiles['Datum'], errors='coerce')

        # Everhome Daten
        df_everhome = pd.read_csv(file_everhome, sep=None, engine='python')
        df_everhome['Datetime'] = pd.to_datetime(df_everhome['Datum'] + ' ' + df_everhome['Uhrzeit'], format='%d.%m.%Y %H:%M:%S', errors='coerce')
        df_everhome['Datum'] = pd.to_datetime(df_everhome['Datetime'].dt.date)

        daily_everhome = df_everhome.groupby('Datum').agg({
            'Differenz Bezug': 'sum',
            'Differenz Einspeisung': 'sum'
        }).reset_index()

        # Zusammenführen
        merged = pd.merge(daily_everhome, df_smiles, on='Datum', how='inner')

        # Werte berechnen
        merged['PV_Erzeugung_Wh'] = merged['Ertrag (Wh)']
        merged['Netzbezug_Wh'] = merged['Differenz Bezug']
        merged['Einspeisung_Wh'] = merged['Differenz Einspeisung']
        merged['Eigenverbrauch_Wh'] = merged.apply(lambda row: max(0, row['PV_Erzeugung_Wh'] - row['Einspeisung_Wh']), axis=1)
        merged['Gesamtverbrauch_Wh'] = merged['Netzbezug_Wh'] + merged['Eigenverbrauch_Wh']
        merged['EVQ_%'] = np.where(merged['PV_Erzeugung_Wh'] > 0, (merged['Eigenverbrauch_Wh'] / merged['PV_Erzeugung_Wh']) * 100, 0)

        # --- 2. Interaktiver Datumsfilter ---
        st.sidebar.header("Zeitraum Filter")
        min_date = merged['Datum'].min().date()
        max_date = merged['Datum'].max().date()

        # Session State initialisieren, damit die App sich die manuellen Werte merkt
        if "start_date" not in st.session_state:
            st.session_state.start_date = min_date
        if "end_date" not in st.session_state:
            st.session_state.end_date = max_date

        # Dropdown für die Schnellauswahl
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
        
        quick_select = st.sidebar.selectbox(
            "Schnellauswahl",
            auswahl_optionen,
            index=8 # Standardmäßig auf "Gesamter Zeitraum"
        )

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

        # Der eigentliche Kalender
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

        # DataFrame anhand des ermittelten Zeitraums filtern
        mask = (merged['Datum'].dt.date >= start_date) & (merged['Datum'].dt.date <= end_date)
        filtered_df = merged.loc[mask]

        if filtered_df.empty:
            st.warning("Für den gewählten Zeitraum sind keine übereinstimmenden Daten vorhanden.")
        else:
            # --- 3. KPIs berechnen (basierend auf filtered_df) ---
            total_pv = filtered_df['PV_Erzeugung_Wh'].sum()
            total_bezug = filtered_df['Netzbezug_Wh'].sum()
            total_einspeisung = filtered_df['Einspeisung_Wh'].sum()
            total_eigen = filtered_df['Eigenverbrauch_Wh'].sum()
            total_verbrauch = filtered_df['Gesamtverbrauch_Wh'].sum()
            
            evq = (total_eigen / total_pv * 100) if total_pv > 0 else 0
            autarkie = (total_eigen / total_verbrauch * 100) if total_verbrauch > 0 else 0

            # Finanzielle Ersparnis berechnen (Eigenverbrauch in kWh * Strompreis in Euro)
            ersparnis_euro = (total_eigen / 1000) * (strompreis_ct / 100)

            # PV-Statistiken (Tageswerte) berechnen
            pv_mean = filtered_df['PV_Erzeugung_Wh'].mean() / 1000
            pv_max = filtered_df['PV_Erzeugung_Wh'].max() / 1000
            
            active_pv_days = filtered_df[filtered_df['PV_Erzeugung_Wh'] > 0]
            pv_min = (active_pv_days['PV_Erzeugung_Wh'].min() / 1000) if not active_pv_days.empty else 0

            # --- UI: KPIs anzeigen ---
            st.header("📊 Auswertung für den gewählten Zeitraum")
            
            # Zeile 1: Die Haupt-Metriken
            col1, col2, col3, col4 = st.columns(4)
            
            col1.metric("PV-Erzeugung (Gesamt)", f"{total_pv/1000:.2f} kWh")
            col2.metric(
                label="Tatsächlicher Netzbezug", 
                value=f"{total_bezug/1000:.2f} kWh", 
                delta=f"-{total_eigen/1000:.2f} kWh (Ersparnis)", 
                delta_color="inverse"
            )
            col3.metric("Eigenverbrauchsquote", f"{evq:.1f} %")
            col4.metric("Autarkiegrad", f"{autarkie:.1f} %")
            
            # Zeile 2: Die PV-Statistiken & finanzielle Ersparnis
            st.markdown("### ☀️ PV-Leistung & Ersparnis")
            col_pv1, col_pv2, col_pv3, col_pv4 = st.columns(4)
            
            col_pv1.metric("Ø Tagesertrag", f"{pv_mean:.2f} kWh")
            col_pv2.metric("Maximaler Tagesertrag", f"{pv_max:.2f} kWh")
            col_pv3.metric("Minimaler Tagesertrag (aktiv)", f"{pv_min:.2f} kWh")
            
            # Hier ist nun die finanzielle Ersparnis als vierte Kachel platziert
            col_pv4.metric(
                label="Geldwerte Ersparnis", 
                value=f"{ersparnis_euro:.2f} €",
                help=f"Basiert auf deinem Eigenverbrauch von {total_eigen/1000:.2f} kWh multipliziert mit {strompreis_ct:.2f} ct/kWh."
            )

            # --- 4. Interaktives Diagramm (Plotly) ---
            st.header("📈 Tagesverlauf")
            
            fig = go.Figure()

            # Balken für Eigenverbrauch (unten)
            fig.add_trace(go.Bar(
                x=filtered_df['Datum'],
                y=filtered_df['Eigenverbrauch_Wh']/1000,
                name='Eigenverbrauch (kWh)',
                marker_color='green'
            ))

            # Balken für Netzbezug (oben drauf gestapelt)
            fig.add_trace(go.Bar(
                x=filtered_df['Datum'],
                y=filtered_df['Netzbezug_Wh']/1000,
                name='Netzbezug (kWh)',
                marker_color='orange'
            ))

            # Linie für PV-Erzeugung
            fig.add_trace(go.Scatter(
                x=filtered_df['Datum'],
                y=filtered_df['PV_Erzeugung_Wh']/1000,
                name='PV Erzeugung (kWh)',
                mode='lines+markers',
                line=dict(color='blue', width=2),
                marker=dict(size=8)
            ))

            y_max = np.maximum(
                (filtered_df['Eigenverbrauch_Wh'] + filtered_df['Netzbezug_Wh']) / 1000,
                filtered_df['PV_Erzeugung_Wh'] / 1000
            )
            
            text_labels = filtered_df['EVQ_%'].apply(lambda x: f"<b>{x:.0f} %</b>" if x > 0 else "")

            fig.add_trace(go.Scatter(
                x=filtered_df['Datum'],
                y=y_max,
                mode='text',
                text=text_labels,
                textposition="top center",
                showlegend=False,
                hoverinfo='skip'
            ))

            max_total = filtered_df['Gesamtverbrauch_Wh'].max()
            max_pv = filtered_df['PV_Erzeugung_Wh'].max()
            graph_max = max(max_total, max_pv) / 1000
            
            fig.update_layout(
                barmode='stack',
                yaxis_title='Energie (kWh)',
                yaxis=dict(range=[0, (graph_max * 1.25) if graph_max > 0 else 1]),
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

            # --- 5. Rohdaten anzeigen ---
            with st.expander("Tabelle mit aggregierten Tagesdaten anzeigen"):
                display_df = filtered_df[['Datum', 'PV_Erzeugung_Wh', 'Netzbezug_Wh', 'Einspeisung_Wh', 'Eigenverbrauch_Wh', 'EVQ_%']].copy()
                
                cols_to_convert = ['PV_Erzeugung_Wh', 'Netzbezug_Wh', 'Einspeisung_Wh', 'Eigenverbrauch_Wh']
                display_df[cols_to_convert] = display_df[cols_to_convert].astype(float) / 1000.0
                
                display_df.rename(columns=lambda x: x.replace('_Wh', ' (kWh)'), inplace=True)
                display_df['Datum'] = display_df['Datum'].dt.strftime('%d.%m.%Y')
                
                st.dataframe(display_df, use_container_width=True)

    except Exception as e:
        st.error(f"Fehler bei der Datenverarbeitung. Bitte prüfe das Format der CSV-Dateien. Detail: {e}")
else:
    st.info("👈 Bitte lade beide CSV-Dateien (S-Miles und Everhome) in der Seitenleiste hoch, um die Auswertung zu starten.")