"""
POST /api/v1/hydrate-category  — replaces legacy `insert-nodes`. Pre-warms
    the cache for one category (and optionally several levels of its
    subcategories) directly, without needing a /dig call to trigger it.

POST /api/v1/hydrate-synonyms  — replaces legacy `assign-synonym-from-*`.
    Pre-warms label/alt-name/redirect/disambiguation synonyms for one
    entity (category or page).

Both are budgeted the same way /dig is, so a broad pre-warm can't fan out
into an unbounded live-SPARQL crawl either.
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..config import settings
from ..hydration import SparqlBudget

router = APIRouter(prefix="/api/v1", tags=["hydrate"])


class HydrateCategoryRequest(BaseModel):
    category: str
    depth: int = 1  # how many levels of subcategories to pre-warm


class HydrateSynonymsRequest(BaseModel):
    entity: str


@router.post("/hydrate-category")
async def hydrate_category(body: HydrateCategoryRequest, request: Request):
    store = request.app.state.store
    hydration = request.app.state.hydration
    depth = min(body.depth, settings.max_depth_hard_cap)
    budget = SparqlBudget(settings.max_sparql_calls_per_request)

    frontier = [body.category]
    total_new_nodes = 0
    total_new_edges = 0

    for _level in range(max(depth, 1)):
        next_frontier = []
        for category in frontier:
            new_nodes, new_edges = await hydration.hydrate_category_structure(category, budget)
            total_new_nodes += new_nodes
            total_new_edges += new_edges
            if not budget.has_room():
                break
            next_frontier.extend(c for c in store.children(category) if c.startswith("Category:"))
        frontier = next_frontier
        if not budget.has_room() or not frontier:
            break

    return {
        "category": body.category,
        "new_nodes": total_new_nodes,
        "new_edges": total_new_edges,
        "sparql_calls_used": budget.used,
        "budget_exhausted": budget.exhausted,
    }


@router.post("/hydrate-synonyms")
async def hydrate_synonyms(body: HydrateSynonymsRequest, request: Request):
    hydration = request.app.state.hydration
    budget = SparqlBudget(settings.max_sparql_calls_per_request)
    added = await hydration.hydrate_synonyms(body.entity, budget)
    return {
        "entity": body.entity,
        "synonyms_added": added,
        "sparql_calls_used": budget.used,
        "budget_exhausted": budget.exhausted,
    }
