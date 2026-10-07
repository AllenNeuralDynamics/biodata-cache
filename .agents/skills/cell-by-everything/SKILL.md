---
name: cell-by-everything
description: Extend biodata-cache's per-cell identity, properties, and assay projections while preserving stable joins.
---

# Cell-by-everything

The per-cell cache separates narrow identity and provenance, sparse measurements, and wider assay data. Current tables and source mappings live under src/biodata_cache/cache_table_helpers/cell_by_everything/; table_specs.py defines their published contract. Read those sources before extending the table set or physical layout. The shared cell_key identifies a cell within an asset and joins the per-cell tables. Its construction is defined in keys.py and must remain stable for existing sources; never derive identity from row order or mutable display labels.

## Extend a source or property

- Inspect a representative source partition, including column types, nulls, and identifier quality. A scheduled projection must not silently depend on a manual or one-off cache table that can go stale. Use a scheduled upstream job or an independent reader with explicit freshness and failure behavior.
- Add source mapping through the current CellSource model in sources.py. Choose stable container and cell-reference fields because they feed identity. Map source-specific measurements to shared property names; missing measurements remain null.
- Keep identity fields narrow. Sparse scalar measurements belong in the properties table; high-dimensional panels or matrices need a separate table with an explicit join key and suitable partitioning. Decide by data grain and access pattern, not a fixed column-count threshold.
- Check sync.py dependencies when a source job is added, and update table specs and PIPELINE.md when the published or scheduled contract changes.
- Ordinary builds can skip existing asset partitions. A schema, mapping, or identity change needs the builder's deliberate rewrite or backfill path; inspect current rebuild behavior before running a sync.

For annotations computed against a different processing of the same acquisition, match through a validated acquisition/session identity rather than assuming asset names match. Keep cell_key asset-scoped; consult keys.py and genes.py for current cross-processing joins. Validate key stability, duplicate handling, populated properties, nulls, and the intended rewrite behavior with representative source data.
