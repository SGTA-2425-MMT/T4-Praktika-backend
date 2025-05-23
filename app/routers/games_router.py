from fastapi import APIRouter, Depends, HTTPException, status, Path, Body
from typing import Dict, List, Any, Union
from bson import ObjectId
from datetime import datetime, timezone
import logging
from app.auth import get_current_user
from app.db import db
from app.schemas import CheatRequest, GameCreate, GameOut, CheatResponse
from app.services.cheat_handler import handle_cheat
from app.services import ai_agent
from app.models import Game, GameState, GameStatePlayer
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


from pydantic import BaseModel

class GameSessionUpdate(BaseModel):
    gamesession: str

@router.post("/{game_id}/save", response_model=GameOut)
async def save_game(
    body: GameSessionUpdate,
    game_id: str,
    current_user: dict = Depends(get_current_user),
):
    objid = ObjectId(game_id)
    now = datetime.now(timezone.utc)

    # Validar y normalizar gamesession antes de guardar
    update = {
        "$set": {
            "gamesession": body.gamesession,
            "last_saved": now,
            "is_autosave": False,
        }
    }
    await db.games.update_one({"_id": objid}, update)
    updated = await db.games.find_one({"_id": objid})
    return _convert_id(updated)


@router.post("/{game_id}/action", response_model=GameOut, summary="Apply player action to game state")
async def apply_action(
    payload: Dict[str, Any],
    game_id: str,
    current_user: dict = Depends(get_current_user),
):
    user_id = _get_user_id(current_user)
    from bson import ObjectId
    doc = None
    object_id = None
    if ObjectId.is_valid(game_id):
        object_id = ObjectId(game_id)
        doc = await db.games.find_one({"_id": object_id, "user_id": user_id})
    if not doc:
        doc = await db.games.find_one({"name": game_id})
    if not doc:
        doc = await db.games.find_one({"scenario_id": game_id})
    if not doc:
        raise HTTPException(status_code=404, detail="game not found or not owned by user")
    if not object_id and doc.get("_id"):
        object_id = doc["_id"]

    # gamesession puede venir en el payload o en el doc
    import json
    gs_data = None
    if "gamesession" in payload:
        gs_raw = payload["gamesession"]
    elif hasattr(doc, "gamesession"):
        gs_raw = doc["gamesession"]
    else:
        gs_raw = None
    if gs_raw is None:
        raise HTTPException(status_code=400, detail="No se proporcionó gamesession en el payload ni en la base de datos")
    if isinstance(gs_raw, str):
        try:
            gs_data = json.loads(gs_raw)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"gamesession no es un JSON válido: {str(e)}")
    else:
        gs_data = gs_raw
    if isinstance(gs_data, dict) and "gamesession" in gs_data:
        gs_data = gs_data["gamesession"]
    required_fields = ["current_player", "player", "ai", "map"]
    missing = [f for f in required_fields if f not in gs_data]
    if missing:
        raise HTTPException(status_code=400, detail=f"gamesession no tiene la estructura GameState esperada. Faltan campos: {missing}")
    try:
        gs = GameState(**gs_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"gamesession no tiene la estructura GameState válida: {str(e)}")

    # Aplicar acción del jugador
    action = payload.get("action")
    if not action:
        raise HTTPException(status_code=400, detail="No se proporcionó acción a aplicar")
    try:
        gs = apply_player_actions(gs, [action])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error aplicando acción: {str(e)}")

    # Guardar el nuevo estado
    await db.games.update_one(
        {"_id": object_id},
        {
            "$set": {
                "gamesession": gs.model_dump(),
                "last_saved": datetime.now(timezone.utc),
                "is_autosave": False,
            }
        }
    )
    updated = await db.games.find_one({"_id": object_id})
    return _convert_id(updated)


