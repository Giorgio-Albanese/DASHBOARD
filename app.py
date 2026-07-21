import streamlit as st
import cryptography
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
import hashlib
import io
import os
import sys
import glob
from PIL import Image
import pyarrow.parquet as pq

# Importiamo le funzioni di gestione del database dal modulo locale
from src.database import inizializza_database_in_ram, ottieni_connessione

# --- FUNZIONE PER PERCORSI RISORSE ---
def get_resource_path(relative_path):
    """Risolve i percorsi delle risorse sia in locale che in ambiente di produzione"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Configurazione globale della pagina Streamlit
st.set_page_config(
    page_title="Dashboard CP - HDI", 
    layout="wide",
    page_icon=":material/analytics:"
)

# --- CSS PERSONALIZZATO ISTITUZIONALE ---
st.markdown("""
    <style>
    .main { background-color: #F8F9FA; }
    .hdi-card {
        background-color: white;
        padding: 18px 24px; 
        border-radius: 8px;
        border: 1px solid #E5E7EB; 
        border-left: 3px solid #007A33; 
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05); 
        margin-bottom: 20px;
    }
    /* Stile Tab base protetto da regole globali */
    [data-testid="stSidebar"] img { border-radius: 0px !important; }
    [data-testid="stSidebar"] [data-testid="stImage"] { padding: 10px 0px !important; }
    </style>
    """, unsafe_allow_html=True)

# --- SIDEBAR GLOBALE ---
with st.sidebar:
    path_logo = get_resource_path("logo_hdi.png")
    if os.path.exists(path_logo):
        st.image(Image.open(path_logo), use_container_width=True)
    st.markdown("### ⚙️ Area Riservata")
    st.divider()

# --- RICERCA AUTOMATICA DEL FILE CIFRATO ---
file_trovati = glob.glob("DB_GIORGIO_*.parquet.enc")

if file_trovati:
    file_trovati.sort()
    FILE_CIFRATO = file_trovati[-1]
else:
    FILE_CIFRATO = "DB_GIORGIO_NON_TROVATO.parquet.enc"

# --- OTTIMIZZAZIONE 1: DECRYPTION IN STREAMING CHUNKS ---
def decifra_parquet_in_memoria(file_path: str, password: str):
    """Decifra il file a blocchi (chunking) per salvare RAM in ambiente Cloud."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Il file '{file_path}' non è stato trovato sul disco.")
        
    password_pulita = password.strip()
    chiave = hashlib.sha256(password_pulita.encode('utf-8')).digest()
    
    out_buffer = io.BytesIO()
    
    with open(file_path, "rb") as f:
        iv = f.read(16)
        if len(iv) < 16:
            raise ValueError("Il file cifrato ha una dimensione inferiore ai 16 byte minimi dell'IV.")
            
        cipher = Cipher(algorithms.AES(chiave), modes.CBC(iv))
        decryptor = cipher.decryptor()
        unpadder = padding.PKCS7(128).unpadder()
        
        # Legge il file in blocchi da 64KB invece di ingoiarlo tutto in RAM
        chunk_size = 64 * 1024
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            decrypted_chunk = decryptor.update(chunk)
            if decrypted_chunk:
                out_buffer.write(unpadder.update(decrypted_chunk))
                
        # Finalizzazione crittografica
        final_decrypted = decryptor.finalize()
        if final_decrypted:
            out_buffer.write(unpadder.update(final_decrypted))
            
        out_buffer.write(unpadder.finalize())
    
    out_buffer.seek(0)
    return out_buffer


# --- INIZIALIZZAZIONE DELLO STATO DELLA SESSIONE ---
if "sbloccato" not in st.session_state:
    st.session_state["sbloccato"] = False
if "buffer_dati" not in st.session_state:
    st.session_state["buffer_dati"] = None
if "db_conn" not in st.session_state:
    st.session_state["db_conn"] = None


# -------------------------------------------------------------------------
# STATO 1: APPLICAZIONE BLOCCATA (LOGIN)
# -------------------------------------------------------------------------
if not st.session_state["sbloccato"]:
    st.markdown("<h2 style='text-align: center; margin-top: 50px;'>🔒 Accesso Riservato - Dashboard Analitica</h2>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown('<div class="hdi-card"><h4>Autenticazione Richiesta</h4>', unsafe_allow_html=True)
        password_input = st.text_input("Password di Decifratura dei Dati", type="password")
        pulsante_sblocco = st.button("Sblocca e Carica Dati", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
        if pulsante_sblocco and password_input:
            with st.spinner("Decifratura e materializzazione in RAM in corso..."):
                try:
                    buffer = decifra_parquet_in_memoria(FILE_CIFRATO, password_input)
                    
                    # Eliminato il doppio test inutile di PyArrow. Delegato direttamente a database.py
                    conn = inizializza_database_in_ram(buffer)
                    if conn is None:
                        raise ValueError("Impossibile generare la tabella in memoria.")
                        
                    st.session_state["sbloccato"] = True
                    st.session_state["buffer_dati"] = buffer
                    st.success("🔓 Dati decifrati e strutturati in RAM con successo!")
                    st.rerun()
                    
                except FileNotFoundError as fnf_err:
                    st.error(f"❌ Errore di sistema: {str(fnf_err)}")
                except ValueError as val_err:
                    if "padding" in str(val_err).lower():
                        st.error("❌ Password errata. Impossibile decifrare i blocchi di dati (Errore di Padding).")
                    else:
                        st.error(f"❌ Errore nei dati: {str(val_err)}")
                except Exception as e:
                    stringa_errore = str(e)
                    if "parquet" in stringa_errore.lower() or "magic bytes" in stringa_errore.lower():
                        st.error(f"❌ Password CORRETTA, ma il formato non è un Parquet valido. Dettaglio: {stringa_errore}")
                    else:
                        st.error(f"⚠️ Errore imprevisto: {stringa_errore}")

# -------------------------------------------------------------------------
# STATO 2: APPLICAZIONE SBLOCCATA (DASHBOARD ATTIVA)
# -------------------------------------------------------------------------
else:
    with st.sidebar:
        st.sidebar.markdown("**Sessione Attiva**")
        if st.sidebar.button("🔒 Chiudi Sessione (Cancella RAM)", use_container_width=True):
            if st.session_state["db_conn"]:
                try: st.session_state["db_conn"].close()
                except: pass
            st.session_state["sbloccato"] = False
            st.session_state["buffer_dati"] = None
            st.session_state["db_conn"] = None
            st.rerun()
            
    st.title("Dashboard Credit Protection")
    
    conn = ottieni_connessione()
    
    if conn is not None:
        tab_navigatore, tab_premi, tab_sinistri = st.tabs([
            "🔍 Navigatore DB", 
            "💰 Analisi Premi", 
            "🚨 Analisi Sinistri"
        ])
        
        with tab_navigatore:
            from src.components.explorer import render_db_navigator
            render_db_navigator(conn)
            
        with tab_premi:
            from src.components.premi import render_analisi_premi
            render_analisi_premi(conn)
            
        with tab_sinistri:
            from src.components.sinistri import render_analisi_sinistri
    
            render_analisi_sinistri(conn)
            
    else:
        st.error("⚠️ Connessione al database persa. Effettua nuovamente l'accesso.")
        st.session_state["sbloccato"] = False
        st.rerun()
