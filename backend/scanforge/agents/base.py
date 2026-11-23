"""Minimal tool-using agent on the Claude API.

Each agent = a system prompt + a set of Python tools. Agents never touch geometry
math themselves; they call pipeline functions and read/write the building graph.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

DEFAULT_MODEL = os.getenv("SCANFORGE_MODEL", "claude-sonnet-5-5")


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable[..., Any]

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


@dataclass
class Agent:
    name: str
    system: str
    tools: list[Tool] = field(default_factory=list)
    model: str = DEFAULT_MODEL
    max_turns: int = 12

    def run(self, task: str, client=None) -> str:
        import anthropic
        client = client or anthropic.Anthropic()
        by_name = {t.name: t for t in self.tools}
        messages: list[dict] = [{"role": "user", "content": task}]
        for _ in range(self.max_turns):
            resp = client.messages.create(model=self.model, max_tokens=4096, system=self.system,
                                          tools=[t.spec() for t in self.tools], messages=messages)
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                return "".join(b.text for b in resp.content if b.type == "text")
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                try:
                    out = by_name[block.name].fn(**block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": json.dumps(out, default=str)[:20000]})
                except Exception as e:  # report to the model so it can adjust
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"error: {e}", "is_error": True})
            messages.append({"role": "user", "content": results})
        return f"{self.name}: stopped after {self.max_turns} turns"
