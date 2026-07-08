"""Management CLI. Installed as `survey` (see pyproject.toml), or run with
`python -m app.cli`."""

import csv
from datetime import datetime
from pathlib import Path

import httpx
import typer
from sqlalchemy import func, select

from .config import get_settings
from .db import SessionLocal, init_db
from .engine import dispatch_survey, handle_inbound, render_question
from .gateways import get_gateway
from .gridcook import fetch_accounts, import_accounts
from .models import Respondent, Reward, Survey, SurveySession, utcnow
from .panel import assign_arms, load_panel_plan, run_panel
from .phone import PhoneError, normalize_phone
from .results import survey_results
from .survey_loader import (
    SurveyDefinitionError,
    load_survey_directory,
    load_survey_from_yaml,
)

app = typer.Typer(help="Manage SMS surveys for minigrid customers.", no_args_is_help=True)
survey_app = typer.Typer(help="Create and inspect surveys.", no_args_is_help=True)
respondent_app = typer.Typer(help="Manage respondents.", no_args_is_help=True)
panel_app = typer.Typer(help="Run the eCooking panel schedule.", no_args_is_help=True)
rewards_app = typer.Typer(help="Electricity-credit rewards ledger.", no_args_is_help=True)
app.add_typer(survey_app, name="survey")
app.add_typer(respondent_app, name="respondent")
app.add_typer(panel_app, name="panel")
app.add_typer(rewards_app, name="rewards")


@app.callback()
def _startup() -> None:
    init_db()


def _get_survey_or_exit(db, slug: str) -> Survey:
    survey = db.scalar(select(Survey).where(Survey.slug == slug))
    if survey is None:
        typer.echo(f"No survey with slug {slug!r}. Load instruments with: survey panel load")
        raise typer.Exit(code=1)
    return survey


# --- surveys -----------------------------------------------------------------


@survey_app.command("load")
def survey_load(path: Path) -> None:
    """Create a survey from one YAML definition."""
    with SessionLocal() as db:
        try:
            survey, created, warnings = load_survey_from_yaml(db, path)
        except SurveyDefinitionError as exc:
            typer.echo(f"Error: {exc}")
            raise typer.Exit(code=1)
        verb = "Created" if created else "Updated"
        typer.echo(f"{verb} survey {survey.slug!r} with {len(survey.questions)} questions.")
        for warning in warnings:
            typer.echo(f"  warning: {warning}")


@survey_app.command("list")
def survey_list() -> None:
    """List surveys and their session counts."""
    with SessionLocal() as db:
        surveys = db.scalars(select(Survey).order_by(Survey.created_at)).all()
        if not surveys:
            typer.echo("No surveys yet. Load the panel instruments with: survey panel load")
            return
        for survey in surveys:
            statuses: dict[str, int] = {}
            for session in survey.sessions:
                statuses[session.status] = statuses.get(session.status, 0) + 1
            summary = ", ".join(f"{v} {k}" for k, v in sorted(statuses.items())) or "not dispatched"
            typer.echo(
                f"{survey.slug} [{survey.module}, {survey.reward_kwh:g} kWh]: "
                f"\"{survey.title}\" ({len(survey.questions)} questions) — {summary}"
            )


@survey_app.command("show")
def survey_show(slug: str, language: str = typer.Option("en", "--language", help="en or sw")) -> None:
    """Print a survey's messages as they will appear on the phone."""
    with SessionLocal() as db:
        survey = _get_survey_or_exit(db, slug)
        for question in survey.questions:
            tag = f"[{question.position}. {question.key}"
            if question.qtype == "system":
                tag += " (system)"
            if question.ask_if or question.skip_if:
                tag += " (conditional)"
            typer.echo(tag + "]")
            typer.echo(render_question(question, language))
            typer.echo("")


# --- respondents -------------------------------------------------------------


@respondent_app.command("add")
def respondent_add(
    phone: str,
    account_id: str = typer.Option(None, "--account-id", help="Household account ID (meter join key)"),
    name: str = typer.Option(None, "--name"),
    site: str = typer.Option(None, "--site", help="Village / minigrid site"),
    language: str = typer.Option("en", "--language", help="en or sw (S0 overrides at enrolment)"),
) -> None:
    """Register one respondent."""
    settings = get_settings()
    with SessionLocal() as db:
        try:
            normalized = normalize_phone(phone, settings.default_country)
        except PhoneError as exc:
            typer.echo(f"Error: {exc}")
            raise typer.Exit(code=1)
        if db.scalar(select(Respondent).where(Respondent.phone == normalized)):
            typer.echo(f"{normalized} is already registered.")
            raise typer.Exit(code=1)
        db.add(
            Respondent(
                phone=normalized, account_id=account_id, name=name, site=site, language=language
            )
        )
        db.commit()
        typer.echo(f"Added {normalized}" + (f" (account {account_id})" if account_id else ""))


