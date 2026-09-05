"""Zero-dependency structured-output contracts (v5 01 §L2).

The v5 backend deliberately avoids a third-party validation library so a
reviewer can clone the repo and run ``bun start`` / the test suite on a
stock CPython 3.11+ install (v5 04: Windows + WSL must work without a
model download or a wheel build).

The pieces here are small on purpose:

``Field``   declares one JSON field: type, bounds, enum membership, default.
``Schema``  binds an ordered set of ``Field`` s to a class and gives it
            ``parse`` / ``to_dict`` with *versioned* output.
``SchemaError`` carries a machine-readable ``code`` so the L2 repair path
            (v5 01: "schema invalid 可 repair 1 次") can tell a malformed
            envelope apart from a value that is merely out of range.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Sequence


class SchemaError(ValueError):
    """A payload did not satisfy a declared contract."""

    def __init__(self, path: str, code: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message}


_MISSING = object()


class Field:
    """One declared field of a structured contract."""

    __slots__ = (
        "kind",
        "default",
        "choices",
        "minimum",
        "maximum",
        "item",
        "max_items",
        "coerce",
    )

    def __init__(
        self,
        kind: type | tuple[type, ...],
        *,
        default: Any = _MISSING,
        choices: Sequence[Any] | None = None,
        minimum: float | None = None,
        maximum: float | None = None,
        item: type | None = None,
        max_items: int | None = None,
        coerce: Callable[[Any], Any] | None = None,
    ) -> None:
        self.kind = kind
        self.default = default
        self.choices = tuple(choices) if choices is not None else None
        self.minimum = minimum
        self.maximum = maximum
        self.item = item
        self.max_items = max_items
        self.coerce = coerce

    @property
    def required(self) -> bool:
        return self.default is _MISSING

    def default_value(self) -> Any:
        if self.default is _MISSING:
            raise KeyError("field has no default")
        if callable(self.default):
            return self.default()
        return self.default

    def validate(self, path: str, raw: Any) -> Any:
        value = self.coerce(raw) if self.coerce is not None else raw

        # bool is a subclass of int; never let True satisfy an int field.
        if self.kind is int and isinstance(value, bool):
            raise SchemaError(path, "type", "expected int, got bool")
        if self.kind is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if not isinstance(value, self.kind):
            want = getattr(self.kind, "__name__", str(self.kind))
            raise SchemaError(path, "type", f"expected {want}, got {type(value).__name__}")

        if self.choices is not None and value not in self.choices:
            allowed = ", ".join(repr(c) for c in self.choices)
            raise SchemaError(path, "choice", f"{value!r} not in [{allowed}]")

        if self.minimum is not None and value < self.minimum:
            raise SchemaError(path, "range", f"{value!r} < minimum {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise SchemaError(path, "range", f"{value!r} > maximum {self.maximum}")

        if isinstance(value, list):
            if self.max_items is not None and len(value) > self.max_items:
                raise SchemaError(path, "range", f"{len(value)} items > max {self.max_items}")
            if self.item is not None:
                for i, entry in enumerate(value):
                    if not isinstance(entry, self.item):
                        want = self.item.__name__
                        raise SchemaError(
                            f"{path}[{i}]", "type", f"expected {want}, got {type(entry).__name__}"
                        )
        return value


class Schema:
    """Base class for a versioned structured contract.

    Subclasses declare ``schema_version`` and ``fields``. Instances expose
    every declared field as a plain attribute, so downstream domain code
    reads like ordinary Python and never touches this module.
    """

    schema_version: str = "unversioned"
    fields: Mapping[str, Field] = {}
    #: nested contracts, ``attribute -> Schema subclass``
    nested: Mapping[str, type["Schema"]] = {}
    #: reject keys the contract does not declare (v5 02 audit needs exact shapes)
    extra_forbidden: bool = True

    def __init__(self, **values: Any) -> None:
        for name in self.fields:
            setattr(self, name, values[name])
        for name in self.nested:
            setattr(self, name, values[name])

    # -- construction ----------------------------------------------------

    @classmethod
    def parse(cls, payload: Any, path: str = "$") -> "Schema":
        if not isinstance(payload, Mapping):
            raise SchemaError(path, "type", f"expected object, got {type(payload).__name__}")

        values: dict[str, Any] = {}
        for name, field in cls.fields.items():
            child = f"{path}.{name}"
            if name in payload and payload[name] is not None:
                values[name] = field.validate(child, payload[name])
            elif field.required:
                raise SchemaError(child, "missing", "required field is absent")
            else:
                values[name] = field.default_value()

        for name, sub in cls.nested.items():
            child = f"{path}.{name}"
            if name in payload and payload[name] is not None:
                values[name] = sub.parse(payload[name], child)
            else:
                values[name] = sub.empty()

        if cls.extra_forbidden:
            declared = set(cls.fields) | set(cls.nested)
            unknown = sorted(k for k in payload if k not in declared)
            if unknown:
                raise SchemaError(path, "extra", f"undeclared keys: {', '.join(unknown)}")

        return cls(**values)

    @classmethod
    def empty(cls) -> "Schema":
        """Build an instance from defaults alone; raises if any field is required."""
        return cls.parse({})

    # -- serialisation ---------------------------------------------------

    def to_dict(self, *, with_version: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if with_version:
            out["schema_version"] = self.schema_version
        for name in self.fields:
            out[name] = getattr(self, name)
        for name in self.nested:
            out[name] = getattr(self, name).to_dict()
        return out

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        body = ", ".join(f"{k}={getattr(self, k)!r}" for k in self.fields)
        return f"{type(self).__name__}({body})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.to_dict() == other.to_dict()


def json_skeleton(schema: type[Schema]) -> str:
    """Render the contract as the example object we put in a model prompt.

    Models follow a concrete example far more reliably than prose, and this
    keeps the prompt from drifting away from the code when a field changes.
    """

    def render(cls: type[Schema], indent: int) -> Iterable[str]:
        pad = " " * indent
        entries: list[str] = []
        for name, field in cls.fields.items():
            entries.append(f'{pad}"{name}": {_hint(field)}')
        for name, sub in cls.nested.items():
            inner = "\n".join(render(sub, indent + 2))
            entries.append(f'{pad}"{name}": {{\n{inner}\n{pad}}}')
        return [",\n".join(entries)]

    return "{\n" + "\n".join(render(schema, 2)) + "\n}"


def _hint(field: Field) -> str:
    if field.choices is not None:
        return "|".join(str(c) for c in field.choices)
    if field.kind is bool:
        return "true|false"
    if field.kind is int:
        return "<int>"
    if field.kind is float:
        rng = ""
        if field.minimum is not None and field.maximum is not None:
            rng = f" {field.minimum}..{field.maximum}"
        return f"<float{rng}>"
    if field.kind is list:
        item = field.item.__name__ if field.item else "any"
        return f"[<{item}>, ...]"
    return "<string>"
