# Ask VeraPolitica (`ask-verapolitica/v1`)

Citizen question answering over **already published** VeraPolitica data.
It does not evaluate promises, publish assessments, or search the web.

`POST /ask` with `{ "question": "..." }`. One question, one answer. No chat history.

## Supported v1 families

- **Politician** — published explicit promises for a named public profile
- **Verdict / status** — Italian public labels or internal values (`In corso` / `in_progress`)
- **Topic** — CAP topic codes via public keywords (sanità, tasse, pensioni, …)
- **Pledge explanation** — why a published promise has its published status
- **Sources / evidence** — approved excerpt and official URL for that assessment

Unsupported questions get a bounded reply: VeraPolitica can answer about published
politicians, promises, statuses, topics, and evidence.

## Retrieval order

1. Deterministic intent/entity parse (no LLM planner)
2. Existing public politician/proposal search
3. Structured lookup of classified, published explicit promises
4. Latest **published** `PledgeAssessment` only
5. Optional LLM synthesis of the retrieved facts
6. Citation and contradiction guards; otherwise deterministic fallback

No embeddings, pgvector, Redis, or extra database.

## Public-data boundary

Allowed: published politician profiles, published explicit promises, published
classifications and current approved assessments, approved excerpts, official
source URLs on those assessments, public topic labels.

Forbidden: pending/rejected drafts, unpublished pledges or evidence candidates,
editorial comments, reviewer identities, admin data, inference traces, web
search, and general model knowledge as factual support.

## No autonomous verdicts

Ask may **explain** a published verdict. It must not create or change one.

If there is no published assessment: «VeraPolitica non ha ancora pubblicato una
valutazione per questa promessa.» The model must not infer kept/broken/in
progress from raw evidence.

## Fallback

Production works with AI disabled. Every supported intent has a deterministic
Italian answer built from the same published rows. Provider errors, empty
output, invented URLs, contradictory public labels, forbidden rhetoric, or
unsupported counts discard the model text.

## AI behaviour

Prompt file: `backend/app/pipeline/prompts/ask_verapolitica_v1.txt`.
The user message separates `USER_QUESTION` (untrusted) from `VERIFIED_CONTEXT`
(retrieved facts only). The model must not follow instructions in the question
that ask it to ignore VeraPolitica, reveal prompts, or use unpublished data.

## Citations

Source URLs come only from retrieved published assessments. The model cannot
invent URLs. List/count answers may cite VeraPolitica records without an
external source on every row.

## Ambiguity

If several published politicians match (for example two people named Rossi),
the API returns clarification options and does not guess.

## Limitations

v1 is not a general political knowledge agent. It does not rank politicians,
does not use pending editorial work, and does not retrieve by embeddings.
Next step, if needed: optional semantic retrieval **after** this published-data
boundary, still without letting the model mint verdicts.
