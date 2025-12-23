# Generalization Design (Config-First)

Goal: Turn the CRE dashboard into a reusable relationship network builder driven by config. The default enricher is LinkedIn, but the architecture should allow other enrichers later.

## Principles

- Config-first: behavior and visuals are controlled by a single config file.
- Node/type first: all entities are modeled as nodes with explicit types.
- Extensible enrichers: LinkedIn is default; others can be added without changing core graph logic.
- Exemplar analytics: built-in visualizations demonstrate the value of the dataset.

## Core Data Model

Nodes:
- id: stable unique identifier (string).
- type: node type (Company, Person, Market, Group, University, etc.).
- label: display label.
- attributes: arbitrary key/value metadata.

Edges:
- id: stable unique identifier (string).
- type: edge type (belongs_to, employed_by, member_of, operates_in, etc.).
- from: source node id.
- to: target node id.
- attributes: optional metadata.

## Config Structure (Conceptual)

config/network.yml defines:
- domain: name and description.
- node_types: list of allowed node types and display metadata.
- edge_types: list of allowed edge types and display metadata.
- dimensions: which node/edge types power analytics and visual grouping.
- enrichers: LinkedIn default, others optional.
- visuals: default visual modules and their data sources.

## Config Schema (Draft)

```yaml
domain:
  name: string
  description: string

node_types:
  <TypeName>:
    color: "#RRGGBB"
    icon: string
    label_key: string   # optional, defaults to "label"

edge_types:
  <EdgeName>:
    from: <TypeName>
    to: <TypeName>
    directed: boolean   # optional, defaults true

dimensions:
  primary: [<TypeName>, ...]
  secondary: [<TypeName>, ...]

enrichers:
  default: string
  <EnricherName>:
    enabled: boolean
    ... enricher-specific config

visuals:
  - id: string
    title: string
    description: string
    inputs: [<TypeName>, <EdgeName>, ...]
```

Validation rules:
- All node types referenced by edges and dimensions must exist in node_types.
- All edge_types must define from/to node types.
- `enrichers.default` must exist in `enrichers`.
- `visuals.inputs` should reference known node or edge types.

## Pipeline Flow (Generic)

1) Load config and seed nodes (e.g., companies).
2) Crawl public sources defined in config.
3) Normalize and merge nodes/edges (resolver assigns stable ids).
4) Enrich via LinkedIn loop (default).
5) Export graph + derived datasets for visuals.
6) Render exemplar analytics from config dimensions.

## UI Requirements

- Always show node type (badges/colors/legend).
- Expandable network view based on node types.
- Filters by type and by configured dimensions.
- Exemplar visual modules should load from derived datasets and be easy to swap.

## LinkedIn Loop (Default Enricher)

For each Company:
- Find related People.
- Enrich People data.
- Discover related Companies from work history.
- Repeat per policy (max depth, max new companies).

## Extensibility

- Add new enrichers by implementing Node/Edge output.
- Add new visuals by reading graph + dimension outputs.
- Add new dimensions via config without UI rewrite.

## Roadmap

1) Define config-first schema for nodes, edges, and dimensions.
2) Add a graph export (`graph.json`) from the existing pipeline.
3) Refactor LinkedIn enrichment into a modular enricher interface.
4) Update the dashboard to render from config + graph outputs.
5) Create a synthetic dataset with strong clustering to showcase the network builder.
