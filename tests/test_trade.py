"""交易底层：物品目录、库存数据库、中英文名、OCR 行解析、价格统计、市场缓存、UEX/SCM 数据源"""
from sc_mining.trade.storage import Database
from sc_mining.trade.catalog import Catalog
from sc_mining.trade.models import Item
import sqlite3  # noqa: F401
import pytest
from sc_mining.trade.inventory import Inventory
from sc_mining.trade.models import Item, StockKey, StockLine  # noqa: F811
from datetime import datetime, timezone
from sc_mining.trade.models import Item, OcrToken  # noqa: F811
from sc_mining.trade.names import to_english, has_chinese
from sc_mining.trade.parser import parse_inventory
from sc_mining.trade.market_service import MarketService
from dataclasses import replace
from pathlib import Path
import shutil  # noqa: F401
from PIL import Image, ImageDraw, ImageFont  # noqa: F401
from sc_mining.trade.models import Item, OcrToken, ImportRow  # noqa: F811
from sc_mining.trade.parser import parse_inventory, validate_rows  # noqa: F811
from datetime import datetime, timedelta, timezone  # noqa: F811
from decimal import Decimal as D
from sc_mining.trade.models import PriceKey, Quote, Snapshot, PriceStats, StockKey, StockLine  # noqa: F811
from sc_mining.trade.pricing import aggregate, value_stock
from sc_mining.trade.history import History
from sc_mining.trade.models import Item, PriceKey, PriceStats, ProviderResult  # noqa: F811
import json
from datetime import datetime, timezone, timedelta  # noqa: F811
from decimal import Decimal
from tests import fakehttp as httpx
from sc_mining.trade.providers.http import HttpTransport, SourceError, decimal_price
from sc_mining.trade.providers.uex import UexProvider
from sc_mining.trade.providers.scm import ScmProvider


# ======================================================================
# 物品目录
# ======================================================================

def test_persistent_catalog(tmp_path):
    path = tmp_path / 'live.db'
    catalog = Catalog(Database(path))
    catalog.upsert([Item('a', 'FR-86', 'uuid-86'), Item('b', 'FR-76', None)])
    catalog.add_alias('a', '护盾86')
    reopened = Catalog(Database(path))
    assert reopened.search('fr-86')[0].id == 'a'
    assert reopened.search('护盾86')[0].id == 'a'
    assert len(reopened.search('FR-')) == 2
    assert len(reopened.search('')) == 2


def test_source_mapping_is_explicit(tmp_path):
    catalog = Catalog(Database(tmp_path / 'live.db'))
    catalog.upsert([Item('a', 'FR-86', None)])
    catalog.map_source('uex', '7', 'a')
    assert catalog.source_id('uex', 'a') == '7'
    assert catalog.source_id('scm', 'a') is None


# ======================================================================
# 库存数据库
# ======================================================================

def test_connection_rolls_back(tmp_path):
    db = Database(tmp_path / 'live.db')
    with pytest.raises(RuntimeError):
        with db.connection() as c:
            c.execute("insert into items(id,name,uuid) values ('a','test',null)")
            raise RuntimeError('cancel')
    assert Catalog(db).search('') == []


# ======================================================================
# 库存出入库
# ======================================================================

@pytest.fixture
def inv(tmp_path):
    db = Database(tmp_path / 'stock.db')
    Catalog(db).upsert([Item('a', 'FR-86'), Item('b', 'Helmet')])
    return Inventory(db)


def key(location='Port Tressler', quality='unknown'):
    return StockKey('a', quality, location, 'unit')


def add(inv, n=2, k=None, image_hash=None):
    return inv.commit(inv.prepare([StockLine(k or key(), n)], 'add', image_hash))


def test_add_and_reopen(inv):
    add(inv, 2)
    add(inv, 3)
    assert Inventory(Database(inv.db.path)).list_stock() == [StockLine(key(), 5)]
    assert len(inv.history()) == 2


def test_count_duplicate_rows(inv):
    add(inv, 7)
    add(inv, 9, key('C2'))
    preview = inv.prepare([StockLine(key(), 2), StockLine(key(), 3)], 'count')
    assert preview.lines == (StockLine(key(), 5),)
    inv.commit(preview)
    assert {s.key.location: s.quantity for s in inv.list_stock()} == {'Port Tressler': 5, 'C2': 9}


def test_negative_and_atomic_move(inv):
    add(inv)
    with pytest.raises(ValueError):
        inv.move(key(), 'C2', 3)
    assert inv.list_stock() == [StockLine(key(), 2)]
    inv.move(key(), 'C2', 1)
    assert sorted(s.quantity for s in inv.list_stock()) == [1, 1]


def test_duplicate_hash_requires_confirmation(inv):
    add(inv, image_hash='abcd')
    p = inv.prepare([StockLine(key(), 1)], 'add', 'abcd')
    assert p.duplicate
    with pytest.raises(ValueError):
        inv.commit(p)
    inv.commit(p, allow_duplicate=True)
    assert inv.list_stock()[0].quantity == 3


