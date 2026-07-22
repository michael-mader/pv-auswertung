import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import datetime

st.set_page_config(page_title="PV & Stromverbrauch Dashboard", layout="wide")
st.title("☀️ Interaktives PV & Stromverbrauch Dashboard")

# Seitenleiste für die Uploads & Filter
st.sidebar.header("Daten Upload")
file_smiles = st.sidebar.file_uploader("S-Miles Cloud Export (CSV)", type=['csv'])
file_everhome = st.sidebar.file_uploader("Everhome Export (CSV)", type=['csv'])

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

        date_selection = st.sidebar.date_input(
            "Zeitraum auswählen",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )

        # Abfangen, falls der Nutzer erst ein Startdatum geklickt hat und das Enddatum noch fehlt
        if len(date_selection) == 2:
            start_date, end_date = date_selection
        else:
            start_date = date_selection[0]
            end_date = date_selection[0]

        # DataFrame anhand des Kalenders filtern
        mask = (merged['Datum'].dt.date >= start_date) & (merged['Datum'].dt.date <= end_date)
        filtered_df = merged.loc[mask]

        if filtered_df.empty:
            st.warning("Für den gewählten Zeitraum sind keine übereinstimmenden Daten vorhanden.")
        else:
            # --- 3. KPIs berechnen (jetzt basierend auf filtered_df) ---
            total_pv = filtered_df['PV_Erzeugung_Wh'].sum()
            total_bezug = filtered_df['Netzbezug_Wh'].sum()
            total_einspeisung = filtered_df['Einspeisung_Wh'].sum()
            total_eigen = filtered_df['Eigenverbrauch_Wh'].sum()
            total_verbrauch = filtered_df['Gesamtverbrauch_Wh'].sum()
            
            evq = (total_eigen / total_pv * 100) if total_pv > 0 else 0
            autarkie = (total_eigen / total_verbrauch * 100) if total_verbrauch > 0 else 0

            # UI: KPIs anzeigen
            st.header("📊 Auswertung für den gewählten Zeitraum")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("PV-Erzeugung", f"{total_pv/1000:.2f} kWh")
            col2.metric("Netzbezug", f"{total_bezug/1000:.2f} kWh")
            col3.metric("Eigenverbrauchsquote", f"{evq:.1f} %")
            col4.metric("Autarkiegrad", f"{autarkie:.1f} %")

            # --- 4. Diagramm zeichnen ---
            st.header("📈 Tagesverlauf")
            fig, ax = plt.subplots(figsize=(12, 6))
            
            ax.bar(filtered_df['Datum'], filtered_df['Eigenverbrauch_Wh']/1000, label='Eigenverbrauch (kWh)', color='green')
            ax.bar(filtered_df['Datum'], filtered_df['Netzbezug_Wh']/1000, bottom=filtered_df['Eigenverbrauch_Wh']/1000, label='Netzbezug (kWh)', color='orange')
            ax.plot(filtered_df['Datum'], filtered_df['PV_Erzeugung_Wh']/1000, label='PV Erzeugung (kWh)', color='blue', marker='o')

            for i, row in filtered_df.iterrows():
                if row['PV_Erzeugung_Wh'] > 0:
                    val = row['EVQ_%']
                    total_height = (row['Eigenverbrauch_Wh'] + row['Netzbezug_Wh']) / 1000
                    ax.text(row['Datum'], total_height + 0.3, f"{val:.0f} %", 
                            ha='center', va='bottom', fontsize=8, 
                            bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=1))
            
            ax.set_ylabel("Energie (kWh)")
            if not filtered_df.empty:
                max_y = max((filtered_df['Eigenverbrauch_Wh'] + filtered_df['Netzbezug_Wh'])/1000)
                ax.set_ylim(0, max_y * 1.15 if max_y > 0 else 1)
            
            ax.legend()
            plt.xticks(rotation=45)
            st.pyplot(fig)

            # --- 5. Rohdaten anzeigen ---
            with st.expander("Tabelle mit aggregierten Tagesdaten anzeigen"):
                display_df = filtered_df[['Datum', 'PV_Erzeugung_Wh', 'Netzbezug_Wh', 'Einspeisung_Wh', 'Eigenverbrauch_Wh', 'EVQ_%']].copy()
                
                # Datentypen sauber aufteilen, um Streamlit/PyArrow-Fehler zu vermeiden
                cols_to_convert = ['PV_Erzeugung_Wh', 'Netzbezug_Wh', 'Einspeisung_Wh', 'Eigenverbrauch_Wh']
                display_df[cols_to_convert] = display_df[cols_to_convert].astype(float) / 1000.0
                
                display_df.rename(columns=lambda x: x.replace('_Wh', ' (kWh)'), inplace=True)
                # Datum auf lesbares Format ohne Uhrzeit kürzen
                display_df['Datum'] = display_df['Datum'].dt.strftime('%d.%m.%Y')
                
                st.dataframe(display_df, use_container_width=True)

    except Exception as e:
        st.error(f"Fehler bei der Datenverarbeitung. Bitte prüfe das Format der CSV-Dateien. Detail: {e}")
else:
    st.info("👈 Bitte lade beide CSV-Dateien (S-Miles und Everhome) in der Seitenleiste hoch, um die Auswertung zu starten.")