"""Development-tree import shim.

The distributable package lives in ``soropy/soropy`` next to this file. When
an editable install is used while Python is launched from the repository root,
the outer project directory can otherwise be selected as an empty namespace
package before setuptools' editable finder runs. Point this package at the real
source tree and execute its public initializer.

This shim is not included as a package in built wheels/sdists.
"""

from pathlib import Path

_SOURCE_PACKAGE = Path(__file__).resolve().parent / "soropy"
__path__ = [str(_SOURCE_PACKAGE)]
__file__ = str(_SOURCE_PACKAGE / "__init__.py")

_code = compile(
    (_SOURCE_PACKAGE / "__init__.py").read_text(encoding="utf-8"),
    __file__,
    "exec",
)
exec(_code, globals(), globals())