def test_undo_once(inv):
    batch = add(inv)
    assert inv.preview_undo(batch).lines[0].quantity == 0
    inv.undo(batch)
    assert inv.list_stock() == []
    with pytest.raises(ValueError):
        inv.undo(batch)


def test_undo_after_sale(inv):
    batch = add(inv)
    inv.adjust(key(), -1)
    old_history = inv.history()
    with pytest.raises(ValueError):
        inv.undo(batch)
    assert inv.list_stock()[0].quantity == 1
    assert inv.history() == old_history


def test_stale_preview(inv):
    preview = inv.prepare([StockLine(key(), 3)], 'add')
    add(inv)
    with pytest.raises(ValueError, match='变化'):
        inv.commit(preview)
    assert inv.list_stock()[0].quantity == 2


def test_rollback_all_lines_when_item_missing(inv):
    p = inv.prepare([StockLine(key(), 2), StockLine(StockKey('missing', 'unknown', 'C2'), 1)], 'add')
    with pytest.raises(ValueError):
        inv.commit(p)
    assert inv.list_stock() == []
    assert inv.history() == []


@pytest.mark.parametrize('n', [0, -1, True, 1.5, 2**64])
def test_invalid_quantities(inv, n):
    with pytest.raises(ValueError):
        inv.prepare([StockLine(key(), n)], 'add')


def test_quality_locations_stay_separate(inv):
    add(inv, 2, key(quality='q0'))
    add(inv, 3, key(quality='unknown'))
    assert len(inv.list_stock()) == 2
    assert len(inv.list_stock('FR-86')) == 2


def test_whitespace_same_location_move_cannot_create_stock(inv):
    add(inv,10,key('C2'))
    with pytest.raises(ValueError):inv.move(key('C2'),' C2 ',2)  # noqa: E701
    assert inv.list_stock()==[StockLine(key('C2'),10)]


# ======================================================================
# 中英文名
# ======================================================================

def test_short_names_not_in_name_table():
    """汉化包里物品的「简称」（视差步枪HD、刀轴Arbor S00、导弹 [红外]灾星 XII-IR）后面跟的是型号 / 尺寸代码，不是英文名：
    重建对照表时跳过，已有的对照表读进来时也筛掉（以前「视差步枪」→ HD，物品查询搜不到视差步枪，1.6.41）"""
    from sc_mining.update import localization as L
    from sc_mining.trade import names
    ini = {"item_Namevolt_rifle_energy_01": "视差 能量突击步枪\\nParallax Energy Assault Rifle",
           "item_Namevolt_rifle_energy_01_black01_short": "视差步枪HD",
           "item_shortMining_Head_S00_Arbor_SCItem": "刀轴Arbor S00",
           "item_NameORIG_300i_shop": "起源跃动300i",
           "items_commodities_tin": "锡\\nTin"}
    assert L.zh2en_items(ini) == {"视差 能量突击步枪": "Parallax Energy Assault Rifle", "锡": "Tin"}
    known = {names._fold_en("Tin")}
    assert names._junk("HD", known) and names._junk("S1", known) and names._junk("XII-IR", known)
    assert names._junk("Arbor S00", known) and names._junk("1 SCU", known)
    assert not names._junk("Tin", known) and not names._junk("Guardian Undersuit", known)


def test_chinese_to_english():
    assert to_english('科力晶') == ['Carinite']
    assert to_english('科力晶（单个矿块）') == ['Carinite']
    assert to_english('量子矿物') == ['Quantainium']
    assert to_english('FR-86') == [] and not has_chinese('FR-86')


def test_catalog_finds_english_item_by_chinese_name(tmp_path):
    c = Catalog(Database(tmp_path / 'p.db'))
    c.upsert([Item('a', 'Carinite'), Item('b', 'Laranite')])
    assert [i.id for i in c.search('科力晶')] == ['a']


def test_ocr_row_with_chinese_name_matches(tmp_path):
    c = Catalog(Database(tmp_path / 'p.db'))
    c.upsert([Item('a', 'Carinite'), Item('b', 'Laranite')])
    row = parse_inventory([OcrToken('科力晶 x3 Q650', 90, (0, 0, 300, 24))], c)[0]
    assert row.item_id == 'a' and row.quantity == 3 and row.quality == 'exact:650'


def test_market_lookup_translates_for_english_only_source(tmp_path):
    class Uex:
        source = 'uex'
        def __init__(self): self.queries = []
        def lookup(self, q):
            self.queries.append(q)
            return [Item('uex:1', 'Carinite')] if q == 'Carinite' else []
    db = Database(tmp_path / 'p.db'); src = Uex()  # noqa: E702
    items, err = MarketService(db, [src]).lookup('科力晶')
    assert [i.name for i in items] == ['Carinite'] and src.queries == ['科力晶', 'Carinite']
    assert Catalog(db).search('科力晶')[0].id == 'uex:1'          # 中文记成别名了


