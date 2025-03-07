import json
import os
import random
import string

from google.protobuf.wrappers_pb2 import BoolValue, StringValue
from wandb.proto import wandb_settings_pb2
from wandb.sdk.internal.job_builder import JobBuilder
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.util import make_artifact_name_safe


def str_of_length(n):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


def make_proto_settings(**kwargs):
    proto = wandb_settings_pb2.Settings()
    for k, v in kwargs.items():
        if isinstance(v, bool):
            getattr(proto, k).CopyFrom(BoolValue(value=v))
        elif isinstance(v, str):
            getattr(proto, k).CopyFrom(StringValue(value=v))
    return proto


def test_build_repo_job(runner):
    remote_name = str_of_length(129)
    metadata = {
        "git": {"remote": remote_name, "commit": "testtestcommit"},
        "codePath": "blah/test.py",
        "args": ["--test", "test"],
        "python": "3.7",
    }
    with runner.isolated_filesystem():
        with open("requirements.txt", "w") as f:
            f.write("numpy==1.19.0")
            f.write("wandb")
        with open("wandb-metadata.json", "w") as f:
            f.write(json.dumps(metadata))

        settings = SettingsStatic(
            make_proto_settings(
                **{"files_dir": "./", "disable_job_creation": False, "_jupyter": False}
            )
        )
        job_builder = JobBuilder(settings)
        artifact = job_builder.build()
        assert artifact is not None
        assert artifact.name == make_artifact_name_safe(
            f"job-{remote_name}_blah_test.py"
        )
        assert artifact.type == "job"
        assert artifact._manifest.entries["wandb-job.json"]
        assert artifact._manifest.entries["requirements.frozen.txt"]


def test_build_repo_notebook_job(runner, tmp_path, mocker):
    remote_name = str_of_length(129)
    metadata = {
        "git": {"remote": remote_name, "commit": "testtestcommit"},
        "program": "blah/test.ipynb",
        "args": ["--test", "test"],
        "python": "3.7",
        "root": "test",
    }

    orig_os_path_exists = os.path.exists

    def exists(path):
        if "test.ipynb" in path:
            return True
        return orig_os_path_exists(path)

    mocker.patch("os.path.exists", side_effect=exists)
    with runner.isolated_filesystem():
        with open("requirements.txt", "w") as f:
            f.write("numpy==1.19.0")
            f.write("wandb")
        with open("wandb-metadata.json", "w") as f:
            f.write(json.dumps(metadata))
        settings = SettingsStatic(
            make_proto_settings(
                **{
                    "files_dir": "./",
                    "disable_job_creation": False,
                    "_jupyter": True,
                    "_jupyter_root": str(tmp_path),
                }
            )
        )
        job_builder = JobBuilder(settings)
        artifact = job_builder.build()
        assert artifact is not None
        assert artifact.name == make_artifact_name_safe(
            f"job-{remote_name}_blah_test.ipynb"
        )
        assert artifact.type == "job"
        assert artifact._manifest.entries["wandb-job.json"]
        assert artifact._manifest.entries["requirements.frozen.txt"]
        assert job_builder._is_notebook_run() is True


def test_build_artifact_job(runner):
    metadata = {
        "codePath": "blah/test.py",
        "args": ["--test", "test"],
        "python": "3.7",
    }
    artifact_name = str_of_length(129)
    with runner.isolated_filesystem():
        with open("requirements.txt", "w") as f:
            f.write("numpy==1.19.0")
            f.write("wandb")
        with open("wandb-metadata.json", "w") as f:
            f.write(json.dumps(metadata))
        settings = SettingsStatic(
            make_proto_settings(
                **{"files_dir": "./", "disable_job_creation": False, "_jupyter": False}
            )
        )
        job_builder = JobBuilder(settings)
        job_builder._logged_code_artifact = {
            "id": "testtest",
            "name": artifact_name,
        }
        artifact = job_builder.build()
        assert artifact is not None
        assert artifact.name == make_artifact_name_safe(f"job-{artifact_name}")
        assert artifact.type == "job"
        assert artifact._manifest.entries["wandb-job.json"]
        assert artifact._manifest.entries["requirements.frozen.txt"]


def test_build_artifact_notebook_job(runner, tmp_path, mocker):
    metadata = {
        "program": "blah/test.ipynb",
        "args": ["--test", "test"],
        "python": "3.7",
    }
    artifact_name = str_of_length(129)
    orig_os_path_exists = os.path.exists

    def exists(path):
        if "test.ipynb" in path:
            return True
        return orig_os_path_exists(path)

    mocker.patch("os.path.exists", side_effect=exists)
    with runner.isolated_filesystem():
        with open("requirements.txt", "w") as f:
            f.write("numpy==1.19.0")
            f.write("wandb")
        with open("wandb-metadata.json", "w") as f:
            f.write(json.dumps(metadata))
        settings = SettingsStatic(
            make_proto_settings(
                **{
                    "files_dir": "./",
                    "disable_job_creation": False,
                    "_jupyter": True,
                    "_jupyter_root": str(tmp_path),
                }
            )
        )
        job_builder = JobBuilder(settings)
        job_builder._logged_code_artifact = {
            "id": "testtest",
            "name": artifact_name,
        }
        artifact = job_builder.build()
        assert artifact is not None
        assert artifact.name == make_artifact_name_safe(f"job-{artifact_name}")
        assert artifact.type == "job"
        assert artifact._manifest.entries["wandb-job.json"]
        assert artifact._manifest.entries["requirements.frozen.txt"]
        assert job_builder._is_notebook_run() is True


def test_build_image_job(runner):
    image_name = str_of_length(129)
    metadata = {
        "program": "blah/test.py",
        "args": ["--test", "test"],
        "python": "3.7",
        "docker": image_name,
    }
    with runner.isolated_filesystem():
        with open("requirements.txt", "w") as f:
            f.write("numpy==1.19.0")
            f.write("wandb")
        with open("wandb-metadata.json", "w") as f:
            f.write(json.dumps(metadata))
        settings = SettingsStatic(
            make_proto_settings(
                **{"files_dir": "./", "disable_job_creation": False, "_jupyter": False}
            )
        )
        job_builder = JobBuilder(settings)
        artifact = job_builder.build()
        assert artifact is not None
        assert artifact.name == make_artifact_name_safe(f"job-{image_name}")
        assert artifact.type == "job"
        assert artifact._manifest.entries["wandb-job.json"]
        assert artifact._manifest.entries["requirements.frozen.txt"]


def test_set_disabled():
    settings = SettingsStatic(
        make_proto_settings(**{"files_dir": "./", "disable_job_creation": False})
    )

    job_builder = JobBuilder(settings)
    job_builder.disable = "testtest"
    assert job_builder.disable == "testtest"


def test_no_metadata_file():
    settings = SettingsStatic(
        make_proto_settings(**{"files_dir": "./", "disable_job_creation": False})
    )
    job_builder = JobBuilder(settings)
    artifact = job_builder.build()
    assert artifact is None
