# Agents

This directory contains individual agent modules. Each agent should have its own folder with the following structure:

- `__init__.py`
- `router.py`: API endpoints for the agent.
- `service.py`: Business logic for the agent.
- `schemas.py`: Pydantic models for request and response.

Refer to the `example_agent` for a template.
