"""
Base Agent with @tool decorator.

Every agent tool function must be decorated with @tool.
The decorator registers the function's name, description, and JSON schema
so the Claude API (tool_runner) can call it automatically.
"""

import json
import inspect
import functools
from typing import Any, Callable, Dict, List, Optional, get_type_hints
import anthropic

# Global tool registry — populated by @tool decorators at import time
_TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}


def tool(description: str, schema: Optional[Dict] = None):
    """
    Decorator that marks a function as an agent tool.

    Usage:
        @tool("Queries recent metrics from the silver layer")
        def query_metrics(service: str, minutes: int = 30) -> dict:
            ...

    The decorated function is registered with its Claude tool schema
    and can be called by the LLM during an agentic loop.
    """
    def decorator(func: Callable) -> Callable:
        tool_name = func.__name__

        # Build input_schema from function signature if not provided
        if schema is None:
            input_schema = _build_schema_from_signature(func)
        else:
            input_schema = schema

        _TOOL_REGISTRY[tool_name] = {
            "name": tool_name,
            "description": description,
            "input_schema": input_schema,
            "fn": func,
        }

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        wrapper._is_tool = True
        wrapper._tool_name = tool_name
        wrapper._tool_description = description
        wrapper._tool_schema = input_schema
        return wrapper

    return decorator


def _build_schema_from_signature(func: Callable) -> Dict:
    """Introspects function signature to build a JSON schema."""
    sig = inspect.signature(func)
    hints = {}
    try:
        hints = get_type_hints(func)
    except Exception:
        pass

    _type_map = {
        int: "integer",
        float: "number",
        str: "string",
        bool: "boolean",
        list: "array",
        dict: "object",
        List: "array",
    }

    properties: Dict[str, Any] = {}
    required: List[str] = []

    for name, param in sig.parameters.items():
        if name == "self":
            continue
        py_type = hints.get(name, str)
        json_type = _type_map.get(py_type, "string")
        properties[name] = {"type": json_type, "description": name.replace("_", " ")}
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def get_tools_for_agent(agent_tool_names: List[str]) -> List[Dict]:
    """Returns Claude-format tool definitions for the given tool names."""
    result = []
    for name in agent_tool_names:
        if name in _TOOL_REGISTRY:
            entry = _TOOL_REGISTRY[name]
            result.append({
                "name": entry["name"],
                "description": entry["description"],
                "input_schema": entry["input_schema"],
            })
    return result


def execute_tool(tool_name: str, tool_input: Dict[str, Any]) -> Any:
    """Executes a registered tool function by name."""
    if tool_name not in _TOOL_REGISTRY:
        raise ValueError(f"Unknown tool: {tool_name}")
    fn = _TOOL_REGISTRY[tool_name]["fn"]
    return fn(**tool_input)


class BaseAgent:
    """
    Base class for all AIOps agents.

    Subclasses declare which tools they own via self.tool_names,
    then call self.run(prompt) to execute an agentic loop where
    Claude can call those tools until it reaches a final answer.
    """

    def __init__(self, client: anthropic.Anthropic, model: str, tool_names: List[str]):
        self.client = client
        self.model = model
        self.tool_names = tool_names

    def run(self, system_prompt: str, user_prompt: str, max_iterations: int = 20) -> str:
        """
        Runs the agentic tool-calling loop until Claude produces a final answer.
        Returns the final text response.
        """
        tools = get_tools_for_agent(self.tool_names)
        messages = [{"role": "user", "content": user_prompt}]

        for _ in range(max_iterations):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system_prompt,
                tools=tools,
                messages=messages,
                thinking={"type": "adaptive"},
            )

            # Append assistant response to message history
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                # Extract the final text answer
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return ""

            if response.stop_reason == "tool_use":
                # Execute all tool calls and collect results
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        try:
                            result = execute_tool(block.name, block.input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result, default=str),
                            })
                        except Exception as exc:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": str(exc),
                            })
                messages.append({"role": "user", "content": tool_results})
                continue

            # Any other stop reason (e.g. refusal) — return what we have
            break

        return "Agent reached maximum iterations without a final answer."
