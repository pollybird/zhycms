"""v3.3.0 信创适配：openAMDC 编排与镜像文件测试。

运行态识别（INFO 解析、healthz、后台展示）由
``tests/test_redis_backend_v330.py`` 覆盖；本文件只校验 M4 交付的
compose profile、镜像构建文件与基线配置，防止后续改动误删信创入口。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


class TestComposeProfile:
    def test_default_compose_has_openamdc_service(self):
        text = _read('docker-compose.yml')
        assert '\n  openamdc:\n' in text
        assert 'profiles: ["openamdc"]' in text
        assert '\n  openamdc_data:\n' in text

    def test_default_compose_uses_openamdc_cli_healthcheck(self):
        text = _read('docker-compose.yml')
        assert '"CMD", "openamdc-cli", "ping"' in text
        assert 'pollybird/openamdc:1.0.0' in text

    def test_opengauss_compose_has_openamdc_profile(self):
        text = _read('docker-compose.opengauss.yml')
        assert '\n  openamdc:\n' in text
        assert 'profiles: ["openamdc"]' in text
        assert '\n  openamdc_data:\n' in text


class TestImageFiles:
    def test_dockerfile_pins_commit_and_drops_privileges(self):
        text = _read('docker/openamdc/Dockerfile')
        assert '6758505d722a7efa0fd64dec5164e19885942f87' in text
        assert 'USER 999' in text
        assert 'openamdc-server' in text
        assert 'openamdc-cli' in text

    def test_dockerfile_healthcheck_uses_cli(self):
        text = _read('docker/openamdc/Dockerfile')
        assert 'HEALTHCHECK' in text
        assert 'openamdc-cli -p 6379 ping' in text

    def test_baseline_config_and_entrypoint(self):
        conf = _read('docker/openamdc/openamdc.conf')
        entry = _read('docker/openamdc/entrypoint.sh')
        assert 'worker-threads 4' in conf
        assert 'swap-enabled no' in conf
        assert 'maxmemory-policy allkeys-lru' in conf
        assert 'exec openamdc-server' in entry
