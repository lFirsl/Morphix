import sys
import pytest
from unittest.mock import patch


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
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10", "--output", "out.mp4"])
    assert args.output == "out.mp4"


# 4. --quality default is medium
def test_quality_default_is_medium():
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10"])
    assert args.quality == "medium"


# 5. --quality choices
def test_quality_choices():
    for quality in ["low", "medium", "high"]:
        args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10", "--quality", quality])
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
    args = parse_args_with(["morphix", "video.mp4", "--max-mb", "10", "--resolution", "1280x720"])
    assert args.resolution == "1280x720"
