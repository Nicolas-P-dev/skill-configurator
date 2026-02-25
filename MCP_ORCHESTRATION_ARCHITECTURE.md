# Optimal LLM Agent Orchestration via Model Context Protocol (MCP)

This document outlines the optimal architecture for building a scalable, tool-agnostic LLM orchestrator. It explains how to fully decouple the **Skill Routing Engine** (which determines *what* an agent needs) from the **MCP Client Layer** (which provides *how* the agent executes tasks).

This architecture allows developers to add infinite new tools (Jira, GitLab, Database query engines) to an AI system without writing a single line of custom tool-parsing code in the central LLM orchestration repository.

---

## 1. The Core Problem
In traditional AI agent architectures, every newly requested capability requires central code changes:
1. Hardcoding an API wrapper for the new tool (e.g., `def create_jira_ticket(title):`).
2. Hardcoding the JSON Schema representation of that tool to pass into the LLM context.
3. Hardcoding conditional logic to route the LLM's raw tool-call output to the correct Python/TypeScript function.

When scaling to dozens of tools across multiple teams, the main agent repo becomes a bloated, monolithic bottleneck. Furthermore, eagerly injecting all 50+ tool schemas into the LLM's context window degrades reasoning, increases latency, and maximizes costs.

## 2. The MCP Architectural Solution
The solution is a hyper-modular, two-part architecture:
1. **The Skill Router**: A purely semantic configuration layer defining rules and required tool connections.
2. **The Generic MCP Orchestrator**: A dumb, tool-agnostic loop that reads the router's config and dynamically queries remote MCP containers.

### Part A: The Skill Router (The `aiam-core` Repository)
Instead of hardcoding logic, the central repo only stores Markdown files denoting "Skills". If a specific workflow requires tools, the Skill explicitly maps a string identifier.

```json
// The output of the Skill Engine for a specific user request:
{
  "system_prompt": "You are the AIAM agent.\n\n# Jira Rules\n1. Always add ticket IDs to commits.",
  "required_mcp_servers": ["mcp-atlassian"]
}
```

### Part B: The Remote MCP Tool Containers
Teams (e.g., Atlassian Ops) build isolated microservices running an MCP Server (`mcp-atlassian`). 
This container holds the *actual* execution logic. It exposes standard MCP methods (`ListTools`, `CallTool`) over an SSE or Stdio transport layer. It has zero knowledge of the LLM or the central agent.

---

## 3. The "Dumb" Orchestration Loop (The Magic)
This is the optimal implementation of the central orchestration layer. The orchestrator never knows what a `create_ticket` function is; it only knows how to route JSON payloads natively using the official MCP Client SDK.

### Step 1: The Connection Registry
Maintain a simple registry mapping the Skill Engine's string identifiers to physical container connection endpoints.
```python
MCP_REGISTRY = {
    "mcp-atlassian": {"url": "http://jira-container-internal:3000/sse"},
    "mcp-gitlab": {"url": "http://gitlab-container-internal:3000/sse"}
}
```

### Step 2: Dynamic Tool Discovery (`ListTools`)
When a request arrives, the orchestrator connects *only* to the servers requested by the Skill Engine, and asks them for their tool schemas dynamically.

```python
import asyncio
from mcp import ClientSession # Official MCP SDK

async def build_llm_context(required_servers: list[str]):
    active_mcp_clients = {}
    llm_tool_schemas = []

    for server_name in required_servers:
        config = MCP_REGISTRY[server_name]
        
        # 1. Open persistent connection to the standalone container
        client = ClientSession(config["url"])
        await client.connect()
        active_mcp_clients[server_name] = client
        
        # 2. Dynamically ask the container for its schemas!
        response = await client.list_tools()
        
        # 3. Append to the massive array passed blindly to the LLM
        for tool in response.tools:
            # Map tool name back to the server name for later routing 
            # (e.g. "create_ticket" belongs to "mcp-atlassian")
            tool.internal_server_owner = server_name 
            llm_tool_schemas.append(tool)

    return active_mcp_clients, llm_tool_schemas
```

### Step 3: LLM Invocation & Agnostic Execution (`CallTool`)
Pass the schemas to the LLM, let the LLM decide what to do, and then blindly forward the LLM's requested arguments to the correct external container.

```python
async def execute_agent_loop(system_prompt, active_mcp_clients, llm_tool_schemas):
    
    # 1. Give the agent its rules and the dynamically discovered tools
    llm_response = await llm.generate(
        prompt=system_prompt,
        tools=llm_tool_schemas
    )
    
    # 2. Iterate through the LLM's tool-call decisions
    if llm_response.tool_calls:
        for tool_call in llm_response.tool_calls:
            # e.g., tool_call.name = "create_ticket"
            # e.g., tool_call.arguments = {"summary": "Fix login bug"}
            
            # Find the client that registered this schema
            server_name = get_server_owner_for_tool(tool_call.name)
            client = active_mcp_clients[server_name]
            
            # 3. Blindly forward the tool execution to the external container!
            # The AIAM repo contains ZERO custom python executing this logic.
            result = await client.call_tool(
                name=tool_call.name, 
                arguments=tool_call.arguments
            )
            
            # 4. Feed result back to the LLM
            append_to_conversation_history(result)
            
    # Clean up connections when request finishes
    for client in active_mcp_clients.values():
        await client.close()
```

## Conclusion for Claude Review
This architecture achieves **O(1) Central Complexity** for adding new tools. To add an entirely new capability (e.g., AWS EC2 Management):
1. Write a standalone AWS MCP Docker container.
2. Add `"mcp-aws": "http://aws-mcp:3000"` to the JSON registry.
3. Write a `rules.md` file in the UI dictating the team's EC2 tag naming conventions, bound to "mcp-aws".

The core LLM repository requires **zero PRs, zero python edits, and zero recompiles** to leverage this new backend capability perfectly. The Context Window remains hyper-focused and highly precise, dramatically improving latency and reducing hallucination.
