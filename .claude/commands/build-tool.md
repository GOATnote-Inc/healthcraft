# /build-tool [name]

Implement an MCP tool with tests, schema, and Docker integration.

## Team
- **tool-implementer** (sonnet): Implement tool module
- **infra-engineer** (sonnet): Docker integration and MCP server wiring

## Workflow
1. tool-implementer creates `src/healthcraft/mcp/tools/{name}.py` with:
   - Async tool function with type hints
   - Input validation
   - Audit logging
   - World state interaction
2. tool-implementer registers tool in `src/healthcraft/mcp/server.py`
3. tool-implementer writes tests in `tests/test_mcp_tools/test_{name}.py`
4. infra-engineer verifies Docker compose integration

## Validation
- [ ] Tool registered in MCP server
- [ ] Input validation covers edge cases
- [ ] Audit log records tool call
- [ ] World state mutations are consistent
- [ ] Tests pass against sample world state
