from obsidian_memory_core.wiki.reflect_retrieval import (
    reciprocal_rank_fusion,
    retrieve_reflect_excerpts,
    select_reflect_excerpts,
    split_markdown_sections,
)


def test_rrf_fuses_channels_and_collapses_duplicate_paths():
    fused = reciprocal_rank_fusion(
        [
            [{"path": "a.md", "title": "A", "score": 9000}, {"path": "b.md", "title": "B"}],
            [{"path": "a.md", "title": "A", "score": 0.01}],
        ],
        limit=10,
    )
    assert [item["path"] for item in fused] == ["a.md", "b.md"]
    assert fused[0]["rrf_score"] > fused[1]["rrf_score"]


def test_rrf_ties_are_deterministic():
    ranked = [{"path": path, "title": title} for path, title in [
        ("z.md", "Zulu"), ("a.md", "Alpha")
    ]]
    reverse = list(reversed(ranked))
    assert [x["path"] for x in reciprocal_rank_fusion([ranked, reverse], limit=5)] == ["a.md", "z.md"]


def test_rrf_keeps_exact_page_identity_ahead_of_other_channel_ranks():
    exact = {"rel": "people/linh.md", "title": "Linh", "stem": "linh",
             "meta": {"aliases": ["Linh Nguyen"]}}
    fused = reciprocal_rank_fusion(
        [[{"path": "other.md", "title": "Other"},
          {"path": "people/linh.md", "title": "Linh"}]],
        limit=5, pages_by_path={"people/linh.md": exact}, query="Linh Nguyen",
    )
    assert fused[0]["path"] == "people/linh.md"


def test_selector_uses_semantic_section_score_when_words_do_not_overlap():
    class FakeEmbedder:
        def embed(self, values):
            vectors = {"question about planning": [1.0, 0.0],
                       "## Unrelated\n\nBird migration patterns.": [0.0, 1.0],
                       "## Relevant\n\nCoordinating future work together.": [0.99, 0.01]}
            return [vectors[value] for value in values]

    page = {"rel": "concepts/semantics.md", "title": "Semantics",
            "body": "## Unrelated\n\nBird migration patterns.\n\n"
                    "## Relevant\n\nCoordinating future work together."}
    result = select_reflect_excerpts(
        "question about planning", [page], embedder=FakeEmbedder(),
        max_sections_per_page=1,
    )
    assert "## Relevant" in result[0]["content"]


def test_selector_reranks_pages_by_best_section_not_rrf_input_order():
    class FakeEmbedder:
        def embed(self, values):
            vectors = {
                "query about a particular topic": [1.0, 0.0],
                "## Topic\n\nSpecific topic evidence.": [0.95, 0.05],
                "## Other\n\nUnrelated general evidence.": [0.05, 0.95],
            }
            return [vectors[value] for value in values]

    pages = [
        {"rel": "concepts/other.md", "title": "Other", "body": "## Other\n\nUnrelated general evidence."},
        {"rel": "concepts/topic.md", "title": "Topic", "body": "## Topic\n\nSpecific topic evidence."},
    ]
    result = select_reflect_excerpts(
        "query about a particular topic", pages, embedder=FakeEmbedder(),
        max_total_chars=1000,
    )
    assert result[0]["path"] == "concepts/topic.md"


def test_selector_fairly_samples_sections_from_later_candidate_pages():
    class FakeEmbedder:
        def embed(self, values):
            query = "question about a specific family fact"
            vectors = [([1.0, 0.0] if value == query else [0.0, 1.0]) for value in values]
            vectors[0] = [1.0, 0.0]
            vectors[-1] = [0.99, 0.01]
            return vectors

    long_page = {
        "rel": "concepts/noisy.md", "title": "Noisy",
        "body": "\n\n".join(f"## Section {i}\n\nUnrelated material." for i in range(24)),
    }
    relevant_page = {
        "rel": "people/fact.md", "title": "Fact",
        "body": "## Identity\n\nPerson details.\n\n## Family\n\nSpecific family fact.",
    }
    result = select_reflect_excerpts(
        "question about a specific family fact", [long_page, relevant_page],
        embedder=FakeEmbedder(), max_sections_per_page=1,
    )
    # Selection must still inspect candidates beyond the first page's sections.
    assert any(item["path"] == "people/fact.md" for item in result)


