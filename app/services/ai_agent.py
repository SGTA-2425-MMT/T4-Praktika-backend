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

def get_ai_unit_updates(gs: GameState, ai_actions: list) -> dict:
    """
    Dado el estado del juego y las acciones de la IA,
    devuelve los cambios de posición y salud de las unidades de la IA en el formato requerido.
    Si una unidad muere, pone newHealth: 0.
    """
    # Copia profunda para no modificar el estado original
    from copy import deepcopy
    gs_copy = deepcopy(gs)
    ai_player = gs_copy.ai[0] if gs_copy.ai and len(gs_copy.ai) > 0 else None
    if not ai_player:
        return {"unitUpdates": []}

    # Crear un dict para acceso rápido a las unidades por id
    units_by_id = {u["id"]: u for u in ai_player.units}
    # Guardar salud inicial
    initial_health = {u["id"]: u.get("health", 100) for u in ai_player.units}
    # Guardar posición inicial
    initial_pos = {u["id"]: dict(u.get("location", {})) for u in ai_player.units}
    # Unidades muertas
    dead_units = set()

    # Procesar acciones
    for action in ai_actions:
        t = action.get("type")
        details = action.get("details", {})
        if t == "moveUnit":
            unit_id = details.get("unitId")
            dest = details.get("destination")
            if unit_id in units_by_id and dest:
                units_by_id[unit_id]["location"] = dest
        elif t == "attackEnemy":
            unit_id = details.get("unitId")
            # Simulación simple: la unidad IA sobrevive pero pierde 20 de salud, la unidad enemiga muere
            if unit_id in units_by_id:
                prev_health = units_by_id[unit_id].get("health", 100)
                new_health = max(0, prev_health - 20)
                units_by_id[unit_id]["health"] = new_health
                if new_health == 0:
                    dead_units.add(unit_id)
    # Construir la respuesta
    updates = []
    for unit_id, unit in units_by_id.items():
        # Si la unidad murió en este turno
        if unit_id in dead_units:
            updates.append({
                "id": unit_id,
                "newPosition": unit.get("location", initial_pos[unit_id]),
                "newHealth": 0
            })
        else:
            updates.append({
                "id": unit_id,
                "newPosition": unit.get("location", initial_pos[unit_id]),
                "newHealth": unit.get("health", 100)
            })
    return {"unitUpdates": updates}

