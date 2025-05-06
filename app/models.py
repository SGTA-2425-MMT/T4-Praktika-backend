from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from bson import ObjectId
from datetime import datetime

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

class User(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id")
    username: str
    email: str
    password_hash: str
    created_at: datetime
    last_login: Optional[datetime]

    class Config:
        json_encoders = { ObjectId: str }
        allow_population_by_field_name = True

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

class GameState(BaseModel):
    turn: int
    current_player: str
    player: GameStatePlayer
    ai: GameStatePlayer
    map: GameMap

class Game(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id")
    user_id: PyObjectId
    name: str
    scenario_id: str
    created_at: datetime
    last_saved: datetime
    is_autosave: bool
    cheats_used: List[str]
    game_state: GameState

    class Config:
        json_encoders = { ObjectId: str }
        allow_population_by_field_name = True

class Scenario(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id")
    name: str
    description: str
    difficulty: str
    map_size: MapSize
    initial_state: Dict[str, Any]

    class Config:
        json_encoders = { ObjectId: str }
        allow_population_by_field_name = True