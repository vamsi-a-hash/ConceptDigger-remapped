
"""
HydrationService is the only thing allowed to call out to SPARQL and write
new nodes/edges/synonyms into the GraphStore. Two safety mechanisms live
here:

  - SparqlBudget: a small mutable counter shared across every seed in one
    HTTP request. Every live SPARQL call spends 1 unit; once exhausted,
    hydration calls become no-ops and traversal/enrichment just stops
    expanding further (falling back to whatever's already cached).

  - De-duped hydration (via GraphStore.run_deduped): if two requests arrive
    at the same moment both wanting to hydrate "Category:Birds", only one
    actually fires the SPARQL calls; the other awaits that same result.
"""
from typing import List, Tuple

import httpx

from .graph_store import GraphStore
from .sparql_client import SparqlClient
from .utils import convert_entity_uri_to_label

SOURCE_LABEL = "rdfs:label"
SOURCE_ALT_NAME = "alt_name"
SOURCE_DISAMBIGUATION = "disambiguation"
SOURCE_REDIRECT = "redirect"


class SparqlBudget:
    """Shared, mutable per-request budget for live SPARQL calls."""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def has_room(self) -> bool:
        return self.used < self.limit

    def spend(self, n: int = 1) -> None:
        self.used += n

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit


class HydrationService:
    def __init__(self, store: GraphStore, sparql_client: SparqlClient, http_client: httpx.AsyncClient):
        self.store = store
        self.sparql_client = sparql_client
        self.http_client = http_client

    # ------------------------------------------------------------------
    # structure: skos:broader (subcategories) + dct:subject (member articles)
    # ------------------------------------------------------------------
    async def hydrate_category_structure(self, local_name: str, budget: SparqlBudget) -> Tuple[int, int]:
        key = f"structure:{local_name}"
        return await self.store.run_deduped(key, self._do_hydrate_category, local_name, budget)

    async def _do_hydrate_category(self, local_name: str, budget: SparqlBudget) -> Tuple[int, int]:
        if self.store.is_structure_hydrated(local_name):
            return (0, 0)
        if not budget.has_room():
            return (0, 0)

        subcats = await self.sparql_client.fetch_subcategories(self.http_client, local_name)
        budget.spend(1)

        articles: List[str] = []
        if budget.has_room():
            articles = await self.sparql_client.fetch_member_articles(self.http_client, local_name)
            budget.spend(1)

        async with self.store.write_lock():
            new_nodes = 0
            new_edges = 0
            if self.store.ensure_node(local_name, SOURCE_LABEL):
                new_nodes += 1
            for child in subcats:
                if self.store.ensure_node(child, SOURCE_LABEL):
                    new_nodes += 1
                if self.store.ensure_edge(local_name, child):
                    new_edges += 1
            for article in articles:
                if self.store.ensure_node(article, SOURCE_LABEL):
                    new_nodes += 1
                if self.store.ensure_edge(local_name, article):
                    new_edges += 1
            self.store.mark_structure_hydrated(local_name)
            await self.store.persist()

        return (new_nodes, new_edges)

    # ------------------------------------------------------------------
    # synonyms: rdfs:label, alt names, redirects, disambiguations
    # ------------------------------------------------------------------
    async def hydrate_synonyms(self, local_name: str, budget: SparqlBudget) -> int:
        key = f"synonyms:{local_name}"
        return await self.store.run_deduped(key, self._do_hydrate_synonyms, local_name, budget)

    async def _do_hydrate_synonyms(self, local_name: str, budget: SparqlBudget) -> int:
        if self.store.is_synonyms_hydrated(local_name):
            return 0
        if not budget.has_room():
            return 0

        collected: List[Tuple[str, str]] = []

        if budget.has_room():
            labels = await self.sparql_client.fetch_labels(self.http_client, local_name)
            budget.spend(1)
            collected += [(label.lower(), SOURCE_LABEL) for label in labels]

        if budget.has_room():
            alt_names = await self.sparql_client.fetch_alt_names(self.http_client, local_name)
            budget.spend(1)
            collected += [(name.lower(), SOURCE_ALT_NAME) for name in alt_names]

        if budget.has_room():
            redirect_sources = await self.sparql_client.fetch_redirect_sources(self.http_client, local_name)
            budget.spend(1)
            collected += [(convert_entity_uri_to_label(s), SOURCE_REDIRECT) for s in redirect_sources]

        if budget.has_room():
            disambig_sources = await self.sparql_client.fetch_disambiguation_sources(self.http_client, local_name)
            budget.spend(1)
            collected += [(convert_entity_uri_to_label(s), SOURCE_DISAMBIGUATION) for s in disambig_sources]

        async with self.store.write_lock():
            self.store.ensure_node(local_name, SOURCE_LABEL)
            added = self.store.add_synonyms(local_name, collected)
            self.store.mark_synonyms_hydrated(local_name)
            await self.store.persist()

        return added
