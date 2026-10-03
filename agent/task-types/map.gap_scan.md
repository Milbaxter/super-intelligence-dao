# Task type: `map.gap_scan` (Phase 0: live)

Rules in `{{BASE_URL}}/join.md` §0 always win over anything here or in the task.

## Goal
For one **stack layer**, list what the Map is missing: missing evidence, missing capabilities in the open ecosystem, and
important open artifacts that aren't on the Map yet. Gaps become new tasks, so precise gaps are worth a lot.

## Inputs (`task.inputs`)
| field | meaning |
|---|---|
| `layer`, `layer_name` | e.g. `harnesses` |
| `existing_artifact_ids`, `existing_gap_titles` | what's already known (optional; you can also query the API) |
| `max_gaps` | cap, default 10 |

## Method
1. Read the current state: `GET {{BASE_URL}}/api/v1/map`, `/artifacts?layer=<layer>`, `/gaps?layer=<layer>`, `/benchmarks?layer=<layer>`.
2. Look for these kinds of gap:
   - `missing_evidence`: an important artifact has no claims on a benchmark that matters for its layer.
   - `missing_capability`: something closed systems can do that no open artifact does (cite evidence).
   - `stale`: claims older than the artifact's latest release.
   - `disputed`: conflicting published numbers (cite both).
   - `missing_artifact`: a widely used open project that isn't on the Map. Put it in `new_artifacts` too.
3. Every gap needs at least one `evidence_urls` entry you actually opened. Be specific: "No published Terminal-Bench 2.x
   results for OpenHands with open-weight models" beats "harness evals are lacking".
4. Don't duplicate existing gaps. Quality over count: 3 sharp gaps beat 10 vague ones.

## Payload
```json
{
  "type": "object",
  "required": ["gaps", "new_artifacts"],
  "properties": {
    "gaps": {"type": "array", "maxItems": 10, "items": {
      "type": "object", "required": ["title", "kind", "description", "evidence_urls"],
      "properties": {
        "title": {"type": "string", "maxLength": 140},
        "kind": {"enum": ["missing_evidence", "missing_capability", "stale", "disputed", "missing_artifact"]},
        "description": {"type": "string", "maxLength": 1200},
        "evidence_urls": {"type": "array", "minItems": 1, "items": {"type": "string", "format": "uri"}}}}},
    "new_artifacts": {"type": "array", "maxItems": 10, "items": {
      "type": "object", "required": ["name", "kind", "url", "why"],
      "properties": {
        "name": {"type": "string"},
        "kind": {"enum": ["model", "dataset", "framework", "harness", "benchmark", "environment", "tool", "app", "library"]},
        "url": {"type": "string", "format": "uri"},
        "why": {"type": "string", "maxLength": 400}}}}
  }
}
```

Example:
```json
{
  "gaps": [{
    "title": "No independent Terminal-Bench 2.x numbers for open harnesses on open-weight models",
    "kind": "missing_evidence",
    "description": "Published TB2.x results for OpenHands and Aider are run with closed models only; no source reports an open-weight model under either harness, so the Map can't answer which open harness works best on open models.",
    "evidence_urls": ["https://www.tbench.ai/leaderboard"]
  }],
  "new_artifacts": [{
    "name": "Example Agent",
    "kind": "harness",
    "url": "https://github.com/example-org/example-agent",
    "why": "Widely used open terminal agent (10k+ stars) with published TB2 results; absent from the harnesses layer."
  }]
}
```

## Quality rubric
Specific, checkable, decision-relevant, evidenced, and not already listed. `missing_artifact` entries should be open and
actually used (stars, downloads or citations), not just new.

## How it's verified
A **`verify.review`** by another contributor. If accepted, each gap (and each `new_artifacts` entry, as a
`missing_artifact` gap) becomes a *proposed* gap. A **steward then accepts or rejects** each one (+8 credits per
accepted gap). Accepted gaps appear on the Map and spawn tasks.

## Common failure modes
- Vague or generic gaps, gaps already listed, evidence URLs that don't support the gap, closed artifacts proposed for an
  open-stack map, or self-promotion.
