from fastapi import APIRouter, Depends, HTTPException, status, Path
from typing import Dict, List, Any
from bson import ObjectId
from datetime import datetime
from app.auth import verify_token
from app.db import db
from app.schemas import CheatRequest, GameCreate, GameOut, CheatResponse
from app.services.cheat_handler import handle_cheat
from app.services import ai_agent
from app.models import Game, GameState
from copy import deepcopy

router = APIRouter(prefix="/api/games", tags=["Games"])

def _get_user_objid(claims: dict) -> ObjectId:
    return ObjectId(claims["sub"])


@router.get("", response_model=List[GameOut])
async def list_games(claims: dict = Depends(verify_token)):
    user_id = _get_user_objid(claims)
    cursor = db.games.find({"user_id": user_id})
    games: List[Any] = []
    async for doc in cursor:
        games.append(doc)
    return games


@router.post("", response_model=GameOut, status_code=status.HTTP_201_CREATED)
async def create_game(
    game: GameCreate, claims: dict = Depends(verify_token)
):
    user_id = _get_user_objid(claims)
    now = datetime.now(datetime.timezone.utc)
    obj = game.model_dump()
    obj.update(
        {
            "user_id": user_id,
            "created_at": now,
            "last_saved": now,
            "is_autosave": False,
            "cheats_used": [],
        }
    )
    res = await db.games.insert_one(obj)
    created = await db.games.find_one({"_id": res.inserted_id})
    return created


@router.get("/{game_id}", response_model=GameOut)
async def get_game(
    game_id: str = Path(..., description="MongoDB ObjectId of the game"),
    claims: dict = Depends(verify_token),
):
    objid = ObjectId(game_id)
    game = await db.games.find_one({"_id": objid})
    if not game:
        raise HTTPException(status_code=404, detail="game not found")
    return game


@router.post("/{game_id}/save", response_model=GameOut)
async def save_game(
    game_state: GameState,
    game_id: str,
    claims: dict = Depends(verify_token),
):
    """
    Persist a manual save.
    """
    objid = ObjectId(game_id)
    now = datetime.now(datetime.timezone.utc)
    update = {
        "$set": {
            "game_state": game_state.model_dump(),
            "last_saved": now,
            "is_autosave": False,
        }
    }
    await db.games.update_one({"_id": objid}, update)
    updated = await db.games.find_one({"_id": objid})
    return updated


