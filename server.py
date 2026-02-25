import os
import json
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pydantic import BaseModel
from typing import List, Optional

# --- Configuration & Security ---
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
SKILLS_DIR = BASE_DIR / "skills"
DEFAULT_SKILLS_DIR = SKILLS_DIR / "default"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
DEFAULT_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

# Create a sample default skill if none exists
sample_default = DEFAULT_SKILLS_DIR / "jira-rules.md"
if not sample_default.exists():
    sample_default.write_text("# Default Jira Rules\n- Always include ticket IDs in commits.\n- Keep comments concise.", encoding="utf-8")

# --- Database Setup (SQLite) ---
DATABASE_URL = f"sqlite:///{DATA_DIR}/skills.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class DBSkill(Base):
    __tablename__ = "skills"
    id = Column(Integer, primary_key=True, index=True)
    owner_type = Column(String(20), index=True, nullable=False) # 'team' or 'user'
    owner_id = Column(String(50), index=True, nullable=False)
    name = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    override_target = Column(String(100), nullable=True) # ID/filename of global skill
    bound_mcp_servers = Column(Text, nullable=True)      # JSON array of Server names

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Schemas ---
class SkillCreate(BaseModel):
    name: str
    content: str
    override_target: Optional[str] = None
    bound_mcp_servers: Optional[List[str]] = None
    
class SkillResponse(BaseModel):
    id: int
    owner_type: str
    owner_id: str
    name: str
    content: str
    override_target: Optional[str] = None
    bound_mcp_servers: Optional[List[str]] = None
    class Config:
        from_attributes = True
        
class GlobalSkillResponse(BaseModel):
    id: str
    name: str
    content: str
    bound_mcp_servers: List[str]

# --- API App ---
app = FastAPI(title="AIAM Skill Backend")

# Security: CORS for local UI testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow UI
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Core Skill Loader Logic ---
def get_global_skills() -> List[dict]:
    """Safely reads default skills from the filesystem."""
    globals = []
    try:
        if DEFAULT_SKILLS_DIR.exists():
            for file_path in DEFAULT_SKILLS_DIR.iterdir():
                if file_path.is_file() and file_path.suffix == ".md" and file_path.parent == DEFAULT_SKILLS_DIR:
                    content = file_path.read_text(encoding="utf-8")
                    name = file_path.stem.replace("-", " ").title()
                    mcp_servers = ["mcp-atlassian"] if "jira" in name.lower() else []
                    globals.append({
                        "id": file_path.name,
                        "name": name,
                        "content": content,
                        "bound_mcp_servers": mcp_servers
                    })
    except Exception as e:
        print(f"Error loading defaults: {e}")
    return globals

def get_active_configuration(team_id: str, user_id: str, db: Session):
    globals = get_global_skills()
    
    db_skills = db.query(DBSkill).filter(
        ((DBSkill.owner_type == 'team') & (DBSkill.owner_id == team_id)) |
        ((DBSkill.owner_type == 'user') & (DBSkill.owner_id == user_id))
    ).all()
    
    overrides = [s.override_target for s in db_skills if s.override_target]
    
    active_skills = []
    active_mcp_servers = set()
    
    for g in globals:
        if g["id"] not in overrides:
            active_skills.append(f"### Global Skill: {g['name']}\n{g['content']}")
            active_mcp_servers.update(g["bound_mcp_servers"])
            
    for s in db_skills:
        tier_label = "Team Skill" if s.owner_type == 'team' else "Personal Skill"
        active_skills.append(f"### {tier_label}: {s.name}\n{s.content}")
        if s.bound_mcp_servers:
            try:
                servers = json.loads(s.bound_mcp_servers)
                active_mcp_servers.update(servers)
            except:
                pass
                
    system_prompt = "You are the AIAM Agent. Below are your loaded skills and rules:\n\n"
    if active_skills:
        system_prompt += "\n\n".join(active_skills)
    else:
        system_prompt += "No active skills loaded."
    
    return system_prompt, list(active_mcp_servers)

# --- API Endpoints ---

