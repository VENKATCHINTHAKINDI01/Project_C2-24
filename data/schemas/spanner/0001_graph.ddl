-- C2-24 knowledge graph on Spanner Graph (plan §3.6, §5.2; ADR-0048). The same store-agnostic shape
-- as Cloud SQL (data/schemas/postgres/0002_graph.sql): nodes are documents with their access tags,
-- edges are relations. No document text: IDs, access tags, dates and the subject line only.
-- Applied once when the database is created (26_spanner_graph.sh); statements end with ';'.

CREATE TABLE graph_nodes (
  canonical_id     STRING(200) NOT NULL,
  department       STRING(64) NOT NULL,
  section          STRING(64),
  classification   STRING(64) NOT NULL,
  file_no          STRING(128),
  doc_id           STRING(200) NOT NULL,
  doc_type         STRING(64),
  hierarchy_level  INT64,
  issue_date       DATE,
  effective_from   DATE,
  valid_until      DATE,
  subject          STRING(MAX),
) PRIMARY KEY (canonical_id);

CREATE TABLE graph_edges (
  source     STRING(200) NOT NULL,
  kind       STRING(32) NOT NULL,
  target     STRING(200) NOT NULL,
  confirmed  BOOL NOT NULL,
  CONSTRAINT fk_edge_source FOREIGN KEY (source) REFERENCES graph_nodes (canonical_id),
  CONSTRAINT fk_edge_target FOREIGN KEY (target) REFERENCES graph_nodes (canonical_id),
) PRIMARY KEY (source, kind, target);

CREATE INDEX graph_edges_by_target ON graph_edges (target, kind, source) STORING (confirmed);

-- The property graph over the same two tables: for GQL exploration in the console and later
-- queries. The application's walk stays hop by hop in fixed SQL templates, with the officer's
-- scope applied to every node in the application (ADR-0023): the access rule exists once.
CREATE PROPERTY GRAPH c2_graph
  NODE TABLES (graph_nodes KEY (canonical_id) LABEL Document)
  EDGE TABLES (
    graph_edges KEY (source, kind, target)
      SOURCE KEY (source) REFERENCES graph_nodes (canonical_id)
      DESTINATION KEY (target) REFERENCES graph_nodes (canonical_id)
      LABEL Relation
  );
