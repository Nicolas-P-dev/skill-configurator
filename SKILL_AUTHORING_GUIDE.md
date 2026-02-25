# AIAM Skill Framework: Developer Integration Guide

The AIAM Skill Framework allows you to natively add distinct features, behaviors, and MCP server integrations into the core agent without changing the prompt logic for unrelated workflows.

This guide outlines how developers should structure, write, and map new Agent Skills.

---

## 1. Creating the Markdown Baseline

All core system behaviors ship natively inside the repository as fallback defaults ("Global Skills"). This ensures an infinitely scalable codebase without an extremely bloated main system prompt.

1. Create a `.md` file in `skills/default/` (e.g., `skills/default/gitlab-release-manager.md`).
2. Write rules strictly and affirmatively.

### Markdown Best Practices:
* **The "Zero-Shot" Rule:** The AIAM agent only gets the active skills injected into its prompt. Write the markdown file so that an AI agent reading *only* this file natively knows how to execute the workflow.
* **Few-Shot Examples:** Provide JSON templates, conventional commit formats, or sample query structures inside codeblocks in your markdown.
* **Avoid Generalities:** "Be helpful" or "Write good code" wastes tokens. Use "Enforce Google PEP8 Style" or "All Python functions must include NumPy docstrings."

**Example (`skills/default/gitlab-release-manager.md`):**
```markdown
# GitLab Release Manager Rules
You are responsible for cutting releases in GitLab.
1. Always run the `get_open_merge_requests` tool before drafting the release notes.
2. Group release notes into `Features` and `Bug Fixes`.
3. If an MR title does not follow Conventional Commits (e.g., `feat: ...`), flag it back to the user.
```

---

## 2. Binding MCP Servers (Tools)

To give your new Skill the actual *capabilities* to execute its rules (e.g., retrieving GitLab MRs), you must bind it to the relevant Model Context Protocol (MCP) server integration. 

The backend aggregates all active rules and deduplicates their bound MCP servers, ensuring that the agent's context window contains *only* the tools it actually needs for that specific user.

### Updating `server.py`
In the backend router `get_global_skills()`, intercept your new file and append the `bound_mcp_servers` JSON array.

```python
def get_global_skills() -> List[dict]:
    globals = []
    # ... directory iteration ...
        mcp_servers = []
        
        # 1. Bind your custom skill to an external MCP tool
        if file_path.name == "gitlab-release-manager.md":
            mcp_servers = ["mcp-gitlab"]
            
        # 2. Add other bindings as needed...
        elif "jira" in name.lower():
            mcp_servers = ["mcp-atlassian"]

        globals.append({
            "id": file_path.name,
            "name": name,
            "content": content,
            "bound_mcp_servers": mcp_servers
        })
    return globals
```

---

## 3. How the AI Context Mapping Works

Once you commit `skills/default/something-new.md` and define its `bound_mcp_servers` in Python:

1. **Discovery:** The UI configurator instantly identifies the new capability via the `/api/skills/global` endpoint.
2. **Overrides:** Teams can see this new GitLab template and press "Override this Baseline" to add their own internal release-branching strategies to it.
3. **Execution:** When a user chats with AIAM, the backend resolves the hierarchy (Global → Team → Personal). If the user is a `devops` engineer that uses the GitLab Release Manager, AIAM injects your `.md` prompt rules and strictly loads the tools exposed by `mcp-gitlab`. 

If a Data Scientist talks to the agent, the `gitlab-release-manager` logic and tools are entirely omitted from the prompt, saving tokens and compute!
