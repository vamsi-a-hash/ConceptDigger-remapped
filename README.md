# ConceptDigger

A FastAPI service that digs DBpedia categories: it walks a category's subcategories and pages, collects their synonyms, and exposes the resulting graph.

Data comes from live SPARQL queries (default: `https://dbpedia.org/sparql`) and is cached in memory and on disk. The graph starts empty; each category is fetched once, then served from the cache.

## Run

**Docker** (builds the image and persists the cache to `./data`):

```bash
./start.sh
```

**Locally:**

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 5007
```

Check it is up: `curl http://localhost:5007/api/v1/health`
Interactive docs: `http://localhost:5007/docs`

## API

All routes are under `/api/v1`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/dig` | Hydrate a category tree and return its subcategories and pages with synonyms |
| `POST` | `/hydrate-category` | Fetch only the structure (children) of a category; no synonyms, returns counts |
| `POST` | `/hydrate-synonyms` | Fetch synonyms for one entity |
| `GET` | `/graph/data` | Cached nodes and edges as JSON (read-only, never calls SPARQL) |
| `GET` | `/graph` | Cached graph as an interactive HTML tree (read-only) |
| `GET` | `/ontology/analysis`, `/mapping-table`, `/skos`, `/owl` | Generate SKOS / OWL from the cached graph (read-only) |
| `GET` | `/health` | Status and cached node/edge counts |

### `POST /dig`

```json
{
  "categories": ["Category:Food_ingredients"],
  "max_depth": 1,
  "return_categories": true,
  "return_pages": true
}
```

Returns a list of `{entity_url, surface_text, seed_category, how_this_record}`. The seed category itself is not included, only what is below it.

If the SPARQL call budget runs out, the response still contains what was hydrated and carries the header `X-SPARQL-Budget-Exhausted: true`. Call again to continue; already-hydrated nodes are skipped.

### `GET /graph/data`

```
GET /api/v1/graph/data?root=Category:Food_ingredients&depth=2
```

Returns `{root, depth, nodes, edges}`. Each node has `id`, `type`, `synonyms`, `structure_hydrated` and `synonyms_hydrated`. If `root` is not cached, `nodes` is empty.

Depth note: `/dig` with `max_depth=d` reaches one level deeper than `/graph/data` with `depth=d`. Use `depth = max_depth + 1` to read back everything a dig covered.

## Configuration

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `SPARQL_ENDPOINT` | `https://dbpedia.org/sparql` | SPARQL endpoint to hydrate from |
| `CACHE_FILE_PATH` | `data/graph_cache.json` | Where the graph is persisted (mount as a volume) |
| `PORT` | `5007` | Server port |
| `MAX_DEPTH_HARD_CAP` | `6` | Upper limit on any requested depth |
| `MAX_SPARQL_CALLS_PER_REQUEST` | `10000` | SPARQL calls one request may spend |
| `SPARQL_MIN_INTERVAL_SECONDS` | `0.5` | Minimum gap between SPARQL calls |
| `SPARQL_TIMEOUT_SECONDS` | `15` | Timeout per SPARQL call |
| `SPARQL_MAX_RETRIES` | `3` | Retries on 429/503 |

## Project layout

```
app/
  main.py          app setup and router registration
  config.py        env-driven settings
  dig.py           dig traversal and output
  hydration.py     SPARQL hydration with call budget
  graph_store.py   in-memory graph with JSON persistence
  sparql_client.py rate-limited SPARQL client
  ontology.py      SKOS / OWL generation
  routers/         one file per endpoint group
```

## License

AGPL-3.0. See `LICENCE-AGPL-3.0.txt`.
