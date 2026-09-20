from types import SimpleNamespace

import pytest

from frontend.telegram.user_context import get_user_state_key


def _message(chat_id: int, thread_id: int | None, user_id: int | None):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id),
        message_thread_id=thread_id,
        from_user=None if user_id is None else SimpleNamespace(id=user_id),
    )


def test_user_state_key_includes_chat_topic_and_user():
    message = _message(chat_id=-100123, thread_id=42, user_id=7)

    assert get_user_state_key(message) == (-100123, 42, 7)


def test_user_state_key_isolates_users_in_the_same_topic():
    first_user = _message(chat_id=-100123, thread_id=42, user_id=7)
    second_user = _message(chat_id=-100123, thread_id=42, user_id=8)

    assert get_user_state_key(first_user) != get_user_state_key(second_user)


def test_user_state_key_isolates_topics_for_the_same_user():
    first_topic = _message(chat_id=-100123, thread_id=42, user_id=7)
    second_topic = _message(chat_id=-100123, thread_id=43, user_id=7)

    assert get_user_state_key(first_topic) != get_user_state_key(second_topic)


def test_user_state_key_rejects_messages_without_identified_user():
    message = _message(chat_id=-100123, thread_id=None, user_id=None)

    with pytest.raises(ValueError, match="identified user"):
        get_user_state_key(message)
