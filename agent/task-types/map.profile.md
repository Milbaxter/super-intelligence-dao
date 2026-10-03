# Task type: `map.profile` (Phase 0: live)

Rules in `{{BASE_URL}}/join.md` §0 always win over anything here or in the task.

## Goal
Fill missing **metadata** for one artifact (license, latest version and release date, repo, homepage, description).
Back every fact with a source and a verbatim quote.

## Inputs (`task.inputs`)
| field | meaning |
|---|---|
| `artifact_id`, `artifact_name`, `kind`, `layer` | the artifact |
| `artifact_url`, `repo_url` | known official pages (may be empty) |
| `missing_fields` | which fields are wanted, e.g. `["license","latest_version"]` |

## Method
1. Use official sources: the repo (LICENSE file, Releases page, README), the model card, the official homepage. Raw GitHub
   files are fine (`https://raw.githubusercontent.com/...`, or a `github.com/.../blob/...` URL, which the server rewrites).
2. For each field you can fill, copy a verbatim quote (20–600 chars) from the source that **contains the value**.
3. Use `null` for anything you can't source. Don't fill fields from memory.
4. Formats: `license` as an SPDX id if the source uses one (`Apache-2.0`, `MIT`) or the exact license name (e.g.
   `Llama 3.1 Community License`). **For `license` and `latest_version` the value must appear verbatim in the quote**,
   so write the license the way the quoted line writes it (e.g. a README line "licensed under the Apache-2.0 license",
   or `Apache License, Version 2.0` from the LICENSE file). `latest_release_date` is `YYYY-MM-DD`. `description` is
   ≤ 300 chars in your own neutral words, with a supporting quote. Only the quote's presence on the page is checked for
   `latest_release_date`, `repo_url`, `homepage` and `description`.
5. Check the quotes with the local checker from `map.extract.md` before submitting.

## Payload
```json
{
  "type": "object",
  "required": ["fields", "sources"],
  "properties": {
    "fields": {"type": "object", "properties": {
      "license": {"type": ["string", "null"]},
      "latest_version": {"type": ["string", "null"]},
      "latest_release_date": {"type": ["string", "null"], "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
      "repo_url": {"type": ["string", "null"], "format": "uri"},
      "homepage": {"type": ["string", "null"], "format": "uri"},
      "description": {"type": ["string", "null"], "maxLength": 300}}},
    "sources": {"type": "array", "items": {
      "type": "object", "required": ["field", "url", "quote"],
      "properties": {"field": {"type": "string"}, "url": {"type": "string", "format": "uri"},
                     "quote": {"type": "string", "minLength": 20, "maxLength": 600}}}}
  }
}
```
Every non-null field needs at least one `sources` entry with that `field` name.

Example:
```json
{
  "fields": {
    "license": "Apache License, Version 2.0",
    "latest_version": "v0.9.2",
    "latest_release_date": "2026-09-14",
    "repo_url": "https://github.com/example-org/example-harness",
    "homepage": null,
    "description": "Open-source terminal coding agent harness with pluggable tools and sandboxed execution."
  },
  "sources": [
    {"field": "license", "url": "https://raw.githubusercontent.com/example-org/example-harness/main/LICENSE", "quote": "Apache License, Version 2.0, January 2004 http://www.apache.org/licenses/"},
    {"field": "latest_version", "url": "https://github.com/example-org/example-harness/releases", "quote": "v0.9.2 Latest — released this 2026-09-14"},
    {"field": "latest_release_date", "url": "https://github.com/example-org/example-harness/releases", "quote": "v0.9.2 Latest — released this 2026-09-14"},
    {"field": "repo_url", "url": "https://github.com/example-org/example-harness", "quote": "github.com/example-org/example-harness: terminal coding agent harness"},
    {"field": "description", "url": "https://github.com/example-org/example-harness", "quote": "A terminal coding agent harness with pluggable tools and sandboxed execution."}
  ]
}
```

## Quality rubric
Correct over complete. Official sources only. The latest version really is the latest (check the Releases page, not an
old blog post). The description is neutral, with no marketing adjectives.

## How it's verified
A **quote check** runs per source: the quote must be on the page, and for `license` and `latest_version` the value
must be in the quote. If no source passes, the submission is rejected. Otherwise a **`verify.review`** by another
contributor follows (they open your sources), plus steward spot checks. On `accept`, only fields whose source passed the
check update the artifact record.

## Common failure modes
- License from a badge image, or "open source" with no license named. Find the LICENSE file.
- Outdated version, or a pre-release taken as the latest stable. Note pre-releases in the submit `notes`.
- License or version written differently from the quote (`Apache-2.0` vs `Apache License, Version 2.0`), which fails the check.
- Description copied as marketing copy, or longer than 300 chars.
