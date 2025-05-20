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
    stored_tiles: Optional[List[List[Any]]] = None

class GameStatePlayer(BaseModel):
    cities: List[Dict[str, Any]]
    units: List[Dict[str, Any]]
    technologies: List[Dict[str, Any]]
    resources: Dict[str, Any]

class GameState(BaseModel):
    turn: int
    current_player: str
    player: GameStatePlayer
    ai: List[GameStatePlayer]  # Lista de jugadores IA
    map: GameMap


# ─── Auth & Profile ─────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class TokenRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400  # 24 horas en segundos

class ProfileUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None

class UserOut(BaseModel):
    id: str = Field(alias="_id")
    username: str
    email: str
    created_at: datetime
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

class PlayerAction(BaseModel):
    type: str
    details: Dict[str, Any]

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