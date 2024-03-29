import unittest

from antelope import comp_dir
from antelope_core.entities.tests import BasicEntityTest
from ..entities.fragment_editor import create_fragment
from ..terminations import FlowTermination


class FlowTerminationTestCase(BasicEntityTest):
    """
    Mainly want to test initialization (for process ref and flow [context]), enumeration of "unobserved exchanges",
    and LCIA
    """
    '''
    _qdb = None

    @property
    def qdb(self):
        if self._qdb is None:
            self._qdb = Qdb()
            q = next(self.A.search('quantity', Name='coolness'))
            qi = self.A.make_interface('quantity')
            for cf in qi.factors(q):
                self._qdb.add_cf(cf)
        return self._qdb
    '''

    def _petro_frag(self):
        rx = next(x for x in self.petro.references() if x.flow['Name'].startswith('Diesel'))
        return create_fragment(rx.flow, rx.direction, origin='test.termination')

    def _petro_term(self):
        """
        NOTE: this term will have a phony / proxy background implementation, since we don't have a true catalog query
        :return:
        """
        frag = self._petro_frag()
        return frag.terminate(self.petro.make_ref(self.A.query), term_flow=frag.flow)

    def test_create_term(self):
        frag = self._petro_frag()
        term = FlowTermination(frag, self.petro, term_flow=frag.flow)
        self.assertIs(frag.flow, term.term_flow)
        self.assertEqual(comp_dir(frag.direction), term.direction)
        self.assertTrue(term.is_process)
        self.assertFalse(term.is_null)
        self.assertFalse(term.is_null)
        self.assertFalse(term.is_subfrag)
        self.assertTrue(term.is_bg)  # bg now means "no child flows"
        self.assertFalse(term.term_is_bg)

    def test_unobserved(self):
        term = self._petro_term()
        ux = [x for x in term._unobserved_exchanges()]
        self.assertEqual(len(ux), 42)

    def _frag_with_child(self):
        frag = self._petro_frag()
        frag.terminate(self.petro.make_ref(self.A.query), term_flow=frag.flow)
        lead = next(x for x in self.petro.inventory(frag.flow) if x.flow['Name'].startswith('Lead'))
        c = create_fragment(flow=lead.flow, direction=lead.direction, parent=frag, value=lead.value)
        c.terminate(self.A.tm[lead.flow.context])
        return frag

    def test_unobserved_with_child(self):
        frag = self._frag_with_child()
        ux = [x for x in frag.term._unobserved_exchanges()]
        self.assertEqual(len(ux), 41)

    def _get_coolness(self):
        q = next(self.A.search('quantity', Name='coolness'))
        return q.make_ref(self.A.query)

    def test_lcia(self):
        term = self._petro_term()
        q = self._get_coolness()
        res = term.compute_unit_score(q)
        self.assertAlmostEqual(res.total(), 0.00013695)

    def test_lcia_with_child(self):
        frag = self._frag_with_child()
        q = self._get_coolness()
        res = frag.term.compute_unit_score(q)
        self.assertAlmostEqual(res.total(), 0.00012425)

    def test_fg(self):
        frag = self._frag_with_child()
        z = next(frag.child_flows)
        self.assertFalse(z.term.is_fg)
        self.assertTrue(z.term.is_context)
        self.assertIs(z.flow, z.term.term_flow)
        self.assertEqual(z.direction, comp_dir(z.term.direction))

    def test_fg_lcia(self):
        frag = self._frag_with_child()
        z = next(frag.child_flows)
        q = self._get_coolness()
        res = z.term.compute_unit_score(q)
        self.assertEqual(res.total(), q.cf(z.flow))

    def test_traversal(self):
        c = self._frag_with_child()
        c.observe(accept_all=True)  # fragment_lcia only operates on observed exchanges
        q = self._get_coolness()
        res1 = q.do_lcia(self.petro.inventory(c.flow))
        res2 = c.fragment_lcia(q)
        self.assertAlmostEqual(res1.total(), res2.total(), places=15)

if __name__ == '__main__':
    unittest.main()
