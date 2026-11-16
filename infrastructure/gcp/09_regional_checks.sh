#!/usr/bin/env bash
# READ-ONLY, no cost: what Document AI and Gemini offer in our region (plan §3.5, region [To confirm]).
# 1) Document AI processor types available in $REGION (and in the `us` multi-region, for comparison).
# 2) Gemini: a countTokens call (free, no generation) per model in $REGION — 200 means usable there.
# Output: regional_checks.out.txt (git-ignored).
source "$(dirname "$0")/lib.sh"
export CLOUDSDK_CORE_DISABLE_PROMPTS=1
OUT="$HERE/regional_checks.out.txt"
TOKEN="$(gcloud auth print-access-token)"
# Gemini model IDs: discovered from the Model Garden list (names change over time), unless given.
discover_models() {
  curl -sS -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT_ID" \
    "https://us-central1-aiplatform.googleapis.com/v1beta1/publishers/google/models?pageSize=200" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); ids=sorted({m["name"].rsplit("/",1)[-1] for m in d.get("publisherModels",[]) if "gemini" in m["name"] and "embedding" not in m["name"]}); print(" ".join(ids) if ids else "ERROR "+json.dumps(d.get("error",d))[:300])'
}
MODELS="${GEMINI_MODELS:-$(discover_models)}"
docai_types() {  # $1 = location
  local host="$1-documentai.googleapis.com"
  echo; echo "### Document AI processor types in $1"
  curl -sS -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT_ID" \
    "https://$host/v1/projects/$PROJECT_ID/locations/$1:fetchProcessorTypes" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("error") or "\n".join(sorted(t["type"]+("" if t.get("allowCreation") else "  (no creation)") for t in d.get("processorTypes",[]))))'
}
{
  echo "C2-24 regional checks · $(date '+%Y-%m-%d %H:%M %Z') · project=$PROJECT_ID region=$REGION"
  docai_types "$REGION"
  docai_types us
  echo; echo "### Gemini models found: $MODELS"
  echo; echo "### Gemini countTokens in $REGION (200 = usable in-region; 404 = not offered there)"
  for m in $MODELS; do
    [[ "$m" == ERROR* ]] && break
    code="$(curl -sS -o /dev/null -w "%{http_code}" -X POST \
      -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
      "https://$REGION-aiplatform.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/publishers/google/models/$m:countTokens" \
      -d '{"contents":[{"role":"user","parts":[{"text":"hello"}]}]}')"
    echo "$code  $m"
  done
} > "$OUT"
echo "Done. Output: $OUT"
