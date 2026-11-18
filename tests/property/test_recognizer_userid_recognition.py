"""Property 1 of logon-recovery: user id length does not change recognition."""
from __future__ import annotations

import string

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.recognizer.bundled import load_bundled_signatures
from greenscreen.recognizer.matching import signature_matches
from greenscreen.recognizer.recognizer import recognize
from greenscreen.recognizer.view import ScreenView
from tests.screen_support import in_use_screen, reconnect_prompt_screen

_SIGS = load_bundled_signatures()


def _satisfied(screen) -> list[str]:
    view = ScreenView(screen)
    return [s.name for s in _SIGS if signature_matches(s, view)]


@settings(max_examples=100, deadline=None)
@given(
    userid=st.text(
        alphabet=string.ascii_letters + string.digits + "@#$",
        min_size=1,
        max_size=8,
    )
)
def test_userid_length_does_not_change_recognition(userid: str) -> None:
    # Feature: logon-recovery, Property 1: User id length does not change recognition
    # **Validates: Requirements 4.4, 9.3, 9.4**
    in_use = in_use_screen(userid)
    assert _satisfied(in_use) == ["tso-userid-in-use"]
    assert recognize(in_use, _SIGS) == "tso-userid-in-use"

    prompt = reconnect_prompt_screen(userid)
    assert _satisfied(prompt) == ["tso-reconnect-password-prompt"]
    assert recognize(prompt, _SIGS) == "tso-reconnect-password-prompt"
