import math
import struct

from pitwall_rig.tracks.ac_files import lateral_position, read_fast_lane, read_sections


def write_fast_lane(path, n=400, radius=100.0, left=6.0, right=4.0):
    """A circle of right-hand turns (like most of Spa), AI line on it, fixed edge distances.

    In AC's (x, z) plane a heading that rotates counter-clockwise mathematically
    is a right turn, which is what the real Spa data shows.
    """
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        pts.append((radius * math.cos(a), 0.0, radius * math.sin(a), 2 * math.pi * radius * i / n))
    b = struct.pack("<4i", 7, n, 0, 0)
    b += b"".join(struct.pack("<4fi", x, y, z, d, i) for i, (x, y, z, d) in enumerate(pts))
    b += struct.pack("<i", n)
    b += b"".join(struct.pack("<18f", 30, 1, 0, 0, radius, left, right, *([0.0] * 11)) for _ in range(n))
    b += b"\x00" * 64  # newer builds append more data; must be ignored
    path.write_bytes(b)


def test_reads_line_and_edges(tmp_path):
    p = tmp_path / "fast_lane.ai"
    write_fast_lane(p)
    line = read_fast_lane(p)
    assert len(line) == 400
    assert line.side_left[0] == 6.0 and line.side_right[0] == 4.0
    assert abs(line.length - 2 * math.pi * 100 * 399 / 400) < 0.5


def test_lateral_position(tmp_path):
    p = tmp_path / "fast_lane.ai"
    write_fast_lane(p)
    line = read_fast_lane(p)
    # On a clockwise circle, "right" is towards the centre (the inside of the corner).
    _, off, frac = lateral_position(line, 100.0, 0.0)
    assert abs(off) < 0.01 and abs(frac - 0.6) < 0.01  # on the line: 6 m from left of 10 m
    _, off, frac = lateral_position(line, 96.0, 0.0)  # 4 m towards the centre = right edge
    assert abs(off + 4.0) < 0.05 and abs(frac - 1.0) < 0.01
    _, off, frac = lateral_position(line, 106.0, 0.0)  # 6 m outwards = left edge
    assert abs(off - 6.0) < 0.05 and abs(frac) < 0.01


def test_reads_sections(tmp_path):
    p = tmp_path / "sections.ini"
    p.write_text("[SECTION_1]\nIN=0.137\nOUT=0.154\nTEXT=Eau Rouge\n\n[SECTION_0]\nIN=0.038\nOUT=0.068\nTEXT=La Source\n")
    secs = read_sections(p)
    assert [s.name for s in secs] == ["La Source", "Eau Rouge"]
    assert secs[0].start == 0.038
