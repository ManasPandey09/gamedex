import streamlit as st
import httpx
from typing import Dict, Any
import json


class Chatbot:
    def __init__(self, api_url: str):
        self.api_url = api_url
        self.current_tool_call = {"name": None, "args": None}
        self.messages = st.session_state.get("messages", [])

    def display_message(self, message: Dict[str, Any]):
        if not isinstance(message, dict):
            st.warning(f"⚠️ Invalid message (not a dict): {message}")
            return

        role = message.get("role")
        content = message.get("content")

        # 🧍 USER
        if role == "user":
            if isinstance(content, str):
                st.chat_message("user").markdown(content)
            elif isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        st.warning(f"⚠️ Invalid user content item: {item}")
                        continue
                    if item.get("type") == "text":
                        st.chat_message("user").markdown(item.get("text", ""))
                    elif item.get("type") == "tool_result":
                        with st.chat_message("assistant"):
                            st.write(f"Tool result from: {self.current_tool_call['name']}")
                            try:
                                data = item.get("content", [])
                                if data and isinstance(data[0], dict):
                                    text = data[0].get("text", "")
                                    parsed = json.loads(text)
                                    st.json({
                                        "name": self.current_tool_call["name"],
                                        "args": self.current_tool_call["args"],
                                        "content": parsed
                                    }, expanded=False)
                                else:
                                    st.warning("⚠️ Tool result content is not in expected format.")
                            except Exception as e:
                                st.error(f"⚠️ Error parsing tool result: {str(e)}")

        # 🤖 ASSISTANT
        elif role == "assistant":
            if isinstance(content, str):
                st.chat_message("assistant").markdown(content)
            elif isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        st.warning(f"⚠️ Invalid assistant content item: {item}")
                        continue
                    if item.get("type") == "text":
                        st.chat_message("assistant").markdown(item.get("text", ""))
                    elif item.get("type") == "tool_use":
                        self.current_tool_call = {
                            "name": item.get("name"),
                            "args": item.get("input"),
                        }

        else:
            st.warning(f"⚠️ Unknown message format: {message}")

    async def get_tools(self):
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            response = await client.get(
                f"{self.api_url}/tools",
                headers={"Content-Type": "application/json"},
            )
            return response.json()

    async def render(self):
        st.title("🎮 GameDex")

        with st.sidebar:
            st.subheader("Settings")
            st.write("API URL: ", self.api_url)

            if st.button("🧹 Clear Chat"):
                try:
                    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                        await client.post(f"{self.api_url}/reset")

                    # Clear frontend memory
                    st.session_state["messages"] = []
                    self.messages = []
                    st.rerun()
                except Exception as e:
                    st.error(f"⚠️ Failed to reset conversation: {str(e)}")

            try:
                result = await self.get_tools()
                st.subheader("Tools")
                st.write([tool["name"] for tool in result["tools"]])
            except Exception as e:
                st.error(f"⚠️ Failed to fetch tools: {str(e)}")

        # Chat input must be placed first to capture query before rerender
        query = st.chat_input("Enter your query here")

        if query:
            async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
                try:
                    response = await client.post(
                        f"{self.api_url}/query",
                        json={"query": query},
                        headers={"Content-Type": "application/json"},
                    )
                    if response.status_code == 200:
                        data = response.json()

                        # Append new messages properly
                        if isinstance(data, dict) and isinstance(data.get("messages"), list):
                            st.session_state["messages"] += data["messages"]
                        elif isinstance(data, list):
                            st.session_state["messages"] += data
                        else:
                            st.error("⚠️ Unexpected response format.")
                            st.json(data)
                    else:
                        st.error(f"⚠️ API Error: {response.status_code}")
                except Exception as e:
                    st.error(f"Frontend: Error processing query: {str(e)}")

        # Always render current session messages
        self.messages = st.session_state.get("messages", [])
        for message in self.messages:
            self.display_message(message)








