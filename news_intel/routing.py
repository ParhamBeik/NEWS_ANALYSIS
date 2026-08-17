"""Per-node provider routing.

One model for the whole pipeline is a false economy. `classify` makes a four-way choice
that a small local model can usually make correctly; `evaluate` produces the three
ordinal scores that decide whether a human gets woken up, and is where being wrong is
expensive. They do not need to be the same model.

This file is what makes "swap GapGPT for a local model" a config edit rather than a code
change, and it makes the swap *partial* - which is how a migration to local inference
realistically happens. Move `summarize` to Ollama, measure it on the review set, then
move `classify`, and leave `evaluate` hosted until the numbers say otherwise.

Two properties matter more than they look:

- Providers are shared by (provider, model), never rebuilt per node. The request cap and
  the HTTP session live on the instance, so three instances of the same provider would
  silently triple the cap that is supposed to stop a runaway loop.
- Every inference row already carries its own `provider` and `model` columns, so a run
  that used two different models stays legible afterwards. Routing does not blur the
  record of what produced what.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

import yaml

from .core import config
from .providers import Provider, make_provider

# The nodes that issue provider calls. Anything not listed here is not routable.
NODES = ("classify", "evaluate", "summarize")


@dataclass(frozen=True)
class Route:
    node: str
    provider: str
    # None means "whatever that provider's configured default model is", which keeps
    # routing.yaml from having to be re-edited every time a model name changes in .env.
    model: str | None = None


def _coerce(node: str, value: object, fallback: Route | None) -> Route:
    """Accept either `classify: ollama` or a `{provider:, model:}` mapping."""
    if isinstance(value, str):
        return Route(node, value, None)
    if isinstance(value, Mapping):
        name = value.get("provider") or (fallback.provider if fallback else None)
        if not name:
            raise config.ConfigError(
                f"routing: node {node!r} has no provider and no default to fall back on"
            )
        model = value.get("model")
        return Route(node, str(name), str(model) if model else None)
    raise config.ConfigError(
        f"routing: node {node!r} must be a provider name or a mapping, got {type(value).__name__}"
    )


def load(path: Path | None = None, *, override: str | None = None) -> dict[str, Route]:
    """Resolve every node to a route.

    `override` is the `--provider X` case: an explicit choice on the command line beats
    the file for every node, so a one-off run against a single provider stays a one-liner
    and does not require editing config.
    """
    if override:
        return {node: Route(node, override, None) for node in NODES}

    path = path or config.ROUTING_PATH
    if not path.exists():
        raise config.ConfigError(
            f"missing routing config: {path}. Pass --provider to choose one explicitly."
        )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise config.ConfigError(f"routing: {path} is not valid YAML: {exc}") from exc
    if not isinstance(document, Mapping):
        raise config.ConfigError(f"routing: {path} must contain a mapping")

    raw_default = document.get("default")
    default = _coerce("default", raw_default, None) if raw_default is not None else None
    nodes = document.get("nodes") or {}
    if not isinstance(nodes, Mapping):
        raise config.ConfigError("routing: `nodes` must be a mapping of node -> provider")

    unknown = set(nodes) - set(NODES)
    if unknown:
        # A typo here would otherwise route nothing and look like the file was ignored.
        raise config.ConfigError(
            f"routing: unknown node(s) {sorted(unknown)}; known nodes are {list(NODES)}"
        )

    routes: dict[str, Route] = {}
    for node in NODES:
        if node in nodes:
            routes[node] = _coerce(node, nodes[node], default)
        elif default is not None:
            routes[node] = Route(node, default.provider, default.model)
        else:
            raise config.ConfigError(
                f"routing: node {node!r} is unrouted and no `default` is set in {path}"
            )
    return routes


def build(
    routes: Mapping[str, Route],
    *,
    factory: Callable[..., Provider] = make_provider,
) -> dict[str, Provider]:
    """Instantiate one provider per distinct (provider, model), shared across nodes."""
    shared: dict[tuple[str, str | None], Provider] = {}
    resolved: dict[str, Provider] = {}
    for node, route in routes.items():
        key = (route.provider, route.model)
        if key not in shared:
            shared[key] = factory(route.provider, model=route.model)
        resolved[node] = shared[key]
    return resolved


def describe(providers: Mapping[str, Provider]) -> dict[str, str]:
    """Compact `node -> provider:model` map, for run logs and the dashboard."""
    return {node: f"{p.name}:{p.model}" for node, p in providers.items()}
