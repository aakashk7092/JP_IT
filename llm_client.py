"""LLM Client orchestrator supporting multi-provider fallback chain.

Chain order: Gemini (primary) -> Groq (fallback) -> OpenRouter (fallback).
Enforces strict JSON schema validation and retry mechanics.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

logger = logging.getLogger("recruitment_automation.llm_client")

# System prompt enforcing the Truthfulness Guard and strict JSON output
SYSTEM_TAILORING_PROMPT = """
You are an expert Executive Resume Specialist and Technical Career Coach.
Your task is to tailor a candidate's resume content specifically to align with a Target Job Description (JD).

CRITICAL TRUTHFULNESS GUARD (STRICT MANDATORY RULES):
1. You must ONLY emphasize technologies, frameworks, and experience ALREADY explicitly present in the original resume.
2. NEVER invent, hallucinate, or add new employers, companies, job titles, employment dates, degrees, certifications, or technologies that are absent from the original resume.
3. If the JD requires a skill that the candidate does NOT possess in their original resume, DO NOT add it.
4. Highlight and foreground overlapping skills and rephrase bullet points with strong action verbs to directly address the JD's requirements without misrepresenting experience.

OUTPUT REQUIREMENTS:
You MUST respond with ONLY a valid, parseable JSON object matching this exact schema:
{
  "rewritten_summary": "A 3-4 sentence professional summary highlighting the candidate's existing background aligned with the JD.",
  "rewritten_skills": ["List", "of", "existing", "skills", "ordered", "by", "relevance", "to", "JD"],
  "rewritten_paragraphs": [
    "Rewritten bullet point 1 emphasizing relevant achievements...",
    "Rewritten bullet point 2 using strong action verbs..."
  ]
}
Do not include any conversational preamble, explanation, or markdown formatting outside of the JSON.
"""


def extract_json_from_response(text: str) -> dict[str, Any]:
    """Parse JSON from model response text, stripping any markdown code fences."""
    cleaned = text.strip()
    # Strip markdown ```json ... ``` blocks if present
    if cleaned.startswith("```"):
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if match:
            cleaned = match.group(1).strip()

    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response did not parse into a dictionary.")

    required_keys = {"rewritten_summary", "rewritten_skills", "rewritten_paragraphs"}
    missing = required_keys - set(parsed.keys())
    if missing:
        raise ValueError(f"LLM JSON missing required keys: {missing}")

    return parsed


class LLMClient:
    """Manages LLM API requests with automated fallback across providers."""

    def __init__(self, provider_chain: Optional[list[str]] = None) -> None:
        load_dotenv(override=True)
        chain_env = os.getenv("LLM_PROVIDER_CHAIN", "gemini,groq,openrouter")
        self.provider_chain = provider_chain or [p.strip().lower() for p in chain_env.split(",") if p.strip()]

        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        self.groq_key = os.getenv("GROQ_API_KEY", "")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")

    def call_gemini(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        as_json: bool = True,
    ) -> str:
        """Call Google Gemini model."""
        if not self.gemini_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.gemini_key}"
        sys_p = system_prompt if system_prompt is not None else SYSTEM_TAILORING_PROMPT
        content_text = f"{sys_p}\n\n{prompt}" if sys_p else prompt

        gen_config: dict[str, Any] = {"temperature": 0.2}
        if as_json:
            gen_config["responseMimeType"] = "application/json"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": content_text}
                    ]
                }
            ],
            "generationConfig": gen_config,
        }
        resp = requests.post(url, json=payload, timeout=40)
        resp.raise_for_status()

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError(f"Gemini returned no candidates: {data}")

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise ValueError("Gemini returned empty parts.")

        return parts[0].get("text", "")

    def call_groq(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        as_json: bool = True,
    ) -> str:
        """Call Groq API (fallback 1)."""
        if not self.groq_key:
            raise ValueError("GROQ_API_KEY is not configured.")

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json",
        }
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        sys_p = system_prompt if system_prompt is not None else SYSTEM_TAILORING_PROMPT
        messages = []
        if sys_p:
            messages.append({"role": "system", "content": sys_p})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }
        if as_json:
            payload["response_format"] = {"type": "json_object"}

        resp = requests.post(url, headers=headers, json=payload, timeout=40)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def call_openrouter(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        as_json: bool = True,
    ) -> str:
        """Call OpenRouter API (fallback 2)."""
        if not self.openrouter_key:
            raise ValueError("OPENROUTER_API_KEY is not configured.")

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://recruitment-automation.local",
            "X-Title": "Recruitment Outreach System",
        }
        model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")
        sys_p = system_prompt if system_prompt is not None else SYSTEM_TAILORING_PROMPT
        messages = []
        if sys_p:
            messages.append({"role": "system", "content": sys_p})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }
        if as_json:
            payload["response_format"] = {"type": "json_object"}

        resp = requests.post(url, headers=headers, json=payload, timeout=40)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def generate_freeform_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_retries: int = 1,
    ) -> str:
        """Generate freeform non-JSON text using the provider fallback chain."""
        last_error = None
        for provider in self.provider_chain:
            for attempt in range(max_retries + 1):
                try:
                    if provider == "gemini":
                        return self.call_gemini(prompt, system_prompt=system_prompt, as_json=False)
                    elif provider == "groq":
                        return self.call_groq(prompt, system_prompt=system_prompt, as_json=False)
                    elif provider == "openrouter":
                        return self.call_openrouter(prompt, system_prompt=system_prompt, as_json=False)
                    break
                except Exception as e:
                    last_error = e
                    time.sleep(1.0)
        raise RuntimeError(f"All LLM providers failed for text generation. Last error: {last_error}")

    def generate_tailored_content(
        self,
        original_summary: str,
        original_experience: list[str],
        original_skills: list[str],
        job_description: str,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """Generate tailored resume content using provider fallback chain."""
        prompt = (
            f"TARGET JOB DESCRIPTION:\n{job_description}\n\n"
            f"ORIGINAL PROFESSIONAL SUMMARY:\n{original_summary}\n\n"
            f"ORIGINAL TECHNICAL SKILLS:\n{', '.join(original_skills)}\n\n"
            f"ORIGINAL PROJECT EXPERIENCE BULLET POINTS:\n"
            + "\n".join(f"- {p}" for p in original_experience)
        )

        last_error = None

        for provider in self.provider_chain:
            logger.info("Attempting LLM call via provider: %s", provider)
            for attempt in range(max_retries + 1):
                try:
                    if provider == "gemini":
                        raw_response = self.call_gemini(prompt)
                    elif provider == "groq":
                        raw_response = self.call_groq(prompt)
                    elif provider == "openrouter":
                        raw_response = self.call_openrouter(prompt)
                    else:
                        logger.warning("Unknown provider: %s", provider)
                        break

                    parsed_json = extract_json_from_response(raw_response)
                    logger.info("Successfully generated and validated JSON with provider: %s", provider)
                    return parsed_json

                except Exception as e:
                    last_error = e
                    logger.warning("Provider %s attempt %d failed: %s", provider, attempt + 1, e)
                    time.sleep(1.0 * (attempt + 1))

        raise RuntimeError(
            f"All LLM providers in chain {self.provider_chain} failed. Last error: {last_error}"
        )
