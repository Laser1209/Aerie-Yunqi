"""v13.0 Phase 0 — Persona Hub 单元测试"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from core.persona_hub.persona_manager import PersonaManager
from core.persona_hub.persona_validator import PersonaValidator


VALID_PERSONA = {
    "id": "test_persona",
    "name": "测试人设",
    "version": "1.0.0",
    "basic": {
        "name": "测试",
        "english_name": "Test",
        "age": 25,
        "product_name": "Test Product",
    },
    "personality": {
        "cores": [{"name": "温柔", "en": "Gentleness", "desc": "..."}],
        "speech_style": "温柔大方",
    },
    "relationship": {
        "user_address_default": "你",
        "self_reference": "我",
    },
    "emotion": {
        "baseline": {"pleasure": 0.1, "arousal": 0.2, "dominance": 0.8},
        "thresholds": {
            "patience": {"label": "忍耐", "threshold": 100, "initial_value": 50}
        },
    },
    "behavior": {
        "proactivity_level": 0.75,
        "default_permission_level": "VIEW_ONLY",
    },
}


class TestPersonaValidator(unittest.TestCase):
    def test_valid_persona_passes(self):
        ok, errors = PersonaValidator.validate(VALID_PERSONA)
        self.assertTrue(ok, f"Expected valid, got errors: {errors}")
        self.assertEqual(len(errors), 0)

    def test_missing_required_field_fails(self):
        bad = dict(VALID_PERSONA)
        del bad["basic"]
        ok, errors = PersonaValidator.validate(bad)
        self.assertFalse(ok)
        self.assertTrue(any("basic" in e for e in errors))

    def test_invalid_id_format_fails(self):
        bad = dict(VALID_PERSONA)
        bad["id"] = "INVALID ID!"
        ok, errors = PersonaValidator.validate(bad)
        self.assertFalse(ok)
        self.assertTrue(any("id" in e.lower() for e in errors))

    def test_invalid_pleasure_range_fails(self):
        bad = json.loads(json.dumps(VALID_PERSONA))
        bad["emotion"]["baseline"]["pleasure"] = 2.0
        ok, errors = PersonaValidator.validate(bad)
        self.assertFalse(ok)
        self.assertTrue(any("pleasure" in e for e in errors))

    def test_invalid_permission_level_fails(self):
        bad = json.loads(json.dumps(VALID_PERSONA))
        bad["behavior"]["default_permission_level"] = "INVALID"
        ok, errors = PersonaValidator.validate(bad)
        self.assertFalse(ok)
        self.assertTrue(any("permission" in e for e in errors))

    def test_proactivity_out_of_range_fails(self):
        bad = json.loads(json.dumps(VALID_PERSONA))
        bad["behavior"]["proactivity_level"] = 1.5
        ok, errors = PersonaValidator.validate(bad)
        self.assertFalse(ok)
        self.assertTrue(any("proactivity" in e for e in errors))


class TestPersonaManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = PersonaManager(data_dir=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_default_persona_exists(self):
        personas = self.mgr.list_personas()
        self.assertTrue(len(personas) >= 1)
        ids = [p["id"] for p in personas]
        self.assertIn("yita_default", ids)

    def test_get_active_is_default(self):
        self.assertEqual(self.mgr.get_active_id(), "yita_default")

    def test_get_name_default(self):
        self.assertEqual(self.mgr.get_name(), "伊塔")

    def test_get_english_name_default(self):
        self.assertEqual(self.mgr.get_english_name(), "Ita")

    def test_create_persona(self):
        ok, pid = self.mgr.create_persona(json.loads(json.dumps(VALID_PERSONA)))
        self.assertTrue(ok, f"Create failed: {pid}")
        self.assertEqual(pid, "test_persona")

        personas = self.mgr.list_personas()
        ids = [p["id"] for p in personas]
        self.assertIn("test_persona", ids)

    def test_create_duplicate_fails(self):
        self.mgr.create_persona(json.loads(json.dumps(VALID_PERSONA)))
        ok, msg = self.mgr.create_persona(json.loads(json.dumps(VALID_PERSONA)))
        self.assertFalse(ok)
        self.assertIn("已存在", msg)

    def test_update_persona(self):
        self.mgr.create_persona(json.loads(json.dumps(VALID_PERSONA)))
        ok, pid = self.mgr.update_persona(
            "test_persona", {"basic": {"name": "新名字"}}
        )
        self.assertTrue(ok)
        p = self.mgr.get_persona("test_persona")
        self.assertEqual(p["basic"]["name"], "新名字")

    def test_update_nonexistent_fails(self):
        ok, msg = self.mgr.update_persona("nonexistent", {"basic": {"name": "x"}})
        self.assertFalse(ok)
        self.assertIn("不存在", msg)

    def test_delete_persona(self):
        self.mgr.create_persona(json.loads(json.dumps(VALID_PERSONA)))
        ok, msg = self.mgr.delete_persona("test_persona")
        self.assertTrue(ok, msg)
        personas = self.mgr.list_personas()
        ids = [p["id"] for p in personas]
        self.assertNotIn("test_persona", ids)

    def test_delete_builtin_fails(self):
        ok, msg = self.mgr.delete_persona("yita_default")
        self.assertFalse(ok)
        self.assertIn("不可删除", msg)

    def test_delete_active_falls_back_to_default(self):
        self.mgr.create_persona(json.loads(json.dumps(VALID_PERSONA)))
        self.mgr.switch_persona("test_persona")
        self.assertEqual(self.mgr.get_active_id(), "test_persona")
        self.mgr.delete_persona("test_persona")
        self.assertEqual(self.mgr.get_active_id(), "yita_default")

    def test_switch_persona(self):
        self.mgr.create_persona(json.loads(json.dumps(VALID_PERSONA)))
        ok, pid = self.mgr.switch_persona("test_persona")
        self.assertTrue(ok)
        self.assertEqual(self.mgr.get_active_id(), "test_persona")
        self.assertEqual(self.mgr.get_name(), "测试")

    def test_switch_nonexistent_fails(self):
        ok, msg = self.mgr.switch_persona("nonexistent")
        self.assertFalse(ok)
        self.assertIn("不存在", msg)

    def test_get_emotion_baseline(self):
        baseline = self.mgr.get_emotion_baseline()
        self.assertIn("pleasure", baseline)
        self.assertIn("arousal", baseline)
        self.assertIn("dominance", baseline)
        self.assertAlmostEqual(baseline["pleasure"], 0.1, places=2)

    def test_get_emotion_thresholds(self):
        thresholds = self.mgr.get_emotion_thresholds()
        self.assertIn("patience", thresholds)
        self.assertIn("anxiety", thresholds)
        self.assertIn("desire", thresholds)

    def test_get_proactivity_level(self):
        level = self.mgr.get_proactivity_level()
        self.assertGreaterEqual(level, 0)
        self.assertLessEqual(level, 1)

    def test_get_default_permission_level(self):
        perm = self.mgr.get_default_permission_level()
        self.assertIn(perm, ("VIEW_ONLY", "STANDARD", "FULL"))

    def test_export_persona(self):
        data = self.mgr.export_persona("yita_default")
        self.assertIsNotNone(data)
        self.assertIn("basic", data)
        self.assertNotIn("is_builtin", data)  # 导出时移除内置标记

    def test_export_nonexistent_returns_none(self):
        data = self.mgr.export_persona("nonexistent")
        self.assertIsNone(data)

    def test_persistence(self):
        """验证重启后数据保留。"""
        self.mgr.create_persona(json.loads(json.dumps(VALID_PERSONA)))
        self.mgr.switch_persona("test_persona")

        # 新建一个实例，应该读到相同数据
        mgr2 = PersonaManager(data_dir=self.tmpdir)
        self.assertEqual(mgr2.get_active_id(), "test_persona")
        personas = mgr2.list_personas()
        ids = [p["id"] for p in personas]
        self.assertIn("test_persona", ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
