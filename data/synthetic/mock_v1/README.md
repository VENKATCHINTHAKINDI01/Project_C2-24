# C2-24 mock corpus — what the department data will look like

**Synthetic test data.** The formats are modelled on published Andhra Pradesh Government Orders, memos, proceedings and e-Office notings. The departments' contents, numbers, names and decisions are all invented ("Urban Services" is a placeholder department). Every page carries a "SYNTHETIC TEST DATA" footer.

As-of date for every status in the corpus: **02-10-2026**.

---

## 1. What the real data will look like (research findings)

### 1.1 Document types you should expect

| Type | What it is | How it is numbered (real examples) | Hierarchy |
|---|---|---|---|
| **G.O.(Ms)** – Manuscript series | Policy orders, retained permanently | `G.O.Ms.No.116 Dated:07-06-2022`; `G.O.Ms.No:15 Dated:19.04.2025` | High |
| **G.O.(Rt)** – Routine series | Sanctions and routine orders, retained about 5 years | `G.O.RT.No. 2706 Dated: 28-10-2025` | Below Ms |
| **Memo / Circular Memo** | Instructions, clarifications, continuations | `Circular Memo. No. FIN01-HROPDPP(ICCP)/2/2019`; `Cir.Memo.No.1249673/11/75512020/PC-TA/2022-1`; `Circular Mem No.2745769` | Below G.O. |
| **Proceedings (Rc.No.)** | Orders of a Head of Department (Director, Commissioner) | `Rc.No.ESE02/576/2024-MODAL SCHOOL-CSE` | Below Government |
| **Standing Order / Office Order** | Internal standing procedure of a department | Department-specific | Internal |
| **e-Office note file** | Note-sheet trail: dealing hand → SO → AS → DS → Secretary | e-File `ESE02-17/116/2022-PS1`, Computer No `1930111`; `FIN04-22/11/2025-BUDGET SEC-DOID` | Decision / precedent |
| **U.O. Note** | Inter-departmental internal reference (e.g. Finance concurrence) | `U.O.Note No…dt…` | Supporting |

### 1.2 Anatomy of a G.O. (stable across departments and years)

`GOVERNMENT OF ANDHRA PRADESH` → `ABSTRACT` (one-line subject ending "– Orders – Issued.") → `<DEPARTMENT> (<SECTION>) DEPARTMENT` → `G.O.Ms.No.X Dated: dd-mm-yyyy` → **Read the following:** (numbered references, i.e. citations of earlier G.O.s, letters and e-files) → `ORDER:` (numbered paragraphs, often with (i), (ii) sub-clauses) → `(BY ORDER AND IN THE NAME OF THE GOVERNOR OF ANDHRA PRADESH)` → signatory name and designation → `To` / `Copy to` → `//FORWARDED :: BY ORDER//  SECTION OFFICER` → `SF/SC (<computer no.>)`.

**Why this matters for us:** the "Read the following" list is a ready-made citation graph, and the ORDER paragraphs carry the relationship language.

### 1.3 Relationship language to extract (supersession graph)

| Phrase in the text | Relation |
|---|---|
| "in supersession of the orders issued in the references 9th & 10th read above" | `SUPERSEDES` (points to items in the Read list, not to G.O. numbers) |
| "AMENDMENT – In para 2(i)… for the words '30-06-2019', the words '10-07-2019' shall be substituted" | `AMENDS` (clause-level) |
| "In continuation of the orders issued in the reference 18th read above" | `CONTINUES` / extends validity |
| "the following clarifications are issued" | `CLARIFIES` |
| "hereby withdrawn / cancelled" | `REPEALS` |
| "up to 31-03-2026" / "until further orders" | `effective_to` / open-ended |

**Key finding:** supersession usually refers to *Read-list positions* ("reference 2nd read above"). So the extractor must resolve the Read list first and then map the ordinals.

### 1.4 e-Office specifics

- **Notes:** green notes are final; yellow notes are drafts (e.g. dictation by PA); **DFA** is a draft for approval of the outgoing letter or G.O.; **PUC** is the paper under consideration.
- **Flags:** references are flagged A, B, C.
- **Paragraphs** are numbered continuously.
- **Sign-off:** each note ends with the officer's name, designation and timestamp.
- **Typical phrases:**
  - "It is submitted that…"
  - "Submitted. May approve."
  - "If approved, DFA is put up."
  - "Approved. Issue orders."
