"""
Per-reference outputs for group 2: every group 2 reference's own fit, depth and fd at every pixel.

EDITED 11/24/2027: new module (optional ``per_reference`` pipeline stage).

Why this is needed
------------------
Within a group, Tetracorder computes the fit and depth of every enabled reference at every pixel, then keeps
only the group's best reference and sets every other reference of the group to 0 before the images are written
(``tp1all.r``). A normal run therefore gives, per pixel, the winner of group 2 and zeros for the other 199
references. A reference that is alone in its group is always that group's best, so its own values are written
wherever its own rules pass.

What this stage does
--------------------
The Tetracorder program is not changed. After the ``setup`` stage has made the run folder
(``output.tetracorder``), this stage:

1. copies the run folder once per batch of group 2 references;
2. in each copy, edits the run folder's copy of the expert-system command file (``cmd.lib.setup.t6.00a6``):
   each batch reference moves from ``group 2`` to a free group number of its own, and the header is extended so
   Tetracorder accepts those groups (see :func:`regroup`); the new group numbers are switched on in
   ``DISABLE/force-disable.txt``;
3. starts Tetracorder in each copy the way the run folder's ``cmd.runtet`` starts it (``<ptc> r1`` reading
   ``<tetcmdsstart>``), without ``cmd.runtet``'s picture-making steps;
4. collects, for every group 2 reference, the ``.fit``, ``.depth`` and ``.fd`` images Tetracorder wrote
   (gzip-compressed, bytes unchanged), and stacks the fd images into one ENVI cube with one band per reference.

Two modes
---------
Tetracorder allows 50 groups (``multmap.h``: ``maxgrp=50``); the stock command file uses 22 group numbers, so
28 are free.

``lean`` (default; used for the EMIT-AV5 group 2 fd labels)
    Each run takes up to 28 references (8 runs for the 200 of group 2). Every entry that the batch does not
    need is switched off with its own ``use= no``. Kept on: the batch references, and every entry that one of
    their NOT tests refers to (followed through the entries those refer to in turn), so each NOT test compares
    against the same reference as in a normal run. A referenced entry of group 0 is moved into group 2 (where it
    competes with nothing written out), so no group 0 entry competes with the batch.
``conservative``
    Nothing is switched off or moved except the batch references, which go to free group numbers that are also
    listed on the ``nogroup0:`` line (so group 0 does not compete with them). That line has 80 columns, so one run
    takes at most 19 references (11 runs). Much slower, because every entry of the file runs; it exists to check
    that ``lean`` gives the same numbers.

Images are read as Tetracorder writes them (``cublineout.r``, ``creatoutfiles.r``): one unsigned byte per pixel
after a label of whole records (at least 299 bytes); fit is stored as fit x 255, depth and fd as
value x 255 / X, where X is the reference's ``8 DN 255 = X`` setting (column ``depth_value_of_255`` of the
reference table).
"""

import gzip
import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

Logger = logging.getLogger(__name__)

EXPERT = "cmd.lib.setup.t6.00a6"
GROUP = 2                        # the only group supported (and tested)
N_GROUP = 200                    # references in group 2 of the stock command file
MAXGRP = 50                      # multmap.h: parameter (maxgrp=50)
CONSERVATIVE_MAX = 19            # group numbers that fit on the 80-column "nogroup0:" line
ENTRY = re.compile(r"^(group|case)\s+(\d+)\s*$")
KINDS = ("fit", "depth", "fd")


# ---------------------------------------------------------------- reading the command file
def code(raw: str) -> str:
    """A command-file line without its trailing comment."""
    return raw.split("\\#")[0].rstrip()


def read_nots(path: Path) -> Dict[str, Tuple[str, int]]:
    """``[NOTNAME]`` -> (library alias, record) from the run folder's NOT reference file."""
    nots = {}
    for raw in open(path, encoding="latin-1"):
        m = re.match(r"^==\[(\w+)\]\s*\[(\w+)\]\s+(\d+)", raw)
        if m:
            nots[m.group(1)] = (m.group(2), int(m.group(3)))
    return nots


def nots_file(run: Path) -> Path:
    for name in ("cmd.lib.setup.nots-ratios", "cmd.lib.setup.nots-ratios-small"):
        if (run / name).exists():
            return run / name
    raise FileNotFoundError(f"no cmd.lib.setup.nots-ratios[-small] in {run}")


