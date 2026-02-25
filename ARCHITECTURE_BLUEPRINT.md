# AIAM Enterprise Architecture & Implementation Blueprint

This document defines the clear, strict separation of concerns for the final AIAM Agent architecture. To prevent confusion, remember this central tenet: **Skills are Configuration (Markdown), Tools are Services (Containers), and the Agent is just an Orchestrator (Router).**

There are three distinct layers to this architecture. Keep their codebases and responsibilities strictly separated.

---

## Layer 1: The AIAM Agent Orchestrator (The "Engine")
*Where it runs:* The central Python/FastAPI Application (e.g., `server.py`).

The Orchestrator's *only* job is to receive a user message, fetch the appropriate configuration, connect to the exact tools requested by that configuration, and let the LLM execute. 

**Implementation Responsibilities:**
1. **Receive Chat Input:** Accepts `teamProfile`, `userProfile`, and the user's `message`.
2. **Call the Config Loader:** Runs `get_active_configuration(team_id, user_id)` to get the massive Markdown string of rules and the `["list-of-mcp-servers"]`.
3. **Connect to MCPs:** Iterates over the list of servers. For every server (e.g., `mcp-atlassian`), it connects to the remote container via the `MCP_REGISTRY`, runs `.list_tools()`, and gathers the JSON schemas.
4. **Execute LLM:** Passes the Markdown string as the `system_prompt` and the giant array of JSON schemas as the `tools` list to the LLM (e.g., Langchain/OpenAI).
5. **Tool Routing:** If the LLM returns a Tool Call (e.g., `create_ticket`), the Orchestrator finds the MCP client that provided that schema, runs `.call_tool()`, and returns the result to the LLM.

*Crucially: The Orchestrator contains zero Python code for specific tools, and zero Python code for specific skills.*

---

## Layer 2: The Skill Configurator & Loader (The "Control Plane")
*Where it runs:* The UI (`admin.html`), the Database (`skills.db`), and the Loader Logic (`get_active_configuration`).

This layer dictates *what* the Agent should do and *what tools* it needs. It does not execute tools itself.

**Implementation Responsibilities:**
1. **Global Fallbacks:** Reads baseline company `.md` files from the `skills/default/` directory.
2. **Overrides (Storage):** The Configurator UI allows teams (via `admin.html`) to clone global rules and explicitly modify them (saving to `skills.db`).
3. **The Loader Logic:** When the Orchestrator requests context, this layer automatically replaces Global rules with any Database Overrides for that specific user. 
4. **Tool Demands:** Every skill (Markdown file) can return an array of `bound_mcp_servers`. The Loader combines all required arrays into a single, deduplicated set (e.g., `{"mcp-atlassian", "mcp-gitlab"}`) and hands it to Layer 1.

*Crucially: This layer is entirely Semantic. It outputs a String (the prompt) and a List of Strings (the needed servers).*

---

## Layer 3: The MCP Tooling Containers (The "Hands")
*Where it runs:* Isolated Docker Containers separate from the main Agent (e.g., `mcp-atlassian`, `mcp-docintel`).

This layer is the only place where actual API execution code lives. Each tool container does one job perfectly.

**Implementation Responsibilities:**
1. **Independent Microservices:** A team builds an isolated service using the official TypeScript or Python MCP SDK.
2. **Tool Definition:** The service exposes `ListTools` by defining its JSON schemas (e.g., "I know how to search Jira").
3. **Execution Logic:** The service exposes `CallTool` and writes the actual Python/TS code to hit the Jira API using service accounts.
4. **The Registry Mapping:** To make these tools available to Layer 1 and Layer 2, you place the container's internal network URL into the central `MCP_REGISTRY.json` file.

*Crucially: The MCP container has no idea who the LLM is, has no system prompts, and does not understand conversational context. It just executes rigid API commands and returns JSON.*

---

## Example Flow of a Request

1. **User Request:** A DevOps engineer types: "Can you create a Jira ticket for this build failure?"
2. **Layer 2 (Configurator):** The Loader sees the user is in DevOps. It drops the Global Jira rules because DevOps created an Override. It returns the Custom DevOps Markdown rule, and says `"We need mcp-atlassian"`.
3. **Layer 1 (Orchestrator):** The Orchestrator connects to the `mcp-atlassian` container, gets the `create_ticket` JSON schema, and invokes the LLM with the custom rules and the schema.
4. **Agent Decision:** The LLM decides it must call `create_ticket`.
5. **Layer 3 (MCP Server):** The Orchestrator blindly passes the arguments to the `mcp-atlassian` container. The container physically creates the requested Jira ticket and returns success to the orchestrator.
