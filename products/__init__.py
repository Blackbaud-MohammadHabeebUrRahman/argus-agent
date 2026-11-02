"""In-repo product plugins.

Each subpackage ships a ``register(hub)`` function that an entry point in
pyproject.toml exposes under the ``argus.plugins`` group. External plugins
can ship from their own distributions the same way.
"""
