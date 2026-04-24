from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_readme_documents_closed_loop_acceptance_guidance() -> None:
    content = (REPO_ROOT / "README.md").read_text()
    assert "the externally observable outcome" in content
    assert "the operation result at the system boundary" in content
    assert "the persisted source-of-truth state" in content
    assert "the downstream derived state" in content


def test_end_to_end_demo_documents_how_to_reject_one_layer_success_signals() -> None:
    content = (REPO_ROOT / "docs" / "end-to-end-demo.md").read_text()
    assert "Acceptance check for behavior-changing workflows" in content
    assert "one signal looks good" in content
    assert "task verify <task-id> --result failed" in content
    assert "deviation add <task-id>" in content


def test_public_docs_use_donegate_as_project_name() -> None:
    checked_paths = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "README.zh-CN.md",
        REPO_ROOT / "CONTRIBUTING.md",
        REPO_ROOT / "docs",
        REPO_ROOT / "examples",
    ]
    contents: list[tuple[Path, str]] = []
    for path in checked_paths:
        if path.is_dir():
            contents.extend((file_path, file_path.read_text()) for file_path in path.rglob("*") if file_path.is_file())
        else:
            contents.append((path, path.read_text()))

    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path, content in contents
        if "DoneGate MCP" in content or "DoneGate-MCP" in content
    ]

    assert offenders == []
