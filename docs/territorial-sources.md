# Territorial source research

Research date: 6 October 2026.

## Territorial reference data: ISTAT

VeraPolitica uses ISTAT's official *Codici delle unità amministrative* workbook:

- catalogue: <https://www.istat.it/classificazione/codici-dei-comuni-delle-province-e-delle-regioni/>
- stable workbook URL: <https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx>
- historical changes: <https://situas.istat.it/web/#/home>

The catalogue was updated on 26 February 2026 and describes the territorial
state through 21 February 2026: 20 regions and 7,894 current municipalities
after the Castegnero-Nanto merger. ISTAT states that the workbook URL remains
stable across releases.

The XLSX contains the six-character ISTAT municipality code, two-character
region code, official names, UTS/province metadata, cadastral code, NUTS data,
and multilingual names. VeraPolitica treats the ISTAT codes as opaque canonical
identities. Names are mutable labels, not identifiers. Province/UTS fields are
preserved as metadata; they do not create a Province domain.

ISTAT's SITUAS service covers changes from 1861, including creations,
suppressions, mergers, and renames. This milestone does not import that full
lineage. An inactive municipality can remain stored with validity dates, and a
rename updates the row identified by the same ISTAT code.

ISTAT data reuse is generally governed by CC BY 4.0. Operators remain
responsible for checking the notice attached to a downloaded release.

## Current office holders: DAIT mayors

The selected office-holder source is the Ministry of the Interior, Department
for Internal and Territorial Affairs (DAIT):

- publication page: <https://dait.interno.gov.it/elezioni/open-data/amministratori-locali-e-regionali-in-carica>
- current mayors CSV: <https://dait.interno.gov.it/documenti/sindaciincarica.csv>
- administrative registry: <https://dait.interno.gov.it/elezioni/anagrafe-amministratori>
- annual archive: <https://dait.interno.gov.it/elezioni/open-data>

The inspected current publication is dated 24 August 2026. It is a
semicolon-delimited CSV with title/update lines followed by a header. It
contains DAIT region, province, and municipality codes and names; province
abbreviation; person name, sex, birth date/place; office; election and
entry dates; list; education; and profession. Prefetture/UTG validate changes
submitted by municipalities after elections.

The current feed does not document its municipality code as the ISTAT code and
does not provide a stable person identifier. Its record count is lower than
the ISTAT municipality count and municipalities under commissioners or
otherwise absent must not be interpreted as having no administration.
Dataset-specific reuse terms were not explicit on the publication page at the
time of research; this remains an operational licensing risk to verify before
redistribution.

Regional presidents were not selected: the national current-region feed has
coverage gaps, while regional institutional sites have fragmented contracts.
This milestone implements the `regional_president` office type for future data
but imports only mayors.

## Conservative linkage policy

ISTAT ingestion must run before DAIT office ingestion.

- A Region is identified only by its ISTAT region code.
- A Municipality is identified only by its six-character ISTAT code.
- A DAIT territory is linked only when normalized municipality name, province
  abbreviation, and region code select exactly one ISTAT municipality.
- Ambiguous or missing territory matches remain unresolved; fuzzy matching is
  forbidden.
- A person is linked by an exact existing source identifier or by the existing
  deterministic normalized-name plus exact-birth-date rule.
- Name-only person linkage and automatic person creation are forbidden.
- DAIT has no stable person ID, so the importer derives a deterministic source
  record identifier for replay and human-review case identity. It is not
  represented as a national identity number.
- Incomplete or ambiguous people go through the existing
  `IdentityResolutionCase` workflow. Complete unknown people remain unresolved
  until explicitly bootstrapped or reviewed.

DAIT coverage and linkage counts are reported on every run. They are never
presented as a complete census of Italian mayors.
