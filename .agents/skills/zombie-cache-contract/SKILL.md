---
name: zombie-cache-contract
description: Maintain the versioned biodata-cache registry and table contracts read by Zombie's browser pages.
---

# Zombie cache contract

Zombie resolves a cache version, reads published registry fragments, and queries Parquet over HTTPS in browser DuckDB. The registry is the consumer's contract for table location, type, columns, and partitioning. Inspect the current table specification and generated fragment before changing a table; do not rely on a remembered inventory of consumer tables.

Preserve the core asset and provenance tables required to discover records. Other jobs publish independent fragments so an optional failure should not remove successful tables. Use backend-produced partition layouts and keep explicit partition URL readers consistent with them; browser readers cannot assume S3 prefix globbing works.

For a breaking schema, name, or partition change, identify Zombie consumers, coordinate their queries and the cache version, and verify that the published registry describes the actual objects. Use backend and registry fixtures for contract checks without relying on live S3.
