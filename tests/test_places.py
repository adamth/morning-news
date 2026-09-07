"""Unit tests for home-place matching and the local-relevance ranking it drives.

The behaviour under test is why a listener in Sassafras stopped hearing about
primary schools an hour away: place names decide what counts as local, both
when building Google News queries and when ranking candidate articles.
"""

from __future__ import annotations

from app.places import match_places, parse_places, score_text, serialize_places
from app.sources import news
from app.sources.news import Article, build_home_place_queries, build_local_news_sources

RANGES = parse_places("Sassafras, Olinda, Kallista, Mount Dandenong, Monbulk, Belgrave")


class TestParsePlaces:
    def test_trims_and_drops_blanks(self):
        assert parse_places("  Sassafras ,, Olinda  ") == ["Sassafras", "Olinda"]

    def test_collapses_inner_whitespace(self):
        assert parse_places("Mount   Dandenong") == ["Mount Dandenong"]

    def test_dedupes_case_insensitively_keeping_first_spelling(self):
        assert parse_places("Sassafras, sassafras, SASSAFRAS") == ["Sassafras"]

    def test_preserves_order_because_closest_is_listed_first(self):
        assert parse_places("Olinda, Sassafras") == ["Olinda", "Sassafras"]

    def test_empty_value_yields_no_places(self):
        assert parse_places("") == []
        assert parse_places("  ,  , ") == []

    def test_serialize_round_trips(self):
        assert serialize_places(["Sassafras", " Olinda "]) == "Sassafras, Olinda"


class TestMatchPlaces:
    def test_matches_case_insensitively(self):
        assert match_places("SASSAFRAS hall reopens", RANGES) == ["Sassafras"]

    def test_matches_inside_hyphenated_compounds(self):
        # A real headline: the local footy club is "Olinda-Ferny Creek".
        assert match_places("Olinda-Ferny Creek books grand final spot", RANGES) == [
            "Olinda"
        ]

    def test_matches_multi_word_places(self):
        assert match_places("Mount Dandenong Tourist Road closed", RANGES) == [
            "Mount Dandenong"
        ]

    def test_respects_word_boundaries(self):
        # Guards against "Belgrave" matching a surname-ish "Belgraves".
        assert match_places("Carlos Belgraves obituary", RANGES) == []

    def test_returns_places_in_home_order_not_text_order(self):
        matched = match_places("Monbulk beat Olinda at Sassafras", RANGES)
        assert matched == ["Sassafras", "Olinda", "Monbulk"]

    def test_no_places_configured_matches_nothing(self):
        assert match_places("Sassafras hall reopens", []) == []


class TestScoreText:
    def test_title_mention_outweighs_body_mention(self):
        title_hit = score_text(title="Sassafras hall reopens", body="", places=RANGES)
        body_hit = score_text(title="Council news", body="in Sassafras", places=RANGES)
        assert title_hit > body_hit

    def test_body_mentions_are_capped_so_one_rambler_cannot_win(self):
        rambling = score_text(title="Region roundup", body="Olinda " * 20, places=RANGES)
        about_us = score_text(title="Olinda hall reopens", body="", places=RANGES)
        assert about_us >= rambling

    def test_unrelated_story_scores_zero(self):
        assert score_text(title="Federal budget handed down", body="", places=RANGES) == 0

    def test_no_places_configured_scores_zero(self):
        assert score_text(title="Sassafras hall reopens", body="", places=[]) == 0


class TestBuildHomePlaceQueries:
    def test_quotes_each_place_and_anchors_to_the_region(self):
        # Unquoted town names match homonyms worldwide, so quoting is the point.
        (query,) = build_home_place_queries(["Sassafras", "Olinda"], "Victoria")
        assert query == '("Sassafras" OR "Olinda") "Victoria" when:2d'

    def test_omits_region_when_unknown(self):
        (query,) = build_home_place_queries(["Sassafras"], "")
        assert query == '("Sassafras") when:2d'

    def test_chunks_long_lists_into_several_queries(self):
        places = [f"Town{n}" for n in range(13)]
        queries = build_home_place_queries(places, "Victoria", max_per_query=6)
        assert len(queries) == 3
        assert all(query.count(" OR ") <= 5 for query in queries)

    def test_no_places_yields_no_queries(self):
        assert build_home_place_queries([], "Victoria") == []


