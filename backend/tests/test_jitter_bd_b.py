"""红测乙（内红）：抖动对账不得把越界影子误标成界内合法。

越界影子 = 旁路账册里原始抖动越界、却被标成“界内合法”的记录。
互证必须识别出来，判抖动对齐失败。
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


def test_越界影子不得标成界内合法():
    from app.db import 连接
    from app.services import 互证
    from app.services.时间 import 此刻

    影子事件号 = f'EVT-shadow-{uuid.uuid4().hex[:8]}'
    conn = 连接()
    try:
        conn.execute(
            "INSERT INTO 抖动账册(事件号,调度方,下界毫秒,上界毫秒,原始抖动毫秒,"
            "钳后等待毫秒,是否越界,处置,时刻) VALUES (?,?,?,?,?,?,?,?,?)",
            (影子事件号, '影子', 800, 3000, -50, 800, 0, '采纳', 此刻()),
        )
        conn.commit()
    finally:
        conn.close()

    报 = 互证.跑一次()
    assert 报['抖动对齐'] is False, '越界影子被误标成界内合法，互证必须判撕裂'
    assert 报['越界影子数'] >= 1
    assert 报['是否全部对齐'] is False
    assert '抖动' in 报['说明'] or '影子' in 报['说明']


def test_正常账册可对平():
    from app.services import 互证

    报 = 互证.跑一次()
    # 上面影子还在，抖动对齐仍应为否；但口径字段必须存在且结构完整
    assert '明细' in 报
    assert '抖动明细' in 报
    assert isinstance(报['是否对齐'], bool)