def test_glued_quantity_and_quality(tmp_path):
    c = Catalog(Database(tmp_path / 'p.db'))
    c.upsert([Item('a', 'Carinite'), Item('b', 'FR-86')])
    row = parse_inventory([OcrToken('科力晶 x3Q650', 90, (0, 0, 300, 24))], c)[0]       # 实测 RapidOCR 输出
    assert (row.item_id, row.quantity, row.quality, row.raw_name) == ('a', 3, 'exact:650', '科力晶')
    row = parse_inventory([OcrToken('FR-86 x2 Q500', 90, (0, 0, 300, 24))], c)[0]
    assert (row.item_id, row.quantity, row.quality) == ('b', 2, 'exact:500')


# ======================================================================
# OCR 行解析
# ======================================================================

@pytest.fixture
def catalog(tmp_path):
    c=Catalog(Database(tmp_path/'p.db'));c.upsert([Item('a','FR-86'),Item('b','FR-76')]);return c  # noqa: E702


def token(text, y=0):
    return OcrToken(text,95,(0,y,250,24))


def test_text_candidates(catalog):
    rows=parse_inventory([token('FR-86 x2 Q500')],catalog)
    assert len(rows)==1
    assert rows[0].item_id=='a'
    assert rows[0].quantity==2
    assert rows[0].quality=='exact:500'
    assert not rows[0].confirmed


def test_missing_quantity(catalog):
    assert parse_inventory([token('FR-86 Q500')],catalog)[0].quantity is None


def test_ambiguous_item(catalog):
    row=parse_inventory([token('FR- x2')],catalog)[0]
    assert row.item_id is None
    assert len(row.candidates)==2


def test_unknown_quality(catalog):
    row=parse_inventory([token('FR-86 x2')],catalog)[0]
    assert row.quality is None
    with pytest.raises(ValueError):validate_rows([replace(row,confirmed=True)],'C2')  # noqa: E701
    assert validate_rows([replace(row,quality='unknown',confirmed=True)],'C2')[0].key.quality=='unknown'


def test_unconfirmed_rejected(catalog):
    rows=parse_inventory([token('FR-86 x2 Q500')],catalog)
    with pytest.raises(ValueError):validate_rows(rows,'C2')  # noqa: E701
    result=validate_rows([replace(rows[0],confirmed=True)],'C2')
    assert result[0].quantity==2


def test_repeated_rows(catalog):
    rows=parse_inventory([token('FR-86 x2 Q500'),token('FR-86 x3 Q500',60)],catalog)
    assert len(rows)==2
    assert sum(r.quantity for r in rows)==5


@pytest.mark.parametrize('qty',[0,-1,True,1.5])
def test_reject_invalid_confirmed_quantity(qty):
    with pytest.raises(ValueError):validate_rows([ImportRow('FR-86','a',qty,'q0',confirmed=True)],'C2')  # noqa: E701


# ======================================================================
# 价格统计
# ======================================================================

NOW_P = datetime(2026, 10, 20, 12, 30, tzinfo=timezone.utc)
KEY = PriceKey('uex', 'a', 'q0', 'UEC', 'unit', '4.10.2', 'sell')


def quote(ident, value, key=KEY, kind='fixed', expiry=None):
    return Quote(str(ident), key, D(value), kind, expiry, 'https://example.com')


def test_listing_mean_not_quantity_weighted():
    result = aggregate([quote(1, 100), quote(1, 100), quote(2, 300)], NOW_P)
    assert len(result) == 1
    assert result[0].mean == 200
    assert result[0].minimum == 100
    assert result[0].count == 2


@pytest.mark.parametrize('field,value', [('source', 'scm'), ('quality_group','q1'), ('currency','AUEC'), ('unit','set'), ('version','4.10.1'), ('operation','buy'), ('item_id','b')])
def test_isolated_groups(field, value):
    assert len(aggregate([quote(1, 100), quote(1, 300, replace(KEY, **{field:value}))], NOW_P)) == 2


def test_invalid_and_expired_quotes():
    rows = [quote(1, '0'), quote(2, '-1'), quote(3, 'NaN'), quote(4,'Infinity'), quote(5,100,kind='auction'), quote(6,100,kind='bundle'), quote(7,100,kind='negotiable'), quote(8,100,kind='service'), quote(9,100,expiry=NOW_P), quote(10,100), quote(11,100000)]
    r = aggregate(rows, NOW_P)[0]
    assert r.count == 2
    assert r.mean == 50050


def test_exact_decimal():
    assert aggregate([quote(1,'0.1'), quote(2,'0.2')],NOW_P)[0].mean == D('0.15')


def test_168_hour_boundary(tmp_path):
    h = History(Database(tmp_path / 'p.db'))
    h.record(Snapshot(KEY, NOW_P-timedelta(hours=168, microseconds=1), D(999)))
    for hours, value in [(168,100),(144,300),(0,500)]:
        h.record(Snapshot(KEY, NOW_P-timedelta(hours=hours), D(value)))
    window = h.window(KEY, NOW_P)
    assert window['mean'] == D(300)
    assert window['days'] == 3
    assert len(window['points']) == 3
    assert window['coverage'] < 1


