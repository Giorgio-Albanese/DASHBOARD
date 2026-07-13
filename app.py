import streamlit as st
import cryptography
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
import hashlib
import io
import os
import glob
import pyarrow.parquet as pq

# Importiamo le funzioni di gestione del database dal modulo locale
from src.database import inizializza_database_in_ram, ottieni_connessione

# Configurazione globale della pagina Streamlit
st.set_page_config(page_title="Dashboard CP", layout="wide")

# --- RICERCA AUTOMATICA DEL FILE CIFRATO ---
file_trovati = glob.glob("DB_GIORGIO_*.parquet.enc")

if file_trovati:
    # Ordina i file alfabeticamente/cronologicamente e prende il più recente
    file_trovati.sort()
    FILE_CIFRATO = file_trovati[-1]
else:
    FILE_CIFRATO = "DB_GIORGIO_NON_TROVATO.parquet.enc"


def decifra_parquet_in_memoria(file_path: str, password: str):
    """
    Decifra il file ed effettua l'unpadding PKCS7 in memoria RAM.
    Solleva eccezioni esplicite catturate dal blocco dell'interfaccia utente.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Il file '{file_path}' non è stato trovato sul disco.")
        
    # Rimozione di spazi bianchi o invii accidentali dall'input
    password_pulita = password.strip()
    
    # Derivazione chiave a 256-bit tramite SHA-256 (perfettamente allineata con l'esportazione R)
    chiave = hashlib.sha256(password_pulita.encode('utf-8')).digest()
    
    with open(file_path, "rb") as f:
        dati_cifrati = f.read()
        
    if len(dati_cifrati) < 16:
        raise ValueError("Il file cifrato ha una dimensione inferiore ai 16 byte minimi dell'IV.")
        
    # Separazione IV (primi 16 byte) e Payload cifrato
    iv = dati_cifrati[:16]
    payload_cifrato = dati_cifrati[16:]
    
    # Decifratura AES-256-CBC
    cipher = Cipher(algorithms.AES(chiave), modes.CBC(iv))
    decryptor = cipher.decryptor()
    dati_decifrati = decryptor.update(payload_cifrato) + decryptor.finalize()
    
    # Rimozione Rimozione Padding PKCS7
    unpadder = padding.PKCS7(128).unpadder()
    dati_puliti = unpadder.update(dati_decifrati) + unpadder.finalize()
    
    return io.BytesIO(dati_puliti)


# --- INIZIALIZZAZIONE DELLO STATO DELLA SESSIONE ---
if "sbloccato" not in st.session_state:
    st.session_state["sbloccato"] = False
if "buffer_dati" not in st.session_state:
    st.session_state["buffer_dati"] = None
if "db_conn" not in st.session_state:
    st.session_state["db_conn"] = None


# -------------------------------------------------------------------------
# STATO 1: APPLICAZIONE BLOCCATA (LOGIN & DIAGNOSTICA)
# -------------------------------------------------------------------------
if not st.session_state["sbloccato"]:
    st.markdown("<h2 style='text-align: center;'>🔒 Accesso Riservato - Dashboard Analitica</h2>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        password_input = st.text_input("Inserisci la Password di Decifratura dei Dati", type="password")
        pulsante_sblocco = st.button("Sblocca e Carica Dati", use_container_width=True)
        
        if pulsante_sblocco and password_input:
            with st.spinner("Decifratura e verifica del database in corso..."):
                try:
                    # 1. Tentativo di decifratura e rimozione del padding crittografico
                    buffer = decifra_parquet_in_memoria(FILE_CIFRATO, password_input)
                    
                    # 2. Verifica formale dell'integrità del formato Parquet tramite PyArrow
                    buffer.seek(0)
                    tabella_test = pq.read_table(buffer)
                    
                    # 3. Inizializzazione della connessione DuckDB persistente in RAM
                    inizializza_database_in_ram(buffer)
                    
                    # Se non sono state sollevate eccezioni, la sessione viene promossa a sbloccata
                    st.session_state["sbloccato"] = True
                    st.session_state["buffer_dati"] = buffer
                    st.success("🔓 Dati decifrati e strutturati in RAM con successo!")
                    st.rerun()
                    
                except FileNotFoundError as fnf_err:
                    st.error(f"❌ Errore di sistema: {str(fnf_err)}")
                    
                except ValueError as val_err:
                    # Se il padding PKCS7 fallisce, la password inserita è errata
                    if "padding" in str(val_err).lower():
                        st.error("❌ Password errata. Impossibile decifrare i blocchi di dati (Errore di Padding).")
                    else:
                        st.error(f"❌ Errore nei dati: {str(val_err)}")
                        
                except Exception as e:
                    stringa_errore = str(e)
                    # Verifica se l'errore deriva dalla formattazione interna del file Parquet decifrato
                    if "parquet" in stringa_errore.lower() or "magic bytes" in stringa_errore.lower():
                        st.error(f"❌ Password CORRETTA, ma il file decifrato non è un Parquet valido! Controlla lo script di esportazione da R. Dettaglio: {stringa_errore}")
                    else:
                        st.error(f"⚠️ Errore imprevisto durante la decifratura: {stringa_errore}")

# -------------------------------------------------------------------------
# STATO 2: APPLICAZIONE SBLOCCATA (DASHBOARD ATTIVA)
# -------------------------------------------------------------------------
else:
    # Pulsante per cancellare completamente la RAM e chiudere la sessione di lavoro
    if st.sidebar.button("🔒 Chiudi Sessione (Cancella RAM)"):
        if st.session_state["db_conn"]:
            try:
                st.session_state["db_conn"].close()
            except:
                pass
        st.session_state["sbloccato"] = False
        st.session_state["buffer_dati"] = None
        st.session_state["db_conn"] = None
        st.rerun()
        
    st.title("📊 Dashboard Direzione Vita: Premi, Sinistri ed Estinzioni")
    st.sidebar.header("Configuratore Dashboard")
    
    # Recuperiamo la connessione DuckDB persistente dallo stato di Streamlit
    conn = ottieni_connessione()
    
    if conn is not None:
        try:
            # Query di test ultra-veloce eseguita direttamente sulla tabella in memoria
            df_struttura = conn.execute("SELECT * FROM vista_polizze LIMIT 5").df()
            
            st.write("### Anteprima dei dati sbloccati in memoria (Query interna in RAM):")
            st.dataframe(df_struttura)
            
            st.sidebar.subheader("Filtri Globali")
            # [I prossimi componenti dei filtri interagiranno direttamente con l'oggetto 'conn']
            
        except Exception as e:
            st.error(f"Errore di lettura dal database persistente: {e}")
    else:
        st.error("⚠️ Connessione al database persa. Effettua nuovamente l'accesso.")
        st.session_state["sbloccato"] = False
        st.rerun()
