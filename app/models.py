from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from bson import ObjectId
from datetime import datetime

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v, *args, **kwargs):  # <-- Accept extra args for Pydantic v2 compatibility
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

class User(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id")
    username: str
    email: str
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    is_active: bool = True

    class Config:
        json_encoders = { ObjectId: str }
        validate_by_name = True

class GameStatePlayer(BaseModel):
    cities: List[Dict[str, Any]]
    units: List[Dict[str, Any]]
    technologies: List[Dict[str, Any]]
    resources: Dict[str, Any]

class MapSize(BaseModel):
    width: int
    height: int

class GameMap(BaseModel):
    size: MapSize
    explored: List[List[int]]
    visible_objects: List[Dict[str, Any]]
    stored_tiles: Optional[List[List[Any]]] = None
    

class GameState(BaseModel):
    turn: int
    current_player: str
    player: GameStatePlayer
    ai: List[GameStatePlayer]
    map: GameMap

class Game(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id")
    user_id: str  # <-- Change from PyObjectId to str
    name: str
    scenario_id: str
    created_at: datetime
    last_saved: datetime
    is_autosave: bool
    cheats_used: List[str]
    game_state: GameState

    class Config:
        json_encoders = { ObjectId: str }
        validate_by_name = True

class Scenario(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id")
    name: str
    description: str
    difficulty: str
    map_size: MapSize
    initial_state: Dict[str, Any]

    class Config:
        json_encoders = { ObjectId: str }
        validate_by_name = True