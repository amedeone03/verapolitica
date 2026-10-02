# Admin API contract

The Admin API is the authenticated HTTP adapter for the existing editorial service
layer. It does not contain review or publication transactions.

## Authentication

All `/admin/*` routes require:

```http
Authorization: Bearer <VERAPOLITICA_ADMIN_API_KEY>
```

The secret comes from `VERAPOLITICA_ADMIN_API_KEY`. The reviewer recorded in final
Reviews comes from `VERAPOLITICA_ADMIN_REVIEWER_IDENTITY`, never from request JSON.
Missing or invalid credentials return 401. If no key is configured, the admin router
fails closed with 503.

## Error envelope

```json
{
  "error": {
    "code": "draft_not_reviewable",
    "message": "draft 1 cannot be approved from status 'approved'",
    "details": null
  }
}
```

- 401: missing or invalid credentials
- 404: missing draft/resource
- 409: stale draft, terminal transition, supersession, or publication conflict
- 422: request body, query, filter, or review-input validation
- 500: sanitized internal persistence/unexpected failure
- 503: admin authentication is not configured

## `GET /health`

Public health check:

```json
{"status": "ok"}
```

## `GET /admin/drafts`

Supported query parameters:

- `status`: `pending`, `in_review`, `approved`, `rejected`, `superseded`, `failed`
- `kind`: `initial`, `update`
- `politician_id`: positive integer
- `source_key`: official source key
- `created_after`, `created_before`: ISO-8601 datetimes
- `offset`: non-negative integer, default 0
- `limit`: 1–100, default 50

Active drafts are ordered first, followed by terminal drafts; each group is ordered
by newest creation timestamp and then descending draft ID.

```json
{
  "items": [
    {
      "id": 12,
      "politician_id": 4,
      "politician_name": "Maria Rossi",
      "kind": "update",
      "status": "pending",
      "baseline_version_id": 3,
      "created_at": "2026-10-02T10:00:00Z",
      "updated_at": "2026-10-02T10:00:00Z",
      "evidence_count": 1,
      "change_count": 1,
      "supersedes_id": null,
      "final_review_decision": null
    }
  ],
  "total": 1,
  "offset": 0,
  "limit": 50
}
```

## `GET /admin/drafts/{draft_id}`

Returns draft and politician metadata, the complete proposed profile, typed diff,
field-level Evidence, source/RawDocument metadata, baseline and current versions,
supersession context, and the final Review. Raw bytes are never returned.

## `POST /admin/drafts/{draft_id}/start-review`

No request body. Delegates to `ReviewService.start_review` and creates no Review row.

```json
{
  "status": "in_review",
  "draft_id": 12,
  "politician_id": 4,
  "final_draft_status": "in_review"
}
```

## `POST /admin/drafts/{draft_id}/approve`

Optional body:

```json
{"note": "Official evidence verified"}
```

Delegates exclusively to `PublishService.approve`.

```json
{
  "status": "reviewed",
  "review_id": 8,
  "decision": "approved",
  "draft_id": 12,
  "politician_id": 4,
  "created_version_id": 7,
  "version_number": 2,
  "current_version_id": 7,
  "final_draft_status": "approved"
}
```

## `POST /admin/drafts/{draft_id}/reject`

Optional body:

```json
{"note": "Evidence requires clarification"}
```

Delegates exclusively to `ReviewService.reject`. `created_version_id` and
`version_number` are null; the current-version pointer is unchanged.
