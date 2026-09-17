"""Static release-boundary checks for the production Compose contract."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_container_dependency_install_is_lockfile_strict() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "pnpm install --frozen-lockfile || pnpm install" not in dockerfile
    assert 'uv sync --frozen "$@" || uv sync "$@"' not in dockerfile
    assert "npm ci || npm install" not in dockerfile
    assert "pnpm@9\n" not in dockerfile
    assert 'uv==${UV_VERSION}' in dockerfile


def test_compose_healthcheck_uses_readiness_endpoint() -> None:
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "healthcheck:" in compose
    assert "/api/health" in compose


def test_compose_binds_application_port_to_loopback_and_supports_a_release_tag() -> None:
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "image: ${IMAGE_TAG:-tickflow-stock-panel:dev}" in compose
    assert '"127.0.0.1:${PORT:-3018}:3018"' in compose


def test_docker_build_keeps_runtime_secrets_out_of_the_build_context() -> None:
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert ".env" in dockerignore.splitlines()
    assert "data" in dockerignore.splitlines()
