import streamlit as st
import pandas as pd
import datetime
import copy  # Necessario per clonare lo stato dei filtri senza riferimenti condivisi

def carica_metadati_db(conn):
    """Recupera le colonne e mappa i filtri corretti, forzando la gestione data se il nome lo suggerisce"""
    info = conn.execute("PRAGMA table_info(vista_polizze)").df()
    mappa_tipi = {}
    for _, row in info.iterrows():
        col_name = str(row['name'])
        tipo_sql = str(row['type']).upper()
        
        if any(x in tipo_sql for x in ["INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "REAL"]):
            mappa_tipi[col_name] = "NUMERIC"
        elif any(x in tipo_sql for x in ["DATE", "TIME", "TIMESTAMP"]) or any(x in col_name.upper() for x in ["DATA", "DECORRENZA", "SCADENZA", "PERIODO"]):
            mappa_tipi[col_name] = "DATE"
        else:
            mappa_tipi[col_name] = "TEXT"
    return mappa_tipi

def costruisci_campo_data_safe(colonna):
    """Genera un'espressione SQL DuckDB a cascata capace di digerire qualsiasi formato di data"""
    return f"""CAST(COALESCE(
        TRY_STRPTIME(CAST({colonna} AS VARCHAR), '%d/%m/%Y'),
        TRY_STRPTIME(CAST({colonna} AS VARCHAR), '%Y-%m-%d'),
        TRY_STRPTIME(CAST({colonna} AS VARCHAR), '%d-%m-%Y'),
        TRY_CAST({colonna} AS DATE)
    ) AS DATE)"""

@st.cache_data(ttl=300)
def ottieni_anni_univoci(colonna, _conn):
    """Estrae in modo sicuro gli anni dalle date usando il parser multi-formato"""
    try:
        campo_data_safe = costruisci_campo_data_safe(colonna)
        query = f"SELECT DISTINCT YEAR({campo_data_safe}) AS anno FROM vista_polizze WHERE {colonna} IS NOT NULL ORDER BY anno DESC"
        df_anni = _conn.execute(query).df()
        return sorted(df_anni['anno'].dropna().astype(int).tolist(), reverse=True)
    except Exception:
        return [2026, 2025, 2024, 2023, 2022, 2021, 2020]

# --- NUOVA FUNZIONE DI SICUREZZA ---
@st.cache_data(ttl=300)
def ottieni_conteggio_univoci(colonna, _conn):
    """Esegue un conteggio super veloce della cardinalità della colonna lato database"""
    try:
        query = f'SELECT COUNT(DISTINCT "{colonna}") FROM vista_polizze'
        return int(_conn.execute(query).fetchone()[0])
    except Exception:
        return 999999  # Nel dubbio, blocca la tendina e attiva la scrittura manuale

@st.cache_data(ttl=300)
def ottieni_modalita_uniche(colonna, _conn):
    """Estrae in modo sicuro le modalità uniche per le colonne di tipo TEXT"""
    try:
        query = f'SELECT DISTINCT "{colonna}" FROM vista_polizze WHERE "{colonna}" IS NOT NULL ORDER BY "{colonna}"'
        df_unici = _conn.execute(query).df()
        return df_unici[colonna].astype(str).tolist()
    except Exception:
        return []

def render_db_navigator(conn):
    # --- INIZIALIZZAZIONE DELLO STATO ---
    if "lista_filtri" not in st.session_state:
        st.session_state["lista_filtri"] = []  
    if "lista_filtri_applicati" not in st.session_state:
        st.session_state["lista_filtri_applicati"] = []  # Stato effettivo usato per la query
    if "step_righe" not in st.session_state:
        st.session_state["step_righe"] = 10    
    if "filtro_id_counter" not in st.session_state:
        st.session_state["filtro_id_counter"] = 0
        
    metadati = carica_metadati_db(conn)
    elenco_colonne = list(metadati.keys())
    colonne_numeriche = [col for col, tipo in metadati.items() if tipo == "NUMERIC"]
    
    # Controllo di sicurezza per gli ID persistenti
    for filtro in st.session_state["lista_filtri"]:
        if "id" not in filtro:
            st.session_state["filtro_id_counter"] += 1
            filtro["id"] = st.session_state["filtro_id_counter"]
    
    # =========================================================================
    # 1. CONFIGURAZIONE FILTRI (Stile .hdi-card)
    # =========================================================================
    st.markdown('<div class="hdi-card"><h3>🎛️ Filtri</h3></div>', unsafe_allow_html=True)
    
    col_pulsanti_top_1, col_pulsanti_top_2 = st.columns([1, 1])
    with col_pulsanti_top_1:
        if st.button("➕ Aggiungi un nuovo filtro", use_container_width=True):
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
        if st.button("🗑️ Rimuovi tutti i filtri", use_container_width=True):
            st.session_state["lista_filtri"] = []
            st.session_state["lista_filtri_applicati"] = []
            st.session_state["step_righe"] = 10
            st.rerun()

    indici_da_rimuovere = []
    
    # Rendering dei filtri basato su lista_filtri (modificabili liberamente)
    for i, filtro in enumerate(st.session_state["lista_filtri"]):
        f_id = filtro["id"]
        col_f1, col_f2, col_f3, col_f4 = st.columns([3, 2, 4, 1])
        
        with col_f1:
            colonna_precedente = filtro["colonna"]
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
            
            tipo_dato = metadati[filtro["colonna"]]
            if tipo_dato == "DATE":
                filtro["tipo_data"] = st.selectbox(
                    f"TipoData##{f_id}", ["Solo Anno", "Data Intera"],
                    index=0 if filtro.get("tipo_data", "Solo Anno") == "Solo Anno" else 1,
                    key=f"tg_{f_id}",
                    label_visibility="collapsed"
                )
        
        if tipo_dato == "TEXT":
            opzioni_operatori = ["Uguale a", "Diverso da", "Contiene", "Inizia con", "Incluso in (lista, sep. da virgola)"]
        elif tipo_dato == "NUMERIC":
            opzioni_operatori = ["Uguale a", "Diverso da", "Maggiore di (>)", "Minore di (<)", "Dal (>=)", "Fino al (<=)"]
        elif tipo_dato == "DATE":
            if filtro.get("tipo_data", "Solo Anno") == "Solo Anno":
                opzioni_operatori = ["Uguale a", "Diverso da", "Dopo il (>)", "Prima del (<)", "Dal (>=)", "Fino al (<=)"]
            else:
                opzioni_operatori = ["Uguale a", "Dopo la data (>)", "Prima della data (<)", "Dalla data (>=)", "Fino alla data (<=)"]

        with col_f2:
            idx_op = 0
            if filtro["operatore"] in opzioni_operatori:
                idx_op = opzioni_operatori.index(filtro["operatore"])
            else:
                filtro["operatore"] = opzioni_operatori[0]
                idx_op = 0
                
            operatore_precedente = filtro["operatore"]
            filtro["operatore"] = st.selectbox(
                f"Operatore##{f_id}", opzioni_operatori, 
                index=idx_op, label_visibility="collapsed", key=f"op_{f_id}"
            )
            
            if filtro["operatore"] != operatore_precedente:
                filtro["valore"] = ""
                st.rerun()
            
        with col_f3:
            if tipo_dato == "TEXT":
                if filtro["operatore"] in ["Uguale a", "Diverso da"]:
                    # --- IMPLEMENTAZIONE IDEA 3: IBRIDAZIONE INTELLIGENTE ---
                    SOGLIA_CARDINALITA = 150
                    conteggio_unici = ottieni_conteggio_univoci(filtro["colonna"], conn)
                    
                    if conteggio_unici <= SOGLIA_CARDINALITA:
                        # Bassa cardinalità -> Mostriamo la comoda Selectbox
                        modalita_disponibili = ottieni_modalita_uniche(filtro["colonna"], conn)
                        if modalita_disponibili:
                            val_attuale = str(filtro["valore"])
                            idx_val = modalita_disponibili.index(val_attuale) if val_attuale in modalita_disponibili else 0
                            
                            valore_scelto = st.selectbox(
                                f"Valore##{f_id}", options=modalita_disponibili,
                                index=idx_val, label_visibility="collapsed", key=f"val_txt_{f_id}"
                            )
                            filtro["valore"] = valore_scelto
                        else:
                            filtro["valore"] = st.text_input(
                                f"Valore##{f_id}", value="", 
                                placeholder="Nessun dato presente...", label_visibility="collapsed", key=f"val_txt_vuoto_{f_id}", disabled=True
                            )
                    else:
                        # Alta cardinalità -> Scrittura a mano obbligatoria per salvare le prestazioni
                        filtro["valore"] = st.text_input(
                            f"Valore##{f_id}", value=str(filtro["valore"]), 
                            placeholder="Digita valore esatto...", label_visibility="collapsed", key=f"val_txt_input_{f_id}"
                        )
                        st.caption(f"⚡ Alta cardinalità ({conteggio_unici:,} valori). Input manuale attivo.")
                else:
                    # Per operatori come "Contiene" o "Inizia con" l'input testuale è già il default ideale
                    filtro["valore"] = st.text_input(
                        f"Valore##{f_id}", value=str(filtro["valore"]), 
                        placeholder="Inserisci pattern...", label_visibility="collapsed", key=f"val_txt_input_{f_id}"
                    )
                    
            elif tipo_dato == "NUMERIC":
                filtro["valore"] = st.text_input(
                    f"Valore##{f_id}", value=str(filtro["valore"]), 
                    placeholder="Inserisci valore numerico...", label_visibility="collapsed", key=f"val_num_{f_id}"
                )
            elif tipo_dato == "DATE":
                if filtro.get("tipo_data", "Solo Anno") == "Solo Anno":
                    anni_disponibili = ottieni_anni_univoci(filtro["colonna"], conn)
                    try:
                        val_init = int(filtro["valore"])
                        idx_anno = anni_disponibili.index(val_init) if val_init in anni_disponibili else 0
                    except ValueError:
                        idx_anno = 0
                        
                    anno_scelto = st.selectbox(
                        f"Anno##{f_id}", options=anni_disponibili, 
                        index=idx_anno, label_visibility="collapsed", key=f"val_anno_{f_id}"
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
                        f"Data##{f_id}", value=val_init_date, 
                        label_visibility="collapsed", key=f"val_data_{f_id}"
                    )
                    filtro["valore"] = data_scelta.strftime("%Y-%m-%d")
            
        with col_f4:
            st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
            if st.button("🗑️", key=f"del_{f_id}", help="Rimuovi questo filtro"):
                indici_da_rimuovere.append(i)

    if indici_da_rimuovere:
        for idx in sorted(indici_da_rimuovere, reverse=True):
            st.session_state["lista_filtri"].pop(idx)
        st.rerun()

    # --- CONTROLLO APPLICAZIONE FILTRI ---
    ha_modifiche_pendenti = (st.session_state["lista_filtri"] != st.session_state["lista_filtri_applicati"])
    
    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    col_applica, col_stato = st.columns([1, 2])
    
    with col_applica:
        bottone_tipo = "primary" if ha_modifiche_pendenti else "secondary"
        if st.button("⚡ Applica Filtri", type=bottone_tipo, use_container_width=True):
            st.session_state["lista_filtri_applicati"] = copy.deepcopy(st.session_state["lista_filtri"])
            st.rerun()
            
    with col_stato:
        if ha_modifiche_pendenti:
            st.warning("⚠️ Modifiche pendenti. Clicca su 'Applica Filtri' per aggiornare il database.")
        else:
            st.success("✅ Filtri sincronizzati con il database.")

    # =========================================================================
    # 2. COSTRUZIONE DELLE CLAUSOLE SQL (Strictly basato su lista_filtri_applicati)
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
        st.error(f"⚠️ Errore di sintassi nei filtri condizionali: {e}")
        return

    # =========================================================================
    # 3. PREVIEW DATI (Sincronizzata con i filtri applicati)
    # =========================================================================
    st.markdown('<div class="hdi-card"><h3>👀 Preview e Download</h3></div>', unsafe_allow_html=True)
    if totale_righe > 0:
        
        # --- GENERAZIONE BADGES ---
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
                <span style="
                    background-color: #FFFFFF; 
                    color: #007A33; 
                    padding: 4px 10px; 
                    border-radius: 8px; 
                    font-size: 0.8rem; 
                    font-weight: 600;
                    margin-right: 6px; 
                    display: inline-block; 
                    margin-bottom: 6px;
                    border: 1px solid #007A33;
                ">{testo_badge}</span>
                """
                lista_badges.append(html_badge)
        
        if lista_badges:
            st.markdown("**Filtri applicati correnti:**")
            st.markdown("".join(lista_badges), unsafe_allow_html=True)

        col_info_view, col_dl = st.columns([3, 1])
        with col_info_view:
            righe_mostrate = min(st.session_state["step_righe"], totale_righe)
            st.caption(f"Mostrate {righe_mostrate:,} righe di anteprima su {totale_righe:,} record totali.")
            
        with col_dl:
            @st.cache_data(ttl=60)
            def genera_csv(query):
                df_download = conn.execute(query).df()
                return df_download.to_csv(index=False).encode('utf-8')
                
            query_completa = f"SELECT * FROM vista_polizze{stringa_where_completa}"
            csv_data = genera_csv(query_completa)
            
            st.download_button(
                label="📥 Scarica CSV Filtrato",
                data=csv_data,
                file_name="estrazione_filtrata_completa.csv",
                mime="text/csv",
                use_container_width=True
            )

        query_anteprima = f"SELECT * FROM vista_polizze{stringa_where_completa} LIMIT {st.session_state['step_righe']}"
        df_preview = conn.execute(query_anteprima).df()
        
        colonne_float = df_preview.select_dtypes(include=['float64', 'float32']).columns.tolist()
        df_visualizzazione = df_preview.style
        
        if colonne_float:
            fmt_dict = {col: lambda x: f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") if pd.notnull(x) else "-" for col in colonne_float}
            df_visualizzazione = df_visualizzazione.format(fmt_dict)
        
        def applica_evidenziatore(colonna_dati):
            if colonna_dati.name in colonne_attive_filtrate:
                return ['background-color: rgba(0, 122, 51, 0.08)'] * len(colonna_dati)
            return [''] * len(colonna_dati)

        if len(colonne_attive_filtrate) > 0 and not df_preview.empty:
            df_visualizzazione = df_visualizzazione.apply(applica_evidenziatore, axis=0)

        st.dataframe(df_visualizzazione, use_container_width=True)
        
        if st.session_state["step_righe"] < totale_righe:
            if st.button("🔽 Mostra altre 10 righe", use_container_width=True):
                st.session_state["step_righe"] += 10
                st.rerun()
    else:
        st.warning("Nessun record da mostrare con i filtri applicati.")

    # =========================================================================
    # 4. REPORT TABELLARE DI SINTESI
    # =========================================================================
    st.markdown('<div class="hdi-card"><h3>📈 Statistiche di sintesi</h3></div>', unsafe_allow_html=True)
    if totale_righe == 0:
        st.warning("Nessun dato disponibile con i filtri correnti.")
    elif not colonne_numeriche:
        st.info("Nessuna colonna numerica rilevata per il calcolo delle metriche.")
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
                
                for metric_col in ['SOMMA', 'MEDIA', 'MASSIMO', 'MINIMO']:
                    df_stats_formatted[metric_col] = df_stats_formatted[metric_col].apply(
                        lambda x: f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") if pd.notnull(x) else "-"
                    )
                st.dataframe(df_stats_formatted, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Errore durante il calcolo del report: {e}")
