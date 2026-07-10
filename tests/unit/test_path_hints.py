from claimtrace.path_hints import windows_path_hint


def test_windows_path_hint_converts_drive_path_for_wsl():
    hint = windows_path_hint(r"C:\Users\you\project\figure_A.pml")

    assert "/mnt/c/Users/you/project/figure_A.pml" in hint


def test_windows_path_hint_ignores_linux_path():
    assert windows_path_hint("/home/you/project/figure_A.pml") == ""
