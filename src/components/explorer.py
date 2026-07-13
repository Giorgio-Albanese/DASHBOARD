import streamlit as st
import pandas as pd

def carica_metadati_db(conn):
    """Recupera le colonne e i tipi di dati per mappare i filtri corretti"""
    info = conn.execute("PRAGMA table_info(vista_polizze)").df()
    mappa_tipi = {}
    for _, row in info.iterrows():
        tipo_sql = str(row['type']).upper()
        if any(x in tipo_sql for x in ["INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC"]):
            mappa_tipi[row['name']] = "NUMERIC"
        else:
            mappa_tipi[row['name']] = "TEXT"
    return mappa_tipi

def render_db_navigator(conn):
    st.markdown("### 🔍 Esploratore Dinamico con Report di Sintesi")
    
    # --- INIZIALIZZAZIONE DELLO STATO ---
    if "lista_filtri" not in st.session_state:
        st.session_state["lista_filtri"] = []  
    if "step_righe" not in st.session_state:
        st.session_state["step_righe"] = 10    
        
    metadati = carica_metadati_db(conn)
    elenco_colonne = list(metadati.keys())
    colonne_numeriche = [col for col, tipo in metadati.items() if tipo == "NUMERIC"]
    
    # =========================================================================
    # PANNELLO 1: FILTRI DI RIGA CONDIZIONALI (MINIMIZZABILE)
    # =========================================================================
    with st.expander("🛠️ 1. Configura Filtri di Riga Condizionali", expanded=True):
        st.caption("Aggiungi filtri multipli in AND. Lascia vuoto il valore per disattivare il singolo filtro.")
        
        if st.button("➕ Aggiungi un nuovo filtro"):
            st.session_state["lista_filtri"].append({
                "colonna": elenco_colonne[0],
                "operatore": "Uguale a",
                "valore": ""
            })
            st.rerun()

        clausole_where = []
        indici_da_rimuovere = []
        
        for i, filtro in enumerate(st.session_state["lista_filtri"]):
            col_f1, col_f2, col_f3, col_f4 = st.columns([3, 2, 4, 1])
            
            with col_f1:
                filtro["colonna"] = st.selectbox(f"Colonna##{i}", elenco_colonne, index=elenco_colonne.index(filtro["colonna"]), label_visibility="collapsed", key=f"col_{i}")
            
            tipo_dato = metadati[filtro["colonna"]]
            opzioni_operatori = ["Uguale a", "Diverso da", "Incluso in (lista, sep. da virgola)"]
            if tipo_dato == "TEXT":
                opzioni_operatori += ["Contiene", "Inizia con"]
            else:
                opzioni_operatori += ["Maggiore di (>)", "Minore di (<)"]
                
            with col_f2:
                idx_op = 0
                if filtro["operatore"] in opzioni_operatori:
                    idx_op = opzioni_operatori.index(filtro["operatore"])
                filtro["operatore"] = st.selectbox(f"Operatore##{i}", opzioni_operatori, index=idx_op, label_visibility="collapsed", key=f"op_{i}")
                
            with col_f3:
                filtro["valore"] = st.text_input(f"Valore##{i}", value=filtro["valore"], placeholder="Valore da cercare...", label_visibility="collapsed", key=f"val_{i}")
                
            with col_f4:
                if st.button("🗑️", key=f"del_{i}", help="Rimuovi questo filtro"):
                    indici_da_rimuovere.append(i)

            val_safe = str(filtro["valore"]).replace("'", "''").strip()
            if val_safe:
                op = filtro["operatore"]
                col = filtro["colonna"]
                
                if op == "Uguale a":
                    clausole_where.append(f"{col} = '{val_safe}'" if tipo_dato == "TEXT" else f"{col} = {val_safe}")
                elif op == "Diverso da":
                    clausole_where.append(f"{col} <> '{val_safe}'" if tipo_dato == "TEXT" else f"{col} <> {val_safe}")
                elif op == "Contiene":
                    clausole_where.append(f"{col} ILIKE '%{val_safe}%'")
                elif op == "Inizia con":
                    clausole_where.append(f"{col} ILIKE '{val_safe}%'")
                elif op == "Maggiore di (>)":
                    clausole_where.append(f"{col} > {val_safe}")
                elif op == "Minore di (<)":
                    clausole_where.append(f"{col} < {val_safe}")
                elif op == "Incluso in (lista, sep. da virgola)":
                    elementi = ", ".join([f"'{x.strip()}'" if tipo_dato == "TEXT" else x.strip() for x in val_safe.split(",")])
                    clausole_where.append(f"{col} IN ({elementi})")

        if indici_da_rimuovere:
            for idx in sorted(indici_da_rimuovere, reverse=True):
                st.session_state["lista_filtri"].pop(idx)
            st.rerun()

    stringa_where_completa = " WHERE " + " AND ".join(clausole_where) if clausole_where else ""

    # Calcolo preliminare velocissimo del totale righe filtrate
    try:
        totale_righe = conn.execute(f"SELECT COUNT(*) FROM vista_polizze{stringa_where_completa}").fetchone()[0]
    except Exception as e:
        st.error(f"⚠️ Errore di sintassi nei filtri condizionali: {e}")
        return

    # =========================================================================
    # PANNELLO 2: REPORT TABELLARE DI SINTESI (MINI-PIVOT MULTI-METRICA)
    # =========================================================================
    with st.expander("📈 2. Report Tabellare di Sintesi (Mini-Pivot)", expanded=True):
        if totale_righe == 0:
            st.warning("Nessun dato disponibile con i filtri correnti per generare le statistiche.")
        elif not colonne_numeriche:
            st.info("Nessuna colonna numerica rilevata nel database per il calcolo delle metriche finanziarie.")
        else:
            st.markdown(f"**KPI di Base:** Polizze Totali in Vista: `{totale_righe:,}`")
            
            # Scelta di quali colonne numeriche includere nel report
            colonne_stats_scelte = st.multiselect(
                "Seleziona i campi numerici da analizzare contemporaneamente:",
                options=colonne_numeriche,
                default=colonne_numeriche[:3] if len(colonne_numeriche) > 3 else colonne_numeriche
            )
            
            if colonne_stats_scelte:
                # Costruiamo una query combinata via UNION ALL per estrarre tutto in un unico colpo d'occhio
                pezzi_query = []
                for col in colonne_stats_scelte:
                    pezzi_query.append(f"""
                        SELECT 
                            '{col}' AS [Variabile Finanziaria], 
                            SUM({col}) AS SOMMA, 
                            AVG({col}) AS MEDIA, 
                            MAX({col}) AS MASSIMO, 
                            MIN({col}) AS MINIMO 
                        FROM vista_polizze{stringa_where_completa}
                    """)
                
                query_pivot_completa = " UNION ALL ".join(pezzi_query)
                
                try:
                    df_stats = conn.execute(query_pivot_completa).df()
                    
                    # Formattazione professionale dei numeri per la visualizzazione aziendale
                    df_stats_formatted = df_stats.copy()
                    for metric_col in ['SOMMA', 'MEDIA', 'MASSIMO', 'MINIMO']:
                        df_stats_formatted[metric_col] = df_stats_formatted[metric_col].apply(
                            lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if pd.notnull(x) else "-"
                        )
                    
                    # Mostra la tabella pivot di sintesi
                    st.dataframe(df_stats_formatted, use_container_width=True, hide_index=True)
                    
                except Exception as e:
                    st.error(f"Errore durante il calcolo del report di sintesi: {e}")
            else:
                st.caption("Seleziona almeno una colonna numerica per visualizzare la tabella dei KPI.")

    # =========================================================================
    # PANNELLO 3: SELEZIONE COLONNE OUTPUT TABELLA (MINIMIZZABILE)
    # =========================================================================
    with st.expander("📊 3. Configura Colonne da Mostrare nella Preview", expanded=False):
        colonne_scelte = st.multiselect(
            "Spunta i campi che vuoi vedere nell'anteprima tabellare (Vuoto = Tutti i campi):",
            options=elenco_colonne,
            default=[]
        )
        colonne_sql = ", ".join(colonne_scelte) if colonne_scelte else "*"

    # =========================================================================
    # PANNELLO 4: PREVIEW DATI E DOWNLOAD (MINIMIZZABILE)
    # =========================================================================
    with st.expander("👀 4. Preview dei Dati (Snippet) e Download Estrazione", expanded=True):
        if totale_righe > 0:
            col_info_view, col_dl = st.columns([3, 1])
            with col_info_view:
                righe_mostrate = min(st.session_state["step_righe"], totale_righe)
                st.caption(f"Mostrate {righe_mostrate:,} righe di anteprima su {totale_righe:,} record totali.")
                
            with col_dl:
                @st.cache_data(ttl=60)
                def genera_csv(query):
                    df_download = conn.execute(query).df()
                    return df_download.to_csv(index=False).encode('utf-8')
                    
                query_completa = f"SELECT {colonne_sql} FROM vista_polizze{stringa_where_completa}"
                csv_data = genera_csv(query_completa)
                
                st.download_button(
                    label="📥 Scarica Vista Corrente (CSV)",
                    data=csv_data,
                    file_name="estrazione_filtrata.csv",
                    mime="text/csv",
                    use_container_width=True
                )

            # Query limitata per la preview tabellare reattiva
            query_anteprima = f"SELECT {colonne_sql} FROM vista_polizze{stringa_where_completa} LIMIT {st.session_state['step_righe']}"
            df_preview = conn.execute(query_anteprima).df()
            
            st.dataframe(df_preview, use_container_width=True)
            
            # Tasto "Mostra Altro"
            if st.session_state["step_righe"] < totale_righe:
                if st.button("🔽 Mostra altre 10 righe", use_container_width=True):
                    st.session_state["step_righe"] += 10
                    st.rerun()
        else:
            st.warning("Nessun record da mostrare. Modifica o resetta i filtri di riga al punto 1.")
