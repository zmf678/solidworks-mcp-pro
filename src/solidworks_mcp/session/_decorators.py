"""Decorators shared by the session mixins."""

import functools


def _reads_only(method):
    """Mark a tool that only reads the current document.

    It is not made SolidWorks' active document first, so a person or another
    session working in SolidWorks keeps the window they are in. Tools that
    sketch, add features, export or take screenshots still activate it
    (_require_model).
    """

    @functools.wraps(method)
    def tool(self, *args, **kwargs):
        self._reading += 1
        try:
            return method(self, *args, **kwargs)
        finally:
            self._reading -= 1

    return tool