def test_selector_samples_deep_sections_instead_of_only_page_prefix():
    target = "## Deep Evidence\n\nQuestion-specific evidence lives here."

    class FakeEmbedder:
        def embed(self, values):
            query = "query about the specific topic"
            vectors = [[1.0, 0.0] if value == query else [0.0, 1.0] for value in values]
            vectors[0] = [1.0, 0.0]
            for i, value in enumerate(values[1:], 1):
                if value == target:
                    vectors[i] = [0.99, 0.01]
            return vectors

    body = "\n\n".join([*(f"## Section {i}\n\nUnrelated filler." for i in range(20)), target])
    result = select_reflect_excerpts(
        "query about the specific topic", [{"rel": "concepts/deep.md", "title": "Deep", "body": body}],
        embedder=FakeEmbedder(), max_sections_per_page=1,
    )
    assert result and "## Deep Evidence" in result[0]["content"]


def test_split_markdown_sections_ignores_headings_in_fences_and_keeps_preamble():
    page = {
        "rel": "concepts/example.md", "title": "Example", "ptype": "concept",
        "body": "Intro\n\n```md\n# not heading\n```\n\n## Real\nText",
    }
    sections = split_markdown_sections(page, max_chars=100)
    assert [section["heading"] for section in sections] == ["", "Real"]
    assert "# not heading" in sections[0]["content"]
    assert "## Real" in sections[1]["content"]


def test_selector_finds_relevant_section_below_unrelated_intro_and_bounds_context():
    page = {
        "rel": "concepts/long.md", "title": "Long", "ptype": "concept",
        "body": "# Long\n\n## Unrelated\n\n" + ("filler text. " * 90)
                + "\n\n## Answer\n\nVietnamese investment risk diversification.",
    }
    excerpts = select_reflect_excerpts(
        "investment risk", [page], embedder=False,
        max_excerpt_chars=300, max_total_chars=300,
    )
    assert len(excerpts) == 1
    assert "## Answer" in excerpts[0]["content"]
    assert len(excerpts[0]["content"]) <= 300


def test_selector_returns_bounded_safe_fallback_for_empty_page():
    result = select_reflect_excerpts(
        "anything", [{"rel": "concepts/empty.md", "title": "Empty", "body": ""}],
        embedder=False, max_excerpt_chars=100, max_total_chars=50,
    )
    assert result == [{"path": "concepts/empty.md", "content": ""}]


def test_selector_drops_a_page_with_only_one_weak_query_token():
    result = select_reflect_excerpts(
        "what is my father's name",
        [{"rel": "entities/noise.md", "title": "Noise", "body": "## Notes\n\nWhat is new."}],
        embedder=False,
    )
    assert result == []


def test_splitter_keeps_each_fact_bullet_as_its_own_heading_context_chunk():
    page = {
        "rel": "people/example.md",
        "title": "Example Person",
        "body": "## Profile\n\n- First fact.\n- Second fact.\n- Third fact.",
    }

    chunks = split_markdown_sections(page, max_chars=1800)

    assert len(chunks) == 3
    assert all("## Profile" in chunk["content"] for chunk in chunks)
    assert [chunk["content"].splitlines()[-1] for chunk in chunks] == [
        "- First fact.", "- Second fact.", "- Third fact.",
    ]


