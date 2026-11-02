# Argus MCP server

Argus ships an MCP server so operators can drive investigations from
Claude Code, Claude Desktop, Cursor, or any other MCP client — no SSH
to a box, no custom UI, no Slack-bot plumbing. The server reuses the
real investigation agent, real tools, and real incident store, so
whatever an operator sees in Argus is what the MCP client sees too.

## Install

```bash
pip install -e '.[mcp]'
```

## Register with Claude Code

Add to `~/.config/claude-code/config.json` (or wherever your platform
puts it):

```json
{
  "mcpServers": {
    "argus": {
      "command": "python",
      "args": ["-m", "argus.mcp"],
      "cwd": "/path/to/argus",
      "env": {
        "ARGUS_CONFIG_PATH": "/path/to/argus/config/argus.yaml"
      }
    }
  }
}
```

## Register with Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or the Windows equivalent:

```json
{
  "mcpServers": {
    "argus": {
      "command": "/path/to/argus/.venv/bin/python",
      "args": ["-m", "argus.mcp"],
      "env": {
        "ARGUS_CONFIG_PATH": "/path/to/argus/config/argus.yaml"
      }
    }
  }
}
```

Restart Claude Desktop. The next session will see an **argus**
connection in the hammer menu with the resources, tools, and prompts
listed below.

## What the server exposes

### Resources

| URI | What it returns |
|-----|-----------------|
| `argus://incidents` | All currently-active incidents (JSON) |
| `argus://incident/{id}` | One incident's full record |
| `argus://services` | Configured services with their check definitions |
| `argus://alerts/recent` | Last 50 alert dispatches (placeholder for now) |

### Tools

| Name | Purpose |
|------|---------|
| `investigate_incident` | Runs the Phase 2 agent against an existing incident, returns the markdown report plus a trajectory summary |
| `query_splunk` | Direct passthrough to the Splunk tool — useful for ad-hoc searches without triggering a full investigation |
| `get_recent_deploys`, `search_github_prs`, `get_incident_context` | Core tools, exposed for drill-down |
| `get_saboten_job_history`, `check_saboten_vendor_api_health` | Saboten plugin tools (when the Saboten plugin is loaded) |

### Prompts

| Name | Starter |
|------|---------|
| `incident-triage` | Generic "walk me through this incident" with `incident_id` arg |
| `stuck-jobs` | Saboten-flavored stuck-jobs triage with optional `job_type`, `incident_id` |
| `worker-crash-loop` | For a crashlooping worker |

## Try it from a shell

The quickest smoke test — no Claude needed:

```bash
# One terminal: run the MCP server
python -m argus.mcp

# Another: use the mcp CLI to inspect
mcp dev python -m argus.mcp
```

## Security notes

- The MCP server runs with whatever privileges Argus itself has. Don't
  expose it over a network transport without putting it behind an
  authenticated proxy.
- `investigate_incident` spends tokens against your configured
  Anthropic account; a chatty client could burn through credits.
  Future work: a per-session cost cap enforced at the server.
- The tools passthrough is identical to what the investigation agent
  has access to. If the agent should never see your secrets, the MCP
  client should never see them either.
