"""Process-isolated steady-trial execution for formal LOAD_SEARCH production.

The scientific trial is identical to ``run_steady_trial_v1``.  Process
isolation prevents runtime allocator/cache history from one large lambda trial
from influencing the execution cost of the next trial; no scientific state is
carried across trials, matching the formal empty-state independence rule.
"""
from __future__ import annotations

import multiprocessing as mp
from typing import Any

from src.multi_topology.simulation import PathCatalog, SteadyTrialV1, run_steady_trial_v1


def _worker(connection: Any, payload: dict) -> None:
    try:
        node_count = int(payload["node_count"])
        catalog = PathCatalog.from_edges(
            node_count, payload.pop("edges"), payload.pop("k"),
            cache_capacity=payload.pop("cache_capacity"),
            workspace_capacity=payload.pop("workspace_capacity"),
        )
        result = run_steady_trial_v1(catalog=catalog, **payload)
        connection.send((True, result))
    except BaseException as exc:  # child must return diagnostic to parent
        connection.send((False, (type(exc).__name__, str(exc))))
    finally:
        connection.close()


def isolated_trial_runner(**kwargs) -> SteadyTrialV1:
    catalog: PathCatalog = kwargs.pop("catalog")
    payload = dict(kwargs)
    payload.update({
        "node_count": kwargs["node_count"],
        "edges": [tuple(sorted(edge)) for edge in catalog.graph.edges],
        "k": catalog.k,
        "cache_capacity": catalog.cache_capacity,
        "workspace_capacity": catalog.workspace_capacity,
    })
    # node_count remains in payload for run_steady_trial_v1.
    context = mp.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(child, payload))
    process.start()
    child.close()
    try:
        ok, value = parent.recv()
    finally:
        parent.close()
        process.join()
    if process.exitcode != 0 and ok:
        raise RuntimeError(f"isolated trial process exited with code {process.exitcode}")
    if not ok:
        error_type, message = value
        raise RuntimeError(f"isolated trial failed: {error_type}: {message}")
    return value
