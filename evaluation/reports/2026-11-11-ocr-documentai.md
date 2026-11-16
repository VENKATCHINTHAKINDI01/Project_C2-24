# OCR accuracy — mock_v1 (SYNTHETIC) — 2026-11-11

EVALUATION ONLY. Hand transcriptions are the reference. Word error rate (WER) is exact;
character similarity is difflib's ratio (an approximation). Confidence is Document AI's,
weighted by token length. The gate threshold stays **uncalibrated (null)** until the
owner approves a value from this evidence.

- Files with image-only pages: **8**, OCR run: **8**
- Mean WER: **0.4627** · mean character similarity: **0.7647**
- Canonical ID read correctly from OCR text: **2/8**

| Doc | OCR pages | Min conf. | WER | Char sim. | Languages | ID from OCR | ID matches |
|---|---|---:|---:|---:|---|---|:---:|
| D01 | [1, 2] | 0.9769 | 0.3394 | 0.8662 | en, und | `None` | ✗ |
| D02 | [1] | 0.9792 | 0.4911 | 0.8223 | en, und | `None` | ✗ |
| D09 | [1] | 0.9796 | 0.3506 | 0.8812 | en, und | `None` | ✗ |
| D11 | [1] | 0.9843 | 0.1751 | 0.927 | en, und | `AP-USD01-SO-2-2020` | ✓ |
| D13 | [1] | 0.9626 | 0.4273 | 0.8253 | en, und | `None` | ✗ |
| D15 | [2] | 0.9814 | 0.6739 | 0.6464 | en, und | `AP-USD01-GORT-233-2024` | ✓ |
| D16 | [1] | 0.5077 | 0.9681 | 0.2389 | en, is, jv, lt, sk, sv, und | `None` | ✗ |
| D22 | [1] | 0.9819 | 0.2761 | 0.9106 | en, und | `None` | ✗ |
