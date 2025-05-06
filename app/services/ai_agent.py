from typing import Any, Dict, List
from app.config import settings
from app.models import GameState
from groq import Groq
import json
import re

client = Groq(api_key=settings.GROQ_API_KEY)


def get_ai_actions(gs: GameState) -> Dict[str, Any]:
    completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "You're an AI agent playing a turn-based strategy game in the style of Civilization. Your goal is to expand your empire, conquer cities, gather resources, and defeat your opponent. You will receive the game state and decide your actions for this turn."+
                "Your task is to analyze the game state, formulate a strategy, and specify your actions for the current turn.\nFollow these steps:\n"+
                "1. Analyze the game state, considering the following:\n"+
                "   - The location, condition, and buildings of your cities\n"+
                "   - The position and abilities of your units\n"+
                "   - The available resources and income\n"+
                "   - The explored areas of the map\n"+
                "   - The known locations and strengths of your enemies\n"+
                "   - Nearby opportunities (resources, barbarian camps, technologies, etc.)\n"+
                "   - Fog of war (unexplored areas of the map)\n"+
                "2. Formulate a strategy based on the following priorities:\n"+
                "   - Exploration to find resources and cities\n"+
                "   - Securing income sources\n"+
                "   - City development to recruit stronger units\n"+
                "   - Technological advancements to gain advantages\n"+
                "   - Balancing economy and military power\n"+
                "3. Create a set of actions for this turn. You can perform multiple actions until you run out of movement points. Possible action types are:\n"+
                "   - moveUnit: Move a unit to a new location.\n"+
                "   - buildStructure: Build a structure in a city.\n"+
                "   - trainUnit: Train a new unit in a city.\n"+
                "   - improveResource: Improve a resource tile.\n"+
                "   - attackEnemy: Start a battle with an enemy unit.\n"+
                "   - researchTechnology: Research a new technology.\n"+
                "   - foundCity: Found a new city.\n"+
                "Before providing your final response, write down your thought process and strategic considerations between the <strategic_planning> tags. In this section:\n"+
                "1. Summarize the current game state, including the cities' locations, resources, and known information about the enemy.\n"+
                "2. List potential opportunities and threats.\n"+
                "3. Prioritize goals based on the current situation.\n"+
                "4. Explain your short-term (this turn) and long-term (next turns) strategy.\n"+
                "This section can be quite detailed, as a deep strategy is essential for success in the game.\n"+
                "Your final response should be in the following JSON format:\n"+
                "```json\n"+
                "{\n"+
                "  \"actions\": [\n"+
                "    {\n"+
                "      \"type\": \"moveUnit\",\n"+
                "      \"details\": {\n"+
                "        // Details for the action"+
                "      }\n"+
                "    },\n"+
                "      // More actions can be added here"+
                "    {\n"+
                "      \"type\": \"endTurn\",\n"+
                "    }\n"+
                "  ],\n"+
                "  \"reasoning\": \"A detailed explanation of your strategy and plans for the next turns\",\n"+
                "  \"analysis\": \"A brief analysis of the game state and the opponent's position\"\n"+
                "}\n"+
                "Here is an example of the actions format:\n"+
                "```json\n"+
                "{\n"+
                "  \"actions\": [\n"+
                "    {\n"+
                "      \"type\": \"moveUnit\",\n"+
                "      \"details\": {\n"+
                "        \"unitId\": \"unit1\",\n"+
                "        \"destination\": {\"x\": 5, \"y\": 3},\n"+
                "      }\n"+
                "    },\n"+
                "    {\n"+
                "      \"type\": \"buildStructure\",\n"+
                "      \"details\": {\n"+
                "        \"cityId\": \"city1\",\n"+
                "        \"structureType\": \"granary\"\n"+
                "      }\n"+
                "    },\n"+
                "    {\n"+
                "      \"type\": \"trainUnit\"\n"+
                "      \"details\": {\n"+
                "        \"cityId\": \"city1\",\n"+
                "        \"unitType\": \"warrior\"\n"+
                "        \"quantity\": 1\n"+
                "      }\n"+
                "    },\n"+
                "    {\n"+
                "      \"type\": \"endTurn\"\n"+
                "    }\n"+
                "  ],\n"+
                "  \"reasoning\": \"I will move my unit to explore the nearby area and build a granary in my city to increase food production. I will also train a warrior for defense.\",\n"+
                "  \"analysis\": \"The enemy is located to the north, and I need to secure my borders while expanding my territory.\"\n"+
                "}\n"+
                "Keep in mind:\n"+
                "- Think strategically and plan for the long term.\n"+
                "- Manage your resources efficiently.\n"+
                "- Adapt your strategy to the game state, including unexplored areas due to fog of war.\n"+
                "- Balance economic development and military strength.\n"+
                "- Exploit your strengths and your opponent's weaknesses.\n"+
                "- Always end your turn with an 'endTurn' action.\n"+
                "- Provide a clear explanation of your decisions.\n"+
                "- Stay within the rules and mechanics of the game.\n"+
                "Now, based on the provided game state, analyze the situation, formulate your strategy, and create your actions, reasoning, and analysis for this turn."
            },
            {
                "role": "user",
                "content": f"<game_state>\n{gs.model_dump_json()}\n</game_state>"
            }
        ],
        model="gemma2-9b-it"
    )

    # Extract the JSON block from the response
    response = completion.choices[0].message.content

    # Try to extract the first JSON code block
    import logging
    logging.basicConfig(level=logging.ERROR)

    try:
        json_match = re.search(r"```json\s*({[^}]*})\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Fallback: try to find the first {...} block
            json_match = re.search(r"({.*})", response, re.DOTALL)
            json_str = json_match.group(1) if json_match else "{}"
    except Exception as e:
        logging.error(f"Error extracting JSON from response: {e}")
        json_str = "{}"
    if json_match:
        json_str = json_match.group(1)
    else:
        # Fallback: try to find the first {...} block
        json_match = re.search(r"({.*})", response, re.DOTALL)
        json_str = json_match.group(1) if json_match else "{}"

    try:
        ai_json = json.loads(json_str)
    except Exception:
        ai_json = {}

    actions = ai_json.get("actions", [])
    reasoning = ai_json.get("reasoning", "")
    analysis = ai_json.get("analysis", "")

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
        if t == "moveUnit":
            entity = {
                "id": details.get("unitId"),
                "name": "Unknown",
                "type": "unit"
            }
            dest = details.get("destination")
            if dest:
                path = [dest]
            movement_points = {"initial": 2, "remaining": 0}
        elif t == "buildStructure":
            entity = {
                "id": details.get("cityId"),
                "name": "Unknown",
                "type": "city"
            }
        elif t == "trainUnit":
            entity = {
                "id": details.get("cityId"),
                "name": "Unknown",
                "type": "city"
            }
        elif t == "attackEnemy":
            entity = {
                "id": details.get("unitId", "unknown"),
                "name": "Unknown",
                "type": "unit"
            }
        # ...other action types...

        ai_actions_sequence.append({
            "id": idx,
            "action_type": t,
            "entity": entity,
            "path": path,
            "movement_points": movement_points,
            "state_snapshot_before": {},  # Placeholder
            "state_snapshot_after": {}    # Placeholder
        })

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
    ai = GameStatePlayer(
        cities=[],
        units=[],
        technologies=[],
        resources={}
    )

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