# File contracts

All stages use StageRequestV1 and immutable .nwstage ZIP files. WPuploader reads only
completed .nwdraft bundles. Schema, canonical JSON, path checks, checksums and fixed
ZIP timestamps are implemented in nw_generation/protocol.py and independently bundled
in WPuploader. No shared package installation or database is required.

FETCH_MISSING_SOURCES defaults to false. Request parameters cannot override a disabled
execution policy. FetchPlan purpose must be scheduled, explicit, or missing_sources.

Schemas: stage-request-v1.schema.json, stage-result-v1.schema.json and
 draft-bundle-v1.schema.json. The runtime also checks role/contract type, ZIP limits,
canonical manifest/file hashes, UUID identities and draft eligibility.
Result outputs use local absolute paths; copy the artifact and supply its unchanged
hash with a request-relative path when transferring it to another machine.
