from qport import kb


def test_every_suggested_replacement_exists_in_qnx():
    missing = [(r["names"][0], a) for r in kb.LINUX_APIS for a in r["qnx_alt"] if not kb.qnx_has(a)]
    assert not missing, missing


def test_flagged_linux_apis_are_really_absent_from_qnx():
    present = [n for r in kb.LINUX_APIS for n in r["names"] if kb.qnx_has(n)]
    assert not present, present


def test_link_headers_match_index():
    idx = kb.qnx_index()
    assert idx["inotify_init"]["libs"] == ["fsnotify"]
    assert idx["regcomp"]["libs"] == ["regex"]