def read_entries(lines: List[str], nots: Dict[str, Tuple[str, int]]) -> List[dict]:
    """Every entry after ``BEGIN SETUP``, in file order (the order Tetracorder numbers materials)."""
    start = next(i for i, l in enumerate(lines) if l.startswith("BEGIN SETUP"))
    entries, cur, after_output = [], None, False
    for i in range(start + 1, len(lines)):
        c = code(lines[i])
        s = c.strip()
        if cur is None:
            m = ENTRY.match(c)
            if m:
                cur = {"index": len(entries), "kind": m.group(1), "number": int(m.group(2)), "line": i,
                       "use": None, "use_line": None, "small": None, "nots": [], "name": None,
                       "id": None, "scale": None}
                after_output = False
            continue
        if cur["use"] is None and s.startswith("use"):
            m = re.match(r"^use\s*=\s*(yes|no)\b", s)
            if not m:
                raise ValueError(f"line {i + 1}: cannot read the use= switch: {lines[i]!r}")
            cur["use"], cur["use_line"] = m.group(1), i
        if cur["id"] is None and s.startswith("ID="):
            cur["id"] = s[3:].strip()
        m = re.match(r"^a\s+SMALL:\s*\[(\w+)\]\s+(\S+)", s)
        if m and m.group(2).isdigit():
            cur["small"] = (m.group(1), int(m.group(2)))
        m = re.match(r"^8\s+DN\s+255\s*=\s*(\S+)", s)
        if m and cur["scale"] is None:
            cur["scale"] = m.group(1)                 # a number, or a [VARIABLE] (see resolve_scale)
        m = re.match(r"^n(\d+)([a-i])\s+NOT\s+(.*)$", s)
        if m:
            if m.group(2) != "a":                                      # library slot a = the SMALL record
                raise ValueError(f"line {i + 1}: NOT test on library slot {m.group(2)} is not supported")
            t = m.group(3).split()
            name = t[0].strip("[]")
            ref = nots[name] if name in nots else (name, int(t[1]))
            cur["nots"].append({"name": name, "lib": ref[0], "record": ref[1], "line": i})
        if after_output and s and cur["name"] is None:
            cur["name"] = s.split()[0]
        if s.startswith("output="):
            after_output = True
        if s.startswith("endaction"):
            cur["end"] = i
            if cur["use"] is None:
                raise ValueError(f"entry at line {cur['line'] + 1} has no use= switch")
            entries.append(cur)
            cur = None
    if cur is not None:
        raise ValueError("the command file ends inside an entry")
    return entries


def definer(entries: List[dict], i: int, lib: str, record: int, enabled) -> Optional[int]:
    """The entry a NOT test of entry ``i`` refers to: ``getnotfeat.r`` scans materials 1..i-1 for the library
    record and keeps the last match; an entry with ``use= no`` has no record entered."""
    found = None
    for j in range(i):
        if enabled(entries[j]) and entries[j]["small"] == (lib, record):
            found = j
    return found


def resolve_scale(value: Optional[str], variables: Dict[str, str]) -> Optional[float]:
    """The ``8 DN 255 = X`` value as a number; ``[NAME]`` is looked up in the run folder's
    ``cmd.lib.setup.variables`` (sensor-specific). None when it cannot be resolved."""
    if value is None:
        return None
    m = re.fullmatch(r"\[(\w+)\]", value)
    if m:
        value = variables.get(m.group(1))
        if value is None:
            return None
    try:
        return float(value.split()[0])
    except ValueError:
        return None


def load(run: Path) -> Tuple[List[str], List[dict]]:
    lines = open(Path(run) / EXPERT, encoding="latin-1").read().split("\n")
    return lines, read_entries(lines, read_nots(nots_file(Path(run))))


def group_entries(entries: List[dict]) -> List[dict]:
    g = [e for e in entries if e["kind"] == "group" and e["number"] == GROUP]
    if len(g) != N_GROUP:
        raise ValueError(f"group {GROUP} has {len(g)} entries; the stock command file has {N_GROUP}")
    return g


def free_groups(entries: List[dict]) -> List[int]:
    used = {e["number"] for e in entries if e["kind"] == "group"}
    return [n for n in range(1, MAXGRP + 1) if n not in used]


