"""Response objects: dicts with attribute access, so new API fields appear without an SDK release."""

from __future__ import annotations

from typing import Any


class ScrawlObject(dict):
    """A JSON object from the API. ``result.markdown`` and ``result["markdown"]`` are the same value.

    An unknown attribute raises ``AttributeError`` (typos are not silently ``None``); use ``.get()`` for
    fields that may be absent. A field named like a dict method wins (``batch.items`` is the items).
    """

    __slots__ = ()

    def __getattribute__(self, name: str) -> Any:
        # An API field wins over a dict method of the same name (batch ``items``, ``keys``...); the
        # methods stay available as ``dict.items(obj)``.
        if not name.startswith("_") and dict.__contains__(self, name):
            return dict.__getitem__(self, name)
        return super().__getattribute__(name)

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"{type(self).__name__} has no field {name!r}") from None

    def __dir__(self) -> list[str]:
        return sorted({*super().__dir__(), *dict.keys(self)})

    def __reduce_ex__(self, protocol: Any) -> tuple[Any, ...]:
        # copy, deepcopy and pickle: the default reduction calls ``self.items()``, which is a field on a batch.
        # ``dict(self)`` copies without calling any method, so nested objects stay ScrawlObjects.
        return (type(self), (dict(self),))

    def to_dict(self) -> dict[str, Any]:
        """A plain ``dict`` copy, nested objects included.

        Use it before ``json.dumps``: the encoder calls ``obj.items()``, and on a result with an ``items``
        field (every batch) that is the field, not the dict method.
        """
        return unwrap(self)


def wrap(value: Any) -> Any:
    """Recursively turn JSON dicts into ``ScrawlObject`` (lists keep their items wrapped)."""
    if isinstance(value, dict):
        return ScrawlObject({key: wrap(item) for key, item in value.items()})
    if isinstance(value, list):
        return [wrap(item) for item in value]
    return value


def unwrap(value: Any) -> Any:
    """The inverse of ``wrap``: plain dicts and lists all the way down."""
    if isinstance(value, dict):
        return {key: unwrap(item) for key, item in dict.items(value)}
    if isinstance(value, list):
        return [unwrap(item) for item in value]
    return value
