# MVP ingestion data model

The implemented slices persist the official source and every collected response,
then map changed Senato records to transient CandidateProfiles. They do not yet
define matching, drafts, Evidence records, reviews, or published politician versions.

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

## CandidateProfile

`CandidateProfile` is a source-independent Pydantic object. It is returned only when
a RawDocument's normalized data changed and is never persisted.

It separates:

- identity-like matching inputs: name, birth data, and generic source identifiers;
- versioned profile data: gender, profession, URLs, and political mandates;
- provenance: the RawDocument snapshot plus a deterministic source mapping for each
  populated candidate field.

Senato-specific record keys, RDF terms, person URIs, and mandate URIs remain in the
Senato mapper, generic source identifiers, or provenance. They are not domain field
names. Field provenance retains the parsed source value and source binding name so a
later slice can create Evidence records backed by the persisted RawDocument.
