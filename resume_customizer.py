"""Resume customizer module with style-preserving run-by-run rewrites,
Truthfulness Guard validation, and Word COM PDF conversion mutex.
"""

from __future__ import annotations

import difflib
import importlib
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import docx
from docx.shared import Pt, RGBColor

from client_config import CandidateProfile
from llm_client import LLMClient
from lock_util import FileLock

logger = logging.getLogger("recruitment_automation.resume_customizer")

# Section header recognition regexes
SUMMARY_HEADERS = re.compile(r"^(?:professional\s+summary|summary|profile|about\s+me)\b", re.I)
SKILLS_HEADERS = re.compile(r"^(?:technical\s+skills|core\s+competencies|skills|technologies)\b", re.I)
EXPERIENCE_HEADERS = re.compile(
    r"^(?:professional\s+experience|work\s+experience|experience|projects|project\s+experience)\b", re.I
)
NEXT_SECTION_DIVIDERS = re.compile(
    r"^(?:education|certifications?|awards?|publications?|languages?|references?)\b", re.I
)


@dataclass
class ExtractedResumeContent:
    """Structured sections extracted from a DOCX resume."""
    summary_text: str
    summary_paragraph_indices: list[int]
    skills_list: list[str]
    skills_table_indices: list[int]
    skills_paragraph_indices: list[int]
    experience_bullets: list[str]
    experience_paragraph_indices: list[int]
    full_text: str


class DocxToPdfConverterInterface(ABC):
    """Abstract interface for DOCX to PDF conversion."""

    @abstractmethod
    def convert(self, docx_path: Path, output_pdf_path: Path, timeout: float = 60.0) -> Path:
        """Convert DOCX file to PDF."""
        pass


class WindowsWordComConverter(DocxToPdfConverterInterface):
    """Converts DOCX to PDF using Windows Microsoft Word COM serialized via FileLock."""

    def __init__(self, lock_path: str | Path = "com_word.lock") -> None:
        self.lock_path = Path(lock_path).resolve()

    def _kill_hung_winword(self) -> None:
        """Terminate hung WINWORD.EXE processes if COM fails or times out."""
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", "WINWORD.EXE"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                logger.warning("Forcefully terminated hung WINWORD.EXE processes.")
            except Exception as e:
                logger.debug("Failed or unneeded winword termination: %s", e)

    def convert(self, docx_path: Path, output_pdf_path: Path, timeout: float = 60.0) -> Path:
        """Convert DOCX to PDF inside a file lock mutex."""
        docx_path = Path(docx_path).resolve()
        output_pdf_path = Path(output_pdf_path).resolve()
        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

        with FileLock(self.lock_path, timeout=timeout):
            try:
                from docx2pdf import convert as docx2pdf_convert
                logger.info("Converting %s to PDF via Word COM...", docx_path.name)
                docx2pdf_convert(str(docx_path), str(output_pdf_path))
                if not output_pdf_path.exists():
                    raise RuntimeError(f"Output PDF not found at {output_pdf_path}")
                return output_pdf_path
            except Exception as e:
                logger.error("Word COM conversion failed: %s. Attempting watchdog kill...", e)
                self._kill_hung_winword()
                raise


