import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'football-immersive-game'

def module(name):
    spec = importlib.util.spec_from_file_location(name, SKILL / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

validator = module('validate_story')
initializer = module('init_project')

class StoryTests(unittest.TestCase):
    def setUp(self):
        self.story = json.loads((SKILL / 'assets/templates/story.json').read_text(encoding='utf-8'))

    def test_valid_example(self):
        self.assertEqual(validator.validate(self.story), ([], []))

    def test_missing_target(self):
        self.story['nodes'][0]['next'] = 'missing'
        self.assertTrue(any('missing target' in e for e in validator.validate(self.story)[0]))

    def test_duplicate_id(self):
        self.story['nodes'].append(copy.deepcopy(self.story['nodes'][0]))
        self.assertTrue(any('Duplicate node' in e for e in validator.validate(self.story)[0]))

    def test_unreachable(self):
        self.story['nodes'].append({'id':'orphan','type':'ending','text':'x'})
        self.assertIn('Unreachable node: orphan', validator.validate(self.story)[0])

    def test_cycle_without_exit(self):
        self.story['nodes'][2]['next'] = 'stay_scene'
        errors, warnings = validator.validate(self.story)
        self.assertIn('No path to an ending from: stay_scene', errors)
        self.assertTrue(warnings)

    def test_cycle_with_exit_warns(self):
        self.story['nodes'][2]['next'] = 'decision'
        self.story['nodes'] = [n for n in self.story['nodes'] if n['id'] != 'stay_ending']
        errors, warnings = validator.validate(self.story)
        self.assertFalse(errors)
        self.assertTrue(warnings)

    def test_duplicate_options_and_bad_effect(self):
        opts = self.story['nodes'][1]['options']
        opts[1]['id'] = opts[0]['id']
        opts[0]['effects'] = {'trust':True}
        errors, _ = validator.validate(self.story)
        self.assertTrue(any('duplicate option' in e for e in errors))
        self.assertTrue(any('finite numbers' in e for e in errors))

    def test_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.story['assets'] = [{'id':'photo','path':'photo.txt'}]
            self.story['nodes'][0]['assetIds'] = ['photo']
            self.assertTrue(validator.validate(self.story, root)[0])
            (root/'photo.txt').write_text('placeholder')
            self.assertFalse(validator.validate(self.story, root)[0])
            self.story['assets'][0]['path'] = '../outside.txt'
            self.assertTrue(validator.validate(self.story, root)[0])

    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'project'
            root.mkdir()
            outside = Path(directory)/'outside.txt'
            outside.write_text('x')
            try:
                (root/'link.txt').symlink_to(outside)
            except OSError:
                self.skipTest('Symlinks unavailable')
            self.story['assets'] = [{'id':'image','path':'link.txt'}]
            self.assertTrue(any('escapes' in e for e in validator.validate(self.story, root)[0]))

    def test_malformed_values_do_not_crash(self):
        cases = [None, [], {}, {'nodes':[None]}, {'schemaVersion':1,'nodes':[{'id':'x','type':{},'text':3}], 'start':[]}]
        for data in cases:
            with self.subTest(data=data):
                self.assertTrue(validator.validate(data)[0])

    def test_huge_integer_returns_error(self):
        self.story['nodes'][1]['options'][0]['effects'] = {'score': 10**400}
        errors, _ = validator.validate(self.story)
        self.assertTrue(any('safe range' in e for e in errors))
        self.story['nodes'][1]['options'][0]['effects'] = {'score': 2**53 - 1}
        self.assertFalse(validator.validate(self.story)[0])

    def test_symlink_loop_returns_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            try:
                (root/'loop').symlink_to('loop')
            except OSError:
                self.skipTest('Symlinks unavailable')
            self.story['assets'] = [{'id': 'loop', 'path': 'loop'}]
            errors, _ = validator.validate(self.story, root)
            self.assertTrue(any('resolve asset' in e for e in errors))
            errors, _ = validator.validate(self.story, root/'loop')
            self.assertTrue(any('project root' in e for e in errors))

    def test_missing_root_returns_error(self):
        with tempfile.TemporaryDirectory() as directory:
            errors, _ = validator.validate(self.story, Path(directory)/'missing')
            self.assertTrue(any('not a directory' in e for e in errors))

    def test_long_story(self):
        data = {'schemaVersion':1,'start':'0','nodes':[
            {'id':str(i),'type':'scene','text':'x','next':str(i+1)} for i in range(2500)]}
        data['nodes'].append({'id':'2500','type':'ending','text':'done'})
        self.assertEqual(validator.validate(data), ([], []))

class InitTests(unittest.TestCase):
    def test_cli_default_is_open(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'open-project'
            result = subprocess.run([sys.executable, str(SKILL/'scripts/init_project.py'), str(target)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual({p.name for p in (target/'design').iterdir()}, {'brief.md', 'decisions.md', 'playtest.md'})
            self.assertFalse((target/'game').exists())

    def test_modes_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode in ('open','narrative','career','hybrid'):
                target = Path(directory)/mode
                initializer.create_project(target, mode)
                self.assertTrue((target/'design/brief.md').is_file())
                self.assertEqual((target/'game/story.json').exists(), mode in ('narrative','hybrid'))
                self.assertEqual((target/'design/career-model.md').exists(), mode in ('career','hybrid'))
                before = (target/'README.md').read_bytes()
                with self.assertRaises(FileExistsError):
                    initializer.create_project(target, mode)
                self.assertEqual((target/'README.md').read_bytes(), before)

if __name__ == '__main__':
    unittest.main()
