"""Pemetaan anotasi Python -> JSON Schema untuk definisi tool.

Dulu logika ini diduplikasi di dua tempat (``alfa/tools/registry.py`` dan
``alfa/core/brain/tool_schema.py``) sehingga bisa berbeda hasil. Modul ini
menjadi satu-satunya sumber kebenaran.

Bonus penting: modul yang memakai ``from __future__ import annotations``
menyimpan anotasi sebagai *string*. Tanpa resolusi, semua parameter tool
terbaca ``"string"`` — model lalu mengirim angka sebagai teks dan tool
gagal dengan ``TypeError``. :func:`resolved_annotations` menyelesaikan anotasi
string tersebut (dengan fallback aman bila ada nama yang tak terimpor).
"""

from __future__ import annotations

import functools
import inspect
import types
import typing
from collections.abc import Callable
from typing import Any

#: Pemetaan tipe Python sederhana -> tipe JSON Schema.
JSON_TYPES = {int: "integer", float: "number", bool: "boolean", str: "string"}
_JSON_TYPES = JSON_TYPES


def json_type_for(annotation: Any) -> str:
    """Petakan anotasi Python ke tipe JSON Schema.

    Menangani ``int/float/bool/str/list/dict``, ``list[str]``/``dict[str, Any]``,
    ``Optional[X]``/``X | None``, dan ``Literal``.
    """
    if annotation is inspect.Parameter.empty or annotation is None:
        return "string"

    if isinstance(annotation, type):
        if annotation is bool:
            return "boolean"
        if annotation is int:
            return "integer"
        if annotation is float:
            return "number"
        if annotation is str:
            return "string"
        if annotation is list:
            return "array"
        if annotation is dict:
            return "object"
        return "string"

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin is typing.Literal:
        # Enum literal -> string (nilai spesifik diteruskan via description).
        return "string"
    if origin is not None:
        if origin in (list, set, frozenset, tuple):
            return "array"
        if origin is dict:
            return "object"
        if origin is typing.Union or origin is types.UnionType:
            # Optional[X] / X | None -> pakai tipe non-None-nya.
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                return json_type_for(non_none[0])
            return "string"
        if isinstance(origin, type):
            return _JSON_TYPES.get(origin, "string")
    return "string"


@functools.lru_cache(maxsize=1024)
def resolved_annotations(fn: Callable) -> dict[str, Any]:
    """Resolusi anotasi string (PEP 563) menjadi objek tipe.

    Gagal diam-diam (fallback ke anotasi mentah) bila ada anotasi yang
    merujuk nama yang tidak tersedia saat runtime.
    """
    try:
        return typing.get_type_hints(fn)
    except Exception:  # noqa: BLE001 - fallback aman ke anotasi mentah
        return {}


def annotation_for(fn: Callable, param_name: str, raw: Any) -> Any:
    """Anotasi efektif untuk satu parameter (resolved bila memungkinkan)."""
    hints = resolved_annotations(fn)
    return hints.get(param_name, raw)


def parse_docstring_params(doc: str) -> dict[str, str]:
    """Ambil deskripsi argumen dari bagian 'Args:' docstring."""
    out: dict[str, str] = {}
    in_args = False
    for line in (doc or "").splitlines():
        stripped = line.strip()
        if stripped.rstrip(":").lower() in ("args", "parameters", "arguments"):
            in_args = True
            continue
        if in_args:
            if not stripped:
                continue
            if stripped.endswith(":") or stripped.split(":")[0].lower() in (
                "returns",
                "raises",
                "yields",
                "example",
                "examples",
            ):
                break
            if ":" in stripped:
                nm, desc = stripped.split(":", 1)
                out[nm.strip().split(" ")[0]] = desc.strip()
    return out
