"""Per-suite, per-tool namespace registry.

Interbolt resolves sinks by exact match on the full dotted key
(`policy.compiled_sinks.get(tool)`), with no namespace fallback. The string
this harness passes to `check()` must match a policy's sink keys exactly, so
namespace assignment is an explicit table here rather than something derived
by reflecting on a tool's defining module: AgentDojo wraps tools with
`make_function`, and recovering the original module from that wrapper
depends on an internal accessor that may change. An explicit table is
auditable and fails predictably -- the thing a reader can check directly
against a policy file.
"""

from __future__ import annotations

from collections.abc import Iterable

TOOL_NAMESPACES: dict[str, dict[str, str]] = {
    "workspace": {
        # email
        "send_email": "email",
        "delete_email": "email",
        "get_unread_emails": "email",
        "get_sent_emails": "email",
        "get_received_emails": "email",
        "get_draft_emails": "email",
        "search_emails": "email",
        "search_contacts_by_name": "email",
        "search_contacts_by_email": "email",
        # calendar
        "get_current_day": "calendar",
        "search_calendar_events": "calendar",
        "get_day_calendar_events": "calendar",
        "create_calendar_event": "calendar",
        "cancel_calendar_event": "calendar",
        "reschedule_calendar_event": "calendar",
        "add_calendar_event_participants": "calendar",
        # drive
        "search_files_by_filename": "drive",
        "search_files": "drive",
        "get_file_by_id": "drive",
        "list_files": "drive",
        "create_file": "drive",
        "delete_file": "drive",
        "append_to_file": "drive",
        "share_file": "drive",
    },
}

DEFAULT_SUITE_NAMESPACE: dict[str, str] = {
    "banking": "banking",
    "travel": "travel",
    "slack": "slack",
}


class NamespaceRegistryError(ValueError):
    """A tool has no resolvable namespace: a partial suite table or missing coverage."""


def resolve_namespace(suite_name: str, tool_name: str) -> str:
    """Resolve the namespace `tool_name` should be reported under for `suite_name`.

    Resolution order:
      1. `suite_name` has an explicit `TOOL_NAMESPACES` table and `tool_name` is
         in it -> use that namespace.
      2. `suite_name` has an explicit table but `tool_name` is missing from it
         -> raise. A partially mapped suite is a bug, not a fallback case.
      3. Otherwise -> `DEFAULT_SUITE_NAMESPACE.get(suite_name, suite_name)`, so
         an unmapped suite keeps working under a single suite-named namespace.
    """
    suite_map = TOOL_NAMESPACES.get(suite_name)
    if suite_map is not None:
        if tool_name not in suite_map:
            raise NamespaceRegistryError(
                f"suite {suite_name!r} has an explicit namespace table but does not map tool "
                f"{tool_name!r}; add it to TOOL_NAMESPACES[{suite_name!r}] rather than falling "
                "back silently"
            )
        return suite_map[tool_name]
    return DEFAULT_SUITE_NAMESPACE.get(suite_name, suite_name)


def validate_suite_coverage(suite_name: str, tool_names: Iterable[str]) -> None:
    """Assert every tool in `tool_names` resolves to a namespace for `suite_name`.

    Intended to run once, at executor construction, before any task runs --
    discovering a missing mapping mid-benchmark wastes the run; discovering it
    here costs a second. For suites without an explicit `TOOL_NAMESPACES`
    table (banking/travel/slack today), resolution can never fail, so this is
    a no-op safety net specifically for explicitly-mapped suites.
    """
    unresolved: list[str] = []
    for tool_name in tool_names:
        try:
            resolve_namespace(suite_name, tool_name)
        except NamespaceRegistryError:
            unresolved.append(tool_name)
    if unresolved:
        raise NamespaceRegistryError(
            f"suite {suite_name!r} has {len(unresolved)} tool(s) with no resolvable namespace: "
            f"{sorted(unresolved)}"
        )
