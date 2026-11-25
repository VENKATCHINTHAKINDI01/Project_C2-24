# Demo scenario — from file creation to an issued order (mock e-Office sandbox)

SYNTHETIC data; mock hierarchy `[To confirm]` (ADR-0070). Works the same in every department: an
officer can send a file only to officers of the file's department, and only while it is with them.

**Matter:** Sri P. Ravi, Junior Assistant, asks for a transfer on spouse grounds (Urban Services, Estt.I).
**Chain:** Section Officer (Estt.I) → Assistant Secretary (Estt.) → Deputy Secretary → Secretary to Government → back to the Section Officer → order put up to the Secretary → issued.

| # | Sign in as | Do this | What to show |
|---|---|---|---|
| 1 | Officer A — Section Officer (Estt.I) | **Create new** → subject *"Establishment – Sri P. Ravi, Junior Assistant – Request for transfer on spouse grounds – Reg."* → **Create file** | The file opens; "With you" |
| 2 | Officer A | Click the AI button | The file chat opens with the file's summary |
| 3 | Officer A | **Write a note** (facts of the request) → **Save note** | Yellow Note, editable |
| 4 | Officer A | **Send** → Send to *Assistant Secretary (Estt.)*, remarks *"Submitted for orders, please."* (optional: **Check before sending**) → **Send** | Note signed (Green); file under **Sent**; "With Assistant Secretary" |
| 5 | Officer B — Assistant Secretary | **File inbox** → open the file → write a note → **Send** to *Deputy Secretary* | Inbox shows who sent it and when |
| 6 | Officer E — Deputy Secretary | Open → note *"Submitted for orders."* → **Send** to *Secretary to Government* | |
| 7 | Officer F — Secretary | Open → AI: *"do I have any action on this file?"* → note *"Approved. Issue orders."* → **Send** to *Section Officer (Estt.I)* | Movement marked "sent back" |
| 8 | Officer A | Open → AI: *"prepare a draft"* (the approval picks a G.O.Rt.) → **Create DFA draft** → check/fill any marked gaps → **Put up for approval…** → *Secretary to Government* → **Put up and send** | Pre-send flags shown as open points; only the Secretary sees it for approval |
| 9 | Officer F | Open → **Approve, sign and issue** | "Issued: G.O.Rt.No.9001 Dated …" on the file for everyone who can open it; the order enters institutional memory |
| 10 | Officer F | **Movements** tab | The whole trail with remarks |
| 11 | Any officer of the department | **Ask AI**: *"what orders were issued on transfer of Sri P. Ravi?"* | Cited answer from the issued order |
| 12 | Monitoring Officer (mock) | — | Only the Monitoring pad |

Without Gemini (local runs) the draft's fields are not filled automatically: fill the marked `[ ]`
gaps with **Edit** before putting it up. With Gemini (Cloud Run) they are filled from the notes.