@respondent_app.command("import")
def respondent_import(path: Path) -> None:
    """Import respondents from a CSV with columns: phone,account_id,name,site,language."""
    settings = get_settings()
    added = skipped = invalid = 0
    with SessionLocal() as db, path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            raw = (row.get("phone") or "").strip()
            try:
                normalized = normalize_phone(raw, settings.default_country)
            except PhoneError:
                typer.echo(f"  skipping invalid phone: {raw!r}")
                invalid += 1
                continue
            if db.scalar(select(Respondent).where(Respondent.phone == normalized)):
                skipped += 1
                continue
            db.add(
                Respondent(
                    phone=normalized,
                    account_id=(row.get("account_id") or "").strip() or None,
                    name=(row.get("name") or "").strip() or None,
                    site=(row.get("site") or "").strip() or None,
                    language=(row.get("language") or "en").strip() or "en",
                )
            )
            added += 1
        db.commit()
    typer.echo(f"Imported {added}; {skipped} already registered; {invalid} invalid.")


@respondent_app.command("import-gridcook")
def respondent_import_gridcook(
    base_url: str = typer.Option(
        None, "--base-url", help="GridCook API root (default: GRIDCOOK_API_BASE from .env)"
    ),
    site: str = typer.Option(None, "--site", help="Override the site (default: community_id)"),
    limit: int = typer.Option(None, "--limit", help="Cap the number of accounts (pilot runs)"),
) -> None:
    """Enrol the mini-grid accounts served by a GridCook API (apps/api).

    The dataset has no contact details, so each respondent gets the same
    deterministic placeholder phone number the monitoring dashboard shows;
    account_id stays the join key back to meter and billing data.
    """
    base = base_url or get_settings().gridcook_api_base
    try:
        accounts = fetch_accounts(base)
    except httpx.HTTPError as exc:
        typer.echo(f"Error: could not fetch accounts from {base}: {exc}")
        raise typer.Exit(code=1)
    if limit is not None:
        accounts = accounts[:limit]
    with SessionLocal() as db:
        added, skipped = import_accounts(db, accounts, site=site)
    typer.echo(f"Imported {added} of {len(accounts)} accounts from {base}; {skipped} already registered.")


@respondent_app.command("list")
def respondent_list(site: str = typer.Option(None, "--site")) -> None:
    """List respondents."""
    with SessionLocal() as db:
        query = select(Respondent).order_by(Respondent.created_at)
        if site:
            query = query.where(Respondent.site == site)
        respondents = db.scalars(query).all()
        if not respondents:
            typer.echo("No respondents yet. Add one with: survey respondent add <phone>")
            return
        for r in respondents:
            flags = []
            if r.opted_out:
                flags.append("opted out")
            if r.consented_at:
                flags.append("consented")
            if r.rested:
                flags.append("rested")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            typer.echo(
                f"{r.phone}  acct={r.account_id or '-'}  {r.name or '-'}  {r.site or '-'}  "
                f"lang={r.language}  arm={r.arm or '-'}{suffix}"
            )


# --- panel -------------------------------------------------------------------


@panel_app.command("load")
def panel_load(directory: Path = typer.Argument(Path("surveys"))) -> None:
    """Load every instrument YAML in the surveys directory and check panel.yaml."""
    with SessionLocal() as db:
        try:
            result = load_survey_directory(db, directory)
        except SurveyDefinitionError as exc:
            typer.echo(f"Error: {exc}")
            raise typer.Exit(code=1)
        for slug, verb in result["loaded"]:
            typer.echo(f"{verb} {slug}")
        for warning in result["warnings"]:
            typer.echo(f"  warning: {warning}")

        plan = load_panel_plan(directory / "panel.yaml")
        existing = {s.slug for s in db.scalars(select(Survey))}
        missing = [slug for slug in plan.slugs if slug not in existing]
        if missing:
            typer.echo(f"Error: panel.yaml references missing surveys: {', '.join(missing)}")
            raise typer.Exit(code=1)
        typer.echo(f"Panel plan OK ({len(plan.slugs)} instruments).")


@panel_app.command("run")
def panel_run(
    slot: str = typer.Option(
        None, "--slot", help="morning|midday|evening — only households preferring this slot"
    ),
    plan_path: Path = typer.Option(Path("surveys/panel.yaml"), "--plan"),
) -> None:
    """One scheduler pass: expire (48h), remind (24h), dispatch due sessions.

    Run from cron once per slot, e.g.:  0 7,12,19 * * *  survey panel run --slot ...
    """
    if slot and slot not in ("morning", "midday", "evening"):
        typer.echo("Error: --slot must be morning, midday or evening")
        raise typer.Exit(code=1)
    with SessionLocal() as db:
        plan = load_panel_plan(plan_path)
        counts = run_panel(db, get_gateway(), plan=plan, slot=slot)
        typer.echo(
            f"Dispatched {counts['dispatched']}; reminded {counts['reminded']}; "
            f"expired {counts['expired']}; rested {counts['rested']}."
        )


