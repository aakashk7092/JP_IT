"""Unit tests for resume_customizer.py verifying section parsing, style preservation,
JSON response extraction, and the mandatory Truthfulness Guard.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import docx
from docx.shared import Pt, RGBColor
import pytest

from client_config import CandidateProfile
from llm_client import extract_json_from_response
from resume_customizer import (
    DocxToPdfConverterInterface,
    ResumeCustomizer,
    extract_resume_sections,
    normalize_skill,
    replace_paragraph_text_preserving_style,
    save_diff_report,
    validate_truthfulness,
)


class MockDocxToPdfConverter(DocxToPdfConverterInterface):
    """Offline mock converter for testing."""

    def convert(self, docx_path: Path, output_pdf_path: Path, timeout: float = 60.0) -> Path:
        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        output_pdf_path.write_bytes(b"%PDF-1.4 mock pdf content")
        return output_pdf_path


def create_sample_docx(file_path: Path) -> Path:
    """Helper to create a well-formed test DOCX file with styles."""
    doc = docx.Document()
    doc.add_heading("Alex Johnson", 0)

    doc.add_heading("PROFESSIONAL SUMMARY", level=1)
    p_sum = doc.add_paragraph()
    r_sum = p_sum.add_run("Experienced Java engineer with microservices expertise.")
    r_sum.bold = True
    r_sum.font.name = "Arial"
    r_sum.font.size = Pt(11)

    doc.add_heading("TECHNICAL SKILLS", level=1)
    doc.add_paragraph("Java, Spring Boot, PostgreSQL, Docker, AWS, Kafka")

    doc.add_heading("PROFESSIONAL EXPERIENCE", level=1)
    p_exp = doc.add_paragraph()
    r_exp = p_exp.add_run("Developed high-scale Spring Boot REST APIs handling millions of requests.")
    r_exp.italic = True
    r_exp.font.name = "Arial"

    doc.add_heading("EDUCATION", level=1)
    doc.add_paragraph("B.S. in Computer Science")

    doc.save(str(file_path))
    return file_path


def test_extract_resume_sections(tmp_path: Path):
    docx_file = create_sample_docx(tmp_path / "test_resume.docx")
    doc = docx.Document(str(docx_file))

    extracted = extract_resume_sections(doc)
    assert "Experienced Java engineer" in extracted.summary_text
    assert len(extracted.summary_paragraph_indices) == 1
    assert "Java" in extracted.skills_list
    assert "Spring Boot" in extracted.skills_list
    assert len(extracted.experience_bullets) == 1
    assert "Developed high-scale" in extracted.experience_bullets[0]


def test_replace_paragraph_text_preserving_style(tmp_path: Path):
    doc = docx.Document()
    p = doc.add_paragraph()
    run = p.add_run("Original text that needs replacement.")
    run.bold = True
    run.italic = False
    run.font.name = "Calibri"
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(0x10, 0x20, 0x30)

    new_text = "Tailored rewritten bullet point."
    replace_paragraph_text_preserving_style(p, new_text)

    assert p.text == new_text
    assert p.runs[0].bold is True
    assert p.runs[0].italic is False
    assert p.runs[0].font.name == "Calibri"
    assert p.runs[0].font.size == Pt(12)
    assert p.runs[0].font.color.rgb == RGBColor(0x10, 0x20, 0x30)


def test_extract_json_from_response():
    # Valid markdown-fenced json
    valid_markdown = """
    ```json
    {
      "rewritten_summary": "Seasoned Java Lead...",
      "rewritten_skills": ["Java", "Spring Boot"],
      "rewritten_paragraphs": ["Built services..."]
    }
    ```
    """
    res = extract_json_from_response(valid_markdown)
    assert res["rewritten_summary"] == "Seasoned Java Lead..."
    assert res["rewritten_skills"] == ["Java", "Spring Boot"]

    # Missing keys should raise ValueError
    invalid_schema = '{"rewritten_summary": "Only summary"}'
    with pytest.raises(ValueError) as exc:
        extract_json_from_response(invalid_schema)
    assert "missing required keys" in str(exc.value)


def test_truthfulness_guard_validation():
    original_skills = ["Java", "Spring Boot", "PostgreSQL", "Docker", "AWS"]
    original_text = "Java developer with 8 years building AWS microservices and PostgreSQL databases."
    jd_text = "Need Senior Java Developer with Spring Boot and AWS."

    # 1. Truthful case: only mentions skills from original
    truthful_skills = ["Java", "Spring Boot", "AWS", "PostgreSQL"]
    truthful_paras = ["Engineered Java microservices deployed to AWS."]
    is_valid, violations = validate_truthfulness(
        original_skills, original_text, truthful_skills, truthful_paras, jd_text
    )
    assert is_valid is True
    assert violations == []

    # 2. Fabricated case: introduces ungrounded technologies (Rust, Blockchain, Solidity)
    hallucinated_skills = ["Java", "Rust", "Solidity", "AWS"]
    is_valid_fake, fake_violations = validate_truthfulness(
        original_skills, original_text, hallucinated_skills, truthful_paras, jd_text
    )
    assert is_valid_fake is False
    assert "Rust" in fake_violations
    assert "Solidity" in fake_violations


def test_save_diff_report(tmp_path: Path):
    diff_file = save_diff_report(
        candidate_id="alex_test",
        original_text="Summary: Old summary\nSkills: Java\n",
        tailored_text="Summary: New tailored summary\nSkills: Java, AWS\n",
        scratch_dir=tmp_path / "scratch",
    )
    assert diff_file.exists()
    content = diff_file.read_text(encoding="utf-8")
    assert "Original_Resume" in content
    assert "Tailored_Resume" in content
    assert "+Summary: New tailored summary" in content


def test_customizer_fallback_on_truthfulness_failure(tmp_path: Path):
    docx_file = create_sample_docx(tmp_path / "alex_resume.docx")

    candidate = CandidateProfile(
        id="alex_test",
        name="Alex Test",
        email="alex@test.com",
        primary_role="Java Developer",
        experience_years=8,
        resume_path=str(docx_file),
        skills=["Java", "Spring Boot"],
    )

    # Mock LLM returning hallucinated skill 'Solidity'
    mock_llm = MagicMock()
    mock_llm.generate_tailored_content.return_value = {
        "rewritten_summary": "Blockchain developer",
        "rewritten_skills": ["Java", "Solidity", "Rust"],
        "rewritten_paragraphs": ["Wrote smart contracts"],
    }

    customizer = ResumeCustomizer(
        llm_client=mock_llm,
        converter=MockDocxToPdfConverter(),
        scratch_dir=tmp_path / "scratch",
    )

    result_path = customizer.customize_resume(
        candidate=candidate,
        job_description="Looking for Java developer",
        output_dir=tmp_path / "out",
    )

    # Must fall back to original resume because of hallucinated skills!
    assert result_path == docx_file


def test_customizer_success_with_mock_converter(tmp_path: Path):
    docx_file = create_sample_docx(tmp_path / "alex_good.docx")

    candidate = CandidateProfile(
        id="alex_good",
        name="Alex Good",
        email="alex@good.com",
        primary_role="Java Developer",
        experience_years=8,
        resume_path=str(docx_file),
        skills=["Java", "Spring Boot", "AWS"],
    )

    mock_llm = MagicMock()
    mock_llm.generate_tailored_content.return_value = {
        "rewritten_summary": "Top Java and Spring Boot Engineer.",
        "rewritten_skills": ["Java", "Spring Boot", "AWS"],
        "rewritten_paragraphs": ["Built enterprise services in Spring Boot."],
    }

    customizer = ResumeCustomizer(
        llm_client=mock_llm,
        converter=MockDocxToPdfConverter(),
        scratch_dir=tmp_path / "scratch",
    )

    result_path = customizer.customize_resume(
        candidate=candidate,
        job_description="Urgent Java Engineer role",
        output_dir=tmp_path / "out",
    )

    # Must produce tailored PDF successfully
    assert result_path.suffix == ".pdf"
    assert result_path.exists()
