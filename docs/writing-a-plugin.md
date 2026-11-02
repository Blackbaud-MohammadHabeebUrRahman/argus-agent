# Writing an Argus plugin

Argus's core — scheduler, incident store, dedup, alert channels, the
investigation agent, and the MCP server — is product-agnostic. Everything
that knows about a specific product lives in a plugin.

A plugin can ship from the Argus monorepo (under `products/`) or from its
own PyPI distribution. The interface is the same either way: declare an
entry point, implement a `register(hub)` function, use the hub to add
check types, tools, and remediation actions.

## Minimal plugin

Three files. `products/myapp/` beside `products/saboten/`:

```
products/myapp/
├── __init__.py
└── checks.py
```

`products/myapp/__init__.py`:

```python
from argus.plugins import Hub
from .checks import register_checks


def register(hub: Hub) -> None:
    register_checks(hub)
```

`products/myapp/checks.py`:

```python
from argus.monitor.base import HealthCheck
from argus.models import CheckResult, CheckStatus


class MyAppWorkerCheck(HealthCheck):
    async def execute(self) -> CheckResult:
        # Call your app, decide status, return.
        return self._result(CheckStatus.OK, "worker healthy")


def register_checks(hub):
    def factory(name, svc_name, svc_cfg, chk_cfg, env):
        return MyAppWorkerCheck(
            name=name,
            service=svc_name,
            interval=chk_cfg.interval,
            timeout=chk_cfg.timeout,
            environment=env,
            thresholds=chk_cfg.thresholds,
        )
    hub.register_check("myapp.worker", factory)
```

## Wiring the entry point

In the monorepo, add to `pyproject.toml`:

```toml
[project.entry-points."argus.plugins"]
myapp = "products.myapp:register"
```

Then `pip install -e .` makes it discoverable.

For a standalone PyPI plugin (recommended for production use), its own
`pyproject.toml` declares the same entry point:

```toml
[project]
name = "argus-plugin-myapp"

[project.entry-points."argus.plugins"]
myapp = "argus_plugin_myapp:register"
```

Users then `pip install argus-plugin-myapp` and the plugin loads
automatically.

## Using it in config

```yaml
# config/argus.yaml
product: myapp     # loads only this plugin; omit to load everything

environments:
  dev:
    services:
      worker-1:
        host: "worker-1.internal"
        checks:
          - type: myapp.worker
            interval: 60
```

## Convention: dotted check names

Core checks have simple names (`http`, `redis`). Plugin checks use a
dotted prefix matching the plugin name (`saboten.job_health`,
`example.echo`). This keeps the namespace unambiguous and makes config
files self-documenting about which checks came from where.

## What's coming

Phases 2 and 5 expand the plugin surface:

- `hub.register_tool(name, func)` — investigation tools the agent can call
- `hub.register_action(name, func)` — remediation actions, gated through
  the HITL approval flow

The `register_tool` and `register_action` methods already exist on `Hub`;
the agent and remediation engine that consume them land in those phases.
