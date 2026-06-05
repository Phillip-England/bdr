from click.testing import CliRunner

from bdr.cli import main
from bdr.interpreter import BdrError, Interpreter


class DummyPage:
    pass


def make_interpreter(args=None, stdin_text=""):
    return Interpreter(DummyPage(), cli_args=args or [], stdin_text=stdin_text)


def test_named_cli_args_support_space_and_equals_forms():
    interp = make_interpreter(["--url", "https://example.com", "--query=playwright"])

    assert interp._resolve(1, 'arg("url")') == "https://example.com"
    assert interp._resolve(1, 'arg("query")') == "playwright"


def test_cli_arg_default_and_positional_lookup():
    interp = make_interpreter(["first"])

    assert interp._resolve(1, "arg(0)") == "first"
    assert interp._resolve(1, 'arg(1, "fallback")') == "fallback"
    assert interp._resolve(1, "arg_count()") == "1"


def test_missing_cli_arg_has_clear_error():
    interp = make_interpreter()

    try:
        interp._resolve(7, 'arg("url")')
    except BdrError as exc:
        assert "Line 7: cli arg 'url' is not set" in str(exc)
    else:
        raise AssertionError("missing arg should fail")


def test_stdin_helpers():
    interp = make_interpreter(stdin_text="alpha\nbeta\n")

    assert interp._resolve(1, "stdin()") == "alpha\nbeta\n"
    assert interp._resolve(1, "stdin_line(1)") == "beta"
    assert interp._resolve(1, 'stdin_line(2, "fallback")') == "fallback"


def test_run_command_passes_script_args_and_stdin(monkeypatch):
    captured = {}

    def fake_run_script(script, **kwargs):
        captured["script"] = script
        captured.update(kwargs)

    monkeypatch.setattr("bdr.cli.run_script", fake_run_script)

    result = CliRunner().invoke(
        main,
        ["run", "script.bdr", "--", "--url", "https://example.com"],
        input="piped text\n",
    )

    assert result.exit_code == 0
    assert captured["script"] == "script.bdr"
    assert captured["cli_args"] == ["--url", "https://example.com"]
    assert captured["stdin_text"] == "piped text\n"