class TestBuildLocalNewsSources:
    def _build(self, **kwargs):
        return build_local_news_sources(
            locality="Sassafras",
            admin1="Victoria",
            country="Australia",
            hl="en-AU",
            gl="AU",
            ceid="AU:en",
            **kwargs,
        )

    def test_home_places_replace_the_state_wide_firehose(self):
        # "Victoria when:1d" returns ~100 state-wide stories a day and buried
        # everything else; with home places set it must not be requested.
        names = [source.name for source in self._build(home_places=RANGES)]
        assert not any(name.startswith("Regional") for name in names)
        assert "Local (home places)" in names

    def test_falls_back_to_regional_search_without_home_places(self):
        names = [source.name for source in self._build()]
        assert "Regional (Victoria)" in names

    def test_locality_geo_feed_is_kept_either_way(self):
        for kwargs in ({}, {"home_places": RANGES}):
            names = [source.name for source in self._build(**kwargs)]
            assert "Local (Sassafras)" in names

    def test_every_built_source_is_flagged_as_google_news(self):
        assert all(source.is_google_news for source in self._build(home_places=RANGES))


def _article(title: str, *, source_name: str = "", url: str = "") -> Article:
    """A feed article whose summary carries the text (bodies come later)."""

    return Article(
        title=title,
        url=url or f"https://example.test/{abs(hash(title))}",
        publisher=source_name or "Google News",
        summary=title,
        source_name=source_name,
    )


class TestGatherArticlesLocalRanking:
    """gather_articles must stop a high-volume Google News feed crowding out
    the listener's own feeds, without dropping national news entirely."""

    def _gather(self, monkeypatch, *, user, auto, **kwargs):
        def fake_collect(sources, _max_entries):
            return list(auto) if any(s.is_google_news for s in sources) else list(user)

        monkeypatch.setattr(news, "_collect_from_sources", fake_collect)
        return news.gather_articles(
            [
                news.NewsSource(url="https://paper.test/feed/", name="Star Mail"),
                news.NewsSource(url="https://news.google.com/rss/search?q=x", is_google_news=True),
            ],
            extract=False,
            **kwargs,
        )

    def test_local_stories_outrank_distant_ones_within_a_feed(self, monkeypatch):
        selected = self._gather(
            monkeypatch,
            user=[
                _article("Lilydale primary school fete", source_name="Star Mail"),
                _article("Sassafras hall reopens", source_name="Star Mail"),
            ],
            auto=[],
            home_places=RANGES,
        )
        assert [a.title for a in selected][0] == "Sassafras hall reopens"

    def test_distant_google_news_cannot_crowd_out_user_feeds(self, monkeypatch):
        # The regression: a 100-item state feed against a 12-item local paper.
        selected = self._gather(
            monkeypatch,
            user=[_article(f"Monbulk story {n}", source_name="Star Mail") for n in range(5)],
            auto=[_article(f"Victorian state story {n}") for n in range(100)],
            home_places=RANGES,
            max_articles=10,
        )
        assert [a.title for a in selected][:5] == [f"Monbulk story {n}" for n in range(5)]

    def test_distant_stories_still_backfill_a_quiet_day(self, monkeypatch):
        selected = self._gather(
            monkeypatch,
            user=[],
            auto=[_article("Federal budget handed down")],
            home_places=RANGES,
        )
        assert [a.title for a in selected] == ["Federal budget handed down"]

    def test_local_google_news_stories_are_preferred_over_distant_ones(self, monkeypatch):
        selected = self._gather(
            monkeypatch,
            user=[],
            auto=[
                _article("Interest rates on hold"),
                _article("Kallista market marks fifty years"),
            ],
            home_places=RANGES,
        )
        assert [a.title for a in selected][0] == "Kallista market marks fifty years"

    def test_articles_are_annotated_for_the_prompt(self, monkeypatch):
        selected = self._gather(
            monkeypatch,
            user=[_article("Olinda and Monbulk share the road works", source_name="Star Mail")],
            auto=[],
            home_places=RANGES,
        )
        assert selected[0].local_places == ["Olinda", "Monbulk"]
        assert selected[0].local_score > 0

    def test_without_home_places_nothing_is_scored_or_demoted(self, monkeypatch):
        selected = self._gather(
            monkeypatch,
            user=[_article("Local story", source_name="Star Mail")],
            auto=[_article("State story")],
        )
        assert {a.title for a in selected} == {"Local story", "State story"}
        assert all(a.local_score == 0 and a.local_places == [] for a in selected)


