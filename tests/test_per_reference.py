"""
Tests for the optional ``per_reference`` stage (EDITED 11/24/2027: new file).

The command-file edit is tested on the stock command file of this repository
(``cmd.lib.setup.t6.00a6``). The stage itself runs end to end on a run folder made from
that file, with a stand-in for the Tetracorder program that writes, for every group 2
reference sitting alone in its own group, label + image bytes the way Tetracorder does.
"""

import gzip
import json
import shutil
import stat
import sys
from pathlib import Path

import numpy as np
import pytest

from tetrapy import per_reference as pr

CMDS = Path(__file__).parents[1] / "tetracorder/tetracorder.cmds/tetracorder6.00a.cmds"
SAMPLES, LINES = 7, 5


def make_run(path: Path, program: str = "/bin/false") -> Path:
    """A minimal run folder: stock command file, NOT file, start file, cmd.runtet, DISABLE file."""
    path.mkdir(parents=True)
    shutil.copy(CMDS / pr.EXPERT, path / pr.EXPERT)
    shutil.copy(CMDS / "cmd.lib.setup.nots-ratios-small", path / "cmd.lib.setup.nots-ratios-small")
    shutil.copy(CMDS / "cmds.start.t6.00a", path / "cmds.start.t6.00a")
    (path / "cmd.runtet").write_text(f'\tptc="{program}"\ntetcmdsstart=cmds.start.t6.00a\n')
    (path / "DISABLE").mkdir()
    (path / "DISABLE/force-disable.txt").write_text("\n".join(f"DISABLE   grp   {g}" for g in range(1, 39)) + "\n")
    return path


def test_stock_file_has_200_group2_references_and_28_free_groups():
    entries = pr.read_entries((CMDS / pr.EXPERT).read_text(encoding="latin-1").split("\n"),
                              pr.read_nots(CMDS / "cmd.lib.setup.nots-ratios-small"))
    g2 = pr.group_entries(entries)
    assert len(g2) == 200 and all(e["use"] == "yes" for e in g2)
    assert len(pr.free_groups(entries)) == 28
    assert all(e["scale"] is not None for e in g2)            # a number or a [VARIABLE] for every reference
    assert pr.resolve_scale("[O8DN50]", {"O8DN50": "0.5000"}) == 0.5 and pr.resolve_scale("0.9", {}) == 0.9
    assert pr.resolve_scale("[MISSING]", {}) is None
    lean, cons = pr.batches(entries, "lean"), pr.batches(entries, "conservative")
    assert len(lean) == 8 and lean[0] == (1, 28) and lean[-1] == (197, 200)
    assert len(cons) == 11 and cons[0] == (1, 19) and cons[-1] == (191, 200)
    for b in (lean, cons):                                   # every reference in exactly one run
        assert sum(z - a + 1 for a, z in b) == 200 and all(b[i][1] + 1 == b[i + 1][0] for i in range(len(b) - 1))


@pytest.mark.parametrize("mode,first,last", [("lean", 1, 28), ("lean", 197, 200), ("conservative", 20, 38)])
def test_regroup(tmp_path, mode, first, last):
    run = make_run(tmp_path / "run")
    _, before = pr.load(run)
    rep = pr.regroup(run, mode, first, last)
    lines, after = pr.load(run)
    assert len(after) == len(before)
    batch = [e["name"] for e in pr.group_entries(before)[first - 1:last]]
    assert [b["name"] for b in rep["batch"]] == batch
    free = pr.free_groups(before)
    for b, g in zip(rep["batch"], free):                       # alone, switched on, in a free group
        members = [e for e in after if e["kind"] == "group" and e["number"] == g]
        assert b["group"] == g and len(members) == 1 and members[0]["name"] == b["name"] and members[0]["use"] == "yes"
    on = [e for e in after if e["use"] == "yes"]
    if mode == "lean":
        assert len(on) == len(rep["batch"]) + len(rep["held"]) == rep["entries_switched_on"]
        assert not any(e["kind"] == "group" and e["number"] == 0 for e in on)
    else:                                                       # nothing switched off; group 0 kept out via nogroup0:
        assert [e["use"] for e in after] == [e["use"] for e in before]
        nog = next(l for l in lines if pr.code(l).startswith("nogroup0:"))
        assert all(str(b["group"]) in nog.split() for b in rep["batch"])
    assert any(pr.code(l).strip().startswith("50 ") for l in lines)
    assert sum(pr.code(l).startswith("groupname") for l in lines) >= 50
    dis = (run / "DISABLE/force-disable.txt").read_text()
    for g in (b["group"] for b in rep["batch"] if b["group"] <= 38):
        assert f"ENABLE    grp   {g}" in dis
    assert json.loads((run / "regroup_report.json").read_text())["batch"] == rep["batch"]