def get_ai_actions_reduced(players: list) -> list:
    """
    IA avanzada: recibe la lista de jugadores (formato reducido) y utiliza Groq para decidir movimientos y ataques de la IA.
    Solo puede modificar sus propias unidades/ciudades. Analiza posiciones, rangos y ataques según tipo de unidad.
    Devuelve la lista de jugadores actualizada.
    """
    import json
    import re
    # --- Guardar el input original para devolverlo tal cual si la IA falla ---
    original_players = json.loads(json.dumps(players))  # deep copy, sin modificar
    # --- Preprocesado: asegurar que todos los jugadores tienen 'units' y 'cities' ---
    players_fixed = []
    for p in players:
        p_fixed = dict(p)
        if 'units' not in p_fixed:
            p_fixed['units'] = []
        if 'cities' not in p_fixed:
            p_fixed['cities'] = []
        players_fixed.append(p_fixed)
    # Prompt ultraestricto para Groq
    system_prompt = (
        "You are the AI of a turn-based strategy game. You receive a JSON with a list of players, each with all their attributes, cities, and units, in the exact format shown below.\n"
        "\nYou may ONLY modify the values of fields inside the 'units' and 'cities' arrays of AI players (whose id starts with 'rival').\n"
        "You MUST NOT add, remove, rename, or reorder any field, city, or unit.\n"
        "You MUST NOT invent or delete any data.\n"
        "You MUST NOT remove or empty the 'units' or 'cities' arrays of any player.\n"
        "You MUST NOT add or remove units or cities from any player.\n"
        "You MUST NOT modify anything belonging to human players.\n"
        "You MUST NOT modify any field outside of 'units' and 'cities' of AI players.\n"
        "You MUST return EXACTLY the same JSON, with the same structure, the same attributes, and the same order, except for the values of fields inside the units/cities of the AI that you decide to change.\n"
        "If there are no changes, return the exact same input object.\n"
        "DO NOT add explanations, only return the JSON.\n"
        "\nExample input (truncated):\n"
        "{\n  'players': [\n    {\n      'id': 'player1',\n      'cities': [\n        { 'id': '2318', 'name': 'sasasa', ...other attributes... }\n      ],\n      'units': [\n        { 'id': 'warrior_1747924624286', 'name': 'Warrior', ...other attributes... }\n      ],\n      ...other attributes...\n    },\n    {\n      'id': 'rival1',\n      'cities': [\n        { 'id': '3433', 'name': 'Ciudad Civilización 1', ...other attributes... }\n      ],\n      'units': [\n        { 'id': 'warrior_1747924624287', 'name': 'Warrior', ...other attributes... },\n          ...\n      ],\n      ...other attributes...\n    }\n  ]\n}\n"
        "\nExample output (only the 'position' value of a unit of 'rival1' is changed, everything else is identical):\n"
        "{\n  'players': [\n    {\n      'id': 'player1',\n      'cities': [ ...same as input... ],\n      'units': [ ...same as input... ],\n      ...other attributes...\n    },\n    {\n      'id': 'rival1',\n      'cities': [ ...same as input... ],\n      'units': [\n        { 'id': 'warrior_1747924624287', 'name': 'Warrior', ...other attributes..., 'position': { 'x': 35, 'y': 33 } },\n        ...other units same as input...\n      ],\n      ...other attributes...\n    }\n  ]\n}\n"
        "\nDO NOT MODIFY ANY OTHER ATTRIBUTE, DO NOT CHANGE THE ORDER, DO NOT REMOVE OR INVENT FIELDS.\n"
        "NEVER remove or empty the 'units' or 'cities' arrays of any player.\n"
        "ALWAYS return the full JSON, with the exact same structure, and only valid changes to the values of your own units/cities.\n"
    )
    try:
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{json.dumps({'players': players_fixed})}"}
            ],
            model="gemma2-9b-it",
            max_tokens=3000
        )
        response = completion.choices[0].message.content
        # LOG: respuesta bruta de la IA
        logging.info("[AI DEBUG] Respuesta bruta de la IA:\n%s", response)
    except Exception as e:
        logging.error(f"Error calling Groq for strict AI: {e}")
        return {"players": players_fixed}
    # Extraer JSON de la respuesta
    try:
        json_match = re.search(r"```json|```|`|\n|\r", response)
        if json_match:
            # Si detectamos basura, abortamos y devolvemos el input original
            logging.error("Respuesta de la IA contiene basura o delimitadores extraños. Se ignora la respuesta y se devuelve el input original.")
            if not isinstance(original_players, list):
                logging.error("original_players no es una lista, posible corrupción de datos.")
                return {"players": players_fixed}
            return {"players": original_players}
        ai_json = json.loads(response.replace("'", '"'))
        # Puede devolver {"players": [...]}, o solo la lista
        if isinstance(ai_json, dict) and "players" in ai_json:
            result_players = ai_json["players"]
        elif isinstance(ai_json, list):
            result_players = ai_json
        else:
            return {"players": original_players}  # fallback: sin cambios
        # --- SMART MERGE: solo actualiza lo que se puede, nunca cambia la estructura ---
        merged_players = smart_merge_players(original_players, result_players)
        logging.info("[AI DEBUG] Output final al frontend (smart merge):\n%s", json.dumps(merged_players, indent=2, ensure_ascii=False))
        return {"players": merged_players}
    except Exception as e:
        logging.error(f"Error al parsear respuesta Groq IA avanzada reducida: {e}")
        if not isinstance(original_players, list):
            logging.error("original_players no es una lista, posible corrupción de datos.")
            return {"players": players_fixed}
        return {"players": original_players}
