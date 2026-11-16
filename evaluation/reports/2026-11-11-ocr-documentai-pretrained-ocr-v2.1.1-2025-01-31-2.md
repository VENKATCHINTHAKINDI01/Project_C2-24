# OCR accuracy — mock_v1 (SYNTHETIC) — 2026-11-11

EVALUATION ONLY. Hand transcriptions are the reference. Word recall = share of reference
words OCR recovered in order (text the transcription omits is not an error). WER is exact
but also counts that omitted text; dash variants and spacing are normalised first.
Character similarity is difflib's ratio (an approximation). Confidence is Document AI's,
weighted by token length. The gate threshold stays **uncalibrated (null)** until the
owner approves a value from this evidence.

- Files with image-only pages: **8**, OCR run: **8**
- Mean word recall: **0.9602** · mean WER: **0.3273** · mean character similarity: **0.8575**
- Record identity (canonical ID, or e-File no. for notes) read correctly from OCR text: **7/8**

| Doc | OCR pages | Min conf. | Recall | WER | Char sim. | Languages | ID from OCR | ID matches |
|---|---|---:|---:|---:|---:|---|---|:---:|
| D01 | [1, 2] | 0.9845 | 1.0 | 0.315 | 0.8696 | en | `AP-FIN01-GOMS-62-2019` | ✓ |
| D02 | [1] | 0.9825 | 0.9702 | 0.4405 | 0.8308 | en | `AP-FIN01-GOMS-71-2019` | ✓ |
| D09 | [1] | 0.9872 | 0.9869 | 0.3268 | 0.8837 | en | `AP-GAD01-GOMS-19-2018` | ✓ |
| D11 | [1] | 0.9892 | 0.9907 | 0.1481 | 0.9316 | en | `AP-USD01-SO-2-2020` | ✓ |
| D13 | [1] | 0.9743 | 0.945 | 0.3945 | 0.8171 | en, fi | `AP-USD01-CIRMEMO-USD01WRKS0-9-2023-D20230711` | ✓ |
| D15 | [2] | 0.9853 | 0.8634 | 0.6885 | 0.6456 | en | `AP-USD01-GORT-233-2024` | ✓ |
| D16 | [1] | 0.967 | 0.9783 | 0.087 | 0.9653 | en, lo, te | `None` | ✗ |
| D22 | [1] | 0.984 | 0.9474 | 0.218 | 0.9163 | en | `file:USD01-31/4/2025-VIG` | ✓ |
