"""Janelia MouseLight neuron list cache table.

MouseLight (https://ml-neuronbrowser.janelia.org) publishes ~1.6K single
projection neurons reconstructed and registered to the Allen CCF. Their GraphQL
``searchNeurons`` endpoint is slow to query from the browser (several seconds),
so we cache the full neuron list here — one row per neuron with its label, soma
region acronym, and the tracing UUIDs needed to later fetch each skeleton — for
fast loading on the ExaSPIM morphology page.

Unlike most cache tables, the source is an external GraphQL API rather than the
AIND document DB, so this helper talks to Janelia directly over HTTP.
"""

import json
import logging
import urllib.request

import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging

ML_GRAPHQL_URL = "https://ml-neuronbrowser.janelia.org/graphql"

# SearchScope.Public — the scope value for published neurons.
ML_SCOPE = 6
# MouseLight UUID for the CCF root region (structureId 997, "wholebrain").
ML_ROOT_BRAIN_AREA = "464cb1ee-4664-40dc-948f-85dd1feb3e40"

SEARCH_NEURONS_QUERY = """query SearchNeurons($context: SearchContext) {
  searchNeurons(context: $context) {
    totalCount
    neurons {
      id
      idString
      brainArea { acronym }
      tracings {
        id
        tracingStructure { name value }
      }
    }
    error { name message }
  }
}"""


def _build_search_context() -> dict:
    """Build a SearchContext that returns every public neuron.

    The documented "invert all" ID predicate returns a count but an empty neuron
    list, so we scope an ANATOMICAL predicate to the whole-brain root region
    instead, which reliably returns the full set with tracing UUIDs.
    """
    return {
        "scope": ML_SCOPE,
        "nonce": "biodata-cache",
        "ccfVersion": "CCFV30",
        "predicates": [
            {
                "predicateType": "ANATOMICAL",
                "tracingIdsOrDOIs": [],
                "tracingIdsOrDOIsExactMatch": False,
                "tracingStructureIds": [],
                "nodeStructureIds": [],
                "operatorId": None,
                "amount": 0,
                "brainAreaIds": [ML_ROOT_BRAIN_AREA],
                "arbCenter": {"x": None, "y": None, "z": None},
                "arbSize": None,
                "invert": False,
                "composition": 1,
            }
        ],
    }


def _fetch_mouselight_neurons() -> list[dict]:
    """Fetch the full MouseLight neuron list from the Janelia GraphQL API.

    Returns a list of row dicts with ``id``, ``id_string``, ``region`` and a
    JSON-encoded ``tracings`` field (``[{"id", "kind"}, ...]``).
    """
    payload = json.dumps(
        {"query": SEARCH_NEURONS_QUERY, "variables": {"context": _build_search_context()}}
    ).encode()
    req = urllib.request.Request(
        ML_GRAPHQL_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 (trusted Janelia host)
        body = json.loads(resp.read().decode())

    if body.get("errors"):
        raise ValueError(body["errors"][0].get("message", "GraphQL error"))
    result = body.get("data", {}).get("searchNeurons") or {}
    if result.get("error"):
        raise ValueError(result["error"].get("message", "MouseLight search error"))

    rows = []
    for n in result.get("neurons", []) or []:
        tracings = [
            {"id": t.get("id"), "kind": (t.get("tracingStructure") or {}).get("name", "")}
            for t in (n.get("tracings") or [])
        ]
        rows.append(
            {
                "id": n.get("id"),
                "id_string": n.get("idString") or "",
                "region": (n.get("brainArea") or {}).get("acronym") or "",
                "tracings": json.dumps(tracings),
            }
        )
    rows.sort(key=lambda r: r["id_string"])
    return rows


@registry.register_table(registry.NAMES["mouselight"])
def platform_mouselight(force_update: bool = False) -> pd.DataFrame:
    """Fetch/cache the Janelia MouseLight neuron list.

    Returns cached results if available, fetches from the MouseLight GraphQL API
    if the cache is empty or ``force_update`` is True.

    Args:
        force_update: If True, bypass cache and fetch fresh data from Janelia.

    Returns:
        DataFrame with one row per MouseLight neuron.
    """
    df = registry.BACKEND.read(registry.NAMES["mouselight"])

    if df.empty and not force_update:
        raise ValueError("Cache is empty. Use force_update=True to fetch data from database.")

    if df.empty or force_update:
        setup_logging()
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["mouselight"],
                message="Updating cache",
            ).to_json()
        )
        rows = _fetch_mouselight_neurons()
        df = pd.DataFrame(rows, columns=["id", "id_string", "region", "tracings"])
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["mouselight"],
                message=f"Fetched {len(df)} MouseLight neurons",
            ).to_json()
        )
        registry.BACKEND.write(registry.NAMES["mouselight"], df)

    return df


def platform_mouselight_columns() -> list[Column]:
    """Return MouseLight cache table column definitions."""
    return [
        Column(name="id", description="MouseLight neuron UUID"),
        Column(name="id_string", description="MouseLight neuron label (e.g. 'AA0001')"),
        Column(name="region", description="Soma brain area acronym in the Allen CCF"),
        Column(
            name="tracings",
            description="JSON array of the neuron's tracings as [{id, kind}], where kind is e.g. 'axon'/'dendrite'",
        ),
    ]