def test_hour_upsert_and_retention(tmp_path):
    h = History(Database(tmp_path / 'p.db'))
    h.record(Snapshot(KEY,NOW_P-timedelta(days=91),D(1)))
    h.record(Snapshot(KEY,NOW_P,D(100)))
    h.record(Snapshot(KEY,NOW_P+timedelta(minutes=1),D(200)))
    assert h.window(KEY,NOW_P+timedelta(minutes=2))['hours'] == 1
    with h.db.connection() as c:
        assert c.execute('select count(*) from snapshots').fetchone()[0] == 1


def test_unpriced_stock_not_zero():
    rows = [StockLine(StockKey('a','q0','C2'),2),StockLine(StockKey('a','unknown','C2'),5)]
    prices=[PriceStats(KEY,D(20),D('10.1'),3,NOW_P)]
    r=value_stock(rows,prices,'uex','4.10.2','UEC')
    assert r == {'total':D('20.2'),'priced_rows':1,'unpriced_rows':1}


def test_accepted_large_decimal_stays_exact_in_all_arithmetic(tmp_path):
    value=D('123456789012345678901234567890.12')
    assert aggregate([quote(1,value)],NOW_P)[0].mean==value
    h=History(Database(tmp_path/'p.db'));h.record(Snapshot(KEY,NOW_P,value))  # noqa: E702
    assert h.window(KEY,NOW_P)['mean']==value
    stats=[PriceStats(KEY,value,value,1,NOW_P)]
    stock=[StockLine(StockKey('a','q0','C2'),2)]
    assert value_stock(stock,stats,'uex','4.10.2','UEC')['total']==D('246913578024691357802469135780.24')


# ======================================================================
# 市场缓存
# ======================================================================

NOW_M = datetime(2026,10,20,12,tzinfo=timezone.utc)


class Source:
    source='uex'
    def __init__(self):
        self.calls=0
        self.fail=False
    def fetch(self,item,quality_group,operation,now):
        self.calls+=1
        if self.fail:return ProviderResult('uex','offline',message='网络离线')  # noqa: E701
        return ProviderResult('uex','ok',(PriceStats(PriceKey('uex',item.id,quality_group,'UEC','unit','4.10.2',operation),D(200),D(100),2,now),), items=(item,))


def test_stale_cache(tmp_path):
    source=Source();db=Database(tmp_path/'p.db')  # noqa: E702
    service=MarketService(db,[source])
    first=service.refresh(Item('a','FR-86'),'q0','sell',NOW_M)[0]
    service.refresh(Item('a','FR-86'),'q0','sell',NOW_M+timedelta(minutes=1))
    assert source.calls==1
    source.fail=True
    later=service.refresh(Item('a','FR-86'),'q0','sell',NOW_M+timedelta(hours=2))[0]
    assert later.state=='stale'
    assert later.stats[0].observed_at==first.stats[0].observed_at
    assert later.stats[0].mean==200
    # Cached stale state survives restarting the application.
    reopened=MarketService(Database(db.path),[source])
    assert reopened.refresh(Item('a','FR-86'),'q0','sell',NOW_M+timedelta(hours=2,minutes=1))[0].state=='stale'
    assert source.calls==2


def test_failed_refresh_retries_after_minutes_not_hour(tmp_path):
    source=Source();source.fail=True  # noqa: E702
    s=MarketService(Database(tmp_path/'p.db'),[source])
    assert s.refresh(Item('a','FR-86'),'q0','sell',NOW_M)[0].state=='offline'
    s.refresh(Item('a','FR-86'),'q0','sell',NOW_M+timedelta(minutes=1))
    assert source.calls==1                     # 刚失败：几分钟内用旧结果
    source.fail=False
    assert s.refresh(Item('a','FR-86'),'q0','sell',NOW_M+timedelta(minutes=6))[0].state=='ok'
    assert source.calls==2                     # 网络好了不用等一小时


def test_refresh_total_timeout(tmp_path, monkeypatch):
    import threading
    gate=threading.Event()
    class Hang(Source):
        def fetch(self,*args):gate.wait(5);return super().fetch(*args)  # noqa: E702
    s=MarketService(Database(tmp_path/'p.db'),[Hang()])
    monkeypatch.setattr(MarketService,'TIMEOUT',0.2)
    r=s.refresh(Item('a','FR-86'),'q0','sell',NOW_M)[0]
    gate.set()
    assert r.state=='offline'


def test_cli_stock_line_units(tmp_path):
    from sc_mining.trade.console import Trade, _cli_line, ore_item
    t = Trade(tmp_path, providers=[])
    ore, gun = Item('q', 'Quantainium (Raw)'), Item('g', 'FR-86')
    t.catalog.upsert([ore, gun])
    assert ore_item(ore) and not ore_item(gun)
    l = _cli_line(t, ore, '0.495', '', 'X')  # noqa: E741
    assert (l.key.unit, l.quantity) == ('uSCU', 495000)      # 矿：SCU → uSCU，和窗口里同一行
    l = _cli_line(t, gun, '2', '500', 'X')  # noqa: E741
    assert (l.key.unit, l.quantity, l.key.quality) == ('unit', 2, 'exact:500')
    with pytest.raises(ValueError):
        _cli_line(t, gun, '1.5', '', 'X')                  # 按个的不能有小数