- **Numbering:** e-File numbers and Computer Numbers both appear inside other documents' Read lists. Treat both as identifiers.

### 1.5 Classification and retention

- **Security grading (CSMOP):** Top Secret / Secret / Confidential / Restricted (plus unclassified).
  - Published G.O.s (GOIR, e-Gazette) are effectively public.
  - Confidential G.O.s and vigilance or disciplinary files are not published.
  - **Recommendation:** align our classification enum to these grade names (UNCLASSIFIED < RESTRICTED < CONFIDENTIAL < SECRET), which this corpus already uses. Our earlier plan placed "RESTRICTED" at the top, which is the reverse of CSMOP.
- **Disposal categories (AP office procedure):**

  | Category | Meaning |
  |---|---|
  | R.Dis | Permanent (now 50 years) |
  | D.Dis | 10 years |
  | L.Dis | 1 year |
  | K.Dis | 1–10 years |
  | N / F | No retention |

  The manual's **"chaining of disposals"** (back-numbers linking earlier files) is an official precedent trail and is worth asking the department for.

### 1.6 Formats and language

- **Formats to expect:** native PDFs (recent), scanned image PDFs (older years), phone photos of printed circulars, DOCX drafts, XLSX annexures. Mixed PDFs are common (native order plus a scanned annexure).
- **Language:** English is dominant. Many G.O.s carry a Telugu abstract or a Telugu version, and HOD circulars to field offices are often fully in Telugu.
- **GOIR metadata per G.O.:** department code (e.g. `ESE01`), section (e.g. `PROGRAM-II`), type (Ms/Rt), number, date, category, language.
- **File naming on GOIR / mirrors:** `2025FIN_RT2706_E.pdf` = year + department + type + number + language.

---

## 2. What's in this mock corpus

**29 documents** across 3 departments: Finance (HR.I), GAD (Services-A), and Urban Services (Estt.I / Works / Vigilance).

| Format | Count | Ingestion path it tests |
|---|---|---|
| Native PDF | 17 | Native text |
| Scanned image PDF (skewed, noisy) | 5 | OCR |
| Mixed PDF (native page + scanned annexure) | 1 | Per-page routing |
| Phone photo JPG (one in Telugu) | 2 | OCR + pre-processing |
| DOCX (e-Office draft notes) | 3 | Native |
| XLSX annexure (formulas) | 1 | Table parsing |

### Storylines built in

1. **Transfer guidelines chain** (Finance): G.O.Ms.62/2019 → amended by G.O.Ms.71/2019 → superseded by G.O.Ms.88/2022 → superseded by G.O.Ms.31/2025 → clarified by Memo dt.21-05-2025. The ceiling changes from 20% to 15%, which lets as-of-date questions be tested properly.
2. **Delegation of works powers** (Urban Services): G.O.Ms.14/2021 (Commissioner up to Rs.50 lakh) → superseded by G.O.Ms.27/2024 (Rs.1 crore, emergency Rs.1 crore with ratification). A 2023 Circular Memo allowing **Rs.1.50 crore was never withdrawn**: this is the hierarchy conflict. A Telugu Commissioner's circular (photo) restates the correct limit.
3. **Outsourcing**: G.O.Ms.40/2020 (Finance Department concurrence required) → Circular Memo extension to 31-03-2025 (expired) → G.O.Rt.1184/2025 extension to 31-03-2026 (expired).
4. **Precedent notings**: four spouse-ground transfer decisions (2022 approved, 2023 rejected because the ban was in force, 2025 approved, 2025 rejected because of a pending enquiry) and two emergency-works decisions (2023 Commissioner, 2024 Government).
5. **Classified material**: a CONFIDENTIAL vigilance enquiry (two notes), a CONFIDENTIAL Estt note that reveals the enquiry, and a SECRET V&E report.
6. **Three live proposals (2026)** with planted conflicts:
   - **D27, transfer:** A, F, C, E, B, D
   - **D28, emergency works:** G, C, D
   - **D29, outsourcing:** F, C

### Metadata files

