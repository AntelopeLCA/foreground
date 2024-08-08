"""
I forget how to work this

Basically we want to create a foreground with a few interfaces:
"""

from ..foreground_catalog import ForegroundCatalog
from antelope_core.entities.tests.base_testclass import refinery_archive
from ..terminations import FlowConversionError
from antelope_core.characterizations import DuplicateCharacterizationError

import unittest


class TestFlowConversions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cat = ForegroundCatalog.make_tester()
        cat.new_resource('test.refinery', refinery_archive, 'json', interfaces=('basic', 'index',
                                                                                'exchange', 'quantity',
                                                                                'background'),
                         config={'hints': [['context', 'air', 'to air'],
                                           ['context', 'water', 'to water']]})
        cat.create_foreground('my.main')
        cat.create_foreground('my.alt')

        cat.foreground('my.main').new_flow('Massive flow A', 'mass')

        cls.cat = cat

    @property
    def mass(self):
        return self.cat.get_canonical('mass')

    @property
    def volume(self):
        return self.cat.get_canonical('volume')

    @property
    def gasoline(self):
        return next(self.cat.query('test.refinery').flows(name='gasoline'))

    @property
    def ncv(self):
        return self.cat.get_canonical('net calorific value')

    @property
    def main(self):
        return self.cat.foreground('my.main')

    @property
    def alt(self):
        return self.cat.foreground('my.alt')

    @classmethod
    def tearDownClass(cls) -> None:
        cls.cat.__del__()

    def test_gasoline_flow(self):
        self.assertEqual(self.gasoline.cf(self.mass), 750.0)

    def test_mass_to_gasoline(self):
        """
        This tests the use of the remote qdb to access flow properties
        :return:
        """
        p = next(self.gasoline.targets())
        a = self.main.new_flow('Massive flow A', self.mass)
        f = self.main.new_fragment(a, 'Output', exchange_value=1.0)
        f.terminate(p, term_flow=self.gasoline)
        self.assertEqual(f.term.flow_conversion * 750.0, 1.0)

    def test_anchor_flow(self):
        """
        Just a straight up test of above using fragments
        :return:
        """
        p = next(self.gasoline.targets())
        f_0 = self.main.new_fragment(self.gasoline, 'Output', observe=True, termination=p)
        z = self.alt.new_flow('Massive Flow Z', 'mass')
        f_z = self.alt.new_fragment(z, 'Output', observe=True, termination=f_0)
        self.assertEqual(f_z.term.flow_conversion * 750.0, 1.0)

    def test_volume_to_gasoline(self):
        """
        This tests the identity hit
        :return:
        """
        p = next(self.gasoline.targets())
        b = self.main.new_flow('Volume flow B', self.volume)
        f = self.main.new_fragment(b, 'Output', exchange_value=1.0)
        f.terminate(p, term_flow=self.gasoline)
        self.assertEqual(f.term.flow_conversion, 1.0)

    def test_fg_conv_gasoline(self):
        """
        This tests the use of the local qdb to access ad hoc characterizations of remote flows
        :return:
        """
        p = next(self.gasoline.targets())
        e = self.main.new_flow('Energetic flow E', self.ncv)
        self.gasoline.characterize(e.reference_entity, 32250.0)
        f = self.main.new_fragment(e, 'Output', exchange_value=1.0)
        f.terminate(p, term_flow=self.gasoline)
        self.assertEqual(f.term.flow_conversion * 32250.0, 1.0)

    def test_fg_conv_direct(self):
        """
        This tests the use of local qdb to characterize local flows
        :return:
        """
        p = next(self.gasoline.targets())
        g = self.main.new_flow('Massive fuel flow', self.mass)
        g.characterize(self.volume, 0.00122)
        f = self.main.new_fragment(g, 'Output', exchange_value=1.0)
        f.terminate(p, term_flow=self.gasoline)
        self.assertEqual(f.term.flow_conversion, 0.00122)

    def test_intermediate_context(self):
        """
        This tests whether we can use anchor-specific CFs
        :return:
        """
        e = self.main.new_flow('Energetic flow E', self.ncv)
        f_e = self.main.new_fragment(e, 'Output', observe=True)
        h = self.alt.new_flow('Fuel flow H', 'mass')
        f_h = self.alt.new_fragment(h, 'Output', observe=True)

        f_h.terminate(f_e)
        with self.assertRaises(FlowConversionError):
            f_h.traverse()

        h.characterize(self.ncv, 123.0)

        f_h.traverse()
        self.assertEqual(f_h.term.flow_conversion, 123.0)

        """ # we don't actually raise DuplicateCharacterizationError- we catch it and IGNORE it. possibly unwise.
        with self.assertRaises(DuplicateCharacterizationError):
            h.characterize(self.ncv, 126.0)
        """
        h.characterize(self.ncv, 125.0)
        self.assertEqual(f_h.term.flow_conversion, 123.0)  # test that 125 was ignored

        h.characterize(self.ncv, 126.0, context=(f_e.origin, f_e.external_ref))
        self.assertEqual(f_h.term.flow_conversion, 126.0)  # test that 126 was accepted


if __name__ == '__main__':
    unittest.main()