class TestTitleDedupe:
    """Google News appends " - Publisher" to headlines, so the same story from
    a search feed and from the publisher's own feed looked like two stories."""

    def test_google_news_suffix_is_stripped_for_the_dedupe_key(self):
        assert news._title_key("Bushfire failings - Lilydale Star Mail") == "bushfire failings"

    def test_plain_titles_are_only_lowercased(self):
        assert news._title_key("Sassafras hall reopens") == "sassafras hall reopens"

    def test_hyphenated_names_are_left_alone(self):
        key = news._title_key("Olinda-Ferny Creek books grand final spot")
        assert key == "olinda-ferny creek books grand final spot"

    def test_colon_subtitles_are_left_alone(self):
        assert news._title_key("Review: you don't want this") == "review: you don't want this"

    def test_same_story_from_two_feeds_is_selected_once(self, monkeypatch):
        def fake_collect(sources, _max_entries):
            if any(s.is_google_news for s in sources):
                return [_article("Bushfire failings - Lilydale Star Mail")]
            return [_article("Bushfire failings", source_name="Star Mail")]

        monkeypatch.setattr(news, "_collect_from_sources", fake_collect)
        selected = news.gather_articles(
            [
                news.NewsSource(url="https://paper.test/feed/", name="Star Mail"),
                news.NewsSource(url="https://news.google.com/rss/search?q=x", is_google_news=True),
            ],
            extract=False,
            home_places=RANGES,
        )
        assert len(selected) == 1

    def test_a_story_already_aired_is_not_repeated_under_a_suffixed_title(self, monkeypatch):
        monkeypatch.setattr(
            news,
            "_collect_from_sources",
            lambda sources, _m: [_article("Bushfire failings - Lilydale Star Mail")],
        )
        selected = news.gather_articles(
            [news.NewsSource(url="https://news.google.com/rss/search?q=x", is_google_news=True)],
            extract=False,
            exclude_titles={"bushfire failings"},
        )
        assert selected == []


class TestPlaceScopedFallbackScore:
    """A Google News snippet often omits the town its own query matched, so a
    place-scoped feed's stories must not be demoted as if they were regional."""

    def _gather(self, monkeypatch, auto):
        monkeypatch.setattr(news, "_collect_from_sources", lambda sources, _m: list(auto))
        return news.gather_articles(
            [
                news.NewsSource(
                    url="https://news.google.com/rss/search?q=x",
                    name="Local (home places)",
                    is_google_news=True,
                    place_scoped=True,
                )
            ],
            extract=False,
            home_places=RANGES,
        )

    def test_place_scoped_story_scores_above_zero_without_a_place_in_its_title(
        self, monkeypatch
    ):
        article = _article("Must-see town this spring")
        article.place_scoped = True
        (selected,) = self._gather(monkeypatch, [article])
        assert selected.local_score == 1

    def test_a_named_home_place_still_outranks_the_query_floor(self, monkeypatch):
        vague, named = _article("Must-see town this spring"), _article("Kallista market turns fifty")
        vague.place_scoped = named.place_scoped = True
        selected = self._gather(monkeypatch, [vague, named])
        assert [a.title for a in selected][0] == "Kallista market turns fifty"

    def test_broad_regional_feeds_get_no_floor(self, monkeypatch):
        monkeypatch.setattr(
            news, "_collect_from_sources", lambda sources, _m: [_article("State budget news")]
        )
        (selected,) = news.gather_articles(
            [news.NewsSource(url="https://news.google.com/rss/search?q=Victoria", is_google_news=True)],
            extract=False,
            home_places=RANGES,
        )
        assert selected.local_score == 0


