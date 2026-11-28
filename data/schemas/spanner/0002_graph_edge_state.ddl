-- C2-24 Spanner Graph edge learning state (ADR-0074 step 3; plan §3.6, §8).
-- Applied via: gcloud spanner databases ddl update c2graph --instance=c2-spanner --ddl-file=data/schemas/spanner/0002_graph_edge_state.ddl

ALTER TABLE graph_edges ADD COLUMN state STRING(32);
ALTER TABLE graph_edges ADD COLUMN score INT64;
ALTER TABLE graph_edges ADD COLUMN evidence STRING(MAX);
