# MVP ingestion data model

This first slice persists the official source and every collected response. It does
not yet define candidate profiles, matching, drafts, evidence, reviews, or published
politician versions.

## Source

`Source` identifies one configured official provider.

- `id`: internal primary key
- `key`: stable application key (`senato-repubblica`)
- `name`: human-readable institution name
- `base_url`: official provider URL
- `is_enabled`: whether collection is enabled
- `created_at`: creation timestamp

One Source has many RawDocuments.

## RawDocument

`RawDocument` records one collection attempt. Duplicate responses still receive
separate database records for auditability, while their raw bytes share the same
content-addressed storage object.

- source and retrieval metadata
- raw storage key and raw SHA-256
- canonical normalized SHA-256 after successful parsing
- structured parser records
- normalized human-readable text
- `collected`, `parsed`, or `failed` process status
- change-detection result
- collector and parser versions
- parser error text when parsing fails

The raw SHA-256 identifies exact response bytes. Semantic change detection compares
the normalized SHA-256, which is computed from canonical JSON with normalized strings,
stable record order, stable key order, and explicit JSON null values.