class TestInterestTopics:
    """Interest stories are slow-day filler: capped, balanced across topics,
    and never able to displace a local story."""

    def _sources(self, topics):
        return news.build_interest_sources(topics, hl="en-AU", gl="AU", ceid="AU:en")

    def test_one_feed_per_topic_so_each_can_be_capped(self):
        sources = self._sources(["video games", "artificial intelligence"])
        assert [s.name for s in sources] == [
            "Interest (video games)",
            "Interest (artificial intelligence)",
        ]
        assert all(s.interest and s.is_google_news for s in sources)

    def test_no_topics_yields_no_sources(self):
        assert self._sources([]) == []

    def test_interest_stories_rank_below_every_local_story(self, monkeypatch):
        local = [_article(f"Monbulk story {n}", source_name="Star Mail") for n in range(3)]
        filler = [_article("New Melbourne game studio opens", source_name="Interest (games)")]
        for article in filler:
            article.interest = True

        def fake_collect(sources, _max):
            if not sources:
                return []
            if sources[0].interest:
                return list(filler)
            if sources[0].is_google_news:
                return []
            return list(local)

        monkeypatch.setattr(news, "_collect_from_sources", fake_collect)
        selected = news.gather_articles(
            [
                news.NewsSource(url="https://paper.test/feed/", name="Star Mail"),
                news.NewsSource(url="https://news.google.com/rss/search?q=x", is_google_news=True),
                news.NewsSource(
                    url="https://news.google.com/rss/search?q=games",
                    name="Interest (games)",
                    is_google_news=True,
                    interest=True,
                ),
            ],
            extract=False,
            home_places=RANGES,
        )
        assert selected[-1].title == "New Melbourne game studio opens"
        assert selected[-1].interest is True

    def test_interest_stories_are_not_scored_as_failed_local_stories(self, monkeypatch):
        filler = _article("AI model released", source_name="Interest (ai)")
        filler.interest = True
        monkeypatch.setattr(
            news, "_collect_from_sources", lambda sources, _m: [filler] if sources else []
        )
        (selected,) = news.gather_articles(
            [
                news.NewsSource(
                    url="https://news.google.com/rss/search?q=ai",
                    name="Interest (ai)",
                    is_google_news=True,
                    interest=True,
                )
            ],
            extract=False,
            home_places=RANGES,
        )
        assert selected.interest is True


class TestBalanceBySource:
    """A query for AI returns ~100 stories in two days; one for the Australian
    games industry returns two a week. Filler must not become all-AI."""

    def test_round_robins_so_a_chatty_topic_cannot_fill_the_pool(self):
        articles = [_article(f"AI {n}", source_name="Interest (ai)") for n in range(10)]
        articles += [_article("Games story", source_name="Interest (games)")]
        balanced = news._balance_by_source(articles, 2)
        assert [a.source_name for a in balanced[:2]] == [
            "Interest (ai)",
            "Interest (games)",
        ]

    def test_caps_each_source(self):
        articles = [_article(f"AI {n}", source_name="Interest (ai)") for n in range(10)]
        assert len(news._balance_by_source(articles, 2)) == 2

    def test_keeps_a_sparse_source_that_has_fewer_than_the_cap(self):
        articles = [
            _article("AI one", source_name="Interest (ai)"),
            _article("AI two", source_name="Interest (ai)"),
            _article("Games story", source_name="Interest (games)"),
        ]
        titles = {a.title for a in news._balance_by_source(articles, 2)}
        assert "Games story" in titles
