import streamlit as st
import pandas as pd
import datetime
import copy  
import warnings

# --- OTTIMIZZAZIONE 3: SINGLE MASS SAMPLING (Risolto N+1) ---
@st.cache_data(ttl=600)  
def carica_metadati_db(_conn):
    """
    Analizza la struttura del DB. Esegue una singola query per estrarre 
    un campione massivo e identificare tutte le colonne data contemporaneamente.
    """
    info = _conn.execute("PRAGMA table_info(vista_polizze)").df()
    mappa_tipi = {}
    colonne_text = []
    
    for _, row in info.iterrows():
        col_name = str(row['name'])
        tipo_sql = str(row['type']).upper()
        
        if any(x in tipo_sql for x in ["INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "REAL"]):
            mappa_tipi[col_name] = "NUMERIC"
        elif any(x in tipo_sql for x in ["DATE", "TIME", "TIMESTAMP"]):
            mappa_tipi[col_name] = "DATE"
        else:
            colonne_text.append(col_name)
            
    if colonne_text:
        # Preleva un campione di 20 righe per tutte le colonne di testo in un colpo solo
        cols_selezionate = ", ".join([f'"{c}"' for c in colonne_text])
        query = f"SELECT {cols_selezionate} FROM vista_polizze LIMIT 20"
        try:
            df_sample = _conn.execute(query).df()
            
            for col in colonne_text:
                valori = df_sample[col].dropna().astype(str).str.strip()
                valori = valori[valori != '']
                totale = len(valori)
                
                if totale == 0:
                    mappa_tipi[col] = "TEXT"
                    continue
                    
                numeri_puri = valori.str.match(r'^\d+$').sum()
                if (numeri_puri / totale) > 0.3:  
                    mappa_tipi[col] = "TEXT"
                    continue
                    
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    date_convertite = pd.to_datetime(valori, errors='coerce', dayfirst=True, format='mixed')
                    
                valide = date_convertite.notna().sum()
                if (valide / totale) >= 0.7:
                    mappa_tipi[col] = "DATE"
                else:
                    mappa_tipi[col] = "TEXT"
        except Exception:
            for col in colonne_text:
                mappa_tipi[col] = "TEXT"
                
    return mappa_tipi

def costruisci_campo_data_safe(colonna):
    return f"""CAST(COALESCE(
        TRY_STRPTIME(CAST({colonna} AS VARCHAR), '%d/%m/%Y'),
        TRY_STRPTIME(CAST({colonna} AS VARCHAR), '%Y-%m-%d'),
        TRY_STRPTIME(CAST({colonna} AS VARCHAR), '%d-%m-%Y'),
        TRY_CAST({colonna} AS DATE)
    ) AS DATE)"""

@st.cache_data(ttl=300)
def ottieni_anni_univoci(colonna, _conn):
    try:
        campo_data_safe = costruisci_campo_data_safe(colonna)
        query = f"SELECT DISTINCT YEAR({campo_data_safe}) AS anno FROM vista_polizze WHERE {colonna} IS NOT NULL ORDER BY anno DESC"
        df_anni = _conn.execute(query).df()
        return sorted(df_anni['anno'].dropna().astype(int).tolist(), reverse=True)
    except Exception:
        return [2026, 2025, 2024, 2023, 2022, 2021, 2020]

@st.cache_data(ttl=300)
def ottieni_conteggio_univoci(colonna, _conn):
    try:
        query = f'SELECT COUNT(DISTINCT "{colonna}") FROM vista_polizze'
        return int(_conn.execute(query).fetchone()[0])
    except Exception:
        return 999999

@st.cache_data(ttl=300)
def ottieni_modalita_uniche(colonna, _conn):
    try:
        query = f'SELECT DISTINCT "{colonna}" FROM vista_polizze WHERE "{colonna}" IS NOT NULL ORDER BY "{colonna}"'
        df_unici = _conn.execute(query).df()
        return df_unici[colonna].astype(str).tolist()
    except Exception:
        return []

def render_db_navigator(conn):
    st.markdown("""
        <style>
        div.stButton > button:not([data-baseweb="tab"]), 
        div.stDownloadButton > button {
            height: 2.2rem !important; 
            padding: 0px 16px !important;
            font-size: 0.85rem !important;
            font-weight: 500 !important;
            border-radius: 4px !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
        }
        div.stButton > button p, div.stDownloadButton > button p { margin-bottom: 0px !important; line-height: 1 !important; }
        
        div.stButton > button[kind="primary"] { background-color: #007A33 !important; color: white !important; border: none !important; }
        div.stButton > button[kind="primary"]:hover { background-color: #005F26 !important; }
        div.stButton > button[kind="secondary"] { background-color: white !important; color: #4B5563 !important; border: 1px solid #D1D5DB !important; }
        div.stButton > button[kind="secondary"]:hover { color: #DC2626 !important; border-color: #FCA5A5 !important; background-color: #FEF2F2 !important; }
        </style>
    """, unsafe_allow_html=True)

    if "lista_filtri" not in st.session_state: st.session_state["lista_filtri"] = []  
    if "lista_filtri_applicati" not in st.session_state: st.session_state["lista_filtri_applicati"] = []  
    if "step_righe" not in st.session_state: st.session_state["step_righe"] = 10    
    if "filtro_id_counter" not in st.session_state: st.session_state["filtro_id_counter"] = 0
    if "genera_download" not in st.session_state: st.session_state["genera_download"] = False
        
    metadati = carica_metadati_db(conn)
    elenco_colonne = list(metadati.keys())
    colonne_numeriche = [col for col, tipo in metadati.items() if tipo == "NUMERIC"]
    
    for filtro in st.session_state["lista_filtri"]:
        if "id" not in filtro:
            st.session_state["filtro_id_counter"] += 1
            filtro["id"] = st.session_state["filtro_id_counter"]
    
    # =========================================================================
    # 1. CONFIGURAZIONE FILTRI
    # =========================================================================
    st.markdown('<div class="hdi-card"><h3>🎛️ Filtri di Estrazione</h3></div>', unsafe_allow_html=True)
    
    col_pulsanti_top_1, col_pulsanti_top_2, col_spazio_dx = st.columns([1.5, 1.5, 7])
    with col_pulsanti_top_1:
        if st.button("➕ Aggiungi filtro", type="primary", use_container_width=True):
            st.session_state["filtro_id_counter"] += 1
            st.session_state["lista_filtri"].append({
                "id": st.session_state["filtro_id_counter"],
                "colonna": elenco_colonne[0],
                "operatore": "Uguale a",
                "valore": "",
                "tipo_data": "Solo Anno"
            })
            st.rerun()
            
    with col_pulsanti_top_2:
        if st.button("🗑️ Rimuovi tutti", type="secondary", use_container_width=True):
            st.session_state["lista_filtri"] = []
            st.session_state["lista_filtri_applicati"] = []
            st.session_state["step_righe"] = 10
            st.session_state["genera_download"] = False
            st.rerun()

    indici_da_rimuovere = []
    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)

    for i, filtro in enumerate(st.session_state["lista_filtri"]):
        f_id = filtro["id"]
        col_f1, col_f2, col_f3, col_f4 = st.columns([4, 2, 4, 1])
        
        with col_f1:
            tipo_dato = metadati[filtro["colonna"]]
            colonna_precedente = filtro["colonna"]
            
            if tipo_dato == "DATE":
                sub_col1, sub_col2 = st.columns([1, 1])
                with sub_col1:
                    filtro["colonna"] = st.selectbox(
                        f"Colonna##{f_id}", elenco_colonne, 
                        index=elenco_colonne.index(filtro["colonna"]), 
                        label_visibility="collapsed", key=f"col_{f_id}"
                    )
                with sub_col2:
                    filtro["tipo_data"] = st.selectbox(
                        f"TipoData##{f_id}", ["Solo Anno", "Data Intera"],
                        index=0 if filtro.get("tipo_data", "Solo Anno") == "Solo Anno" else 1,
                        key=f"tg_{f_id}",
                        label_visibility="collapsed"
                    )
            else:
                filtro["colonna"] = st.selectbox(
                    f"Colonna##{f_id}", elenco_colonne, 
                    index=elenco_colonne.index(filtro["colonna"]), 
                    label_visibility="collapsed", key=f"col_{f_id}"
                )
            
            if filtro["colonna"] != colonna_precedente:
                filtro["valore"] = ""
                tipo_nuovo = metadati[filtro["colonna"]]
                if tipo_nuovo == "DATE":
                    filtro["tipo_data"] = "Solo Anno"
                st.rerun()
        
        if tipo_dato == "TEXT": opzioni_operatori = ["Uguale a", "Diverso da", "Contiene", "Inizia con", "Incluso in (lista, sep. da virgola)"]
        elif tipo_dato == "NUMERIC": opzioni_operatori = ["Uguale a", "Diverso da", "Maggiore di (>)", "Minore di (<)", "Dal (>=)", "Fino al (<=)"]
        elif tipo_dato == "DATE": opzioni_operatori = ["Uguale a", "Diverso da", "Dopo il (>)", "Prima del (<)", "Dal (>=)", "Fino al (<=)"] if filtro.get("tipo_data", "Solo Anno") == "Solo Anno" else ["Uguale a", "Dopo la data (>)", "Prima della data (<)", "Dalla data (>=)", "Fino alla data (<=)"]

        with col_f2:
            idx_op = opzioni_operatori.index(filtro["operatore"]) if filtro["operatore"] in opzioni_operatori else 0
            filtro["operatore"] = st.selectbox(
                f"Operatore##{f_id}", opzioni_operatori, 
                index=idx_op, label_visibility="collapsed", key=f"op_{f_id}"
            )
            
        with col_f3:
            if tipo_dato == "TEXT":
                if filtro["operatore"] in ["Uguale a", "Diverso da"]:
                    SOGLIA_CARDINALITA = 150
                    conteggio_unici = ottieni_conteggio_univoci(filtro["colonna"], conn)
                    if conteggio_unici <= SOGLIA_CARDINALITA:
                        modalita_disponibili = ottieni_modalita_uniche(filtro["colonna"], conn)
                        if modalita_disponibili:
                            val_attuale = str(filtro["valore"])
                            idx_val = modalita_disponibili.index(val_attuale) if val_attuale in modalita_disponibili else 0
                            filtro["valore"] = st.selectbox(f"Valore##{f_id}", options=modalita_disponibili, index=idx_val, label_visibility="collapsed", key=f"val_txt_{f_id}")
                        else:
                            filtro["valore"] = st.text_input(f"Valore##{f_id}", value="", placeholder="Nessun dato...", label_visibility="collapsed", key=f"val_txt_vuoto_{f_id}", disabled=True)
                    else:
                        filtro["valore"] = st.text_input(f"Valore##{f_id}", value=str(filtro["valore"]), placeholder="Digita valore...", label_visibility="collapsed", key=f"val_txt_input_{f_id}")
                        st.caption(f"⚡ Alta cardinalità ({conteggio_unici:,} unici). Scrittura libera.")
                else:
                    filtro["valore"] = st.text_input(f"Valore##{f_id}", value=str(filtro["valore"]), placeholder="Cerca pattern...", label_visibility="collapsed", key=f"val_txt_input_{f_id}")
            elif tipo_dato == "NUMERIC":
                filtro["valore"] = st.text_input(f"Valore##{f_id}", value=str(filtro["valore"]), placeholder="Numero...", label_visibility="collapsed", key=f"val_num_{f_id}")
            elif tipo_dato == "DATE":
                if filtro.get("tipo_data", "Solo Anno") == "Solo Anno":
                    anni_disponibili = ottieni_anni_univoci(filtro["colonna"], conn)
                    try:
                        val_init = int(filtro["valore"])
                        idx_anno = anni_disponibili.index(val_init) if val_init in anni_disponibili else 0
                    except ValueError:
                        idx_anno = 0
                    filtro["valore"] = str(st.selectbox(f"Anno##{f_id}", options=anni_disponibili, index=idx_anno, label_visibility="collapsed", key=f"val_anno_{f_id}"))
                else:
                    val_init_date = datetime.date.today()
                    if filtro["valore"]:
                        try: val_init_date = pd.to_datetime(filtro["valore"]).date()
                        except Exception: pass
                    data_scelta = st.date_input(f"Data##{f_id}", value=val_init_date, label_visibility="collapsed", key=f"val_data_{f_id}")
                    filtro["valore"] = data_scelta.strftime("%Y-%m-%d")
            
        with col_f4:
            if st.button("🗑️", key=f"del_{f_id}", help="Elimina riga", type="secondary", use_container_width=True):
                indici_da_rimuovere.append(i)

    if indici_da_rimuovere:
        for idx in sorted(indici_da_rimuovere, reverse=True):
            st.session_state["lista_filtri"].pop(idx)
        st.rerun()

    ha_modifiche_pendenti = (st.session_state["lista_filtri"] != st.session_state["lista_filtri_applicati"])
    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    
    col_applica, col_stato, col_spazio_app = st.columns([1.5, 4, 4.5])
    with col_applica:
        if st.button("⚡ Applica Filtri", type="primary" if ha_modifiche_pendenti else "secondary", use_container_width=True):
            st.session_state["lista_filtri_applicati"] = copy.deepcopy(st.session_state["lista_filtri"])
            st.session_state["genera_download"] = False # Reset status download
            st.rerun()
            
    with col_stato:
        if ha_modifiche_pendenti:
            st.warning("⚠️ Modifiche pendenti da applicare.")
        else:
            st.success("✅ Filtri sincronizzati con il database.")

    # =========================================================================
    # 2. COSTRUZIONE DELLE CLAUSOLE SQL
    # =========================================================================
    clausole_where = []
    colonne_attive_filtrate = []
    
    for filtro_app in st.session_state["lista_filtri_applicati"]:
        val_safe = str(filtro_app["valore"]).replace("'", "''").strip()
        if val_safe:
            op = filtro_app["operatore"]
            col = filtro_app["colonna"]
            tipo_dato = metadati[col]
            colonne_attive_filtrate.append(col)
            
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
                campo_sql_safe = costruisci_campo_data_safe(col)
                if filtro_app.get("tipo_data", "Solo Anno") == "Solo Anno":
                    campo_anno = f"YEAR({campo_sql_safe})"
                    if op == "Uguale a": clausole_where.append(f"{campo_anno} = {val_safe}")
                    elif op == "Diverso da": clausole_where.append(f"{campo_anno} <> {val_safe}")
                    elif op == "Dopo il (>)": clausole_where.append(f"{campo_anno} > {val_safe}")
                    elif op == "Prima del (<)": clausole_where.append(f"{campo_anno} < {val_safe}")
                    elif op == "Dal (>=)": clausole_where.append(f"{campo_anno} >= {val_safe}")
                    elif op == "Fino al (<=)": clausole_where.append(f"{campo_anno} <= {val_safe}")
                else:
                    if op == "Uguale a": clausole_where.append(f"{campo_sql_safe} = CAST('{val_safe}' AS DATE)")
                    elif op == "Dopo la data (>)": clausole_where.append(f"{campo_sql_safe} > CAST('{val_safe}' AS DATE)")
                    elif op == "Prima della data (<)": clausole_where.append(f"{campo_sql_safe} < CAST('{val_safe}' AS DATE)")
                    elif op == "Dalla data (>=)": clausole_where.append(f"{campo_sql_safe} >= CAST('{val_safe}' AS DATE)")
                    elif op == "Fino alla data (<=)": clausole_where.append(f"{campo_sql_safe} <= CAST('{val_safe}' AS DATE)")

    stringa_where_completa = " WHERE " + " AND ".join(clausole_where) if clausole_where else ""

    try:
        totale_righe = conn.execute(f"SELECT COUNT(*) FROM vista_polizze{stringa_where_completa}").fetchone()[0]
    except Exception as e:
        st.error(f"⚠️ Errore di sintassi nei filtri: {e}")
        return

    # =========================================================================
    # 3. PREVIEW DATI
    # =========================================================================
    st.markdown('<div class="hdi-card"><h3>👀 Preview e Download</h3></div>', unsafe_allow_html=True)
    if totale_righe > 0:
        
        lista_badges = []
        for f in st.session_state["lista_filtri_applicati"]:
            valore_filtro = f.get("valore", "").strip()
            if valore_filtro:
                col_name = f["colonna"]
                op_label = f["operatore"].lower()
                
                if metadati[col_name] == "DATE" and f.get("tipo_data") == "Solo Anno":
                    testo_badge = f"📅 Anno({col_name}) {op_label} {valore_filtro}"
                elif metadati[col_name] == "DATE":
                    testo_badge = f"📅 {col_name} {op_label} {valore_filtro}"
                elif metadati[col_name] == "NUMERIC":
                    testo_badge = f"🔢 {col_name} {op_label} {valore_filtro}"
                else:
                    testo_badge = f"🔤 {col_name} {op_label} '{valore_filtro}'"
                    
                html_badge = f"""
                <span style="background-color: #E6F2EB; color: #005F26; padding: 6px 14px; border-radius: 20px; font-size: 0.8rem; font-weight: 600; border: 1px solid #C2E0CC;">{testo_badge}</span>
                """
                lista_badges.append(html_badge)
        
        if lista_badges:
            st.markdown("**Filtri applicati:**")
            st.markdown(f'<div style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 15px;">{"".join(lista_badges)}</div>', unsafe_allow_html=True)

        col_info_view, col_dl = st.columns([3, 1])
        with col_info_view:
            righe_mostrate = min(st.session_state["step_righe"], totale_righe)
            st.caption(f"Mostrate {righe_mostrate:,} righe di anteprima su {totale_righe:,} record totali.")
            
        with col_dl:
            query_completa = f"SELECT * FROM vista_polizze{stringa_where_completa}"
            
            # --- OTTIMIZZAZIONE 4: DEFERRED CSV GENERATION ---
        with col_dl:
            @st.cache_data(ttl=60)
            def genera_csv(query):
                df_download = conn.execute(query).df()
                # Aggiungiamo sep=';' e decimal=',' per l'export in stile italiano
                return df_download.to_csv(index=False, sep=';', decimal=',').encode('utf-8')
                
                with st.spinner("Creazione CSV in corso..."):
                    csv_data = genera_csv(query_completa)
                
                st.download_button(
                    label="📥 Salva file (Pronto)",
                    data=csv_data,
                    file_name="estrazione_filtrata.csv",
                    mime="text/csv",
                    type="primary",
                    use_container_width=True
                )
            else:
                if st.button("⚙️ Prepara Download", use_container_width=True):
                    st.session_state["genera_download"] = True
                    st.rerun()

        query_anteprima = f"SELECT * FROM vista_polizze{stringa_where_completa} LIMIT {st.session_state['step_righe']}"
        df_preview = conn.execute(query_anteprima).df()
        
# --- NUOVO CODICE (PIÙ ROBUSTO) ---
        # Configurazione nativa di Streamlit per i numeri
        column_config = {}
        colonne_float = df_preview.select_dtypes(include=['float64', 'float32']).columns.tolist()
        
        for col in colonne_float:
            column_config[col] = st.column_config.NumberColumn(
                col,
                format=",.2f" # Format specificato nativamente
            )
        
        # Rendering diretto del dataframe (senza Styler)
        st.dataframe(
            df_preview, 
            use_container_width=True,
            column_config=column_config
        )
        
        if st.session_state["step_righe"] < totale_righe:
            if st.button("🔽 Mostra altre 10 righe", use_container_width=True):
                st.session_state["step_righe"] += 10
                st.rerun()
    else:
        st.warning("Nessun record da mostrare con i filtri applicati.")

    # =========================================================================
    # 4. REPORT TABELLARE DI SINTESI
    # =========================================================================
    st.markdown('<div class="hdi-card"><h3>📈 Statistiche di Sintesi</h3></div>', unsafe_allow_html=True)
    if totale_righe == 0:
        st.warning("Nessun dato disponibile.")
    elif not colonne_numeriche:
        st.info("Nessuna colonna numerica rilevata.")
    else:
        colonne_stats_scelte = st.multiselect(
            "Seleziona i campi numerici da analizzare:",
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
                
                for metric_col in ['SUM', 'AVG', 'MAX', 'MIN']:
                    col_key = metric_col if metric_col in df_stats_formatted.columns else metric_col.lower()
                    if col_key in df_stats_formatted.columns:
                        df_stats_formatted[col_key] = df_stats_formatted[col_key].apply(
                            lambda x: f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") if pd.notnull(x) else "-"
                        )
                
                df_stats_formatted.columns = ["Variabile Finanziaria", "SOMMA", "MEDIA", "MASSIMO", "MINIMO"]
                st.dataframe(df_stats_formatted, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Errore durante il calcolo delle statistiche: {e}")
