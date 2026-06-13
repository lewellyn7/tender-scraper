"""P0-3 safety_guard 单测

测试场景:
1. dev + self → pass
2. dev + team → pass
3. staging + team → pass
4. production + team → pass
5. production + self → raise RuntimeError
6. 未设置 env → 默认 development → pass
7. is_production() 便捷函数
8. get_deployment_mode() 便捷函数
"""
import os
import sys
from unittest import mock

import pytest

# 把项目根加入 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.safety_guard import check_production_safety, is_production, get_deployment_mode


class TestCheckProductionSafety:
    """check_production_safety() 行为测试"""

    def test_dev_self_passes(self, monkeypatch, capsys):
        """dev + self 应该通过（self 仅在 production 被禁）"""
        monkeypatch.setenv("ENV", "development")
        monkeypatch.setenv("DEPLOYMENT_MODE", "self")
        check_production_safety()  # 不抛异常
        # 无 stdout 输出（除非 VERBOSE）
        captured = capsys.readouterr()
        assert "BLOCKED" not in captured.err

    def test_dev_team_passes(self, monkeypatch):
        """dev + team 默认模式，应该通过"""
        monkeypatch.setenv("ENV", "development")
        monkeypatch.delenv("DEPLOYMENT_MODE", raising=False)
        check_production_safety()  # 不抛异常

    def test_staging_team_passes(self, monkeypatch):
        """staging + team 应该通过"""
        monkeypatch.setenv("ENV", "staging")
        monkeypatch.setenv("DEPLOYMENT_MODE", "team")
        check_production_safety()  # 不抛异常

    def test_production_team_passes(self, monkeypatch):
        """production + team (推荐配置) 应该通过"""
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("DEPLOYMENT_MODE", "team")
        check_production_safety()  # 不抛异常

    def test_production_self_raises(self, monkeypatch, capsys):
        """production + self 应该抛 RuntimeError"""
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("DEPLOYMENT_MODE", "self")
        with pytest.raises(RuntimeError, match="forbidden in production"):
            check_production_safety()
        # 错误信息应包含原因
        captured = capsys.readouterr()
        assert "BLOCKED" in captured.err
        assert "DEPLOYMENT_MODE=self" in captured.err

    def test_production_self_case_insensitive(self, monkeypatch):
        """大写 SELF 也应该被拦截"""
        monkeypatch.setenv("ENV", "PRODUCTION")
        monkeypatch.setenv("DEPLOYMENT_MODE", "SELF")
        with pytest.raises(RuntimeError):
            check_production_safety()

    def test_no_env_defaults_to_development(self, monkeypatch):
        """未设 ENV 时默认 development + 通过"""
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.setenv("DEPLOYMENT_MODE", "self")
        check_production_safety()  # 不抛

    def test_unknown_env_warns_but_passes(self, monkeypatch, capsys):
        """未知 ENV 值应该警告但不阻塞（避免误伤 dev 实验）"""
        monkeypatch.setenv("ENV", "experimental")
        monkeypatch.setenv("DEPLOYMENT_MODE", "team")
        check_production_safety()
        captured = capsys.readouterr()
        assert "Unknown" in captured.err

    def test_unknown_mode_warns_but_passes(self, monkeypatch, capsys):
        """未知 DEPLOYMENT_MODE 值应该警告但不阻塞"""
        monkeypatch.setenv("ENV", "development")
        monkeypatch.setenv("DEPLOYMENT_MODE", "weird-mode")
        check_production_safety()
        captured = capsys.readouterr()
        assert "Unknown" in captured.err

    def test_verbose_mode_prints_ok(self, monkeypatch, capsys):
        """SAFETY_GUARD_VERBOSE=1 时打印 OK"""
        monkeypatch.setenv("ENV", "development")
        monkeypatch.setenv("DEPLOYMENT_MODE", "team")
        monkeypatch.setenv("SAFETY_GUARD_VERBOSE", "1")
        check_production_safety()
        captured = capsys.readouterr()
        assert "passed" in captured.err


class TestIsProduction:
    """is_production() 便捷判断"""

    def test_true(self, monkeypatch):
        monkeypatch.setenv("ENV", "production")
        assert is_production() is True

    def test_false_dev(self, monkeypatch):
        monkeypatch.setenv("ENV", "development")
        assert is_production() is False

    def test_false_default(self, monkeypatch):
        monkeypatch.delenv("ENV", raising=False)
        assert is_production() is False  # 默认 development

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("ENV", "PRODUCTION")
        assert is_production() is True


class TestGetDeploymentMode:
    """get_deployment_mode() 便捷获取"""

    def test_self(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_MODE", "self")
        assert get_deployment_mode() == "self"

    def test_team(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_MODE", "team")
        assert get_deployment_mode() == "team"

    def test_default_team(self, monkeypatch):
        monkeypatch.delenv("DEPLOYMENT_MODE", raising=False)
        assert get_deployment_mode() == "team"  # 默认

    def test_unknown_value(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_MODE", "weird")
        assert get_deployment_mode() == "unknown"

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_MODE", "SELF")
        assert get_deployment_mode() == "self"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