@panel_app.command("assign-arms")
def panel_assign_arms(seed: int = typer.Option(None, "--seed", help="For a reproducible draw")) -> None:
    """Randomise credit-window arms A/B/C (40/40/20), stratified by village x EPC."""
    with SessionLocal() as db:
        counts = assign_arms(db, seed=seed)
        typer.echo(
            f"Assigned arms across {counts['strata']} strata: "
            f"A={counts['A']} B={counts['B']} C={counts['C']}"
        )


@panel_app.command("status")
def panel_status() -> None:
    """Panel health at a glance."""
    with SessionLocal() as db:
        total = db.scalar(select(func.count(Respondent.id)))
        consented = db.scalar(select(func.count()).where(Respondent.consented_at.is_not(None)))
        opted_out = db.scalar(select(func.count()).where(Respondent.opted_out == True))  # noqa: E712
        rested = db.scalar(select(func.count()).where(Respondent.rested == True))  # noqa: E712
        typer.echo(f"Respondents: {total} ({consented} consented, {opted_out} opted out, {rested} rested)")
        for arm in ("A", "B", "C"):
            n = db.scalar(select(func.count()).where(Respondent.arm == arm))
            typer.echo(f"  arm {arm}: {n}")
        typer.echo("Sessions:")
        rows = db.execute(
            select(Survey.slug, SurveySession.status, func.count())
            .join(SurveySession, SurveySession.survey_id == Survey.id)
            .group_by(Survey.slug, SurveySession.status)
            .order_by(Survey.slug)
        ).all()
        for slug, status, n in rows:
            typer.echo(f"  {slug}: {n} {status}")
        pending = db.scalar(select(func.coalesce(func.sum(Reward.kwh), 0)).where(Reward.status == "pending"))
        typer.echo(f"Rewards pending delivery: {pending:g} kWh")


# --- rewards -----------------------------------------------------------------


@rewards_app.command("export")
def rewards_export(
    out: Path,
    include_delivered: bool = typer.Option(False, "--all", help="Include delivered rewards"),
) -> None:
    """Export the rewards ledger to CSV for the vending/billing system.

    Arms A and C credits must be provisioned as daytime-window (10:00-15:00)
    tokens; arm B credits are unrestricted.
    """
    with SessionLocal() as db:
        query = select(Reward).order_by(Reward.created_at)
        if not include_delivered:
            query = query.where(Reward.status == "pending")
        rewards = db.scalars(query).all()
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                ["reward_id", "account_id", "phone", "arm", "window", "kwh", "kind", "status", "created_at"]
            )
            for reward in rewards:
                r = reward.respondent
                window = "anytime" if r.arm == "B" else "daytime"
                writer.writerow(
                    [
                        reward.id, r.account_id or "", r.phone, r.arm or "", window,
                        f"{reward.kwh:g}", reward.kind, reward.status,
                        reward.created_at.isoformat(),
                    ]
                )
        typer.echo(f"Wrote {len(rewards)} rewards to {out}")


@rewards_app.command("mark-delivered")
def rewards_mark_delivered(
    ids: list[int] = typer.Argument(None, help="Reward IDs; omit to mark ALL pending"),
) -> None:
    """Mark rewards delivered after loading them into the vending system."""
    with SessionLocal() as db:
        query = select(Reward).where(Reward.status == "pending")
        if ids:
            query = query.where(Reward.id.in_(ids))
        rewards = db.scalars(query).all()
        for reward in rewards:
            reward.status = "delivered"
            reward.delivered_at = utcnow()
        db.commit()
        typer.echo(f"Marked {len(rewards)} rewards delivered.")


# --- shared ------------------------------------------------------------------


@app.command("dispatch")
def dispatch(
    slug: str,
    site: str = typer.Option(None, "--site", help="Only respondents at this site"),
    resend: bool = typer.Option(False, "--resend", help="Re-survey people who already had this survey"),
    limit: int = typer.Option(None, "--limit", help="Cap the number of respondents (pilot runs)"),
) -> None:
    """Manually send one survey to all eligible respondents (bypasses the panel calendar)."""
    with SessionLocal() as db:
        survey = _get_survey_or_exit(db, slug)
        counts = dispatch_survey(db, survey, get_gateway(), site=site, resend=resend, limit=limit)
        typer.echo(f"Dispatched to {counts['sent']} respondents ({counts['skipped']} skipped).")


@app.command("reply")
def reply(phone: str, text: str) -> None:
    """Simulate an inbound SMS from a respondent (local testing)."""
    with SessionLocal() as db:
        replies = handle_inbound(db, phone, text, get_gateway())
        if not replies:
            typer.echo("(no reply sent — unknown number or no active session)")


@app.command("export")
def export(slug: str, out: Path) -> None:
    """Export a survey's results to CSV, one row per respondent session."""
    with SessionLocal() as db:
        survey = _get_survey_or_exit(db, slug)
        columns, rows = survey_results(db, survey)
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        typer.echo(f"Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    app()
