"""Importing this package registers all @builtin functions on the registry."""
from app.runtime.tools.builtins import calculator, send_telegram, web_fetch  # noqa: F401
