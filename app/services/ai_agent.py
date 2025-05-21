from typing import Any, Dict, List
from app.config import settings
from app.models import GameState, GameStatePlayer
from groq import Groq
import json
import re
import logging

client = Groq(api_key=settings.GROQ_API_KEY)
logging.basicConfig(level=logging.INFO)

def simplify_game_state(gs: GameState) -> Dict[str, Any]:
    """
    Crea una versión simplificada del estado de juego para reducir los tokens enviados a la API.
    """
    # Para el primer jugador de la IA (o creamos uno vacío si no existe)
    ai_player = gs.ai[0] if gs.ai and len(gs.ai) > 0 else GameStatePlayer(
        cities=[], units=[], technologies=[], resources={}
    )
    
    # Simplificar y eliminar datos innecesarios
    return {
        "turn": gs.turn,
        "current_player": gs.current_player,
        "map": {
            "size": {
                "width": gs.map.size.width,
                "height": gs.map.size.height
            },
            # Mapa de exploración simplificado - sólo cuántas casillas exploradas
            "explored_count": sum(sum(row) for row in gs.map.explored) if gs.map.explored else 0,
        },
        "player": {
            "cities": [
                {
                    "id": city.get("id"),
                    "location": city.get("location"),
                    "buildings": city.get("buildings", [])[:3]  # Limitamos a los 3 primeros edificios
                } for city in gs.player.cities[:5]  # Limitamos a 5 ciudades
            ],
            "units": [
                {
                    "id": unit.get("id"),
                    "type": unit.get("type"),
                    "location": unit.get("location")
                } for unit in gs.player.units[:10]  # Limitamos a 10 unidades
            ],
            "tech_count": len(gs.player.technologies),
            "resources": list(gs.player.resources.keys())  # Solo los nombres de los recursos
        },
        "ai": {
            "cities": [
                {
                    "id": city.get("id"),
                    "location": city.get("location"),
                    "buildings": city.get("buildings", [])
                } for city in ai_player.cities
            ],
            "units": [
                {
                    "id": unit.get("id"),
                    "type": unit.get("type"),
                    "location": unit.get("location")
                } for unit in ai_player.units
            ],
            "tech_count": len(ai_player.technologies),
            "resources": list(ai_player.resources.keys())
        }
    }

