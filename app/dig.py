"""
Core traversal logic for /api/v1/dig and /api/v1/dig/fixed.

Both endpoints walk the same descendant tree from each seed category, up to
max_depth, collecting categories and/or pages per the return_categories /
return_pages flags — this mirrors the legacy enumerateChild()/prepareOutput()
pair exactly, including recursing into every category regardless of whether
categories are being *returned*, since a category might still contain pages
deeper down that should be returned.

The two endpoints differ only in output attribution:

  - /dig (legacy):  seed_category is set from the matched node's OWN name.
    This is the original bug (`graph.node[child]['name']` instead of the
    seed that was actually dug), preserved on purpose. Matches are deduped
    globally across the whole request batch, same as the original
    `set(enumeratedChildInList)`.

  - /dig/fixed:      seed_category is the seed that was actually dug for that
    branch. Because a node can legitimately be reachable from more than one
    seed in the same batch, dedup here is per (node, seed) pair rather than
    global.
"""
from typing import Dict, List, Set, Tuple

from .config import settings
from .graph_store import GraphStore
from .hydration import HydrationService, SparqlBudget

DigItem = Tuple[str, int, int, int]  # (seed_category, max_depth, return_categories, return_pages)


async def _enumerate_descendants(
    hydration: HydrationService,
    store: GraphStore,
    node: str,
    cur_depth: int,
    max_depth: int,
    return_categories: bool,
    return_pages: bool,
    budget: SparqlBudget,
    seed: str,
    collected: List[Tuple[str, str]],
) -> None:
    if not store.is_structure_hydrated(node):
        await hydration.hydrate_category_structure(node, budget)

    for child in store.children(node):
        is_category = child.startswith("Category:")
        if is_category:
            if return_categories:
                collected.append((child, seed))
            if cur_depth < max_depth:
                await _enumerate_descendants(
                    hydration, store, child, cur_depth + 1, max_depth,
                    return_categories, return_pages, budget, seed, collected,
                )
        else:
            if return_pages:
                collected.append((child, seed))


def _prepare_output_legacy(store: GraphStore, matched: Set[str]) -> List[Dict[str, str]]:
    output = []
    for uri in matched:
        for text, source in store.synonyms(uri):
            output.append({
                "entity_url": f"DBPedia>{uri}",
                "surface_text": text,
                # Bug preserved on purpose: this is the matched node's own
                # name, not the seed category that was actually dug.
                "seed_category": uri,
                "how_this_record": source,
            })
    return output


def _prepare_output_fixed(store: GraphStore, matched: Set[Tuple[str, str]]) -> List[Dict[str, str]]:
    output = []
    for uri, seed in matched:
        for text, source in store.synonyms(uri):
            output.append({
                "entity_url": f"DBPedia>{uri}",
                "surface_text": text,
                "seed_category": seed,
                "how_this_record": source,
            })
    return output


async def run_dig(
    hydration: HydrationService,
    store: GraphStore,
    items: List[DigItem],
    budget: SparqlBudget,
    fixed: bool,
) -> List[Dict[str, str]]:
    matched_legacy: Set[str] = set()
    matched_fixed: Set[Tuple[str, str]] = set()

    for seed_category, max_depth_raw, return_categories_raw, return_pages_raw in items:
        max_depth = min(int(max_depth_raw), settings.max_depth_hard_cap)
        return_categories = bool(int(return_categories_raw))
        return_pages = bool(int(return_pages_raw))

        if not store.is_structure_hydrated(seed_category):
            await hydration.hydrate_category_structure(seed_category, budget)
        if not store.has_node(seed_category):
            # Category doesn't exist even after a live hydration attempt
            # (unknown seed, or budget ran out before we could create it) —
            # skip it rather than crash the whole batch.
            continue

        collected: List[Tuple[str, str]] = []
        await _enumerate_descendants(
            hydration, store, seed_category, 0, max_depth,
            return_categories, return_pages, budget, seed_category, collected,
        )

        if fixed:
            matched_fixed.update(collected)
        else:
            matched_legacy.update(child for child, _seed in collected)

    all_uris = matched_legacy if not fixed else {child for child, _seed in matched_fixed}
    for uri in all_uris:
        if not store.is_synonyms_hydrated(uri):
            await hydration.hydrate_synonyms(uri, budget)

    if fixed:
        return _prepare_output_fixed(store, matched_fixed)
    return _prepare_output_legacy(store, matched_legacy)
