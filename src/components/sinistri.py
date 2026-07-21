import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

def costruisci_campo_data_safe(colonna):
    """Crea la stringa SQL per il parsing sicuro delle date in DuckDB."""
    return f"""CAST(COALESCE(
        TRY_STRPTIME(CAST({colonna} AS VARCHAR), '%d/%m/%Y'),
        TRY_STRPTIME(CAST({colonna} AS VARCHAR), '%Y-%m-%d'),
        TRY_STRPTIME(CAST({colonna} AS VARCHAR), '%d-%m-%Y'),
        TRY_CAST({colonna} AS DATE)
    ) AS DATE)"""

def render_analisi_sinistri(conn):
    st.markdown("""
        <style>
        .metric-card-sinistri {
            background-color: white;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #E5E7EB;
            border-left: 4px solid #C8102E; /* Bordo Rosso HDI */
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            margin-bottom: 20px;
        }
        </style>
    """, unsafe_allow_html=True)

    st.markdown("### 🚨 Velocità di Liquidazione (Claim Velocity)")
    st.markdown("Analisi dello sviluppo cumulato degli **importi liquidati (€)** nel corso dei primi 10 anni dalla messa in copertura.")

    # --- SETUP FILTRI ED ESTRAZIONE DIMENSIONI ---
    data_eff_safe = costruisci_campo_data_safe("DATAEFFETTO")
    data_liq_safe = costruisci_campo_data_safe("DATALIQUIDAZIONE")

    # Recuperiamo generazioni e contraenti disponibili
    with st.spinner("Lettura portafoglio in corso..."):
        query_filtri = f"""
            SELECT DISTINCT 
                YEAR({data_eff_safe}) AS Generazione,
                COALESCE(CONTRAENTE, 'SCONOSCIUTO') AS Contraente
            FROM vista_polizze
            WHERE DATAEFFETTO IS NOT NULL
              AND YEAR({data_eff_safe}) BETWEEN 1990 AND 2050
        """
        df_filtri = conn.execute(query_filtri).df()
        
    generazioni_disp = sorted(df_filtri['Generazione'].dropna().unique().astype(int).tolist(), reverse=True)
    contraenti_disp = sorted(df_filtri['Contraente'].dropna().unique().tolist())

    if not generazioni_disp or not contraenti_disp:
        st.warning("Dati insufficienti per generare l'analisi di sviluppo.")
        return

    # --- UI: CONFIGURAZIONE COORTI ---
    st.markdown("<div class='metric-card-sinistri'>", unsafe_allow_html=True)
    
    st.markdown("##### 🎯 Configurazione Coorte Target")
    col1, col2 = st.columns(2)
    with col1:
        gen_target = st.selectbox("Generazione Target (Anno Effetto)", generazioni_disp)
    with col2:
        contr_target = st.selectbox("Contraente Target", contraenti_disp)

    confronto_attivo = st.toggle("🔄 Confronta con un'altra coorte specifica (anziché con il resto del portafoglio)")
    
    if confronto_attivo:
        st.markdown("##### ⚖️ Configurazione Coorte di Confronto")
        col3, col4 = st.columns(2)
        with col3:
            gen_bench = st.selectbox("Generazione di Confronto", generazioni_disp, index=1 if len(generazioni_disp) > 1 else 0)
        with col4:
            contr_bench = st.selectbox("Contraente di Confronto", contraenti_disp)
        
        if gen_target == gen_bench and contr_target == contr_bench:
            st.warning("⚠️ Hai selezionato lo stesso contraente e la stessa generazione per il confronto. Seleziona parametri differenti.")
            st.markdown("</div>", unsafe_allow_html=True)
            return

        label_bench = f"Confronto ({gen_bench} - {contr_bench})"
    else:
        gen_bench = gen_target
        contr_bench = "RESTO_PORTAFOGLIO"
        label_bench = "Resto Portafoglio"

    st.markdown("</div>", unsafe_allow_html=True)

    # --- COSTRUZIONE CONDITION SQL SANITIZZATE ---
    contr_target_safe = contr_target.replace("'", "''")
    cond_target = f"YEAR({data_eff_safe}) = {gen_target} AND COALESCE(CONTRAENTE, 'SCONOSCIUTO') = '{contr_target_safe}'"
    
    if confronto_attivo:
        contr_bench_safe = contr_bench.replace("'", "''")
        cond_bench = f"YEAR({data_eff_safe}) = {gen_bench} AND COALESCE(CONTRAENTE, 'SCONOSCIUTO') = '{contr_bench_safe}'"
    else:
        cond_bench = f"YEAR({data_eff_safe}) = {gen_target} AND COALESCE(CONTRAENTE, 'SCONOSCIUTO') != '{contr_target_safe}'"

    label_bench_sql = label_bench.replace("'", "''")

    # --- ESECUZIONE QUERY SVILUPPO ---
    with st.spinner("Calcolo sviluppo sinistri in corso..."):
        query_sviluppo = f"""
        SELECT
            CASE 
                WHEN {cond_target} THEN 'Target'
                WHEN {cond_bench} THEN '{label_bench_sql}'
                ELSE NULL
            END AS Gruppo,
            UPPER(CAST(RAMO AS VARCHAR)) AS Ramo,
            YEAR({data_liq_safe}) - YEAR({data_eff_safe}) AS t_sviluppo,
            SUM(CAST(COALESCE(LIQUIDAZIONI, 0) AS DOUBLE)) AS Liquidato_t
        FROM vista_polizze
        WHERE DATAEFFETTO IS NOT NULL
          AND DATALIQUIDAZIONE IS NOT NULL
        GROUP BY Gruppo, Ramo, t_sviluppo
        HAVING Gruppo IS NOT NULL 
           AND t_sviluppo >= 0 
           AND t_sviluppo <= 10
        """
        
        try:
            df_sql = conn.execute(query_sviluppo).df()
            
            if df_sql.empty:
                st.info("Nessun sinistro liquidato trovato per le coorti selezionate.")
                return

            # Griglia fissa t=0 ... t=10 per tutte le combinazioni
            gruppi_presenti = [g for g in ['Target', label_bench] if g in df_sql['Gruppo'].unique()]
            grid = pd.MultiIndex.from_product(
                [gruppi_presenti, ['DANNI', 'VITA'], range(11)],
                names=['Gruppo', 'Ramo', 't_sviluppo']
            ).to_frame(index=False)

            # Merge e pulizia
            df_full = pd.merge(grid, df_sql, on=['Gruppo', 'Ramo', 't_sviluppo'], how='left').fillna(0)
            
            # Ordine e Somma Cumulata dell'importo liquidato
            df_full = df_full.sort_values(['Gruppo', 'Ramo', 't_sviluppo'])
            df_full['Cum_Liquidato'] = df_full.groupby(['Gruppo', 'Ramo'])['Liquidato_t'].cumsum()

            df_full['Serie'] = df_full['Gruppo'] + " - " + df_full['Ramo']

            # Pivot Table (Righe: Anno t, Colonne: Serie, Valori: Importo Cumulato)
            df_pivot = df_full.pivot(index='t_sviluppo', columns='Serie', values='Cum_Liquidato').fillna(0)

            # --- 1. RENDERING GRAFICO PLOTLY (CON DOWNLOAD IMMAGINE PNG) ---
            st.markdown("#### 📈 Sviluppo Cumulato Importi Liquidati (€)")

            color_map = {
                'Target - DANNI': '#007A33',        # Verde HDI
                'Target - VITA': '#C8102E',         # Rosso HDI
                f'{label_bench} - DANNI': '#80BCA1', # Verde Chiaro
                f'{label_bench} - VITA': '#E38796'   # Rosso Chiaro
            }

            fig = go.Figure()

            for col in df_pivot.columns:
                color = color_map.get(col, '#6B7280')
                fig.add_trace(go.Scatter(
                    x=df_pivot.index,
                    y=df_pivot[col],
                    mode='lines+markers',
                    name=col,
                    line=dict(color=color, width=3),
                    marker=dict(size=7),
                    hovertemplate='<b>' + col + '</b><br>Anno t: %{x}<br>Liquidato: € %{y:,.2f}<extra></extra>'
                ))

            fig.update_layout(
                xaxis_title="Anno di Sviluppo (t)",
                yaxis_title="Importo Liquidato Cumulato (€)",
                xaxis=dict(tickmode='linear', tick0=0, dtick=1),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=20, r=20, t=30, b=30),
                plot_bgcolor="white",
                paper_bgcolor="white",
                hovermode="x unified",
                height=420
            )

            # Render con pulsante di download PNG nativo in alto a destra nel grafico
            st.plotly_chart(
                fig, 
                use_container_width=True,
                config={
                    'displayModeBar': True,
                    'toImageButtonOptions': {
                        'format': 'png',
                        'filename': f'sviluppo_sinistri_{gen_target}_{contr_target}',
                        'height': 600,
                        'width': 1000,
                        'scale': 2
                    }
                }
            )

            # --- 2. TABELLA MATRICE DI SVILUPPO E DOWNLOAD CSV ---
            col_titolo, col_dl = st.columns([3, 1])
            with col_titolo:
                st.markdown("#### 🧮 Matrice Sviluppo Cumulato (€)")
            
            # Trasponiamo per avere le Serie nelle righe e gli Anni t nelle colonne
            df_matrix = df_pivot.T
            df_matrix.columns = [f"Anno {int(c)}" for c in df_matrix.columns]

            with col_dl:
                csv_data = df_matrix.reset_index().to_csv(index=False, sep=';', decimal=',').encode('utf-8')
                st.download_button(
                    label="📥 Scarica CSV Tabella",
                    data=csv_data,
                    file_name=f"matrice_sviluppo_{gen_target}_{contr_target}.csv",
                    mime="text/csv",
                    type="primary",
                    use_container_width=True
                )

            # Formatting Valuta
            col_config = {
                col: st.column_config.NumberColumn(col, format="€ %,.2f") 
                for col in df_matrix.columns
            }
            
            st.dataframe(df_matrix, use_container_width=True, column_config=col_config)

        except Exception as e:
            st.error(f"⚠️ Errore durante l'aggregazione dello sviluppo sinistri: {e}")
