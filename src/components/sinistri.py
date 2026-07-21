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
    st.markdown("### Analisi Sviluppo Portafoglio")
    #st.markdown("Monitoraggio dell'incisività dei sinistri e sviluppo del Loss Ratio Cumulato nei primi 10 anni dalla messa in copertura.")
    st.markdown("")

    # --- SETUP FILTRI ED ESTRAZIONE DIMENSIONI ---
    data_eff_safe = costruisci_campo_data_safe("DATAEFFETTO")
    data_liq_safe = costruisci_campo_data_safe("DATALIQUIDAZIONE")

    with st.spinner("Lettura portafoglio in corso..."):
        query_filtri = f"""
            SELECT DISTINCT 
                YEAR({data_eff_safe}) AS Generazione,
                COALESCE(CONTRAENTE, 'SCONOSCIUTO') AS Contraente,
                COALESCE(GARANZIA, 'SCONOSCIUTO') AS Garanzia
            FROM vista_polizze
            WHERE DATAEFFETTO IS NOT NULL
              AND YEAR({data_eff_safe}) BETWEEN 1990 AND 2050
        """
        df_filtri = conn.execute(query_filtri).df()
        
    generazioni_disp = sorted(df_filtri['Generazione'].dropna().unique().astype(int).tolist(), reverse=True)
    contraenti_disp = sorted(df_filtri['Contraente'].dropna().unique().tolist())
    garanzie_disp = sorted(df_filtri['Garanzia'].dropna().unique().tolist())

    if not generazioni_disp or not contraenti_disp:
        st.warning("Dati insufficienti per generare l'analisi di sviluppo.")
        return

    # --- PANNELLO DI CONTROLLO NATIVO (RISOLVE IL BUG DEL BOX) ---
    with st.container(border=True):
        st.markdown("##### Configurazione Parametri")
        
        col_c1, col_c2, col_c3 = st.columns([2, 1.5, 1.5])
        with col_c1:
            tipo_analisi = st.radio(
                "Variabile di stratificazione", 
                ["Contraente", "Garanzia"], 
                horizontal=True
            )
        with col_c2:
            st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
            usa_estinzioni = st.toggle("Includi Estinzioni")
        with col_c3:
            st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
            confronto_attivo = st.toggle("Attiva Confronto")

        st.divider()

        col_dim = "CONTRAENTE" if tipo_analisi == "Contraente" else "GARANZIA"
        valori_disp = contraenti_disp if tipo_analisi == "Contraente" else garanzie_disp

        if confronto_attivo:
            col_target, col_bench_ui = st.columns(2)
            with col_target:
                st.markdown("**Coorte Target**")
                gen_target = st.selectbox("Generazione Target", generazioni_disp, key="gen_target")
                val_target = st.selectbox(f"{tipo_analisi} Target", valori_disp, key="val_target")
            with col_bench_ui:
                st.markdown("**Coorte di Confronto**")
                gen_bench = st.selectbox("Generazione di Confronto", generazioni_disp, index=1 if len(generazioni_disp) > 1 else 0, key="gen_bench")
                val_bench = st.selectbox(f"{tipo_analisi} di Confronto", valori_disp, key="val_bench")
            
            if gen_target == gen_bench and val_target == val_bench:
                st.warning("Selezionare parametri differenti per il confronto tra coorti identiche.")
                return

            label_bench = f"Confronto ({gen_bench} - {val_bench})"
        else:
            col_target, col_info = st.columns(2)
            with col_target:
                st.markdown("**Coorte Target**")
                gen_target = st.selectbox("Generazione Target", generazioni_disp, key="gen_target")
                val_target = st.selectbox(f"{tipo_analisi} Target", valori_disp, key="val_target")
            # with col_info:
            #     st.markdown("**Benchmark di Riferimento**")
            #     st.info("Confronto automatico attivo con il **Resto del Portafoglio** (esclusa la coorte target).")

            gen_bench = gen_target
            val_bench = "RESTO_PORTAFOGLIO"
            label_bench = "Resto Portafoglio"

    # --- COSTRUZIONE CONDIZIONI SQL SANITIZZATE ---
    val_target_safe = str(val_target).replace("'", "''")
    cond_target = f"YEAR({data_eff_safe}) = {gen_target} AND COALESCE({col_dim}, 'SCONOSCIUTO') = '{val_target_safe}'"
    
    if confronto_attivo:
        val_bench_safe = str(val_bench).replace("'", "''")
        cond_bench = f"YEAR({data_eff_safe}) = {gen_bench} AND COALESCE({col_dim}, 'SCONOSCIUTO') = '{val_bench_safe}'"
    else:
        cond_bench = f"YEAR({data_eff_safe}) = {gen_target} AND COALESCE({col_dim}, 'SCONOSCIUTO') != '{val_target_safe}'"

    label_bench_sql = label_bench.replace("'", "''")

    # --- DEFINIZIONE ESPRESSIONE PREMI (CON O SENZA ESTINZIONI) ---
    if usa_estinzioni:
        premio_expr = "CAST(COALESCE(PREMI_NETTO, 0) + COALESCE(ESTINZIONI, 0) AS DOUBLE)"
    else:
        premio_expr = "CAST(COALESCE(PREMI_NETTO, 0) AS DOUBLE)"

    # --- NOMI FILE DINAMICI PER EXPORT ---
    dim_prefix = tipo_analisi.lower()
    clean_target = f"{gen_target}_{str(val_target).replace(' ', '_').replace('''\'''', '').replace('/', '_')}"
    if confronto_attivo:
        clean_bench = f"{gen_bench}_{str(val_bench).replace(' ', '_').replace('''\'''', '').replace('/', '_')}"
        nome_export = f"target_{dim_prefix}_{clean_target}_vs_confronto_{dim_prefix}_{clean_bench}"
    else:
        nome_export = f"target_{dim_prefix}_{clean_target}"

    if usa_estinzioni:
        nome_export += "_con_estinzioni"

    # --- ESECUZIONE QUERY SVILUPPO LOSS RATIO ---
    with st.spinner("Calcolo triangolazione e Loss Ratio in corso..."):
        query_sviluppo = f"""
        WITH TargetData AS (
            SELECT 
                'Target' AS Gruppo,
                UPPER(CAST(RAMO AS VARCHAR)) AS Ramo,
                ID,
                {premio_expr} AS Premio_Netto,
                CAST(COALESCE(LIQUIDAZIONI, 0) AS DOUBLE) AS Liquidazione,
                YEAR({data_liq_safe}) - YEAR({data_eff_safe}) AS t_sviluppo,
                DATALIQUIDAZIONE
            FROM vista_polizze
            WHERE DATAEFFETTO IS NOT NULL AND ({cond_target})
        ),
        BenchData AS (
            SELECT 
                '{label_bench_sql}' AS Gruppo,
                UPPER(CAST(RAMO AS VARCHAR)) AS Ramo,
                ID,
                {premio_expr} AS Premio_Netto,
                CAST(COALESCE(LIQUIDAZIONI, 0) AS DOUBLE) AS Liquidazione,
                YEAR({data_liq_safe}) - YEAR({data_eff_safe}) AS t_sviluppo,
                DATALIQUIDAZIONE
            FROM vista_polizze
            WHERE DATAEFFETTO IS NOT NULL AND ({cond_bench})
        ),
        CombinedData AS (
            SELECT * FROM TargetData
            UNION ALL
            SELECT * FROM BenchData
        ),
        Denominatore AS (
            SELECT 
                Gruppo, Ramo,
                SUM(Premio_Netto_Univoco) AS Tot_Premio_Netto
            FROM (
                SELECT Gruppo, Ramo, ID, MAX(Premio_Netto) AS Premio_Netto_Univoco
                FROM CombinedData
                GROUP BY Gruppo, Ramo, ID
            ) sub
            GROUP BY Gruppo, Ramo
        ),
        Numeratore AS (
            SELECT 
                Gruppo, Ramo, t_sviluppo,
                SUM(Liquidazione) AS Liquidato_t
            FROM CombinedData
            WHERE DATALIQUIDAZIONE IS NOT NULL 
              AND t_sviluppo >= 0 AND t_sviluppo <= 10
            GROUP BY Gruppo, Ramo, t_sviluppo
        )
        SELECT 
            d.Gruppo, d.Ramo, d.Tot_Premio_Netto,
            n.t_sviluppo, COALESCE(n.Liquidato_t, 0) AS Liquidato_t
        FROM Denominatore d
        LEFT JOIN Numeratore n ON d.Gruppo = n.Gruppo AND d.Ramo = n.Ramo
        """
        
        try:
            df_sql = conn.execute(query_sviluppo).df()
            
            if df_sql.empty:
                st.info("Nessun dato trovato per le coorti selezionate.")
                return

            grid = pd.MultiIndex.from_product(
                [['Target', label_bench], ['DANNI', 'VITA'], range(11)],
                names=['Gruppo', 'Ramo', 't_sviluppo']
            ).to_frame(index=False)

            df_full = pd.merge(grid, df_sql, on=['Gruppo', 'Ramo', 't_sviluppo'], how='left').fillna(0)
            
            totali = df_sql[['Gruppo', 'Ramo', 'Tot_Premio_Netto']].replace(0, np.nan).dropna().drop_duplicates()
            if 'Tot_Premio_Netto' in df_full.columns:
                df_full = df_full.drop(columns=['Tot_Premio_Netto'])
            df_full = pd.merge(df_full, totali, on=['Gruppo', 'Ramo'], how='left')

            df_full = df_full.sort_values(['Gruppo', 'Ramo', 't_sviluppo'])
            df_full['Cum_Liquidato'] = df_full.groupby(['Gruppo', 'Ramo'])['Liquidato_t'].cumsum()

            df_full['Loss_Ratio'] = (df_full['Cum_Liquidato'] / df_full['Tot_Premio_Netto'].replace(0, np.nan)) * 100
            df_full['Loss_Ratio'] = df_full['Loss_Ratio'].fillna(0) 

            df_full['Serie'] = df_full['Gruppo'] + " - " + df_full['Ramo']
            df_pivot = df_full.pivot(index='t_sviluppo', columns='Serie', values='Loss_Ratio').fillna(0)

            # --- 1. GRAFICO PLOTLY ---
            st.markdown("#### Sviluppo Loss Ratio Cumulato (%)")

            color_map = {
                'Target - DANNI': '#007A33',         
                'Target - VITA': '#C8102E',          
                f'{label_bench} - DANNI': '#80BCA1', 
                f'{label_bench} - VITA': '#E38796'   
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
                    hovertemplate='<b>' + col + '</b><br>Anno t: %{x}<br>Loss Ratio: %{y:,.2f}%<extra></extra>'
                ))

            fig.update_layout(
                xaxis_title="Anno di Sviluppo (t)",
                yaxis_title="Loss Ratio (%)",
                xaxis=dict(tickmode='linear', tick0=0, dtick=1),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=20, r=20, t=30, b=30),
                plot_bgcolor="white",
                paper_bgcolor="white",
                hovermode="x unified",
                height=420
            )

            st.plotly_chart(
                fig, 
                use_container_width=True,
                config={
                    'displayModeBar': True,
                    'toImageButtonOptions': {
                        'format': 'png',
                        'filename': f'grafico_{nome_export}',
                        'height': 600,
                        'width': 1000,
                        'scale': 2
                    }
                }
            )

            # --- 2. TABELLA LOSS RATIO E DOWNLOAD ---
            _, col_dl = st.columns([3, 1])
            
            df_matrix = df_pivot.T
            df_matrix.columns = [f"Anno {int(c)}" for c in df_matrix.columns]

            with col_dl:
                csv_data = df_matrix.reset_index().to_csv(index=False, sep=';', decimal=',').encode('utf-8')
                
                st.download_button(
                    label="📥 Scarica CSV",
                    data=csv_data,
                    file_name=f"tabella_{nome_export}.csv",
                    mime="text/csv",
                    type="primary",
                    use_container_width=True
                )

            col_config = {
                col: st.column_config.NumberColumn(col, format="%.2f %%") 
                for col in df_matrix.columns
            }
            
            st.dataframe(df_matrix, use_container_width=True, column_config=col_config)

        except Exception as e:
            st.error(f"Errore durante l'aggregazione del Loss Ratio: {e}")
