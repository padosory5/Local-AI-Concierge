import json

from concierge import elaina
from concierge.agents.blueprint import load_blueprints
from concierge.agents.builder import AgentBuilder
from concierge.cli import TerminalScreen
from concierge.events import ElainaText, IdeaCard, Question, Thinking
from concierge.fake_engine import FakeEngine
from concierge.ui.window import ChatBridge, ChatHub


class ThinkingModel:
    """Streams a few thoughts, then a reply."""

    def capabilities(self, name):
        return ["completion", "thinking"]

    def chat_parts(self, model, messages, think=None, options=None, keep_alive=None):
        assert think is True
        yield "thought", "The user greets me. "
        yield "thought", "A short reply fits."
        yield "text", "Hi! "
        yield "text", "Good to see you. "
        yield "text", "Let me know if you need anything else."

    def chat(self, *args, **kwargs):
        yield "Hi!"


def test_think_through_streams_thoughts_then_the_reply():
    chat = elaina.ElainaChat(ThinkingModel())
    assert chat.can_think
    parts = list(chat.think_through("hello"))
    kinds = [k for k, _ in parts]
    assert kinds[:2] == ["thought", "thought"] and set(kinds[2:]) == {"text"}
    reply = "".join(p for k, p in parts if k == "text")
    assert reply.strip() == "Hi! Good to see you."  # closing filler dropped here too
    # Only the reply is remembered, never the thoughts.
    assert chat.history[-1] == {"role": "assistant", "content": "Hi! Good to see you."}


def test_a_model_without_thinking_says_it_cannot():
    class Plain(ThinkingModel):
        def capabilities(self, name):
            return ["completion"]

    assert not elaina.ElainaChat(Plain()).can_think


def test_composing_shows_the_instruction_it_wrote():
    class Writer(ThinkingModel):
        def chat_json(self, model, messages, schema, think=None, keep_alive=None):
            return {"name": "Korean translator", "instruction": "Translate the text into Korean.",
                    "example": "Good morning"}

    builder = AgentBuilder(Writer(), "elaina", None, load_blueprints())
    events = list(builder.compose("translate what I highlight into Korean", ["while_on", "selected_text"]))
    step = next(e for e in events if isinstance(e, Thinking))
    assert step.kind == "step" and step.text == 'Wrote what it does: "Translate the text into Korean."'
    assert type(events[-1]).__name__ == "AgentCard"


def test_fake_engine_streams_thinking_when_asked():
    engine = FakeEngine(delay=0)
    events = list(engine.send("hello", think=True))
    thinking = [e for e in events if isinstance(e, Thinking)]
    assert thinking[0].kind == "step" and {e.kind for e in thinking[1:]} == {"thought"}
    first_text = next(i for i, e in enumerate(events) if isinstance(e, ElainaText))
    assert all(isinstance(e, Thinking) for e in events[1:first_text])  # fog comes before the answer
    assert not any(isinstance(e, Thinking) for e in FakeEngine(delay=0).send("hello"))


def test_window_passes_the_think_button_through():
    pushed = []
    bridge = ChatBridge(ChatHub(FakeEngine(delay=0)))
    bridge._attach(type("W", (), {"run_js": lambda self, js: pushed.append(js)})())
    bridge.send("hello", True)
    types = [json.loads(js[len("app.onEvent("):-1])["type"] for js in pushed]
    assert "Thinking" in types


def test_terminal_draws_thinking_dimmed(capsys):
    screen = TerminalScreen()
    screen.draw(Thinking("This asks for a new agent: Highlight translator."))
    screen.draw(Thinking("Let me think. ", "thought"))
    screen.draw(Thinking("Done.", "thought"))
    screen.draw(ElainaText("Hello"))
    out = capsys.readouterr().out
    assert "· This asks for a new agent" in out
    assert "(thinking) Let me think. Done." in out
    assert out.index("Done.") < out.index("Elaina: Hello")


def test_idea_card_comes_after_its_steps():
    from concierge.agents.planner import IdeaPlanner
    from tests.test_catalog import machine, nvidia

    class Planner:
        def chat_json(self, model, messages, schema, think=None, keep_alive=None):
            return {"title": "Word explainer", "steps": [
                {"block": "while_on", "detail": ""}, {"block": "selected_text", "detail": ""},
                {"block": "translate", "detail": "simple Korean"}, {"block": "show_popup", "detail": ""}]}

    p = IdeaPlanner(Planner(), "elaina", None, lambda: (machine(gpus=[nvidia(16)]), 3.8), load_blueprints())
    events = list(p.start("explain words I highlight in simple Korean"))
    assert isinstance(events[0], Thinking) and events[0].text.startswith("Broke the idea into parts:")
    assert isinstance(events[-1], IdeaCard)
