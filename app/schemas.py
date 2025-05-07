from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

# ─── Game State Schemas ─────────────────────────────────────────────────────────

class MapSize(BaseModel):
    width: int
    height: int

class GameMap(BaseModel):
    size: MapSize
    explored: List[List[int]]
    visible_objects: List[Dict[str, Any]]

class GameStatePlayer(BaseModel):
    cities: List[Dict[str, Any]]
    units: List[Dict[str, Any]]
    technologies: List[Dict[str, Any]]
    resources: Dict[str, Any]

class GameState(BaseModel):
    turn: int
    current_player: str
    player: GameStatePlayer
    ai: GameStatePlayer
    map: GameMap


# ─── Auth & Profile ─────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str

class ProfileUpdate(BaseModel):
    username: Optional[str]
    email: Optional[str]

class UserOut(BaseModel):
    id: str = Field(alias="sub")
    username: Optional[str]
    email: Optional[str]
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None

    class Config:
        validate_by_name = True
        from_attributes = True


# ─── Cheat System ───────────────────────────────────────────────────────────────

class CheatTarget(BaseModel):
    type: str
    id: str

class CheatRequest(BaseModel):
    game_id: str
    cheat_code: str
    target: CheatTarget

class AffectedEntity(BaseModel):
    type: str
    id: str
    changes: Dict[str, Dict[str, Any]]

class CheatResponse(BaseModel):
    success: bool
    message: str
    affected_entity: AffectedEntity
    game_state: GameState

    class Config:
        from_attributes = True


# ─── Game Management ────────────────────────────────────────────────────────────

class GameCreate(BaseModel):
    name: str
    scenario_id: str
    game_state: GameState

class GameOut(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    name: str
    scenario_id: str
    created_at: datetime
    last_saved: datetime
    is_autosave: bool
    cheats_used: List[str]
    game_state: GameState

    class Config:
        validate_by_name = True
        from_attributes = True

class ScenarioOut(BaseModel):
    id: str = Field(alias="_id")
    name: str
    description: str
    difficulty: str
    map_size: MapSize
    initial_state: Dict[str, Any]

    class Config:
        validate_by_name = True
        from_attributes = True