def batches(entries: List[dict], mode: str) -> List[Tuple[int, int]]:
    """(first, last) positions (1..200, inclusive) of each run's references."""
    if mode not in ("lean", "conservative"):
        raise ValueError(f"mode must be lean or conservative, not {mode!r}")
    size = len(free_groups(entries)) if mode == "lean" else CONSERVATIVE_MAX
    return [(a, min(a + size - 1, N_GROUP)) for a in range(1, N_GROUP + 1, size)]


# ---------------------------------------------------------------- the edit
def regroup(run: Path, mode: str, first: int, last: int) -> dict:
    """Edit the run folder's command file (and ``DISABLE/force-disable.txt``) so that group 2 references
    ``first`` .. ``last`` (positions within group 2, 1-based, inclusive) each sit alone in a free group.
    Returns the report also written to ``regroup_report.json`` in the run folder."""
    run = Path(run)
    if mode not in ("lean", "conservative"):
        raise ValueError(f"mode must be lean or conservative, not {mode!r}")
    nots = read_nots(nots_file(run))
    lines, entries = load(run)
    group2 = group_entries(entries)
    if not all(e["use"] == "yes" for e in group2):
        raise ValueError("the run folder is not a fresh copy of the stock command file (a group 2 entry has use= no)")
    batch = [e["index"] for e in group2[first - 1:last]]
    free = free_groups(entries)
    limit = len(free) if mode == "lean" else CONSERVATIVE_MAX
    if not 1 <= len(batch) <= limit:
        raise ValueError(f"{len(batch)} references; one {mode} run takes at most {limit}")

    # the entries the NOT tests refer to, followed through the entries they refer to in turn
    stock = lambda e: e["use"] == "yes"
    keep, todo, links = set(batch), list(batch), {}
    while todo:
        i = todo.pop()
        for n in entries[i]["nots"]:
            j = definer(entries, i, n["lib"], n["record"], stock)
            if j is None:
                raise ValueError(f"{entries[i]['name']}: NOT test {n['name']} refers to no enabled entry")
            links[(i, n["line"])] = j
            if j not in keep:
                keep.add(j)
                todo.append(j)
    held = sorted(keep - set(batch))
    if not all(entries[j]["kind"] == "group" for j in held):
        raise ValueError("a NOT test refers to an entry in a case")

    private = dict(zip(batch, free))
    out = list(lines)
    moved = []
    for i, g in private.items():
        out[entries[i]["line"]] = f"group {g}"
    if mode == "lean":
        for j in held:                                   # group 0 would compete in every group
            if entries[j]["number"] == 0:
                out[entries[j]["line"]] = f"group {GROUP}"
                moved.append(j)
        for e in entries:
            if e["index"] not in keep and e["use"] == "yes":
                new, n = re.subn(r"^use\s*=\s*yes", "use= no ", out[e["use_line"]], count=1)
                assert n == 1, out[e["use_line"]]
                out[e["use_line"]] = new

    # header: number of groups, the output path of each private group (group 2's), short names
    k = next(i for i, l in enumerate(out) if re.match(r"^\s*38\s+7\s*$", code(l)))
    out[k] = f"{MAXGRP}     7      \\# {MAXGRP} groups (39-{MAXGRP}: one group 2 entry each) and 7 cases"
    for g in range(1, 39):
        if code(out[k + g]).strip() != f"[DIRg{g}]":
            raise ValueError(f"unexpected header line for group {g}: {out[k + g]!r}")
    for g in private.values():
        if g <= 38:
            out[k + g] = f"[DIRg{GROUP}]      \\# group {g} path (one group 2 entry)"
    out[k + 39:k + 39] = [f"[DIRg{GROUP}]      \\# group {g} path (one group 2 entry)" for g in range(39, MAXGRP + 1)]
    k = next(i for i, l in enumerate(out) if code(l).startswith("groupname 38"))
    out[k + 1:k + 1] = [f"groupname {g}  g2 single" for g in range(39, MAXGRP + 1)]
    k = next(i for i, l in enumerate(out) if code(l).startswith("nogroup0:"))
    if mode == "conservative":                            # group 0 must not compete with the batch
        out[k] = code(out[k]) + " " + " ".join(str(g) for g in private.values())
        if len(out[k]) > 78:
            raise ValueError(f"nogroup0: line too long ({len(out[k])} columns)")

    # check the result as Tetracorder will read it
    new = read_entries(out, nots)
    assert len(new) == len(entries)
    on = lambda e: e["use"] == "yes"
    for (i, line), j in links.items():
        n = next(x for x in entries[i]["nots"] if x["line"] == line)
        assert definer(new, i, n["lib"], n["record"], on) == j, (entries[i]["name"], n)
    for i, g in private.items():
        members = [e for e in new if e["kind"] == "group" and e["number"] == g]
        assert len(members) == 1 and members[0]["index"] == i and members[0]["use"] == "yes", (g, members)
    if mode == "lean":
        assert not any(on(e) and e["kind"] == "group" and e["number"] == 0 for e in new)
        assert {e["index"] for e in new if on(e)} == keep
    if not all(len(l) <= 80 for l in out[:k + 2] if not l.startswith("\\#")):
        raise ValueError("a header line is over 80 columns")

    open(run / EXPERT, "w", encoding="latin-1", newline="").write("\n".join(out))

    # the private group numbers must be switched on (force-disable.txt lists groups 1..38)
    dis = run / "DISABLE" / "force-disable.txt"
    switched = []
    if dis.exists():
        text = open(dis, encoding="latin-1").read().split("\n")
        for n, raw in enumerate(text):
            m = re.match(r"^DISABLE(\s+)grp(\s+)(\d+)\s*$", raw)
            if m and int(m.group(3)) in private.values():
                text[n] = f"ENABLE {m.group(1)}grp{m.group(2)}{m.group(3)}"
                switched.append(int(m.group(3)))
        open(dis, "w", encoding="latin-1", newline="").write("\n".join(text))

    report = {
        "mode": mode, "first": first, "last": last,
        "batch": [{"n": first + k, "name": entries[i]["name"], "group": private[i]} for k, i in enumerate(batch)],
        "held": [{"name": entries[j]["name"], "group_in_stock_file": entries[j]["number"],
                  "group_in_this_run": GROUP if j in moved else entries[j]["number"]} for j in held],
        "not_links": [{"entry": entries[i]["name"], "refers_to": entries[j]["name"],
                       "group_of_reference_in_stock_file": entries[j]["number"]} for (i, _), j in sorted(links.items())],
        "entries_switched_on": sum(on(e) for e in new), "entries_in_file": len(new),
        "groups_switched_on_in_force_disable": sorted(switched),
    }
    json.dump(report, open(run / "regroup_report.json", "w"), indent=1)
    return report