| File | Use |
|---|---|
| `manifest.json` | Full ground truth per document: canonical ID, raw reference, type, hierarchy level, classification, status as of 02-10-2026, effective dates, relations, planted conflicts |
| `documents_index.csv` | The same information flattened into one table |
| `users.csv` | 8 officers (Officer A–H) across roles, sections and clearances |
| `access_matrix.csv` | ALLOW/DENY for every user × document, computed from the policy below |
| `ground_truth/relations.csv` | The supersession / amendment / citation graph |
| `ground_truth/conflicts.json` | The answer key for the 7 conflict types |
| `ground_truth/golden_questions.json` | 24 eval questions with expected and forbidden documents, ladder level, answer key and expected conflicts; 7 are leakage probes |
| `ground_truth/text/*.txt` | Exact source text, for measuring OCR / extraction accuracy |

**Access policy used:**
1. UNCLASSIFIED (published) → anyone.
2. Otherwise all of the following must hold:
   - same department;
   - clearance ≥ classification;
   - one of: Deputy Secretary or above, same section, or assigned to the file.

---

## 3. Things to confirm when the real data arrives

1. The real **classification grades** and who holds which clearance.
2. Whether masked data keeps G.O. / e-File / Computer numbers intact. They are the backbone of canonical IDs and the citation graph.
3. Whether supersession is recorded anywhere besides the text (registers, e-Office links).
4. The department's **section codes** and e-File number pattern.
5. The Telugu share, and whether old files are scans or photos.
6. Whether R.Dis / D.Dis disposal chains or a precedent register exist.

## Sources

- [AP Government Orders Issue Register (GOIR)](https://goir.ap.gov.in/)
- [Internet Archive mirror of GOIR — item metadata (dept code ESE01, section, GO type)](https://archive.org/details/in.gov.andhra.goir.2024-02-26.E-487896)
- [G.O.Ms.No.116, Finance (HR.I-Plg.&Policy), 07-06-2022 — supersession wording, Read list, SF/SC](https://images.tv9telugu.com/wp-content/uploads/2022/06/go-ms-116-transfers-postings-guidelines.pdf)
- [G.O.Ms.No.58, School Education, 22-06-2023 — e-File and Computer No. format](https://www.aputf.org/wp-content/uploads/2023/06/GO-Ms.No_.58-Dt.22.06.2023.pdf)
- [G.O.Ms.No.15, School Education (Services-I), 19-04-2025 — layout, signature, forwarding](https://www.aputf.org/wp-content/uploads/2025/04/2025SE_36315_MS15_E-Dt.19.04.2025.pdf)
- [G.O.Rt.No.2706, Finance, 28-10-2025 — Rt series, e-File in Read list](https://www.aputf.org/wp-content/uploads/2025/10/2025FIN_RT2706_E.pdf)
- [G.O.Ms.No.38, Finance, 28-04-2020 — "In continuation of", FD concurrence](https://www.aputf.org/wp-content/uploads/2020/06/2020FIN_MS38.pdf)
- [Proceedings Rc.No.ESE02/576/2024, Director of School Education — HOD proceedings format](https://www.aputf.org/wp-content/uploads/2024/09/Rc.No_.ESE02-576-Dt.15.09.2024.pdf)
- [Circular Memo, Finance (HR.I), 30-04-2020](https://s3.ap-south-1.amazonaws.com/apfinance.gov.in/uploads/More/New-Circular-Memo_2_2019.pdf)
- [Circular Memo No.1249673/…/PC-TA/2022-1, Finance (PC-TA)](https://www.aputf.org/wp-content/uploads/2022/01/Cir.Memo_.No_.1249673D.22.01.2022.pdf)
- [Circular Memo No.2745769, Institutional Finance, 03-07-2025](https://www.aputf.org/wp-content/uploads/2025/07/Cir.Memo_.No_.2745769-Dt.03.07.2025.pdf)
- [AP Secretariat Office Manual / Business Rules — G.O. series, noting, flags, channel of submission](https://worksaccounts.com/wp-content/uploads/2020/08/Secretariat-Procedures-Business-Rules.pdf)
- [Noting, drafting and file management (AP Revenue Academy)](https://revenueacademy.in/api/uploads/1753595995_139.pdf)
- [Office management — disposal categories R/D/L/K, chaining of disposals](https://www.servicesjournal.in/2024/07/office-management-noting-and-drafting.html)
- [File management — note file / current file (ETC Srikalahasti, AP)](https://etcsrikalahasti.ap.gov.in/assets/pdf/Filemgt.pdf)
- [e-Office file management — receipts, green/yellow notes, DFA (CAG training)](https://cag.gov.in/uploads/subsite_whats_new/WBM-eoffice-0615ada10562272-33366978.pdf)