def test_selector_uses_multilingual_semantic_relevance_between_atomic_facts():
    question = "bạn gái tôi làm nghề gì"
    target = "## Profile\n\n- Occupation: English teacher."

    class FakeEmbedder:
        def embed(self, values):
            vectors = {
                question: [1.0, 0.0],
                "## Profile\n\n- Birth date: 7 February 1997.": [0.0, 1.0],
                target: [0.2, 0.98],
            }
            return [vectors.get(value, [0.0, 1.0]) for value in values]

    page = {
        "rel": "people/example.md",
        "title": "Example Person",
        "body": "## Profile\n\n- Birth date: 7 February 1997.\n"
                "- Occupation: English teacher.",
    }
    excerpts = select_reflect_excerpts(
        question, [page], embedder=FakeEmbedder(), max_sections_per_page=1,
    )

    assert excerpts
    assert excerpts[0]["content"] == target


def test_selector_keeps_lower_ranked_fact_when_it_fits_page_context_budget():
    question = "bạn gái tôi làm nghề gì"
    target = "## Profile\n\n- Occupation: English teacher."
    facts = [
        "## Profile\n\n- Current address: Somewhere.",
        "## Profile\n\n- Gift purchase: A book.",
        "## Profile\n\n- Family detail: Has a sibling.",
        "## Profile\n\n- Date of birth: A date.",
        target,
    ]

    class FakeEmbedder:
        def embed(self, values):
            scores = {facts[0]: 0.9, facts[1]: 0.8, facts[2]: 0.7,
                      facts[3]: 0.6, target: 0.2}
            return [[1.0, 0.0] if value == question else
                    [scores.get(value, 0.0), (1 - scores.get(value, 0.0) ** 2) ** 0.5]
                    for value in values]

    page = {
        "rel": "people/example.md",
        "title": "Example Person",
        "body": "## Profile\n\n" + "\n".join(fact.split("\n\n", 1)[1] for fact in facts),
    }
    excerpts = select_reflect_excerpts(
        question, [page], embedder=FakeEmbedder(), max_excerpt_chars=1000,
    )

    assert excerpts
    assert "Occupation: English teacher" in excerpts[0]["content"]


def test_selector_groups_sections_by_original_page_path():
    page = {
        "rel": "people/example.md", "title": "Example",
        "body": "## Work\n\nProject planning.\n\n## Preferences\n\nPrefers clear planning.",
    }
    result = select_reflect_excerpts(
        "planning preferences", [page], embedder=False,
        max_sections_per_page=2, max_total_chars=500,
    )
    assert len(result) == 1
    assert result[0]["path"] == "people/example.md"
    assert "## Preferences" in result[0]["content"]


def test_retrieval_fuses_independent_channels_and_excludes_sources(monkeypatch):
    from obsidian_memory_core.wiki import fts

    pages = [
        {"rel": "people/relevant.md", "path": None, "title": "Relevant",
         "ptype": "people", "updated": "", "meta": {"aliases": []},
         "body": "## Answer\n\nInvestment risk needs diversification.", "text": "", "stem": "relevant"},
        {"rel": "sources/raw.md", "title": "Raw source", "ptype": "source",
         "updated": "", "meta": {}, "body": "Investment risk", "text": "", "stem": "raw"},
    ]

    class FakeVault:
        def load_pages(self):
            return pages

        def _keyword_search(self, query, limit=5, pages=None):
            return [{"path": "people/relevant.md", "title": "Relevant", "_phrase": True}]

    monkeypatch.setattr(fts, "ensure_fresh", lambda vault: {})
    monkeypatch.setattr(fts, "search_fts", lambda *args, **kwargs: [])
    embed_options = {}
    monkeypatch.setattr(
        fts, "_embedding_search",
        lambda *args, **kwargs: embed_options.update(kwargs) or [],
    )
    result = retrieve_reflect_excerpts(FakeVault(), "investment risk")
    assert [item["path"] for item in result] == ["people/relevant.md"]
    assert "Investment risk" in result[0]["content"]
    assert embed_options["threshold"] == 0.0