# ---------------------------------------------------------------- images
def label_bytes(samples: int) -> int:
    """Label size written by ``creatoutfiles.r``: one record, or enough records to hold 299 bytes."""
    return samples if samples >= 299 else samples * (299 // samples + 1)


def read_image(path: Path, samples: int, lines: int) -> np.ndarray:
    """One Tetracorder output image as uint8 ``[lines, samples]``; plain or ``.gz``."""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rb") as f:
        raw = f.read()
    off = label_bytes(samples)
    if len(raw) != off + samples * lines:
        raise ValueError(f"{path}: {len(raw)} bytes, expected {off + samples * lines}")
    return np.frombuffer(raw, np.uint8, samples * lines, off).reshape(lines, samples)


def find_image(folder: Path, name: str, kind: str) -> Optional[Path]:
    for ext in (".gz", ""):
        p = Path(folder) / f"{name}.{kind}{ext}"
        if p.exists():
            return p
    return None


def group_dir(run: Path) -> str:
    """Output folder of group 2 in the run folder (``[DIRg2]`` of the start file, e.g. ``group.2um``)."""
    from tetrapy.tetracorder import TetraDecoder
    _, start = tetracorder_command(run)
    paths = TetraDecoder.parse_group_paths(str(Path(run) / start))      # "==[DIRg2]group.2um/" in cmds.start.*
    return paths[GROUP].strip().rstrip("/")


def image_size(rfl: str) -> Tuple[int, int]:
    """(samples, lines) from the reflectance header (the cube Tetracorder reads; ``AAA.info/image-*pixels.txt``
    only exists after Tetracorder has run)."""
    hdr = Path(str(rfl) + ".hdr").read_text(encoding="latin-1")
    samples = int(re.search(r"^\s*samples\s*=\s*(\d+)", hdr, re.M).group(1))
    lines = int(re.search(r"^\s*lines\s*=\s*(\d+)", hdr, re.M).group(1))
    return samples, lines


def tetracorder_command(run: Path) -> Tuple[str, str]:
    """(program, start file) as the run folder's ``cmd.runtet`` uses them in cube mode."""
    text = (Path(run) / "cmd.runtet").read_text(encoding="latin-1")
    ptc = re.search(r'^\s*ptc="?([^"\s]+)"?', text, re.M)
    start = re.search(r"^tetcmdsstart=(\S+)", text, re.M)
    if not ptc or not start or start.group(1) == "CMDSSTART":
        raise ValueError(f"cannot find ptc= / tetcmdsstart= in {run}/cmd.runtet (was the setup stage run?)")
    return ptc.group(1), start.group(1)


def gz_copy(src: Path, dst: Path) -> None:
    with open(src, "rb") as f, gzip.open(dst, "wb", compresslevel=6) as g:
        shutil.copyfileobj(f, g)


# ---------------------------------------------------------------- the stage
def run(tetracorder: str, output: str, rfl: str, mode: str = "lean", jobs: int = 1, keep_runs: bool = False) -> dict:
    """
    Run Tetracorder once per batch of group 2 references, each reference alone in its own group, and collect
    every reference's fit, depth and fd images plus a stacked fd cube.

    Parameters
    ----------
    tetracorder : str
        The run folder made by the ``setup`` stage (``output.tetracorder``); it is copied, never changed.
    output : str
        Folder for the results (must be empty or absent):
        ``group2/<name>.{fit,depth,fd}.gz``, ``group2_fd`` + ``group2_fd.hdr`` (ENVI, uint8, BIP, band k = group 2
        reference k in command-file order), ``group2_references.csv``, ``summary.json``, ``logs/<run>/``.
    rfl : str
        The scene reflectance (data file); its header supplies samples, lines, ``map info`` and
        ``coordinate system string``.
    mode : {"lean", "conservative"}
        See the module docstring.
    jobs : int
        Tetracorder runs at the same time.
    keep_runs : bool
        Keep the per-batch run folders (``output/runs/<mode>_<first>``) after collecting.
    """
    base, out = Path(tetracorder), Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty")
    (out / "group2").mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    _, entries = load(base)
    group2 = group_entries(entries)
    specs = batches(entries, mode)
    program, start = tetracorder_command(base)
    gdir = group_dir(base)
    samples, lines = image_size(rfl)
    Logger.info(f"per_reference: {mode}, {len(specs)} runs of up to {specs[0][1]} group {GROUP} references, {jobs} at a time")

    runs = []
    for a, b in specs:
        d = out / "runs" / f"{mode}_{a:03d}"
        shutil.copytree(base, d, symlinks=True)
        rep = regroup(d, mode, a, b)
        (d / "stdin.txt").write_text(f"<{start}\ne\n")
        runs.append({"spec": f"{mode}:{a}:{b}", "dir": d, "report": rep})

    waiting, active = list(runs), []
    while waiting or active:
        while waiting and len(active) < jobs:
            r = waiting.pop(0)
            r["t0"] = time.time()
            r["proc"] = subprocess.Popen([program, "r1"], cwd=r["dir"], stdin=open(r["dir"] / "stdin.txt"),
                                         stdout=open(r["dir"] / "tetracorder.out", "wb"), stderr=subprocess.STDOUT)
            Logger.info(f"per_reference: started {r['spec']}")
            active.append(r)
        time.sleep(2)
        for r in list(active):
            if r["proc"].poll() is not None:
                r["seconds"], r["exit"] = round(time.time() - r["t0"]), r["proc"].returncode
                Logger.info(f"per_reference: finished {r['spec']}: exit {r['exit']}, {r['seconds']} s")
                active.remove(r)

    # collect the images (bytes unchanged; gzip-compressed as a normal run's group folders are) and logs
    summary = []
    for r in runs:
        logs = out / "logs" / r["dir"].name
        logs.mkdir(parents=True, exist_ok=True)
        written = 0
        for e in r["report"]["batch"]:
            e["files"] = []
            for kind in KINDS:
                src = find_image(r["dir"] / gdir, e["name"], kind)
                if src is not None:
                    dst = out / "group2" / f"{e['name']}.{kind}.gz"
                    shutil.copy(src, dst) if src.suffix == ".gz" else gz_copy(src, dst)
                    e["files"].append(kind)
            written += len(e["files"]) == 3
        for f in ("tetracorder.out", "history", EXPERT):
            if (r["dir"] / f).exists():
                gz_copy(r["dir"] / f, logs / (f + ".gz"))
        for f in ("regroup_report.json", "AAA.info/material-DN-scalling.txt", "DISABLE/force-disable.txt", start):
            if (r["dir"] / f).exists():
                shutil.copy(r["dir"] / f, logs)
        summary.append({"spec": r["spec"], "exit": r["exit"], "seconds": r["seconds"],
                        "entries": len(r["report"]["batch"]), "entries_with_images": written,
                        "batch": r["report"]["batch"], "held": r["report"]["held"]})
        Logger.info(f"per_reference: {r['spec']}: {written} of {len(r['report']['batch'])} references wrote fit, depth and fd")

    # the reference table (band order of the stacked cube) and the stacked fd cube
    names = [e["name"] for e in group2]
    order = {e["n"]: e["name"] for s in summary for e in s["batch"]}
    assert [order[k] for k in range(1, N_GROUP + 1)] == names, "batch order differs from the command file"
    from tetrapy.tetracorder import TetraDecoder
    var_file = base / "cmd.lib.setup.variables"
    variables = TetraDecoder.parse_variables(str(var_file)) if var_file.exists() else {}
    with open(out / "group2_references.csv", "w") as f:
        f.write("band,name,id,library,record,depth_value_of_255,has_images\n")
        for k, e in enumerate(group2, 1):
            lib, rec = e["small"] if e["small"] else ("", "")
            has = find_image(out / "group2", e["name"], "fd") is not None
            f.write(f"{k},{e['name']},{e['id'] or ''},{lib},{rec},{'' if (x := resolve_scale(e['scale'], variables)) is None else x},{int(has)}\n")
    missing = []
    with open(out / "group2_fd", "wb") as f:
        step = max(1, int(200e6 // (samples * N_GROUP)))
        stack = np.zeros((N_GROUP, lines, samples), np.uint8)
        for k, name in enumerate(names):
            p = find_image(out / "group2", name, "fd")
            if p is None:
                missing.append(name)
            else:
                stack[k] = read_image(p, samples, lines)
        for y0 in range(0, lines, step):
            f.write(np.ascontiguousarray(stack[:, y0:y0 + step].transpose(1, 2, 0)).tobytes())
    hdr = Path(str(rfl) + ".hdr").read_text(encoding="latin-1")

    def keep(key):
        m = re.search(r"^\s*" + key + r"\s*=\s*(\{[^}]*\}|[^\n]*)", hdr, re.M)
        return f"{key} = {m.group(1).strip()}\n" if m else ""

    with open(out / "group2_fd.hdr", "w", encoding="latin-1", newline="\n") as f:
        f.write("ENVI\n")
        f.write("description = {Tetracorder group 2 fd per reference: band k = group 2 reference k in command-file "
                "order (group2_references.csv); Tetracorder's stored 8-bit fd (fd x 255 / depth_value_of_255)}\n")
        f.write(f"samples = {samples}\nlines = {lines}\nbands = {N_GROUP}\nheader offset = 0\n")
        f.write("file type = ENVI Standard\ndata type = 1\ninterleave = bip\nbyte order = 0\n")
        f.write(keep("map info") + keep("coordinate system string"))
        f.write("band names = {\n " + ",\n ".join(f"{k:03d} {n}" for k, n in enumerate(names, 1)) + "}\n")

    result = {"mode": mode, "jobs": jobs, "total_seconds": round(time.time() - t0), "samples": samples, "lines": lines,
              "references_without_images_bands_of_zeros": missing, "runs": summary}
    json.dump(result, open(out / "summary.json", "w"), indent=1)
    if not keep_runs:
        shutil.rmtree(out / "runs")
    Logger.info(f"per_reference: {N_GROUP - len(missing)} references with images, {len(missing)} without; {out}")
    if any(s["exit"] != 0 for s in summary):
        raise RuntimeError(f"a Tetracorder run ended with an error; see {out}/logs")
    return result
