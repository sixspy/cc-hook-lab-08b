"""红测甲（外红）：抖动越界样本不得提前开火。

夹具键：负抖动五十毫秒（-50ms）。
等待必须落在上下界 [800, 3000] 毫秒内；算出越界的样本不得直接排进点火队列。
越界样本收进旁路账册并拒绝回刷；点火队列只收钳后等待。
"""
import os
import tempfile
import uuid
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ['数据目录'] = _tmp
os.environ['夹具目录'] = str(Path(__file__).resolve().parents[2] / 'fixtures')


def setup_module():
    from app import seed
    seed.初始化库()


def _新事件(前缀: str) -> str:
    from app.services import 入队
    事件号 = f'EVT-jit-{前缀}-{uuid.uuid4().hex[:8]}'
    入队.建事件({
        '事件号': 事件号,
        '事件类型': 'invoice.paid',
        '端点键': 'ep-billing',
        '载荷摘要': f'jitter-{前缀}',
        '优先级': '普通',
    })
    return 事件号


def test_负抖动五十毫秒不得提前开火():
    from app.services import 抖动, 重试, 夹具

    体 = 夹具.读取('负抖动五十毫秒')
    样本 = int(体['抖动样本'][0]['抖动毫秒'])
    assert 样本 == -50

    事件号 = _新事件('neg50')
    结 = 重试.排程重试(事件号, 抖动毫秒=样本, 调度方='甲')

    # 原始样本保留负值，等待被钳到下界
    assert 结['原始抖动毫秒'] == -50
    assert 结['下界毫秒'] == 800
    assert 结['上界毫秒'] == 3000
    assert 结['等待毫秒'] == 800
    assert 800 <= 结['等待毫秒'] <= 3000
    assert 结['是否钳住'] is True

    # 点火队列里不能留下 50 毫秒或负的等待
    行 = next(x for x in 重试.排程列表() if x['事件号'] == 事件号)
    assert 行['等待毫秒'] == 800
    assert 800 <= 行['等待毫秒'] <= 3000
    assert 行['原始抖动毫秒'] == -50

    # 越界样本进旁路账册，处置为拒绝回刷
    账 = [x for x in 抖动.账册列表() if x['事件号'] == 事件号]
    assert 账, '越界样本必须收进旁路账册'
    末 = 账[-1]
    assert 末['原始抖动毫秒'] == -50
    assert 末['钳后等待毫秒'] == 800
    assert 末['是否越界'] == 1
    assert 末['处置'] == '拒绝回刷'

    # 页面文案：等待落在界内或抖动越界已钳住
    文案 = 结['文案']
    assert ('落在界内' in 文案) or ('越界已钳住' in 文案)


def test_正五十毫秒也钳到下界():
    from app.services import 抖动, 重试

    事件号 = _新事件('pos50')
    结 = 重试.排程重试(事件号, 抖动毫秒=50, 调度方='甲')
    assert 结['等待毫秒'] == 800
    assert 结['等待毫秒'] != 50
    assert 结['是否钳住'] is True
    行 = next(x for x in 重试.排程列表() if x['事件号'] == 事件号)
    assert 800 <= 行['等待毫秒'] <= 3000


def test_点保存抖动界后下一次等待落在界内():
    from app.services import 抖动, 重试

    旧界 = 抖动.取界()
    try:
        抖动.定界(1000, 1500)
        assert 抖动.取界() == {'下界毫秒': 1000, '上界毫秒': 1500}

        事件号 = _新事件('newsave')
        # 上越界样本必须钳到新上界，不能按旧界放行
        结 = 重试.排程重试(事件号, 抖动毫秒=2500, 调度方='乙')
        assert 结['下界毫秒'] == 1000
        assert 结['上界毫秒'] == 1500
        assert 结['等待毫秒'] == 1500
        assert 1000 <= 结['等待毫秒'] <= 1500
        assert 结['是否钳住'] is True
    finally:
        抖动.定界(旧界['下界毫秒'], 旧界['上界毫秒'])


def test_死信列表看见上下界与实际等待():
    from app.services import 签名目录, 投递

    # 先排程，让投递失败时带上等待详情
    事件号 = _新事件('dead')
    from app.services import 重试
    重试.排程重试(事件号, 抖动毫秒=1200, 调度方='丙')

    最大 = int(签名目录.签名规().get('最大重试') or 3)
    末 = None
    for _ in range(最大 + 1):
        末 = 投递.投递一次(事件号, 强制失败=True)
        if 末.get('事件状态') == '死信':
            break
    assert 末 and 末.get('事件状态') == '死信'

    死信行 = next(x for x in 签名目录.死信列表() if x['事件号'] == 事件号)
    assert 死信行['抖动下界毫秒'] == 800
    assert 死信行['抖动上界毫秒'] == 3000
    assert 800 <= 死信行['实际等待毫秒'] <= 3000


def test_接口保存抖动界后下一次等待界内():
    """策略页保存抖动界 → 下一次排程立刻按新界钳住。"""
    from app.factory import create_app

    app = create_app()
    c = app.test_client()
    assert c.post('/api/登录', json={'账号': 'admin', '密码': '123456'}).status_code == 200

    r = c.post('/api/签名规', json={'抖动下界毫秒': 900, '抖动上界毫秒': 1200})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['抖动界'] == {'下界毫秒': 900, '上界毫秒': 1200}

    事件号 = _新事件('api')
    试 = c.post('/api/抖动试算', json={'抖动毫秒': -50}).get_json()
    assert 试['下界毫秒'] == 900 and 试['上界毫秒'] == 1200
    assert 试['等待毫秒'] == 900
    assert 试['是否钳住'] is True

    排 = c.post('/api/重试排程', json={'事件号': 事件号, '抖动毫秒': 2500, '调度方': '甲'})
    assert 排.status_code == 200, 排.get_data(as_text=True)
    结 = 排.get_json()
    assert 900 <= 结['等待毫秒'] <= 1200
    assert 结['等待毫秒'] == 1200

    # 复位，别影响其它用例
    c.post('/api/签名规', json={'抖动下界毫秒': 800, '抖动上界毫秒': 3000})


def test_接口争用返回409():
    from app.factory import create_app
    from app.services import 重试

    app = create_app()
    c = app.test_client()
    assert c.post('/api/登录', json={'账号': 'admin', '密码': '123456'}).status_code == 200

    事件号 = _新事件('api409')
    重试.建待排(事件号)
    ok = c.post('/api/重试排程', json={'事件号': 事件号, '抖动毫秒': 1000, '调度方': '甲'})
    assert ok.status_code == 200
    第二次 = c.post('/api/重试排程', json={'事件号': 事件号, '抖动毫秒': 2000, '调度方': '乙'})
    assert 第二次.status_code == 409
    assert 第二次.get_json()['争用'] is True
    行 = next(x for x in 重试.排程列表() if x['事件号'] == 事件号)
    assert 行['原始抖动毫秒'] == 1000
    assert 800 <= 行['等待毫秒'] <= 3000
