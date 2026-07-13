import streamlit as st
import pandas as pd

def carica_metadati_db(conn):
    """Recupera le colonne e i tipi di dati per mappare i filtri corretti"""
    info = conn.execute("PRAGMA table_info(vista_polizze)").df()
    # Mappiamo i tipi in Macro-categorie (Testo o Numerico)
    mappa_tipi = {}
    for _, row in info.iterrows():
        tipo_sql = str(row['type']).upper()
        if any(x in tipo_sql for x in ["INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC"]):
            mappa_tipi[row['name']] = "NUMERIC"
        else:
            mappa_tipi[row['name']] = "TEXT"
    return mappa_tipi

def render_db_navigator(conn):
    st.markdown("### 🔍 Esploratore Dinamico del Database")
    
    # --- 1. INIZIALIZZAZIONE DELLO STATO (Solo se non presente) ---
    if "lista_filtri" not in st.session_state:
        st.session_state["lista_filtri"] = []  # Lista di dizionari con i filtri attivi
    if "step_righe" not in st.session_state:
        st.session_state["step_righe"] = 10    # Quante righe mostrare inizialmente
        
    metadati = carica_metadati_db(conn)
    elenco_colonne = list(metadati.keys())
    
    # --- 2. PANNELLO CONTROLLO COLONNE ---
    with st.expander("📊 Seleziona Colonne da Visualizzare", expanded=False):
        colonne_scelte = st.multiselect(
            "Seleziona i campi (Lascia vuoto per vederli tutti):",
            options=elenco_colonne,
            default=[]
        )
        colonne_sql = ", ".join(colonne_scelte) if colonne_scelte else "*"

    # --- 3. MOTORE DI FILTRAGGIO DINAMICO MULTIPLO ---
    st.markdown("##### 🛠️ Filtri di Riga Attivi")
    
    # Pulsante per aggiungere una nuova riga di filtro
    if st.button("➕ Aggiungi un nuovo filtro condizionale"):
        st.session_state["lista_filtri"].append({
            "colonna": elenco_colonne[0],
            "operatore": "Uguale a",
            "valore": ""
        })
        st.rerun()

    # Renderizziamo i filtri correnti generati dall'utente
    clausole_where = []
    indici_da_rimuovere = []
    
    for i, filtro in enumerate(st.session_state["lista_filtri"]):
        col_f1, col_f2, col_f3, col_f4 = st.columns([3, 2, 4, 1])
        
        with col_f1:
            filtro["colonna"] = st.selectbox(f"Colonna##{i}", elenco_colonne, index=elenco_colonne.index(filtro["colonna"]), label_visibility="collapsed", key=f"col_{i}")
        
        # Adatta gli operatori in base al tipo di dato (Testo vs Numero)
        tipo_dato = metadati[filtro["colonna"]]
        opzioni_operatori = ["Uguale a", "Diverso da", "Incluso in (lista separata da virgola)"]
        if tipo_dato == "TEXT":
            opzioni_operatori += ["Contiene", "Inizia con"]
        else:
            opzioni_operatori += ["Maggiore di (>)", "Minore di (<)"]
            
        with col_f2:
            # Protezione nel caso il cambio colonna sballi l'indice dell'operatore precedente
            idx_op = 0
            if filtro["operatore"] in opzioni_operatori:
                idx_op = opzioni_operatori.index(filtro["operatore"])
            filtro["operatore"] = st.selectbox(f"Operatore##{i}", opzioni_operatori, index=idx_op, label_visibility="collapsed", key=f"op_{i}")
            
        with col_f3:
            filtro["valore"] = st.text_input(f"Valore##{i}", value=filtro["valore"], placeholder="Inserisci valore...", label_visibility="collapsed", key=f"val_{i}")
            
        with col_f4:
            if st.button("🗑️", key=f"del_{i}", help="Rimuovi questo filtro"):
                indici_da_rimuovere.append(i)

        # Costruzione della stringa SQL per questo specifico filtro (Sanitizzazione base per apici)
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
            elif op == "Incluso in (lista separata da virgola)":
                elementi = ", ".join([f"'{x.strip()}'" if tipo_dato == "TEXT" else x.strip() for x in val_safe.split(",")])
                clausole_where.append(f"{col} IN ({elementi})")

    # Rimuovi i filtri cancellati dall'utente
    if indici_da_rimuovere:
        for idx in sorted(indici_da_rimuovere, reverse=True):
            st.session_state["lista_filtri"].pop(idx)
        st.rerun()

    # Uniamo tutti i filtri in un'unica clausola WHERE SQL
    stringa_where_completa = " WHERE " + " AND ".join(clausole_where) if clausole_where else ""

    # --- 4. CALCOLO METRICHE DI SINTESI (Velocissimo su DuckDB) ---
    try:
        totale_righe = conn.execute(f"SELECT COUNT(*) FROM vista_polizze{stringa_where_completa}").fetchone()[0]
    except Exception as e:
        st.error(f"⚠️ Errore di sintassi nei filtri inseriti: {e}")
        return

    # --- 5. SCARICO DATI (LA VISTA COMPLETA FILTRATA) ---
    col_kpi, col_dl = st.columns([3, 1])
    with col_kpi:
        righe_mostrate = min(st.session_state["step_righe"], totale_righe)
        st.info(f"📊 Risultati Trovati: **{totale_righe:,}** | Visualizzati in anteprima: **{righe_mostrate:,}**")
        
    with col_dl:
        if totale_righe > 0:
            # Estraiamo l'intero set di dati filtrato (senza LIMIT) SOLO al momento del click per non intasare la RAM
            @st.cache_data(ttl=60) # Cache corta per non saturare la memoria se cambia filtri spesso
            def genera_csv(query):
                df_download = conn.execute(query).df()
                return df_download.to_csv(index=False).encode('utf-8')
                
            query_completa = f"SELECT {colonne_sql} FROM vista_polizze{stringa_where_completa}"
            csv_data = genera_csv(query_completa)
            
            st.download_button(
                label="📥 Scarica Vista Corrente (CSV)",
                data=csv_data,
                file_name="estrazione_dashboard.csv",
                mime="text/csv",
                use_container_width=True
            )

    # --- 6. QUERY E PREVIEW TABELLARE (PAGINATA CON LIMIT) ---
    if totale_righe > 0:
        query_anteprima = f"SELECT {colonne_sql} FROM vista_polizze{stringa_where_completa} LIMIT {st.session_state['step_righe']}"
        df_preview = conn.execute(query_anteprima).df()
        
        # Mostra la tabella
        st.dataframe(df_preview, use_container_width=True)
        
        # Pulsante "Mostra Altro" (Aumenta il limite di 10 ad ogni clic)
        if st.session_state["step_righe"] < totale_righe:
            if st.button("🔽 Mostra altre 10 righe", use_container_width=True):
                st.session_state["step_righe"] += 10
                st.rerun()
    else:
        st.warning("Nessun record corrisponde ai criteri di filtraggio selezionati.")
