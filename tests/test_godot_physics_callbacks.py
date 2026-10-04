"""Healthy controls precede individually broken collider callback mutations."""
from __future__ import annotations

import unittest

from _support import cli_json, make_tree

RULE = 'godot.collider_write_in_physics_signal'
HEALTHY = (
    'extends Area2D\n'
    '@onready var collider: CollisionShape2D = $CollisionShape2D\n'
    'func _ready():\n\tbody_entered.connect(on_contact)\n'
    'func on_contact(body):\n\tresize.call_deferred()\n'
    'func resize():\n\tcollider.shape = shape\n'
)


class PhysicsCallbackTests(unittest.TestCase):
    def test_healthy_then_individual_regressions(self):
        def scan(source):
            with make_tree({'src/area.gd': source}) as tmp:
                return cli_json(tmp, '--check', RULE, '--strict')
        code, report = scan(HEALTHY)
        self.assertEqual(code, 0)
        self.assertEqual(report['results'][0]['status'], 'pass')
        mutations = (
            HEALTHY.replace('resize.call_deferred()', 'resize()'),
            HEALTHY.replace('resize.call_deferred()', 'collider.shape = shape'),
            HEALTHY.replace('resize.call_deferred()', 'collider.disabled = true'),
        )
        for source in mutations:
            with self.subTest(source=source):
                code, report = scan(source)
                self.assertEqual(code, 1)
                findings = report['results'][0]['findings']
                self.assertEqual(len(findings), 1)
                expected_line = 8 if 'resize()\n' in source else 6
                self.assertEqual(findings[0]['line'], expected_line)

    def test_comment_prefix_and_3d_counterprobe(self):
        healthy = HEALTHY.replace('Area2D', 'Area3D').replace('CollisionShape2D', 'CollisionShape3D')
        healthy = '# note\n' * 30 + healthy
        with make_tree({'src/area.gd': healthy}) as tmp:
            code, _ = cli_json(tmp, '--check', RULE, '--strict')
            self.assertEqual(code, 0)
        broken = healthy.replace('resize.call_deferred()', 'resize()')
        with make_tree({'src/area.gd': broken}) as tmp:
            code, report = cli_json(tmp, '--check', RULE, '--strict')
            self.assertEqual(code, 1)
            self.assertEqual(report['results'][0]['findings'][0]['line'], 38)


if __name__ == '__main__':
    unittest.main()
