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
    Prende il buffer decifrato, lo indicizza in DuckDB e salva 
    la connessione nello session_state per renderla persistente.
    """
    # Se la connessione esiste già, non fare nulla e restituisci quella attiva
    if "db_conn" in st.session_state and st.session_state["db_conn"] is not None:
        return st.session_state["db_conn"]
        
    try:
        # 1. Crea il motore DuckDB isolato in memoria RAM
        conn = duckdb.connect(database=':memory:')
        
        # 2. Legge i dati tramite PyArrow
        buffer.seek(0)
        tabella_arrow = pq.read_table(buffer)
        
        # 3. Registra e materializza la tabella in SQL
        conn.register("vista_polizze_ram", tabella_arrow)
        conn.execute("CREATE TABLE vista_polizze AS SELECT * FROM vista_polizze_ram")
        
        # 4. Salva la connessione nello stato globale della sessione Streamlit
        st.session_state["db_conn"] = conn
        return conn
        
    except Exception as e:
        st.error(f"❌ Errore durante l'inizializzazione del database in RAM: {str(e)}")
        return None