def smart_merge_players(original_players, ai_players):
    """
    Dado el input original y la respuesta de la IA (ya parseada y validada como lista),
    recorre cada jugador, ciudad y unidad, y SOLO actualiza los valores de los campos que existen en ambos,
    nunca añade ni elimina nada, y nunca cambia la estructura.
    Si la IA devuelve basura, ignora ese campo y deja el original.
    """
    merged = []
    for orig_p, ai_p in zip(original_players, ai_players):
        merged_p = dict(orig_p)
        # Solo actualizamos units y cities de rivales
        if str(orig_p.get('id', '')).startswith('rival'):
            # --- CITIES ---
            orig_cities = orig_p.get('cities', [])
            ai_cities = ai_p.get('cities', []) if isinstance(ai_p.get('cities', []), list) else []
            merged_cities = []
            for oc, ac in zip(orig_cities, ai_cities):
                mc = dict(oc)
                for k in oc:
                    if k in ac and type(ac[k]) == type(oc[k]):
                        mc[k] = ac[k]
                merged_cities.append(mc)
            merged_p['cities'] = merged_cities
            # --- UNITS ---
            orig_units = orig_p.get('units', [])
            ai_units = ai_p.get('units', []) if isinstance(ai_p.get('units', []), list) else []
            merged_units = []
            for ou, au in zip(orig_units, ai_units):
                mu = dict(ou)
                for k in ou:
                    if k in au and type(au[k]) == type(ou[k]):
                        mu[k] = au[k]
                merged_units.append(mu)
            merged_p['units'] = merged_units
        merged.append(merged_p)
    return merged

