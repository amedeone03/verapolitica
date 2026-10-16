# Explain this promise (`pledge_explanation_v1`)

Citizen action **«Spiegami questa promessa»** on a published pledge. It
explains the **already published** assessment in plain Italian. It does not
evaluate, score, or publish anything.

## Allowed inputs

- published pledge title and exact statement
- published classification fields (type, specificity, holder role)
- current published `PledgeAssessment` (verdict, rationale, excerpt, source URL)
- official source name linked to that assessment’s stored document

## Forbidden inputs

- pending or rejected drafts
- unpublished evidence candidates
- reviewer names, approval notes, admin comments
- other politicians’ records
- web search or model world-knowledge as factual support

## Behaviour

1. Unpublished or non-promise records → HTTP 404.
2. No published assessment → deterministic:
   «VeraPolitica non ha ancora pubblicato una valutazione per questa promessa.»
3. Published assessment, AI disabled / timeout / invalid output → deterministic
   fallback built only from those published fields.
4. Published assessment, provider configured → short Italian explanation.
   The prompt receives `PUBLISHED_VERDICT` as immutable. The model must not
   change it.

`GET /proposals/{proposal_id}/explanation`

The process never writes `PledgeAssessment`, drafts, or reviews.

## Contradiction guard

If the model names a different public status (for example «Mantenuta» when the
published verdict is `in_progress`), the API discards the text and returns the
fallback. Sources in the JSON are always the approved assessment source, never
URLs invented by the model.

## Cache

In-memory fingerprint of pledge id, published assessment id, verdict, evidence
text, prompt version, and model. No database table. Restart clears the cache.

## Production

App startup and `/health/*` do not require Ollama. With blank
`VERAPOLITICA_LLM_PROVIDER` the endpoint still returns the fallback.
Prompt file: `backend/app/pipeline/prompts/pledge_explanation_v1.txt`.
