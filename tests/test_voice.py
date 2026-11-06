from concierge import voice
from concierge.elaina import ElainaChat


def tidied(text, size=3):
    """Run text through tidy in small pieces, the way a model streams it."""
    return "".join(voice.tidy(iter([text[i:i + size] for i in range(0, len(text), size)])))


def test_the_kind_of_question_is_decided_by_code():
    assert voice.kind_of("Plan a 3-day trip to Busan") == "plan"
    assert voice.kind_of("Should I learn Python or JavaScript first?") == "decide"  # a choice, not code
    assert voice.kind_of("How do I take a screenshot on Windows?") == "how-to"
    assert voice.kind_of("My Python says IndexError") == "code"
    assert voice.kind_of("What's the capital of Australia?") == "fact"
    assert voice.kind_of("What is an API?") == "explain"
    assert voice.kind_of("주말에 공부하는 방법 알려줘") == "how-to"
    assert voice.kind_of("hey") == "small_talk"
    assert voice.kind_of("hey, can you help me with my CV?") == "chat"


def test_each_kind_gets_its_own_word_budget():
    assert "under 40 words" in voice.guide("What's the capital of Australia?")
    assert "no list" in voice.guide("What's the capital of Australia?")
    assert "up to 4 short points" in voice.guide("How do I take a screenshot?")
    plan = voice.guide("Plan a trip to Busan")
    assert "under 170 words" in plan and "bold label for each day" in plan
    assert "code block" in voice.guide("Why does my Python code crash?")


def test_empty_openers_are_taken_off_the_start_only():
    assert tidied("Great question! Canberra is the capital.") == "Canberra is the capital."
    assert tidied("Sure, here it is.\n- one") == "Here it is.\n- one"
    assert tidied("Canberra. That's a great question! people ask") == "Canberra. That's a great question! people ask"


def test_headings_rules_and_tables_become_what_the_window_shows_well():
    text = "## Day 1\n---\n| Place | Cost |\n|---|---|\n| Beach | Free |\n| Tower | 12,000 won |\nDone."
    assert tidied(text) == "**Day 1**\n- **Beach**: Free\n- **Tower**: 12,000 won\nDone."


def test_a_quote_mark_is_taken_off_and_a_closing_offer_dropped():
    from concierge.elaina import without_closing_filler

    assert tidied("Press Win + Shift + S.\n> Note: PrtScn saves it.") == "Press Win + Shift + S.\nNote: PrtScn saves it."
    reply = ["Press Win + Shift + S. ", "Would you like to save these steps somewhere?"]
    assert "".join(voice.tidy(without_closing_filler(iter(reply)))) == "Press Win + Shift + S. "


def test_a_question_tacked_on_after_a_whole_answer_is_dropped_but_a_needed_one_stays():
    from concierge.elaina import without_closing_filler

    def said(*sentences):
        return "".join(without_closing_filler(iter(sentences)))

    whole = ["Pick Python for data. ", "JavaScript is for websites. ", "Either works. ", "Which area feels right to you?"]
    assert said(*whole) == "Pick Python for data. JavaScript is for websites. Either works. "
    assert said("I can't see that folder. ", "Which one do you mean?") == "I can't see that folder. Which one do you mean?"
    points = "시간을 확보하면 됩니다.\n- **시간**을 정한다\n- 휴대폰을 치운다\n\n혹시 특정 과목 때문인가요?"
    assert said(points) == "시간을 확보하면 됩니다.\n- **시간**을 정한다\n- 휴대폰을 치운다\n\n"  # points have no full stops


def test_gaps_close_up_but_code_is_never_touched():
    text = "Use this:\n\n\n\n```python\n# not a heading\n\n\nprint(1)\n```\n\nThat's it."
    assert tidied(text) == "Use this:\n\n```python\n# not a heading\n\n\nprint(1)\n```\n\nThat's it."


def test_an_ordinary_line_still_streams_word_by_word():
    pieces = list(voice.tidy(iter(["Great question! ", "Canberra is the capital. ", "It's ", "in the ACT."])))
    assert pieces[0] == "Canberra is the capital. " and "".join(pieces) == "Canberra is the capital. It's in the ACT."


class Talker:
    def __init__(self, reply="## Answer\nCanberra."):
        self.reply, self.sent = reply, None

    def capabilities(self, name):
        return []

    def show(self, name):
        return {"system": "I am Elaina."}

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.sent = messages
        return iter([self.reply])


def test_every_model_gets_the_note_and_her_memory_keeps_only_the_words():
    own = Talker()
    chat = ElainaChat(own)
    assert "".join(chat.send("What's the capital of Australia?")) == "**Answer**\nCanberra."
    assert own.sent[-1]["content"].endswith(voice.guide("What's the capital of Australia?"))
    cloud = Talker("Sure! Canberra.")
    chat.talker = cloud  # a Claude or GPT model picked in the menu
    assert "".join(chat.send("And of Korea?")) == "Canberra."
    assert "Elaina's way" in cloud.sent[-1]["content"]
    assert [m["content"] for m in chat.history if m["role"] == "user"] == ["What's the capital of Australia?", "And of Korea?"]
    chat.close()


def test_the_note_is_chosen_from_the_question_not_from_an_added_file():
    own = Talker()
    chat = ElainaChat(own)
    chat.attach("FILE notes.txt\nPlan for the plan of the planning", [])
    list(chat.send("What does this say?"))
    assert own.sent[-1]["content"].endswith(voice.guide("What does this say?"))
    chat.close()


def test_small_talk_gets_a_note_of_its_own_and_no_answer_rules():
    for words in ("hello", "Thanks!", "ok cool", "good morning Elaina", "안녕!", "고마워요"):
        assert voice.kind_of(words) == "small_talk", words
    note = voice.guide("thanks!")
    assert "small talk" in note and "Don't answer an earlier question again" in note
    assert "Start with the answer itself" not in note
    assert voice.kind_of("thanks for that, but what's the capital of Peru?") != "small_talk"


def test_lines_that_only_echo_the_answer_rules_are_dropped():
    said = "".join(voice.tidy(iter([
        "The capital of Japan is Tokyo.\n",
        "There are no additional tips or questions needed for this answer.\n",
        "No special conditions are needed for this answer.\n",
        "Word count: 12\n",
    ])))
    assert said.strip() == "The capital of Japan is Tokyo."


def test_a_real_answer_starting_with_no_still_goes_through():
    said = "".join(voice.tidy(iter(["No, the capital of Australia is Canberra, not Sydney.\n", "It has been since 1913.\n"])))
    assert said == "No, the capital of Australia is Canberra, not Sydney.\nIt has been since 1913.\n"


def test_a_bullet_inside_the_bold_comes_out_in_front():
    assert tidied("Use it.\n**- Right side:** keeps all rows.\n**Tip:** stir.") == "Use it.\n- **Right side:** keeps all rows.\n**Tip:** stir."
