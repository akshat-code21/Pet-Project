"""
Alert checker node.
Rule-based scoring — no LLM calls.
Creates alerts in DB and triggers email for high/critical severity.
"""
import uuid
from datetime import datetime, timedelta, timezone

import structlog

from agents.state import PipelineState
from services.alert_service import score_alert

logger = structlog.get_logger()


def alert_checker_node(state: PipelineState) -> PipelineState:
    investor_id = state.get("investor_id", "")
    user_id = state.get("user_id", "")
    content_item_id = state.get("content_item_id", "")
    content_type = state.get("content_type", "")
    entities = state.get("entities", [])
    theses = state.get("theses", [])
    cleaned_text = state.get("cleaned_text", "")

    if not investor_id or not user_id:
        return {**state, "alerts_created": []}

    # Minimum quality gate
    if len(cleaned_text) < 200:
        return {**state, "alerts_created": []}

    created_ids: list[str] = []

    import asyncio
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_create_alerts_async(
            investor_id=investor_id,
            user_id=user_id,
            content_item_id=content_item_id,
            content_type=content_type,
            entities=entities,
            theses=theses,
            created_ids=created_ids,
        ))
    except RuntimeError:
        pass

    return {**state, "alerts_created": created_ids}


async def _create_alerts_async(
    investor_id: str,
    user_id: str,
    content_item_id: str,
    content_type: str,
    entities: list,
    theses: list,
    created_ids: list,
) -> None:
    from database.connection import AsyncSessionLocal
    from models.alert import Alert
    from sqlalchemy import select
    from services.email_service import send_alert_email

    now = datetime.now(timezone.utc)
    cooldown_cutoff = now - timedelta(days=7)

    async with AsyncSessionLocal() as db:
        # Check existing alerts in cooldown window
        from sqlalchemy import func
        existing = (await db.execute(
            select(Alert.alert_type, Alert.investor_id)
            .where(
                Alert.investor_id == uuid.UUID(investor_id),
                Alert.created_at > cooldown_cutoff,
            )
        )).all()
        cooldown_set = {(str(row.investor_id), row.alert_type) for row in existing}

        alerts_to_create = []

        # 1. Filing alert
        if content_type == "filing":
            base = "new_filing"
            if (investor_id, base) not in cooldown_set:
                score, severity = score_alert(base, is_new_position=True)
                alerts_to_create.append(Alert(
                    user_id=uuid.UUID(user_id),
                    investor_id=uuid.UUID(investor_id),
                    content_item_id=uuid.UUID(content_item_id),
                    alert_type=base,
                    title="New 13F Filing Detected",
                    summary="A new 13F SEC filing has been processed and parsed.",
                    severity=severity,
                    score=score,
                    extra_metadata={"content_type": content_type},
                ))

        # 2. Per-entity alerts
        for entity in entities:
            ticker = entity.get("ticker_symbol")
            name = entity.get("entity_name", "")
            conviction = entity.get("conviction_level")
            sentiment = entity.get("sentiment")
            context = entity.get("context_snippet") or ""

            base = "new_company_mention"
            key = (investor_id, base)
            if ticker and key not in cooldown_set:
                score, severity = score_alert(
                    base,
                    conviction=conviction,
                    sentiment=sentiment,
                    context_length=len(context),
                )
                alerts_to_create.append(Alert(
                    user_id=uuid.UUID(user_id),
                    investor_id=uuid.UUID(investor_id),
                    content_item_id=uuid.UUID(content_item_id),
                    alert_type=base,
                    title=f"New Mention — ${ticker}" if ticker else f"New Mention — {name}",
                    summary=context[:300] if context else f"{name} mentioned.",
                    severity=severity,
                    score=score,
                    extra_metadata={"ticker": ticker, "entity_name": name, "sentiment": sentiment},
                ))

            if conviction == "high":
                hc_key = (investor_id, "high_conviction")
                if hc_key not in cooldown_set:
                    score, severity = score_alert("new_company_mention", conviction="high", sentiment=sentiment)
                    score = min(100, score + 10)
                    severity = "high" if score >= 60 else "medium"
                    alerts_to_create.append(Alert(
                        user_id=uuid.UUID(user_id),
                        investor_id=uuid.UUID(investor_id),
                        content_item_id=uuid.UUID(content_item_id),
                        alert_type="high_conviction",
                        title=f"High Conviction Mention — {name}",
                        summary=context[:300],
                        severity=severity,
                        score=score,
                        extra_metadata={"ticker": ticker, "entity_name": name},
                    ))

        # 3. Thesis alerts
        for thesis in theses:
            base = "new_thesis"
            if (investor_id, base) not in cooldown_set:
                score, severity = score_alert(base, conviction="high" if thesis.get("conviction_score", 5) >= 7 else "medium")
                alerts_to_create.append(Alert(
                    user_id=uuid.UUID(user_id),
                    investor_id=uuid.UUID(investor_id),
                    content_item_id=uuid.UUID(content_item_id),
                    alert_type=base,
                    title=f"Investment Thesis — {thesis.get('company', '')}",
                    summary=thesis.get("thesis_summary", "")[:300],
                    severity=severity,
                    score=score,
                    extra_metadata={"ticker": thesis.get("ticker"), "company": thesis.get("company")},
                ))

        for alert in alerts_to_create:
            db.add(alert)
        await db.commit()

        # Email for critical/high
        for alert in alerts_to_create:
            if alert.severity in ("critical", "high") and not alert.email_sent:
                try:
                    await send_alert_email(str(user_id), alert)
                    alert.email_sent = True
                except Exception as e:
                    logger.warning("Email send failed", alert_id=str(alert.id), error=str(e))
        await db.commit()

        created_ids.extend([str(a.id) for a in alerts_to_create])
        logger.info("Alerts created", count=len(alerts_to_create), investor_id=investor_id)