# --- JSON de referencia para validación exhaustiva ---
reference_format = {
    "players": [
        {
            "id": "player1",
            "cities": [
                {
                    "id": "2318",
                    "name": "sasasa",
                    "ownerId": "player1",
                    "position": {"x": 23, "y": 18},
                    "population": 1,
                    "maxPopulation": 5,
                    "populationGrowth": 0,
                    "citizens": {
                        "unemployed": 1,
                        "farmers": 0,
                        "workers": 0,
                        "merchants": 0,
                        "scientists": 0,
                        "artists": 0
                    },
                    "food": 6,
                    "foodPerTurn": 1,
                    "foodToGrow": 20,
                    "production": 0,
                    "productionPerTurn": 1,
                    "gold": 0,
                    "goldPerTurn": 1,
                    "science": 0,
                    "sciencePerTurn": 1,
                    "culture": 0,
                    "culturePerTurn": 1,
                    "happiness": 0,
                    "turnsFounded": 1,
                    "era": "ancient",
                    "buildings": [],
                    "workingTiles": [],
                    "defense": 5,
                    "health": 100,
                    "maxHealth": 100,
                    "cultureBorder": 1,
                    "cultureToExpand": 30,
                    "specialists": {
                        "scientists": 0,
                        "merchants": 0,
                        "artists": 0,
                        "engineers": 0
                    },
                    "level": "settlement"
                }
            ],
            "units": [
                {
                    "id": "warrior_1747924624286",
                    "name": "Warrior",
                    "type": "warrior",
                    "owner": "player1",
                    "position": {"x": 23, "y": 16},
                    "turnsToComplete": 0,
                    "cost": 0,
                    "movementPoints": 0,
                    "maxMovementPoints": 2,
                    "strength": 25,
                    "health": 115,
                    "maxHealth": 115,
                    "attacksPerTurn": 1,
                    "maxattacksPerTurn": 1,
                    "isRanged": False,
                    "attackRange": 1,
                    "availableActions": ["move"],
                    "canMove": True,
                    "isFortified": False,
                    "level": 1,
                    "canSwim": False
                }
            ]
        },
        {
            "id": "rival1",
            "cities": [
                {
                    "id": "3433",
                    "name": "Ciudad Civilización 1",
                    "ownerId": "rival1",
                    "position": {"x": 34, "y": 33},
                    "population": 1,
                    "maxPopulation": 5,
                    "populationGrowth": 0,
                    "citizens": {
                        "unemployed": 1,
                        "farmers": 0,
                        "workers": 0,
                        "merchants": 0,
                        "scientists": 0,
                        "artists": 0
                    },
                    "food": 7,
                    "foodPerTurn": 1,
                    "foodToGrow": 20,
                    "production": 0,
                    "productionPerTurn": 1,
                    "gold": 0,
                    "goldPerTurn": 1,
                    "science": 0,
                    "sciencePerTurn": 1,
                    "culture": 0,
                    "culturePerTurn": 1,
                    "happiness": 0,
                    "turnsFounded": 1,
                    "era": "ancient",
                    "buildings": [],
                    "workingTiles": [],
                    "defense": 5,
                    "health": 100,
                    "maxHealth": 100,
                    "cultureBorder": 1,
                    "cultureToExpand": 30,
                    "specialists": {
                        "scientists": 0,
                        "merchants": 0,
                        "artists": 0,
                        "engineers": 0
                    },
                    "level": "settlement"
                }
            ],
            "units": [
                {
                    "id": "warrior_1747924624287",
                    "name": "Warrior",
                    "type": "warrior",
                    "owner": "rival1",
                    "position": {"x": 34, "y": 33},
                    "turnsToComplete": 0,
                    "cost": 0,
                    "movementPoints": 2,
                    "maxMovementPoints": 2,
                    "strength": 25,
                    "health": 115,
                    "maxHealth": 115,
                    "attacksPerTurn": 1,
                    "maxattacksPerTurn": 1,
                    "isRanged": False,
                    "attackRange": 1,
                    "availableActions": ["move", "attack", "retreat"],
                    "canMove": True,
                    "isFortified": False,
                    "level": 1,
                    "canSwim": False
                },
                {
                    "id": "archer_1747924624287",
                    "name": "Archer",
                    "type": "archer",
                    "owner": "rival1",
                    "position": {"x": 34, "y": 33},
                    "turnsToComplete": 0,
                    "cost": 0,
                    "movementPoints": 2,
                    "maxMovementPoints": 2,
                    "strength": 8,
                    "health": 110,
                    "maxHealth": 110,
                    "isRanged": True,
                    "maxRange": 2,
                    "attacksPerTurn": 1,
                    "maxattacksPerTurn": 1,
                    "availableActions": ["move", "attack", "retreat"],
                    "canMove": True,
                    "isFortified": False,
                    "level": 1,
                    "attackRange": 2,
                    "canSwim": False
                }
            ]
        },
        {
            "id": "rival2",
            "cities": [
                {
                    "id": "618",
                    "name": "Ciudad Civilización 2",
                    "ownerId": "rival2",
                    "position": {"x": 6, "y": 18},
                    "population": 1,
                    "maxPopulation": 5,
                    "populationGrowth": 0,
                    "citizens": {
                        "unemployed": 1,
                        "farmers": 0,
                        "workers": 0,
                        "merchants": 0,
                        "scientists": 0,
                        "artists": 0
                    },
                    "food": 7,
                    "foodPerTurn": 1,
                    "foodToGrow": 20,
                    "production": 0,
                    "productionPerTurn": 1,
                    "gold": 0,
                    "goldPerTurn": 1,
                    "science": 0,
                    "sciencePerTurn": 1,
                    "culture": 0,
                    "culturePerTurn": 1,
                    "happiness": 0,
                    "turnsFounded": 1,
                    "era": "ancient",
                    "buildings": [],
                    "workingTiles": [],
                    "defense": 5,
                    "health": 100,
                    "maxHealth": 100,
                    "cultureBorder": 1,
                    "cultureToExpand": 30,
                    "specialists": {
                        "scientists": 0,
                        "merchants": 0,
                        "artists": 0,
                        "engineers": 0
                    },
                    "level": "settlement"
                }
            ],
            "units": [
                {
                    "id": "warrior_1747924624287",
                    "name": "Warrior",
                    "type": "warrior",
                    "owner": "rival2",
                    "position": {"x": 6, "y": 18},
                    "turnsToComplete": 0,
                    "cost": 0,
                    "movementPoints": 2,
                    "maxMovementPoints": 2,
                    "strength": 25,
                    "health": 115,
                    "maxHealth": 115,
                    "attacksPerTurn": 1,
                    "maxattacksPerTurn": 1,
                    "isRanged": False,
                    "attackRange": 1,
                    "availableActions": ["move", "attack", "retreat"],
                    "canMove": True,
                    "isFortified": False,
                    "level": 1,
                    "canSwim": False
                },
                {
                    "id": "archer_1747924624287",
                    "name": "Archer",
                    "type": "archer",
                    "owner": "rival2",
                    "position": {"x": 6, "y": 18},
                    "turnsToComplete": 0,
                    "cost": 0,
                    "movementPoints": 2,
                    "maxMovementPoints": 2,
                    "strength": 8,
                    "health": 110,
                    "maxHealth": 110,
                    "isRanged": True,
                    "maxRange": 2,
                    "attacksPerTurn": 1,
                    "maxattacksPerTurn": 1,
                    "availableActions": ["move", "attack", "retreat"],
                    "canMove": True,
                    "isFortified": False,
                    "level": 1,
                    "attackRange": 2,
                    "canSwim": False
                }
            ]
        },
        {
            "id": "rival3",
            "cities": [
                {
                    "id": "3233",
                    "name": "Ciudad Civilización 3",
                    "ownerId": "rival3",
                    "position": {"x": 32, "y": 33},
                    "population": 1,
                    "maxPopulation": 5,
                    "populationGrowth": 0,
                    "citizens": {
                        "unemployed": 1,
                        "farmers": 0,
                        "workers": 0,
                        "merchants": 0,
                        "scientists": 0,
                        "artists": 0
                    },
                    "food": 7,
                    "foodPerTurn": 1,
                    "foodToGrow": 20,
                    "production": 0,
                    "productionPerTurn": 1,
                    "gold": 0,
                    "goldPerTurn": 1,
                    "science": 0,
                    "sciencePerTurn": 1,
                    "culture": 0,
                    "culturePerTurn": 1,
                    "happiness": 0,
                    "turnsFounded": 1,
                    "era": "ancient",
                    "buildings": [],
                    "workingTiles": [],
                    "defense": 5,
                    "health": 100,
                    "maxHealth": 100,
                    "cultureBorder": 1,
                    "cultureToExpand": 30,
                    "specialists": {
                        "scientists": 0,
                        "merchants": 0,
                        "artists": 0,
                        "engineers": 0
                    },
                    "level": "settlement"
                }
            ],
            "units": [
                {
                    "id": "warrior_1747924624288",
                    "name": "Warrior",
                    "type": "warrior",
                    "owner": "rival3",
                    "position": {"x": 32, "y": 33},
                    "turnsToComplete": 0,
                    "cost": 0,
                    "movementPoints": 2,
                    "maxMovementPoints": 2,
                    "strength": 25,
                    "health": 115,
                    "maxHealth": 115,
                    "attacksPerTurn": 1,
                    "maxattacksPerTurn": 1,
                    "isRanged": False,
                    "attackRange": 1,
                    "availableActions": ["move", "attack", "retreat"],
                    "canMove": True,
                    "isFortified": False,
                    "level": 1,
                    "canSwim": False
                },
                {
                    "id": "archer_1747924624288",
                    "name": "Archer",
                    "type": "archer",
                    "owner": "rival3",
                    "position": {"x": 32, "y": 33},
                    "turnsToComplete": 0,
                    "cost": 0,
                    "movementPoints": 2,
                    "maxMovementPoints": 2,
                    "strength": 8,
                    "health": 110,
                    "maxHealth": 110,
                    "isRanged": True,
                    "maxRange": 2,
                    "attacksPerTurn": 1,
                    "maxattacksPerTurn": 1,
                    "availableActions": ["move", "attack", "retreat"],
                    "canMove": True,
                    "isFortified": False,
                    "level": 1,
                    "attackRange": 2,
                    "canSwim": False
                }
            ]
        }
    ]
}