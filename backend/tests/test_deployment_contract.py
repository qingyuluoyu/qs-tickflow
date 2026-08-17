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
