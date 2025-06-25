from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
import httpx
import json
import os
from bs4 import BeautifulSoup
load_dotenv()

mcp = FastMCP("docs")

USER_AGENT = "docs-app/1.0"
SERPER_URL = "https://google.serper.dev/search"

docs_urls = {
    "langchain": "python.langchain.com/docs",
    "llama-index": "docs.llamaindex.ai/en/stable",
    "openai": "platform.openai.com/docs",
}

# ---------------- IGDB Setup ----------------
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
IGDB_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
IGDB_GAMES_URL = "https://api.igdb.com/v4/games"

igdb_access_token = None


async def get_igdb_token():
    global igdb_access_token
    if igdb_access_token:
        return igdb_access_token

    async with httpx.AsyncClient() as client:
        response = await client.post(
            IGDB_TOKEN_URL,
            params={
                "client_id": TWITCH_CLIENT_ID,
                "client_secret": TWITCH_CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
            timeout=15,
        )
        response.raise_for_status()
        igdb_access_token = response.json()["access_token"]
        return igdb_access_token


@mcp.tool()
async def search_game_info(game_name: str):
    """
    Get information about a video game from IGDB.

    Args:
        game_name: The name of the game to search for.

    Returns:
        Summary of the game's information.
    """
    token = await get_igdb_token()
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}",
    }
    body = f'search "{game_name}"; fields name,storyline,first_release_date,genres.name,rating,involved_companies.company.name,similar_games.name; limit 1;'

    async with httpx.AsyncClient() as client:
        response = await client.post(
            IGDB_GAMES_URL,
            data=body,
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
        games = response.json()

        if not games:
            return "No game found."

        game = games[0]
        parts = [
            f"🎮 **{game.get('name', 'Unknown')}**",
            f"📅 Released: {game.get('first_release_date', 'N/A')}",
        ]

        if game.get("genres"):
            genres = ", ".join([g["name"] for g in game["genres"]])
            parts.append(f"🎭 Genres: {genres}")

        if game.get("involved_companies"):
            companies = ", ".join([c["company"]["name"] for c in game["involved_companies"]])
            parts.append(f"🏢 Developers: {companies}")

        if game.get("rating"):
            parts.append(f"⭐ Rating: {round(game['rating'], 1)}")

        if game.get("storyline"):
            parts.append(f"\n📝 Storyline: {game['storyline']}")
        
        if game.get("similar_games"):
            similar_games = ", ".join([sg["name"] for sg in game["similar_games"][:3]])
            parts.append(f"\n🔗 Similar Games: {similar_games}")

        return "\n".join(parts)

# ------------- Existing Tools -------------

async def search_web(query: str) -> dict | None:
    payload = json.dumps({"q": query, "num": 2})
    headers = {
        "X-API-KEY": os.getenv("SERPER_API_KEY"),
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(SERPER_URL, headers=headers, data=payload, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            return {"organic": []}


async def fetch_url(url: str):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=30.0)
            soup = BeautifulSoup(response.text, "html.parser")
            text = soup.get_text()
            return text
        except httpx.TimeoutException:
            return "Timeout error"


@mcp.tool()
async def get_docs(query: str, library: str):
    """  Search the latest docs for a given query and library.
  Supports langchain, openai, and llama-index.

  Args:
    query: The query to search for (e.g. "Chroma DB")
    library: The library to search in (e.g. "langchain")

  Returns:
    Text from the docs"""
    if library not in docs_urls:
        raise ValueError(f"Library {library} not supported by this tool")

    query = f"site:{docs_urls[library]} {query}"
    results = await search_web(query)
    if len(results["organic"]) == 0:
        return "No results found"

    text = ""
    for result in results["organic"]:
        text += await fetch_url(result["link"])
    return text


if __name__ == "__main__":
    mcp.run(transport="stdio")
