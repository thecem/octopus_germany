"""Regression coverage for Marketplace release-asset packaging."""

# ruff: noqa: INP001, S101, S603, S607

import json
import os
import subprocess
from pathlib import Path
from zipfile import ZipFile

import yaml


def test_marketplace_release_archive_contains_only_tracked_integration_files(
    tmp_path: Path,
) -> None:
    """Execute the release build and verify Marketplace's expected ZIP layout."""
    repository = Path(__file__).resolve().parents[1]
    metadata = json.loads((repository / "hacs.json").read_text(encoding="utf-8"))
    workflow = yaml.safe_load(
        (repository / ".github/workflows/tag-and-release.yaml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["tag-and-release"]["steps"]
    build = next(
        step
        for step in steps
        if step.get("name") == "Build integration release archive"
    )
    release = next(
        step for step in steps if step.get("name") == "Create GitHub Release"
    )
    assert metadata["zip_release"] is True
    assert metadata["filename"] == "octopus_germany.zip"
    assert not metadata.get("content_in_root", False)
    assert build["if"] == release["if"] == "env.EXISTS == 'false'"
    assert release["with"]["files"] == "${{ runner.temp }}/octopus_germany.zip"
    assert release["with"]["fail_on_unmatched_files"] is True
    assert release["with"]["body_path"] == "release_body.md"

    subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", build["run"]],
        cwd=repository,
        env={**os.environ, "RUNNER_TEMP": str(tmp_path)},
        check=True,
    )
    tracked = subprocess.check_output(
        [
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            "HEAD:custom_components/octopus_germany",
        ],
        cwd=repository,
        text=True,
    ).splitlines()
    with ZipFile(tmp_path / metadata["filename"]) as archive:
        files = {entry.filename for entry in archive.infolist() if not entry.is_dir()}
        assert files == set(tracked)
        assert {
            "manifest.json",
            "__init__.py",
            "brand/icon.png",
            "brand/icon@2x.png",
        } <= files
        assert all(
            not Path(name).is_absolute() and ".." not in Path(name).parts
            for name in archive.namelist()
        )
        assert json.loads(archive.read("manifest.json"))["domain"] == "octopus_germany"
        assert archive.testzip() is None
