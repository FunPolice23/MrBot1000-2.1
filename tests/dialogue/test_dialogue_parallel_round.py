from unittest.mock import MagicMock

from gui.tabs.dialogue_tab import DialogueTab, _BIG, _SMALL


def _tab():
    tab = DialogueTab.__new__(DialogueTab)
    tab.live_running = True
    tab.goal = "compare two opportunities"
    tab._live_last_speaker = None
    tab._agent_runtime = tab._create_agent_runtime()
    tab.worker = None
    tab.respond = MagicMock()
    return tab


def test_live_selects_one_agent_opportunity_and_then_the_other():
    tab = _tab()
    tab._start_live_opportunity()
    assert tab.current_speaker == _BIG
    tab.respond.assert_called_once_with()

    tab._agent_runtime.record_turn("edward", "I propose verification.", intents=("proposal",))
    tab.respond.reset_mock()
    tab._start_live_opportunity()
    assert tab.current_speaker == _SMALL
    tab.respond.assert_called_once_with()
