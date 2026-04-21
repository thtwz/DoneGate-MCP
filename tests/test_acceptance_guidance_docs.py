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
