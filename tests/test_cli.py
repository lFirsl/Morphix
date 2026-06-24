from unittest.mock import MagicMock, patch

import pytest


def parse_args_with(argv):
    with patch("sys.argv", argv):
        # Re-import to avoid module caching issues with argparse
        import importlib

        import morphix_core.cli_args as cli_args_mod

        importlib.reload(cli_args_mod)
        return cli_args_mod.parse_args()


# 1. Positional input argument
def test_positional_input_argument():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10"])
    assert args.input == "video.mp4"


# 2. --max-mb float argument
def test_max_mb_float_argument():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "25.5"])
    assert args.max_mb == 25.5


# 3. --output argument
def test_output_argument():
    args = parse_args_with(
        ["morphix", "video.mp4", "--max-mb", "10", "--output", "out.mp4"]
    )
    assert args.output == "out.mp4"


# 4. --quality default is medium
def test_quality_default_is_medium():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10"])
    assert args.quality == "medium"


# 5. --quality choices
def test_quality_choices():
    for quality in ["low", "medium", "high"]:
        args = parse_args_with(
            ["morphix", "video.mp4", "--max-mb", "10", "--quality", quality]
        )
        assert args.quality == quality


# 6. --overwrite default is True
def test_overwrite_default_is_true():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10"])
    assert args.overwrite is True


# 7. --no-overwrite flag
def test_no_overwrite_flag():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10", "--no-overwrite"])
    assert args.overwrite is False


# 8. --progress default is True
def test_progress_default_is_true():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10"])
    assert args.progress is True


# 9. --no-progress flag
def test_no_progress_flag():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10", "--no-progress"])
    assert args.progress is False


# 10. --disable-logs default is True
def test_disable_logs_default_is_true():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10"])
    assert args.disable_logs is True


# 11. --enable-logs flag
def test_enable_logs_flag():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10", "--enable-logs"])
    assert args.disable_logs is False


# 12. --no-console flag
def test_no_console_flag():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10", "--no-console"])
    assert args.no_console is True


# 13. --test flag sets default input
def test_test_flag_sets_default_input():
    args = parse_args_with(["morphix", "--test"])
    assert args.input is not None
    assert args.max_mb == 15


# 14. --test flag sets default max_mb
def test_test_flag_sets_default_max_mb():
    args = parse_args_with(["morphix", "--test"])
    assert args.max_mb == 15


# 15. Error when input missing without --test
def test_error_when_input_missing_without_test():
    with pytest.raises(SystemExit):
        parse_args_with(["morphix", "--max-mb", "10"])


# 16. Error when --max-mb missing without --test
def test_error_when_max_mb_missing_without_test():
    with pytest.raises(SystemExit):
        parse_args_with(["morphix", "video.mp4"])


# 17. --resolution argument
def test_resolution_argument():
    args = parse_args_with(
        ["morphix", "video.mp4", "--max-mb", "10", "--resolution", "1280x720"]
    )
    assert args.resolution == "1280x720"


# 18. --quality invalid choice exits
def test_quality_invalid_choice_exits():
    with pytest.raises(SystemExit):
        parse_args_with(
            ["morphix", "video.mp4", "--max-mb", "10", "--quality", "ultra"]
        )


# 19. --overwrite explicit flag
def test_overwrite_explicit_flag():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10", "--overwrite"])
    assert args.overwrite is True


# 20. --progress explicit flag
def test_progress_explicit_flag():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10", "--progress"])
    assert args.progress is True


# 21. --disable-logs explicit flag
def test_disable_logs_explicit_flag():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10", "--disable-logs"])
    assert args.disable_logs is True


# 22. --test flag does not override explicitly provided input
def test_test_flag_does_not_override_explicit_input():
    args = parse_args_with(["morphix", "--test", "my_video.mp4"])
    assert args.input == "my_video.mp4"
    assert args.max_mb == 15


# 23. --test flag does not override explicitly provided --max-mb
def test_test_flag_does_not_override_explicit_max_mb():
    args = parse_args_with(["morphix", "--test", "--max-mb", "50"])
    assert args.max_mb == 50.0


# 24. --no-console re-launch path (mocked subprocess)
def test_no_console_relaunches_subprocess_on_windows():
    """When --no-console is set on Windows, cli.main() should re-launch via subprocess and return."""
    import morphix_core.cli as cli_mod

    mock_args = MagicMock()
    mock_args.no_console = True

    with (
        patch("os.name", "nt"),
        patch("morphix_core.cli.parse_args", return_value=mock_args),
        patch("morphix_core.cli.subprocess.Popen") as mock_popen,
    ):
        cli_mod.main()
        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args[1]
        assert (
            call_kwargs.get("creationflags")
            == __import__("subprocess").CREATE_NO_WINDOW
        )


# 25. --no-console flag is NOT set: no re-launch
def test_no_console_not_set_does_not_relaunch():
    """When --no-console is not set, cli.main() should not call subprocess.Popen for re-launch."""
    import morphix_core.cli as cli_mod

    mock_args = MagicMock()
    mock_args.no_console = False
    mock_args.input = "video.mp4"
    mock_args.max_mb = 10.0
    mock_args.quality = "medium"
    mock_args.resolution = None
    mock_args.overwrite = True
    mock_args.disable_logs = True
    mock_args.progress = True
    mock_args.start = None
    mock_args.end = None

    with (
        patch("morphix_core.cli.parse_args", return_value=mock_args),
        patch("morphix_core.cli.check_target_exceeds_file_size"),
        patch("morphix_core.cli.check_low_compression_ratio", return_value=False),
        patch("morphix_core.cli.run") as mock_run,
        patch("morphix_core.cli.subprocess.Popen") as mock_popen,
    ):
        cli_mod.main()
        mock_run.assert_called_once()
        mock_popen.assert_not_called()


# ===========================================================================
# Trim Feature CLI Argument Tests
# ===========================================================================


def test_start_argument_parsed():
    args = parse_args_with(
        ["morphix", "video.mp4", "--max-mb", "10", "--start", "30.5"]
    )
    assert args.start == 30.5


def test_end_argument_parsed():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10", "--end", "60.0"])
    assert args.end == 60.0


def test_both_start_and_end():
    args = parse_args_with(
        ["morphix", "video.mp4", "--max-mb", "10", "--start", "10", "--end", "30"]
    )
    assert args.start == 10.0
    assert args.end == 30.0


def test_test_flag_does_not_override_explicit_start():
    args = parse_args_with(["morphix", "--test", "--start", "5"])
    assert args.input is not None
    assert args.start == 5.0


def test_test_flag_does_not_override_explicit_end():
    args = parse_args_with(["morphix", "--test", "--end", "120"])
    assert args.input is not None
    assert args.end == 120.0


def test_start_default_is_none():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10"])
    assert args.start is None


def test_end_default_is_none():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10"])
    assert args.end is None


def test_start_invalid_float_exits():
    with pytest.raises(SystemExit):
        parse_args_with(["morphix", "video.mp4", "--max-mb", "10", "--start", "abc"])


def test_end_invalid_float_exits():
    with pytest.raises(SystemExit):
        parse_args_with(["morphix", "video.mp4", "--max-mb", "10", "--end", "xyz"])
