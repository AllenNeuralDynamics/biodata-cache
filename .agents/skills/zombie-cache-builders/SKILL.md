---
name: zombie-cache-builders
description: Build biodata-cache tables and wire their schemas, registration, and sync jobs for Zombie consumers.
---

# Zombie cache builders

A published table needs a builder, a table specification, registration imports, and an owning sync job that builds the data and publishes its registry fragment. Follow the current patterns in cache_table_helpers/, table_specs.py, and sync.py; a registered table alone is not necessarily a scheduled output.

Respect dependencies between jobs, especially the core asset inventory on which downstream builders rely. Jobs publish their own fragments so one failed or delayed job does not erase unrelated tables. Use backend helpers for partition paths and writes rather than inventing S3 layouts. Check existing incremental or overwrite behavior before changing a builder.

When a schema or partition key changes, update column metadata and registry output with the data, then inspect Zombie consumers that query it. Validate representative rows, partition paths, and registry fragments with the repository's fake or memory backends.
