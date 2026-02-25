import os
import sys
import json
import asyncio
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

# Import from our existing backend AIAM Skill Framework
from server import SessionLocal, get_active_configuration

# ---------------------------------------------------------
# LAYER 3: THE MCP REGISTRY
# This maps the string identifiers from our Markdown skills to actual physical containers.
# In production, these points to internal Docker urls via SSE. For local testing, we use npx stdio.
# ---------------------------------------------------------
MCP_REGISTRY = {
    # We map "mcp-atlassian" to the public 'memory' server just to prove the LLM can discover and use tools
    "mcp-atlassian": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"]
    },
    # We map "mcp-gitlab" to the public 'fetch' server 
    "mcp-gitlab": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-fetch"]
    }
}

async def run_orchestrator(team_id: str, user_id: str, prompt: str):
    print(f"\n=======================================================")
    print(f"🚀 RUNNING AIAM ORCHESTRATOR FOR: [Team: {team_id}] [User: {user_id}]")
    print(f"=======================================================\n")
    
    # ---------------------------------------------------------
    # LAYER 2: SKILL ROUTING ENGINE (The 'What')
    # ---------------------------------------------------------
    db = SessionLocal()
    try:
        system_prompt, required_servers = get_active_configuration(team_id, user_id, db)
    finally:
        db.close()
        
    print(f"[*] SKILL ENGINE: Loaded {len(required_servers)} required MCP servers: {required_servers}")
    print(f"[*] SKILL ENGINE: System Prompt Length: {len(system_prompt)} chars\n")
    
    # ---------------------------------------------------------
    # LAYER 3: MCP CLIENT DISCOVERY (The 'How')
    # ---------------------------------------------------------
    active_mcp_sessions = {}
    llm_tools = []
    
    from contextlib import AsyncExitStack
    async with AsyncExitStack() as stack:
        print(f"[*] MCP CLIENT (Orchestrator): Dynamically connecting to requested servers...")
        for server_name in required_servers:
            if server_name not in MCP_REGISTRY:
                print(f"    [!] Warning: '{server_name}' not found in registry. Skipping.")
                continue
                
            config = MCP_REGISTRY[server_name]
            server_params = StdioServerParameters(command=config["command"], args=config["args"])
            
            print(f"    -> Booting isolated container: {server_name}...")
            # We connect to the remote container natively via stdio mapping
            transport = await stack.enter_async_context(stdio_client(server_params))
            read, write = transport
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            
            active_mcp_sessions[server_name] = session
            
            # Blindly ask the remote container for its capabilities (ListTools)
            tools_response = await session.list_tools()
            for t in tools_response.tools:
                # Format the JSON Schema for Langchain/OpenAI
                lc_tool = {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema
                    },
                    # We inject an internal tracking tag so we know where to route execution later
                    "mcp_server_owner": server_name
                }
                llm_tools.append(lc_tool)
                print(f"      + Discovered Tool: '{t.name}' (owned by {server_name})")
                
        print()
        
        # ---------------------------------------------------------
        # LAYER 1: LANGCHAIN / LLM EXECUTION (The 'Brain')
        # ---------------------------------------------------------
        print("[*] LANGCHAIN: Initializing OpenAI Agent...")
        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        
        # We must strip out our internal tracking field before binding to OpenAI
        bindable_tools = [{"type": "function", "function": t["function"]} for t in llm_tools]
        
        if bindable_tools:
            llm_with_tools = llm.bind_tools(bindable_tools)
        else:
            print("    -> No tools discovered. Running purely on semantic rules.")
            llm_with_tools = llm
            
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt)
        ]
        
        print(f"[*] LANGCHAIN: Sending prompt to LLM: '{prompt}'")
        ai_msg = await llm_with_tools.ainvoke(messages)
        messages.append(ai_msg)
        
        # Did the LLM decide to use a tool?
        if ai_msg.tool_calls:
            print(f"\n[*] LANGCHAIN: LLM decided to execute {len(ai_msg.tool_calls)} tool call(s).")
            
            for tool_call in ai_msg.tool_calls:
                name = tool_call["name"]
                args = tool_call["args"]
                tool_call_id = tool_call["id"]
                
                print(f"    -> Intercepted tool request: '{name}'")
                
                # Look up which container owns this tool based on our earlier tracking
                server_owner = next((t["mcp_server_owner"] for t in llm_tools if t["function"]["name"] == name), None)
                if not server_owner:
                    print(f"    [!] Error: No registered MCP server owns '{name}'")
                    messages.append(ToolMessage(content="Error: Tool execution failed.", tool_call_id=tool_call_id))
                    continue
                    
                print(f"    -> Routing execution natively to standalone container: {server_owner}")
                
                # Execute the tool on the remote container (CallTool)
                session = active_mcp_sessions[server_owner]
                try:
                    result = await session.call_tool(name, arguments=args)
                    tool_output = "\n".join([c.text for c in getattr(result, 'content', []) if getattr(c, 'type', '') == 'text'])
                except Exception as e:
                    tool_output = f"Error executing tool: {str(e)}"
                    
                print(f"    -> Tool returned output ({len(tool_output)} chars). Feeding back to LLM context...")
                messages.append(ToolMessage(content=tool_output, tool_call_id=tool_call_id))
                
            # Let the LLM read the tool output and chain another thought or summarize
            print("\n[*] LANGCHAIN: Generating final agentic response...")
            final_msg = await llm_with_tools.ainvoke(messages)
            print("\n=== FINAL AGENT RESPONSE ===")
            print(final_msg.content)
            print("============================\n")
        else:
            print("\n=== FINAL AGENT RESPONSE (No tools needed) ===")
            print(ai_msg.content)
            print("============================\n")

if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        print("\n[!] ERROR: You must set your OPENAI_API_KEY environment variable to test this orchestrator.")
        print("    Example (Windows PowerShell): $env:OPENAI_API_KEY='sk-...'")
        print("    Example (Mac/Linux Bash):     export OPENAI_API_KEY='sk-...'")
        sys.exit(1)
        
    team = "devops"
    user = "alice"
    user_prompt = "What did I instruct you to do about Jira in my skills? Do you have access to any tools? Create a memory graph called 'JiraRules' mapping my rules using your tool."
    
    if len(sys.argv) > 1:
        user_prompt = sys.argv[1]
        
    asyncio.run(run_orchestrator(team_id=team, user_id=user, prompt=user_prompt))
