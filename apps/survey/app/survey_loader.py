"""Load survey definitions from YAML files (see surveys/ for the eCooking
panel instruments). Question texts are the exact SMS bodies per language;
the design requires each to fit one 160-character GSM-7 segment."""

from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import QUESTION_TYPES, SURVEY_MODULES, Question, Survey, SurveySession
from .sms_text import sms_segments


class SurveyDefinitionError(ValueError):
    pass


_CONDITION_OPS = ("equals", "not_equals", "in", "contains")


def _validate_conditions(conds, where: str) -> None:
    if not isinstance(conds, list):
        raise SurveyDefinitionError(f"{where}: conditions must be a list")
    for cond in conds:
        if not isinstance(cond, dict) or not cond.get("var"):
            raise SurveyDefinitionError(f"{where}: each condition needs a 'var'")
        if not any(op in cond for op in _CONDITION_OPS):
            raise SurveyDefinitionError(
                f"{where}: condition on {cond['var']!r} needs one of {', '.join(_CONDITION_OPS)}"
            )


def _validate_question(q: dict, i: int, path: Path, keys: set) -> None:
    where = f"{path}: question {i} ({q.get('key', '?')})"
    for f in ("key", "type", "text"):
        if not q.get(f):
            raise SurveyDefinitionError(f"{where} missing {f!r}")
    if q["type"] not in QUESTION_TYPES:
        raise SurveyDefinitionError(
            f"{where} has unknown type {q['type']!r} (expected one of {', '.join(QUESTION_TYPES)})"
        )
    if q["key"] in keys:
        raise SurveyDefinitionError(f"{path}: duplicate question key {q['key']!r}")
    keys.add(q["key"])
    if not isinstance(q["text"], dict) or not q["text"]:
        raise SurveyDefinitionError(
            f"{where}: 'text' must be a mapping of language to SMS body, e.g. {{en: ..., sw: ...}}"
        )
    if q["type"] in ("single", "multi"):
        if not isinstance(q.get("choices"), int) or q["choices"] < 2:
            raise SurveyDefinitionError(f"{where}: type {q['type']} needs integer 'choices' >= 2")
    if q["type"] != "system" and not q.get("var"):
        raise SurveyDefinitionError(f"{where}: non-system questions need a 'var' (codebook variable)")
    for cond_field in ("ask_if", "skip_if"):
        if q.get(cond_field) is not None:
            _validate_conditions(q[cond_field], f"{where}.{cond_field}")
    if q.get("sets") is not None and not (isinstance(q["sets"], dict) and q["sets"].get("attr")):
        raise SurveyDefinitionError(f"{where}: 'sets' needs an 'attr'")
    if q.get("end_if") is not None:
        if not isinstance(q["end_if"], dict) or "value" not in q["end_if"]:
            raise SurveyDefinitionError(f"{where}: 'end_if' needs a 'value'")


def _validate(data: dict, path: Path) -> None:
    for field in ("slug", "title", "questions"):
        if not data.get(field):
            raise SurveyDefinitionError(f"{path}: missing required field {field!r}")
    if data.get("module", "adhoc") not in SURVEY_MODULES:
        raise SurveyDefinitionError(
            f"{path}: unknown module {data['module']!r} (expected one of {', '.join(SURVEY_MODULES)})"
        )
    keys: set = set()
    for i, q in enumerate(data["questions"], 1):
        _validate_question(q, i, path, keys)


def load_survey_from_yaml(db: Session, path: str | Path) -> tuple[Survey, bool, list[str]]:
    """Create or replace a survey from a YAML file.

    Returns (survey, created, warnings). Refuses to touch a survey that
    already has sessions — dispatched surveys are immutable; use a new slug.
    """
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SurveyDefinitionError(f"{path}: expected a YAML mapping at top level")
    _validate(data, path)

    survey = db.scalar(select(Survey).where(Survey.slug == data["slug"]))
    created = survey is None
    if survey is not None:
        has_sessions = db.scalar(
            select(SurveySession.id).where(SurveySession.survey_id == survey.id).limit(1)
        )
        if has_sessions:
            raise SurveyDefinitionError(
                f"Survey {data['slug']!r} has already been dispatched; "
                "create a new survey with a different slug instead of editing it."
            )
        survey.questions.clear()
        db.flush()  # delete old questions before inserting replacements with the same keys
    else:
        survey = Survey(slug=data["slug"])
        db.add(survey)

    survey.title = data["title"]
    survey.module = data.get("module", "adhoc")
    survey.reward_kwh = float(data.get("reward_kwh", 0) or 0)
    survey.intro_text = (data.get("intro") or "").strip() or None
    survey.thanks_text = (data.get("thanks") or "").strip() or None

    for i, q in enumerate(data["questions"], 1):
        survey.questions.append(
            Question(
                position=i,
                key=str(q["key"]),
                var=q.get("var"),
                qtype=q["type"],
                texts={lang: str(body).strip() for lang, body in q["text"].items()},
                choices=q.get("choices"),
                min_value=q.get("min"),
                max_value=q.get("max"),
                ask_if=q.get("ask_if"),
                skip_if=q.get("skip_if"),
                sets=q.get("sets"),
                end_if=q.get("end_if"),
            )
        )

    warnings = []
    for question in survey.questions:
        for lang, body in question.texts.items():
            segments = sms_segments(body)
            if segments > 1:
                warnings.append(
                    f"question {question.key!r} ({lang}) renders as {segments} SMS segments "
                    "(design requires one) — shorten it"
                )

    db.commit()
    return survey, created, warnings


def load_survey_directory(db: Session, directory: str | Path = "surveys") -> dict:
    """Load every *.yaml instrument in a directory (skipping panel.yaml)."""
    directory = Path(directory)
    loaded, warnings = [], []
    for path in sorted(directory.glob("*.yaml")):
        if path.name == "panel.yaml":
            continue
        survey, created, warns = load_survey_from_yaml(db, path)
        loaded.append((survey.slug, "created" if created else "updated"))
        warnings.extend(f"{survey.slug}: {w}" for w in warns)
    return {"loaded": loaded, "warnings": warnings}
