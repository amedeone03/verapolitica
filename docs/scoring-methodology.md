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
assessment yet), `in_progress`, `stalled`.

Every verdict is first a `PledgeAssessmentDraft` that must carry:

* an evidence label following FEVER (Thorne et al. 2018): `supports`, `refutes`,
  or `not_enough_info`. `supports` may propose `kept`, `partially_kept` or
  `in_progress`; `refutes` may propose `broken` or `stalled`; `not_enough_info`
  never changes a verdict;
* an excerpt that exists verbatim in a stored official document (or one of its
  chunks). This is checked by code before the draft exists, so a model cannot
  cite text that is not there (Gao et al. 2023, ALCE);
* a rationale.

Publication rules:

* one human approval publishes a draft; **`broken` needs two distinct reviewers**;
* an editor cannot be the only approver of a draft they proposed;
* a draft dated before the currently published verdict cannot be published;
* `PledgeAssessment` rows are append-only; the current verdict is the latest row.

> **Current limitation.** The admin API uses one shared bearer credential. The
> `reviewer` / `coder` name sent with an approval or audit code is recorded as
> `<credential identity>/<name>` and is an attestation, not an authenticated
> identity. Real four-eyes control requires per-user editorial accounts.

## 3. Evidence matching (monthly job `pledge-evidence`)

For every classified, non-vague, `action` pledge whose verdict is still open:

1. retrieve candidate passages from stored `DocumentChunk`s with BM25 over
   accent-insensitive, prefix-stemmed Italian tokens; an optional embedding
   ranker is fused with reciprocal rank fusion (no embedding backend ships yet);
2. ask an `EvidenceJudge` for a FEVER judgment, proposed verdict and excerpt;
3. reject anything that fails the rules in section 2; turn the rest into drafts
   with `origin=evidence_matcher`, retrieval scores and judge name/version.

The default judge abstains (`not_enough_info`), so nothing is proposed until a
judge has been validated against the gold set (see `docs/ai-evaluation.md`).
`outcome` pledges are skipped: an act cannot prove an outcome. They need a
statistics matcher (ISTAT/MEF), which is not implemented.

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
