"""Detect, extract, classify, metadata/relations, confidence gate (plan §4).

Implemented: content-based format detection with per-page PDF routing (`detect`); native text
extraction for PDF text layers, DOCX, XLSX, TXT, CSV (`extract`); document-type classification,
own reference, date, subject, "Read the following" list and explicit relations (`metadata`);
extraction-confidence gate holding OCR'd text until a human confirms (`gate`); the idempotent,
versioned ingestion job that ties them together and writes index, graph and temporal facts
(`pipeline`).
Not yet: Document AI OCR for scanned pages and photos (GCP), Telugu text, file-index matching of
note-to-file citations.
"""