def test_trade_dir_follows_install_not_env(tmp_path, monkeypatch):
    from sc_mining.core import paths
    from sc_mining.trade import console as C
    monkeypatch.setattr(paths, 'VELOPACK', True)
    monkeypatch.setattr(paths, 'USER', tmp_path / 'Local' / 'AT_userdata')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'other_admin'))   # 提权换了账号
    assert C.data_directory() == tmp_path / 'Local' / 'SCTradeCompanion'
    monkeypatch.setattr(paths, 'VELOPACK', False)
    assert C.data_directory() == tmp_path / 'other_admin' / 'SCTradeCompanion'   # 源码版照旧（测试隔离靠它）


def test_provider_failure_isolated(tmp_path):
    bad=Source();bad.source='scm';bad.fail=True  # noqa: E702
    s=MarketService(Database(tmp_path/'p.db'),[bad,Source()])
    result=s.refresh(Item('a','FR-86'),'q0','sell',NOW_M)
    assert len(result)==2
    assert result[1].stats[0].mean==200


def test_unexpected_source_exception_does_not_block_other_source(tmp_path):
    class Broken(Source):
        source='scm'
        def fetch(self,*args):raise RuntimeError('PRIVATE token in response')
    s=MarketService(Database(tmp_path/'p.db'),[Broken(),Source()])
    result=s.refresh(Item('a','FR-86'),'q0','sell',NOW_M)
    assert result[0].state=='schema_error'
    assert 'PRIVATE' not in result[0].message
    assert result[1].stats[0].mean==200


# ======================================================================
# UEX / SCM 数据源
# ======================================================================

NOW_S = datetime(2026, 10, 20, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / 'fixtures'


def transport(handler):
    return HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None)


def uex_transport(history=None, averages=None):
    def handle(req):
        name = 'uex-history.json' if 'history' in req.url.path else 'uex-avg.json'
        data = json.loads((FIXTURES / name).read_text())
        if name.startswith('uex-history') and history is not None:
            data['data'] = history
        if name.startswith('uex-avg') and averages is not None:
            data['data'] = averages
        return httpx.Response(200, json=data)
    return transport(handle)


def test_uex_week_fallback_label():
    r = UexProvider(uex_transport()).fetch(Item('fr', 'FR-86'), 'q0', 'sell', NOW_S)
    assert r.state == 'ok'
    assert len(r.stats) == 1
    assert r.stats[0].mean == Decimal('4000000')
    assert '可能回退' in r.stats[0].history_note
    assert r.stats[0].minimum == Decimal('3000000')
    assert r.stats[0].key.quality_group == 'q0'


def test_uex_quality_mismatch():
    r = UexProvider(uex_transport(history=[])).fetch(Item('fr', 'FR-86'), 'q2', 'sell', NOW_S)
    assert all(s.minimum is None for s in r.stats)
    assert all(s.key.quality_group == 'q2' for s in r.stats)


def test_no_active_uex_listing_does_not_relabel_month_mean():
    records = json.loads((FIXTURES / 'uex-avg.json').read_text())['data']
    for x in records:
        x['listings_count'] = 0
    r = UexProvider(uex_transport(history=[], averages=records)).fetch(Item('fr', 'FR-86'), 'q0', 'sell', NOW_S)
    assert r.stats[0].mean is None
    assert r.stats[0].minimum is None


def test_scm_forbidden():
    tr = transport(lambda _: httpx.Response(403))
    r = ScmProvider(tr).fetch(Item('fr', 'FR-86'), 'q0', 'sell', NOW_S)
    assert r.state == 'forbidden'
    assert r.stats == ()


def test_retry_after():
    tr = transport(lambda _: httpx.Response(429, headers={'Retry-After': '120'}))
    with pytest.raises(SourceError) as exc:
        tr.get_json('https://test.example/api', {})
    assert exc.value.state == 'rate_limited'
    assert exc.value.retry_after > datetime.now(timezone.utc) + timedelta(seconds=110)


@pytest.mark.parametrize('text', ['NaN', 'Infinity', '-Infinity', '-2', '0', 'bad', True, '1e1000000'])
def test_invalid_decimal(text):
    assert decimal_price(text) is None


def test_scientific_decimal():
    assert decimal_price('1.25e3') == Decimal('1250')
    assert decimal_price('0.123456789') == Decimal('0.123456789')


def test_scm_empty_is_not_zero():
    def handle(req):
        name = 'scm-items.json' if 'item-search' in req.url.path else 'scm-list2.json'
        return httpx.Response(200, json=json.loads((FIXTURES / name).read_text()))
    r = ScmProvider(transport(handle)).fetch(Item('fr', 'FR-86'), 'q0', 'sell', NOW_S)
    assert r.state == 'empty'
    assert r.stats == ()


