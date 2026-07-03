"""Conversion pipeline: orchestrates the full HTML → MD process."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .citations import CitationMapper, CitationResult
from .converter import Converter
from .errors import ConversionError, WarningCollector
from .extractor import ExtractedDocument, Extractor
from .images import ImageProcessor
from .strategy import SiteStrategy
from .tables import TableConverter


@dataclass
class ConversionInfo:
    """Information about a single conversion for reporting."""
    input_path: str
    output_path: str | None
    success: bool
    stats: dict
    warnings: list[str]


@dataclass
class ConversionResult:
    """Full result of a conversion pipeline run."""

    md_content: str
    notes_md: str
    references_md: str
    citation_result: CitationResult
    output_path: Path
    warnings: list[str] = field(default_factory=list)


class Pipeline:
    """Orchestrates the complete HTML → Markdown conversion process.

    Pipeline stages:
    1. Extract: Load HTML, clean DOM, extract title/subtitle
    2. Tables: Split merged cells in all tables
    3. Citations: Collect bottom refs, replace superscripts
    4. Images: Extract base64 images, keep external URLs
    5. Convert: Render cleaned DOM to Markdown
    6. Assemble: Combine title, body, footnotes into final MD
    """

    def __init__(
        self,
        strategy: SiteStrategy,
        strict: bool = False,
    ):
        self.strategy = strategy
        self.collector = WarningCollector(strict=strict)

        # Initialize pipeline components
        self.extractor = Extractor(strategy, self.collector)
        self.table_converter = TableConverter(self.collector)
        self.citation_mapper = CitationMapper(strategy.citations, self.collector)
        self.image_processor = ImageProcessor(self.collector)

    def run(
        self,
        input_path: Path,
        output_dir: Path | None = None,
    ) -> ConversionResult:
        """Run the full conversion pipeline.

        Args:
            input_path: Path to the HTML file to convert.
            output_dir: Directory for output MD (and img/). None = same as input.

        Returns:
            ConversionResult with the final MD content and metadata.

        Raises:
            ConversionError: If in strict mode and an error occurs.
        """
        if output_dir is None:
            output_dir = input_path.parent

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Stage 1: Extract
        doc = self.extractor.extract(input_path)
        soup = doc.body_soup

        # Auto-detect base_url from canonical link if not configured
        if not self.strategy.links.base_url:
            canonical = soup.find("link", rel="canonical")
            if canonical and canonical.get("href"):
                from urllib.parse import urlparse
                parsed = urlparse(canonical["href"])
                self.strategy.links.base_url = f"{parsed.scheme}://{parsed.netloc}"

        # Get the main content area
        main_content = self.extractor.get_main_content(soup)
        if main_content is None:
            self.collector.warn(
                f"Main content not found with selector "
                f"'{self.strategy.content.main_selector}'. Using whole body."
            )
            main_content = soup.find("body") or soup

        # Stage 2: Tables - split merged cells
        self.table_converter.split_merged_cells(main_content)

        # Stage 3: Citations - collect from full DOM, replace in body.
        # References container is outside .mw-parser-output (sibling),
        # so we need the full soup for collection.
        citation_result = self.citation_mapper.process(soup)

        # Stage 4: Images - extract base64
        self.image_processor.process(main_content, output_dir)

        # Stage 5: Convert to Markdown
        converter = Converter(self.strategy, output_dir, self.collector)
        body_md = converter.convert(main_content)

        # Stage 6: Assemble final MD
        final_md = self._assemble(
            title=doc.title,
            subtitle=doc.subtitle,
            body_md=body_md,
            citation_result=citation_result,
        )

        # Write output
        output_filename = input_path.stem + ".md"
        output_path = output_dir / output_filename
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_md)

        return ConversionResult(
            md_content=final_md,
            notes_md="",
            references_md="",
            citation_result=citation_result,
            output_path=output_path,
            warnings=self.collector.flush(),
        )

    def _assemble(
        self,
        title: str,
        subtitle: str | None,
        body_md: str,
        citation_result: CitationResult,
    ) -> str:
        """Assemble the final Markdown document.

        Structure:
            # Title
            Subtitle
            [body content, with original ## Notes kept, ## References removed]
            ## References   (generated footnotes only)
        """
        import re

        parts: list[str] = []

        # Title
        if title:
            parts.append(f"# {title}\n")

        # Subtitle (source attribution)
        if subtitle:
            parts.append(f"{subtitle}\n")

        # Body: original References have been removed from DOM.
        # Original Notes section stays (letter notes are plain text there).
        parts.append(body_md.strip())

        # Generate footnote definitions for References only (notes are plain text)
        ref_citations = {
            f"ref_{c.display_name}": c
            for c in citation_result.references
        }
        _notes_md, refs_md = self.citation_mapper.generate_footnote_definitions(
            ref_citations
        )

        if refs_md.strip():
            parts.append(f"\n{refs_md.strip()}")

        result = "\n".join(parts)

        # Clean up: collapse 3+ newlines to 2
        result = re.sub(r"\n{3,}", "\n\n", result)

        return result + "\n"