def get_ai_actions(gs: GameState, debug: bool = False) -> Dict[str, Any]:
    # Ensure we have at least one AI player
    if not gs.ai or len(gs.ai) == 0:
        # Create a placeholder AI player if none exists
        gs.ai = [GameStatePlayer(cities=[], units=[], technologies=[], resources={})]
    
    # For now, we'll just use the first AI player
    ai_player = gs.ai[0]
    
    # Crear una versión simplificada del estado del juego para reducir tokens
    simplified_state = simplify_game_state(gs)
    
    try:
        completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content":
                        "You're an AI agent playing a turn-based strategy game in the style of Civilization. "
                        "You can only control assets (units, cities, resources, etc.) where the 'owner' field is set to 'ai'. "
                        "If you have no units or cities with owner 'ai', your first action this turn MUST be to create one (using foundCity or trainUnit). "
                        "If you have only a city and no units, train a unit. "
                        "If you have only a unit and no city, found a city. "
                        "Always take at least one meaningful action before endTurn. "
                        "Available actions:"
                        "- moveUnit: {\"type\": \"moveUnit\", \"details\": {\"unitId\": <string>, \"destination\": {\"x\": <int>, \"y\": <int>}}}"
                        "- buildStructure: {\"type\": \"buildStructure\", \"details\": {\"cityId\": <string>, \"structureType\": <string>}}"
                        "- trainUnit: {\"type\": \"trainUnit\", \"details\": {\"cityId\": <string>, \"unitType\": <string>, \"quantity\": <int>}}"
                        "- improveResource: {\"type\": \"improveResource\", \"details\": {\"resourceType\": <string>}}"
                        "- researchTechnology: {\"type\": \"researchTechnology\", \"details\": {\"technology\": <string>}}"
                        "- foundCity: {\"type\": \"foundCity\", \"details\": {\"cityId\": <string>, \"location\": {\"x\": <int>, \"y\": <int>}}}"
                        "- attackEnemy: {\"type\": \"attackEnemy\", \"details\": {\"unitId\": <string>, \"location\": {\"x\": <int>, \"y\": <int>}}}"
                        "- endTurn: {\"type\": \"endTurn\"}"
                        "Return only a JSON with your actions: {\"actions\": [...]}"
                },
                {
                    "role": "user",
                    "content": f"Game state: {json.dumps(simplified_state)}"
                }
            ],
            model="gemma2-9b-it",
            max_tokens=1000  # Limitar la respuesta para evitar errores
        )
        
        # Extract the JSON block from the response
        response = completion.choices[0].message.content
        
    except Exception as e:
        logging.error(f"Error al llamar a la API de Groq: {e}")
        # Fallback en caso de error - crear acciones predeterminadas
        return create_fallback_actions(gs, ai_player)

    # Procesar la respuesta
    try:
        json_match = re.search(r"```json\s*({[^}]*})\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Fallback: try to find the first {...} block
            json_match = re.search(r"({.*})", response, re.DOTALL)
            json_str = json_match.group(1) if json_match else "{}"
        
        ai_json = json.loads(json_str)
    except Exception as e:
        logging.error(f"Error al analizar la respuesta de la IA: {e}")
        return create_fallback_actions(gs, ai_player)

    actions = ai_json.get("actions", [])
    if not actions:
        return create_fallback_actions(gs, ai_player)

    # --- Resto del procesamiento igual que antes ---
    # --- Analyze actions for summary ---
    total_actions = len(actions)
    main_focus = "expansion"
    resources_gained = {"food": 0, "production": 0, "science": 0}
    territories_explored = 0
    combat_results = []

    explored_tiles = set()
    for act in actions:
        t = act.get("type", "")
        details = act.get("details", {})
        if t == "moveUnit":
            dest = details.get("destination")
            if dest and isinstance(dest, dict):
                explored_tiles.add((dest.get("x"), dest.get("y")))
        if t == "improveResource":
            # Example: +1 food/production
            res_type = details.get("resourceType")
            if res_type == "wheat":
                resources_gained["food"] += 2
            elif res_type == "iron":
                resources_gained["production"] += 2
        if t == "researchTechnology":
            resources_gained["science"] += 1
        if t == "attackEnemy":
            loc = details.get("location", {})
            outcome = details.get("outcome", "unknown")
            reward = details.get("reward", None)
            combat_results.append({
                "location": loc,
                "outcome": outcome,
                "reward": reward
            })
        # Heuristic for main_focus
        if t in ("foundCity", "moveUnit"):
            main_focus = "expansion"
        elif t in ("buildStructure", "improveResource"):
            main_focus = "economy"
        elif t == "attackEnemy":
            main_focus = "combat"

    territories_explored = len(explored_tiles)

    # --- Build ai_actions_sequence ---
    ai_actions_sequence = []
    for idx, act in enumerate(actions, 1):
        t = act.get("type", "")
        details = act.get("details", {})
        entity = None
        path = None
        movement_points = None
        # --- Only reference AI's own assets, not player's ---
        if t == "moveUnit":
            # Only allow AI to move its own units
            unit_id = details.get("unitId")
            ai_unit_ids = {u.get("id") for u in ai_player.units}
            if unit_id not in ai_unit_ids:
                continue  # Skip actions targeting non-AI units
            entity = {
                "id": unit_id,
                "name": "Unknown",
                "type": "unit"
            }
            dest = details.get("destination")
            if dest:
                path = [dest]
            movement_points = {"initial": 2, "remaining": 0}
        elif t in ("buildStructure", "trainUnit"):
            city_id = details.get("cityId")
            ai_city_ids = {c.get("id") for c in ai_player.cities}
            if city_id not in ai_city_ids:
                continue
            entity = {
                "id": city_id,
                "name": "Unknown",
                "type": "city"
            }
        elif t == "attackEnemy":
            # AI can attack player units, so allow this
            entity = {
                "id": details.get("unitId", "unknown"),
                "name": "Unknown",
                "type": "unit"
            }
        elif t == "foundCity":
            entity = None  # AI can always found a city
        elif t == "improveResource":
            entity = None  # AI can always improve its own resources
        elif t == "researchTechnology":
            entity = None
        elif t == "endTurn":
            entity = None
        else:
            continue  # Skip unknown or malformed actions

        ai_actions_sequence.append({
            "id": idx,
            "action_type": t,
            "entity": entity,
            "path": path,
            "movement_points": movement_points,
            "state_snapshot_before": {},  # Placeholder
            "state_snapshot_after": {}    # Placeholder
        })

    result = {}
    if (debug):
        result = {
            "ai_turn_summary": {
                "total_actions": total_actions,
                "main_focus": main_focus,
                "resources_gained": resources_gained,
                "territories_explored": territories_explored,
                "combat_results": combat_results
            },
            "ai_actions_sequence": ai_actions_sequence,
            "reasoning": ai_json.get("reasoning", ""),
            "analysis": ai_json.get("analysis", "")
        }
    else:
        result = {
            "ai_turn_summary": {
                "total_actions": total_actions,
                "main_focus": main_focus,
                "resources_gained": resources_gained,
                "territories_explored": territories_explored,
                "combat_results": combat_results
            },
            "ai_actions_sequence": ai_actions_sequence
        }

    return result

def create_fallback_actions(gs: GameState, ai_player: GameStatePlayer) -> Dict[str, Any]:
    """
    Crear acciones de respaldo en caso de error en la API o procesamiento.
    """
    # Determinar acciones básicas según el estado actual de la IA
    actions = []
    
    # Si no hay ciudades, fundar una
    if not ai_player.cities:
        # Buscar una posición para la nueva ciudad
        map_width = gs.map.size.width
        map_height = gs.map.size.height
        center_x, center_y = map_width // 2, map_height // 2
        
        actions.append({
            "type": "foundCity",
            "details": {
                "cityId": "ai_city_1",
                "location": {"x": center_x, "y": center_y}
            }
        })
    # Si hay ciudades pero no unidades, entrenar una unidad
    elif not ai_player.units and ai_player.cities:
        actions.append({
            "type": "trainUnit",
            "details": {
                "cityId": ai_player.cities[0].get("id", "ai_city_1"),
                "unitType": "warrior",
                "quantity": 1
            }
        })
    # Si hay unidades, mover una al azar
    elif ai_player.units:
        unit = ai_player.units[0]
        loc = unit.get("location", {"x": 0, "y": 0})
        new_x = (loc.get("x", 0) + 1) % gs.map.size.width
        new_y = (loc.get("y", 0) + 1) % gs.map.size.height
        
        actions.append({
            "type": "moveUnit",
            "details": {
                "unitId": unit.get("id", "ai_unit_1"),
                "destination": {"x": new_x, "y": new_y}
            }
        })
    
    # Siempre terminar turno
    actions.append({"type": "endTurn", "details": {}})
    
    # Generar resultado básico
    return {
        "ai_turn_summary": {
            "total_actions": len(actions),
            "main_focus": "fallback",
            "resources_gained": {"food": 0, "production": 0, "science": 0},
            "territories_explored": 0,
            "combat_results": []
        },
        "ai_actions_sequence": [
            {
                "id": idx+1,
                "action_type": action["type"],
                "entity": None,
                "path": None,
                "movement_points": None,
                "state_snapshot_before": {},
                "state_snapshot_after": {}
            }
            for idx, action in enumerate(actions)
        ]
    }

if __name__ == "__main__":
    from app.models import GameState, GameStatePlayer, MapSize, GameMap

    you = GameStatePlayer(
        cities=[
            {
                "id": "city1",
                "name": "Alpha",
                "location": {"x": 2, "y": 3},
                "buildings": ["granary"],
                "population": 5,
                "owner": "player1"
            }
        ],
        units=[
            {
                "id": "unit1",
                "type": "warrior",
                "location": {"x": 2, "y": 4},
                "owner": "player1",
                "movement_points": 2
            }
        ],
        technologies=[
            { "name": "Pottery", "turns_remaining": 3 },
            { "name": "Mining", "turns_remaining": 5 }
        ],
        resources={
            "wheat": { "location": {"x": 3, "y": 3}, "improved": False },
            "iron": { "location": {"x": 4, "y": 4}, "improved": True }
        }
    )
    ai = [GameStatePlayer(
        cities=[],
        units=[],
        technologies=[],
        resources={}
    )]

    world_map = GameMap(
        size=MapSize(width=10, height=10),
        explored=[[0] * 10 for _ in range(10)],
        visible_objects=[]
    )

    # Example dummy data for GameState (adjust fields as needed for your model)
    dummy_state = GameState(
        turn=1,
        current_player="player1",
        player=you,
        ai=ai,
        map=world_map
    )

    def test_ai():
        result = get_ai_actions(dummy_state)
        print(result)

    test_ai()