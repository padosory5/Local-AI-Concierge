from concierge import pictures, voice

PLAN = "Cheap and easy by subway.\n\n**Day 1: Haeundae and Gwangalli**\n- walk\n\n**Day 2: Culture and coast**\n- **Tip:** T-money"


def place(name):
    known = {"Gwangalli": "Gwangalli Beach", "Haeundae": None}
    title = known.get(name)
    return {"title": title, "image": "x.jpg", "about": "", "page": title} if title else None


def test_only_places_she_named_get_a_photo_and_each_goes_with_its_label():
    sent = []
    found = pictures.for_answer("Plan 3 days in Busan", PLAN, look=place, sent=lambda *a: sent.append(a))
    assert [(p["label"], p["title"]) for p in found] == [("Day 1: Haeundae and Gwangalli", "Gwangalli Beach")]
    assert sent == [("Wikipedia", "photos of places")]  # counted on What I see


def test_doing_things_never_gets_photos():
    assert pictures.for_answer("How do I take a screenshot?", PLAN, look=place, sent=lambda *a: None) == []


def test_a_title_must_really_be_the_name_she_wrote():
    assert pictures.same_place("Gwangalli", "Gwangalli Beach")
    assert pictures.same_place("Jagalchi Fish Market", "Jagalchi Market")
    assert not pictures.same_place("Haeundae", "Busan Tower")
    assert pictures.same_place("해운대", "해운대 해수욕장")


def test_names_come_out_of_labels():
    assert pictures.names_in("Day 1: Haeundae and Gwangalli") == ["Haeundae", "Gwangalli"]
    assert pictures.names_in("Day 1, Haeundae and Gwangalli:") == ["Haeundae", "Gwangalli"]
    assert pictures.names_in("Day 1 — Nampo-dong:") == ["Nampo-dong"]
    assert pictures.names_in("1일차: 해운대와 광안리") == ["해운대", "광안리"]


def test_photos_are_only_offered_under_a_plan():
    assert pictures.worth_asking("Plan 3 days in Busan", PLAN)
    assert not pictures.worth_asking("What is an API?", PLAN)


def test_the_buttons_get_their_own_sizes():
    assert "under 40 words" in voice.guide("Shorter, please.", "shorter", "word " * 200)
    assert "under 20 words" in voice.guide("Shorter, please.", "shorter", "word " * 40)
    assert "Don't repeat it" in voice.guide("Tell me more.", "more")
    assert "Pick X if" in voice.guide("Should I learn Python or JavaScript?")
