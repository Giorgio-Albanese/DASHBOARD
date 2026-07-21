import streamlit as st
import pandas as pd
import numpy as np

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
    st.markdown("Analisi di sviluppo: quanto velocemente una generazione satura la propria storia sinistri (fino a 10 anni dalla messa in copertura).")

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

    # --- UI: CONFIGURAZIONE COORTI E METRICA ---
    st.markdown("<div class='metric-card-sinistri'>", unsafe_allow_html=True)
    
    col_metrica, col_spazio = st.columns([1, 2])
    with col_metrica:
        metrica = st.radio(
            "📍 Metrica di Sviluppo", 
            options=["Frequenza (N. Liquidazioni / Tot. Polizze)", "Saturazione Importi (€ Liq. / € Totale Liquidato)"]
        )
    
    st.markdown("##### 🎯 Configurazione Coorte Target")
    col1, col2 = st.columns(2)
    with col1:
        gen_target = st.selectbox("Generazione Target (Anno Effetto)", generazioni_disp)
    with col2:
        contr_target = st.selectbox("Contraente Target", contraenti_disp)

    confronto_attivo = st.toggle("🔄 Confronta con una coorte specifica (anziché con la Media Portafoglio)")
    
    if confronto_attivo:
        st.markdown("##### ⚖️ Configurazione Coorte di Confronto")
        col3, col4 = st.columns(2)
        with col3:
            gen_bench = st.selectbox("Generazione di Confronto", generazioni_disp, index=1 if len(generazioni_disp) > 1 else 0)
        with col4:
            contr_bench = st.selectbox("Contraente di Confronto", contraenti_disp)
        label_bench = "Confronto"
    else:
        # Se non attivato, il benchmark è "Il resto del portafoglio per la STESSA generazione"
        gen_bench = gen_target
        contr_bench = "RESTO_PORTAFOGLIO"
        label_bench = "Media Portafoglio"

    st.markdown("</div>", unsafe_allow_html=True)

    # --- COSTRUZIONE QUERY DINAMICA ---
    contr_target_safe = contr_target.replace("'", "''")
    
    cond_target = f"YEAR({data_eff_safe}) = {gen_target} AND COALESCE(CONTRAENTE, 'SCONOSCIUTO') = '{contr_target_safe}'"
    
    if confronto_attivo:
        contr_bench_safe = contr_bench.replace("'", "''")
        cond_bench = f"YEAR({data_eff_safe}) = {gen_bench} AND COALESCE(CONTRAENTE, 'SCONOSCIUTO') = '{contr_bench_safe}'"
    else:
        cond_bench = f"YEAR({data_eff_safe}) = {gen_target} AND COALESCE(CONTRAENTE, 'SCONOSCIUTO') != '{contr_target_safe}'"

    with st.spinner("Calcolo triangolazioni in corso..."):
        query_sviluppo = f"""
        WITH DatiTag AS (
            SELECT
                CASE 
                    WHEN {cond_target} THEN 'Target'
                    WHEN {cond_bench} THEN '{label_bench}'
                    ELSE NULL
                END AS Gruppo,
                UPPER(CAST(RAMO AS VARCHAR)) AS Ramo,
                YEAR({data_liq_safe}) - YEAR({data_eff_safe}) AS t_sviluppo,
                ID,
                CAST(LIQUIDAZIONI AS DOUBLE) AS Liquidazione
            FROM vista_polizze
            WHERE DATAEFFETTO IS NOT NULL
        ),
        BaseDati AS (
            SELECT * FROM DatiTag WHERE Gruppo IS NOT NULL
        ),
        SintesiCoorte AS (
            SELECT
                Gruppo, Ramo,
                COUNT(DISTINCT ID) AS Tot_Polizze_Coorte,
                SUM(Liquidazione) AS Tot_Liquidato_Coorte
            FROM BaseDati
            GROUP BY Gruppo, Ramo
        ),
        SviluppoTemporale AS (
            SELECT
                Gruppo, Ramo, t_sviluppo,
                COUNT(ID) AS Num_Sinistri_t,
                SUM(Liquidazione) AS Liquidato_t
            FROM BaseDati
            WHERE t_sviluppo IS NOT NULL AND t_sviluppo >= 0 AND t_sviluppo <= 10
            GROUP BY Gruppo, Ramo, t_sviluppo
        )
        SELECT
            s.Gruppo, s.Ramo,
            s.Tot_Polizze_Coorte,
            s.Tot_Liquidato_Coorte,
            v.t_sviluppo,
            v.Num_Sinistri_t,
            v.Liquidato_t
        FROM SintesiCoorte s
        LEFT JOIN SviluppoTemporale v ON s.Gruppo = v.Gruppo AND s.Ramo = v.Ramo
        """
        
        try:
            df_sql = conn.execute(query_sviluppo).df()
            
            if df_sql.empty:
                st.info("Nessun sinistro o polizza trovata per le coorti selezionate.")
                return

            # Costruiamo una griglia fissa t=0 ... t=10 per evitare spezzature di linee
            grid = pd.MultiIndex.from_product(
                [['Target', label_bench], ['DANNI', 'VITA'], range(11)],
                names=['Gruppo', 'Ramo', 't_sviluppo']
            ).to_frame(index=False)

            # Merge e pulizia
            df_sviluppo = pd.merge(grid, df_sql, on=['Gruppo', 'Ramo', 't_sviluppo'], how='left').fillna(0)
            
            totali = df_sql[['Gruppo', 'Ramo', 'Tot_Polizze_Coorte', 'Tot_Liquidato_Coorte']].dropna().drop_duplicates()
            df_sviluppo = df_sviluppo.drop(columns=['Tot_Polizze_Coorte', 'Tot_Liquidato_Coorte'], errors='ignore')
            df_sviluppo = pd.merge(df_sviluppo, totali, on=['Gruppo', 'Ramo'], how='left')
            
            # Calcolo cumulata
            df_sviluppo = df_sviluppo.sort_values(['Gruppo', 'Ramo', 't_sviluppo'])
            df_sviluppo['Cum_Sinistri'] = df_sviluppo.groupby(['Gruppo', 'Ramo'])['Num_Sinistri_t'].cumsum()
            df_sviluppo['Cum_Liquidato'] = df_sviluppo.groupby(['Gruppo', 'Ramo'])['Liquidato_t'].cumsum()

            # Calcolo percentuali
            df_sviluppo['Saturazione_Freq'] = (df_sviluppo['Cum_Sinistri'] / df_sviluppo['Tot_Polizze_Coorte'].replace(0, np.nan)) * 100
            df_sviluppo['Saturazione_Imp'] = (df_sviluppo['Cum_Liquidato'] / df_sviluppo['Tot_Liquidato_Coorte'].replace(0, np.nan)) * 100
            df_sviluppo = df_sviluppo.fillna(0)

            # --- PREPARAZIONE GRAFICO ---
            df_sviluppo['Serie'] = df_sviluppo['Gruppo'] + " - " + df_sviluppo['Ramo']
            metric_col = 'Saturazione_Freq' if 'Frequenza' in metrica else 'Saturazione_Imp'

            df_chart = df_sviluppo.pivot(index='t_sviluppo', columns='Serie', values=metric_col)

            # Mappatura Colori HDI
            color_map = {
                'Target - DANNI': '#007A33',
                'Target - VITA': '#C8102E',
                f'{label_bench} - DANNI': '#80BCA1',
                f'{label_bench} - VITA': '#E38796'
            }
            
            colonne_esistenti = [c for c in ['Target - DANNI', 'Target - VITA', f'{label_bench} - DANNI', f'{label_bench} - VITA'] if c in df_chart.columns]
            df_chart = df_chart[colonne_esistenti]
            colori_linee = [color_map[c] for c in colonne_esistenti]

            # Render grafico
            st.markdown(f"#### 📈 Sviluppo: {metrica.split('(')[0].strip()}")
            st.line_chart(df_chart, color=colori_linee, use_container_width=True)

            # --- TABELLA MATRICE DI SVILUPPO ---
            st.markdown("<div style='margin-top: 30px;'></div>", unsafe_allow_html=True)
            st.markdown("#### 🧮 Matrice di Sviluppo Cumulato (Primi 10 Anni)")
            
            df_matrix = df_chart.T
            df_matrix.columns = [f"Anno {int(c)}" for c in df_matrix.columns]
            
            col_config = {col: st.column_config.NumberColumn(col, format="%.1f %%") for col in df_matrix.columns}
            
            st.dataframe(df_matrix, use_container_width=True, column_config=col_config)

        except Exception as e:
            st.error(f"⚠️ Errore durante l'aggregazione di sviluppo: {e}")
