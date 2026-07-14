import streamlit as st
import pandas as pd
import datetime

def carica_metadati_db(conn):
    """Recupera le colonne e i tipi di dati per mappare i filtri corretti"""
    info = conn.execute("PRAGMA table_info(vista_polizze)").df()
    mappa_tipi = {}
    for _, row in info.iterrows():
        tipo_sql = str(row['type']).upper()
        if any(x in tipo_sql for x in ["INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "REAL"]):
            mappa_tipi[row['name']] = "NUMERIC"
        elif any(x in tipo_sql for x in ["DATE", "TIME", "TIMESTAMP"]):
            mappa_tipi[row['name']] = "DATE"
        else:
            mappa_tipi[row['name']] = "TEXT"
    return mappa_tipi

@st.cache_data(ttl=300)
def ottieni_anni_univoci(colonna, _conn):
    """Estrae gli anni univoci da una colonna data per popolare il dropdown"""
    try:
        query = f"SELECT DISTINCT YEAR({colonna}) AS anno FROM vista_polizze WHERE {colonna} IS NOT NULL ORDER BY anno DESC"
        df_anni = _conn.execute(query).df()
        return sorted(df_anni['anno'].dropna().astype(int).tolist(), reverse=True)
    except Exception:
        return [2026, 2025, 2024, 2023, 2022, 2021, 2020]

def render_db_navigator(conn):
    st.markdown("### 🔍 Esploratore Dinamico del Portafoglio")
    
    # --- INIZIALIZZAZIONE DELLO STATO ---
    if "lista_filtri" not in st.session_state:
        st.session_state["lista_filtri"] = []  
    if "step_righe" not in st.session_state:
        st.session_state["step_righe"] = 10    
        
    metadati = carica_metadati_db(conn)
    elenco_colonne = list(metadati.keys())
    colonne_numeriche = [col for col, tipo in metadati.items() if tipo == "NUMERIC"]
    
    # =========================================================================
    # 1. CONFIGURAZIONE FILTRI (MINIMIZZABILE)
    # =========================================================================
    with st.expander("🛠️ 1. Configura Filtri di Riga Condizionali", expanded=True):
        st.caption("Filtri multipli in AND. Gestione intelligente per i campi DATA con estrazione automatica dell'anno.")
        
        if st.button("➕ Aggiungi un nuovo filtro"):
            st.session_state["lista_filtri"].append({
                "colonna": elenco_colonne[0],
                "operatore": "Uguale a",
                "valore": "",
                "tipo_data": "Solo Anno"
            })
            st.rerun()

        clausole_where = []
        indici_da_rimuovere = []
        
        for i, filtro in enumerate(st.session_state["lista_filtri"]):
            col_f1, col_f2, col_f3, col_f4 = st.columns([3, 2, 4, 1])
            
            with col_f1:
                filtro["colonna"] = st.selectbox(
                    f"Colonna##{i}", elenco_colonne, 
                    index=elenco_colonne.index(filtro["colonna"]), 
                    label_visibility="collapsed", key=f"col_{i}"
                )
                
                tipo_dato = metadati[filtro["colonna"]]
                if tipo_dato == "DATE":
                    filtro["tipo_data"] = st.selectbox(
                        f"TipoData##{i}", ["Solo Anno", "Data Intera"],
                        index=0 if filtro.get("tipo_data", "Solo Anno") == "Solo Anno" else 1,
                        key=f"tg_{i}"
                    )
            
            tipo_dato = metadati[filtro["colonna"]]
            if tipo_dato == "TEXT":
                opzioni_operatori = ["Uguale a", "Diverso da", "Contiene", "Inizia con", "Incluso in (lista, sep. da virgola)"]
            elif tipo_dato == "NUMERIC":
                opzioni_operatori = ["Uguale a", "Diverso da", "Maggiore di (>)", "Minore di (<)", "Dal (>=)", "Fino al (<=)"]
            elif tipo_dato == "DATE":
                if filtro.get("tipo_data") == "Solo Anno":
                    opzioni_operatori = ["Uguale a", "Diverso da", "Dopo il (>)", "Prima del (<)", "Dal (>=)", "Fino al (<=)"]
                else:
                    opzioni_operatori = ["Uguale a", "Dopo la data (>)", "Prima della data (<)", "Dalla data (>=)", "Fino alla data (<=)"]

            with col_f2:
                idx_op = 0
                if filtro["operatore"] in opzioni_operatori:
                    idx_op = opzioni_operatori.index(filtro["operatore"])
                filtro["operatore"] = st.selectbox(
                    f"Operatore##{i}", opzioni_operatori, 
                    index=idx_op, label_visibility="collapsed", key=f"op_{i}"
                )
                
            with col_f3:
                if tipo_dato == "TEXT" or tipo_dato == "NUMERIC":
                    filtro["valore"] = st.text_input(
                        f"Valore##{i}", value=str(filtro["valore"]), 
                        placeholder="Inserisci valore...", label_visibility="collapsed", key=f"val_{i}"
                    )
                elif tipo_dato == "DATE":
                    if filtro.get("tipo_data") == "Solo Anno":
                        anni_disponibili = ottieni_anni_univoci(filtro["colonna"], conn)
                        try:
                            val_init = int(filtro["valore"])
                            idx_anno = anni_disponibili.index(val_init) if val_init in anni_disponibili else 0
                        except ValueError:
                            idx_anno = 0
                            
                        anno_scelto = st.selectbox(
                            f"Anno##{i}", options=anni_disponibili, 
                            index=idx_anno, label_visibility="collapsed", key=f"val_anno_{i}"
                        )
                        filtro["valore"] = str(anno_scelto)
                    else:
                        val_init_date = datetime.date.today()
                        if filtro["valore"]:
                            try:
                                val_init_date = pd.to_datetime(filtro["valore"]).date()
                            except Exception:
                                pass
                        data_scelta = st.date_input(
                            f"Data##{i}", value=val_init_date, 
                            label_visibility="collapsed", key=f"val_data_{i}"
                        )
                        filtro["valore"] = data_scelta.strftime("%Y-%m-%d")
                
            with col_f4:
                if st.button("🗑️", key=f"del_{i}", help="Rimuovi questo filtro"):
                    indici_da_rimuovere.append(i)

            val_safe = str(filtro["valore"]).replace("'", "''").strip()
            if val_safe:
                op = filtro["operatore"]
                col = filtro["colonna"]
                
                if tipo_dato == "TEXT":
                    if op == "Uguale a": clausole_where.append(f"{col} = '{val_safe}'")
                    elif op == "Diverso da": clausole_where.append(f"{col} <> '{val_safe}'")
                    elif op == "Contiene": clausole_where.append(f"{col} ILIKE '%{val_safe}%'")
                    elif op == "Inizia con": clausole_where.append(f"{col} ILIKE '{val_safe}%'")
                    elif op == "Incluso in (lista, sep. da virgola)":
                        elementi = ", ".join([f"'{x.strip()}'" for x in val_safe.split(",")])
                        clausole_where.append(f"{col} IN ({elementi})")
                
                elif tipo_dato == "NUMERIC":
                    if op == "Uguale a": clausole_where.append(f"{col} = {val_safe}")
                    elif op == "Diverso da": clausole_where.append(f"{col} <> {val_safe}")
                    elif op == "Maggiore di (>)": clausole_where.append(f"{col} > {val_safe}")
                    elif op == "Minore di (<)": clausole_where.append(f"{col} < {val_safe}")
                    elif op == "Dal (>=)": clausole_where.append(f"{col} >= {val_safe}")
                    elif op == "Fino al (<=)": clausole_where.append(f"{col} <= {val_safe}")
                
                elif tipo_dato == "DATE":
                    if filtro.get("tipo_data") == "Solo Anno":
                        campo_sql = f"YEAR({col})"
                        if op == "Uguale a": clausole_where.append(f"{campo_sql} = {val_safe}")
                        elif op == "Diverso da": clausole_where.append(f"{campo_sql} <> {val_safe}")
                        elif op == "Dopo il (>)": clausole_where.append(f"{campo_sql} > {val_safe}")
                        elif op == "Prima del (<)": clausole_where.append(f"{campo_sql} < {val_safe}")
                        elif op == "Dal (>=)": clausole_where.append(f"{campo_sql} >= {val_safe}")
                        elif op == "Fino al (<=)": clausole_where.append(f"{campo_sql} <= {val_safe}")
                    else:
                        if op == "Uguale a": clausole_where.append(f"{col} = '{val_safe}'")
                        elif op == "Dopo la data (>)": clausole_where.append(f"{col} > '{val_safe}'")
                        elif op == "Prima della data (<)": clausole_where.append(f"{col} < '{val_safe}'")
                        elif op == "Dalla data (>=)": clausole_where.append(f"{col} >= '{val_safe}'")
                        elif op == "Fino alla data (<=)": clausole_where.append(f"{col} <= '{val_safe}'")

        if indici_da_rimuovere:
            for idx in sorted(indici_da_rimuovere, reverse=True):
                st.session_state["lista_filtri"].pop(idx)
            st.rerun()

    stringa_where_completa = " WHERE " + " AND ".join(clausole_where) if clausole_where else ""

    try:
        totale_righe = conn.execute(f"SELECT COUNT(*) FROM vista_polizze{stringa_where_completa}").fetchone()[0]
    except Exception as e:
        st.error(f"⚠️ Errore di sintassi nei filtri condizionali: {e}")
        return

    # =========================================================================
    # 2. REPORT TABELLARE DI SINTESI (MINI-PIVOT)
    # =========================================================================
    with st.expander("📈 2. Report Tabellare di Sintesi (Mini-Pivot)", expanded=True):
        if totale_righe == 0:
            st.warning("Nessun dato disponibile con i filtri correnti per generare le statistiche.")
        elif not colonne_numeriche:
            st.info("Nessuna colonna numerica rilevata nel database per il calcolo delle metriche.")
        else:
            st.markdown(f"**KPI di Base:** Polizze Totali in Vista: `{totale_righe:,}`")
            
            colonne_stats_scelte = st.multiselect(
                "Seleziona i campi numerici da analizzare contemporaneamente:",
                options=colonne_numeriche,
                default=colonne_numeriche[:3] if len(colonne_numeriche) > 3 else colonne_numeriche
            )
            
            if colonne_stats_scelte:
                pezzi_query = []
                for col in colonne_stats_scelte:
                    pezzi_query.append(f"""
                        SELECT 
                            '{col}' AS "Variabile Finanziaria", 
                            SUM({col}) AS SOMMA, 
                            AVG({col}) AS MEDIA, 
                            MAX({col}) AS MASSIMO, 
                            MIN({col}) AS MINIMO 
                        FROM vista_polizze{stringa_where_completa}
                    """)
                
                query_pivot_completa = " UNION ALL ".join(pezzi_query)
                
                try:
                    df_stats = conn.execute(query_pivot_completa).df()
                    df_stats_formatted = df_stats.copy()
                    for metric_col in ['SOMMA', 'MEDIA', 'MASSIMO', 'MINIMO']:
                        df_stats_formatted[metric_col] = df_stats_formatted[metric_col].apply(
                            lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if pd.notnull(x) else "-"
                        )
                    st.dataframe(df_stats_formatted, use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(f"Errore durante il calcolo del report di sintesi: {e}")
            else:
                st.caption("Seleziona almeno una colonna numerica per visualizzare la tabella dei KPI.")

    # =========================================================================
    # 3. PREVIEW DATI, BADGES & HIGHLIGHT (MINIMIZZABILE)
    # =========================================================================
    with st.expander("👀 3. Preview dei Dati (Snippet) e Download Estrazione completa", expanded=True):
        if totale_righe > 0:
            
            # --- GENERAZIONE DEI BADGES DEI FILTRI ATTIVI ---
            lista_badges = []
            colonne_attive_filtrate = []
            
            for f in st.session_state["lista_filtri"]:
                valore_filtro = f.get("valore", "").strip()
                if valore_filtro:
                    col_name = f["colonna"]
                    op_label = f["operatore"].lower()
                    colonne_attive_filtrate.append(col_name)
                    
                    if metadati[col_name] == "DATE" and f.get("tipo_data") == "Solo Anno":
                        testo_badge = f"📅 Anno({col_name}) {op_label} {valore_filtro}"
                    elif metadati[col_name] == "DATE":
                        testo_badge = f"📅 {col_name} {op_label} {valore_filtro}"
                    elif metadati[col_name] == "NUMERIC":
                        testo_badge = f"🔢 {col_name} {op_label} {valore_filtro}"
                    else:
                        testo_badge = f"🔤 {col_name} {op_label} '{valore_filtro}'"
                        
                    html_badge = f"""
                    <span style="
                        background-color: #1E293B; 
                        color: #38BDF8; 
                        padding: 4px 10px; 
                        border-radius: 8px; 
                        font-size: 0.8rem; 
                        font-weight: 600;
                        margin-right: 6px; 
                        display: inline-block; 
                        margin-bottom: 6px;
                        border: 1px solid #38BDF8;
                    ">{testo_badge}</span>
                    """
                    lista_badges.append(html_badge)
            
            if lista_badges:
                st.markdown("**Filtri applicati correnti:**")
                st.markdown("".join(lista_badges), unsafe_allow_html=True)
            else:
                st.caption("Nessun filtro attivo (Visualizzazione totale portafoglio)")

            # Layout controlli inferiori (Info righe + Tasto download per l'estrazione COMPLETA)
            col_info_view, col_dl = st.columns([3, 1])
            with col_info_view:
                righe_mostrate = min(st.session_state["step_righe"], totale_righe)
                st.caption(f"Mostrate {righe_mostrate:,} righe di anteprima su {totale_righe:,} record totali.")
                
            with col_dl:
                @st.cache_data(ttl=60)
                def genera_csv(query):
                    df_download = conn.execute(query).df()
                    return df_download.to_csv(index=False).encode('utf-8')
                    
                # Rimosso il selettore colonne: ora facciamo direttamente SELECT *
                query_completa = f"SELECT * FROM vista_polizze{stringa_where_completa}"
                csv_data = genera_csv(query_completa)
                
                st.download_button(
                    label="📥 Scarica Intero CSV Filtrato",
                    data=csv_data,
                    file_name="estrazione_filtrata_completa.csv",
                    mime="text/csv",
                    use_container_width=True,
                    help="Scarica tutte le righe che soddisfano i filtri correnti (non solo l'anteprima)."
                )

            # Query limitata per la preview tabellare
            query_anteprima = f"SELECT * FROM vista_polizze{stringa_where_completa} LIMIT {st.session_state['step_righe']}"
            df_preview = conn.execute(query_anteprima).df()
            
            # --- EVIDENZIAZIONE COLONNE FILTRATE ---
            def applica_evidenziatore(colonna_dati):
                if colonna_dati.name in colonne_attive_filtrate:
                    return ['background-color: rgba(56, 189, 248, 0.12)'] * len(colonna_dati)
                return [''] * len(colonna_dati)

            if len(colonne_attive_filtrate) > 0 and not df_preview.empty:
                df_visualizzazione = df_preview.style.apply(applica_evidenziatore, axis=0)
            else:
                df_visualizzazione = df_preview

            st.dataframe(df_visualizzazione, use_container_width=True)
            
            if st.session_state["step_righe"] < totale_righe:
                if st.button("🔽 Mostra altre 10 righe", use_container_width=True):
                    st.session_state["step_righe"] += 10
                    st.rerun()
        else:
            st.warning("Nessun record da mostrare. Modifica o resetta i filtri di riga al punto 1.")
