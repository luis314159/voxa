import pytest

from voxa.audio.pronunciation import DEFAULT_LEXICON, Lexicon, fix_phonemes


@pytest.mark.parametrize(
    ("espeak", "expected"),
    [
        ("ɡˌaβɾiʲˈel", "ɡˌaβɾjˈel"),  # Gabriel: «Ga-briel», no «Ga-bri-ʲél»
        ("ˌaðɾiʲˈan", "ˌaðɾjˈan"),  # Adrián
        ("kliʲˈɛnte", "kljˈɛnte"),  # cliente
        ("rˈiʲo", "rˈiʲo"),  # río: la i tónica se queda en hiato
        ("lusˈiʲa", "lusˈiʲa"),  # Lucía
        ("xwˈaŋ", "xwˈaŋ"),
    ],
)
def test_fix_phonemes(espeak, expected):
    assert "".join(fix_phonemes(list(espeak))) == expected


def test_lexicon_replaces_whole_words_ignoring_case():
    lexicon = Lexicon({"The Beatles": "de bítels", "Queen": "cuín"})
    assert lexicon.apply("Pon a the beatles y Queen.") == "Pon a de bítels y cuín."
    assert lexicon.apply("Queens") == "Queens"


def test_lexicon_prefers_longest_match():
    lexicon = Lexicon({"Roses": "róuses", "Guns N' Roses": "gans an róuses"})
    assert lexicon.apply("Guns N' Roses.") == "gans an róuses."


def test_user_lexicon_overrides_default(tmp_path):
    user = tmp_path / "pronunciacion.yaml"
    user.write_text("Coldplay: kóldplei\nMi Banda: mi bánda\n", encoding="utf-8")
    lexicon = Lexicon.load(DEFAULT_LEXICON, user, tmp_path / "no-existe.yaml")
    assert lexicon.apply("Coldplay") == "kóldplei"
    assert lexicon.apply("The Beatles") == "de bítels"


def test_broken_user_lexicon_is_ignored(tmp_path):
    user = tmp_path / "pronunciacion.yaml"
    user.write_text("- solo\n- una lista\n", encoding="utf-8")
    assert Lexicon.load(DEFAULT_LEXICON, user).apply("Spotify") == "espótifai"