def test_schema_error_does_not_expose_response_secret():
    tr = transport(lambda _: httpx.Response(200, json={'code': 123, 'msg': 'SECRET_TOKEN'}))
    r = ScmProvider(tr).fetch(Item('fr', 'FR-86'), 'q0', 'sell', NOW_S)
    assert r.state == 'schema_error'
    assert 'SECRET' not in r.message


def test_scm_verified_per_piece_quality():
    rows = json.loads((FIXTURES / 'scm-orders.json').read_text())['data']['list']
    item = Item('scm:43475', '科力晶（单个矿块）')
    quotes = ScmProvider.normalize_orders(rows, item, '43475', 'q6', 'sell', NOW_S)
    assert len(quotes) == 1
    assert quotes[0].price == Decimal('1000000')
    assert quotes[0].key.quality_group == 'q6'
    assert quotes[0].key.version == 'unspecified'


def test_scm_fetch_real_order_sample():
    payload = json.loads((FIXTURES / 'scm-orders.json').read_text())
    r = ScmProvider(transport(lambda _: httpx.Response(200, json=payload))).fetch(Item('scm:43475', '科力晶（单个矿块）'), 'q6', 'sell', NOW_S)
    assert r.state == 'ok'
    assert r.stats[0].mean == Decimal('1000000')
    assert r.stats[0].minimum == Decimal('1000000')


def test_cancel_stops_before_request():
    import threading
    tr=transport(lambda _:pytest.fail('Cancelled request must not hit transport'))
    tr.cancel_event=threading.Event();tr.cancel_event.set()  # noqa: E702
    with pytest.raises(SourceError) as e:tr.get_json('https://example.com',{})  # noqa: E701
    assert e.value.state=='cancelled'


def test_scm_far_future_expiry_avoids_platform_timestamp_range(monkeypatch):
    import sc_mining.trade.providers.scm as scm_module
    class LimitedDatetime(datetime):
        @classmethod
        def fromtimestamp(cls,*args,**kwargs):raise OSError('platform timestamp range')
    monkeypatch.setattr(scm_module,'datetime',LimitedDatetime)
    rows=json.loads((FIXTURES/'scm-orders.json').read_text())['data']['list']
    quotes=ScmProvider.normalize_orders(rows,Item('scm:43475','矿块'),'43475','q6','sell',NOW_S)
    assert quotes[0].expires_at.year==9999


# ======================================================================
# F8：汉化包纠名、品质和数量（2026-10-23 用户截图）
# ======================================================================

_NAMES = {"冷冻舱（剜度）": "CryoPod (Vanduul)", "冷冻舱": "CryoPod", "受辐射的瓦拉卡獠牙（巅峰期）": "Irradiated Valakkar Fang (Apex)",
          "瓦拉卡獠牙": "Valakkar Fang", "钛": "Titanium", "稀钛铁": "Stileron", "冷冻之心": "Cryo-Star"}


def _names(monkeypatch):
    from sc_mining.trade import names
    monkeypatch.setattr(names, "table", lambda: dict(_NAMES))
    names._index.cache_clear()
    return names


def test_canonical_name_fixes_ocr_misreads(monkeypatch):
    """认错一个字、丢一个字、中英连写都对回汉化包里的标准名；英文名优先；对不上的不乱猜"""
    names = _names(monkeypatch)
    try:
        assert names.canonical("冷冻舱（刻度）", "") == ("冷冻舱（剜度）", "CryoPod (Vanduul)")
        assert names.canonical("冷冻舱（度）", "") == ("冷冻舱（剜度）", "CryoPod (Vanduul)")
        assert names.canonical("随便", "CryoPod (Vanduul)") == ("冷冻舱（剜度）", "CryoPod (Vanduul)")
        assert names.canonical("", "Irradiated ValakkarFang(Apex)")[0] == "受辐射的瓦拉卡獠牙（巅峰期）"
        assert names.canonical("受辐射的瓦拉卡獠牙（峰期）", "")[1] == "Irradiated Valakkar Fang (Apex)"
        assert names.canonical("塔兰导电石Taranite", "") == ("塔兰导电石", "Taranite")      # 矿物：中英连写拆开
        assert names.split_bilingual("铁 Iron") == ("铁", "Iron") and names.split_bilingual("冷冻舱") == ("冷冻舱", "")
        assert names.canonical("完全不相干的字", "") is None
        assert names.zh_for("CryoPod") == "冷冻舱" and names.zh_for("Taranite") == "塔兰导电石"
        hits = names.suggest("冷冻")
        assert ("冷冻舱", "CryoPod") in hits and ("冷冻舱（剜度）", "CryoPod (Vanduul)") in hits
        assert names.suggest("cryo")[0] == ("冷冻舱", "CryoPod")
    finally:
        names._index.cache_clear()


