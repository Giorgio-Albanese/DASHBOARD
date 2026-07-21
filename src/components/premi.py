import streamlit as st
import pandas as pd

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
            df_aggregato = conn.execute(query).df()
            
            if df_aggregato.empty:
                st.warning("Nessun dato valido trovato per l'analisi.")
                return

            # Filtriamo gli anni di interesse
            df_aggregato = df_aggregato[
                (df_aggregato['Anno_Effetto'] >= 1990) & 
                (df_aggregato['Anno_Effetto'] <= 2050)
            ]

            # Pivot Table (Righe: Anno, Colonne: Ramo)
            df_pivot = df_aggregato.pivot(
                index='Anno_Effetto', 
                columns='Ramo', 
                values='Totale_Premio_Netto'
            ).fillna(0)
            
            df_pivot['Totale Generale'] = df_pivot.sum(axis=1)

            # --- 1. VISUALIZZAZIONE GRAFICA NATIVA STREAMLIT ---
            #st.markdown("<div class='metric-card'><h4>📈 Andamento Storico</h4></div>", unsafe_allow_html=True)
            
            df_chart = df_pivot.drop(columns=['Totale Generale'], errors='ignore')
            
            # Assegniamo in modo dinamico Verde a DANNI e Rosso a VITA
            colori_rami = []
            for col in df_chart.columns:
                if 'DANNI' in str(col).upper():
                    colori_rami.append('#007A33')  # Verde HDI
                elif 'VITA' in str(col).upper():
                    colori_rami.append('#C8102E')   # Rosso HDI
                else:
                    colori_rami.append('#6B7280')

            st.bar_chart(
                df_chart,
                stack=False,
                color=colori_rami if colori_rami else None,
                use_container_width=True
            )

            # --- 2. TABELLA PIVOT NAVIGABILE ---
            col_titolo, col_download = st.columns([3, 1])
            with col_titolo:
                st.markdown("<div class='metric-card'><h4>🧮 Tabella Dati </h4></div>", unsafe_allow_html=True)
            with col_download:
                csv_data = df_pivot.reset_index().to_csv(index=False, sep=';', decimal=',').encode('utf-8')
                st.download_button(
                    label="📥 Scarica CSV",
                    data=csv_data,
                    file_name="premi_per_generazione.csv",
                    mime="text/csv",
                    type="primary",
                    use_container_width=True
                )

            col_config = {
                "Anno_Effetto": st.column_config.NumberColumn("Anno di Effetto", format="%d")
            }
            
            for col in df_pivot.columns:
                col_config[col] = st.column_config.NumberColumn(
                    col,
                    format="€ %,.2f",
                    step=1
                )

            st.dataframe(
                df_pivot.sort_index(ascending=False), 
                use_container_width=True,
                column_config=col_config
            )

        except Exception as e:
            st.error(f"⚠️ Errore durante l'aggregazione dei premi: {e}")