@app.get("/health")
def health_check():
    return {"status": "ok", "agent": "aiam-skill-agent-local"}

# JSON-RPC Chat Endpoint (Mocking the real one)
@app.post("/")
async def chat_endpoint(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except:
        return JSONResponse({"error": {"code": -32700, "message": "Parse error"}}, status_code=400)
    
    method = payload.get("method")
    req_id = payload.get("id", "1")
    params = payload.get("params", {})
    
    if method != "message/send":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}, status_code=404)
    
    # Extract user message
    user_msg = ""
    parts = params.get("message", {}).get("parts", [])
    if parts and len(parts) > 0:
        user_msg = parts[0].get("text", "")
    
    # Extract team profile from params (New Feature!)
    team_id = params.get("teamProfile", "default")
    user_id = params.get("userProfile", "dev-user")
    
    # 1. LOAD SKILLS
    system_prompt, mcp_servers = get_active_configuration(team_id, user_id, db)
    
    # 2. MOCK LLM RESPONSE
    reply_text = f"**Agent Received Message:** {user_msg}\n\n"
    reply_text += f"**Active Team Profile:** `{team_id}` | **User Profile:** `{user_id}`\n\n"
    reply_text += f"**Enabled MCP Servers:** `{', '.join(mcp_servers) if mcp_servers else 'None'}`\n\n"
    reply_text += f"<details><summary>Click to view the System Prompt carrying Active Skills</summary>\n\n```markdown\n{system_prompt}\n```\n</details>"
    
    response_payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "message": {
                "role": "agent",
                "parts": [{"type": "text", "text": reply_text}],
                "contextId": "ctx-local-test"
            }
        }
    }
    return JSONResponse(response_payload)

# --- Configurator UI Endpoints ---
@app.get("/api/skills/global", response_model=List[GlobalSkillResponse])
def get_global_skills_endpoint():
    return get_global_skills()

@app.get("/api/skills/{owner_type}/{owner_id}")
def read_skills(owner_type: str, owner_id: str, db: Session = Depends(get_db)):
    db_skills = db.query(DBSkill).filter(DBSkill.owner_type == owner_type, DBSkill.owner_id == owner_id).all()
    out = []
    for s in db_skills:
        svrs = []
        if s.bound_mcp_servers:
            try: svrs = json.loads(s.bound_mcp_servers)
            except: pass
        out.append({
            "id": s.id, "owner_type": s.owner_type, "owner_id": s.owner_id,
            "name": s.name, "content": s.content, "override_target": s.override_target,
            "bound_mcp_servers": svrs
        })
    return out

@app.post("/api/skills/{owner_type}/{owner_id}", response_model=SkillResponse)
def create_skill(owner_type: str, owner_id: str, skill: SkillCreate, db: Session = Depends(get_db)):
    if not skill.name.strip() or not skill.content.strip():
        raise HTTPException(status_code=400, detail="Name and content required")
    if owner_type not in ["team", "user"]:
        raise HTTPException(status_code=400, detail="Invalid owner type")
    if len(skill.content) > 10000:
        raise HTTPException(status_code=400, detail="Skill content too large")
        
    mcp_json = json.dumps(skill.bound_mcp_servers) if skill.bound_mcp_servers else "[]"
    
    db_skill = DBSkill(
        owner_type=owner_type, 
        owner_id=owner_id, 
        name=skill.name, 
        content=skill.content,
        override_target=skill.override_target,
        bound_mcp_servers=mcp_json
    )
    db.add(db_skill)
    db.commit()
    db.refresh(db_skill)
    return db_skill

@app.delete("/api/skills/{owner_type}/{owner_id}/{skill_id}")
def delete_skill(owner_type: str, owner_id: str, skill_id: int, db: Session = Depends(get_db)):
    db_skill = db.query(DBSkill).filter(DBSkill.id == skill_id, DBSkill.owner_type == owner_type, DBSkill.owner_id == owner_id).first()
    if not db_skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    db.delete(db_skill)
    db.commit()
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8080, reload=True)
