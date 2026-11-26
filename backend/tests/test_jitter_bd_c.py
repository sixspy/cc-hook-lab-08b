"""争用红测（夹红）：两路调度同时抢同一条的下次点火时刻。

只准一路认领成功，另一路必须报争用；禁止两路各写各的毫秒、
静默成功提前重试。等待仍必须落在上下界内。
"""
import os
import tempfile
import threading
import uuid
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ['数据目录'] = _tmp
os.environ['夹具目录'] = str(Path(__file__).resolve().parents[2] / 'fixtures')


def setup_module():
    from app import seed
    seed.初始化库()


def test_两路调度抢点火时刻不得互相覆盖():
    from app.services import 入队, 重试

    事件号 = f'EVT-race-{uuid.uuid4().hex[:8]}'
    入队.建事件({
        '事件号': 事件号,
        '事件类型': 'invoice.paid',
        '端点键': 'ep-billing',
        '载荷摘要': 'race',
        '优先级': '普通',
    })
    重试.建待排(事件号)

    栅栏 = threading.Barrier(2)
    结果 = []
    锁 = threading.Lock()

    def 一路(方: str, 样本: int):
        栅栏.wait()
        try:
            结 = 重试.排程重试(事件号, 抖动毫秒=样本, 调度方=方)
            with 锁:
                结果.append(('ok', 方, 结))
        except 重试.排程争用 as e:
            with 锁:
                结果.append(('争用', 方, str(e)))

    甲 = threading.Thread(target=一路, args=('甲', 1000))
    乙 = threading.Thread(target=一路, args=('乙', 2000))
    甲.start(); 乙.start()
    甲.join(); 乙.join()

    成功 = [x for x in 结果 if x[0] == 'ok']
    争用 = [x for x in 结果 if x[0] == '争用']
    assert len(成功) == 1, f'只准一路成功，实际 {len(成功)} 路：{结果}'
    assert len(争用) == 1, f'另一路必须报争用，实际 {len(争用)} 路：{结果}'

    行 = next(x for x in 重试.排程列表() if x['事件号'] == 事件号)
    assert 800 <= 行['等待毫秒'] <= 3000
    assert 行['等待毫秒'] != 50
    assert 行['排程版本'] == 1  # 只被认领一次

    # 赢家写入的毫秒就是队列里的毫秒，输家没有覆盖
    赢家样本 = 成功[0][2]['原始抖动毫秒']
    assert 行['原始抖动毫秒'] == 赢家样本
    assert 行['等待毫秒'] == 成功[0][2]['等待毫秒']


def test_点火队列无负等待():
    from app.services import 重试

    行们 = 重试.排程列表()
    for 行 in 行们:
        assert 行['等待毫秒'] >= 行['下界毫秒'] >= 0
        assert 行['等待毫秒'] <= 行['上界毫秒']
