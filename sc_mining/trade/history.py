from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from .models import Snapshot
from .decimal_math import precise


def key_json(key):
    return json.dumps(asdict(key), sort_keys=True)


class History:
    def __init__(self, db):
        self.db = db

    def record(self, snapshot):
        at = snapshot.at.astimezone(timezone.utc)
        if not snapshot.mean.is_finite() or snapshot.mean <= 0:
            return
        hour = at.replace(minute=0, second=0, microsecond=0).isoformat()
        with self.db.connection() as c:
            c.execute('INSERT INTO snapshots VALUES (?,?,?,?,?) ON CONFLICT(key,hour) DO UPDATE SET at=excluded.at,mean=excluded.mean,minimum=excluded.minimum WHERE excluded.at>=snapshots.at', (key_json(snapshot.key), hour, at.isoformat(), str(snapshot.mean), str(snapshot.minimum) if snapshot.minimum is not None else None))
            c.execute('DELETE FROM snapshots WHERE at<?', ((at-timedelta(days=90)).isoformat(),))

    def window(self, key, now):
        now = now.astimezone(timezone.utc)
        start = now - timedelta(hours=168)
        with self.db.connection() as c:
            rows = c.execute('SELECT * FROM snapshots WHERE key=? AND at>=? AND at<=? ORDER BY at', (key_json(key), start.isoformat(), now.isoformat())).fetchall()
        points = [Snapshot(key, datetime.fromisoformat(r['at']), Decimal(r['mean']), Decimal(r['minimum']) if r['minimum'] is not None else None) for r in rows]
        days = {}
        for p in points:
            days.setdefault(p.at.date(), []).append(p.mean)
        with precise([p.mean for p in points]):
            daily = [sum(values) / len(values) for values in days.values()]
            mean=sum(daily)/len(daily) if daily else None
        hour_count = int((now.replace(minute=0, second=0, microsecond=0) - start.replace(minute=0, second=0, microsecond=0)).total_seconds() / 3600) + 1
        return {'mean': mean, 'points': points, 'days': len(days), 'hours': len(points), 'coverage': len(points) / hour_count}