@router.post("/{game_id}/endTurn", summary="Procesa el final de turno solo con ciudades y unidades", response_model=Dict[str, Any])
async def end_turn_minimal(
    payload: Dict[str, Any],
    game_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Recibe solo las ciudades y unidades agrupadas por jugador/IA, ejecuta la lógica de IA y de final de turno,
    y devuelve solo las ciudades y unidades actualizadas en el mismo formato reducido.
    """
    # Validar formato de entrada
    players = payload.get("players")
    if not players or not isinstance(players, list):
        raise HTTPException(status_code=400, detail="El payload debe contener una lista 'players'.")

    # Aquí puedes aplicar la lógica de final de turno y de IA sobre players
    from app.services.ai_agent import get_ai_actions_reduced
    updated_players = get_ai_actions_reduced(players)
    return {"players": updated_players}


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
                "gamesession": cheat_res.gamesession,
                "last_saved": datetime.now(timezone.utc),
                "is_autosave": False,
                "cheats_used": game.cheats_used + [req.cheat_code],
            }
        }
    )

    # 5) Return cheat response
    return cheat_res


@router.delete("/{game_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a game")
async def delete_game(
    game_id: str = Path(..., description="ID of the game to delete (either MongoDB ObjectId or custom ID)"),
    current_user: dict = Depends(get_current_user),
):
    """
    Delete a game by its ID.
    
    - Removes the game from the database
    - Returns a 204 No Content on success
    """
    try:
        # Intentamos buscar el juego por varios criterios posibles
        game = None
        
        # 1. Intenta buscar primero por ObjectId (si es un formato válido)
        if ObjectId.is_valid(game_id):
            objid = ObjectId(game_id)
            game = await db.games.find_one({"_id": objid})
        
        # 2. Si no se encuentra, intenta buscar por el ID proporcionado como un campo directo
        if game is None:
            # Podría estar almacenado en scenario_id o ser un formato personalizado
            game = await db.games.find_one({"scenario_id": game_id})
        
        # 3. Si aún no se encuentra, intenta buscar en el campo "name" (también podría usarse como ID)
        if game is None:
            game = await db.games.find_one({"name": game_id})
            
        # 4. Busca en el campo gamesession, ya que el ID podría estar almacenado como JSON dentro de este campo
        if game is None:
            # Usando una expresión regular para buscar el ID dentro del campo gamesession
            # Esto busca juegos donde el campo gamesession contiene el id específico
            import json
            import re
            # Primero intentamos buscar si el ID está almacenado como parte del JSON en gamesession
            cursor = db.games.find({"gamesession": {"$regex": game_id}})
            async for doc in cursor:
                # Si encontramos coincidencia, verificamos si realmente el ID está en el campo correcto
                try:
                    # El campo gamesession puede ser un string JSON o un diccionario
                    if isinstance(doc["gamesession"], str):
                        gamesession_data = json.loads(doc["gamesession"])
                    else:
                        gamesession_data = doc["gamesession"]
                    
                    # Si el ID coincide con el que buscamos, hemos encontrado el juego
                    if gamesession_data.get("id") == game_id:
                        game = doc
                        break
                except (json.JSONDecodeError, KeyError, AttributeError):
                    continue
        
        # Si aún no hemos encontrado el juego, devolvemos un error 404
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        
        # Borrar el juego usando su _id real
        delete_result = await db.games.delete_one({"_id": game["_id"]})
        
        if delete_result.deleted_count == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                detail="Game could not be deleted"
            )
        
        # Return 204 No Content (successful deletion)
        return None
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        # Proporciona un mensaje de error más descriptivo sobre el problema específico
        if "Invalid ObjectId" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El ID proporcionado no es un formato válido: {game_id}"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error al intentar eliminar el juego: {str(e)}"
        )


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
    Now supports multiple AI players.
    """
    gs = deepcopy(gs)
    
    # Initialize with first AI player if it exists, otherwise create one
    if not gs.ai or len(gs.ai) == 0:
        gs.ai = [GameStatePlayer(cities=[], units=[], technologies=[], resources={})]
    
    # For now, we're just processing actions for the first AI player (index 0)
    ai_player = gs.ai[0]
    
    for action in ai_actions:
        t = action.get("type")
        details = action.get("details", {})
        if t == "moveUnit":
            unit_id = details.get("unitId")
            dest = details.get("destination")
            for unit in ai_player.units:
                if unit.get("id") == unit_id and dest:
                    unit["location"] = dest
        elif t == "buildStructure":
            city_id = details.get("cityId")
            structure = details.get("structureType")
            for city in ai_player.cities:
                if city.get("id") == city_id and structure:
                    city.setdefault("buildings", []).append(structure)
        elif t == "trainUnit":
            city_id = details.get("cityId")
            unit_type = details.get("unitType")
            quantity = details.get("quantity", 1)
            for city in ai_player.cities:
                if city.get("id") == city_id and unit_type:
                    for _ in range(quantity):
                        new_unit = {
                            "id": f"ai_unit_{len(ai_player.units)+1}",
                            "type": unit_type,
                            "location": city.get("location"),
                            "owner": "ai",
                            "movement_points": 2
                        }
                        ai_player.units.append(new_unit)
        elif t == "improveResource":
            res_type = details.get("resourceType")
            for res_name, res in ai_player.resources.items():
                if res_name == res_type:
                    res["improved"] = True
        elif t == "researchTechnology":
            tech_name = details.get("technology")
            if tech_name:
                ai_player.technologies.append({"name": tech_name, "turns_remaining": 0})
        elif t == "foundCity":
            # --- AI city random placement ---
            city_id = details.get("cityId", f"ai_city_{len(ai_player.cities)+1}")
            location = details.get("location")
            if not location:
                # Place at random unexplored tile
                x, y = find_random_unexplored_tile(gs.map.explored)
                location = {"x": x, "y": y}
            if not city_id:
                city_id = f"ai_city_{len(ai_player.cities)+1}"
            new_city = {
                "id": city_id,
                "name": city_id,
                "location": location,
                "buildings": [],
                "population": 1,
                "owner": "ai"
            }
            ai_player.cities.append(new_city)
        elif t == "attackEnemy":
            loc = details.get("location")
            if loc:
                gs.player.units = [
                    u for u in gs.player.units
                    if u.get("location") != loc
                ]
        # ...add more action types as needed...
    
    # Update the AI player in the list
    gs.ai[0] = ai_player
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
                if not found:
                    logging.warning(f"Unit {unit_id} not found.")
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
            if loc and gs.ai and len(gs.ai) > 0:
                # Iterar sobre todos los jugadores IA y eliminar unidades en esa ubicación
                for ai_idx, ai_player in enumerate(gs.ai):
                    ai_player.units = [
                        u for u in ai_player.units
                        if u.get("location") != loc
                    ]
                    gs.ai[ai_idx] = ai_player
        # ...add more action types as needed...
    return gs

@router.post("/{game_id}/endTurn/ai-units", summary="Devuelve los cambios de posición y salud de las unidades IA tras el turno")
async def end_turn_ai_units(
    payload: Dict[str, Any],
    game_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Endpoint auxiliar para devolver los cambios de las unidades IA tras el turno, en el formato solicitado por el frontend.
    """
    user_id = _get_user_id(current_user)
    object_id = ObjectId(game_id)
    doc = await db.games.find_one({"_id": object_id, "user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="game not found or not owned by user")
    game = Game(**doc)
    gs = game.gamesession if hasattr(game, "gamesession") else game.game_state

    # Obtener acciones IA usando el formato reducido (players)
    # Extraer el formato reducido desde gamesession si es string
    import json
    players = None
    if isinstance(gs, str):
        try:
            gs_data = json.loads(gs)
            if isinstance(gs_data, dict) and "players" in gs_data:
                players = gs_data["players"]
            elif isinstance(gs_data, list):
                players = gs_data
        except Exception:
            players = None
    elif isinstance(gs, dict) and "players" in gs:
        players = gs["players"]
    if not players:
        raise HTTPException(status_code=400, detail="No se pudo extraer el formato reducido de players del gamesession para IA.")

    updated_players = ai_agent.get_ai_actions_reduced(players)
    # Si quieres devolver solo los cambios de unidades IA, puedes filtrar aquí
    return {"players": updated_players}