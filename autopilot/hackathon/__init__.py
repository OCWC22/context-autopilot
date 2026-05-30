"""Beta Fund x EverMind hackathon integration (2026-05-30).

Submits the project to the sponsors as required:
- Butterbase = the backend/state layer AND the judging submission surface
  ("all projects must be submitted through Butterbase MCP", code build0530).
- EverMind / EverOS = the long-term agent memory the project is built on
  ("Build on top of Evermind"): repo decisions, architecture DAG, eval results,
  and coding-style traces become agent memory the system recalls across sessions.

`autopilot submit` provisions Butterbase tables, writes the project + eval +
bundle records, pushes durable memory to EverMind, and emits the submission
packet. Runs in dry-run with no keys so you can rehearse before the event.
"""

from .submit import submit, ButterbaseClient, SUBMISSION_CODE, BUTTERBASE_PROMO  # noqa: F401
