# OCR accuracy — mock_v1 (SYNTHETIC) — 2026-11-11

EVALUATION ONLY. Hand transcriptions are the reference. Word recall = share of reference
words OCR recovered in order (text the transcription omits is not an error). WER is exact
but also counts that omitted text; dash variants and spacing are normalised first.
Character similarity is difflib's ratio (an approximation). Confidence is Document AI's,
weighted by token length. The gate threshold stays **uncalibrated (null)** until the
owner approves a value from this evidence.

- Files with image-only pages: **8**, OCR run: **8**
- Mean word recall: **0.841** · mean WER: **0.4366** · mean character similarity: **0.7672**
- Record identity (canonical ID, or e-File no. for notes) read correctly from OCR text: **7/8**

| Doc | OCR pages | Min conf. | Recall | WER | Char sim. | Languages | ID from OCR | ID matches |
|---|---|---:|---:|---:|---:|---|---|:---:|
| D01 | [1, 2] | 0.9769 | 0.989 | 0.326 | 0.869 | en, und | `AP-FIN01-GOMS-62-2019` | ✓ |
| D02 | [1] | 0.9792 | 0.9583 | 0.4464 | 0.827 | en, und | `AP-FIN01-GOMS-71-2019` | ✓ |
| D09 | [1] | 0.9796 | 0.9935 | 0.3203 | 0.8839 | en, und | `AP-GAD01-GOMS-19-2018` | ✓ |
| D11 | [1] | 0.9843 | 1.0 | 0.1435 | 0.9318 | en, und | `AP-USD01-SO-2-2020` | ✓ |
| D13 | [1] | 0.9626 | 0.9633 | 0.3853 | 0.8233 | en, und | `AP-USD01-CIRMEMO-USD01WRKS0-9-2023-D20230711` | ✓ |
| D15 | [2] | 0.9814 | 0.8634 | 0.6776 | 0.6462 | en, und | `AP-USD01-GORT-233-2024` | ✓ |
| D16 | [1] | 0.5077 | 0.0435 | 0.9457 | 0.2414 | en, is, jv, lt, sk, sv, und | `None` | ✗ |
| D22 | [1] | 0.9819 | 0.9173 | 0.2481 | 0.9151 | en, und | `file:USD01-31/4/2025-VIG` | ✓ |
