import httpx
from typing import Any, Dict, List
from app.config import settings
from app.models import GameState
from groq import Groq

client = Groq(api_key=settings.GROQ_API_KEY)


async def get_ai_actions(gs: GameState) -> List[Dict[str, Any]]:
    client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "Given the following game state:\n"+
                f"<game_state>\n{gs.model_dump_json()}\n</game_state>\n\n"+
                "You're an AI agent in a Civilizations-like game. Your task is to suggest actions for the AI player. "+
                "You'll receive the game state in a structured format. "+
                "1. Analyze the game state.\n"+
                "2. Suggest a list of actions the AI player can take, based on the following priorities:\n"+
                
                "Please provide a list of suggested actions based on the current game state."
            }
        ],
        model="gemma2-9b-it"
    )