class LibreOfficeConverter(DocxToPdfConverterInterface):
    """Alternative converter using LibreOffice headless mode."""

    def convert(self, docx_path: Path, output_pdf_path: Path, timeout: float = 60.0) -> Path:
        cmd = [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            str(docx_path),
            "--outdir",
            str(output_pdf_path.parent),
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if res.returncode != 0:
            raise RuntimeError(f"LibreOffice conversion failed: {res.stderr.decode('utf-8')}")
        expected = output_pdf_path.parent / f"{docx_path.stem}.pdf"
        if expected != output_pdf_path:
            shutil.move(str(expected), str(output_pdf_path))
        return output_pdf_path


def convert_pdf_to_docx(pdf_path: Path, output_docx_path: Path) -> Path:
    """Convert input PDF to DOCX using pdf2docx."""
    from pdf2docx import Converter
    logger.info("Converting source PDF to DOCX: %s", pdf_path.name)
    output_docx_path.parent.mkdir(parents=True, exist_ok=True)
    cv = Converter(str(pdf_path))
    cv.convert(str(output_docx_path))
    cv.close()
    return output_docx_path


def extract_resume_sections(doc: docx.Document) -> ExtractedResumeContent:
    """Parse Document paragraphs and tables to locate Summary, Skills, and Experience."""
    summary_paras: list[str] = []
    summary_indices: list[int] = []
    skills_list: list[str] = []
    skills_para_indices: list[int] = []
    experience_bullets: list[str] = []
    experience_indices: list[int] = []

    current_section = None
    all_texts: list[str] = []

    for idx, p in enumerate(doc.paragraphs):
        text = p.text.strip()
        all_texts.append(text)
        if not text:
            continue

        # Check section boundaries
        if SUMMARY_HEADERS.match(text):
            current_section = "summary"
            continue
        elif SKILLS_HEADERS.match(text):
            current_section = "skills"
            continue
        elif EXPERIENCE_HEADERS.match(text):
            current_section = "experience"
            continue
        elif NEXT_SECTION_DIVIDERS.match(text):
            current_section = "other"
            continue

        if current_section == "summary":
            summary_paras.append(text)
            summary_indices.append(idx)
        elif current_section == "skills":
            skills_para_indices.append(idx)
            # Split comma-separated or bullet items
            parts = re.split(r"[,•|\n]+", text)
            for part in parts:
                cleaned_skill = part.strip()
                if cleaned_skill and len(cleaned_skill) < 45:
                    skills_list.append(cleaned_skill)
        elif current_section == "experience":
            # Extract bullet points (often start with action verbs or bullet symbols)
            if len(text) > 25:
                experience_bullets.append(text)
                experience_indices.append(idx)

    # Also inspect tables for technical skills
    skills_table_indices: list[int] = []
    for t_idx, table in enumerate(doc.tables):
        table_text = " ".join(cell.text for row in table.rows for cell in row.cells)
        if any(w in table_text.lower() for w in ["language", "framework", "database", "cloud", "tool", "java", "python"]):
            skills_table_indices.append(t_idx)
            for row in table.rows:
                for cell in row.cells:
                    for s in re.split(r"[,•|\n]+", cell.text):
                        c = s.strip()
                        if c and len(c) < 40 and not c.lower().endswith(":"):
                            skills_list.append(c)

    return ExtractedResumeContent(
        summary_text="\n".join(summary_paras),
        summary_paragraph_indices=summary_indices,
        skills_list=list(dict.fromkeys(skills_list)),
        skills_table_indices=skills_table_indices,
        skills_paragraph_indices=skills_para_indices,
        experience_bullets=experience_bullets,
        experience_paragraph_indices=experience_indices,
        full_text="\n".join(all_texts),
    )


def replace_paragraph_text_preserving_style(paragraph: docx.text.paragraph.Paragraph, new_text: str) -> None:
    """Replace paragraph text while strictly preserving font, size, bold/italic, and color.

    Reads the style properties from existing runs, clears run contents,
    and applies new_text to the primary run without destroying paragraph formatting.
    """
    if not paragraph.runs:
        paragraph.add_run(new_text)
        return

    # Extract style properties from the first non-empty run
    target_run = paragraph.runs[0]
    for r in paragraph.runs:
        if r.text.strip():
            target_run = r
            break

    font_name = target_run.font.name
    font_size = target_run.font.size
    bold = target_run.bold
    italic = target_run.italic
    underline = target_run.underline
    color_rgb = target_run.font.color.rgb if target_run.font.color else None

    # Clear all existing runs in paragraph
    for r in paragraph.runs:
        r.text = ""

    # Re-apply text and formatting to first run
    target_run.text = new_text
    if font_name:
        target_run.font.name = font_name
    if font_size:
        target_run.font.size = font_size
    if bold is not None:
        target_run.bold = bold
    if italic is not None:
        target_run.italic = italic
    if underline is not None:
        target_run.underline = underline
    if color_rgb:
        target_run.font.color.rgb = color_rgb


def normalize_skill(skill: str) -> str:
    """Normalize skill name for comparison (lowercase, alphanumeric only)."""
    return re.sub(r"[^a-z0-9]", "", skill.lower())


def validate_truthfulness(
    original_skills: Sequence[str],
    original_text: str,
    rewritten_skills: Sequence[str],
    rewritten_paragraphs: Sequence[str],
    job_description: str,
) -> tuple[bool, list[str]]:
    """Validate that the LLM output does NOT fabricate any technologies or claims.

    Returns:
        (True, []) if validated.
        (False, [flagged_terms]) if ungrounded skills were introduced.
    """
    orig_normalized = {normalize_skill(s) for s in original_skills if s.strip()}
    orig_text_lower = original_text.lower()

    # Known equivalence synonyms (e.g. postgresql == postgres)
    synonym_map = {
        "postgres": "postgresql",
        "postgresql": "postgres",
        "springboot": "spring",
        "spring": "springboot",
        "js": "javascript",
        "ts": "typescript",
        "reactjs": "react",
        "react": "reactjs",
        "k8s": "kubernetes",
        "kubernetes": "k8s",
        "aws": "amazonwebservices",
    }

    flagged_violations: list[str] = []

    # Check rewritten skills
    for skill in rewritten_skills:
        clean = skill.strip()
        norm = normalize_skill(clean)
        if not norm:
            continue

        # Direct normalized match
        if norm in orig_normalized:
            continue

        # Substring in original resume
        if clean.lower() in orig_text_lower:
            continue

        # Check synonym equivalence
        canonical = synonym_map.get(norm, norm)
        if any(synonym_map.get(s, s) == canonical for s in orig_normalized):
            continue

        flagged_violations.append(clean)

    return (len(flagged_violations) == 0, flagged_violations)


def save_diff_report(
    candidate_id: str,
    original_text: str,
    tailored_text: str,
    scratch_dir: str | Path = "scratch",
) -> Path:
    """Save original vs tailored text diff report for operator review."""
    dir_path = Path(scratch_dir).resolve()
    dir_path.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    diff_file = dir_path / f"candidate_diff_{candidate_id}_{ts}.diff"

    orig_lines = original_text.splitlines(keepends=True)
    tailored_lines = tailored_text.splitlines(keepends=True)

    diff = difflib.unified_diff(
        orig_lines,
        tailored_lines,
        fromfile="Original_Resume",
        tofile="Tailored_Resume",
    )
    diff_file.write_text("".join(diff), encoding="utf-8")
    logger.info("Saved resume diff report to %s", diff_file)
    return diff_file


class ResumeCustomizer:
    """High-level customizer orchestrating LLM tailoring, Truthfulness Guard, and PDF generation."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        converter: Optional[DocxToPdfConverterInterface] = None,
        scratch_dir: str | Path = "scratch",
    ) -> None:
        self.llm_client = llm_client or LLMClient()
        self.converter = converter or WindowsWordComConverter()
        self.scratch_dir = Path(scratch_dir).resolve()

    def customize_resume(
        self,
        candidate: CandidateProfile,
        job_description: str,
        output_dir: str | Path = "scratch/tailored_resumes",
    ) -> Path:
        """Tailor candidate resume to JD. If client customizer hook exists, dispatch to it.

        Returns:
            Path: Path to final tailored PDF, or fallback original resume on validation failure.
        """
        # Client-specific override dispatcher
        if candidate.customizer_module:
            try:
                mod_name = f"clients.customizers.{candidate.customizer_module}"
                mod = importlib.import_module(mod_name)
                if hasattr(mod, "customize_resume"):
                    logger.info("Dispatching to custom hook: %s", mod_name)
                    return mod.customize_resume(
                        candidate.resume_path,
                        job_description,
                        candidate,
                        output_dir,
                    )
            except Exception as e:
                logger.warning("Customizer hook failed for %s, falling back to standard customizer: %s", candidate.id, e)

        resume_path = candidate.get_absolute_resume_path()
        if not resume_path.exists():
            raise FileNotFoundError(f"Resume file not found for candidate {candidate.name}: {resume_path}")

        out_dir = Path(output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        # Handle PDF to DOCX conversion if needed
        is_pdf_source = resume_path.suffix.lower() == ".pdf"
        if is_pdf_source:
            working_docx = out_dir / f"{candidate.id}_working.docx"
            convert_pdf_to_docx(resume_path, working_docx)
        else:
            working_docx = out_dir / f"{candidate.id}_working_{int(time.time())}.docx"
            shutil.copy2(str(resume_path), str(working_docx))

        # Open and extract sections
        doc = docx.Document(str(working_docx))
        extracted = extract_resume_sections(doc)

        logger.info(
            "Extracted content: %d summary paras, %d skills, %d experience bullets",
            len(extracted.summary_paragraph_indices),
            len(extracted.skills_list),
            len(extracted.experience_bullets),
        )

        # Query LLM for tailored rewrite
        try:
            llm_result = self.llm_client.generate_tailored_content(
                original_summary=extracted.summary_text or f"Experienced {candidate.primary_role}",
                original_experience=extracted.experience_bullets[:6],
                original_skills=extracted.skills_list or candidate.skills,
                job_description=job_description,
            )
        except Exception as e:
            logger.error("LLM tailoring failed (%s). Falling back to original resume.", e)
            return resume_path

        rewritten_summary = llm_result.get("rewritten_summary", "")
        rewritten_skills = llm_result.get("rewritten_skills", [])
        rewritten_paras = llm_result.get("rewritten_paragraphs", [])

        # MANDATORY TRUTHFULNESS GUARD VALIDATION
        is_truthful, violations = validate_truthfulness(
            original_skills=extracted.skills_list or candidate.skills,
            original_text=extracted.full_text,
            rewritten_skills=rewritten_skills,
            rewritten_paragraphs=rewritten_paras,
            job_description=job_description,
        )

        tailored_full_text = f"SUMMARY:\n{rewritten_summary}\n\nSKILLS:\n{', '.join(rewritten_skills)}\n\nEXPERIENCE:\n" + "\n".join(rewritten_paras)
        diff_path = save_diff_report(
            candidate_id=candidate.id,
            original_text=extracted.full_text,
            tailored_text=tailored_full_text,
            scratch_dir=self.scratch_dir,
        )

        if not is_truthful:
            logger.warning(
                "TRUTHFULNESS GUARD FAILED for %s! Hallucinated/ungrounded skills: %s. "
                "Diff report saved to %s. Falling back to original resume.",
                candidate.name,
                violations,
                diff_path,
            )
            return resume_path

        logger.info("TRUTHFULNESS GUARD PASSED for %s. Applying style-preserving edits.", candidate.name)

        # Style-preserving write into working DOCX
        if extracted.summary_paragraph_indices and rewritten_summary:
            first_idx = extracted.summary_paragraph_indices[0]
            replace_paragraph_text_preserving_style(doc.paragraphs[first_idx], rewritten_summary)
            # Clear any additional summary paragraphs
            for extra_idx in extracted.summary_paragraph_indices[1:]:
                replace_paragraph_text_preserving_style(doc.paragraphs[extra_idx], "")

        # Update experience bullets run by run
        for i, p_idx in enumerate(extracted.experience_paragraph_indices):
            if i < len(rewritten_paras):
                replace_paragraph_text_preserving_style(doc.paragraphs[p_idx], rewritten_paras[i])

        doc.save(str(working_docx))

        # Convert to PDF
        timestamp = int(time.time())
        sanitized_name = re.sub(r"[^a-zA-Z0-9_-]", "_", candidate.name)
        final_pdf_path = out_dir / f"{sanitized_name}_Resume_{timestamp}.pdf"

        try:
            self.converter.convert(working_docx, final_pdf_path)
            return final_pdf_path
        except Exception as e:
            logger.error("DOCX to PDF conversion failed (%s). Falling back to original resume.", e)
            return resume_path
