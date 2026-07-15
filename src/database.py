import streamlit as st
import duckdb
import pyarrow.parquet as pq

def ottieni_connessione():
    """Restituisce la connessione DuckDB attiva se presente nello stato."""
    if "db_conn" in st.session_state and st.session_state["db_conn"] is not None:
        return st.session_state["db_conn"]
    return None

def inizializza_database_in_ram(buffer):
    """
    Prende il buffer decifrato e sfrutta il pattern Zero-Copy di Arrow e DuckDB.
    """
    if "db_conn" in st.session_state and st.session_state["db_conn"] is not None:
        return st.session_state["db_conn"]
        
    try:
        conn = duckdb.connect(database=':memory:')
        buffer.seek(0)
        
        # 1. Legge i dati tramite PyArrow tenendoli in RAM
        tabella_arrow = pq.read_table(buffer)
        
        # --- OTTIMIZZAZIONE 2: ZERO-COPY ARCHITECTURE ---
        # Registra la tabella Arrow direttamente nel motore SQL con il nome finale.
        # Eliminata la "CREATE TABLE AS SELECT..." che duplicava l'intero database in RAM.
        conn.register("vista_polizze", tabella_arrow)
        
        st.session_state["db_conn"] = conn
        return conn
        
    except Exception as e:
        st.error(f"❌ Errore durante l'inizializzazione del database in RAM: {str(e)}")
        return None
