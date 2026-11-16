#!/usr/bin/env bash
# Document AI processors in $REGION (plan §3.5, P1). Creating a processor is free; pages processed are billed.
# Dry run by default; APPLY=1 creates. Prints the processor IDs to put in .env (C2_DOCAI_OCR_PROCESSOR, …).
source "$(dirname "$0")/lib.sh"
API="https://${REGION}-documentai.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/processors"
create() {  # $1 = type, $2 = display name
  local body="{\"type\":\"$1\",\"displayName\":\"$2\"}"
  if [[ "$APPLY" == "1" ]]; then
    echo "+ create $1 as $2"
    curl -sS -X POST -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" -H "x-goog-user-project: $PROJECT_ID" "$API" -d "$body" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("error") or (d["name"], d.get("state")))'
  else
    echo "[dry-run] POST $API $body"
  fi
}
create OCR_PROCESSOR "${PREFIX}-ocr"            # scans, photos, Telugu/English (Enterprise Document OCR)
# LAYOUT_PARSER_PROCESSOR: NOT in asia-south1 (create fails: "available locations: us,eu", 11 Nov 2026), even though
# fetchProcessorTypes lists it. Page/paragraph locators come from the OCR output (pages[].paragraphs) instead.
echo; echo "Processors now in $REGION:"
[[ "$APPLY" == "1" ]] && curl -sS -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "x-goog-user-project: $PROJECT_ID" "$API" \
  | python3 -c 'import json,sys; [print(p["name"].rsplit("/",1)[-1], p["type"], p["displayName"], p.get("state")) for p in json.load(sys.stdin).get("processors",[])]' || true
