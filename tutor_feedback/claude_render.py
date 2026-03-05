"""Stage B – render platform-specific feedback from extracted data via Claude."""

from __future__ import annotations

import json
import logging
import time

import anthropic

from tutor_feedback.models import ExtractedSession
from tutor_feedback.styles import StyleCard

log = logging.getLogger("tutor_feedback")

# ── Voice-matching instructions injected when examples exist ───────────

VOICE_MATCH_BLOCK = """\

VOICE MATCHING — CRITICAL:
You have been given real examples of feedback written by this tutor. Your \
output must be INDISTINGUISHABLE from the tutor's own writing. Study the \
examples carefully and match:
- Sentence length and rhythm (short or long? varied or uniform?)
- Vocabulary level (simple words or formal? contractions or not?)
- How they open and close
- Their specific turns of phrase, filler words, and hedging style
- How much detail they give (brief or thorough?)
- Punctuation habits (semicolons? dashes? exclamation marks?)
- Whether they use the student's name at the start, middle, or end
- The ratio of positive to constructive feedback

Do NOT "improve" or "polish" the tutor's style. If the examples are \
slightly informal, be slightly informal. If they use short blunt sentences, \
do the same. Reproduce the tutor's voice, not a better version of it.\
"""

# ── Anti-AI writing rules (always injected) ────────────────────────────

ANTI_AI_RULES = """\

WRITING STYLE — MANDATORY:
Your output must read like it was written by a real human tutor, not by AI. \
Follow these rules strictly:
- Do NOT open with "Great session today" or any generic opener. Vary how \
  you start — jump straight into content.
- Do NOT use the phrase "demonstrated a strong/solid understanding" or any \
  variation. Describe what actually happened instead.
- Do NOT use "delved into", "dove into", "honed", "showcased", \
  "exhibited", "navigated", "grasped", "mastered", "tackled", "keen", \
  "commendable", "noteworthy", "pivotal", "fostering", "leverage", \
  "holistic", or any other distinctively AI vocabulary.
- Do NOT use the structure "While X, Y" to introduce constructive \
  feedback. Find other ways to transition.
- Do NOT use three-part lists or triple adjectives ("clear, concise, and \
  effective"). Humans rarely do this naturally.
- Do NOT end with a cliché motivational line ("I look forward to \
  continuing this great progress!"). End with something concrete.
- Vary sentence length. Mix short punchy sentences with longer ones.
- Be specific: name the exact question, topic, or moment rather than \
  giving general praise.
- Use normal everyday words. "Got it right" beats "demonstrated proficiency".\
"""

# ── System prompts ─────────────────────────────────────────────────────

RENDER_SYSTEM = """\
You are ghostwriting tutor feedback. You will receive structured session \
data and a style card describing the platform's requirements.

OUTPUT RULES:
- Output ONLY the final feedback text. No preamble, no sign-off like \
  "Best regards, [Tutor Name]" unless the style card asks for it.
- Respect the word limit strictly.
- Include ALL required sections as headings (unless the style uses field-based \
  or chat format — then follow the field/format instructions exactly).
- Use the tone described in the style card.
- The feedback must be parent-safe: no tutor-private notes, no medical or \
  psychological speculation, no raw transcript quotes.
- Use evidence-based statements rather than quoting the transcript directly.\
""" + ANTI_AI_RULES

RENDER_FIELDS_SYSTEM = """\
You are ghostwriting tutor feedback. You will receive structured session \
data and a list of fields to populate for a platform form.

OUTPUT RULES:
- Output ONLY valid JSON: an object whose keys match the field names given.
- Each field value must be a string.
- Respect per-field word limits strictly.
- Use the tone described in the style card.
- The feedback must be parent-safe: no tutor-private notes, no medical or \
  psychological speculation, no raw transcript quotes.
- Use evidence-based statements rather than quoting the transcript directly.
- Do NOT add any keys beyond those listed. Do NOT wrap in markdown fences.\
""" + ANTI_AI_RULES


def _build_examples_block(style: StyleCard) -> str:
    """Build the few-shot examples section of the prompt."""
    if not style.examples:
        return ""

    parts = [
        "\n\n═══ EXAMPLES OF THE TUTOR'S REAL WRITING ═══\n"
        "Study these carefully. Your output must match this voice exactly.\n"
    ]
    for i, ex in enumerate(style.examples, 1):
        parts.append(f"--- Example {i} ---")
        parts.append(ex)
        parts.append("")

    parts.append("═══ END OF EXAMPLES ═══\n")
    return "\n".join(parts)


