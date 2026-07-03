"""Tests for strategy loading and detection."""

from pathlib import Path

from html2md.strategy import CitationConfig, ContentConfig, SiteStrategy


class TestStrategyLoading:
    """Test YAML strategy loading."""

    def test_load_wikipedia_en(self):
        sites_dir = Path(__file__).parent.parent / "sites"
        strategy = SiteStrategy.from_yaml(sites_dir / "wikipedia_en.yaml")

        assert strategy.site_id == "wikipedia_en"
        assert "en.wikipedia.org" in strategy.url_patterns
        assert strategy.content.main_selector == ".mw-parser-output"
        assert strategy.citations.display_number_attr == "data-mw-footnote-number"
        assert strategy.elements.toc_handling == "remove"
        assert strategy.links.base_url == "https://en.wikipedia.org"

    def test_load_all_strategies(self):
        sites_dir = Path(__file__).parent.parent / "sites"
        strategies = SiteStrategy.load_all(sites_dir)

        assert "wikipedia_en" in strategies
        assert "wikipedia_jp" in strategies
        assert "fandom" in strategies
        assert "zeldawiki" in strategies
        assert len(strategies) == 4

    def test_content_config_defaults(self):
        config = ContentConfig()
        assert config.main_selector == ".mw-parser-output"
        assert config.title_selector == "#firstHeading"

    def test_citation_config_defaults(self):
        config = CitationConfig()
        assert config.superscript_selector == "sup.reference"
        assert config.display_number_attr == "data-mw-footnote-number"


class TestStrategyDetection:
    """Test heuristic site detection."""

    def test_detect_wikipedia_en_by_title(self):
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
        <meta charset="UTF-8">
        <title>Metal Gear Solid - Wikipedia</title>
        <meta name="generator" content="MediaWiki 1.47.0">
        </head>
        <body></body>
        </html>
        """
        sites_dir = Path(__file__).parent.parent / "sites"
        strategies = SiteStrategy.load_all(sites_dir)

        # Should detect by title containing "Wikipedia"
        result = SiteStrategy.detect(html, url_hint=None, strategies=strategies)
        assert result.site_id == "wikipedia_en"

    def test_detect_wikipedia_jp_by_lang(self):
        html = """
        <!DOCTYPE html>
        <html lang="ja">
        <head>
        <meta charset="UTF-8">
        <title>メタルギアソリッド - Wikipedia</title>
        <meta name="generator" content="MediaWiki 1.47.0">
        </head>
        <body></body>
        </html>
        """
        sites_dir = Path(__file__).parent.parent / "sites"
        strategies = SiteStrategy.load_all(sites_dir)

        # Should detect by lang="ja" + MediaWiki
        result = SiteStrategy.detect(html, url_hint=None, strategies=strategies)
        assert result.site_id == "wikipedia_jp"

    def test_detect_by_url(self):
        html = "<html></html>"
        sites_dir = Path(__file__).parent.parent / "sites"
        strategies = SiteStrategy.load_all(sites_dir)

        result = SiteStrategy.detect(
            html, url_hint="https://en.wikipedia.org/wiki/Test", strategies=strategies
        )
        assert result.site_id == "wikipedia_en"

        result = SiteStrategy.detect(
            html, url_hint="https://metalgear.fandom.com/wiki/Test", strategies=strategies
        )
        assert result.site_id == "fandom"
