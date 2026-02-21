"""
Jarvis v2 Brain
LLM-powered decision maker with:
- Persistent conversation threading
- Approval gates for risky tool calls
- Semantic memory context injection
- Full audit trail via tool_runs
"""

import os
import yaml
import json
from typing import Dict, List, Optional, Callable
from openai import OpenAI
from app.router import (
    get_openai_tools, parse_tool_call, execute_tool,
    format_tool_result, check_approval_needed
)
from memory.memory import (
    build_context, create_conversation, end_conversation,
    add_message, get_conversation_messages, add_feedback,
    DEFAULT_USER
)

POLICIES_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "policies.yaml")


def load_brain_config() -> Dict:
    with open(POLICIES_PATH) as f:
        config = yaml.safe_load(f)
    return config.get("brain", {})


class Brain:
    def __init__(self, api_key: str = None, approval_callback: Callable = None):
        """
        Args:
            api_key: OpenAI API key
            approval_callback: Function(prompt_text) -> bool. Called when a tool
                needs user confirmation. Returns True to approve, False to deny.
                If None, all confirmations are auto-denied.
        """
        self.config = load_brain_config()
        self.client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self.model = self.config.get("model", "gpt-4o")
        self.temperature = self.config.get("temperature", 0.3)
        self.max_tokens = self.config.get("max_tokens", 2000)
        self.tools = get_openai_tools()
        self.approval_callback = approval_callback

        # Conversation state
        self.conversation_id: Optional[str] = None
        self.chat_history: List[Dict] = []
        self._last_tool_run_id: Optional[str] = None
        self._last_message_id: Optional[str] = None

    def _build_system_prompt(self) -> str:
        base = self.config.get("system_prompt", "You are Jarvis, a helpful assistant.")
        memory_context = build_context()

        # Try to inject semantic context
        semantic_context = self._get_semantic_context()

        parts = [base, "\n## Memory Context\n" + memory_context]
        if semantic_context:
            parts.append("\n## Relevant Knowledge\n" + semantic_context)

        return "\n".join(parts)

    def _get_semantic_context(self) -> str:
        """Pull relevant memories from vector store based on recent conversation."""
        try:
            from memory.vectors import VectorStore
            vs = VectorStore()
            if not vs.available:
                return ""

            # Use last few user messages as query
            user_msgs = [m["content"] for m in self.chat_history if m.get("role") == "user"]
            if not user_msgs:
                return ""

            query = " ".join(user_msgs[-3:])[:500]
            results = vs.search(query, top_k=3)

            if not results:
                return ""

            lines = []
            for r in results:
                if r["score"] > 0.7:  # Only high-relevance
                    lines.append(f"- [{r['score']:.2f}] {r['text'][:200]}")

            return "\n".join(lines)
        except Exception:
            return ""

    def start_conversation(self, title: str = None) -> str:
        """Start a new persistent conversation."""
        self.conversation_id = create_conversation(title=title)
        self.chat_history = []
        self._last_tool_run_id = None
        self._last_message_id = None
        return self.conversation_id

    def end_current_conversation(self):
        """End and archive the current conversation."""
        if self.conversation_id:
            end_conversation(self.conversation_id)
        self.conversation_id = None
        self.chat_history = []

    def reset_conversation(self):
        """Clear in-memory history but keep DB records."""
        self.end_current_conversation()
        self.start_conversation()

    @property
    def last_tool_run_id(self) -> Optional[str]:
        return self._last_tool_run_id

    @property
    def last_message_id(self) -> Optional[str]:
        return self._last_message_id

    def _request_approval(self, tool_name: str, arguments: Dict) -> bool:
        """Ask user for approval on a risky tool call."""
        if self.approval_callback is None:
            return False

        prompt = f"⚠️  Jarvis wants to use [{tool_name}]:\n"
        if tool_name == "shell":
            prompt += f"  Command: {arguments.get('command', '?')}\n"
        else:
            prompt += f"  Args: {json.dumps(arguments, indent=2)[:200]}\n"
        prompt += "Approve? (y/n)"

        return self.approval_callback(prompt)

    def think(self, user_input: str) -> str:
        """
        Process user input through the LLM, execute tools if needed,
        and return the final response. Everything is persisted.
        """
        # Ensure we have a conversation
        if not self.conversation_id:
            self.start_conversation()

        # Persist user message
        user_msg_id = add_message(
            self.conversation_id, "user", user_input
        )
        self.chat_history.append({"role": "user", "content": user_input})

        # Build messages
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            *self.chat_history
        ]

        # First LLM call
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=self.tools,
            tool_choice="auto",
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        message = response.choices[0].message

        # Handle tool calls (up to 5 chained calls)
        max_iterations = 5
        iteration = 0

        while message.tool_calls and iteration < max_iterations:
            iteration += 1

            parsed = parse_tool_call(message)
            if not parsed:
                break

            tool_name, arguments, call_id = parsed

            # Check if approval needed
            needs_approval, tool_info = check_approval_needed(tool_name, arguments)
            if needs_approval:
                approved = self._request_approval(tool_name, arguments)
                if not approved:
                    # Denied — tell the LLM
                    self.chat_history.append({
                        "role": "assistant", "content": None,
                        "tool_calls": [{
                            "id": call_id, "type": "function",
                            "function": {"name": tool_name, "arguments": json.dumps(arguments)}
                        }]
                    })
                    self.chat_history.append({
                        "role": "tool", "tool_call_id": call_id,
                        "content": "❌ User denied this action."
                    })
                    # Re-call LLM to acknowledge denial
                    messages = [
                        {"role": "system", "content": self._build_system_prompt()},
                        *self.chat_history
                    ]
                    response = self.client.chat.completions.create(
                        model=self.model, messages=messages, tools=self.tools,
                        tool_choice="auto", temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )
                    message = response.choices[0].message
                    continue

            # Execute the tool
            result, duration_ms, tool_run_id = execute_tool(
                tool_name, arguments.copy(),
                conversation_id=self.conversation_id
            )

            self._last_tool_run_id = tool_run_id

            # Persist tool call message
            tool_msg_id = add_message(
                self.conversation_id, "assistant", f"[tool:{tool_name}]",
                content_type="json",
                tool_call_id=call_id,
                tool_name=tool_name,
                tool_input=json.dumps(arguments)
            )

            # Add to chat history for LLM
            self.chat_history.append({
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": call_id, "type": "function",
                    "function": {"name": tool_name, "arguments": json.dumps(arguments)}
                }]
            })

            formatted_result = format_tool_result(tool_name, result)

            # Persist tool result message
            add_message(
                self.conversation_id, "tool", formatted_result,
                tool_call_id=call_id, tool_name=tool_name
            )
            self.chat_history.append({
                "role": "tool", "tool_call_id": call_id,
                "content": formatted_result
            })

            # Re-call LLM
            messages = [
                {"role": "system", "content": self._build_system_prompt()},
                *self.chat_history
            ]
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=self.tools,
                tool_choice="auto", temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            message = response.choices[0].message

        # Final text response
        final_text = message.content or "(No response)"

        # Persist assistant response
        self._last_message_id = add_message(
            self.conversation_id, "assistant", final_text
        )
        self.chat_history.append({"role": "assistant", "content": final_text})

        # Trim in-memory history (keep last 30 turns)
        if len(self.chat_history) > 60:
            self.chat_history = self.chat_history[-30:]

        return final_text

    def rate_last(self, rating: int, correction: str = None, label: str = None) -> str:
        """Rate the last interaction."""
        if not self.conversation_id:
            return "No active conversation to rate."

        add_feedback(
            conversation_id=self.conversation_id,
            rating=rating,
            message_id=self._last_message_id,
            tool_run_id=self._last_tool_run_id,
            correction_text=correction,
            label=label,
        )
        return f"Feedback recorded: {'⭐' * rating}"
