import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

st.set_page_config(page_title="PV & Stromverbrauch Dashboard", layout="wide")
st.title("☀️ Interaktives PV & Stromverbrauch Dashboard")

# Seitenleiste für die Uploads
st.sidebar.header("Daten Upload")
file_smiles = st.sidebar.file_uploader("S-Miles Cloud Export (CSV)", type=['csv'])
file_everhome = st.sidebar.file_uploader("Everhome Export (CSV)", type=['csv'])

if file_smiles and file_everhome:
    try:
        # S-Miles Daten aufbereiten
        df_smiles = pd.read_csv(file_smiles)
        # S-Miles nutzt oft ein Leerzeichen als Spaltenname für das Datum
        if ' ' in df_smiles.columns:
            df_smiles.rename(columns={' ': 'Datum'}, inplace=True)
        elif df_smiles.columns[0] != 'Datum': 
            df_smiles.rename(columns={df_smiles.columns[0]: 'Datum'}, inplace=True)
            
        df_smiles['Datum'] = pd.to_datetime(df_smiles['Datum'], errors='coerce')

        # Everhome Daten aufbereiten (sep=None erkennt automatisch Komma/Semikolon)
        df_everhome = pd.read_csv(file_everhome, sep=None, engine='python')
        df_everhome['Datetime'] = pd.to_datetime(df_everhome['Datum'] + ' ' + df_everhome['Uhrzeit'], format='%d.%m.%Y %H:%M:%S', errors='coerce')
        df_everhome['Datum'] = pd.to_datetime(df_everhome['Datetime'].dt.date)

        # Everhome auf Tagesbasis aggregieren
        daily_everhome = df_everhome.groupby('Datum').agg({
            'Differenz Bezug': 'sum',
            'Differenz Einspeisung': 'sum'
        }).reset_index()

        # Zusammenführen
        merged = pd.merge(daily_everhome, df_smiles, on='Datum', how='inner')

        # Metriken in Wh berechnen
        merged['PV_Erzeugung_Wh'] = merged['Ertrag (Wh)']
        merged['Netzbezug_Wh'] = merged['Differenz Bezug']
        merged['Einspeisung_Wh'] = merged['Differenz Einspeisung']
        
        # Eigenverbrauch (Max 0 verhindert negative Werte bei Timing-Diskrepanzen)
        merged['Eigenverbrauch_Wh'] = merged.apply(lambda row: max(0, row['PV_Erzeugung_Wh'] - row['Einspeisung_Wh']), axis=1)
        merged['Gesamtverbrauch_Wh'] = merged['Netzbezug_Wh'] + merged['Eigenverbrauch_Wh']
        
        # Eigenverbrauchsquote in %
        merged['EVQ_%'] = np.where(merged['PV_Erzeugung_Wh'] > 0, (merged['Eigenverbrauch_Wh'] / merged['PV_Erzeugung_Wh']) * 100, 0)

        # Gesamtsummen für KPIs
        total_pv = merged['PV_Erzeugung_Wh'].sum()
        total_bezug = merged['Netzbezug_Wh'].sum()
        total_einspeisung = merged['Einspeisung_Wh'].sum()
        total_eigen = merged['Eigenverbrauch_Wh'].sum()
        total_verbrauch = merged['Gesamtverbrauch_Wh'].sum()
        
        evq = (total_eigen / total_pv * 100) if total_pv > 0 else 0
        autarkie = (total_eigen / total_verbrauch * 100) if total_verbrauch > 0 else 0

        # --- UI: KPIs anzeigen ---
        st.header("📊 Gesamtauswertung")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("PV-Erzeugung", f"{total_pv/1000:.2f} kWh")
        col2.metric("Netzbezug", f"{total_bezug/1000:.2f} kWh")
        col3.metric("Eigenverbrauchsquote", f"{evq:.1f} %")
        col4.metric("Autarkiegrad", f"{autarkie:.1f} %")

        # --- UI: Diagramm zeichnen ---
        st.header("📈 Tagesverlauf")
        fig, ax = plt.subplots(figsize=(12, 6))
        
        ax.bar(merged['Datum'], merged['Eigenverbrauch_Wh']/1000, label='Eigenverbrauch (kWh)', color='green')
        ax.bar(merged['Datum'], merged['Netzbezug_Wh']/1000, bottom=merged['Eigenverbrauch_Wh']/1000, label='Netzbezug (kWh)', color='orange')
        ax.plot(merged['Datum'], merged['PV_Erzeugung_Wh']/1000, label='PV Erzeugung (kWh)', color='blue', marker='o')

        # Prozentzahlen über die Balken schreiben
        for i, row in merged.iterrows():
            if row['PV_Erzeugung_Wh'] > 0:
                val = row['EVQ_%']
                total_height = (row['Eigenverbrauch_Wh'] + row['Netzbezug_Wh']) / 1000
                ax.text(row['Datum'], total_height + 0.3, f"{val:.0f} %", 
                        ha='center', va='bottom', fontsize=8, 
                        bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=1))
        
        ax.set_ylabel("Energie (kWh)")
        # Y-Achse etwas höher ansetzen für die Labels
        ax.set_ylim(0, max((merged['Eigenverbrauch_Wh'] + merged['Netzbezug_Wh'])/1000) * 1.15)
        ax.legend()
        plt.xticks(rotation=45)
        
        # Diagramm in Streamlit rendern
        st.pyplot(fig)

        # --- UI: Rohdaten anzeigen (optional) ---
        with st.expander("Tabelle mit aggregierten Tagesdaten anzeigen"):
            display_df = merged[['Datum', 'PV_Erzeugung_Wh', 'Netzbezug_Wh', 'Einspeisung_Wh', 'Eigenverbrauch_Wh', 'EVQ_%']].copy()
            display_df.iloc[:, 1:5] = display_df.iloc[:, 1:5] / 1000 # in kWh umrechnen
            display_df.rename(columns=lambda x: x.replace('_Wh', ' (kWh)'), inplace=True)
            st.dataframe(display_df, use_container_width=True)

    except Exception as e:
        st.error(f"Fehler bei der Datenverarbeitung. Bitte prüfe das Format der CSV-Dateien. Detail: {e}")
else:
    st.info("👈 Bitte lade beide CSV-Dateien (S-Miles und Everhome) in der Seitenleiste hoch, um die Auswertung zu starten.")
