import unittest
import os
from shutil import rmtree

from ..foreground_catalog import ForegroundCatalog

WORKING_DIR = os.path.join(os.path.dirname(__file__), 'test-foreground')
test_ref = 'test.foreground'


class FgImplementationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = ForegroundCatalog(WORKING_DIR)
        cls.fg = cls.cat.create_foreground(ref=test_ref)

    def test_new_flow(self):
        f = self.fg.new_flow('Test flow', 'mass')
        ar = self.cat.get_archive(self.fg.origin)
        self.assertIs(ar[f.external_ref], f)
        self.assertEqual(self.fg.get(f.external_ref), f)

    @unittest.skip('Disabled frag method for now as inside baseball')
    def test_frag(self):
        f = self.fg.new_flow('a silly flow', 'number of items')
        frag = self.fg.new_fragment(f, 'Output')
        self.assertIs(self.fg.frag(frag.uuid[:3]), frag)  ##

    def test_named_frag(self):
        f = self.fg.new_flow('a reference flow')
        frag_name = 'a stupendous fragment'
        frag = self.fg.new_fragment(f, 'Output', external_ref=frag_name)
        self.assertIs(self.fg.get(frag_name), frag)
        self.assertIs(self.fg.get(frag.uuid), frag)
        with self.assertRaises(ValueError):
            self.fg.new_fragment(f, 'Output', external_ref=frag_name)

    @classmethod
    def tearDownClass(cls):
        rmtree(WORKING_DIR)


if __name__ == '__main__':
    unittest.main()
