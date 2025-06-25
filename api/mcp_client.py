from typing import Optional
from contextlib import AsyncExitStack
import traceback

# from utils.logger import logger
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from datetime import datetime
from utils.logger import logger
import json
import os
from sentence_transformers import SentenceTransformer
from pinecone import Pinecone
from urllib.parse import unquote
import os
from groq import Groq
from dotenv import dotenv_values

# Init clients
env_vars = dotenv_values(".env")
full_env = os.environ.copy()
full_env.update(env_vars)
embedder = SentenceTransformer("all-MiniLM-L6-v2")
pinecone = Pinecone(api_key=env_vars.get("PINECONE_API_KEY"))
index = pinecone.Index("steam-games-index")
groq_client = Groq(api_key=env_vars.get("GROQ_API_KEY"))



class MCPClient:
    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.llm = Groq()
        self.tools = []
        self.messages = []
        self.logger = logger

    # connect to the MCP server
    async def connect_to_server(self, server_script_path: str):
        try:
            is_python = server_script_path.endswith(".py")
            is_js = server_script_path.endswith(".js")
            if not (is_python or is_js):
                raise ValueError("Server script must be a .py or .js file")

            command = "python" if is_python else "node"
            server_params = StdioServerParameters(
                command=command, args=[server_script_path], env=full_env
            )

            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            self.stdio, self.write = stdio_transport
            self.session = await self.exit_stack.enter_async_context(
                ClientSession(self.stdio, self.write)
            )

            await self.session.initialize()

            self.logger.info("Connected to MCP server")

            mcp_tools = await self.get_mcp_tools()
            self.tools = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    }
                }
                for tool in mcp_tools
            ]


            self.logger.info(
                f"Available tools: {[tool['function']['name'] for tool in self.tools]}"
            )


            return True

        except Exception as e:
            self.logger.error(f"Error connecting to MCP server: {e}")
            traceback.print_exc()
            raise

    # get mcp tool list
    async def get_mcp_tools(self):
        try:
            response = await self.session.list_tools()
            return response.tools
        except Exception as e:
            self.logger.error(f"Error getting MCP tools: {e}")
            raise

# Replace your existing process_query with this:
    async def process_query(self, query: str):
        try:
            self.logger.info(f"Processing query: {query}")
            self.messages.append({"role": "user", "content": query})

            # Classification
            classification_response = self.llm.chat.completions.create(
                model="llama3-70b-8192",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a smart assistant router.

    Classify the user's message:
    - "game_info": for any video game questions.
    - "get_docs": for coding, libraries.
    - "general": for general questions.

    Respond in JSON format only.

    Examples:
    {"action": "game_info", "game_name": "Witcher 3", "user_friendly_response": "Here's info about Witcher 3:"}
    {"action": "get_docs", "query": "Streaming API", "library": "openai", "user_friendly_response": "..."}
    {"action": "general", "user_friendly_response": "..."}
    """
                    },
                    {"role": "user", "content": query},
                ],
                max_tokens=150,
            )

            classification_json = classification_response.choices[0].message.content
            try:
                parsed = json.loads(classification_json)
            except Exception as e:
                self.logger.error(f"Failed to parse LLM output: {e}")
                self.logger.error(f"Raw: {classification_json}")
                assistant_reply = "❌ Sorry, I couldn't understand your request."
                self.messages.append({"role": "assistant", "content": assistant_reply})
                return self.messages[-2:]

            action = parsed.get("action")

            if action == "game_info":
                # 🔧 Call IGDB Tool
                igdb_result = await self.session.call_tool("search_game_info", {"game_name": parsed.get("game_name")})
                igdb_text = igdb_result.content[0].text if igdb_result.content else "No IGDB info found."

                # 🔍 RAG with Pinecone
                vector = embedder.encode(query).tolist()
                pinecone_results = index.query(vector=vector, top_k=5, include_metadata=True)
                rag_context = "\n\n".join([match.metadata["text"] for match in pinecone_results.matches]) or "No additional info."

                print("\n🔧 IGDB TOOL RESULT:")
                print(igdb_text)

                print("\n📚 RAG CONTEXT:")
                print(rag_context)                

                # 🧠 Final LLM call
                smart_response = self.llm.chat.completions.create(
                    model="llama3-70b-8192",
                    messages=self.messages + [
                        {
                            "role": "system",
                            "content": "Use the info below to answer user's game question. Combine both IGDB and game database context.",
                        },
                        {"role": "user", "content": f"IGDB Info:\n{igdb_text}\n\nOther Context:\n{rag_context}\n\nQuestion: {query}"}
                    ],
                    max_tokens=700
                )

                final_reply = smart_response.choices[0].message.content
                self.messages.append({"role": "assistant", "content": final_reply})
                return self.messages[-2:]

            elif action == "get_docs":
                # your existing doc lookup logic...
                pass

            else:
                # fallback general LLM chat
                fallback = self.llm.chat.completions.create(
                    model="llama3-70b-8192",
                    messages=self.messages,
                    max_tokens=500,
                )
                reply = fallback.choices[0].message.content
                self.messages.append({"role": "assistant", "content": reply})
                return self.messages[-2:]

        except Exception as e:
            self.logger.error(f"Error processing query: {e}")
            error_msg = {"role": "assistant", "content": "❌ Something went wrong."}
            self.messages.append(error_msg)
            return self.messages[-2:]


    # call llm
    async def call_llm(self):
        try:
            self.logger.info("Calling LLM")
            response = self.llm.chat.completions.create(
                model="llama3-70b-8192",
                max_tokens=1000,
                messages=self.messages,
            )
            return response
        except Exception as e:
            self.logger.error(f"Error calling LLM: {e}")
            raise



    # cleanup
    async def cleanup(self):
        try:
            await self.exit_stack.aclose()
            self.logger.info("Disconnected from MCP server")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            traceback.print_exc()
            raise

    async def log_conversation(self):
        os.makedirs("conversations", exist_ok=True)
        serializable_conversation = []

        for message in self.messages:
            try:
                serializable_message = {"role": message["role"], "content": []}

                content = message["content"]

                # If content is just a string (e.g. user input or assistant reply)
                if isinstance(content, str):
                    serializable_message["content"] = content

                # If content is a list (like tool results)
                elif isinstance(content, list):
                    for item in content:
                        if hasattr(item, "model_dump"):
                            serializable_message["content"].append(item.model_dump())
                        else:
                            serializable_message["content"].append(item)

                # If content is a Pydantic object like `ChatCompletionMessage`
                elif hasattr(content, "model_dump"):
                    serializable_message["content"] = content.model_dump()

                else:
                    serializable_message["content"] = content  # fallback

                serializable_conversation.append(serializable_message)

            except Exception as e:
                self.logger.error(f"Error processing message for logging: {e}")
                self.logger.debug(f"Message content: {message}")
                raise

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filepath = os.path.join("conversations", f"conversation_{timestamp}.json")

        try:
            with open(filepath, "w") as f:
                json.dump(serializable_conversation, f, indent=2, default=str)
        except Exception as e:
            self.logger.error(f"Error writing conversation to file: {e}")
            self.logger.debug(f"Conversation data: {serializable_conversation}")
            raise
