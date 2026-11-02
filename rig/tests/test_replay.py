from pitwall_rig.adapters.replay import Recorder, ReplayAdapter
from pitwall_rig.models import GameStatus


def test_record_then_replay(tmp_path, demo, clock):
    path = tmp_path / "s.pwrec"
    rec = Recorder(path, "demo", demo.capabilities)
    for _ in range(600):
        clock.advance(1 / 60)
        rec.add(demo.poll(), demo.session())
    rec.close()

    rclock = type(clock)(100.0)
    rp = ReplayAdapter(path, clock=rclock)
    assert rp.game_id == "demo" and rp.capabilities.reports_brake_bias
    first = rp.poll()
    assert first.status == GameStatus.LIVE
    assert rp.session().car == "demo_gt3"
    rclock.advance(5.0)
    later = rp.poll()
    assert later.packet_id > first.packet_id
    rclock.advance(20.0)  # past the end: loops
    looped = rp.poll()
    assert looped.packet_id > later.packet_id  # ids stay unique across loops