@router.post("/{game_id}/action", response_model=GameOut, summary="Apply a player action and return the updated game state")
async def player_action(
    payload: Dict[str, Any],
    game_id: str,
    claims: dict = Depends(verify_token),
):
    # 1) Ownership check
    user_id = _get_user_objid(claims)
    object_id = ObjectId(game_id)
    doc = await db.games.find_one({"_id": object_id, "user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="game not found or not owned by user")
    
    # 2) Deserialize game state
    game = Game(**doc)
    gs: GameState = game.game_state

    # 3) Apply action to game state
    # TODO: implement action handling
    # gs = await handle_action(gs, payload)

    # For now, just return the game state as is
    # 4) Persist updated state & timestamp
    await db.games.update_one(
        {"_id": object_id},
        {
            "$set": {
                "game_state": gs.model_dump(),
                "last_saved": datetime.now(datetime.timezone.utc)
            }
        }
    )

    # 5) Return updated game state
    updated = await db.games.find_one({"_id": object_id})
    return updated


@router.post("/{game_id}/endTurn", response_model=GameOut, summary="Finish player turn, advance AI, etc.")
async def end_turn(
    payload: Dict[str, Any],
    game_id: str,
    claims: dict = Depends(verify_token),
):
    # 1) Ownership check
    user_id = _get_user_objid(claims)
    object_id = ObjectId(game_id)
    doc = await db.games.find_one({"_id": object_id, "user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="game not found or not owned by user")
    
    # 2) Deserialize game state
    game = Game(**doc)
    gs: GameState = game.game_state

    # 3) Apply player end turn logic (update state as needed)
    # ...apply any player end turn logic here...

    # 4) Call AI agent to advance AI turn
    ai_result = ai_agent.get_ai_actions(gs)
    ai_actions = []
    if isinstance(ai_result, dict):
        ai_actions = ai_result.get("ai_actions_sequence", [])
        # Convert to action format expected by apply_ai_actions
        ai_actions = [
            {
                "type": a.get("action_type"),
                "details": a.get("entity", {}) | (a.get("path", [{}])[0] if a.get("path") else {})
            } if a.get("action_type") else {}
            for a in ai_actions
        ]
        # If empty, fallback to actions from ai_result if present
        if not ai_actions and "actions" in ai_result:
            ai_actions = ai_result["actions"]

    # If ai_actions is still empty, try to get from raw actions in ai_result
    if not ai_actions and hasattr(ai_result, "get"):
        ai_actions = ai_result.get("actions", [])

    # Apply AI actions to the game state
    gs = apply_ai_actions(gs, ai_actions)

    # Increment turn and switch current_player
    gs.turn += 1
    gs.current_player = "player"

    # 5) Persist updated state & timestamp
    await db.games.update_one(
        {"_id": object_id},
        {
            "$set": {
                "game_state": gs.model_dump(),
                "last_saved": datetime.now(datetime.timezone.utc),
                "is_autosave": False,
            }
        }
    )

    # 6) Return updated game state
    updated = await db.games.find_one({"_id": object_id})
    return updated


@router.post("/{game_id}/cheat", response_model=CheatResponse, summary="Apply a cheat code")
async def cheat(
    req: CheatRequest,
    game_id: str,
    claims: dict = Depends(verify_token)
):
    
    """
    Apply a developer cheat (e.g. "level_up") directly to the game state.
    """
    # 1) Validate path <-> body game_id
    if req.game_id != game_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path and body game_id must match."
        )
    
    # 2) Load game
    object_id = ObjectId(game_id)
    doc = await db.games.find_one({"_id": object_id})
    if not doc:
        raise HTTPException(status_code=404, detail="game not found")
    game = Game(**doc)

    # 3) Apply cheat
    cheat_res = await handle_cheat(game, req)

    # 4) Persist updated state & timestamp
    await db.games.update_one(
        {"_id": object_id},
        {
            "$set": {
                "game_state": cheat_res.game_state.dict(),
                "last_saved": datetime.now(datetime.timezone.utc),
                "is_autosave": False,
                "cheats_used": game.cheats_used + [req.cheat_code],
            }
        }
    )

    # 5) Return cheat response
    return cheat_res


def apply_ai_actions(gs: GameState, ai_actions: list) -> GameState:
    """
    Mutate the GameState in-place according to the AI actions.
    Only basic logic for demonstration; extend as needed.
    """
    gs = deepcopy(gs)
    for action in ai_actions:
        t = action.get("type")
        details = action.get("details", {})
        if t == "moveUnit":
            unit_id = details.get("unitId")
            dest = details.get("destination")
            for unit in gs.ai.units:
                if unit.get("id") == unit_id and dest:
                    unit["location"] = dest
        elif t == "buildStructure":
            city_id = details.get("cityId")
            structure = details.get("structureType")
            for city in gs.ai.cities:
                if city.get("id") == city_id and structure:
                    city.setdefault("buildings", []).append(structure)
        elif t == "trainUnit":
            city_id = details.get("cityId")
            unit_type = details.get("unitType")
            quantity = details.get("quantity", 1)
            for city in gs.ai.cities:
                if city.get("id") == city_id and unit_type:
                    for _ in range(quantity):
                        new_unit = {
                            "id": f"ai_unit_{len(gs.ai.units)+1}",
                            "type": unit_type,
                            "location": city.get("location"),
                            "owner": "ai",
                            "movement_points": 2
                        }
                        gs.ai.units.append(new_unit)
        elif t == "improveResource":
            res_type = details.get("resourceType")
            for res_name, res in gs.ai.resources.items():
                if res_name == res_type:
                    res["improved"] = True
        elif t == "researchTechnology":
            tech_name = details.get("technology")
            if tech_name:
                gs.ai.technologies.append({"name": tech_name, "turns_remaining": 0})
        elif t == "foundCity":
            city_id = details.get("cityId", f"ai_city_{len(gs.ai.cities)+1}")
            location = details.get("location")
            if location:
                new_city = {
                    "id": city_id,
                    "name": city_id,
                    "location": location,
                    "buildings": [],
                    "population": 1,
                    "owner": "ai"
                }
                gs.ai.cities.append(new_city)
        elif t == "attackEnemy":
            # For demo: remove player unit at location if exists
            loc = details.get("location")
            if loc:
                gs.player.units = [
                    u for u in gs.player.units
                    if u.get("location") != loc
                ]
        # ...add more action types as needed...
    return gs