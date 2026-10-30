"""MCP server for an AI agent that works the review queue.

Read tools: list_pending_reviews, get_case, check_action.
Write tools: propose_action (creates a request, runs nothing), execute_action (runs only an
action a human has approved). There is deliberately NO approve tool: approval is a human
decision made over the HTTP API with the reviewer key, so an agent cannot release its own action.

Run:  python -m mcp_server.server        (stdio; shares CASE_DB with the API)
"""

from __future__ import annotations

import os
import threading

from mcp.server.mcpserver import MCPServer

from app.actions import ActionError, ActionStore
from app.store import CaseStore
from engine.audit import AuditLog


def build_server(cases: CaseStore, actions: ActionStore) -> MCPServer:
    mcp = MCPServer("claims-review-agent-tools")

    @mcp.tool()
    def list_pending_reviews() -> list[dict]:
        """Cases waiting for a human decision, with the reason they were escalated."""
        return [{"case_id": c["id"], "domain": c["domain"], "reason": c["result"]["reason"],
                 "issues": c["result"]["issues"]} for c in cases.list("pending_review")]

    @mcp.tool()
    def get_case(case_id: str) -> dict:
        """Extracted fields, issues and status for one case. The source document is not returned."""
        c = cases.get(case_id)
        if not c:
            return {"error": "no such case"}
        c.pop("text")
        return c

    @mcp.tool()
    def propose_action(case_id: str, kind: str, title: str = "", priority: str = "normal", template: str = "") -> dict:
        """Ask for an action (create_ticket or notify_customer). Nothing runs until a human approves it."""
        params = ({"title": title, "priority": priority} if kind == "create_ticket"
                  else {"template": template} if kind == "notify_customer" else {})
        try:
            a = actions.propose(case_id, kind, params, proposer="mcp-agent")
        except ActionError as e:
            return {"error": str(e)}
        return {"action_id": a["id"], "status": a["status"], "next": "wait for a human to approve in the review UI/API"}

    @mcp.tool()
    def check_action(action_id: str) -> dict:
        """Status of a proposed action."""
        a = actions.get(action_id)
        return {"action_id": a["id"], "status": a["status"]} if a else {"error": "no such action"}

    @mcp.tool()
    def execute_action(action_id: str) -> dict:
        """Run an action that a human has approved. Refused for any other status. Runs once."""
        try:
            a = actions.execute(action_id, executor="mcp-agent")
        except ActionError as e:
            return {"error": str(e)}
        return {"action_id": a["id"], "status": a["status"]}

    return mcp


def main() -> None:  # pragma: no cover
    cases = CaseStore(os.environ.get("CASE_DB", ":memory:"))
    actions = ActionStore(cases, AuditLog(), threading.Lock())
    build_server(cases, actions).run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
