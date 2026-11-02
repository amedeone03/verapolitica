# Pledge scorecard methodology (`pledge-score/v1`)

This document is the public method behind the "detto / fatto" scorecard. It is
versioned: every published assessment records the methodology version it was
approved under, so older scores stay reproducible if the method changes.

Code: `backend/app/scoring/` (pure algorithms), `backend/app/services/pledge_service.py`,
`backend/app/services/pledge_evidence_service.py`, models in `backend/app/models/pledge.py`.

## 1. What counts as a pledge

A pledge is a published `Proposal` of type `explicit_promise` with at least one
`commitment_owner`. An editor classifies it (`PledgeClassification`):

| Field | Values | Source in the literature |
|---|---|---|
| `specificity` | `high`, `medium`, `vague` | Royed (1996): only specific, verifiable commitments are pledges. `vague` pledges are tracked but never scored. |
| `commitment_type` | `action`, `outcome` | Thomson et al. (2017, CPPG): "I will present a bill" is verified with official acts; "I will cut unemployment" with statistics. |
| `cap_topic_code` | Comparative Agendas Project major topic code | Keeps topics comparable with political-science datasets. |
| `holder_role` | `government_single_party`, `government_coalition`, `opposition`, `unknown` | Thomson et al. (2017): fulfilment depends mostly on institutional power. Recorded as of the pledge, with the mandate window. |

Unclassified pledges are listed as `unclassified_pledges` and excluded from scoring.

## 2. Fulfilment verdicts

Closed: `kept`, `partially_kept`, `broken`. Open: `not_yet_rated` (default, no
assessment yet), `in_progress`, `stalled`. Public labels (presentation only;
internal values are unchanged):

| Internal value | Public label | Colour |
|---|---|---|
| `kept` | Mantenuta | green |
| `partially_kept` | Mantenuta parzialmente | yellow |
| `in_progress` | In corso | blue |
| `stalled` | Iter bloccato | black |
| `broken` | Non mantenuta | red |
| `not_yet_rated` | Non ancora valutata | grey |

`in_progress` and `stalled` remain open states and do not enter the score.
`not_yet_rated` means no published assessment yet. Only published assessments
are public.

Every verdict is first a `PledgeAssessmentDraft` that must carry:

* an evidence label following FEVER (Thorne et al. 2018): `supports`, `refutes`,
  or `not_enough_info`. `supports` may propose `kept`, `partially_kept` or
  `in_progress`; `refutes` may propose `broken` or `stalled`; `not_enough_info`
  never changes a verdict;
* an excerpt that exists verbatim in a stored official document (or one of its
  chunks). This is checked by code before the draft exists, so a model cannot
  cite text that is not there (Gao et al. 2023, ALCE);
* a rationale.

Practical interpretation used by reviewers (the public formula does not change):

* `not_yet_rated` — no approved assessment yet. Pending drafts do not count.
* `in_progress` — later official follow-up exists (funding, a bill, a framework
  law) but the commitment is not fully implemented.
* `stalled` — official evidence shows the effort stopped without fulfilment.
* `kept` — an official act actually implements the commitment, not merely the
  same topic. Announcement of intent alone is never `kept`. A bill introduced
  is not necessarily `kept`.
* `partially_kept` — official implementation covers only part of the pledge.
* `broken` — official action contradicts or abandons the pledge. Requires two
  distinct reviewers.

Publication rules:

* one human approval publishes a draft; **`broken` needs two distinct reviewers**;
* an editor cannot be the only approver of a draft they proposed;
* a draft dated before the currently published verdict cannot be published;
* `PledgeAssessment` rows are append-only; the current verdict is the latest row.

### 2.1 Verdicts assigned by the redazione (`/redazione`)

The redazione console is where editors assign a status to a promise. Each
member signs in with their own token (`VERAPOLITICA_REDAZIONE_MEMBERS`), so the
names in `approved_by` are authenticated identities, not attestations. On top
of the rules above, the console enforces the "Modelli di scrittura":

* **a promise is tracked only with a date and a source link** to the page that
  reports the declaration (home and section pages are refused);
* **a promise must be classified before it gets a status**: unclassified
  promises are not in the scorecard (`unclassified_pledges`), so the verifier
  fills the classification when approving a promise that has none;
* **the author never approves their own work**, not even as the second
  approver of a `broken` verdict (stricter than the service rule above).
  `broken` therefore needs two members other than the author;
* **`broken` needs a reason**: the declared deadline passed without result
  (the deadline must precede the date of the fact), the mandate ended, or an
  explicit renunciation. The reason is prefixed to the rationale the citizen
  reads;
* **the excerpt is the passage copied from the source** (news agency,
  institutional page, Gazzetta Ufficiale). It is stored with its URL as a
  `RawDocument` (`collector_version = redazione/v1`), so it is verbatim in a
  stored document; that the page really says it is what the second member
  checks before approving. Unlike the evidence matcher, editors may cite
  agencies and newspapers, as the writing models require;
* re-classifying a published promise and withdrawing published profile
  content are change requests that another member approves;
* every write, approval, rejection, withdrawal and status assignment is a row
  in the append-only `editorial_log_entries` table (the "Registro modifiche").

The admin API (`/admin/*`) and the CLI scripts still use one shared operator
credential; they are operator tools, not the editorial workflow.

