import math
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Application


def recompute_job_shortlist(db: Session, job_id: uuid.UUID) -> int:
    """
    Rank all completed applications for `job_id` by `score_out_of_10` and mark
    the top 30th percentile as `is_shortlisted = True`, subject to a minimum
    quality floor (`shortlist_min_score`, default 6.0 / 10.0).
    Returns the number of shortlisted applications.
    """
    settings = get_settings()
    apps = (
        db.execute(
            select(Application)
            .where(
                Application.job_id == job_id,
                Application.status == "completed",
                Application.score_out_of_10.is_not(None),
            )
            .order_by(Application.score_out_of_10.desc(), Application.created_at.asc())
        )
        .scalars()
        .all()
    )

    total = len(apps)
    if total == 0:
        return 0

    top_slots = max(1, math.ceil(total * settings.shortlist_top_percent))
    shortlisted_count = 0

    for rank_idx, app_obj in enumerate(apps):
        # 1.00 = top rank, 0.00 = bottom rank (when total > 1)
        percentile = 1.0 if total == 1 else round(1.0 - (rank_idx / (total - 1)), 4)
        score = float(app_obj.score_out_of_10 or 0.0)
        eligible = rank_idx < top_slots and score >= settings.shortlist_min_score

        app_obj.percentile_rank = percentile
        app_obj.is_shortlisted = eligible
        if eligible:
            shortlisted_count += 1

    db.commit()
    return shortlisted_count
