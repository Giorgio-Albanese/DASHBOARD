import streamlit as st
import cryptography
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
import hashlib
import duckdb
import io
import os
import glob

# Configurazione del titolo della pagina web
st.set_page_config(page_title="Dashboard CP", layout="wide")

# --- RICERCA AUTOMATICA DEL FILE CIFRATO ---
file_trovati = glob.glob("DB_GIORGIO_*.parquet.enc")

if file_trovati:
    # Ordina i file alfabeticamente/cronologicamente e prende l'ultimo (il più recente)
    file_trovati.sort()
    FILE_CIFRATO = file_trovati[-1]
else:
    FILE_CIFRATO = "DB_GIORGIO_NON_TROVATO.parquet.enc"


def decifra_parquet_in_memoria(file_path: str, password: str):
    """
    Decifra il file ed effettua l'unpadding. 
    Non mostra messaggi grafici interni, solleva eccezioni per il blocco UI principale.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Il file '{file_path}' non è stato trovato sul disco.")
        
    # Rimozione di spazi bianchi accidentali o invii dalla stringa di input
    password_pulita = password.strip()
    
    # Generazione chiave binaria a 256-bit tramite SHA-256 (allineata perfettamente con R)
    chiave = hashlib.sha256(password_pulita.encode('utf-8')).digest()
    
    with open(file_path, "rb") as f:
        dati_cifrati = f.read()
        
    if len(dati_cifrati) < 16:
        raise ValueError("Il file cifrato ha una dimensione inferiore ai 16 byte minimi dell'IV.")
        
    # Estrazione IV (primi 16 byte) e Payload cifrato
    iv = dati_cifrati[:16]
    payload_cifrato = dati_cifrati[16:]
    
    # Decifratura AES-256-CBC
    cipher = Cipher(algorithms.AES(chiave), modes.CBC(iv))
    decryptor = cipher.decryptor()
    dati_decifrati = decryptor.update(payload_cifrato) + decryptor.finalize()
    
    # Rimozione Rimozione Padding PKCS7 (Se la password è errata, fallisce matematicamente qui)
    unpadder = padding.PKCS7(128).unpadder()
    dati_puliti = unpadder.update(dati_decifrati) + unpadder.finalize()
    
    return io.BytesIO(dati_puliti)


# --- INTERFACCIA UTENTE (GESTIONE STATO SESSIONE) ---
if "sbloccato" not in st.session_state:
    st.session_state["sbloccato"] = False
if "buffer_dati" not in st.session_state:
    st.session_state["buffer_dati"] = None

# -------------------------------------------------------------------------
# STATO 1: APPLICAZIONE BLOCCATA (LOGIN & DIAGNOSTICA GRANULARE)
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
                    # Passo 1: Tentativo di decifratura e rimozione del padding crittografico
                    buffer = decifra_parquet_in_memoria(FILE_CIFRATO, password_input)
                    
                    # Passo 2: Verifica formale dell'integrità del formato Parquet tramite PyArrow
                    buffer.seek(0)
                    import pyarrow.parquet as pq
                    tabella_test = pq.read_table(buffer)
                    
                    # Se non sono state sollevate eccezioni fino a qui, la password e il file sono integri!
                    st.session_state["sbloccato"] = True
                    st.session_state["buffer_dati"] = buffer
                    st.success("🔓 Dati decifrati e validati con successo!")
                    st.rerun()
                    
                except FileNotFoundError as fnf_err:
                    st.error(f"❌ Errore di sistema: {str(fnf_err)}")
                    
                except ValueError as val_err:
                    # Se il padding PKCS7 fallisce, significa che i byte finali decifrati sono incoerenti
                    if "padding" in str(val_err).lower():
                        st.error("❌ Password errata. Impossibile decifrare i blocchi di dati (Errore di Padding).")
                    else:
                        st.error(f"❌ Errore nei dati: {str(val_err)}")
                        
                except Exception as e:
                    stringa_errore = str(e)
                    # Controlliamo se l'eccezione arriva dalla lettura del file Parquet (es. Magic Bytes mancanti)
                    if "parquet" in stringa_errore.lower() or "magic bytes" in stringa_errore.lower():
                        st.error(f"❌ Password CORRETTA (decifratura riuscita), ma il file decifrato non è un Parquet valido! Controlla l'esportazione da R. Dettaglio: {stringa_errore}")
                    else:
                        st.error(f"⚠️ Errore imprevisto durante la decifratura: {stringa_errore}")

# -------------------------------------------------------------------------
# STATO 2: APPLICAZIONE SBLOCCATA (LA DASHBOARD VERA E PROPRIA)
# -------------------------------------------------------------------------
else:
    if st.sidebar.button("🔒 Chiudi Sessione (Cancella RAM)"):
        st.session_state["sbloccato"] = False
        st.session_state["buffer_dati"] = None
        st.rerun()
        
    st.title("📊 Dashboard Direzione Vita: Premi, Sinistri ed Estinzioni")
    st.sidebar.header("Configuratore Dashboard")
    
    try:
        # 1. Inizializziamo il motore DuckDB in memoria
        conn = duckdb.connect(database=':memory:')
        
        # 2. Riportiamo il puntatore del buffer all'inizio
        st.session_state["buffer_dati"].seek(0)
        
        # 3. Importiamo pyarrow per leggere la tabella binaria dalla RAM
        import pyarrow.parquet as pq
        tabella_arrow = pq.read_table(st.session_state["buffer_dati"])
        
        # 4. Registriamo e materializziamo la tabella dentro DuckDB bypassando gli scope globali
        conn.register("vista_polizze_ram", tabella_arrow)
        conn.execute("CREATE TABLE vista_polizze AS SELECT * FROM vista_polizze_ram")
        
        # Test di lettura rapido (prime 5 righe) da mostrare a schermo
        df_struttura = conn.execute("SELECT * FROM vista_polizze LIMIT 5").df()
        
        st.write("### Anteprima dei dati sbloccati in memoria:")
        st.dataframe(df_struttura)
        
        st.sidebar.subheader("Filtri Globali")
        # Puoi inserire qui sotto le tue selectbox/slider per i filtri usando conn.execute()
        
    except Exception as e:
        st.error(f"Errore critico nel motore dati della dashboard: {e}")