## 3. Evidence matching (job `pledge-evidence`, matcher `pledge-evidence/v2`)

For every classified, non-vague, `action` pledge whose verdict is still open:

1. build a deterministic retrieval profile (actor, title, exact statement,
   topic, policy-instrument phrases, mandate dates);
2. keep only HTTPS passages from configured official hosts (governo.it,
   ministries, Gazzetta Ufficiale, Normattiva, Senato, Camera, other listed
   PA domains). Newspapers, blogs, social media and campaign sites are rejected;
3. exclude the pledge's own announcement document — that text is the
   commitment, not later evidence;
4. require the official passage to name a policy instrument from the
   commitment. Same-topic documents without that instrument abstain;
5. persist unpublished `PledgeEvidenceCandidate` rows;
6. only then ask an `EvidenceJudge`. The scheduled job still uses the
   abstaining judge. A CLI/admin run may use a conservative official-act
   heuristic (open `in_progress` only) or local qwen3:8b. Invalid model
   JSON is rejected, never rewritten;
7. fail-closed checks: verbatim excerpt, official URL, date window,
   instrument overlap, verdict/label compatibility. Failures create no draft.

The default judge abstains (`not_enough_info`). `outcome` pledges are skipped.
Nothing is auto-published. Internal judge/prompt metadata never appears on
the public scorecard.

## 4. The score

Base formula from the product specification:

```
rate = (kept + 0.5 × partially_kept) / closed
```

with three corrections:

1. **Role strata, never mixed.** The scorecard is a list of strata, one per
   `holder_role`. There is no overall number across roles, and clients must not
   rank people from different roles against each other.
2. **Closed pledges only in the denominator.** Open pledges are reported
   separately together with `mandate_progress.elapsed_fraction`.
3. **Small numbers.** Each stratum reports a 90% equal-tailed beta-binomial
   credible interval with a Jeffreys prior, Beta(kept_eq + 0.5, failures + 0.5),
   where `partially_kept` counts half on each side. Below **8 closed pledges**
   the rate is withheld (`rate_withheld_reason = below_minimum_closed_pledges`);
   the composition and the interval are still shown.

Presentation order (Naurin 2011, voters underestimate kept pledges): the API
returns the list of pledges, then each stratum's composition, then the rate.
The public scorecard links to `/methodology/scoring`.

### 4.1 Party scorecard (`/political-parties/{id}/scorecard`)

A party score is **not** an average of its members' rates. Averaging gives a
member with two closed pledges the same weight as one with forty and hides how
little evidence sits behind the number. Instead the party's pledges are pooled
and the ordinary scorer above runs on the pooled counts, stratum by stratum, so
the same intervals and the same 8-pledge minimum apply. Pooling is a weighted
mean of member rates with weights equal to closed pledges.

A pledge counts for a party when the party is a `commitment_owner`, or when a
published politician is the `commitment_owner` and was affiliated with the
party on the pledge date (`introduced_at`, else the classification's
`mandate_start`). Member pledges without a usable date are not attributed and
are reported as `unattributed_member_pledges`. Each pledge counts once.

`window=current` keeps pledges whose mandate window contains `as_of` ("attuale");
`window=all` keeps every pledge ("storica").

### 4.2 Comparison (`/compare/politicians?ids=…&role=…`)

Comparison requires one role and returns each person's stratum for that role
only; there is no cross-role ranking. The response says whether the credible
intervals overlap; when they do, the public page states that the difference is
not distinguishable with the data available.

## 5. Validation

**Agreement.** Krippendorff's alpha (nominal and ordinal over
broken < partially kept < kept) between the published verdicts and blind
auditors. Verified against the worked example in Krippendorff (2011).

**Blind audit and correction.** An admin draws a reproducible random sample
(`seed`, `sample_key`) of current closed assessments; the population and
inclusion probability are frozen at draw time. Auditors see the pledge and the
source excerpt, never the published verdict, and cannot audit verdicts they
approved. The quality report applies the design-based correction of Egami et
al. (2023):

```
Y~_i = Ŷ_i + (R_i / π) (Y_i − Ŷ_i),   rate = mean(Y~),   se = sd(Y~)/√N
```

per role stratum, next to the naive rate and the disagreement rate. A large gap
between naive and corrected rates means the published verdicts are drifting.

**Partisan skew.** `/admin/pledges/bias-audit` compares each party bloc with all
other blocs *within the same role and mandate start year*, pooled with
Mantel-Haenszel-style weights. A bloc is flagged when the 95% interval excludes
zero and the gap is at least 15 points. A flag triggers a methodological review
of the underlying verdicts; it is not proof of bias.

## 6. References

* Royed, T. J. (1996). Testing the mandate model in Britain and the United States. *BJPolS*.
* Thomson, R. et al. (2017). The fulfillment of parties' election pledges. *AJPS*.
* Naurin, E. (2011). *Election Promises, Party Behaviour and Voter Perceptions*.
* Thorne, J. et al. (2018). FEVER: a large-scale dataset for fact extraction and verification.
* Gao, T. et al. (2023). Enabling large language models to generate text with citations (ALCE).
* Egami, N. et al. (2023). Using imperfect surrogates for downstream inference (DSL).
* Krippendorff, K. (2011). Computing Krippendorff's alpha-reliability.
