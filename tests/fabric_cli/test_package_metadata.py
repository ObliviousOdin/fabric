from fabric_cli.package_metadata import (
    configure_packaged_revision,
    get_packaged_revision,
)


def test_package_revision_cli_transport_is_hidden() -> None:
    from fabric_cli._parser import build_top_level_parser

    parser, _subparsers, _chat = build_top_level_parser()
    args = parser.parse_args(["--package-revision", "abc123"])

    assert args.package_revision == "abc123"
    assert "--package-revision" not in parser.format_help()


def test_packaged_revision_is_process_local_metadata() -> None:
    configure_packaged_revision(" abc123 ")
    try:
        assert get_packaged_revision() == "abc123"
    finally:
        configure_packaged_revision(None)


def test_empty_packaged_revision_is_absent() -> None:
    configure_packaged_revision("")
    assert get_packaged_revision() is None
