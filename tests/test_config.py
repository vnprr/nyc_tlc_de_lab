import pytest

from src import config


def test_aws_steps_require_explicit_bucket(monkeypatch):
    monkeypatch.setattr(config, "BUCKET", None)

    with pytest.raises(RuntimeError, match="NYC_LAKE_BUCKET"):
        config.require_bucket()
