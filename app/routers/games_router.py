from fastapi import APIRouter, Depends, HTTPException, status, Path, Body
from typing import Dict, List, Any, Union
from bson import ObjectId
from datetime import datetime, timezone
from app.auth import get_current_user
from app.db import db
from app.schemas import CheatRequest, GameCreate, GameOut, CheatResponse
from app.services.cheat_handler import handle_cheat
from app.services import ai_agent
from app.models import Game, GameState
from copy import deepcopy
from fastapi.responses import JSONResponse
import random

router = APIRouter(prefix="/api/games", tags=["Games"])

def _get_user_id(current_user: dict) -> str:
    # Usar el ObjectId como string
    return str(current_user["_id"])


def _convert_id(doc):
    if doc and "_id" in doc and not isinstance(doc["_id"], str):
        doc["_id"] = str(doc["_id"])
    return doc


@router.get("", response_model=List[GameOut])
async def list_games(current_user: dict = Depends(get_current_user)):
    user_id = _get_user_id(current_user)
    cursor = db.games.find({"user_id": user_id})
    games: List[Any] = []
    async for doc in cursor:
        games.append(_convert_id(doc))
    return games


@router.post("", response_model=GameOut, status_code=status.HTTP_201_CREATED)
async def create_game(
    game: GameCreate, current_user: dict = Depends(get_current_user)
):
    user_id = _get_user_id(current_user)
    now = datetime.now(timezone.utc)
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
    return _convert_id(created)


@router.get("/{game_id}", response_model=GameOut)
async def get_game(
    game_id: str = Path(..., description="MongoDB ObjectId of the game"),
    current_user: dict = Depends(get_current_user),
):
    objid = ObjectId(game_id)
    game = await db.games.find_one({"_id": objid})
    if not game:
        raise HTTPException(status_code=404, detail="game not found")
    return _convert_id(game)


