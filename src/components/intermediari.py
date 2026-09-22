import io
import re
import traceback
import zipfile
import numpy as np
import openpyxl
from openpyxl.utils import get_column_letter
import pandas as pd
import streamlit as st


def render_report_intermediari(conn):
  st.subheader("📊 Generatore Report per Intermediario")
  st.markdown(
      "Carica il file dei contatti (`Contatti.xlsx`) per elaborare e scaricare"
      " i report Excel suddivisi per intermediario e finanziaria."
  )

  if "zip_buffer_intermediari" not in st.session_state:
    st.session_state["zip_buffer_intermediari"] = None

  contatti_file = st.file_uploader(
      "Carica il file Contatti.xlsx", type=["xlsx"], key="uploader_contatti"
  )

  if contatti_file is not None:
    try:
      contatti_df = pd.read_excel(contatti_file)
      contatti_df = contatti_df.dropna(
          subset=["Finanziaria", "Intermediario"]
      ).copy()
      contatti_df["Finanziaria_Clean"] = (
          contatti_df["Finanziaria"]
          .astype(str)
          .str.upper()
          .str.replace(r"\s+", " ", regex=True)
          .str.strip()
      )
    except Exception as e:
      st.error(f"Errore nella lettura del file Contatti: {e}")
      return

    if st.button(
        "🚀 Genera Report Intermediari",
        type="primary",
        width="stretch",
    ):
      try:
        with st.spinner(
            "Analisi date, tabelle e aggregazione in corso..."
        ):
          tables = conn.execute("SHOW TABLES").fetchall()
          if not tables:
            st.error(
                "❌ **Il database DuckDB è vuoto!** Nessuna tabella trovata in"
                " memoria."
            )
            return

          table_name = None
          tabelle_info = {}

          for t in tables:
            t_name = t[0]
            try:
              cols = [
                  c.upper()
                  for c in conn.execute(f"SELECT * FROM {t_name} LIMIT 0")
                  .df()
                  .columns
              ]
              tabelle_info[t_name] = cols
              if "DECORRENZA" in cols or "PREMI_NETTO" in cols:
                table_name = t_name
                break
            except Exception:
              continue

          if not table_name:
            table_name = tables[0][0]

          # --- DIAGNOSTICA PRELIMINARE DATE ---
          # Seleziona un campione di DECORRENZA per verificare il formato
          sample_dates = conn.execute(
              f"SELECT DECORRENZA FROM {table_name} LIMIT 5"
          ).fetchall()

          conn.register("contatti_input", contatti_df)

          # Query con estrazione dell'anno super-robusta (gestisce DD/MM/YYYY, YYYY-MM-DD e Timestamp)
          query_aggregata = f"""
                    WITH cleaned AS (
                        SELECT 
                            PREMI_NETTO,
                            PROVVACQ,
                            COALESCE(ESTINZIONI, 0) AS ESTINZIONI,
                            COALESCE(ESTINZIONI_PROVV, 0) AS ESTINZIONI_PROVV,
                            COALESCE(LIQUIDAZIONI, 0) AS LIQUIDAZIONI,
                            COALESCE(
                                TRY_CAST(YEAR(TRY_CAST(DECORRENZA AS DATE)) AS INTEGER),
                                TRY_CAST(YEAR(TRY_CAST(STRPTIME(CAST(DECORRENZA AS VARCHAR), '%d/%m/%Y') AS DATE)) AS INTEGER),
                                TRY_CAST(SUBSTR(CAST(DECORRENZA AS VARCHAR), 1, 4) AS INTEGER),
                                TRY_CAST(SUBSTR(CAST(DECORRENZA AS VARCHAR), 7, 4) AS INTEGER)
                            ) AS Anno,
                            COALESCE(RAMO, 'Generico') AS Tipo,
                            CASE 
                                WHEN UPPER(CONTRAENTE) LIKE '%I.B.L.%' THEN 'IBL ISTITUTO BANCARIO DEL LAVORO'
                                WHEN UPPER(CONTRAENTE) LIKE '%CREDITIS%' THEN 'CREDITIS'
                                ELSE TRIM(REGEXP_REPLACE(REGEXP_REPLACE(UPPER(CONTRAENTE), '[^\\w\\s]', ' ', 'g'), '\\b(SPA|SRL|S P A|S R L)\\b', '', 'g'))
                            END AS FINANZIARIA,
                            CASE 
                                WHEN COALESCE(AZTIPO, -1) = 0 OR CAST(CODICEPROD AS VARCHAR) = 'CQP' THEN 'Pensionato'
                                WHEN AZTIPO IN (1, 2) THEN 'Pubblico'
                                WHEN AZTIPO = 3 THEN 'Parapubblico'
                                WHEN AZTIPO IN (6, 7, 9, 10) THEN 'Medio Privato'
                                WHEN AZTIPO IN (8, 11) THEN 'Grande Privato'
                                WHEN AZTIPO IN (4, 5) OR (AZTIPO BETWEEN 12 AND 20) THEN 'Resto'
                                WHEN AZTIPO IN (21, 22) THEN 'Del Pubblico'
                                WHEN AZTIPO = 23 THEN 'Del Parapubblico'
                                WHEN AZTIPO = 26 THEN 'Del Medio Privato'
                                WHEN (AZTIPO BETWEEN 24 AND 25) OR (AZTIPO BETWEEN 40 AND 50) THEN 'Del Resto'
                                ELSE 'Privato'
                            END AS Tipo_Azienda
                        FROM {table_name}
                    ),
                    filtered AS (
                        SELECT * FROM cleaned WHERE Anno IS NOT NULL AND Anno BETWEEN 2018 AND 2026
                    ),
                    aggregated AS (
                        SELECT 
                            Anno,
                            FINANZIARIA,
                            Tipo,
                            Tipo_Azienda,
                            SUM(PREMI_NETTO) AS Premi_netto,
                            SUM(PROVVACQ) AS Provvigioni,
                            SUM(ESTINZIONI) AS Estinzioni,
                            SUM(ESTINZIONI_PROVV) AS Provvigioni_rec,
                            SUM(LIQUIDAZIONI) AS Sinistri,
                            COUNT(*) AS N_Polizze,
                            MODE(Tipo_Azienda) AS Tipo_Azienda_prevalenza
                        FROM filtered
                        GROUP BY Anno, FINANZIARIA, Tipo, Tipo_Azienda
                    )
                    SELECT 
                        a.*,
                        c.Intermediario
                    FROM aggregated a
                    LEFT JOIN contatti_input c ON a.FINANZIARIA = c.Finanziaria_Clean
                """

          df_int = conn.execute(query_aggregata).df()

          # Se il DataFrame risultante è vuoto, mostriamo un errore con i dettagli diagnostici
          if df_int.empty:
            st.error(
                "❌ **La query ha restituito 0 righe!** Nessun dato è"
                " sopravvissuto ai filtri (probabilmente a causa del formato"
                " della colonna `DECORRENZA` o dell'intervallo anni)."
            )
            st.info("Campione dei valori grezzi trovati in `DECORRENZA`:")
            st.write(sample_dates)

            # Mostriamo anche gli anni unici rilevati prima del filtro per capire cosa c'è dentro
            anni_grezzi = conn.execute(
                f"SELECT DISTINCT DECORRENZA FROM {table_name} LIMIT 20"
            ).df()
            st.info("Primi valori distinti della colonna DECORRENZA:")
            st.write(anni_grezzi)
            return

          match_count = df_int["Intermediario"].notna().sum()
        #   total_rows = len(df_int)

          if match_count == 0:
            st.error(
                "❌ **Nessuna corrispondenza trovata con i contatti!** Le"
                " finanziarie nel database non coincidono con quelle nel file"
                " Contatti.xlsx."
            )
            st.info("Ecco le chiavi di finanziaria estratte dal database:")
            st.write(df_int["FINANZIARIA"].unique())
            return
        #   else:
        #     st.success(
        #         f"Trovate {match_count} corrispondenze su {total_rows} righe"
        #         " aggregate."
        #     )

          df_int["Premi_netto_est"] = (
              df_int["Premi_netto"]
              - df_int["Provvigioni"]
              + df_int["Estinzioni"]
              + df_int["Provvigioni_rec"]
          )
          df_int["Premi"] = np.maximum(1, df_int["Premi_netto_est"])
          df_int["Sinistri_attesi"] = (
              10
              / np.maximum(1, np.minimum(10, 2026 - df_int["Anno"]))
              * df_int["Sinistri"]
          )
          df_int["LR_netto"] = df_int["Sinistri"] / df_int["Premi"]
          df_int["LR"] = df_int["Sinistri"] / df_int["Premi_netto"]
          df_int["LR_netto_atteso"] = (
              df_int["Sinistri_attesi"] / df_int["Premi"]
          )
          df_int["LR_atteso"] = (
              df_int["Sinistri_attesi"] / df_int["Premi_netto"]
          )
          df_int["Provv_perc"] = (
              df_int["Provvigioni"] / df_int["Premi_netto"]
          )

          cols = list(df_int.columns)
          if "Anno" in cols and "FINANZIARIA" in cols:
            cols.remove("FINANZIARIA")
            anno_idx = cols.index("Anno")
            cols.insert(anno_idx + 1, "FINANZIARIA")
            df_int = df_int[cols]

          zip_buffer = io.BytesIO()
          with zipfile.ZipFile(
              zip_buffer, "w", zipfile.ZIP_DEFLATED
          ) as zip_file:
            df_filtrato = df_int.dropna(subset=["Intermediario"])
            df_filtrato = df_filtrato[
                ~df_filtrato["Intermediario"].isin(["", " ", None])
            ]

            intermediari = df_filtrato["Intermediario"].unique()

            for int_nome in intermediari:
              int_pulito = re.sub(r'[\\/:*?"<>|]', "_", str(int_nome))
              df_sub_int = df_filtrato[df_filtrato["Intermediario"] == int_nome]

              fogli_lista = {
                  k: v
                  for k, v in df_sub_int.groupby("FINANZIARIA")
                  if k != "NA" and str(k) != "nan"
              }

              if not fogli_lista:
                continue

              excel_buffer = io.BytesIO()
              wb = openpyxl.Workbook()
              wb.remove(wb.active)

              for fin_nome, df_fin in fogli_lista.items():
                nome_sheet = re.sub(r'[\\/:*?"<>|]', "_", str(fin_nome))[:31]
                ws = wb.create_sheet(title=nome_sheet)

                headers = list(df_fin.columns)
                ws.append(headers)
                for row in df_fin.itertuples(index=False):
                  ws.append(list(row))

                ws.auto_filter.ref = ws.dimensions
                for col in ws.columns:
                  max_len = max(len(str(cell.value or "")) for cell in col)
                  col_letter = get_column_letter(col[0].column)
                  ws.column_dimensions[col_letter].width = max(max_len + 3, 10)

              wb.save(excel_buffer)
              excel_buffer.seek(0)
              zip_file.writestr(f"{int_pulito}.xlsx", excel_buffer.read())

          zip_buffer.seek(0)
          st.session_state["zip_buffer_intermediari"] = zip_buffer
          st.success("Tutti i report per intermediario sono stati generati!")

      except Exception as e:
        st.error(
            "❌ Si è verificato un errore durante l'esecuzione della query"
            " SQL:"
        )
        st.exception(e)
        traceback.print_exc()

  if st.session_state["zip_buffer_intermediari"] is not None:
    st.markdown("---")
    st.download_button(
        label="📦 Scarica Archivio ZIP (Report Intermediari)",
        data=st.session_state["zip_buffer_intermediari"],
        file_name="Report_Intermediari_Excel.zip",
        mime="application/zip",
        width="stretch",
    )
