from dataclasses import asdict, replace
from datetime import datetime, timedelta
from decimal import Decimal
import json
import threading
import time
from .catalog import Catalog
from .names import has_chinese, to_english
from .history import History
from .models import Item, PriceKey, PriceStats, ProviderResult, Quote, Snapshot


def encode_result(result):
    return json.dumps(asdict(result), default=lambda x: x.isoformat() if isinstance(x, datetime) else str(x), ensure_ascii=False)


def decode_result(text):
    d = json.loads(text)
    stats = tuple(PriceStats(PriceKey(**s['key']), Decimal(s['mean']) if s['mean'] is not None else None, Decimal(s['minimum']) if s['minimum'] is not None else None, s['count'], datetime.fromisoformat(s['observed_at']), Decimal(s['week_mean']) if s['week_mean'] is not None else None, s['history_note']) for s in d['stats'])
    quotes = tuple(Quote(q['id'], PriceKey(**q['key']), Decimal(q['price']), q['kind'], datetime.fromisoformat(q['expires_at']) if q['expires_at'] else None, q['url']) for q in d['quotes'])
    return ProviderResult(d['source'], d['state'], stats, quotes, tuple(Item(**i) for i in d['items']), datetime.fromisoformat(d['retry_after']) if d['retry_after'] else None, d['message'])


class MarketService:
    TIMEOUT = 25        # 秒
    RETRY_MIN = 5       # 查价失败后几分钟内用旧结果、不再联网

    def __init__(self, db, providers):
        self.db, self.providers = db, providers
        self.catalog, self.history = Catalog(db), History(db)
        self.lock = threading.RLock()
        self._key_locks = {}        # (物品, 品质档, 买/卖) → 锁：同一个查价连点两下只联网一次，不同物品可以同时查
        self.cancelled = threading.Event()
        for provider in providers:
            if hasattr(provider,'http'):provider.http.cancel_event=self.cancelled

    def lookup(self, query):
        found = {i.id: i for i in self.catalog.search(query)}
        errors = []
        for provider in self.providers:
            if self.cancelled.is_set():
                break
            try:
                items = provider.lookup(query)
                # UEX 只认英文名：中文搜不到时，用汉化包对照表换成英文再搜，并把中文记成别名
                if not items and has_chinese(query):
                    for en in to_english(query)[:3]:
                        items = list(items) + list(provider.lookup(en))
                        if self.cancelled.is_set():break
                    if items:
                        self.catalog.upsert(items)
                        for i in items:
                            if i.name in to_english(query)[:3]:
                                self.catalog.add_alias(i.id, query.strip())
                if self.cancelled.is_set():break
                self.catalog.upsert(items)
                found.update({i.id: i for i in items})
            except Exception:
                errors.append(provider.source.upper() + ' 搜索暂不可用')
        return sorted(found.values(), key=lambda i: i.name), '；'.join(errors)

    def refresh(self, item, quality_group, operation, now):
        """各来源的价格：1 小时内查过的直接用缓存；要联网的几个来源同时查（以前一个查完再查下一个）"""
        # 同一个（物品, 品质档, 买/卖）一次只查一个，连点两下不会重复联网；以前整把全局锁一直锁到联网结束，
        # 库存页一批查价被串成一个一个查，F8 的价格要排在后面等（审查 2026-10-31）
        with self.lock:
            klock = self._key_locks.setdefault((item.id, quality_group, operation), threading.Lock())
        with klock:
            slots, todo = [], []
            for provider in self.providers:
                key = json.dumps([provider.source, item.id, quality_group, operation])
                with self.db.connection() as c:
                    cached = c.execute('SELECT * FROM provider_cache WHERE cache_key=?', (key,)).fetchone()
                if cached and now < datetime.fromisoformat(cached['next_at']):
                    slots.append(decode_result(cached['payload']))
                    continue
                slots.append(None)
                todo.append((len(slots) - 1, provider, key, cached))
            fetched = {}

            def work(idx, provider):
                try:
                    fetched[idx] = provider.fetch(item, quality_group, operation, now)
                except Exception:
                    fetched[idx] = ProviderResult(provider.source, 'schema_error', message='来源发生异常，已停止使用该响应')
            threads = [threading.Thread(target=work, args=(idx, provider), daemon=True) for idx, provider, _, _ in todo]
            for th in threads:
                th.start()
            deadline = time.monotonic() + self.TIMEOUT    # 一次查价的总时限：单个请求有超时，但重试几次、翻好几页加起来能到一分钟
            for th in threads:
                th.join(max(0.0, deadline - time.monotonic()))
            for idx, provider, key, cached in todo:
                if self.cancelled.is_set():
                    break
                result = fetched.get(idx) or ProviderResult(provider.source, 'offline', message=f'{self.TIMEOUT} 秒内没查完')
                self.catalog.upsert(result.items)
                if result.state in ('ok', 'empty', 'partial'):
                    next_at = now + timedelta(hours=1)
                else:                                         # 失败（断网、超时、格式变化）：过几分钟再试，别锁死一小时；限流照对方给的时间
                    next_at = max(now + timedelta(minutes=self.RETRY_MIN), result.retry_after or now)
                if result.state in ('ok', 'empty', 'partial'):
                    at = now
                    if result.state == 'ok':
                        for stat in result.stats:
                            if stat.mean is not None and stat.count:
                                self.history.record(Snapshot(stat.key, now, stat.mean, stat.minimum))
                else:
                    at = datetime.fromisoformat(cached['at']) if cached else now
                    if cached:
                        prior = decode_result(cached['payload'])
                        if prior.stats:
                            result = replace(prior, state='stale', retry_after=result.retry_after, message='缓存数据，更新失败：' + result.message)
                with self.db.connection() as c:
                    c.execute('INSERT OR REPLACE INTO provider_cache VALUES (?,?,?,?)', (key, at.isoformat(), next_at.isoformat(), encode_result(result)))
                slots[idx] = result
            return [r for r in slots if r is not None]

    def cached_stats(self):
        with self.db.connection() as c:
            rows = c.execute('SELECT payload FROM provider_cache').fetchall()
        return [s for r in rows for s in decode_result(r[0]).stats]

    def cancel(self):
        self.cancelled.set()