def test_label_uses_corrected_chinese_name(monkeypatch, tmp_path):
    """库存里记着 F8 认错的中文名（冷冻舱（刻度））：显示时按汉化包纠正"""
    names = _names(monkeypatch)
    from sc_mining.trade.console import Trade
    try:
        t = Trade(tmp_path / "db", providers=[])
        t.catalog.upsert([Item("uex:1", "CryoPod"), Item("uex:2", "Taranite")])
        t.catalog.add_alias("uex:1", "冷冻舱（刻度）")
        t.catalog.add_alias("uex:2", "塔兰导电石Taranite")
        assert t.label("uex:1") == "冷冻舱（剜度）（CryoPod）"
        assert t.label("uex:2") == "塔兰导电石（Taranite）"
    finally:
        names._index.cache_clear()


def _tok(text, x, y, w=40, h=14):
    return OcrToken(text, 90.0, (x, y, w, h))


def test_tooltip_row_quality_and_amount():
    """说明框内容行「塔兰导电石Taranite｜925｜0.495 SCU」：品质 925、数量 0.495 SCU；「容量：1.00SCU」不算"""
    from sc_mining.tasks.hover import tooltip_row
    toks = [_tok("塔兰导电石Taranite", 100, 50, 120), _tok("体积：1000000uSCU", 100, 70, 120),
            _tok("容量：1.00SCU", 100, 100, 90), _tok("塔兰导电石Taranite", 100, 130, 120), _tok("925", 240, 131, 30),
            _tok("0.495SCU", 300, 130, 60)]
    assert tooltip_row(toks) == (925, 0.495)
    assert tooltip_row([_tok("冷冻舱（剜度）", 100, 50), _tok("体积：4000000uSCU", 100, 70)]) == (None, None)
    assert tooltip_row([_tok("瓦拉卡獠牙", 100, 130), _tok("1SCU", 300, 130)]) == (None, 1.0)


def test_cell_quality_and_count_labels():
    """格子左上角「575Q」是品质（Q 常被认成 0：907Q → 9070，0Q → QQ），右上角「200x」是数量，「200/200」两样都不是"""
    from sc_mining.tasks.hover import parse_qlabel, parse_count, cell_labels
    assert [parse_qlabel(t) for t in ("575Q", "9070", "6770", "0Q", "QQ", "1000Q", "10000", "344Q", "70Q")] == \
        [575, 907, 677, 0, 0, 1000, 1000, 344, 70]
    assert parse_qlabel("200x") is None and parse_qlabel("200/200") is None and parse_qlabel("体积") is None
    assert parse_count("200x") == 200 and parse_count("3x") == 3 and parse_count("200/200") is None and parse_count("575Q") is None
    img = Image.new("RGB", (1000, 800))
    # 两排格子，每格 150×140；鼠标在第 2 排第 2 格（925Q、29x）
    toks = [_tok("710Q", 5, 10), _tok("874Q", 155, 10), _tok("5x", 120, 10, 25),
            _tok("324Q", 5, 150), _tok("925Q", 155, 150), _tok("29x", 265, 150, 30), _tok("710Q", 305, 150), _tok("2x", 420, 150, 25),
            _tok("200/200", 160, 260, 70)]
    assert cell_labels(img, (220, 230), tokens=toks, size=(150, 140)) == (925, 29)
    assert cell_labels(img, (220, 90), tokens=toks, size=(150, 140)) == (874, None)


def test_inventory_cell_labels_real_screens():
    """真截图（2026-10-23 用户发的物品栏）：20 个格子的品质全对（其中 7 个 Q 被认成 0），0Q 是 0，200x / 3x 是数量，200/200 不算"""
    from sc_mining.tasks.hover import cell_labels, tooltip_row  # noqa: F401
    d = Path(__file__).parent / "ingame"
    if not (d / "inv_grid.png").exists():
        pytest.skip("没有物品栏截图")
    try:
        from sc_mining.trade.ocr import recognize
        recognize(Image.new("RGB", (40, 20)))
    except Exception:
        pytest.skip("没装 OCR")
    img = Image.open(d / "inv_grid.png").convert("RGB")
    labels = [[(6, 13), (149, 8), (296, 0), (452, 0)], [(7, 156), (150, 150), (298, 147), (452, 143)],
              [(7, 294), (151, 293), (299, 291), (452, 290)], [(7, 432), (151, 434), (299, 436), (451, 434)],
              [(4, 569), (150, 573), (299, 578), (452, 583)]]
    want = [[710, 874, 907, 325], [677, 664, 974, 717], [521, 514, 344, 344], [344, 669, 324, 677], [547, 762, 677, 852]]
    toks = recognize(img)
    got = [[cell_labels(img, (x + 60, y + 70), tokens=toks, size=(150, 140))[0] for x, y in row] for row in labels]
    assert got == want, got
    img = Image.open(d / "inv_q0.png").convert("RGB")
    assert [cell_labels(img, c, size=(150, 140))[0] for c in ((62, 90), (216, 93))] == [0, 0]
    assert cell_labels(Image.open(d / "inv_count200.png").convert("RGB"), (75, 80), size=(150, 140)) == (None, 200)
    assert cell_labels(Image.open(d / "inv_count3.png").convert("RGB"), (68, 80), size=(150, 140)) == (None, 3)
    # 整屏（F8 存下的 1280×720 截图）：鼠标指着 925Q 那格
    img = Image.open(d / "inv_taranite_720.jpg").convert("RGB")
    assert cell_labels(img, (175, 565))[0] == 925


