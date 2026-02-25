# AIAM Skill Framework: Authoring Guide

The AIAM Skill Framework is incredibly modular. It is designed so that non-technical users and admins can instantly inject, modify, or strip behaviors from the core agent without changing the LLM execution code. 

There are two primary ways to add skills, depending on the scope of the rule.

---

## 1. Global Baseline Skills (Codebase)

Global skills represent company-wide standards and best practices (e.g., "Company-Wide Jira Standards", "Python Best Practices"). These ship inside the Git repository with the AIAM agent codebase.

### How to Add a Global Skill:
1. Navigate to the `skills/default/` directory in the repository.
2. Create a new `.md` file (e.g., `git-commit-rules.md`).
3. Write your instructions using standard Markdown. State clear, concise rules for the agent.

### Conventions:
* **Filenames:** Use lowercase with hyphens (kebab-case). The Python backend automatically parses the filename into the display name.
  * *Example:* `python-best-practices.md` becomes the title "Python Best Practices".
* **Formatting:** Use strong headings and short bullet points. The LLM parses formatted lists and explicit constraints much better than large paragraphs.
* **MCP Binding:** By default, if a skill requires an external Model Context Protocol (MCP) tool like `mcp-gitlab` or `mcp-atlassian`, the mapping is configured in the `get_global_skills()` function inside `server.py` to ensure it dynamically bounds the right external context.

---

## 2. Team & Personal Skills (UI Configurator)

Team and Personal skills allow specific groups (e.g., "Frontend") or users to override the global baseline or add hyper-specific workflows without cluttering the global prompt for everyone else.

### How to Add via UI:
1. Open the Skill Configurator (`admin.html`).
2. Select your Team or Personal profile from the sidebar.
3. To **Add a completely new workflow**: Fill out the form at the bottom, specify any MCP servers (comma-separated, e.g., `mcp-kubernetes`), and click Save.
4. To **Override a Global Skill**: Find the Global DB Baseline Rules in the configurator and click the "Override this Baseline" button. The UI will instantly clone the global rules into your custom editor. You can then delete, append, or modify the company standards to fit your personal workflow. Click Save.

### Conventions:
* **Rule Collisions:** If you override a Global Skill, the framework completely drops the global rule and *only* injects your custom override. Do not delete standard rules in your template modification unless you explicitly want the agent to ignore them.
* **Micro-Skills:** Keep custom skills small and focused. Create one skill for "Deployment Rules", a separate one for "Code Formatting", and a third for "Jira Creation". This allows the backend to intelligently decouple the LLM token load.
* **MCP Server Names:** Ensure you use the exact MCP server identifier configured in your production environment (e.g., `mcp-atlassian`, `mcp-gitlab`).

---

## 3. Best Practices for Writing AI Rules

* **Be Absolute:** Use words like "Always", "Never", "Must". This acts as a strict guardrail for the LLM.
* **Provide Examples:** If enforcing a specific JSON schema, conventional commit message format, or Terraform block architecture, provide a tiny code block example in the markdown. The LLM learns best through these "few-shot" examples.
* **Avoid Duplication:** Do not write rules that are already defined in the Global Baseline unless you are explicitly overriding that baseline. Rely on the inheritance mechanism to keep your personal prompt clean and fast.
