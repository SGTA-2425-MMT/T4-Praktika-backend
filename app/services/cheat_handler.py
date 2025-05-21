from datetime import datetime
from typing import Any

from app.models import Game
from app.schemas import AffectedEntity, CheatRequest, CheatResponse


async def handle_cheat(game: Game, req: CheatRequest) -> CheatResponse:
    """
    In-process cheat handling. Example: 'level_up' on a city.
    """
    code = req.cheat_code
    targ = req.target
    gs = game.gamesession

    if code == "level_up":
        if targ.type != "city":
            return CheatResponse(
                success=False,
                message="Cheat code 'level_up' can only be used on cities.",
                affected_entity=AffectedEntity(type=targ.type, id=targ.id, changes={}),
                gamesession=gs,
            )
        
        # Find the city in the current player's cities
        for city in gs.player.cities:
            if city.get("id") == targ.id:
                before_pop = city.get("population", 0)
                city["population"] = before_pop + 1

                # Example growth field-increment if present, else start at +1
                before_growth = city.get("growth", 0)
                city["growth"] = before_growth + 1

                changes = {
                    "population": {
                        "before": before_pop,
                        "after": city["population"],
                    },
                    "growth": {
                        "before": before_growth,
                        "after": city["growth"],
                    }
                }
                affected = AffectedEntity(
                    type="city",
                    id=targ.id,
                    changes=changes,
                )

                return CheatResponse(
                    success=True,
                    message="City leveled up successfully.",
                    affected_entity=affected,
                    gamesession=gs
                )
            
            # Unknown city
            return CheatResponse(
                success=False,
                message=f"City '{targ.id}' not found.",
                affected_entity=AffectedEntity(type=targ.type, id=targ.id, changes={}),
                gamesession=gs,
            )
        
    # Unknown cheat code
    return CheatResponse(
        success=False,
        message=f"Unknown cheat code '{code}'.",
        affected_entity=AffectedEntity(type=targ.type, id=targ.id, changes={}),
        gamesession=gs,
    )