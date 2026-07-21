import streamlit as st
import pandas as pd
import altair as alt

def costruisci_campo_data_safe(colonna):
    """Crea la stringa SQL per il parsing sicuro delle date in DuckDB."""
    return f"""CAST(COALESCE(
        TRY_STRPTIME(CAST({colonna} AS VARCHAR), '%d/%m/%Y'),
        TRY_STRPTIME(CAST({colonna} AS VARCHAR), '%Y-%m-%d'),
        TRY_STRPTIME(CAST({colonna} AS VARCHAR), '%d-%m-%Y'),
        TRY_CAST({colonna} AS DATE)
    ) AS DATE)"""

def render_analisi_premi(conn):
    st.markdown("""
        <style>
        .metric-card {
            background-color: white;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #E5E7EB;
            border-left: 4px solid #007A33;
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            margin-bottom: 20px;
        }
        </style>
    """, unsafe_allow_html=True)

    st.markdown("### 💰 Analisi Premi per Generazione e Ramo")
    st.markdown("Analisi dei volumi di **Premio Netto** aggregati per Ramo (Danni/Vita) e Anno di Effetto della polizza.")

    with st.spinner("Aggregazione dati in corso..."):
        # Costruiamo la query estraendo in modo sicuro l'anno e sommando i premi
        campo_data_sicuro = costruisci_campo_data_safe("DATAEFFETTO")
        
        query = f"""
            SELECT 
                YEAR({campo_data_sicuro}) AS Anno_Effetto,
                UPPER(CAST(RAMO AS VARCHAR)) AS Ramo,
                SUM(CAST(PREMI_NETTO AS DOUBLE)) AS Totale_Premio_Netto
            FROM vista_polizze
            WHERE DATAEFFETTO IS NOT NULL 
              AND PREMI_NETTO IS NOT NULL
            GROUP BY Anno_Effetto, Ramo
            HAVING Anno_Effetto IS NOT NULL
            ORDER BY Anno_Effetto DESC
        """
        
        try:
            # Eseguiamo la query e carichiamo il dataframe
            df_aggregato = conn.execute(query).df()
            
            if df_aggregato.empty:
                st.warning("Nessun dato valido trovato per l'analisi.")
                return

            # Rimuoviamo eventuali anni anomali (es. date di default come 1900 o 2099)
            df_aggregato = df_aggregato[
                (df_aggregato['Anno_Effetto'] >= 1990) & 
                (df_aggregato['Anno_Effetto'] <= 2050)
            ]

            # Trasformiamo i dati in una vera Pivot Table (Righe: Anno, Colonne: Ramo)
            df_pivot = df_aggregato.pivot(
                index='Anno_Effetto', 
                columns='Ramo', 
                values='Totale_Premio_Netto'
            ).fillna(0)
            
            # Aggiungiamo la colonna "Totale Generale" per ogni anno
            df_pivot['Totale Generale'] = df_pivot.sum(axis=1)

            # --- 1. VISUALIZZAZIONE GRAFICA (BARRE AFFIANCATE + TOOLTIP EURO) ---
            st.markdown("<div class='metric-card'><h4>📈 Andamento Storico</h4></div>", unsafe_allow_html=True)
            
            # Prepariamo i dati per il grafico (escludiamo il Totale Generale per non sballare le proporzioni)
            df_chart = df_pivot.drop(columns=['Totale Generale'], errors='ignore')
            
            # Adattiamo il DataFrame per Altair
            df_melted = df_chart.reset_index().melt(
                id_vars='Anno_Effetto', 
                var_name='Ramo', 
                value_name='Premio_Netto'
            )

            # Grafico Altair con colonne affiancate e Tooltip formattati in Euro
            chart = alt.Chart(df_melted).mark_bar().encode(
                x=alt.X('Ramo:N', title=None, axis=None),
                y=alt.Y('Premio_Netto:Q', title='Premio Netto (€)'),
                color=alt.Color(
                    'Ramo:N', 
                    scale=alt.Scale(domain=['DANNI', 'VITA'], range=['#007A33', '#004D20']),
                    legend=alt.Legend(title="Ramo")
                ),
                column=alt.Column(
                    'Anno_Effetto:O', 
                    title='Anno di Effetto',
                    header=alt.Header(labelOrient='bottom', titleOrient='bottom', labelAngle=0)
                ),
                tooltip=[
                    alt.Tooltip('Anno_Effetto:O', title='Anno'),
                    alt.Tooltip('Ramo:N', title='Ramo'),
                    alt.Tooltip('Premio_Netto:Q', title='Premio Netto', format='€ ,.2f')
                ]
            ).properties(
                height=340
            ).configure_view(
                stroke='transparent'
            )

            st.altair_chart(chart, use_container_width=True)

            # --- 2. TABELLA PIVOT NAVIGABILE ---
            col_titolo, col_download = st.columns([3, 1])
            with col_titolo:
                st.markdown("<div class='metric-card'><h4>🧮 Tabella Dati </h4></div>", unsafe_allow_html=True)
            with col_download:
                # Generazione CSV al volo in formato italiano (separatore ';' e decimali ',')
                csv_data = df_pivot.reset_index().to_csv(index=False, sep=';', decimal=',').encode('utf-8')
                st.download_button(
                    label="📥 Scarica CSV",
                    data=csv_data,
                    file_name="premi_per_generazione.csv",
                    mime="text/csv",
                    type="primary",
                    use_container_width=True
                )

            # Configurazione delle colonne per formattare i numeri come Valuta nativamente
            col_config = {
                "Anno_Effetto": st.column_config.NumberColumn("Anno di Effetto", format="%d")
            }
            
            for col in df_pivot.columns:
                col_config[col] = st.column_config.NumberColumn(
                    col,
                    format="€ %,.2f", # Formatta con il simbolo Euro, separatore delle migliaia e 2 decimali
                    step=1
                )

            # Rendering della tabella con ordine decrescente per anno
            st.dataframe(
                df_pivot.sort_index(ascending=False), 
                use_container_width=True,
                column_config=col_config
            )

        except Exception as e:
            st.error(f"⚠️ Errore durante l'aggregazione dei premi: {e}")