def test_regroup_refuses_too_many_and_edited_files(tmp_path):
    run = make_run(tmp_path / "run")
    with pytest.raises(ValueError):
        pr.regroup(run, "lean", 1, 29)
    with pytest.raises(ValueError):
        pr.regroup(run, "conservative", 1, 20)
    pr.regroup(run, "lean", 1, 28)
    with pytest.raises(ValueError):                             # not a fresh copy any more
        pr.regroup(run, "lean", 29, 56)


FAKE = '''#!{python}
"""Stand-in for tetracorder6.00 r1: for every group 2 reference alone in its own group (use= yes), write
<name>.fit / .depth / .fd in group.2um/ as label + bytes, value = (position within group 2 + kind) mod 256."""
import sys
sys.path.insert(0, {repo!r})
from pathlib import Path
from tetrapy import per_reference as pr
sys.stdin.read()
lines, entries = pr.load(Path("."))
stock = pr.read_entries(Path({stock!r}).read_text(encoding="latin-1").split("\\n"),
                        pr.read_nots(Path("cmd.lib.setup.nots-ratios-small")))
pos = {{e["name"]: k for k, e in enumerate(pr.group_entries(stock), 1)}}
groups = {{}}
for e in entries:
    if e["kind"] == "group" and e["use"] == "yes":
        groups.setdefault(e["number"], []).append(e)
out = Path("group.2um"); out.mkdir(exist_ok=True)
S, L = {s}, {l}
for g, es in groups.items():
    if len(es) == 1 and g not in (0, 2) and es[0]["name"] in pos and es[0]["name"] != {skip!r}:
        for j, kind in enumerate(("fit", "depth", "fd")):
            v = (pos[es[0]["name"]] + j) % 256
            (out / f"{{es[0]['name']}}.{{kind}}").write_bytes(b"L" * pr.label_bytes(S) + bytes([v]) * (S * L))
print("fake tetracorder done")
'''


def test_stage_end_to_end(tmp_path):
    stock = CMDS / pr.EXPERT
    g2 = pr.group_entries(pr.read_entries(stock.read_text(encoding="latin-1").split("\n"),
                                          pr.read_nots(CMDS / "cmd.lib.setup.nots-ratios-small")))
    skip = g2[10]["name"]                                      # one reference that writes no image
    prog = tmp_path / "fake_tetracorder"
    prog.write_text(FAKE.format(python=sys.executable, repo=str(Path(__file__).parents[1]), stock=str(stock),
                                s=SAMPLES, l=LINES, skip=skip))
    prog.chmod(prog.stat().st_mode | stat.S_IEXEC)
    run = make_run(tmp_path / "run", str(prog))
    original = (run / pr.EXPERT).read_bytes()
    rfl = tmp_path / "rfl"
    (tmp_path / "rfl.hdr").write_text("ENVI\nsamples = 7\nlines = 5\nmap info = {UTM, 1, 1, 0, 0, 10, 10, 11, North}\n")

    res = pr.run(str(run), str(tmp_path / "out"), str(rfl), mode="lean", jobs=3)
    out = tmp_path / "out"
    assert (run / pr.EXPERT).read_bytes() == original           # the setup run folder is not changed
    assert len(res["runs"]) == 8 and all(r["exit"] == 0 for r in res["runs"])
    assert res["references_without_images_bands_of_zeros"] == [skip]
    assert len(list((out / "group2").glob("*.gz"))) == 3 * 199
    assert not (out / "runs").exists()
    cube = np.fromfile(out / "group2_fd", np.uint8).reshape(LINES, SAMPLES, 200)
    for k, e in enumerate(g2, 1):
        want = 0 if e["name"] == skip else (k + 2) % 256        # fd = position + 2
        assert (cube[..., k - 1] == want).all(), e["name"]
        if e["name"] != skip:                                   # collected images are Tetracorder's bytes, gzipped
            raw = gzip.open(out / "group2" / f"{e['name']}.fit.gz").read()
            assert raw[pr.label_bytes(SAMPLES):] == bytes([k % 256]) * (SAMPLES * LINES)
    csv = (out / "group2_references.csv").read_text().splitlines()
    assert csv[0].startswith("band,name") and len(csv) == 201 and csv[11].split(",")[1] == skip and csv[11].endswith(",0")
    hdr = (out / "group2_fd.hdr").read_text()
    assert "bands = 200" in hdr and "interleave = bip" in hdr and "map info = {UTM" in hdr
    assert sorted(p.name for p in (out / "logs").iterdir()) == [f"lean_{a:03d}" for a in range(1, 201, 28)]

    with pytest.raises(FileExistsError):                        # output folder must be empty
        pr.run(str(run), str(out), str(rfl))