def test_tooltip_zh_only_medal_not_description():
    """2026-10-27 老大 F8：勋章 / 计算板说明框只有中文名、最下面是「容量：1.00SCU」。以前按「容量」往上找，
    把说明最后一截「越。」当成名字；只有中文名的也查不到英文名"""
    from sc_mining.trade.console import tooltip_pick
    from sc_mining.trade.names import canonical
    toks = [_tok("地球联合帝国（UEE）六排勋章（完好）", 100, 50, 260), _tok("体积：173uSCU", 100, 70, 100),
            _tok("MICROT", 300, 70, 60),
            _tok("为表彰UEE海军陆战队第六排的杰出表现而授予的勋章。伟大", 100, 95, 380),
            _tok("带部分崭新如初，勋章金属部分的蚀刻也无明显损耗，成色卓", 100, 113, 380),
            _tok("越。", 100, 131, 30), _tok("容量：1.00SCU", 100, 160, 100)]
    name, sure = tooltip_pick(toks, (120, 170))
    assert name and name[0] == "地球联合帝国（UEE）六排勋章（完好）" and sure
    assert canonical("DCHS-06通讯计算板", "") == ("DCHS-06 通讯 计算板", "DCHS-06 Communication Comp-Board")
    assert canonical("塔维因战争服役微记（完好）", "")[1] == "Tevarin War Service Marker (Pristine)"      # 徽认成微
    assert canonical("焦焰RYT多功能工具", "Pyro RYT Multi-Tool") == ("焦焰 RYT 多功能工具", "Pyro RYT Multi-Tool")



def test_tooltip_double_picks_bright():
    """2026-10-27 老大：两个说明框叠在一起（上面亮的是鼠标指着的，下面暗的是身上装备的对比框）只认亮的那个。
    以前认成了下面的「焦焰 RYT “血统红” 多功能工具」"""
    from sc_mining.tasks.hover import _read_tooltip
    from sc_mining.trade.names import canonical
    d = Path(__file__).parent / "ingame"
    if not (d / "hover_double.jpg").exists():
        pytest.skip("没有叠框截图")
    try:
        from sc_mining.trade.ocr import recognize
        recognize(Image.new("RGB", (40, 20)))
    except Exception:
        pytest.skip("没装 OCR")
    img = Image.open(d / "hover_double.jpg").convert("RGB")
    _toks, name, _where = _read_tooltip(img, (1950, 820))
    assert canonical(*name)[1] == "Pyro RYT Multi-Tool", name



# ---------------------------------------------------------------- 2026-10-30 重构阶段 1：交易、库存的接口走自己的 Controller
_TRADE_API = ["search", "item_search", "item_info", "item_loot", "nav_shop", "trade", "market_lookup",
              "market_prices", "mineral_search", "mineral_info"]
_STOCK_API = ["stock", "stock_add", "craft_slots_for", "stock_add_named", "stock_suggest", "stock_set_quality",
              "stock_undo", "stock_out", "stock_set_qty", "stock_move", "stock_relocate", "stock_keep_custom",
              "stock_places", "stock_place_add", "stock_bin_save", "stock_bin_delete", "stock_reserve",
              "stock_ledger", "stock_prices"]


def test_trade_stock_controller_routes():
    """交易、库存的每个接口名都由 app/api/trade.py、app/api/stock.py 接，名单和 Controller 的 ROUTES 一个不多一个不少"""
    from sc_mining.app.api import router, trade as CT, stock as CS
    router.reset()
    r = router.routes()
    for name in _TRADE_API:
        assert r[name].__module__ == "sc_mining.app.api.trade", name
    for name in _STOCK_API:
        assert r[name].__module__ == "sc_mining.app.api.stock", name
    assert sorted(CT.ROUTES) == sorted(_TRADE_API) and sorted(CS.ROUTES) == sorted(_STOCK_API)


def test_trade_stock_tasks_no_services():
    """tasks/trade.py、tasks/stock.py 不再反过来引用 app.services"""
    root = Path(__file__).resolve().parent.parent / "sc_mining" / "tasks"
    for f in ("trade.py", "stock.py"):
        text = (root / f).read_text(encoding="utf-8")
        for bad in ("app import services", "_services()", "@api"):
            assert bad not in text, (f, bad)


def test_trade_stock_router_roundtrip(monkeypatch, tmp_path):
    """只读接口 stock_places：走 router 和直接调 tasks 结果一样"""
    from sc_mining.app.api import router
    from sc_mining.tasks import trade as TT, stock as TS
    from sc_mining.trade.console import Trade
    t = Trade(tmp_path / "db", providers=[])
    monkeypatch.setattr(TT, "trade", lambda: t)
    monkeypatch.setattr(TS, "trade", lambda: t)
    router.reset()
    got = router.call("stock_places", {})
    assert got["ok"], got
    want = json.loads(json.dumps(TS.stock_places(), ensure_ascii=False, default=str))
    assert got["data"] == want