@router.post("/{game_id}/save", response_model=GameOut)
async def save_game(
    game_state: GameState,
    game_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Persist a manual save.
    """
    objid = ObjectId(game_id)
    now = datetime.now(timezone.utc)
    update = {
        "$set": {
            "game_state": game_state.model_dump(),
            "last_saved": now,
            "is_autosave": False,
        }
    }
    await db.games.update_one({"_id": objid}, update)
    updated = await db.games.find_one({"_id": objid})
    return _convert_id(updated)


@router.post("/{game_id}/action", response_model=GameOut, summary="Apply a player action and return the updated game state")
async def player_action(
    payload: Union[Dict[str, Any], List[Dict[str, Any]]] = Body(...),
    game_id: str = Path(...),
    current_user: dict = Depends(get_current_user),
):
    # 1) Ownership check
    user_id = _get_user_id(current_user)
    object_id = ObjectId(game_id)
    doc = await db.games.find_one({"_id": object_id, "user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="game not found or not owned by user")
    
    # 2) Deserialize game state
    game = Game(**doc)
    gs: GameState = game.game_state

    # 3) Apply action(s) to game state
    # Accept both a single action or a list of actions
    actions = payload if isinstance(payload, list) else [payload]
    errors = []
    gs_new = deepcopy(gs)
    for action in actions:
        t = action.get("type")
        details = action.get("details", {})
        error = None
        if t == "moveUnit":
            unit_id = details.get("unitId")
            dest = details.get("destination")
            if not unit_id or not dest:
                error = f"moveUnit: Missing unitId or destination."
            elif not any(unit.get("id") == unit_id for unit in gs_new.player.units):
                error = f"moveUnit: Unit '{unit_id}' not found."
            else:
                for unit in gs_new.player.units:
                    if unit.get("id") == unit_id:
                        unit["location"] = dest
        elif t == "buildStructure":
            city_id = details.get("cityId")
            structure = details.get("structureType")
            if not city_id or not structure:
                error = f"buildStructure: Missing cityId or structureType."
            elif not any(city.get("id") == city_id for city in gs_new.player.cities):
                error = f"buildStructure: City '{city_id}' not found."
            else:
                for city in gs_new.player.cities:
                    if city.get("id") == city_id:
                        city.setdefault("buildings", []).append(structure)
        elif t == "trainUnit":
            city_id = details.get("cityId")
            unit_type = details.get("unitType")
            quantity = details.get("quantity", 1)
            city = next((c for c in gs_new.player.cities if c.get("id") == city_id), None)
            if not city_id or not unit_type:
                error = f"trainUnit: Missing cityId or unitType."
            elif not city:
                error = f"trainUnit: City '{city_id}' not found."
            else:
                for _ in range(quantity):
                    new_unit = {
                        "id": f"player_unit_{len(gs_new.player.units)+1}",
                        "type": unit_type,
                        "location": city.get("location"),
                        "owner": "player",
                        "movement_points": 2
                    }
                    gs_new.player.units.append(new_unit)
        elif t == "improveResource":
            res_type = details.get("resourceType")
            if not res_type:
                error = f"improveResource: Missing resourceType."
            elif res_type not in gs_new.player.resources:
                error = f"improveResource: Resource '{res_type}' not found."
            else:
                gs_new.player.resources[res_type]["improved"] = True
        elif t == "researchTechnology":
            tech_name = details.get("technology")
            if not tech_name:
                error = f"researchTechnology: Missing technology."
            elif any(t.get("name") == tech_name for t in gs_new.player.technologies):
                error = f"researchTechnology: Technology '{tech_name}' already researched."
            else:
                gs_new.player.technologies.append({"name": tech_name, "turns_remaining": 0})
        elif t == "foundCity":
            city_id = details.get("cityId", f"player_city_{len(gs_new.player.cities)+1}")
            location = details.get("location")
            if not location:
                error = f"foundCity: Missing location."
            elif any(c.get("id") == city_id for c in gs_new.player.cities):
                error = f"foundCity: City '{city_id}' already exists."
            else:
                new_city = {
                    "id": city_id,
                    "name": city_id,
                    "location": location,
                    "buildings": [],
                    "population": 1,
                    "owner": "player"
                }
                gs_new.player.cities.append(new_city)
        elif t == "attackEnemy":
            loc = details.get("location")
            if not loc:
                error = f"attackEnemy: Missing location."
            else:
                before = len(gs_new.ai.units)
                gs_new.ai.units = [
                    u for u in gs_new.ai.units
                    if u.get("location") != loc
                ]
                if len(gs_new.ai.units) == before:
                    error = f"attackEnemy: No AI unit found at location {loc}."
        else:
            error = f"Unknown action type: {t}"
        if error:
            errors.append({"action": t, "details": details, "error": error})

    if errors:
        return JSONResponse(
            status_code=400,
            content={"detail": "One or more actions failed validation.", "errors": errors}
        )

    # 4) Persist updated state & timestamp
    await db.games.update_one(
        {"_id": object_id},
        {
            "$set": {
                "game_state": gs_new.model_dump(),
                "last_saved": datetime.now(timezone.utc)
            }
        }
    )

    # 5) Return updated game state
    updated = await db.games.find_one({"_id": object_id})
    return _convert_id(updated)


@router.post("/{game_id}/endTurn", response_model=GameOut, summary="Finish player turn, advance AI, etc.")
async def end_turn(
    payload: Dict[str, Any],
    game_id: str,
    current_user: dict = Depends(get_current_user),
):
    # 1) Ownership check
    user_id = _get_user_id(current_user)
    object_id = ObjectId(game_id)
    doc = await db.games.find_one({"_id": object_id, "user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="game not found or not owned by user")
    
    # 2) Deserialize game state
    game = Game(**doc)
    gs: GameState = game.game_state

    # --- Update explored area around all player cities before AI turn ---
    for city in gs.player.cities:
        loc = city.get("location")
        if loc and isinstance(loc, dict) and "x" in loc and "y" in loc:
            set_explored_radius(gs.map.explored, (loc["x"], loc["y"]), radius=2)

    # 3) Apply player end turn logic (update state as needed)
    # ...apply any player end turn logic here...

    # 4) Call AI agent to advance AI turn
    ai_result = ai_agent.get_ai_actions(gs)
    print(f"AI actions: {ai_result}")
    ai_actions = []
    if isinstance(ai_result, dict):
        ai_actions_seq = ai_result.get("ai_actions_sequence", [])
        print(f"AI actions sequence: {ai_actions_seq}")
        # Accept both new and old AI action formats
        def safe_merge(a):
            if not a.get("action_type"):
                return None
            entity = a.get("entity") or {}
            path = a.get("path")
            path_dict = path[0] if path and isinstance(path, list) and len(path) > 0 and isinstance(path[0], dict) else {}
            details = {**entity, **path_dict} if entity or path_dict else {}
            return {
                "type": a.get("action_type"),
                "details": details
            }
        ai_actions = [safe_merge(a) for a in ai_actions_seq if a.get("action_type")]
        ai_actions = [a for a in ai_actions if a is not None]
        # If still empty, fallback to actions from ai_result if present
        if not ai_actions and "actions" in ai_result and isinstance(ai_result["actions"], list):
            ai_actions = ai_result["actions"]

    print(f"AI actions after processing: {ai_actions}")

    # If ai_actions is still empty, try to get from raw actions in ai_result
    if not ai_actions and hasattr(ai_result, "get"):
        actions = ai_result.get("actions", [])
        if isinstance(actions, list):
            ai_actions = actions

    print(f"Final AI actions: {ai_actions}")

    # --- Ensure AI actions are applied and saved even if empty ---
    # Always use the updated state after applying AI actions
    gs = apply_ai_actions(gs, ai_actions)

    print(f"Game state after AI actions: {gs}")

    # Increment turn and switch current_player
    gs.turn += 1
    gs.current_player = "player"

    # 5) Persist updated state & timestamp
    await db.games.update_one(
        {"_id": object_id},
        {
            "$set": {
                "game_state": gs.model_dump(),
                "last_saved": datetime.now(timezone.utc),
                "is_autosave": False,
            }
        }
    )

    # 6) Return updated game state
    updated = await db.games.find_one({"_id": object_id})
    return _convert_id(updated)


@router.post("/{game_id}/cheat", response_model=CheatResponse, summary="Apply a cheat code")
async def cheat(
    req: CheatRequest,
    game_id: str,
    current_user: dict = Depends(get_current_user)
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
                "last_saved": datetime.now(timezone.utc),
                "is_autosave": False,
                "cheats_used": game.cheats_used + [req.cheat_code],
            }
        }
    )

    # 5) Return cheat response
    return cheat_res


def find_random_unexplored_tile(explored):
    height = len(explored)
    width = len(explored[0]) if height > 0 else 0
    unexplored = [(x, y) for y in range(height) for x in range(width) if explored[y][x] == 0]
    if unexplored:
        return random.choice(unexplored)
    # fallback: center
    return (width // 2, height // 2)

def set_explored_radius(explored, center, radius=2):
    height = len(explored)
    width = len(explored[0]) if height > 0 else 0
    cx, cy = center
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            x, y = cx + dx, cy + dy
            if 0 <= x < width and 0 <= y < height:
                explored[y][x] = 1

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
            # --- AI city random placement ---
            city_id = details.get("cityId", f"ai_city_{len(gs.ai.cities)+1}")
            location = details.get("location")
            if not location:
                # Place at random unexplored tile
                x, y = find_random_unexplored_tile(gs.map.explored)
                location = {"x": x, "y": y}
            if not city_id:
                city_id = f"ai_city_{len(gs.ai.cities)+1}"
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
            loc = details.get("location")
            if loc:
                gs.player.units = [
                    u for u in gs.player.units
                    if u.get("location") != loc
                ]
        # ...add more action types as needed...
    return gs

def apply_player_actions(gs: GameState, player_actions: list) -> GameState:
    """
    Mutate the GameState in-place according to the player actions.
    Mirrors apply_ai_actions but for the player.
    Handles edge cases gracefully if referenced entities do not exist.
    """
    gs = deepcopy(gs)
    for action in player_actions:
        t = action.get("type")
        details = action.get("details", {})
        if t == "moveUnit":
            unit_id = details.get("unitId")
            dest = details.get("destination")
            if unit_id and dest:
                found = False
                for unit in gs.player.units:
                    if unit.get("id") == unit_id:
                        unit["location"] = dest
                        found = True
                        break
                # Optionally: log or handle if not found
        elif t == "buildStructure":
            city_id = details.get("cityId")
            structure = details.get("structureType")
            if city_id and structure:
                found = False
                for city in gs.player.cities:
                    if city.get("id") == city_id:
                        city.setdefault("buildings", []).append(structure)
                        found = True
                        break
                # Optionally: log or handle if not found
        elif t == "trainUnit":
            city_id = details.get("cityId")
            unit_type = details.get("unitType")
            quantity = details.get("quantity", 1)
            if city_id and unit_type:
                city = next((c for c in gs.player.cities if c.get("id") == city_id), None)
                if city:
                    for _ in range(quantity):
                        new_unit = {
                            "id": f"player_unit_{len(gs.player.units)+1}",
                            "type": unit_type,
                            "location": city.get("location"),
                            "owner": "player",
                            "movement_points": 2
                        }
                        gs.player.units.append(new_unit)
                # Optionally: log or handle if city not found
        elif t == "improveResource":
            res_type = details.get("resourceType")
            if res_type:
                resource = gs.player.resources.get(res_type)
                if resource:
                    resource["improved"] = True
                # Optionally: log or handle if resource not found
        elif t == "researchTechnology":
            tech_name = details.get("technology")
            if tech_name:
                # Avoid duplicate technologies
                if not any(t.get("name") == tech_name for t in gs.player.technologies):
                    gs.player.technologies.append({"name": tech_name, "turns_remaining": 0})
        elif t == "foundCity":
            city_id = details.get("cityId", f"player_city_{len(gs.player.cities)+1}")
            location = details.get("location")
            if location:
                # Avoid duplicate city IDs
                if not any(c.get("id") == city_id for c in gs.player.cities):
                    new_city = {
                        "id": city_id,
                        "name": city_id,
                        "location": location,
                        "buildings": [],
                        "population": 1,
                        "owner": "player"
                    }
                    gs.player.cities.append(new_city)
                    # --- Mark explored radius when first player city is created ---
                    if len(gs.player.cities) == 1:
                        set_explored_radius(gs.map.explored, (location["x"], location["y"]), radius=2)
        elif t == "attackEnemy":
            loc = details.get("location")
            if loc:
                # Remove AI unit at location if exists
                gs.ai.units = [
                    u for u in gs.ai.units
                    if u.get("location") != loc
                ]
        # ...add more action types as needed...
    return gs