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
    st.markdown("### Analisi Premi per Generazione e Ramo")
    #st.markdown("Analisi dei volumi di **Premio Netto** aggregati per Ramo (Danni/Vita) e Anno di Effetto della polizza.")
    st.markdown("")

    # --- ESTRAZIONE CONTRAENTI DISPONIBILI ---
    try:
        query_contraenti = """
            SELECT DISTINCT COALESCE(CONTRAENTE, 'SCONOSCIUTO') AS Contraente 
            FROM vista_polizze 
            WHERE CONTRAENTE IS NOT NULL 
            ORDER BY Contraente
        """
        df_contraenti = conn.execute(query_contraenti).df()
        lista_contraenti = ["Tutti i Contraenti"] + sorted(df_contraenti['Contraente'].tolist())
    except Exception:
        lista_contraenti = ["Tutti i Contraenti"]

    # --- PANNELLO FILTRI NATIVO ---
    with st.container(border=True):
        st.markdown("##### Seleziona Contraente")
        contraente_scelto = st.selectbox("Seleziona Contraente", lista_contraenti, label_visibility="collapsed")

    with st.spinner("Aggregazione dati in corso..."):
        campo_data_sicuro = costruisci_campo_data_safe("DATAEFFETTO")
        
        # Costruzione dinamica della clausola WHERE per il contraente
        where_cond = "DATAEFFETTO IS NOT NULL AND PREMI_NETTO IS NOT NULL"
        if contraente_scelto != "Tutti i Contraenti":
            contraente_safe = str(contraente_scelto).replace("'", "''")
            where_cond += f" AND COALESCE(CONTRAENTE, 'SCONOSCIUTO') = '{contraente_safe}'"

        query = f"""
            SELECT 
                YEAR({campo_data_sicuro}) AS Anno_Effetto,
                UPPER(CAST(RAMO AS VARCHAR)) AS Ramo,
                SUM(CAST(PREMI_NETTO AS DOUBLE)) AS Totale_Premio_Netto
            FROM vista_polizze
            WHERE {where_cond}
            GROUP BY Anno_Effetto, Ramo
            HAVING Anno_Effetto IS NOT NULL
            ORDER BY Anno_Effetto DESC
        """
        
        try:
            df_aggregato = conn.execute(query).df()
            
            if df_aggregato.empty:
                st.warning("Nessun dato valido trovato per i filtri selezionati.")
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
            _, col_download = st.columns([3, 1])
            with col_download:
                suffix_file = f"_contraente_{str(contraente_scelto).replace(' ', '_').replace('/', '_')}" if contraente_scelto != "Tutti i Contraenti" else "_totale_portafoglio"
                csv_data = df_pivot.reset_index().to_csv(index=False, sep=';', decimal=',').encode('utf-8')
                st.download_button(
                    label="📥 Scarica CSV",
                    data=csv_data,
                    file_name=f"premi_per_generazione{suffix_file}.csv",
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
