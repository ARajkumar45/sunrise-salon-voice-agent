"""How the Piper adapter cuts a long sentence so the first audio is ready sooner."""

from app.tts_piper import first_clause_and_rest


def test_short_sentence_is_spoken_in_one_piece():
    assert first_clause_and_rest("We are open on Sunday, ten to six.") == ["We are open on Sunday, ten to six."]


def test_long_sentence_is_cut_after_its_first_clause():
    sentence = "Let me read that back: a haircut with Priya on Tuesday at three PM, under the name Raj."
    assert first_clause_and_rest(sentence) == [
        "Let me read that back:", "a haircut with Priya on Tuesday at three PM, under the name Raj."]


def test_long_sentence_without_a_pause_mark_is_not_cut():
    sentence = "A haircut costs three hundred and fifty rupees and takes about thirty minutes in total."
    assert first_clause_and_rest(sentence) == [sentence]


def test_numbers_with_commas_are_never_cut():
    sentence = "The full bridal package costs 12,500 rupees and it takes about four hours in total."
    assert first_clause_and_rest(sentence) == [sentence]


def test_no_stray_words_at_either_end():
    # A cut that would leave a very short first or last piece is not made.
    assert len(first_clause_and_rest("Yes, we do offer hair colouring and it starts at fifteen hundred rupees.")) == 1
    assert len(first_clause_and_rest("We offer hair colouring starting at fifteen hundred rupees for short hair, yes.")) == 1
