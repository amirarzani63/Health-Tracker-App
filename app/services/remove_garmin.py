"""One-time clean-up (Nov 2026): the user stopped using Garmin and logs everything by hand.

Deletes what came from Garmin: synced workouts, daily wellness stats, Garmin weigh-ins, the saved
Garmin sign-in and the watch-calendar state. Typed-in data (food, water, steps, sleep, weights,
workouts logged by hand) is kept.
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Activity, DailyStats, Goals, StoredSecret, SyncState, WeightEntry

MARKER = "garmin-removed-v1"


def remove_garmin_data(db: Session) -> bool:
    if db.get(StoredSecret, MARKER):
        return False
    db.execute(delete(Activity).where(Activity.source == "garmin"))
    db.execute(delete(DailyStats))
    db.execute(delete(WeightEntry).where(WeightEntry.source == "garmin"))
    db.execute(delete(StoredSecret).where(StoredSecret.key.in_(["garmin_tokens", "garmin_plan"])))
    db.execute(delete(SyncState).where(SyncState.key.like("garmin%")))
    g = db.scalar(select(Goals))
    if g:
        g.follow_garmin = False
    db.add(StoredSecret(key=MARKER, value="done"))
    db.commit()
    return True