def build_render_prompt(
    extracted: ExtractedSession,
    style: StyleCard,
) -> str:
    extracted_text = json.dumps(extracted.model_dump(), indent=2, ensure_ascii=False)
    examples_block = _build_examples_block(style)
    voice_block = VOICE_MATCH_BLOCK if style.examples else ""

    if style.output_format == "fields" and style.fields:
        fields_desc = "\n".join(
            f"  - {f.name}: {f.description or f.label}"
            + (f" (max {f.word_limit} words)" if f.word_limit else "")
            + (" [required]" if f.required else " [optional]")
            for f in style.fields
        )
        style_text = (
            f"PLATFORM: {style.name}\n"
            f"Tone: {style.tone}\n"
            f"Output: JSON object with these fields:\n{fields_desc}\n"
            f"DO rules:\n" + "\n".join(f"  - {r}" for r in style.do_rules) + "\n"
            f"DON'T rules:\n" + "\n".join(f"  - {r}" for r in style.dont_rules)
        )
        return (
            f"{style_text}"
            f"{voice_block}"
            f"{examples_block}\n"
            f"SESSION DATA:\n{extracted_text}\n\n"
            f"Write the JSON now. Output ONLY the JSON object."
        )

    style_text = (
        f"STYLE CARD: {style.name}\n"
        f"Tone: {style.tone}\n"
        f"Word limit: {style.word_limit}\n"
        f"Format: {style.format}\n"
    )
    if style.required_sections:
        style_text += f"Required sections (in this order): {', '.join(style.required_sections)}\n"
    style_text += (
        f"DO rules:\n" + "\n".join(f"  - {r}" for r in style.do_rules) + "\n"
        f"DON'T rules:\n" + "\n".join(f"  - {r}" for r in style.dont_rules)
    )
    return (
        f"{style_text}"
        f"{voice_block}"
        f"{examples_block}\n"
        f"SESSION DATA:\n{extracted_text}\n\n"
        f"Write the feedback now. Output ONLY the feedback text."
    )


def render_feedback(
    extracted: ExtractedSession,
    style: StyleCard,
    *,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
    max_retries: int = 2,
) -> tuple[str, float]:
    """
    Render feedback for one platform.

    Returns (feedback_text, elapsed_seconds).
    For field-based styles, returns pretty-printed JSON with field labels.
    Retries on validation violations.
    """
    is_fields = style.output_format == "fields" and style.fields
    system = RENDER_FIELDS_SYSTEM if is_fields else RENDER_SYSTEM

    client = anthropic.Anthropic(api_key=api_key)
    user_msg = build_render_prompt(extracted, style)

    errors: list[str] = []
    for attempt in range(1, max_retries + 2):
        prompt = user_msg
        if errors:
            fix_type = "corrected JSON" if is_fields else "corrected feedback text"
            prompt += (
                "\n\n--- VALIDATION ERRORS FROM PREVIOUS ATTEMPT ---\n"
                + "\n".join(f"- {e}" for e in errors)
                + f"\n\nPlease fix these and output ONLY the {fix_type}."
            )

        log.info("Claude render [%s] – attempt %d/%d", style.name, attempt, max_retries + 1)
        t0 = time.time()

        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.time() - t0

        text = response.content[0].text.strip()

        if is_fields:
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.startswith("```")]
                text = "\n".join(lines)
            errors = _validate_fields_render(text, style)
            if not errors:
                text = _format_fields_output(text, style)
        else:
            errors = _validate_render(text, style)

        if not errors:
            log.info("Render [%s] validated on attempt %d (%.1fs)", style.name, attempt, elapsed)
            return text, elapsed

        log.warning("Render [%s] attempt %d issues: %s", style.name, attempt, errors)

    log.warning("Render [%s] returning best-effort after retries", style.name)
    return text, elapsed


def render_homework(extracted: ExtractedSession) -> str:
    """Build a consolidated homework summary (no LLM needed)."""
    if not extracted.homework:
        return "No homework was set this session."

    lines = [f"# Homework – {extracted.student_name}", ""]
    for i, hw in enumerate(extracted.homework, 1):
        lines.append(f"## Task {i}: {hw.task}")
        lines.append(f"{hw.instructions}")
        if hw.success_criteria:
            lines.append("\nSuccess criteria:")
            for sc in hw.success_criteria:
                lines.append(f"  - {sc}")
        if hw.estimated_time_minutes:
            lines.append(f"\nEstimated time: {hw.estimated_time_minutes} minutes")
        lines.append("")
    return "\n".join(lines)


def _validate_render(text: str, style: StyleCard) -> list[str]:
    """Quick validation checks for rendered feedback."""
    errors: list[str] = []
    word_count = len(text.split())
    if word_count > style.word_limit * 1.15:
        errors.append(
            f"Word count {word_count} exceeds limit {style.word_limit} "
            f"(+15% tolerance = {int(style.word_limit * 1.15)})"
        )
    for section in style.required_sections:
        if section.lower() not in text.lower():
            errors.append(f"Missing required section heading: '{section}'")
    return errors


def _validate_fields_render(text: str, style: StyleCard) -> list[str]:
    """Validate field-based JSON output."""
    errors: list[str] = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"Invalid JSON: {exc}"]

    if not isinstance(data, dict):
        return ["Output must be a JSON object"]

    for field in style.fields:
        if field.required and field.name not in data:
            errors.append(f"Missing required field: '{field.name}'")
        if field.name in data and field.word_limit:
            wc = len(str(data[field.name]).split())
            if wc > field.word_limit * 1.15:
                errors.append(
                    f"Field '{field.name}' has {wc} words, limit is {field.word_limit}"
                )
    return errors


def _format_fields_output(raw_json: str, style: StyleCard) -> str:
    """Format field-based JSON into a readable labelled output."""
    data = json.loads(raw_json)
    label_map = {f.name: (f.label or f.name) for f in style.fields}
    lines = []
    for field in style.fields:
        value = data.get(field.name, "")
        label = label_map.get(field.name, field.name)
        lines.append(f"[{label}]")
        lines.append(str(value).strip())
        lines.append("")
    return "\n".join(lines).strip()
