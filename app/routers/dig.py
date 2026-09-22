"""
POST /api/v1/dig — digs one or more DBpedia categories to a shared max_depth,
collecting subcategories and/or member articles per category, using the
corrected seed_category attribution (this used to be the separate
`/dig/fixed` endpoint; the legacy buggy `/dig` has been retired — there is
now only one dig endpoint and it's always correct).

Request body:
{
  "categories": ["Category:Birds", "Category:Fish"],
  "max_depth": 2,
  "return_categories": true,
  "return_pages": true
}

max_depth / return_categories / return_pages apply to every category in the
batch (this is a change from the old per-item-tuple protocol, where each
category could carry its own depth/flags). max_depth is still clamped to
MAX_DEPTH_HARD_CAP regardless of what's requested.

Response body: a JSON array of
{entity_url, surface_text, seed_category, how_this_record} objects.

If the per-request SPARQL call budget (MAX_SPARQL_CALLS_PER_REQUEST) is
exhausted before every branch could be fully explored/enriched, the response
still contains whatever was hydrated (this call or previously cached) and an
`X-SPARQL-Budget-Exhausted: true` header is set — the body stays a plain
JSON array either way.
"""
from typing import List

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from ..config import settings
from ..dig import run_dig
from ..hydration import SparqlBudget

router = APIRouter(prefix="/api/v1", tags=["dig"])


class DigRequest(BaseModel):
    categories: List[str] = Field(..., min_length=1, description="DBpedia category local names to dig.")
    max_depth: int = Field(1, ge=0, description="How many levels deep to traverse. Clamped to MAX_DEPTH_HARD_CAP.")
    return_categories: bool = Field(True, description="Include matched subcategories in the output.")
    return_pages: bool = Field(True, description="Include matched member articles in the output.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "categories": ["Category:Food_ingredients"],
                "max_depth": 2,
                "return_categories": True,
                "return_pages": True,
            }
        }
    }


@router.post("/dig")
async def dig(body: DigRequest, request: Request, response: Response):
    store = request.app.state.store
    hydration = request.app.state.hydration
    budget = SparqlBudget(settings.max_sparql_calls_per_request)

    items = [
        (category, body.max_depth, int(body.return_categories), int(body.return_pages))
        for category in body.categories
    ]

    result = await run_dig(hydration, store, items, budget, fixed=True)
    if budget.exhausted:
        response.headers["X-SPARQL-Budget-Exhausted"] = "true"
    return result