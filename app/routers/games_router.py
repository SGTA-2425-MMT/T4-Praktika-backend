from fastapi import APIRouter, Depends, HTTPException, status, Path
from typing import Dict, List, Any
from bson import ObjectId
from datetime import datetime
from app.auth import verify_token
from app.db import db
from app.schemas import CheatRequest, GameCreate, GameOut, CheatResponse
from app.services.cheat_handler import handle_cheat
from app.models import Game, GameState

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
    now = datetime.utcnow()
    obj = game.dict()
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
    now = datetime.utcnow()
    update = {
        "$set": {
            "game_state": game_state.dict(),
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
                "game_state": gs.dict(),
                "last_saved": datetime.utcnow()
            }
        }
    )

    # 5) Return updated game state
    updated = await db.games.find_one({"_id": object_id})
    return updated


@router.post("/{game_id}/endTurn", response_model=GameOut, summary="FInish player turn, advance AI, etc.")
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

    # 3) Apply action to game state
    


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
                "last_saved": datetime.utcnow()
            }
        }
    )

    # 5) Return cheat response
    return cheat_res